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

MODEL = os.environ.get("KALKAN_MODEL", "gemma4")
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


def health(timeout: float = 2) -> dict:
    """Ollama açık mı ve model yüklü mü?"""
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=timeout)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        ok = any(n == MODEL or n.split(":")[0] == MODEL for n in names)
        return {"llm": ok, "model": MODEL, "models": names}
    except Exception:
        return {"llm": False, "model": MODEL, "models": []}


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
    if not text.strip() or not available():
        return None
    try:
        r = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": MODEL,
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
    return _ground(text, items)


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
