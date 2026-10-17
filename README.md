# 🛡️ KVKK Kalkanı

**Your employees keep using ChatGPT. Their customers' data never leaves the laptop.**

KVKK Kalkanı ("KVKK Shield") is a local privacy layer for Turkish companies. Before a message reaches ChatGPT, Claude or Gemini, it is scanned **on the employee's own computer**, personal data and trade secrets are replaced with consistent tags (`Ahmet Yılmaz` → `[KISI_1]`), and the tags in the AI's answer are swapped back to the real values on screen.

Built for Hacktoberfest Elazığ 2026 — theme: *Side Hustle*. MIT licensed.

```
Employee types          AI sees                       Employee reads
Ahmet Yılmaz      →     [KISI_1]                →     Ahmet Yılmaz
TC 12345678950    →     TC [TC_1]                     (restored locally)
şeker hastası     →     [SAGLIK_1]  (KVKK Art. 6)
```

## Why an open model?

The model that cleans the data has to *see* the data. That job, by definition, cannot be done by a closed API — sending a customer list to a cloud model in order to "anonymize" it is the very leak we are trying to stop. Gemma 4 runs locally through Ollama: no data leaves the machine, no per-token cost, and the model can be tuned for Turkish context and the special-category data defined in KVKK Article 6 (health, religion, union membership, criminal records…).

## How it works

| Layer | Finds | How |
|---|---|---|
| 1. Regex + validation | Turkish ID (TC), IBAN, tax no (VKN), card, phone, e-mail, plate, address | Pattern + checksum (TC algorithm, IBAN mod-97, VKN, Luhn). Numbers that fail validation — order numbers, invoice numbers — are **not** masked. |
| 1b. Name list | "Ahmet Yılmaz", "Ayşe Hanım" | ~150 common Turkish first names + surname pattern. Works without the LLM. |
| 1c. Company dictionary | Client names, secret project names | Terms the compliance officer enters in the admin panel. |
| 2. Gemma 4 (local) | People, indirect identifiers, KVKK Art. 6 data, trade secrets | Ollama `/api/chat`, JSON mode, temperature 0. Any phrase the model returns that doesn't appear verbatim in the text is dropped (hallucination guard). |

Overlaps are resolved by priority (`TC = IBAN = KART > VKN > EPOSTA > TELEFON > PLAKA > SOZLUK > ADRES > KISI > Art. 6 types > TICARI_SIR`). The tag ↔ value table (the *vault*) lives only in memory on the employee's machine. The statistics file stores **types and counts only — never raw values**.

If the local server is unreachable, the browser extension **does not send the message** (fail closed).

## Benchmark

100 synthetic Turkish samples (customer service, HR, legal, mixed, and trap samples full of invalid ID numbers, order numbers, dates and city names). All IDs are algorithmically valid but randomly generated — no real personal data. Part of the name pool is deliberately *not* in our name list.

See [benchmark/results.md](benchmark/results.md) for the latest run. Without Gemma (layers 1 + 1b):

| | Regex only | + Name list |
|---|---|---|
| Recall (structured IDs, phones, e-mail, address) | 100% | 100% |
| Recall (people) | 0% | 59% |
| Recall (health / religion / union / criminal / trade secret) | 0% | 0% |
| Overall recall | 40% | 63% |
| Precision | 100% | 100% |
| False masks in trap samples | 0 | 0 |

Rules catch the numbers; they cannot read context. The remaining gap — names outside the list, "şeker hastası", "kâr marjımız %18" — is exactly what the local Gemma layer is for. Run `python benchmark/evaluate.py` with Ollama running to get the (c) column.

## Limitations (honestly)

- The synthetic benchmark is template-based, so structured fields are easier than in real-world text.
- The name list is small by design; names outside it depend on Gemma.
- The extension relies on each chat site's DOM; a UI update on ChatGPT/Claude/Gemini can break send interception (it then fails closed).
- The vault is in memory: after a server restart, tags in old conversations can no longer be restored.
- The OpenAI-compatible proxy does not support streaming yet.

---

## Kurulum (Setup)

Requirements: Python 3.11+, Chrome, optionally [Ollama](https://ollama.com).

```bash
pip install -r requirements.txt

# Optional — Layer 2 (Gemma 4, local)
ollama pull gemma4          # model name: check with `ollama list`

cd backend
uvicorn kalkan.api:app --host 127.0.0.1 --port 8765
```

- Demo: http://127.0.0.1:8765/
- Admin panel: http://127.0.0.1:8765/panel
- Extension: `chrome://extensions` → Developer mode → *Load unpacked* → select `extension/`

### Environment variables

| Variable | Default | |
|---|---|---|
| `KALKAN_MODEL` | `gemma4` | Ollama model name |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | |
| `KALKAN_UPSTREAM` | `https://api.openai.com/v1` | Target of the OpenAI-compatible proxy |
| `KALKAN_UPSTREAM_KEY` | — | Used if the client sends no `Authorization` header |
| `KALKAN_LLM_TIMEOUT` | `60` | Seconds |

### API

| Endpoint | |
|---|---|
| `GET /health` | `{ok, llm, model}` |
| `POST /mask` | `{text, session, use_llm}` → `{masked, findings, counts, ms, llm_used}` |
| `POST /unmask` | `{text, session}` → `{text}` |
| `GET /mapping/{session}` | tag → value (localhost only) |
| `POST /reset/{session}` | drop a session's vault |
| `POST /mask-file` | CSV / XLSX / TXT → masked file; report in the `X-Kalkan-Report` header |
| `GET /stats` | panel statistics (types and counts only) |
| `GET/PUT /sozluk` | company trade-secret dictionary |
| `POST /v1/chat/completions` | OpenAI-compatible proxy: mask → forward → restore (no streaming) |

Any OpenAI client can use the shield by changing its base URL to `http://127.0.0.1:8765/v1`.

### Tests and benchmark

```bash
cd backend && python tests/test_acceptance.py     # or: python -m pytest tests
python benchmark/generate.py && python benchmark/evaluate.py
```

## Project layout

```
backend/kalkan/   detectors.py  names.py  llm.py  engine.py  files.py  api.py
backend/tests/    acceptance tests (synthetic data only)
extension/        Chrome MV3 extension
demo/             index.html (demo), panel.html (admin panel)
benchmark/        generate.py, evaluate.py, results.md
```

## License

MIT
