"""Ekran görüntüsü karartma.

İş bölümü:
  - Tesseract OCR her kelimenin piksel konumunu verir (dil modellerinin koordinat tahmini güvenilir değildir;
    kutu birkaç piksel kayarsa numaranın yarısı açıkta kalır).
  - Mevcut katmanlar (desen + sağlama, form alanları, isimler, sözlük) OCR metni üzerinde çalışır.
  - Gemma 4 görüntünün kendisine bakar ve bağlamı okur (sağlık bilgisi, ticari bilgi, listede olmayan isim);
    bulduğu ifadeler OCR kelimeleriyle toleranslı biçimde eşleştirilir, kutunun yerini OCR belirler.
  - Sonuç yeniden OCR'dan geçirilir; gizlenen bir değer hâlâ okunabiliyorsa raporlanır.
"""

from __future__ import annotations

import difflib
import io
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import llm
from .detectors import Finding
from .names import tr_lower

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
_NUMERIC = {"TC", "IBAN", "TELEFON", "KART", "VKN", "DOGUM_TARIHI"}


# ---------------------------------------------------------------------------
# Tesseract
# ---------------------------------------------------------------------------

def _tesseract():
    import pytesseract

    exe = shutil.which("tesseract") or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if not Path(exe).exists():
        raise ValueError("Ekran görüntüsü için Tesseract OCR gerekli. Kurulum: winget install UB-Mannheim.TesseractOCR")
    pytesseract.pytesseract.tesseract_cmd = exe
    return pytesseract


# Türkçe dil verisi kullanıcının yazabildiği bir klasörde olabilir (Program Files yönetici izni ister).
# Yol bilerek ASCII seçilir: Tesseract Windows'ta Türkçe karakterli kullanıcı klasörü yollarında sorun çıkarabilir.
_TESSDATA_DIRS = [os.environ.get("KALKAN_TESSDATA", ""), r"C:\ProgramData\Kalkan\tessdata"]


def _ocr_config(pt) -> tuple[str, str]:
    """(dil, ek ayar) döner. Türkçe yoksa İngilizceye düşer (ş, ğ, ı harfleri bozuk okunabilir)."""
    for d in _TESSDATA_DIRS:
        if d and (Path(d) / "tur.traineddata").exists():
            if " " in d:  # pytesseract tırnakları yolun parçası sayar; boşluklu yolda ortam değişkeni kullan
                os.environ["TESSDATA_PREFIX"] = d
                return "tur+eng", ""
            return "tur+eng", f"--tessdata-dir {Path(d).as_posix()}"
    try:
        langs = set(pt.get_languages(config=""))
    except Exception:
        langs = set()
    return ("tur+eng" if "tur" in langs else "eng"), ""


@dataclass
class Word:
    x0: int
    y0: int
    x1: int
    y1: int
    text: str
    start: int = 0  # OCR metnindeki konum
    end: int = 0
    line: int = 0  # görsel satır numarası


