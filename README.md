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
| 1b. Name list | "Ahmet Yılmaz", "Ayşe Hanım" | ~200 common Turkish first names + surname pattern (same line, same letter case). Works without the LLM. |
| 1d. Form fields | "Adı : …", "Doğum Tarihi : …", "Baba Adı : …" | Official documents (SGK, e-Devlet, bank forms) put values next to known labels. The value is masked because of its label, even if the name is not in the list or the number fails validation. Document dates are left alone. |
| 1c. Company dictionary | Client names, secret project names | Terms the compliance officer enters in the admin panel. |
| 1e. Developer leaks | API keys (AWS, GitHub, OpenAI/Anthropic, Google, Slack, Stripe), JWTs, `Bearer` tokens, PEM private keys, passwords, connection strings with credentials | Known key formats by exact pattern; generic assignments (`api_key = …`, `smtp_password = …`, `şifre: …`) by context. Only the value is masked, the key name stays. Placeholders (`<API_KEY>`, `${VAR}`, `****`, `changeme`) are ignored. Ranked above every other type so digits inside a key are never mistaken for a Turkish ID. |
| 2. Gemma 4 (local) | People, indirect identifiers, KVKK Art. 6 data, trade secrets | Ollama `/api/chat`, JSON mode, temperature 0. Any phrase the model returns that doesn't appear verbatim in the text is dropped (hallucination guard). |

Overlaps are resolved by priority (`TC = IBAN = KART > VKN > EPOSTA > TELEFON > PLAKA > SOZLUK > ADRES > KISI > Art. 6 types > TICARI_SIR`). The tag ↔ value table (the *vault*) lives only in memory on the employee's machine. The statistics file stores **types and counts only — never raw values**.

If the local server is unreachable, the browser extension **does not send the message** (fail closed).

## Benchmark

100 synthetic Turkish samples (customer service, HR, legal, mixed, and trap samples full of invalid ID numbers, order numbers, dates and city names). All IDs are algorithmically valid but randomly generated — no real personal data. Part of the name pool is deliberately *not* in our name list.

