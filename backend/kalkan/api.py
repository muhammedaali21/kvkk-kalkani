"""FastAPI uç noktaları + OpenAI uyumlu proxy.

Çalıştırma (backend klasöründe): uvicorn kalkan.api:app --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import llm
from .engine import Engine
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


class UnmaskIn(BaseModel):
    text: str
    session: str = "default"


class SozlukIn(BaseModel):
    terimler: list[str]


@app.get("/health")
def health() -> dict:
    h = llm.health(timeout=1)
    return {"ok": True, "llm": h["llm"], "model": h["model"]}


@app.post("/mask")
def mask(body: MaskIn) -> dict:
    return engine.mask(body.text, session=body.session, use_llm=body.use_llm)


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
) -> Response:
    session = session or f"dosya-{uuid.uuid4().hex[:8]}"
    data = await file.read()
    try:
        content, media, report = mask_file(engine, file.filename or "", data, session, use_llm)
    except ValueError as e:
        raise HTTPException(400, str(e))
    stem, _, ext = (file.filename or "dosya.txt").rpartition(".")
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
def demo_page() -> FileResponse:
    return FileResponse(DEMO_DIR / "index.html")


@app.get("/panel")
def panel_page() -> FileResponse:
    return FileResponse(DEMO_DIR / "panel.html")


def _ascii(s: str) -> str:
    table = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    return "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "_" for c in s.translate(table))
