"""LoRA adaptörünü birleştirir, GGUF'a çevirir, Q4_K_M'ye kuantize eder ve Ollama'ya aktarır.

Adil kıyaslama için TEMEL model de birebir aynı hattan geçer (aynı Hugging Face ağırlıkları, aynı dönüştürücü,
aynı Q4_K_M kuantizasyonu, aynı Ollama ayarları). Böylece iki model arasındaki tek fark LoRA ağırlıklarıdır.

  kalkan-gemma4-e2b    : ince ayarlı
  gemma4-e2b-yerel     : aynı hattan geçen temel model

Görüntü projektörü (mmproj) de aktarılır; LoRA yalnızca dil katmanlarını değiştirdiği için ikisinde aynıdır.

Gereksinimler: llama.cpp deposu (C:/kalkan-train/llama.cpp, gguf-py kurulu) ve llama-quantize (C:/kalkan-train/llama-bin).
Çalıştırma (eğitim ortamında): C:\\kalkan-train\\Scripts\\python.exe finetune/export.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

W = Path("C:/kalkan-train")
FULL = W / "models" / "gemma-4-E2B-it"
ADAPTER = W / "adapter"
MERGED = W / "merged"
GGUF = W / "gguf"
CONVERT = W / "llama.cpp" / "convert_hf_to_gguf.py"
QUANTIZE = next((W / "llama-bin").rglob("llama-quantize.exe"), None)

MODELFILE = """FROM {model}
FROM {mmproj}
RENDERER gemma4
PARSER gemma4
PARAMETER temperature 1
PARAMETER top_k 64
PARAMETER top_p 0.95
"""


def run(cmd: list) -> None:
    print("$", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def merge() -> None:
    if (MERGED / "model.safetensors.index.json").exists():
        print("birleştirilmiş model zaten var:", MERGED, flush=True)
        return
    import torch
    from peft import PeftModel
    from transformers import Gemma4ForConditionalGeneration

    print("tam model yükleniyor (CPU, bf16)…", flush=True)
    base = Gemma4ForConditionalGeneration.from_pretrained(FULL, dtype=torch.bfloat16, device_map="cpu",
                                                          low_cpu_mem_usage=True)
    model = PeftModel.from_pretrained(base, ADAPTER).merge_and_unload()
    model.save_pretrained(MERGED, safe_serialization=True, max_shard_size="4GB")
    for f in FULL.iterdir():  # tokenizer, işlemci ve şablon dosyaları
        if f.is_file() and f.suffix in (".json", ".jinja", ".model", ".txt") and not (MERGED / f.name).exists():
            shutil.copy(f, MERGED / f.name)


def in_ollama(name: str) -> bool:
    return subprocess.run(["ollama", "show", name], capture_output=True).returncode == 0


def to_ollama(src: Path, name: str, mmproj: Path) -> None:
    if in_ollama(name) and "--force" not in sys.argv:
        print(f"{name} Ollama'da zaten var (yeniden üretmek için --force)", flush=True)
        return
    f16, q4 = GGUF / f"{name}-bf16.gguf", GGUF / f"{name}-Q4_K_M.gguf"
    if not q4.exists():
        # Ollama modelleri boşaltıldıktan sonra RAM yeterli; --use-temp-file diski iki kat kullanır.
        # Yine de bellek yetmezse: export.py --temp
        extra = ["--use-temp-file"] if "--temp" in sys.argv else []
        run([sys.executable, CONVERT, src, "--outfile", f16, "--outtype", "bf16", *extra])
        run([QUANTIZE, f16, q4, "Q4_K_M"])
        f16.unlink()
    modelfile = GGUF / f"{name}.Modelfile"
    modelfile.write_text(MODELFILE.format(model=q4.as_posix(), mmproj=mmproj.as_posix()), encoding="utf-8")
    run(["ollama", "create", name, "-f", modelfile])
    print(f"Ollama modeli hazır: {name}", flush=True)


def main() -> None:
    if QUANTIZE is None or not CONVERT.exists():
        sys.exit("llama.cpp araçları bulunamadı (README'deki ince ayar bölümüne bakın).")
    GGUF.mkdir(exist_ok=True)
    # Ollama'da yüklü modeller belleği paylaşır; dönüştürme öncesi boşalt.
    for m in ("gemma4", "gemma4:e2b", "kalkan-gemma4-e2b", "gemma4-e2b-yerel"):
        subprocess.run(["ollama", "stop", m], capture_output=True)
    if not in_ollama("kalkan-gemma4-e2b") or "--force" in sys.argv:
        merge()
    mmproj = GGUF / "gemma4-e2b-mmproj-bf16.gguf"
    if not mmproj.exists():
        run([sys.executable, CONVERT, FULL, "--mmproj", "--outfile", mmproj, "--outtype", "bf16"])
    to_ollama(MERGED, "kalkan-gemma4-e2b", mmproj)
    to_ollama(FULL, "gemma4-e2b-yerel", mmproj)


if __name__ == "__main__":
    main()
