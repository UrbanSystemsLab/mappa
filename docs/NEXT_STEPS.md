# Mappa — Next Steps: RAG Data Pipeline + GCP

**Scope decision (2026-07-14):** "Train the model" = build the **retrieval-augmented
generation (RAG) data pipeline** that feeds an off-the-shelf hosted LLM (Mistral /
Gemini / Claude) at inference time. **No GPU fine-tuning.** Model weights do not change.
This matches the strategy in [mapa_llm_plan.docx](mapa_llm_plan.docx): the LLM is an
interchangeable narration layer; the engineering value is in retrieval quality, spatial
reasoning, and context assembly.

"LLM training data" in this project therefore means three concrete artifacts:
1. **The retrieval corpus** — parsed, chunked, embedded planning documents in pgvector.
2. **The spatial layers** — GeoPackage/tabular data in PostGIS for spatial indicators.
3. **The eval set** — bilingual labeled Q&A pairs used to measure retrieval + answer quality
   (and, if fine-tuning is ever revisited, the seed for an instruction dataset).

Fine-tuning is **explicitly deferred** until RAG is proven against the eval set. Revisit
only if retrieval + a hosted model provably cannot hit quality targets. See "Deferred".

---

## What's actually in Drive (inventoried 2026-07-14)

Source folder: `1KUiyOWsO5e2DBHj3fiYJaf1LJZPQkdSt`. Contents span all four data types,
but the GIS data is **large, mixed-format, and only partly curated**:

- **Planning / research docs** — Google Docs: PRD (La Maraña Geospatial Assistant),
  Technical Stack, PR LLM Design Considerations, user research, surveys, project briefs.
  These are *product* docs; the *regulatory* corpus (Plan de Uso, Reglamento Conjunto,
  FIRM, etc.) is referenced but the machine-readable PDFs are a still-open dependency.
- **GIS** — under `Capas GIS/GIS/` and the curated `Capas GIS/CAPAS GIS FINAL/`. Dozens
  of layers in **shapefile** (multi-file), **Esri `.gdb`** (proprietary), **ArcGIS
  `.lpkx`**, **GeoPackage**, and **zipped** form. Many folders are duplicated or flagged
  `INCOMPLETO`. **Treat `CAPAS GIS FINAL/` as the source of truth.**
- **Tabular** — `Deslizamientos_rainfall-induced_*.csv`, plus `.dbf` attribute tables.
- **Data dictionary** — `Inventario_Territorial_Docs_GIS.xlsx`, `Data dictionary_NHDPLUS…`,
  and a **"Basic Layers MVP"** sheet. The MVP sheet defines the target layer taxonomy
  (Political / Natural / Planning / Risks / Social / Infrastructure) but its metadata
  cells (CRS, source, dates, attribute defs) are **empty** — this is the "final data
  dictionary" partner dependency, still unmet.

The MVP layer taxonomy, mapped to the folders that actually exist (with format + status
+ priority), is seeded in [`../data/mvp_layers.csv`](../data/mvp_layers.csv). That file
is both the ingestion work-list and the skeleton for the data dictionary.

**Format handling this implies:**
- Shapefiles / GeoPackage / zipped shapefiles → `ogr2ogr` directly (existing pipeline).
- Esri `.gdb` → readable via GDAL's OpenFileGDB driver; convert to GPKG on ingest.
- ArcGIS `.lpkx` → **not** OGR-readable; unzip and extract the contained layer first.
- Because shapefiles and `.gdb`/`.lpkx` are multi-file, the Drive sync **mirrors the
  tree faithfully** (never flattens) — see `pipelines/sync_drive.py`.

---

## Target architecture (GCP)

