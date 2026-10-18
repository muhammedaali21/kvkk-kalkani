"""Dört modelin benchmark sonuçlarını tek tabloda toplar → finetune/results.md

Önce her model için:
  python benchmark/evaluate.py --model <ad> --only-llm --out results-<ad>.md
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROWS = [
    ("gemma4 (E4B, stock)", "results-gemma4.md"),
    ("gemma4:e2b (stock)", "results-gemma4-e2b.md"),
    ("E2B base, same pipeline as ours", "results-gemma4-e2b-yerel.md"),
    ("**E2B + Kalkan LoRA**", "results-kalkan-gemma4-e2b.md"),
]
TYPES = ["KISI", "SAGLIK", "DIN_INANC", "SIYASI", "SENDIKA", "CEZA", "TICARI_SIR"]


def grab(text: str, key: str) -> str:
    m = re.search(r"^\| " + re.escape(key) + r" \| ([^|]+) \|", text, re.M)
    return m.group(1).strip() if m else "—"


def main() -> None:
    out = [
        "# Fine-tuning results", "",
        "Same 100-sample benchmark, full Kalkan pipeline (patterns + names + Gemma layer). "
        "Only the model behind the Gemma layer changes. Recall per type in the middle columns.", "",
        "| Model | Recall | Precision | Unnecessary masks | " + " | ".join(TYPES) + " | Time / sample |",
        "|---" * (5 + len(TYPES)) + "|",
    ]
    for name, file in ROWS:
        path = ROOT / "benchmark" / file
        if not path.exists():
            continue
        t = path.read_text(encoding="utf-8")
        cells = [grab(t, "Recall"), grab(t, "Precision"), grab(t, "Unnecessary masks")]
        cells += [grab(t, k).split(" ")[0] for k in TYPES] + [grab(t, "Avg. time / sample")]
        out.append(f"| {name} | " + " | ".join(cells) + " |")
    log = json.loads((ROOT / "finetune" / "train_log.json").read_text(encoding="utf-8"))
    v0, v1 = log["dogrulama"][0]["kayip"], log["dogrulama"][-1]["kayip"]
    out += ["", f"Training: {log['sure_dk']} min on an RTX 4070 Laptop GPU (8 GB). "
                f"Validation loss {v0:.3f} → {v1:.4f} (validation set uses the training templates; "
                f"the benchmark above does not)."]
    (ROOT / "finetune" / "results.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