def ocr(img: Image.Image) -> tuple[str, list[Word]]:
    """Kelimeleri konumlarıyla okur ve görsel satırlara göre birleştirir."""
    pt = _tesseract()
    # Ekran yazıları küçüktür (~12 px); Tesseract ~30 px yükseklikte en iyi sonucu verir.
    scale = 2 if img.width < 1800 else 1
    work = img.convert("RGB")
    if scale > 1:
        work = work.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    lang, extra = _ocr_config(pt)
    data = pt.image_to_data(work, lang=lang, config=f"--psm 11 {extra}".strip(), output_type=pt.Output.DICT)
    words = []
    for i, t in enumerate(data["text"]):
        t = (t or "").strip()
        if not t or float(data["conf"][i]) < 0:
            continue
        x, y, w, h = (data[k][i] // scale for k in ("left", "top", "width", "height"))
        words.append(Word(x, y, x + max(1, w), y + max(1, h), t))
    if not words:
        return "", []

    # Aynı yükseklikteki kelimeler bir satır; satırlar yukarıdan aşağı, kelimeler soldan sağa.
    words.sort(key=lambda w: ((w.y0 + w.y1) / 2, w.x0))
    lines: list[list[Word]] = []
    for w in words:
        cy, h = (w.y0 + w.y1) / 2, w.y1 - w.y0
        if lines:
            last = lines[-1]
            ly = sum((v.y0 + v.y1) / 2 for v in last) / len(last)
            if abs(cy - ly) <= max(3, h * 0.5):
                last.append(w)
                continue
        lines.append([w])
    parts, pos = [], 0
    for li, line in enumerate(lines):
        line.sort(key=lambda w: w.x0)
        for wi, w in enumerate(line):
            if wi:
                parts.append(" ")
                pos += 1
            w.start, w.end, w.line = pos, pos + len(w.text), li
            parts.append(w.text)
            pos = w.end
        if li < len(lines) - 1:
            parts.append("\n")
            pos += 1
    ordered = [w for line in lines for w in line]
    return "".join(parts), ordered


# ---------------------------------------------------------------------------
# Gemma 4 ifadelerini OCR kelimelerine bağlama (toleranslı)
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^\w@.]", "", tr_lower(s))


def _digits(s: str) -> str:
    # OCR'ın sık karıştırdığı harf/rakam çiftleri
    s = s.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1").replace("S", "5")
    return re.sub(r"\D", "", s)


def ground_phrases(items: list[dict], words: list[Word], text: str) -> list[Finding]:
    """Modelin okuduğu ifadeyi OCR kelime dizisinde bulur. Birebir eşleşme şart değildir:
    sayılarda rakamlar, metinde kelime benzerliği (≥ 0,8) karşılaştırılır."""
    out: list[Finding] = []
    for item in items:
        typ, phrase = item["tur"], item["ifade"]
        tokens = phrase.split()
        best = None
        if typ in _NUMERIC:
            # Pencere yalnızca rakam içeren kelimelerden oluşur ve satır atlamaz; rakamlar birebir tutmalı.
            # OCR'ın tek tük rakam hatası yalnızca uzunluk aynıysa tolere edilir.
            target = _digits(phrase)
            if len(target) < 6:
                continue
            for i in range(len(words)):
                if not _digits(words[i].text):
                    continue
                acc = ""
                for j in range(i, min(i + 8, len(words))):
                    d = _digits(words[j].text)
                    if not d or words[j].line != words[i].line:
                        break
                    acc += d
                    if acc == target or (len(acc) == len(target)
                                         and difflib.SequenceMatcher(None, acc, target).ratio() >= 0.9):
                        best = (i, j)
                        break
                    if len(acc) >= len(target):
                        break
                if best:
                    break
        else:
            n = len(tokens)
            want = [_norm(t) for t in tokens]
            for i in range(len(words) - n + 1):
                if words[i + n - 1].line != words[i].line:
                    continue  # ifade satır atlamaz
                got = [_norm(words[i + k].text) for k in range(n)]
                if all(difflib.SequenceMatcher(None, a, b).ratio() >= 0.8 for a, b in zip(want, got) if a):
                    best = (i, i + n - 1)
                    break
        if best:
            i, j = best
            out.append(Finding(words[i].start, words[j].end, typ, text[words[i].start:words[j].end], "llm"))
    return out


# ---------------------------------------------------------------------------
# Karartma
# ---------------------------------------------------------------------------

