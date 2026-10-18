"""Katman 2: Gemma 4 ile bağlamsal tespit (Ollama, tamamen local).

Ollama kapalıysa veya model yoksa sessizce boş döner; sistem regex katmanıyla devam eder.
"""

from __future__ import annotations

import json
import os
import re
import time

import httpx

from .detectors import Finding

# "auto": kurulu modeller arasından en iyisi seçilir.
#   Metin: Türkçe KVKK için ince ayarlı küçük model (finetune/), yoksa gemma4.
#   Görüntü: gemma4 (e4b); ince ayar yalnızca metinle yapıldığı için görüntüde büyük model daha iyi.
MODEL = os.environ.get("KALKAN_MODEL", "auto")
VISION_MODEL = os.environ.get("KALKAN_VISION_MODEL", "auto")
_TEXT_CANDIDATES = ("kalkan-gemma4-e2b", "gemma4")
_VISION_CANDIDATES = ("gemma4", "kalkan-gemma4-e2b")
_installed: list[str] = []
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
TIMEOUT = float(os.environ.get("KALKAN_LLM_TIMEOUT", "60"))

LLM_TYPES = (
    "KISI", "ADRES", "KURUM_KISI", "SAGLIK", "DIN_INANC", "SIYASI",
    "SENDIKA", "CEZA", "BIYOMETRIK", "TICARI_SIR",
)

SYSTEM_PROMPT = """Sen bir KVKK (Kişisel Verilerin Korunması Kanunu) veri tespit aracısın.
Sana verilen Türkçe metinde, bir şirket çalışanının yapay zekâ sohbet aracına yapıştırmaması gereken
hassas ifadeleri bul. Metni ASLA yeniden yazma, sadece ifadeleri listele.

Türler:
- KISI: gerçek kişi adı / soyadı ("Ahmet Yılmaz", "Bayram Aksoy")
- ADRES: açık adres (mahalle, sokak, kapı no, ilçe)
- KURUM_KISI: kişiyi dolaylı olarak tanımlayan ifade ("muhasebedeki tek kadın çalışan", "genel müdürün oğlu")
- SAGLIK: hastalık, tanı, ilaç, engellilik, hamilelik, psikolojik durum ("şeker hastası", "kemoterapi görüyor")
- DIN_INANC: din, mezhep, inanç bilgisi
- SIYASI: siyasi görüş, parti üyeliği
- SENDIKA: sendika üyeliği
- CEZA: sabıka, mahkûmiyet, ceza davası bilgisi
- BIYOMETRIK: parmak izi, yüz tanıma, genetik veri
- TICARI_SIR: maaş tutarı, kâr marjı, gizli indirim oranı, teklif fiyatı, gizli proje/müşteri bilgisi ("kâr marjımız %18")

Kurallar:
- "ifade" alanı metindeki karakter dizisinin BİREBİR kopyası olmalı (büyük/küçük harf ve noktalama dahil).
- İfadeyi olabildiğince kısa tut; tüm cümleyi değil sadece hassas kısmı ver.
- TC kimlik, IBAN, telefon, e-posta gibi numaraları listeleme; onları başka katman yakalıyor.
- Şehir adı, ürün adı, tarih, sipariş numarası hassas değildir.
- Hiçbir şey yoksa boş liste döndür.

Sadece şu JSON'u döndür: {"bulgular": [{"tur": "TUR", "ifade": "metindeki ifade"}]}"""


def _is_installed(name: str) -> bool:
    return any(n == name or n == f"{name}:latest" for n in _installed)


def _pick(preference: str, candidates: tuple[str, ...]) -> str:
    if preference != "auto":
        return preference
    return next((c for c in candidates if _is_installed(c)), candidates[-1])


def text_model() -> str:
    return _pick(MODEL, _TEXT_CANDIDATES)


def vision_model() -> str:
    return _pick(VISION_MODEL, _VISION_CANDIDATES)


def health(timeout: float = 2) -> dict:
    """Ollama açık mı ve seçili model kurulu mu?"""
    global _installed
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=timeout)
        r.raise_for_status()
        _installed = [m.get("name", "") for m in r.json().get("models", [])]
        model = text_model()
        return {"llm": _is_installed(model), "model": model, "vision_model": vision_model(), "models": _installed}
    except Exception:
        return {"llm": False, "model": text_model(), "vision_model": vision_model(), "models": []}


_health_cache: tuple[float, bool] = (0.0, False)


