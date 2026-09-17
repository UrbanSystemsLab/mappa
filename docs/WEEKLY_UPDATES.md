# MAPPA — Weekly Status & Progress Tracker

Purpose: keep everyone aligned on what's done, in progress, blocked, and next — and
keep a single map of *where everything lives* so we don't lose the thread. Updated weekly.

---

## Status at a glance — as of 2026-07-30

**Headline:** A working **local prototype** answers questions over real Puerto Rico
planning documents, with cited sources. The full **cloud** build is blocked on getting
the Google Cloud project created (NYU IT).

### ✅ Done
- Reviewed the existing codebase; confirmed approach = **RAG** (feed an open model real
  documents at answer-time), **not** training a custom model.
- Inventoried La Maraña's Google Drive: GIS layers + the **master inventory of 473
  planning documents** (225 with direct PDF links).
- Wrote the **data-pipeline code**: Drive→cloud-storage sync, PDF/Word parser, document
  indexing, and an evaluation harness.
- Built a **working local demo**: open-source model **Mistral** (via Ollama) + semantic
  search, running on a laptop, English/Spanish toggle, answers with citations.
- Loaded **4 real municipal plans** (Adjuntas, Aguada, Aguadilla — recovery + mitigation)
  and tested with 5 questions. It answers correctly and won't invent facts.
- Produced a **cost estimate** (verified: database ~$53/mo; MVP ~$70–110/mo) — shareable page.
- Wrote setup/planning **docs** and pushed all code to **GitHub (PR #1)**.

### 🔄 In progress / awaiting others
- **Platform name** — team + La Maraña deciding (MAPPA vs. alternatives).
- **Data dictionaries & data-quality list** — La Maraña finalizing (priority layer list received).

### ⛔ Blocked
- **GCP project creation** — NYU org policy blocks our account from creating projects.
  Waiting on NYU IT (Shenlong) to create `mappa-lamarana` + grant access. *Everything
  cloud-related waits on this.*

### ⏭️ Next (once unblocked)
- Create the GCP project → migrate Drive data → load the full document corpus → connect maps.
- Build the **click-a-municipality** map interaction (location-aware answers).
- Fold the **priority layer list** into the ingestion plan; show each layer's date + reliability flag.

---

## Key decisions (log)
| Date | Decision |
|---|---|
| 2026-07-14 | "Train the model" = build the RAG pipeline, **not** fine-tune. LLM is a swappable narration layer. |
| 2026-07-14 | Build for **La Maraña ownership**; GCP project owned by them, NYU billing (ClimateIQ chartfield) during build. |
| 2026-07-16 | Model = open-source **Mistral** for the local demo (matches the ownership goal). |
| 2026-07-24 | Reference spatial unit = **municipio** (barrios/parcels later). |
| 2026-07-28 | Domain = **mappapr.org** (verified available); platform name still open. |

## Open dependencies
- **GCP access** — NYU IT to create the project (blocker).
- **Full data dictionaries + data-quality list** — La Maraña (priority layers received).
- **Regulatory PDFs** — received (inventory + Drive folder).
- **Platform name** — team/marketing decision.

---

## Where everything lives (so nobody loses track)

**Code — GitHub**
- Repo: `UrbanSystemsLab/mappa` (private)
- Latest work: PR #1 — https://github.com/UrbanSystemsLab/mappa/pull/1

**Docs (in the repo, `docs/`)**
- `NEXT_STEPS.md` — the full roadmap (RAG pipeline + GCP architecture).
- `GCP_SETUP_AND_COST.md` — ownership/handoff model + full cost estimate.
- `SETUP_RUNBOOK.md` — step-by-step cloud setup (7 phases).
- `RUN_LOCAL.md` — how to run the local demo.
- `WEEKLY_UPDATES.md` — this file.

**Pipelines (in the repo, `pipelines/`)**
- `sync_drive.py` (Drive→storage), `parse_documents.py` (PDF/Word→text),
  `ingest_documents.py` (index), `build_eval_set.py` + `run_eval.py` (quality checks).

**Local demo**
- Run: `ollama serve` + `./venv/bin/uvicorn api.main:app --port 8000` → http://127.0.0.1:8000
- Corpus: `data/documents.json` + `data/drive_docs.json` + `data/planning_docs.json`.

**Cost estimate (shareable page)**
- https://claude.ai/code/artifact/810458d4-aa1f-4613-936f-ac90e9be3086 (open + Share before sending)

**Drive data (source of truth)**
- Master doc inventory (Google Sheet): `1zC5g6KnULR_jrAQedSM2OLXlecEl2NMH`
- Planning PDFs folder: `1KwTUP7IvGUVVB9B_Cm7Kr3vYJuKMr7DJ`
- GIS layers: `Capas GIS / CAPAS GIS FINAL`

**Compute / infra**
- GCP: pending project creation. (LLM hosting = pay-per-use API or GCP GPU — not HPC.)

---

## Weekly log

### Week of 2026-07-28
- Received La Maraña's **priority layer list** (16 layers) and the **planning-doc inventory + PDFs**.
- Confirmed **municipio** as the reference unit; picked **mappapr.org** (verified available).
- Loaded **4 real municipal plans** into the local demo and validated answers with citations.
- Pushed all code to GitHub (**PR #1**); produced the verified cost estimate.
- **Still blocked:** GCP project creation (NYU IT).

### Week of 2026-07-21
- Built the local LLM demo (Mistral via Ollama) and wired it into the API with citations.
- Verified the database cost in Google's calculator (~$52.71/mo).
- Attempted GCP project creation → blocked by NYU org permissions; drafted IT request.

### Week of 2026-07-14
- Reviewed codebase; wrote pipeline code + planning/cost/ownership docs.
- Inventoried Drive data; confirmed RAG (not fine-tuning) approach.

<!-- Add a new dated section at the top of this log each week. -->
