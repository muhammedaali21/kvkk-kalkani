# Benchmark results

100 synthetic Turkish samples, 286 gold findings (customer service, HR, legal, mixed, traps). Model: `kalkan-gemma4-e2b`.

## Recall by type (leak prevented)

| Type | (a) Regex + validation | (b) + Turkish name list | (c) + Gemma 4 (local) |
|---|---|---|---|
| TC | 100% (13/13) | 100% (13/13) | 100% (13/13) |
| IBAN | 100% (13/13) | 100% (13/13) | 100% (13/13) |
| KART | 100% (9/9) | 100% (9/9) | 100% (9/9) |
| VKN | 100% (10/10) | 100% (10/10) | 100% (10/10) |
| TELEFON | 100% (25/25) | 100% (25/25) | 100% (25/25) |
| EPOSTA | 100% (18/18) | 100% (18/18) | 100% (18/18) |
| PLAKA | 100% (9/9) | 100% (9/9) | 100% (9/9) |
| ADRES | 100% (18/18) | 100% (18/18) | 100% (18/18) |
| KISI | 0% (0/112) | 63% (71/112) | 97% (109/112) |
| SAGLIK | 0% (0/13) | 0% (0/13) | 100% (13/13) |
| DIN_INANC | 0% (0/4) | 0% (0/4) | 100% (4/4) |
| SIYASI | 0% (0/5) | 0% (0/5) | 100% (5/5) |
| SENDIKA | 0% (0/4) | 0% (0/4) | 100% (4/4) |
| CEZA | 0% (0/9) | 0% (0/9) | 100% (9/9) |
| TICARI_SIR | 0% (0/24) | 0% (0/24) | 92% (22/24) |

## Overall

| Metric | (a) | (b) | (c) |
|---|---|---|---|
| Recall | 40% | 65% | 98% |
| Precision | 100% | 100% | 98% |
| Unnecessary masks | 0 | 0 | 7 |
| …of which in trap samples | 0 | 0 | 4 |
| Avg. time / sample | 0.1 ms | 0.1 ms | 538.8 ms |
