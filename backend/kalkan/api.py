"""FastAPI uç noktaları + OpenAI uyumlu proxy.

Çalıştırma (backend klasöründe): uvicorn kalkan.api:app --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import llm
from .engine import PRIORITY, SPECIAL_CATEGORIES, Engine, normalize
from .files import mask_file

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "backend" / "data"
DEMO_DIR = ROOT / "demo"
UPSTREAM = os.environ.get("KALKAN_UPSTREAM", "https://api.openai.com/v1").rstrip("/")

engine = Engine(DATA_DIR)
app = FastAPI(title="KVKK Kalkanı", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    expose_headers=["X-Kalkan-Report", "X-Kalkan-Session"],
)

LOCALHOST = {"127.0.0.1", "::1", "localhost"}


class MaskIn(BaseModel):
    text: str
    session: str = "default"
    use_llm: bool = True
    # Gizlenecek veri türleri; verilmezse şirket politikası (/politika) geçerlidir.
    types: list[str] | None = None


class UnmaskIn(BaseModel):
    text: str
    session: str = "default"


class SozlukIn(BaseModel):
    terimler: list[str]


class PolitikaIn(BaseModel):
    turler: list[str]


@app.get("/health")
def health() -> dict:
    h = llm.health(timeout=1)
    return {"ok": True, "llm": h["llm"], "model": h["model"]}


@app.post("/mask")
def mask(body: MaskIn) -> dict:
    return engine.mask(body.text, session=body.session, use_llm=body.use_llm, types=body.types)


@app.post("/unmask")
def unmask(body: UnmaskIn) -> dict:
    return {"text": engine.unmask(body.text, body.session)}


@app.get("/mapping/{session}")
def mapping(session: str, request: Request) -> dict:
    # Gerçek değerler sadece bu makineden istenebilir.
    if not request.client or request.client.host not in LOCALHOST:
        raise HTTPException(403, "Eşleme tablosu sadece localhost'tan okunabilir.")
    return engine.mapping(session)


@app.post("/reset/{session}")
def reset(session: str) -> dict:
    return {"silindi": engine.reset(session)}


@app.post("/mask-file")
async def mask_file_endpoint(
    file: UploadFile = File(...),
    session: str = Form(default=""),
    use_llm: bool = Form(default=False),
    types: str | None = Form(default=None),  # virgülle ayrılmış; verilmezse şirket politikası
) -> Response:
    session = session or f"dosya-{uuid.uuid4().hex[:8]}"
    data = await file.read()
    try:
        content, media, report = mask_file(engine, file.filename or "", data, session, use_llm, _types(types))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _file_response(file.filename or "dosya.txt", content, media, report, session)


# ---------------------------------------------------------------------------
# İki adımlı dosya akışı: önce incele, sonra kullanıcının seçtiklerini gizle.
# Dosya yalnızca bu süreçte, bellekte ve kısa süre tutulur; diske yazılmaz.
# ---------------------------------------------------------------------------

_FILE_TTL = 30 * 60
_FILE_MAX = 20
_pending: dict[str, dict] = {}
_pending_lock = threading.Lock()


def _prune_pending() -> None:
    now = time.time()
    with _pending_lock:
        for fid in [f for f, e in _pending.items() if now - e["zaman"] > _FILE_TTL]:
            del _pending[fid]
        for fid in sorted(_pending, key=lambda f: _pending[f]["zaman"])[:-_FILE_MAX]:
            del _pending[fid]


@app.post("/analyze-file")
async def analyze_file(
    file: UploadFile = File(...),
    use_llm: bool = Form(default=False),
    types: str | None = Form(default=None),
) -> dict:
    """Dosyayı değiştirmeden tarar; gizlenebilecek değerleri türe göre listeler."""
    t0 = time.perf_counter()
    name, data = file.filename or "", await file.read()
    found: list[tuple[str, str]] = []
    phrase_cache: dict = {}
    scratch = f"analiz-{uuid.uuid4().hex[:8]}"
    try:
        _, _, report = mask_file(engine, name, data, scratch, use_llm, _types(types),
                                 found=found, phrase_cache=phrase_cache, record=False)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        engine.reset(scratch)  # analiz oturumunun eşleme tablosu tutulmaz

    items: dict[str, dict] = {}
    for typ, value in found:
        key = f"{typ}|{normalize(typ, value)}"
        if key not in items:
            items[key] = {"key": key, "type": typ, "value": value, "count": 0,
                          "special": typ in SPECIAL_CATEGORIES}
        items[key]["count"] += 1

    _prune_pending()
    file_id = uuid.uuid4().hex
    with _pending_lock:
        _pending[file_id] = {"ad": name, "veri": data, "use_llm": use_llm, "ifadeler": phrase_cache,
                             "zaman": time.time()}
    report.pop("bulgular", None)
    return {"file_id": file_id, "dosya": name, "rapor": report, "bulgular": list(items.values()),
            "toplam": len(found), "ms": round((time.perf_counter() - t0) * 1000)}


class SelectionIn(BaseModel):
    keys: list[str]  # /analyze-file yanıtındaki "key" değerleri
    session: str = "default"


@app.post("/mask-file/{file_id}")
def mask_selected(file_id: str, body: SelectionIn) -> Response:
    """İncelenen dosyada yalnızca seçilen değerleri gizler."""
    _prune_pending()
    with _pending_lock:
        entry = _pending.get(file_id)
    if entry is None:
        raise HTTPException(404, "Dosyanın inceleme süresi doldu. Lütfen dosyayı tekrar yükleyin.")
    only = {(t, v) for t, _, v in (k.partition("|") for k in body.keys) if t in PRIORITY}
    content, media, report = mask_file(engine, entry["ad"], entry["veri"], body.session, entry["use_llm"],
                                       sorted({t for t, _ in only}), only=only,
                                       phrase_cache=entry["ifadeler"])
    return _file_response(entry["ad"] or "dosya.txt", content, media, report, body.session)


def _types(types: str | None) -> list[str] | None:
    """Virgülle ayrılmış tür listesi; verilmezse (None) şirket politikası geçerlidir."""
    return None if types is None else [t.strip() for t in types.split(",") if t.strip()]


def _file_response(filename: str, content: bytes, media: str, report: dict, session: str) -> Response:
    stem, _, ext = filename.rpartition(".")
    return Response(
        content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{_ascii(stem or ext)}-maskeli.{ext}"',
            # ensure_ascii: HTTP başlıkları ASCII olmalı.
            "X-Kalkan-Report": json.dumps(report, ensure_ascii=True),
            "X-Kalkan-Session": session,
        },
    )


@app.get("/stats")
def stats() -> dict:
    return engine.stats.snapshot()


@app.get("/sozluk")
def get_sozluk() -> dict:
    return {"terimler": engine.sozluk.terms}


@app.put("/sozluk")
def put_sozluk(body: SozlukIn) -> dict:
    return {"terimler": engine.sozluk.set(body.terimler)}


@app.get("/politika")
def get_politika() -> dict:
    return {"turler": engine.policy.types, "tum_turler": list(PRIORITY)}


@app.put("/politika")
def put_politika(body: PolitikaIn) -> dict:
    return {"turler": engine.policy.set(body.turler), "tum_turler": list(PRIORITY)}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    """OpenAI uyumlu proxy: maskele → KALKAN_UPSTREAM'e ilet → cevabı geri çevir. (stream yok)"""
    body = await request.json()
    session = request.headers.get("x-kalkan-session", "proxy")
    use_llm = request.headers.get("x-kalkan-llm", "1") != "0"
    found = 0
    for msg in body.get("messages", []):
        content = msg.get("content")
        if isinstance(content, str):
            r = engine.mask(content, session=session, use_llm=use_llm)
            msg["content"], found = r["masked"], found + len(r["findings"])
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    r = engine.mask(part.get("text", ""), session=session, use_llm=use_llm)
                    part["text"], found = r["masked"], found + len(r["findings"])
    body["stream"] = False

    headers = {"Content-Type": "application/json"}
    auth = request.headers.get("authorization") or (
        f"Bearer {os.environ['KALKAN_UPSTREAM_KEY']}" if os.environ.get("KALKAN_UPSTREAM_KEY") else None
    )
    if auth:
        headers["Authorization"] = auth
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            up = await client.post(f"{UPSTREAM}/chat/completions", json=body, headers=headers)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Upstream'e ulaşılamadı: {e}")
    try:
        data = up.json()
    except ValueError:
        raise HTTPException(502, f"Upstream geçersiz cevap döndü ({up.status_code}).")
    for choice in data.get("choices", []) if isinstance(data, dict) else []:
        message = choice.get("message") or {}
        if isinstance(message.get("content"), str):
            message["content"] = engine.unmask(message["content"], session)
    return JSONResponse(
        data, status_code=up.status_code,
        headers={"X-Kalkan-Session": session, "X-Kalkan-Report": json.dumps({"toplam": found})},
    )


@app.get("/")
def landing_page() -> FileResponse:
    return FileResponse(DEMO_DIR / "landing.html")


@app.get("/uygulama")
def demo_page() -> FileResponse:
    return FileResponse(DEMO_DIR / "index.html")


@app.get("/panel")
def panel_page() -> FileResponse:
    return FileResponse(DEMO_DIR / "panel.html")


# İlk arayüzün yedeği (geri dönmek gerekirse).
@app.get("/eski")
def old_demo_page() -> FileResponse:
    return FileResponse(DEMO_DIR / "v1" / "index.html")


@app.get("/eski/panel")
def old_panel_page() -> FileResponse:
    return FileResponse(DEMO_DIR / "v1" / "panel.html")


def _ascii(s: str) -> str:
    table = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    return "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "_" for c in s.translate(table))