```
Google Drive (source of truth: PDFs, DOCX, GPKG, CSV/XLSX, labeled Q&A)
    │  pipelines/sync_drive.py  (service account, scheduled)
    ▼
GCS bucket: gs://mappa-raw/           ← immutable raw zone (versioned)
    │
    ├── documents/*.pdf, *.docx
    ├── spatial/*.gpkg, *.shp, *.tif
    ├── tabular/*.csv, *.xlsx
    └── eval/*.jsonl                   ← labeled Q&A
    │
    ▼  parse + normalize
GCS bucket: gs://mappa-processed/      ← parsed zone
    ├── corpus/*.json                  ← documents.json-shaped, one per source doc
    └── eval/eval_set.jsonl            ← validated
    │
    ├── pipelines/parse_documents.py  (PDF/DOCX → corpus JSON)
    ├── pipelines/ingest_documents.py (chunk → embed → pgvector)   [EXISTS]
    ├── pipelines/ingest_spatial.py   (GPKG → PostGIS)             [EXISTS]
    └── pipelines/ingest_tabular.py   (CSV/XLSX → reference_units / indicators) [TODO]
    │
    ▼
Cloud SQL for PostgreSQL 16 (PostGIS + pgvector)
    │
    ▼
Cloud Run: FastAPI /ask  → retrieval + spatial indicators + LLM narration
    │
    ▼
Vertex AI (Gemini) or Mistral/Claude API   ← narration layer, benchmarked not locked
```

Buckets are two-zone (raw immutable, processed derived) so any parse/embed step is
fully reproducible from raw. Everything downstream of `gs://mappa-raw/` can be rebuilt.

---

## Projects (sequenced)

Each is a self-contained unit of work with a clear "done" bar. P0 items unblock the
end-to-end demo; P1 improves quality; P2 hardens for beta.

### P0 — Stand up the pipeline end-to-end on real data

**1. GCP project + infra bootstrap**  — `infra/gcp_bootstrap.sh`
- Enable APIs (Cloud SQL, Run, Storage, Vertex AI, Drive, Secret Manager).
- Cloud SQL Postgres 16 instance with PostGIS + pgvector; load `db/schema.sql`.
- GCS buckets `mappa-raw`, `mappa-processed` (versioning on).
- Service account `mappa-pipeline@` with least-privilege roles.
- Done when: `psql "$DATABASE_URL"` connects to Cloud SQL and extensions exist.

**2. Drive → GCS sync**  — `pipelines/sync_drive.py`
- Service-account access to the shared Drive folder; mirror to `gs://mappa-raw/`,
  sorted into `documents/ spatial/ tabular/ eval/` by MIME type.
- Idempotent (skip unchanged by md5/modifiedTime); log dropped/unknown types.
- Done when: raw bucket mirrors Drive and re-running is a no-op.
- **Blocker:** shared-drive folder ID + a service account with Viewer on it. The
  claude.ai Drive connector (currently expired) is fine for exploration but **not**
  for the production pipeline — use a service account.

**3. Document parsing**  — `pipelines/parse_documents.py`
- PDF (PyMuPDF) + DOCX (python-docx) → normalized corpus JSON matching
  `data/documents.json` schema (`id, title, jurisdiction, doc_type, year, url, tags,
  text, language`). Per-page text retained for citation page numbers.
- Metadata from an optional sidecar `<file>.meta.json` or a `manifest.csv`; sensible
  defaults + a warnings report for missing fields.
- Done when: N partner PDFs → N corpus JSON files that `ingest_documents.py` accepts.

**4. Point ingestion at Cloud SQL + scale corpus**
- `ingest_documents.py` already chunks + embeds + upserts. Run it against Cloud SQL
  with the parsed corpus (not the 8 samples).
- Done when: `document_chunks` populated with real docs; HNSW search returns them.

**5. LLM narration**  — `api/llm.py` + wire into `api/retrieval.py::compose_answer`
- Replace the templated composition with a real LLM call over the assembled context
  (retrieved chunks + spatial indicators). Provider behind an interface so
  Mistral/Gemini/Claude are swappable. Enforce citation-grounding: answer may only cite
  retrieved chunk ids; refuse when evidence is thin.
