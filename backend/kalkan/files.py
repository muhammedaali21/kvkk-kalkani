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

from . import llm
from .engine import LLM_CAPABLE, PRIORITY, Engine
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
    # Başlık hem Türkçe ("İsim" → "isim") hem İngilizce kurallarla ("IBAN" → "iban") küçültülür.
    variants = (tr_lower(str(header)), str(header).lower())
    for pattern, typ in HEADER_HINTS:
        if any(re.search(pattern, h) for h in variants):
            return typ
    return None


def mask_dataframe(engine: Engine, df: pd.DataFrame, session: str,
                   use_llm: bool = False, types: set[str] | None = None) -> tuple[pd.DataFrame, dict]:
    vault = engine.vault(session)
    counts: Counter[str] = Counter()
    # Filtre dışındaki bir türün sütunu otomatik gizlenmez; hücreleri normal taramadan geçer.
    hints = {col: h if (h := column_hint(col)) and (types is None or h in types) else None for col in df.columns}
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
                r = engine.mask(text, session=session, use_llm=use_llm, record=False, types=types)
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
              use_llm: bool = False, types: list[str] | None = None) -> tuple[bytes, str, dict]:
    """Dosyayı maskeler. (içerik, medya türü, rapor) döner. types yoksa şirket politikası geçerlidir."""
    allowed = engine.allowed_types(types)
    if not allowed & LLM_CAPABLE:
        use_llm = False
    ext = PurePath(filename).suffix.lower()
    if ext == ".csv":
        text = _decode(data)
        sep = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, sep=sep)
        masked, report = mask_dataframe(engine, df, session, use_llm, allowed)
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
                masked, rep = mask_dataframe(engine, df, session, use_llm, allowed)
                masked.to_excel(writer, sheet_name=name, index=False)
                report["sayfalar"][name] = rep
                total.update(rep["bulgular"])
        report["bulgular"], report["toplam"] = dict(total), int(sum(total.values()))
        content = buf.getvalue()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif ext in (".txt", ".md", ""):
        r = engine.mask(_decode(data), session=session, use_llm=use_llm, record=False, types=allowed)
        report = {"bulgular": r["counts"], "toplam": sum(r["counts"].values())}
        content, media = r["masked"].encode("utf-8"), "text/plain; charset=utf-8"
    elif ext == ".docx":
        content, report = mask_docx(engine, data, session, use_llm, allowed)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif ext == ".pdf":
        content, report = mask_pdf(engine, data, session, use_llm, allowed)
        media = "application/pdf"
    elif ext == ".doc":
        raise ValueError("Eski Word biçimi (.doc) desteklenmiyor. Dosyayı Word'de .docx olarak kaydedip tekrar yükleyin.")
    else:
        raise ValueError(f"Desteklenmeyen dosya türü: {ext or '(yok)'}. CSV, XLSX, DOCX, PDF veya TXT yükleyin.")
    report["filtre_disi"] = sorted(set(PRIORITY) - allowed)
    engine.stats.record(report["bulgular"], llm_used=use_llm, file=True)
    return content, media, report


# ---------------------------------------------------------------------------
# Word (.docx)
# ---------------------------------------------------------------------------

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# Kullanıcı metni taşıyan parçalar: gövde, üst/alt bilgi, dipnot, sonnot, yorum.
_DOCX_TEXT_PARTS = ("document.main", "header", "footer", "footnotes", "endnotes", "comments")


def _docx_text_roots(doc):
    """(parça, kök XML öğesi) çiftleri. Ayrıştırılmamış parçalar blob'dan okunur."""
    from lxml import etree

    for part in doc.part.package.iter_parts():
        ct = getattr(part, "content_type", "")
        if "wordprocessingml" not in ct or not any(k in ct for k in _DOCX_TEXT_PARTS):
            continue
        root = getattr(part, "_element", None)
        if root is None:
            root = etree.fromstring(part.blob)
            yield part, root, True
        else:
            yield part, root, False


def _docx_paragraph_nodes(root):
    """Her paragraf için metin düğümleri (w:t, w:delText). Bağlantılar, izlenen değişiklikler ve
    metin kutuları dahildir; iç içe paragrafların düğümleri yalnızca kendi paragraflarına sayılır."""
    for p in root.iter(f"{_W}p"):
        nodes = [
            t for t in p.iter(f"{_W}t", f"{_W}delText")
            if next(t.iterancestors(f"{_W}p"), None) is p
        ]
        if nodes:
            yield nodes


def _replace_in_nodes(nodes, start: int, end: int, tag: str) -> None:
    bounds, pos = [], 0
    for n in nodes:
        length = len(n.text or "")
        bounds.append((pos, pos + length))
        pos += length
    i = next(k for k, (a, b) in enumerate(bounds) if a <= start < b)
    j = next(k for k, (a, b) in enumerate(bounds) if a < end <= b)
    ti, tj = nodes[i].text or "", nodes[j].text or ""
    if i == j:
        a = bounds[i][0]
        nodes[i].text = ti[: start - a] + tag + ti[end - a:]
    else:
        nodes[i].text = ti[: start - bounds[i][0]] + tag
        for k in range(i + 1, j):
            nodes[k].text = ""
        nodes[j].text = tj[end - bounds[j][0]:]
    # Baştaki/sondaki boşluklar Word'de korunmalı.
    for n in (nodes[i], nodes[j]):
        n.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


