# Run MAPPA locally (no GCP needed)

A fully local demo: semantic retrieval + a local open-source LLM (Mistral via
Ollama) over the sample + Drive-sourced documents. Nothing leaves the machine,
no API keys, no cloud database.

## One-time setup (already done on this machine)
- Python 3.12 venv at `./venv` with deps installed.
- Ollama installed, with the `mistral` model pulled (`ollama pull mistral`).
- Local corpus: `data/documents.json` (samples) + `data/drive_docs.json` (pulled from Drive).

## Start it
```bash
# 1. Make sure the local model server is running:
ollama serve   # (or: brew services start ollama) — leave running

# 2. Start the app:
cd /Users/rmj7591/mappa
./venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
```
Then open **http://127.0.0.1:8000** in your browser — map on the left, chat on the right.
Ask in Spanish, e.g. *"¿Puedo construir en zona inundable cerca del río en Ponce?"*

## How it works
- `api/retrieval.py` — embeds the corpus in memory (multilingual MiniLM) and finds the
  most relevant documents for a question.
- `api/llm.py` — sends those documents + the question to the local Mistral model and gets
  back a cited Spanish answer. If Ollama is off, it falls back to a templated answer.
- `api/main.py` — the `/ask` endpoint that ties them together; `frontend/` is the UI.

## Answer language
Defaults to **English** (`RESPONSE_LANG=en`) for now so it's easy to verify.
Switch to Spanish (the real product default) with:
```bash
RESPONSE_LANG=es ./venv/bin/uvicorn api.main:app --port 8000
```

## Swapping the model
```bash
ollama pull llama3.1        # or any Ollama model
LLM_MODEL=llama3.1 ./venv/bin/uvicorn api.main:app --port 8000
```

## Adding more documents
Drop more entries into `data/drive_docs.json` (same shape as `data/documents.json`)
and restart the server. For the real pipeline (PDFs, cloud DB) see `docs/SETUP_RUNBOOK.md`.

## Notes / limits of this local demo
- The map shows base tiles only — real PR layers come once PostGIS is loaded (needs GCP).
- Retrieval here is in-memory over a handful of docs; the production path uses Postgres +
  pgvector. Same idea, bigger scale.