- Done when: `/ask` returns an LLM-narrated, cited Spanish answer end-to-end.

### P1 — Quality

**6. Tabular ingestion**  — `pipelines/ingest_tabular.py` (CSV/XLSX/DBF → `reference_units` / indicators).
**7. GIS curation + ingest** — work the [`mvp_layers.csv`](../data/mvp_layers.csv) list against
`CAPAS GIS FINAL/`: dedupe vs `INCOMPLETO`/duplicate folders, convert `.gdb`/`.lpkx` → GPKG,
group shapefile sidecars, then run `ingest_spatial.py` on the `status=ready` P0/P1 rows and
tag `spatial_layers.theme`. Generalize `ingest_spatial.read_layer_metadata` beyond GeoPackage
(it currently reads gpkg SQLite tables only) — use `ogrinfo`/GDAL so shapefiles and `.gdb`
report metadata too. **Confirm the reference spatial unit** (municipio/barrio/parcel) — that
row becomes `reference_units`.
**8. Location-aware retrieval** — extract geographic constraint from query; spatial pre-filter on `location_tags` / `reference_units` before/with vector search.
**9. Eval harness** — `pipelines/build_eval_set.py` + `pipelines/run_eval.py`: retrieval metrics (recall@k, MRR) + answer checks against the labeled Q&A. This is where the Drive "labeled Q&A" pays off.
**10. Embedding model benchmark** — compare multilingual MiniLM vs. larger Spanish-capable embedders on the eval set. (LLM-specialist call per plan; harness makes it measurable.)

### P2 — Harden for beta (April 2027)

- Cloud Run deploy + CI; secrets in Secret Manager.
- Scheduled Drive→GCS→ingest refresh (Cloud Scheduler + a job).
- Cost/latency tuning; caching of embeddings and LLM calls.
- Policy–condition alignment reasoning (deferred design; needs lead eng / LLM specialist).

---

## Immediate next actions (this week)

1. Create the GCP project and run `infra/gcp_bootstrap.sh` (review vars first), then grant
   the pipeline service account Viewer on Drive folder `1KUiyOWsO5e2DBHj3fiYJaf1LJZPQkdSt`.
2. Run `sync_drive.py --folder-id 1KUiyOWsO5e2DBHj3fiYJaf1LJZPQkdSt` (dry run first) to
   mirror Drive → `gs://…-raw/`, then spot-check that shapefiles and `.gdb`/`.lpkx`
   folders came across intact.
3. **Push the partner to fill the "Basic Layers MVP" data dictionary** (CRS, source, dates,
   attribute defs are all empty) — it is a listed dependency and blocks reliable spatial
   ingest + attribute-aware retrieval.
4. Confirm the **reference spatial unit** with the partner (municipio / barrio / parcel).
   `Municipios_2015`, `BARRIOS_Corrected_2015`, and `ParcelarioCRIM-PR` are all present in
   Drive, so this is a decision, not a data gap. Blocks location-aware retrieval (Project 8).
5. Choose the **narration provider** for the first wired demo (Vertex AI Gemini is the
   path of least resistance on GCP; Mistral endpoint keeps to the ownership goal). Not
   locked in — the interface in Project 5 keeps it swappable.

---

## Deferred: fine-tuning (do NOT start yet)

If revisited, the path is: curate an instruction dataset from the eval set (Spanish
question → grounded, cited answer), LoRA/QLoRA on Vertex AI custom training, eval the
adapter vs. the base model **on the same harness** as RAG. Only worth it if RAG
provably plateaus below quality targets. The eval set built in Project 9 is the seed, so
building it now serves both paths — no wasted work.

---

## Open dependencies (from the plan, still open)

- Reference spatial unit decision (partner).
- Final data dictionary with include/exclude flags (partner data team).
- LLM specialist role filled (embedding + prompt + eval ownership).
- Lead-engineering sign-off on location-aware retrieval architecture.
