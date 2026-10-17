"""Katmanları birleştirir: çakışma çözümü, Vault (eşleme), mask/unmask, istatistik, sözlük.

Ham veri yalnızca bu süreçteki Vault belleğinde durur. stats.json'a sadece tür ve sayı yazılır.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter
from datetime import date
from pathlib import Path

from . import llm
from .detectors import Finding, detect_dictionary, detect_names, detect_regex
from .names import tr_lower

PRIORITY = {
    "TC": 100, "IBAN": 100, "KART": 100,
    "VKN": 90, "EPOSTA": 80, "TELEFON": 70, "PLAKA": 60,
    "SOZLUK": 50, "ADRES": 40, "KISI": 30,
    "KURUM_KISI": 20, "SAGLIK": 20, "DIN_INANC": 20, "SIYASI": 20,
    "SENDIKA": 20, "CEZA": 20, "BIYOMETRIK": 20,
    "TICARI_SIR": 10,
}

# KVKK m.6 özel nitelikli kişisel veri türleri (arayüzde kırmızı gösterilir).
SPECIAL_CATEGORIES = {"SAGLIK", "DIN_INANC", "SIYASI", "SENDIKA", "CEZA", "BIYOMETRIK"}

TAG_RE = re.compile(r"\[([A-Z][A-Z_]*_\d+)\]")
_NUMERIC_TYPES = {"TC", "IBAN", "KART", "VKN", "TELEFON"}


def resolve_overlaps(findings: list[Finding]) -> list[Finding]:
    """Önceliği yüksek olan kazanır; eşitlikte uzun olan kazanır."""
    ordered = sorted(
        findings, key=lambda f: (-PRIORITY.get(f.type, 0), -(f.end - f.start), f.start)
    )
    taken: list[Finding] = []
    for f in ordered:
        if f.end <= f.start:
            continue
        if all(f.end <= t.start or f.start >= t.end for t in taken):
            taken.append(f)
    return sorted(taken, key=lambda f: f.start)


def normalize(typ: str, value: str) -> str:
    if typ in _NUMERIC_TYPES:
        digits = re.sub(r"[\s\-()]", "", value).upper()
        if typ == "TELEFON":
            digits = re.sub(r"^(\+90|0090|0)", "", digits)
        return digits
    return " ".join(tr_lower(value).split())


class Vault:
    """Oturum başına (tür, normalize değer) → etiket ve etiket → değer eşlemesi."""

    def __init__(self) -> None:
        self.by_value: dict[tuple[str, str], str] = {}
        self.by_tag: dict[str, str] = {}
        self.counters: Counter[str] = Counter()
        self.touched = time.time()

    def tag_for(self, typ: str, value: str) -> str:
        key = (typ, normalize(typ, value))
        tag = self.by_value.get(key)
        if tag is None:
            self.counters[typ] += 1
            tag = f"[{typ}_{self.counters[typ]}]"
            self.by_value[key] = tag
            self.by_tag[tag] = value
        self.touched = time.time()
        return tag


class Stats:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"istek": 0, "korunan_istek": 0, "toplam": 0, "turler": {}, "gunluk": {},
                    "llm_istek": 0, "dosya": 0}

    def record(self, counts: dict[str, int], llm_used: bool, file: bool = False) -> None:
        """Sadece tür ve sayı kaydedilir — ham veri asla."""
        with self.lock:
            d = self.data
            today = date.today().isoformat()
            day = d["gunluk"].setdefault(today, {"istek": 0, "toplam": 0, "turler": {}})
            total = sum(counts.values())
            d["istek"] += 1
            day["istek"] += 1
            d["llm_istek"] += int(llm_used)
            d["dosya"] = d.get("dosya", 0) + int(file)
            if total:
                d["korunan_istek"] += 1
            d["toplam"] += total
            day["toplam"] += total
            for typ, n in counts.items():
                d["turler"][typ] = d["turler"].get(typ, 0) + n
                day["turler"][typ] = day["turler"].get(typ, 0) + n
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    def snapshot(self) -> dict:
        with self.lock:
            d = json.loads(json.dumps(self.data))
        d["bugun"] = d["gunluk"].get(date.today().isoformat(), {"istek": 0, "toplam": 0, "turler": {}})
        d["ozel_nitelikli"] = sum(n for t, n in d["turler"].items() if t in SPECIAL_CATEGORIES)
        return d


class Sozluk:
    """Şirketin panelden girdiği ticari sır terimleri."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.terms: list[str] = json.loads(path.read_text(encoding="utf-8")).get("terimler", [])
        except Exception:
            self.terms = []

    def set(self, terms: list[str]) -> list[str]:
        clean = sorted({t.strip() for t in terms if t and t.strip()}, key=tr_lower)
        self.terms = clean
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"terimler": clean}, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        return clean


class Engine:
    def __init__(self, data_dir: Path) -> None:
        self.vaults: dict[str, Vault] = {}
        self.lock = threading.Lock()
        self.stats = Stats(data_dir / "stats.json")
        self.sozluk = Sozluk(data_dir / "sozluk.json")

    # -- tespit ------------------------------------------------------------
    def detect(self, text: str, use_llm: bool = True, use_names: bool = True,
               use_regex: bool = True) -> tuple[list[Finding], bool]:
        findings: list[Finding] = []
        if use_regex:
            findings += detect_regex(text)
            findings += detect_dictionary(text, self.sozluk.terms)
        if use_names:
            findings += detect_names(text)
        llm_used = False
        if use_llm:
            llm_findings = llm.detect_llm(text)
            if llm_findings is not None:
                llm_used = True
                findings += llm_findings
        return resolve_overlaps(findings), llm_used

    # -- vault -------------------------------------------------------------
    def vault(self, session: str) -> Vault:
        with self.lock:
            v = self.vaults.get(session)
            if v is None:
                v = self.vaults[session] = Vault()
            return v

    def reset(self, session: str) -> bool:
        with self.lock:
            return self.vaults.pop(session, None) is not None

    # -- mask / unmask -----------------------------------------------------
    def mask(self, text: str, session: str = "default", use_llm: bool = True,
             record: bool = True) -> dict:
        t0 = time.perf_counter()
        findings, llm_used = self.detect(text, use_llm=use_llm)
        vault = self.vault(session)
        with self.lock:
            tags = [vault.tag_for(f.type, f.value) for f in findings]
        parts, pos = [], 0
        for f, tag in zip(findings, tags):
            parts.append(text[pos:f.start])
            parts.append(tag)
            pos = f.end
        parts.append(text[pos:])
        counts = dict(Counter(f.type for f in findings))
        if record:
            self.stats.record(counts, llm_used)
        return {
            "masked": "".join(parts),
            "findings": [
                {**f.to_dict(), "tag": tag, "special": f.type in SPECIAL_CATEGORIES}
                for f, tag in zip(findings, tags)
            ],
            "counts": counts,
            "ms": round((time.perf_counter() - t0) * 1000, 1),
            "llm_used": llm_used,
        }

    def unmask(self, text: str, session: str = "default") -> str:
        vault = self.vaults.get(session)
        if vault is None:
            return text
        return TAG_RE.sub(lambda m: vault.by_tag.get(m.group(0), m.group(0)), text)

    def mapping(self, session: str) -> dict[str, str]:
        vault = self.vaults.get(session)
        return dict(vault.by_tag) if vault else {}