def _font(size: int):
    for name in ("consola.ttf", "cour.ttf", "DejaVuSansMono.ttf"):
        for base in (Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts", Path("/usr/share/fonts/truetype/dejavu")):
            p = base / name
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def _boxes_for(finding: dict, words: list[Word]) -> list[tuple[int, int, int, int]]:
    """Bulgunun kapsadığı kelimeleri satır satır birleşik kutulara çevirir."""
    hit = [w for w in words if w.start < finding["end"] and finding["start"] < w.end]
    rows: dict[int, list[Word]] = {}
    for w in hit:
        key = next((k for k in rows if abs(k - (w.y0 + w.y1) // 2) <= max(3, (w.y1 - w.y0) // 2)), (w.y0 + w.y1) // 2)
        rows.setdefault(key, []).append(w)
    return [(min(w.x0 for w in r), min(w.y0 for w in r), max(w.x1 for w in r), max(w.y1 for w in r))
            for r in rows.values()]


def mask_image(engine, data: bytes, job) -> tuple[bytes, dict]:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise ValueError("Görüntü açılamadı. PNG, JPG, WEBP veya BMP yükleyin.")
    img = img.convert("RGB")
    text, words = ocr(img)
    if not text.strip():
        raise ValueError("Görüntüde okunabilir metin bulunamadı.")

    # Kuralların bulduğu konumlar kesindir; Gemma'nın bulguları yalnızca boşlukları doldurur.
    rules, _ = engine.detect(text, use_llm=False, types=job.types)

    # Gemma 4 görüntüye bakar (tür filtresi modelin bulabileceği hiçbir türü içermiyorsa çağrılmaz).
    extra: list[Finding] = []
    vision_used = False
    if job.use_llm and job.types & set(llm.IMAGE_TYPES):
        cache = job.phrase_cache if job.phrase_cache is not None else {}
        if "gorsel" not in cache:
            png = io.BytesIO()
            img.save(png, format="PNG")
            cache["gorsel"] = llm.detect_image(png.getvalue())
        if cache["gorsel"] is not None:
            vision_used = True
            extra = [f for f in ground_phrases(cache["gorsel"], words, text)
                     if not any(f.start < r.end and r.start < f.end for r in rules)]

    r = job.mask(engine, text, use_llm=False, extra=extra)

    # Karart
    pad = 2
    draw = ImageDraw.Draw(img)
    ink, white = (27, 27, 26), (255, 255, 255)
    for f in r["findings"]:
        for k, (x0, y0, x1, y1) in enumerate(_boxes_for(f, words)):
            box = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
            draw.rectangle(box, fill=ink)
            if k == 0:
                label = f["tag"]
                size = max(8, min(int((y1 - y0) * 0.85), int((x1 - x0 + 2 * pad) / max(1, len(label)) / 0.6)))
                font = _font(size)
                tw = draw.textlength(label, font=font)
                if tw <= (x1 - x0) + 2 * pad:
                    draw.text((x0 - pad + ((x1 - x0 + 2 * pad) - tw) / 2, y0 - pad + ((y1 - y0 + 2 * pad) - size) / 2),
                              label, fill=white, font=font)

    out = io.BytesIO()
    img.save(out, format="PNG")

    # Doğrulama: karartılmış görüntüde gizlenen değerlerden biri hâlâ okunabiliyor mu?
    after, _ = ocr(img)
    # Hem gizlenen değerler hem de kuralların orijinalde bulduğu her değer aranır (yanlış eşleşmiş bir
    # bulgu yüzünden bir değerin kenarı açıkta kalmışsa da yakalansın). Kullanıcının bilerek bıraktıkları hariç.
    after_norm, after_digits = _norm(after), _digits(after)
    hidden = [(f["type"], f["value"]) for f in r["findings"]]
    hidden += [(f.type, f.value) for f in rules if job.selected(f.type, f.value)]
    leaked = 0
    for typ, value in set(hidden):
        if typ in _NUMERIC:
            d = _digits(value)
            leaked += len(d) >= 6 and d in after_digits
        else:
            v = _norm(value)
            leaked += len(v) >= 3 and v in after_norm
    report = {"bulgular": r["counts"], "toplam": sum(r["counts"].values()), "kalan": int(leaked),
              "kelime": len(words), "gorsel_model": vision_used, "boyut": [img.width, img.height]}
    return out.getvalue(), report
