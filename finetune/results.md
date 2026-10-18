# Fine-tuning results

Same 100-sample benchmark, full Kalkan pipeline (patterns + names + Gemma layer). Only the model behind the Gemma layer changes. Recall per type in the middle columns.

| Model | Recall | Precision | Unnecessary masks | KISI | SAGLIK | DIN_INANC | SIYASI | SENDIKA | CEZA | TICARI_SIR | Time / sample |
|---|---|---|---|---|---|---|---|---|---|---|---|
| gemma4 (E4B, stock) | 99% | 96% | 13 | 97% | 100% | 100% | 100% | 100% | 100% | 100% | 575.1 ms |
| gemma4:e2b (stock) | 83% | 98% | 4 | 89% | 46% | 50% | 80% | 50% | 67% | 12% | 480.1 ms |
| E2B base, same pipeline as ours | 87% | 95% | 13 | 89% | 62% | 50% | 100% | 50% | 100% | 33% | 496.4 ms |
| **E2B + Kalkan LoRA** | 98% | 98% | 6 | 96% | 100% | 100% | 100% | 100% | 100% | 92% | 584.9 ms |

Training: 33.1 min on an RTX 4070 Laptop GPU (8 GB). Validation loss 1.107 → 0.0001 (validation set uses the training templates; the benchmark above does not).
