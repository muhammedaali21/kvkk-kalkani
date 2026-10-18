"""Gemma 4 E2B için QLoRA ince ayarı (8 GB GPU'da).

Bellek: 2,35 milyar parametrelik katman başına gömme tablosu (embed_tokens_per_layer) yalnızca satır okur;
CPU'da tutulur. Dönüştürücü katmanları 4-bit olarak GPU'dadır, yalnızca LoRA ağırlıkları eğitilir.
Kayıp yalnızca modelin cevabı üzerinden hesaplanır (talimat ve kullanıcı metni maskelenir).

Çalıştırma (eğitim ortamında):
  C:\\kalkan-train\\Scripts\\python.exe finetune/train.py
Çıktı: C:/kalkan-train/adapter (LoRA adaptörü) ve finetune/train_log.json
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model
from transformers import AutoConfig, AutoTokenizer, Gemma4ForConditionalGeneration, get_cosine_schedule_with_warmup

BASE = "C:/kalkan-train/models/gemma-4-E2B-it-unsloth-bnb-4bit"
OUT = Path("C:/kalkan-train/adapter")
HERE = Path(__file__).resolve().parent
EPOCHS, ACCUM, LR, MAX_LEN = 2, 8, 2e-4, 1024
torch.manual_seed(0)
random.seed(0)


def device_map() -> dict:
    gpu = 0
    m = "model.language_model"
    return {
        f"{m}.embed_tokens_per_layer": "cpu",  # 4,7 GB'lık arama tablosu
        f"{m}.embed_tokens": gpu, f"{m}.layers": gpu, f"{m}.norm": gpu, f"{m}.rotary_emb": gpu,
        f"{m}.per_layer_model_projection": gpu, f"{m}.per_layer_projection_norm": gpu,
        # Görüntü/ses kodlayıcıları metin eğitiminde hiç çağrılmaz; GPU'da yer kaplamasınlar.
        "model.vision_tower": "cpu", "model.audio_tower": "cpu", "model.embed_vision": "cpu", "model.embed_audio": "cpu",
        "lm_head": gpu,
    }


class CpuLookup(torch.nn.Module):
    """Katman başına gömme tablosu CPU'da kalır; yalnızca o anki tokenların satırları GPU'ya gider.

    accelerate'in varsayılan CPU yüklemesi tüm tabloyu (4,7 GB) her ileri geçişte GPU'ya taşır; bu çok yavaştır.
    Tablo yalnızca satır okuduğu için (eğitilmez) bu ayrım sonucu değiştirmez.
    """

    def __init__(self, weight: torch.Tensor, scale: float) -> None:
        super().__init__()
        self.table = weight  # Parameter değil: .to()/peft taşımasın, gradyan almasın
        self.scale = scale

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        rows = torch.nn.functional.embedding(input_ids.cpu(), self.table)
        return (rows * self.scale).to(input_ids.device, non_blocking=True)


def attach_cpu_lookup(model) -> None:
    import json as _json
    from safetensors import safe_open

    key = "model.language_model.embed_tokens_per_layer.weight"
    index = Path(BASE) / "model.safetensors.index.json"
    shard = _json.loads(index.read_text())["weight_map"][key] if index.exists() else "model.safetensors"
    with safe_open(str(Path(BASE) / shard), framework="pt", device="cpu") as f:
        weight = f.get_tensor(key)
    lm = model.model.language_model
    old = lm.embed_tokens_per_layer
    scale = getattr(old, "embed_scale", None)
    scale = float(scale.item()) if scale is not None and scale.device.type != "meta" else \
        float(model.config.text_config.hidden_size_per_layer_input) ** 0.5
    lm.embed_tokens_per_layer = CpuLookup(weight, scale)
    print(f"katman başına gömme CPU'da: {tuple(weight.shape)}, ölçek {scale:.2f}", flush=True)


def encode(tok, example: dict) -> dict:
    msgs = example["messages"]
    prompt_str = tok.apply_chat_template(msgs[:2], tokenize=False, add_generation_prompt=True)
    full_str = tok.apply_chat_template(msgs, tokenize=False)
    assert full_str.startswith(prompt_str), "sohbet şablonu: komut, tam metnin öneki değil"
    # Komut ve cevap ayrı ayrı tokenlara bölünür (birleşik tokenlaştırmada "\n{" tek token olabiliyor);
    # bu, çıkarımdaki durumla aynıdır: model komuttan sonra üretmeye başlar.
    prompt = tok(prompt_str, add_special_tokens=False)["input_ids"]
    answer = tok(full_str[len(prompt_str):], add_special_tokens=False)["input_ids"]
    full = (prompt + answer)[:MAX_LEN]
    labels = ([-100] * len(prompt) + answer)[:MAX_LEN]
    return {"input_ids": full, "labels": labels}


def answer_loss(model, ex: dict) -> torch.Tensor:
    """Kayıp yalnızca cevap tokenları üzerinden.

    Tüm dizi için logit üretmek (≈640 token × 262.144 kelimelik sözlük) tek başına 1,5–2 GB tutar ve 8 GB'lık
    GPU'yu taşırır. logits_to_keep ile yalnızca cevabı tahmin eden son konumların logitleri hesaplanır.
    """
    n_ans = sum(1 for t in ex["labels"] if t != -100)
    ids = torch.tensor([ex["input_ids"]], device="cuda")
    with torch.autocast("cuda", dtype=torch.bfloat16):
        logits = model(input_ids=ids, logits_to_keep=n_ans + 1).logits  # [1, n_ans+1, V]
    pred = logits[:, :-1, :].float().reshape(-1, logits.shape[-1])
    target = ids[:, -n_ans:].reshape(-1)
    return torch.nn.functional.cross_entropy(pred, target)


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@torch.no_grad()
def evaluate(model, data: list[dict]) -> float:
    model.eval()
    total, n = 0.0, 0
    for ex in data:
        total += answer_loss(model, ex).item()
        n += 1
    model.train()
    return total / max(1, n)


def main() -> None:
    tok = AutoTokenizer.from_pretrained(BASE)
    train = [encode(tok, ex) for ex in load(HERE / "data" / "train.jsonl")]
    valid = [encode(tok, ex) for ex in load(HERE / "data" / "valid.jsonl")]
    print(f"eğitim {len(train)} örnek, doğrulama {len(valid)}, en uzun {max(len(e['input_ids']) for e in train)} token")

    # Modelin kendi 4-bit ayarı korunur; yalnızca CPU'ya taşınan (kuantize olmayan) arama tablosuna izin verilir.
    # (Önceden kuantize modellerde dışarıdan verilen ayar yok sayılır; bayrak modelin kendi yapılandırmasına yazılır.)
    cfg = AutoConfig.from_pretrained(BASE)
    cfg.quantization_config["llm_int8_enable_fp32_cpu_offload"] = True
    model = Gemma4ForConditionalGeneration.from_pretrained(
        BASE, config=cfg, device_map=device_map(), dtype=torch.bfloat16)
    attach_cpu_lookup(model)
    model.config.use_cache = False
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.enable_input_require_grads()
    lora = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        target_modules=r".*language_model\.layers\.\d+\.(self_attn\.(q_proj|k_proj|v_proj|o_proj)|mlp\.(gate_proj|up_proj|down_proj))",
    )
    model = get_peft_model(model, lora)
    for p in model.parameters():
        if p.requires_grad:
            p.data = p.data.float()  # LoRA ağırlıkları fp32: kararlı eğitim
    model.print_trainable_parameters()

    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=LR, weight_decay=0.0)
    steps = math.ceil(len(train) * EPOCHS / ACCUM)
    sched = get_cosine_schedule_with_warmup(opt, int(steps * 0.05), steps)
    log = {"adimlar": [], "dogrulama": [], "ayarlar": {"epoch": EPOCHS, "accum": ACCUM, "lr": LR, "r": 16}}

    if "--probe" in sys.argv:  # hız ölçümü: birkaç adım, eğitim yok
        model.train()
        for k in range(6):
            t = time.time()
            loss = answer_loss(model, train[k])
            loss.backward()
            opt.zero_grad(set_to_none=True)
            torch.cuda.synchronize()
            print(f"örnek {k}: {time.time() - t:.2f} sn, kayıp {loss.item():.3f}, "
                  f"GPU {torch.cuda.max_memory_allocated() / 2**30:.1f} GB", flush=True)
        return

    base_val = evaluate(model, valid)
    print(f"başlangıç doğrulama kaybı: {base_val:.4f}")
    log["dogrulama"].append({"epoch": 0, "kayip": base_val})
    model.train()
    t0, step, running = time.time(), 0, 0.0
    for epoch in range(1, EPOCHS + 1):
        order = list(range(len(train)))
        random.shuffle(order)
        for i, idx in enumerate(order, 1):
            loss = answer_loss(model, train[idx]) / ACCUM
            loss.backward()
            running += loss.item()
            if i % ACCUM == 0 or i == len(order):
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
                step += 1
                if step % 10 == 0:
                    el = time.time() - t0
                    print(f"epoch {epoch} adım {step}/{steps} kayıp {running / 10:.4f} "
                          f"({el / 60:.1f} dk, kalan ~{el / step * (steps - step) / 60:.1f} dk)", flush=True)
                    log["adimlar"].append({"adim": step, "kayip": running / 10})
                    running = 0.0
        val = evaluate(model, valid)
        print(f"epoch {epoch} doğrulama kaybı: {val:.4f}", flush=True)
        log["dogrulama"].append({"epoch": epoch, "kayip": val})

    OUT.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(OUT)
    tok.save_pretrained(OUT)
    log["sure_dk"] = round((time.time() - t0) / 60, 1)
    (HERE / "train_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"adaptör kaydedildi: {OUT} ({log['sure_dk']} dk)")


if __name__ == "__main__":
    main()
