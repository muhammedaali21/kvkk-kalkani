"""Benchmark: üç modu karşılaştırır ve README / DEV yazısı için tablo üretir.

  (a) sadece regex + doğrulama
  (b) regex + isim sözlüğü
  (c) regex + isim + Gemma 4 (Ollama açıksa)

Recall: altın bulgu herhangi bir tahminle örtüşüyorsa "sızıntı engellendi".
Precision: hiçbir altınla örtüşmeyen tahmin = gereksiz maskeleme.

Çalıştırma: python benchmark/evaluate.py [--no-llm]  →  benchmark/results.md
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from kalkan import llm  # noqa: E402
from kalkan.engine import Engine  # noqa: E402

MODES = {
    "a": ("Regex + validation", dict(use_regex=True, use_names=False, use_llm=False)),
    "b": ("+ Turkish name list", dict(use_regex=True, use_names=True, use_llm=False)),
    "c": ("+ Gemma 4 (local)", dict(use_regex=True, use_names=True, use_llm=True)),
}
TYPE_ORDER = ["TC", "IBAN", "KART", "VKN", "TELEFON", "EPOSTA", "PLAKA", "ADRES", "KISI",
              "SAGLIK", "DIN_INANC", "SIYASI", "SENDIKA", "CEZA", "TICARI_SIR"]


def overlaps(a: dict, b) -> bool:
    return a["start"] < b.end and b.start < a["end"]


def run(rows: list[dict], engine: Engine, flags: dict) -> dict:
    per_type = defaultdict(lambda: [0, 0])  # tür → [yakalanan, toplam]
    tp_pred = fp_pred = 0
    trap_fp = 0
    elapsed = []
    for row in rows:
        t0 = time.perf_counter()
        preds, _ = engine.detect(row["text"], **flags)
        elapsed.append((time.perf_counter() - t0) * 1000)
        for g in row["gold"]:
            per_type[g["type"]][1] += 1
            if any(overlaps(g, p) for p in preds):
                per_type[g["type"]][0] += 1
        for p in preds:
            if any(overlaps(g, p) for g in row["gold"]):
                tp_pred += 1
            else:
                fp_pred += 1
                trap_fp += row["category"] == "tuzak"
    caught = sum(v[0] for v in per_type.values())
    total = sum(v[1] for v in per_type.values())
    return {
        "per_type": dict(per_type),
        "recall": caught / total if total else 0,
        "precision": tp_pred / (tp_pred + fp_pred) if tp_pred + fp_pred else 1,
        "fp": fp_pred,
        "trap_fp": trap_fp,
        "ms": sum(elapsed) / len(elapsed),
    }


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def main() -> None:
    data = ROOT / "benchmark" / "data.jsonl"
    if not data.exists():
        sys.exit("Önce veriyi üretin: python benchmark/generate.py")
    rows = [json.loads(line) for line in data.read_text(encoding="utf-8").splitlines() if line.strip()]
    engine = Engine(Path(tempfile.mkdtemp()))  # istatistik dosyasını kirletme

    modes = ["a", "b"]
    if "--no-llm" not in sys.argv and llm.available():
        modes.append("c")
    else:
        print("Ollama/Gemma kapalı: (c) modu atlandı.")

    results = {}
    for m in modes:
        print(f"({m}) {MODES[m][0]} çalışıyor…")
        results[m] = run(rows, engine, MODES[m][1])

    head = "| Type | " + " | ".join(f"({m}) {MODES[m][0]}" for m in modes) + " |"
    sep = "|---|" + "---|" * len(modes)
    lines = [
        f"# Benchmark results\n",
        f"{len(rows)} synthetic Turkish samples, {sum(len(r['gold']) for r in rows)} gold findings "
        f"(customer service, HR, legal, mixed, traps). Model: `{llm.MODEL}`.\n",
        "## Recall by type (leak prevented)\n", head, sep,
    ]
    for t in TYPE_ORDER:
        if not any(t in results[m]["per_type"] for m in modes):
            continue
        cells = []
        for m in modes:
            c, n = results[m]["per_type"].get(t, [0, 0])
            cells.append(f"{pct(c / n)} ({c}/{n})" if n else "—")
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    lines += [
        "\n## Overall\n", "| Metric | " + " | ".join(f"({m})" for m in modes) + " |", sep,
        "| Recall | " + " | ".join(pct(results[m]["recall"]) for m in modes) + " |",
        "| Precision | " + " | ".join(pct(results[m]["precision"]) for m in modes) + " |",
        "| Unnecessary masks | " + " | ".join(str(results[m]["fp"]) for m in modes) + " |",
        "| …of which in trap samples | " + " | ".join(str(results[m]["trap_fp"]) for m in modes) + " |",
        "| Avg. time / sample | " + " | ".join(f"{results[m]['ms']:.1f} ms" for m in modes) + " |",
    ]
    report = "\n".join(lines) + "\n"
    (ROOT / "benchmark" / "results.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