def mask_docx(engine: Engine, data: bytes, session: str, use_llm: bool,
              types: set[str] | None = None) -> tuple[bytes, dict]:
    import docx
    from lxml import etree

    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception:
        raise ValueError("Word dosyası açılamadı. Dosya bozuk veya parola korumalı olabilir.")

    roots = list(_docx_text_roots(doc))
    paragraphs = [(nodes, "".join(n.text or "" for n in nodes))
                  for _, root, _ in roots for nodes in _docx_paragraph_nodes(root)]
    phrases = llm.collect_phrases("\n".join(t for _, t in paragraphs)) if use_llm else None

    counts: Counter[str] = Counter()
    values: set[str] = set()
    for nodes, text in paragraphs:
        if not text.strip():
            continue
        r = engine.mask(text, session=session, use_llm=False, record=False, phrases=phrases, types=types)
        counts.update(r["counts"])
        for f in reversed(r["findings"]):
            _replace_in_nodes(nodes, f["start"], f["end"], f["tag"])
            values.add(f["value"])

    for part, root, from_blob in roots:
        if from_blob:
            part._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        # Bağlantı hedefleri (mailto:, tel: veya gizlenen bir değer içeren adresler).
        for rel in part.rels.values():
            if rel.is_external and rel.reltype.endswith("/hyperlink"):
                target = rel.target_ref
                if target.lower().startswith(("mailto:", "tel:")) or any(v in target for v in values):
                    rel._target = "#gizlendi"

    # Belge bilgileri de kişisel veri taşır.
    props = doc.core_properties
    props.author = props.last_modified_by = ""
    props.comments = ""

    buf = io.BytesIO()
    doc.save(buf)

    # Doğrulama: kaydedilen dosyada gizlenen değerlerden biri hâlâ okunabiliyor mu?
    saved = docx.Document(io.BytesIO(buf.getvalue()))
    remaining_text = "\n".join("".join(n.text or "" for n in nodes)
                               for _, root, _ in _docx_text_roots(saved)
                               for nodes in _docx_paragraph_nodes(root))
    leaked = [v for v in values if v in remaining_text]
    report = {"paragraf": sum(1 for _, t in paragraphs if t.strip()), "bulgular": dict(counts),
              "toplam": int(sum(counts.values())), "kalan": len(leaked)}
    return buf.getvalue(), report


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def mask_pdf(engine: Engine, data: bytes, session: str, use_llm: bool,
             types: set[str] | None = None) -> tuple[bytes, dict]:
    """Gerçek karartma: gizlenen metin PDF'ten silinir, yerine etiket yazılır.

    Sadece üstüne kutu çizmek yetmez; alttaki metin seçilip kopyalanabilir ve yapay zekâ onu okur.
    """
    import pymupdf

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise ValueError("PDF açılamadı. Dosya bozuk olabilir.")
    if doc.needs_pass:
        raise ValueError("Parola korumalı PDF'ler işlenemez. Parolayı kaldırıp tekrar yükleyin.")

    texts = [page.get_text() for page in doc]
    if not any(t.strip() for t in texts):
        raise ValueError("PDF'te seçilebilir metin yok; taranmış (görüntü) bir belge olabilir. "
                         "Bu sürüm yalnızca metin içeren PDF'leri karartır.")
    phrases = llm.collect_phrases("\n".join(texts)) if use_llm else None

    counts: Counter[str] = Counter()
    values: set[str] = set()
    ink, white = (0.106, 0.106, 0.102), (1, 1, 1)
    for page, text in zip(doc, texts):
        r = engine.mask(text, session=session, use_llm=False, record=False, phrases=phrases, types=types)
        counts.update(r["counts"])
        seen: set[str] = set()
        for f in r["findings"]:
            if f["value"] in seen:
                continue  # search_for sayfadaki tüm geçişleri zaten bulur
            seen.add(f["value"])
            values.add(f["value"])
            # Tam eşleşmelerin her biri etiket alır.
            labelled = [(rect, f["tag"]) for rect in page.search_for(f["value"])]
            if not labelled:
                # Satır sonunda bölünmüş değer: parçaları ayrı ayrı ara (fazla karartmak, sızdırmaktan iyidir).
                pieces = [rect for piece in f["value"].split() if len(piece) >= 2 for rect in page.search_for(piece)]
                labelled = [(rect, f["tag"] if k == 0 else "") for k, rect in enumerate(pieces)]
            for rect, label in labelled:
                # Courier'de karakter genişliği ~0,6 × punto; etiket kutuya sığacak en büyük boyutta yazılır.
                size = max(4.0, min(rect.height * 0.75, rect.width / (max(1, len(label)) * 0.62))) if label else 6
                page.add_redact_annot(rect, text=label, fontname="cour", fontsize=size,
                                      fill=ink, text_color=white, align=pymupdf.TEXT_ALIGN_CENTER)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)

    doc.set_metadata({})  # yazar, başlık vb. belge bilgilerini temizle
    content = doc.tobytes(garbage=3, deflate=True)

    # Doğrulama: karartılmış dosyada gizlenen değerlerden biri hâlâ okunabiliyor mu?
    check = pymupdf.open(stream=content, filetype="pdf")
    remaining_text = "\n".join(p.get_text() for p in check)
    leaked = sorted(v for v in values if v in remaining_text)
    report = {"sayfa": len(texts), "bulgular": dict(counts), "toplam": int(sum(counts.values())),
              "kalan": len(leaked)}
    return content, report


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
