"""Excel/CSV/TXT maskeleme.

Aynı değer dosya boyunca aynı etiketi alır; böylece gruplama, sayma, pivot gibi analizler bozulmaz.
Sayısal sütunlar (tutar, adet) desenlere uymadığı için olduğu gibi kalır.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from pathlib import PurePath

import pandas as pd

from .engine import Engine
from .names import tr_lower

# Sütun başlığı bu kalıplara uyuyorsa hücrenin tamamı ilgili türle maskelenir.
HEADER_HINTS: list[tuple[str, str]] = [
    (r"\b(tc|tckn|kimlik)\b", "TC"),
    (r"\biban\b", "IBAN"),
    (r"(e-?posta|e-?mail|\bmail\b)", "EPOSTA"),
    (r"(telefon|\btel\b|gsm|cep)", "TELEFON"),
    (r"adres", "ADRES"),
    (r"(ad[ıi]? ?soyad|isim|\bad\b|\badı\b|soyad|müşteri ad|personel ad|çalışan ad)", "KISI"),
]


def column_hint(header: str) -> str | None:
    h = tr_lower(str(header))
    for pattern, typ in HEADER_HINTS:
        if re.search(pattern, h):
            return typ
    return None


def mask_dataframe(engine: Engine, df: pd.DataFrame, session: str,
                   use_llm: bool = False) -> tuple[pd.DataFrame, dict]:
    vault = engine.vault(session)
    counts: Counter[str] = Counter()
    hints = {col: column_hint(col) for col in df.columns}
    cache: dict[str, str] = {}
    out = df.copy()
    for col in df.columns:
        hint = hints[col]
        values = []
        for cell in df[col]:
            text = "" if cell is None else str(cell)
            if not text.strip():
                values.append(text)
                continue
            if hint:
                with engine.lock:
                    values.append(vault.tag_for(hint, text.strip()))
                counts[hint] += 1
                continue
            if text not in cache:
                r = engine.mask(text, session=session, use_llm=use_llm, record=False)
                cache[text] = r["masked"]
                counts.update(r["counts"])
            elif cache[text] != text:
                # Önbellekten gelen hücre de bir bulgu sayılır.
                counts.update(re.findall(r"\[([A-Z][A-Z_]*)_\d+\]", cache[text]))
            values.append(cache[text])
        out[col] = values
    report = {
        "satir": int(len(df)),
        "sutun": int(len(df.columns)),
        "sutun_ipuclari": {str(c): h for c, h in hints.items() if h},
        "bulgular": dict(counts),
        "toplam": int(sum(counts.values())),
    }
    return out, report


def mask_file(engine: Engine, filename: str, data: bytes, session: str,
              use_llm: bool = False) -> tuple[bytes, str, dict]:
    """Dosyayı maskeler. (içerik, medya türü, rapor) döner."""
    ext = PurePath(filename).suffix.lower()
    if ext == ".csv":
        text = _decode(data)
        sep = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, sep=sep)
        masked, report = mask_dataframe(engine, df, session, use_llm)
        buf = io.StringIO()
        masked.to_csv(buf, index=False, sep=sep)
        content, media = buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8"
    elif ext in (".xlsx", ".xlsm"):
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str, keep_default_na=False)
        buf = io.BytesIO()
        report = {"sayfalar": {}, "bulgular": {}, "toplam": 0}
        total: Counter[str] = Counter()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            for name, df in sheets.items():
                masked, rep = mask_dataframe(engine, df, session, use_llm)
                masked.to_excel(writer, sheet_name=name, index=False)
                report["sayfalar"][name] = rep
                total.update(rep["bulgular"])
        report["bulgular"], report["toplam"] = dict(total), int(sum(total.values()))
        content = buf.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif ext in (".txt", ".md", ""):
        r = engine.mask(_decode(data), session=session, use_llm=use_llm, record=False)
        report = {"bulgular": r["counts"], "toplam": sum(r["counts"].values())}
        content, media = r["masked"].encode("utf-8"), "text/plain; charset=utf-8"
    else:
        raise ValueError(f"Desteklenmeyen dosya türü: {ext or '(yok)'} — CSV, XLSX veya TXT yükleyin.")
    engine.stats.record(report["bulgular"], llm_used=use_llm, file=True)
    return content, media, report


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
