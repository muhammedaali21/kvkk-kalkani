# Benchmark results

100 synthetic Turkish samples, 286 gold findings (customer service, HR, legal, mixed, traps). Model: `kalkan-gemma4-e2b`.

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
| KISI | 96% (108/112) |
| SAGLIK | 100% (13/13) |
| DIN_INANC | 100% (4/4) |
| SIYASI | 100% (5/5) |
| SENDIKA | 100% (4/4) |
| CEZA | 100% (9/9) |
| TICARI_SIR | 92% (22/24) |

## Overall

| Metric | (c) |
|---|---|
| Recall | 98% |
| Precision | 98% |
| Unnecessary masks | 6 |
| …of which in trap samples | 4 |
| Avg. time / sample | 584.9 ms |
