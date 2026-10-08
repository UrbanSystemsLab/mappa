# Mappa

A bilingual planning assistant for Puerto Rico, built for La Maraña. People ask questions
about their community in Spanish or English and get answers drawn only from La Maraña's
planning documents and map layers, with the sources named and the relevant layers shown
on the map.

Live at https://app.mappealo.org.

## Layout

```
api/          the web service: routers, services, the assistant and its tools, SQL
core/         settings and shared constants
frontend/     the web app (plain JavaScript + MapLibre)
pipelines/    scripts that load and prepare data, and the answer evaluation
migrations/   database structure (Alembic)
scripts/      run locally, copy production to staging, release
tests/        unit, integration (database) and end-to-end (answers)
docs/         see below
```

## Documentation

- [docs/ENGINEERING_LOG.md](docs/ENGINEERING_LOG.md): what changed, when and why - the running record
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the parts fit, and what happens to a question
- [docs/API.md](docs/API.md): the HTTP API, for this or any other frontend ([openapi.json](docs/openapi.json))
- [docs/RUN_LOCAL.md](docs/RUN_LOCAL.md): run it on a laptop
- [docs/RELEASING.md](docs/RELEASING.md): staging and production
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md): the database tables
- [docs/DATA_GAPS.md](docs/DATA_GAPS.md): which layers and metadata are still missing

## Quick start

```bash
python3.12 -m venv venv && ./venv/bin/pip install -r requirements.txt
cloud-sql-proxy mappa-lamarana-aecc:us-central1:mappa-pg --port 5432   # separate terminal
./scripts/run_local.sh                                                 # http://127.0.0.1:8765
./venv/bin/python -m pytest tests/unit
```

## Data

All documents and layers come from La Maraña. Nothing is downloaded from public sites.
