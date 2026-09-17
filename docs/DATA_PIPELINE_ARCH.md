# MAPPA — Data Pipeline Architecture

Goal: get all source data (documents + spatial + metadata) from Drive into the cloud,
keep it current as new data arrives, and make it easy to add or change sources without
rewriting code.

## Two decoupled stages

```
  Google Drive (source of truth, La Maraña edits here)
        │
        │  STAGE 1 — ACQUIRE   (pipelines/sync_drive.py, config-driven, incremental)
        ▼
  gs://…-raw/                      ← faithful mirror of Drive
     documents/   spatial/   metadata/
        │
        │  STAGE 2 — PROCESS+LOAD  (parse / embed / load; per data type)
        ▼
  Cloud SQL (PostGIS + pgvector)   +   gs://…-processed/ (derived + backups)
        │
        ▼
  API (Cloud Run)  →  map + chat
```

**Why two stages:** acquiring (copying from Drive) and processing (parsing, embedding,
loading) change for different reasons and at different speeds. Keeping them separate means
we can re-run one without the other, and swap either without touching the other.

## Stage 1 — Acquire (Drive → bucket)

- **Config-driven:** every source is one entry in [`pipelines/sources.json`](../pipelines/sources.json)
  (Drive folder id → bucket prefix → type). **Adding or changing a source = edit that file, no code change.**
- **Tree-faithful:** mirrors the Drive folder structure exactly, so multi-file datasets
  (shapefiles, `.gdb`, `.gpkg`) stay intact.
- **Incremental:** skips files whose content is unchanged (md5 match) — so re-runs only move
  new/changed data. This is what makes "pull whenever new data comes in" cheap to repeat.
- **Run:** `python -m pipelines.sync_drive --config pipelines/sources.json --commit`

## Stage 2 — Process + Load (bucket → database)

- **Documents:** `parse_documents.py` (PDF/DOCX → text) → `ingest_documents.py` (chunk + embed → `document_chunks`).
- **Spatial:** `ingest_spatial.py` (GeoPackage/shapefile/`.gdb` → PostGIS `layer_*` tables via ogr2ogr).
- **Metadata / data dictionaries:** loaded into `spatial_layers` / `reference_units` (mapping phase, next).
- Each data **type has its own processor**, so adding a new type = add one processor; existing ones are untouched.

## Automation ("whenever new data comes in")

Drive doesn't push notifications cleanly, so the practical pattern is **scheduled polling**
(incremental, so it's cheap):

```
Cloud Scheduler (e.g. nightly)  →  Cloud Run Job (runs sync_drive --config)
                                    →  then the process/load step for anything new
```

Because Stage 1 is incremental, a nightly run only moves what actually changed. We can tighten
or loosen the schedule freely. (Set this up once the access prerequisites below are met.)

## Extending it later — the easy-change design

| To… | Do this |
|---|---|
| Add a new Drive folder / dataset | Add one entry to `sources.json` |
| Change where something lands | Edit that entry's `prefix` |
| Support a new file type | Add a processor in Stage 2; Stage 1 already copies anything |
| Change the schedule | Edit the Cloud Scheduler cron |

## Prerequisites to turn on the *automated* pipeline

The code is ready; automation needs two access grants we can't self-serve:

1. **La Maraña** (folder owner) shares the Drive folders with the pipeline service account —
   `mappa-pipeline@mappa-lamarana-aecc.iam.gserviceaccount.com` (Viewer). Without this, an
   unattended service account can't read Drive.
2. **NYU IT / project admin (Minh)** grants that service account, at the project level:
   - `roles/cloudsql.client` (so the load step can reach the database),
   - `roles/secretmanager.secretAccessor` (so it can read the DB password secret).
   (Our group role can create the SA and grant bucket access, but not project-level IAM.)

## Current state (2026-08-04)

- ✅ Buckets created: `…-raw`, `…-processed` (versioned).
- ✅ In `…-raw`: `spatial/la_marana.gpkg` (3 GB, 108 layers) + `documents/planning/*.pdf` (4 plans).
- ✅ DB backup in `…-processed/backups/`.
- ✅ Config-driven `sync_drive.py` + `sources.json` ready.
- ✅ Pipeline service account created + granted bucket access.
- ⛔ Full/automated Drive sync waits on the two grants above.
