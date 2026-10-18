# Benchmark results

100 synthetic Turkish samples, 286 gold findings (customer service, HR, legal, mixed, traps). Model: `gemma4-e2b-yerel`.

## Recall by type (leak prevented)

| Type | (c) + Gemma 4 (local) |
|---|---|
| TC | 100% (13/13) |
| IBAN | 100% (13/13) |
| KART | 100% (9/9) |
| VKN | 100% (10/10) |
| TELEFON | 100% (25/25) |
| EPOSTA | 100% (18/18) |
| PLAKA | 100% (9/9) |
| ADRES | 100% (18/18) |
| KISI | 89% (100/112) |
| SAGLIK | 62% (8/13) |
| DIN_INANC | 50% (2/4) |
| SIYASI | 100% (5/5) |
| SENDIKA | 50% (2/4) |
| CEZA | 100% (9/9) |
| TICARI_SIR | 33% (8/24) |

## Overall

| Metric | (c) |
|---|---|
| Recall | 87% |
| Precision | 95% |
| Unnecessary masks | 13 |
| …of which in trap samples | 13 |
| Avg. time / sample | 496.4 ms |