def available() -> bool:
    """Sağlık kontrolünü 15 sn önbellekle (her istekte Ollama'ya sormamak için)."""
    global _health_cache
    now = time.monotonic()
    if now - _health_cache[0] > 15:
        # Kısa zaman aşımı: Ollama kapalıyken mesaj gönderimini geciktirmesin.
        _health_cache = (now, health(timeout=0.5)["llm"])
    return _health_cache[1]


def detect_llm(text: str) -> list[Finding] | None:
    """Gemma'dan bulguları al. Ollama yoksa veya hata olursa None döner."""
    items = _ask(text)
    return None if items is None else _ground(text, items)


def collect_phrases(text: str, chunk_size: int = 3500) -> list[dict] | None:
    """Uzun belgeler için: metni parçalara bölüp Gemma'ya birkaç kez sorar, ham ifade listesini döner.

    Ifadeler daha sonra her paragrafta ayrıca eşlenir (bkz. Engine.detect(phrases=...)); böylece
    yüzlerce paragraf için yüzlerce model çağrısı yapılmaz.
    """
    if not text.strip() or not available():
        return None
    chunks, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) > chunk_size:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current)
    phrases: list[dict] = []
    for chunk in chunks:
        items = _ask(chunk)
        if items is None:
            return None
        phrases += [i for i in items if isinstance(i, dict)]
    return phrases


# Görüntüde model numaraları da okur: OCR bir rakamı yanlış okursa (0/O, 1/l) bu ikinci kaynak olur.
IMAGE_TYPES = LLM_TYPES + ("TC", "IBAN", "TELEFON", "EPOSTA", "KART", "DOGUM_TARIHI")

IMAGE_PROMPT = SYSTEM_PROMPT.replace(
    "- TC kimlik, IBAN, telefon, e-posta gibi numaraları listeleme; onları başka katman yakalıyor.",
    "- Bu bir EKRAN GÖRÜNTÜSÜ. Görüntüdeki metni oku. Ek türler: TC (T.C. kimlik no), IBAN, TELEFON, "
    "EPOSTA, KART (kredi kartı), DOGUM_TARIHI. Bunları da listele.\n"
    "- \"ifade\" alanına görüntüde yazdığı gibi, birebir aynı karakterlerle yaz.",
)


def detect_image(image_png: bytes, timeout: float | None = None) -> list[dict] | None:
    """Gemma 4'e ekran görüntüsünü gösterir; hassas ifadelerin listesini döner (konum değil, metin).

    Konumu OCR belirler; model bağlamı okur. Ollama yoksa veya model görüntü desteklemiyorsa None.
    """
    import base64

    if not available() or not _is_installed(vision_model()):
        return None
    try:
        r = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": vision_model(),
                "stream": False,
                "format": "json",
                "think": False,
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": IMAGE_PROMPT},
                    {"role": "user", "content": "Bu ekran görüntüsündeki hassas ifadeleri listele.",
                     "images": [base64.b64encode(image_png).decode()]},
                ],
            },
            timeout=timeout or TIMEOUT * 2,
        )
        r.raise_for_status()
        items = json.loads(r.json()["message"]["content"]).get("bulgular", [])
    except Exception:
        return None
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            typ = str(item.get("tur", "")).strip().upper()
            phrase = str(item.get("ifade", "")).strip()
            if typ in IMAGE_TYPES and len(phrase) >= 2:
                out.append({"tur": typ, "ifade": phrase})
    return out


def _ask(text: str) -> list | None:
    if not text.strip() or not available():
        return None
    try:
        r = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": text_model(),
                "stream": False,
                "format": "json",
                # Gemma 4 varsayılan olarak önce uzun bir "düşünme" metni üretir; bu iş için gereksiz ve yavaş.
                "think": False,
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        content = r.json()["message"]["content"]
        items = json.loads(content).get("bulgular", [])
    except Exception:
        return None
    return items if isinstance(items, list) else []


def _ground(text: str, items: list) -> list[Finding]:
    """Halüsinasyon koruması: metinde birebir geçmeyen ifadeleri at, geçenlerin tüm konumlarını bul."""
    out: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        typ = str(item.get("tur", "")).strip().upper()
        phrase = str(item.get("ifade", "")).strip()
        if typ not in LLM_TYPES or len(phrase) < 2 or (typ, phrase) in seen:
            continue
        seen.add((typ, phrase))
        for m in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", text):
            out.append(Finding(m.start(), m.end(), typ, phrase, "llm"))
    return out
