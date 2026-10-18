"""Katman 1: regex + algoritmik doğrulama. Katman 1b: Türkçe isim tespiti.

Doğrulamayı geçmeyen sayılar (ör. sipariş no) bilerek maskelenmez.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .names import AMBIGUOUS, FIRST_NAMES, HONORIFICS, NOT_SURNAME, tr_lower


@dataclass
class Finding:
    start: int
    end: int
    type: str
    value: str
    source: str  # regex | isim | sozluk | llm

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Doğrulayıcılar
# ---------------------------------------------------------------------------

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def tc_valid(s: str) -> bool:
    d = [int(c) for c in _digits(s)]
    if len(d) != 11 or d[0] == 0:
        return False
    d10 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    d11 = sum(d[:10]) % 10
    return d[9] == d10 and d[10] == d11


def iban_valid(s: str) -> bool:
    s = re.sub(r"\s", "", s).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    if s.startswith("TR") and len(s) != 26:
        return False
    rearranged = s[4:] + s[:4]
    number = "".join(str(int(c, 36)) for c in rearranged)
    return int(number) % 97 == 1


def vkn_valid(s: str) -> bool:
    d = [int(c) for c in _digits(s)]
    if len(d) != 10:
        return False
    total = 0
    for i in range(1, 10):
        t = (d[i - 1] + 10 - i) % 10
        total += 9 if t == 9 else (t * 2 ** (10 - i)) % 9
    return (10 - total % 10) % 10 == d[9]


def luhn_valid(s: str) -> bool:
    d = [int(c) for c in _digits(s)]
    if not 13 <= len(d) <= 19:
        return False
    total = 0
    for i, x in enumerate(reversed(d)):
        if i % 2 == 1:
            x *= 2
            if x > 9:
                x -= 9
        total += x
    return total % 10 == 0


# ---------------------------------------------------------------------------
# Desenler
# ---------------------------------------------------------------------------

TC_RE = re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)")
IBAN_RE = re.compile(
    r"\bTR\d{2}(?:[ ]?\d{4}){5}[ ]?\d{2}\b"
    r"|\b(?!TR)[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b"
)
CARD_RE = re.compile(
    r"(?<!\d)(?:\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,7}|\d{4}[ -]?\d{6}[ -]?\d{5})(?!\d)"
)
VKN_RE = re.compile(r"(?<!\d)\d{10}(?!\d)")
VKN_CONTEXT_RE = re.compile(r"vergi|vkn", re.IGNORECASE)
PHONE_RE = re.compile(
    r"(?<![\d+])(?P<prefix>(?:\+90|0090)[\s-]?|0)?\(?(?P<area>[2-5]\d{2})\)?"
    r"[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}(?!\d)"
)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PLATE_RE = re.compile(
    r"(?<!\w)(?:0[1-9]|[1-7]\d|8[01])[ ]?(?P<letters>[A-Z]{1,3})[ ]?(?P<num>\d{2,5})(?!\w)"
)

_CAP = r"[A-ZÇĞİÖŞÜ][\wçğıöşü']*"
_KW = (
    r"(?:Mahallesi|Mahalle|Mah\.|Mh\.|Caddesi|Cad\.|Cd\.|Sokağı|Sokak|Sok\.|Sk\."
    r"|Bulvarı|Blv\.|Apartmanı|Apt\.|Sitesi|Köyü)"
)
_NUM = (
    r"(?:No\s*[:.]?\s*\d+[A-Za-z]?(?:/\d+)?|Daire\s*[:.]?\s*\d+|D\s*[:.]\s*\d+"
    r"|Kat\s*[:.]?\s*\d+|\d+/\d+)"
)
ADDRESS_RE = re.compile(
    rf"(?:(?:{_CAP}|\d+\.)\s+){{1,3}}{_KW}(?:[ \t,/]+(?:{_KW}|{_NUM}|{_CAP}|\d+\.(?=\s*{_KW}))){{0,10}}"
)
# Adres eşleşmesinin başına yanlışlıkla takılan kelimeler.
_ADDRESS_LEAD_STOP = ("adres", "ikamet", "sayın", "müşteri", "yeni", "eski", "teslimat")

NAME_TOKEN_RE = re.compile(r"(?<![\w])(?:[A-ZÇĞİÖŞÜ][a-zçğıöşü]+|[A-ZÇĞİÖŞÜ]{2,})(?![\w])")


# ---------------------------------------------------------------------------
# Tespit fonksiyonları
# ---------------------------------------------------------------------------

def _plate_ok(letters: str, num: str) -> bool:
    n = len(letters)
    return (n == 1 and len(num) in (4, 5)) or (n == 2 and len(num) in (3, 4)) or (
        n == 3 and len(num) in (2, 3)
    )


def detect_regex(text: str) -> list[Finding]:
    out: list[Finding] = []

    def add(m: re.Match, typ: str) -> None:
        out.append(Finding(m.start(), m.end(), typ, m.group(0), "regex"))

    for m in TC_RE.finditer(text):
        if tc_valid(m.group(0)):
            add(m, "TC")
    for m in IBAN_RE.finditer(text):
        if iban_valid(m.group(0)):
            add(m, "IBAN")
    for m in CARD_RE.finditer(text):
        if luhn_valid(m.group(0)):
            add(m, "KART")
    for m in VKN_RE.finditer(text):
        if vkn_valid(m.group(0)) and VKN_CONTEXT_RE.search(text[max(0, m.start() - 40): m.start()]):
            add(m, "VKN")
    for m in EMAIL_RE.finditer(text):
        add(m, "EPOSTA")
    for m in PHONE_RE.finditer(text):
        # Ön eki olmayan numarayı sadece cep telefonu (5xx) ise kabul et.
        if m.group("prefix") or m.group("area").startswith("5"):
            add(m, "TELEFON")
    for m in PLATE_RE.finditer(text):
        if _plate_ok(m.group("letters"), m.group("num")):
            add(m, "PLAKA")
    for m in ADDRESS_RE.finditer(text):
        start, value = m.start(), m.group(0)
        # Baştaki "Adresi", "Müşteri" gibi kelimeleri at.
        while True:
            first, _, rest = value.partition(" ")
            if rest and tr_lower(first).startswith(_ADDRESS_LEAD_STOP):
                start += len(first) + 1
                value = rest.lstrip()
                start += len(rest) - len(value)
            else:
                break
        out.append(Finding(start, start + len(value), "ADRES", value, "regex"))
    return out


def detect_names(text: str) -> list[Finding]:
    """Yaygın Türkçe ad + (ikinci ad) + (soyadı). Hitap maskelenmez."""
    tokens = list(NAME_TOKEN_RE.finditer(text))
    out: list[Finding] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        low = tr_lower(tok.group(0))
        if low not in FIRST_NAMES:
            i += 1
            continue

        first_upper = tok.group(0).isupper()

        def adjacent(j: int) -> bool:
            """Sonraki kelime aynı satırda, hemen bitişikte ve aynı yazım biçiminde mi?
            ("YİĞİT\\nBaba Adı" gibi satır atlayan ya da "MAHMUT Sosyal" gibi biçimi tutmayan eşleşmeler reddedilir.)"""
            if j >= len(tokens):
                return False
            gap = text[tokens[j - 1].end(): tokens[j].start()]
            if not gap or not gap.isspace() or "\n" in gap or "\r" in gap or len(gap) > 2:
                return False
            return tokens[j].group(0).isupper() == first_upper

        end_idx = i
        # İkinci ad (ör. "Ayşe Nur").
        if adjacent(end_idx + 1) and tr_lower(tokens[end_idx + 1].group(0)) in FIRST_NAMES:
            end_idx += 1
        has_surname = False
        if adjacent(end_idx + 1):
            nxt = tr_lower(tokens[end_idx + 1].group(0))
            if nxt not in NOT_SURNAME and len(nxt) >= 2:
                end_idx += 1
                has_surname = True
        followed_by_honorific = adjacent(end_idx + 1) and tr_lower(
            tokens[end_idx + 1].group(0)
        ) in HONORIFICS

        if low in AMBIGUOUS and end_idx == i and not followed_by_honorific:
            i += 1
            continue
        if not has_surname and end_idx == i and not followed_by_honorific and tok.group(0).isupper():
            # Tek başına büyük harfli kelime (ör. "CAN") — muhtemelen ad değil.
            i += 1
            continue
        start, end = tok.start(), tokens[end_idx].end()
        out.append(Finding(start, end, "KISI", text[start:end], "isim"))
        i = end_idx + 1
    return out


# ---------------------------------------------------------------------------
# Katman 1e: geliştirici sızıntıları (API anahtarları, şifreler, bağlantı adresleri)
# ---------------------------------------------------------------------------
# Yazılımcılar loglarla, yapılandırma dosyalarıyla ve hata çıktılarıyla birlikte anahtar yapıştırır.
# Bilinen biçimler kesin desenle, genel atamalar ("api_key = ...") bağlamla yakalanır.
_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("GIZLI_ANAHTAR", re.compile(
        r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY(?: BLOCK)?-----[\s\S]+?-----END (?:[A-Z]+ )?PRIVATE KEY(?: BLOCK)?-----")),
    ("GIZLI_ANAHTAR", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),  # JWT
    ("GIZLI_ANAHTAR", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),  # AWS erişim anahtarı
    ("GIZLI_ANAHTAR", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,255}\b|\bgithub_pat_[A-Za-z0-9_]{22,255}\b")),
    ("GIZLI_ANAHTAR", re.compile(r"\bsk-(?:ant-|proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}")),  # OpenAI / Anthropic
    ("GIZLI_ANAHTAR", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),  # Google
    ("GIZLI_ANAHTAR", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b|https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+")),
    ("GIZLI_ANAHTAR", re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,}\b")),  # Stripe
    ("BAGLANTI", re.compile(r"\b[a-z][a-z0-9+.-]{1,20}://[^\s:/@'\"]*:[^\s@/'\"]+@[^\s'\"<>]+", re.I)),
    ("BAGLANTI", re.compile(
        r"(?i)\b(?:Server|Data Source|Host|Endpoint)=[^;\n]+;[^\n]*?(?:Password|Pwd|AccountKey|SharedAccessKey)=[^;\n]+;?[^\s'\"]*")),
]
# Değerin kendisi gizlenir; anahtar adı ("password=") bağlam için kalır.
# Önek: "smtp_password", "DB_PASSWORD", "db.password" gibi adlar; önek ayraçla bitmeli ki "bypass" eşleşmesin.
_PREFIX = r"(?<![\w])(?:[A-Za-z0-9]+[_.-])*"
_SECRET_ASSIGN: list[tuple[str, re.Pattern]] = [
    ("GIZLI_ANAHTAR", re.compile(r"(?i)\bBearer\s+(?P<v>[A-Za-z0-9._~+/-]{20,}=*)")),
    ("SIFRE", re.compile(
        rf"(?i)(?:{_PREFIX}(?:password|passwd|pwd|pass)\b|\b(?:şifre|sifre|parola)(?:si|sı|m|miz|niz|n)?\b)"
        r"[\"']?\s*(?:[:=]|=>)\s*[\"']?(?P<v>[^\s\"',;}]{4,})")),
    ("GIZLI_ANAHTAR", re.compile(
        rf"(?i){_PREFIX}(?:api[_-]?key|apikey|secret(?:[_-]?key)?|client[_-]?secret|access[_-]?token|auth[_-]?token"
        r"|refresh[_-]?token|private[_-]?key|token|secret_access_key)\b[\"']?\s*(?:[:=]|=>)\s*[\"']?"
        r"(?P<v>[A-Za-z0-9_\-./+=]{16,})")),
]


def detect_secrets(text: str) -> list[Finding]:
    out: list[Finding] = []
    for typ, rx in _SECRET_PATTERNS:
        for m in rx.finditer(text):
            out.append(Finding(m.start(), m.end(), typ, m.group(0), "regex"))
    for typ, rx in _SECRET_ASSIGN:
        for m in rx.finditer(text):
            v = m.group("v")
            # Genel atamalarda yer tutucuları ("<token>", "***", "xxxxx", "${VAR}") atla.
            if typ == "GIZLI_ANAHTAR" and not (re.search(r"\d", v) and re.search(r"[A-Za-z]", v)):
                continue
            if re.fullmatch(r"[*x.\-_<>${}]+|(?i:null|none|true|false|undefined|changeme|password)", v):
                continue
            out.append(Finding(m.start("v"), m.end("v"), typ, v, "regex"))
    return out


# ---------------------------------------------------------------------------
# Katman 1d: form alanları ("Etiket : Değer")
# ---------------------------------------------------------------------------
# Resmî yazılarda (SGK, e-Devlet, nüfus, banka formları) değerler etiketle birlikte durur.
# Etiket bilindiği için değer, isim listesinde olmasa ya da doğrulamadan geçmese bile gizlenir.
# Sıra önemlidir: uzun etiketler önce denenir ("Baba Adı" → "Adı"dan önce).
_FORM_FIELDS: list[tuple[str, str]] = [
    (r"T\.?\s*C\.?\s*Kimlik\s*(?:No|Numarası)|T\.?\s*C\.?\s*No|TCKN|Kimlik\s*(?:No|Numarası)", "TC"),
    (r"Ad[ıi]\s*Soyad[ıi]|Ad\s*Soyad|Baba\s*Ad[ıi]|Anne\s*Ad[ıi]|Ana\s*Ad[ıi]|Eşinin\s*Ad[ıi]"
     r"|Kızlık\s*Soyad[ıi]|Önceki\s*Soyad[ıi]|Soyad[ıi]|Soyad|Ad[ıi]|Ad", "KISI"),
    (r"Doğum\s*Tarihi", "DOGUM_TARIHI"),
    (r"Doğum\s*Yeri", "DOGUM_YERI"),
    (r"(?:Cep\s*)?Telefon(?:\s*(?:No|Numarası))?|GSM(?:\s*No)?", "TELEFON"),
    (r"E-?\s?posta(?:\s*Adresi)?|E-?\s?mail", "EPOSTA"),
    (r"(?:İkamet(?:gâh|gah)?\s*|Yerleşim\s*Yeri\s*|Ev\s*|İş\s*)?Adres(?:i)?", "ADRES"),
    (r"IBAN(?:\s*(?:No|Numarası))?", "IBAN"),
    (r"Kan\s*Grubu", "SAGLIK"),
]
_FORM_LABEL = "|".join(f"(?P<f{i}>{p})" for i, (p, _) in enumerate(_FORM_FIELDS))
# Etiket satır başında; ':' aynı satırda ya da (PDF'lerde sık görüldüğü gibi) bir alt satırda olabilir.
FORM_RE = re.compile(
    rf"(?im)^[ \t]*(?:{_FORM_LABEL})[ \t]*\n?[ \t]*:[ \t]*\n?[ \t]*(?P<value>[^\n]{{1,80}}?)[ \t]*$"
)
_ANY_LABEL_RE = re.compile(rf"(?i)^(?:{'|'.join(p for p, _ in _FORM_FIELDS)}|Sayı|Konu|Tarih)\b")


def detect_form_fields(text: str) -> list[Finding]:
    out: list[Finding] = []
    for m in FORM_RE.finditer(text):
        value = m.group("value")
        # Değer boşsa regex bir sonraki satırı (çoğu zaman başka bir etiketi) yakalar; bunu ele.
        if not value.strip(" :.-") or _ANY_LABEL_RE.match(value):
            continue
        typ = next(t for i, (_, t) in enumerate(_FORM_FIELDS) if m.group(f"f{i}"))
        out.append(Finding(m.start("value"), m.end("value"), typ, value, "form"))
    return out


def detect_dictionary(text: str, terms: list[str]) -> list[Finding]:
    """Katman 1c: şirketin ticari sır sözlüğü (büyük/küçük harf duyarsız)."""
    out: list[Finding] = []
    low_text = tr_lower(text)
    for term in terms:
        term = term.strip()
        if not term:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(tr_lower(term))}(?!\w)")
        # tr_lower uzunluğu korur, bu yüzden indeksler orijinal metinle aynıdır.
        for m in pattern.finditer(low_text):
            out.append(Finding(m.start(), m.end(), "SOZLUK", text[m.start(): m.end()], "sozluk"))
    return out