Full per-type table: [benchmark/results.md](benchmark/results.md). The Gemma layer is our fine-tuned `kalkan-gemma4-e2b` (see [Fine-tuning](#fine-tuning-gemma-4-for-turkish-kvkk-lora)) via Ollama on a laptop RTX 4070.

| | Regex only | + Name list | + Gemma 4 E2B + Kalkan LoRA (local) |
|---|---|---|---|
| Recall (IDs, IBAN, card, phone, e-mail, plate, address) | 100% | 100% | 100% |
| Recall (people) | 0% | 63% | 96% |
| Recall (health / religion / politics / union / criminal) | 0% | 0% | 100% |
| Recall (trade secrets) | 0% | 0% | 92% |
| **Overall recall** | 40% | 65% | **98%** |
| Precision | 100% | 100% | 98% |
| Unnecessary masks (of 100 samples) | 0 | 0 | 7 |
| Avg. time / sample | <1 ms | <1 ms | ~540 ms |

Rules catch the numbers; they cannot read context. Gemma closes the gap: names outside the list, "şeker hastası" (diabetic), "kâr marjımız %18" (our margin is 18%).

What the stock model got wrong, and why we fine-tuned: the stock 4B model (`gemma4`) reaches 99% recall but makes 13 unnecessary masks — mostly plain invoice/budget amounts flagged as trade secrets and the harmless phrase "maaş hesabı" (salary account). The stock 2B model is smaller but misses half the health, religion and union data. We did **not** tune the prompt on this benchmark; we trained on separate synthetic data instead (below).

Implementation note: Gemma 4 "thinks" before answering by default. Turning it off (`think: false`) cut latency from ~14 s to ~1 s per message with the same findings on our acceptance sample.

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

- Landing page: http://127.0.0.1:8765/
- App (message & file masking): http://127.0.0.1:8765/uygulama
- Admin panel: http://127.0.0.1:8765/panel
- Extension: `chrome://extensions` → Developer mode → *Load unpacked* → select `extension/`

### Environment variables

| Variable | Default | |
|---|---|---|
| `KALKAN_MODEL` | `auto` | Text model. `auto` = `kalkan-gemma4-e2b` if installed, else `gemma4` |
| `KALKAN_VISION_MODEL` | `auto` | Screenshot model. `auto` = `gemma4` if installed, else the fine-tuned one |
| `KALKAN_TESSDATA` | `C:\ProgramData\Kalkan\tessdata` | Folder with `tur.traineddata` for OCR |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | |
| `KALKAN_UPSTREAM` | `https://api.openai.com/v1` | Target of the OpenAI-compatible proxy |
| `KALKAN_UPSTREAM_KEY` | — | Used if the client sends no `Authorization` header |
| `KALKAN_LLM_TIMEOUT` | `60` | Seconds |

### API

| Endpoint | |
|---|---|
| `GET /health` | `{ok, llm, model}` |
| `POST /mask` | `{text, session, use_llm, types?}` → `{masked, findings, counts, ms, llm_used, excluded}` |
| `GET/PUT /politika` | Company masking policy: which data types are masked. Used whenever a request omits `types` (extension, proxy, files). |
| `POST /unmask` | `{text, session}` → `{text}` |
| `GET /mapping/{session}` | tag → value (localhost only) |
| `POST /reset/{session}` | drop a session's vault |
| `POST /mask-file` | DOCX / PDF / XLSX / CSV / TXT → masked file in the same format; report in the `X-Kalkan-Report` header |
| `POST /analyze-file` | Review step: scans the file without changing it and lists every value found, grouped by type (`{file_id, bulgular: [{key, type, value, count}]}`). The file is kept in memory for 30 minutes, never on disk. |
| `POST /mask-file/{file_id}` | `{keys, session}` → masks only the values the user selected in the review step |
| `GET /stats` | panel statistics (types and counts only) |
| `GET/PUT /sozluk` | company trade-secret dictionary |
| `POST /v1/chat/completions` | OpenAI-compatible proxy: mask → forward → restore (no streaming) |

Any OpenAI client can use the shield by changing its base URL to `http://127.0.0.1:8765/v1`.

### Tests and benchmark

```bash
cd backend && python tests/test_acceptance.py     # or: python -m pytest tests
python benchmark/generate.py && python benchmark/evaluate.py

# Extension end-to-end: real Chromium + the extension, chatgpt.com routed to a local mock page
pip install playwright && python -m playwright install chromium
python tests/extension/e2e_extension.py
```

## Project layout

```
backend/kalkan/   detectors.py  names.py  llm.py  engine.py  files.py  api.py
backend/tests/    acceptance tests (synthetic data only)
extension/        Chrome MV3 extension
demo/             landing.html (/), index.html (/uygulama), panel.html (/panel)
benchmark/        generate.py, evaluate.py, results.md
ornek/            synthetic sample files (xlsx, csv, docx, pdf) for trying file masking
```

## File masking

| Format | What happens |
|---|---|
| Word (.docx) | Every text node is scanned: body, tables, headers/footers, footnotes, comments, hyperlinks and tracked changes. Formatting is preserved. `mailto:` link targets and the document's author fields are cleared too. |
| PDF | **True redaction**: the matched text is removed from the file and replaced by a labelled black bar — not just covered, so it cannot be selected or copied. Scanned (image-only) PDFs are not supported yet. |
| Excel / CSV | Columns whose header names a personal field (name, TC, phone, e-mail, IBAN, address) are masked entirely; other cells go through the same layers as messages. |

After masking, the output file is re-opened and searched for every value that was hidden; the count of anything still readable is returned as `kalan` and shown as a warning in the UI.

## Fine-tuning Gemma 4 for Turkish KVKK (LoRA)

"We can customise the open model" is easy to say. We did it, on the laptop GPU (RTX 4070, 8 GB).

- **Data** — `finetune/make_data.py`: 1,200 training + 120 validation synthetic Turkish examples. Templates, phrase pools and random seed are all **different from the benchmark**, so the benchmark measures generalisation, not memorisation. Includes negative examples (invoice totals, budgets, "maaş hesabı") because those caused most of the base model's false positives. The target output is exactly what Kalkan's prompt asks for.
- **Training** — `finetune/train.py`: QLoRA on `gemma-4-E2B-it` (4-bit), r=16, attention + MLP of the language model only (24M trainable parameters, 0.87%), 2 epochs, loss on the answer tokens only. Gemma 4's 2.35B-parameter per-layer embedding table is a pure lookup, so it stays in CPU RAM and only the rows for the current tokens are sent to the GPU — that is what makes it fit in 8 GB.
- **Export** — `finetune/export.py`: the adapter is merged into the full-precision model and imported into Ollama with the same renderer, parser and Q4_K_M quantization as the stock `gemma4:e2b`, so the only difference in the comparison is the weights.

**Result** ([finetune/results.md](finetune/results.md)) — same benchmark, full pipeline, only the model behind the Gemma layer changes:

| Model | Recall | Precision | Unnecessary masks | Health | Religion | Union | Trade secret | Size |
|---|---|---|---|---|---|---|---|---|
| `gemma4` (E4B, stock) | 99% | 96% | 13 | 100% | 100% | 100% | 100% | 6.6 GB |
| `gemma4:e2b` (stock) | 83% | 98% | 4 | 46% | 50% | 50% | 12% | 4.6 GB |
| E2B base, same export pipeline as ours | 87% | 95% | 13 | 62% | 50% | 50% | 33% | 4.4 GB |
| **E2B + Kalkan LoRA** | **98%** | **98%** | **6** | **100%** | **100%** | **100%** | **92%** | **4.4 GB** |

- Against the identical base model (same weights source, same converter, same Q4_K_M quantization): recall **87% → 98%**, precision 95% → 98%. None of the benchmark's templates or phrases were in the training data, so this is generalisation, not memorisation.
- Against the stock model twice its size: **same recall (98% vs 99%), half the unnecessary masks (6 vs 13), a third less memory.**
- What it is *not*: faster. Answers are a few dozen tokens, so latency per message is dominated by fixed overhead (~0.55 s for both). We claimed "twice as fast" in our plan; the measurement says no.
- Vision: the LoRA was trained on text only, and on screenshots the fine-tuned E2B misses context the 4B model catches. Kalkan therefore picks models per job automatically: `KALKAN_MODEL=auto` → fine-tuned E2B for text, `KALKAN_VISION_MODEL=auto` → `gemma4` for screenshots (both overridable).

This is the honest answer to "why an open model": a closed API can't be fine-tuned for Turkish KVKK and then run on the employee's laptop.

Note: the numbers above are from the first run (v1: 1,200 examples). `make_data.py` now generates a v2 set (1,600 examples, shorter target phrases, more harmless business messages) aimed at two v1 weaknesses we found after measuring — occasional long spans and a false positive on short messages like "… iade istiyor". v2 has not been trained yet. The engine is already safe against the long-span case: when a lower-priority finding loses an overlap, its remaining parts are still masked.

Reproduce: `uv venv C:\kalkan-train --python 3.12`, install `torch` (CUDA), `transformers peft accelerate bitsandbytes`, then run `finetune/download.py`, `finetune/make_data.py`, `finetune/train.py`, `finetune/export.py`, and `benchmark/evaluate.py --model kalkan-gemma4-e2b`.

## Screenshots

Employees don't only paste text — they paste a screenshot of the customer screen or the Excel sheet. Kalkan redacts those too, before they reach the chat site.

- **Tesseract OCR** gives the exact pixel position of every word. Language models are not reliable at pixel coordinates; a box that is a few pixels off leaves half an ID number visible.
- The **existing layers** (patterns + checksums, form fields, names, dictionary, secrets) run on the OCR text.
- **Gemma 4 looks at the image itself** and reads context — which phrase is a diagnosis, which is a trade secret, which is a name that isn't in our list. Its phrases are matched (tolerantly, OCR makes small mistakes) to OCR words; OCR decides where the box goes.
- The redacted image is **OCR'd again**; if any hidden value is still readable, the UI warns.

In the browser extension, images pasted with Ctrl+V, dropped onto the page or picked with the attach button are intercepted, redacted locally and only then handed to the site. If the local server is down, the image is not added.

Setup (Windows): `winget install UB-Mannheim.TesseractOCR`, then put `tur.traineddata` from [tessdata_best](https://github.com/tesseract-ocr/tessdata_best) next to `eng.traineddata` in `C:\ProgramData\Kalkan\tessdata` (or set `KALKAN_TESSDATA`). Sample screenshots: `ornek/ekran_tablo.png`, `ornek/ekran_crm.png`.

## License

MIT. Note on dependencies: PDF redaction uses [PyMuPDF](https://pymupdf.readthedocs.io/), which is licensed under AGPL-3.0 (commercial licenses are available from Artifex). That is fine for this open-source project; a closed-source commercial distribution would need a PyMuPDF commercial license or a different PDF backend.
