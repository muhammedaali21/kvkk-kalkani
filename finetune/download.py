"""İnce ayar için Gemma 4 E2B ağırlıklarını indirir (Hugging Face, unsloth aynası; hesap onayı gerekmez).

  - gemma-4-E2B-it-unsloth-bnb-4bit : eğitim (QLoRA)
  - gemma-4-E2B-it                  : adaptörü birleştirip Ollama'ya aktarmak için tam hassasiyetli model

Çalıştırma (eğitim ortamında): C:\\kalkan-train\\Scripts\\python.exe finetune/download.py [4bit|tam]
"""

import os
import sys

os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "1")
from huggingface_hub import snapshot_download  # noqa: E402

TARGET = "C:/kalkan-train/models"
REPOS = {"4bit": "unsloth/gemma-4-E2B-it-unsloth-bnb-4bit", "tam": "unsloth/gemma-4-E2B-it"}

for key in sys.argv[1:] or list(REPOS):
    repo = REPOS[key]
    path = snapshot_download(repo, local_dir=f"{TARGET}/{repo.split('/')[1]}",
                             allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt", "*.jinja"])
    print("OK", path, flush=True)
