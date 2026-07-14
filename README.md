# Mappa — MVP

Bilingual, location-aware question-answering system for Puerto Rico resilience planning.
Built for a partner organization working on community planning and hazard resilience.

Status: MVP scaffold. Backend + retrieval + ingestion pipelines in place.
Frontend and LLM narration wired in later phases.

---

## What Mappa does

Users ask place-based planning questions in Spanish (e.g. *"¿Puedo construir en zona
inundable cerca del río en Ponce?"*). Mappa:

1. Extracts geographic context (municipality, address, coordinates).
2. Retrieves relevant planning documents using semantic search, filtered by location.
3. Runs spatial queries against Puerto Rico GIS layers (flood, zoning, hospitals, shelters, etc.).
4. Passes the assembled evidence to a language model for grounded, cited narration.
5. Returns a Spanish-language answer with source citations and suggested map layers.

The language model is treated as an interchangeable narration layer. The engineering
value is in retrieval quality, spatial reasoning, and context assembly.

---

## Repository layout

```
mappa/
├── api/                    FastAPI backend (POST /ask endpoint)
├── pipelines/              Data ingestion + evaluation scripts
│   ├── ingest_documents.py    Chunk + embed documents into Postgres
│   └── ingest_spatial.py      Load GeoPackage layers into PostGIS
├── db/
│   ├── schema.sql             Postgres schema (documents, chunks, spatial_layers, reference_units)
│   └── Dockerfile             Postgres 16 + PostGIS 3.4 + pgvector
├── data/
│   ├── documents.json         Sample document corpus (8 docs for scaffolding)
│   └── raw/                   Source spatial files (git-ignored)
├── frontend/               Static UI (used later)
├── docs/                   Planning documents (Word)
├── docker-compose.yml      Local Postgres via Docker
├── requirements.txt
└── README.md
```

---

## Prerequisites

- Python 3.11+
- Docker Desktop (for local Postgres) — or a managed Postgres (Cloud SQL) with PostGIS + pgvector enabled
- GDAL command-line tools (`brew install gdal` on macOS) — needed for spatial ingestion

---

## Local setup

```bash
# 1. Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Start the local database
docker compose up -d
# Postgres available at localhost:5433
# The schema is loaded automatically on first start.

# 3. Export the database URL
export DATABASE_URL="postgresql://mappa:mappa@localhost:5433/mappa"

# 4. Ingest the sample document corpus
python -m pipelines.ingest_documents --commit

# 5. (Optional) Ingest a few spatial layers from the partner GeoPackage
#    Place the .gpkg at data/raw/la_marana.gpkg first.
python -m pipelines.ingest_spatial \
    --source data/raw/la_marana.gpkg \
    --layer g03_legales_municipios_2015 \
    --layer barrios_2015_geoid_corrected_16_nov17 \
    --commit

# 6. Run the API
uvicorn api.main:app --reload
# Test:
curl -s http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"¿Puedo construir en zona inundable?"}'
```

---

## Environment variables

| Variable       | Purpose                                                       | Required for                |
|---------------|---------------------------------------------------------------|-----------------------------|
| `DATABASE_URL` | Postgres connection string                                    | Ingestion pipelines, API    |
| `EMBED_MODEL`  | Override embedding model name (default: multilingual MiniLM)  | Optional                    |
| `OGR2OGR_BIN`  | Path to `ogr2ogr` binary if not on `PATH`                     | Optional                    |

---

## Data pipeline overview

### Documents
`pipelines/ingest_documents.py` reads a JSON corpus, splits each document into
~400-token sentence-aware chunks with a small overlap, computes multilingual
embeddings (384-dim), and stores rows in `documents` + `document_chunks`. Each
chunk carries location tags for later location-aware filtering.

### Spatial layers
`pipelines/ingest_spatial.py` reads metadata directly from a GeoPackage using
SQLite, then delegates the actual load to `ogr2ogr`, which handles CRS
reprojection (source → EPSG:4326) and attribute mapping. Each layer becomes its
own table `layer_<layer_name>` in Postgres, and a summary row is stored in
`spatial_layers` for cataloguing.

### Reference units
`reference_units` holds canonical location identifiers (municipios, barrios, or
whichever unit the partner organization confirms). Documents and query points
are matched against this table for location-aware retrieval.

---

## Architecture (current MVP)

```
User query (Spanish)
    │
    ▼
FastAPI /ask endpoint
    │
    ├── Semantic retrieval over document_chunks (pgvector cosine similarity)
    ├── Location tag filter (once implemented)
    ├── Spatial queries against layer_* tables (PostGIS)
    │
    ▼
Templated composition (current) → LLM narration (next phase)
    │
    ▼
Response: answer + citations + suggested_layers + confidence + disclaimer
```

The current retrieval uses `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
for embeddings. Alternative models will be benchmarked against a Spanish-language
evaluation set in a later phase.

---

## Deployment target

The MVP is designed to run on GCP:

- **Cloud SQL for PostgreSQL** with PostGIS + pgvector for the database.
- **Cloud Storage** for source spatial files and PDFs.
- **Cloud Run** for the FastAPI application.
- **Vertex AI (Gemini)** or a provider API (Claude, Mistral) for LLM narration.

Local `docker-compose.yml` is provided for development and matches the Cloud
SQL schema.

---

## Roadmap (short)

- Week 1–2: Database schema + ingestion pipelines *(done)*.
- Week 3: Load 5 priority spatial layers + one spatial tool (point → municipality).
- Week 4: Add location filter to document retrieval.
- Week 5: Wire in LLM narration (provider or open-weight — benchmarked, not locked in).
- Week 6+: Frontend integration, evaluation harness (100-question test set,
  precision/recall/geographic-relevance metrics), partner-team qualitative
  evaluation loop.

---

## Contributing

This is an early-stage internal project. Reach out to the maintainers before
opening large PRs.
