# Run Mappa on your laptop

Use this to check a change before it goes to staging or production.

## Once

- Python 3.12 virtual environment at `./venv` with `pip install -r requirements.txt`.
- `gcloud auth application-default login` (the assistant uses Gemini on Vertex AI).
- [cloud-sql-proxy](https://cloud.google.com/sql/docs/postgres/sql-proxy) installed.
- The database password in `.mappa_db_pw` at the repo root. It is git-ignored; never commit it.

## Each time

```bash
cloud-sql-proxy mappa-lamarana-aecc:us-central1:mappa-pg --port 5432   # leave running
./scripts/run_local.sh                                                 # second terminal
```

Open http://127.0.0.1:8765. The page shows a LOCAL banner.

`run_local.sh` uses the **staging** database (`mappa_staging`), so nothing you do locally
can change live data. `./scripts/run_local.sh production` reads the live database instead;
use it only to look, never to run pipelines.

## Checking a change

```bash
./venv/bin/python -m pytest tests/unit                         # no database needed
./venv/bin/python -m pytest tests/integration tests/e2e         # needs the proxy and the local server
./venv/bin/python -m pipelines.eval_answers --url http://127.0.0.1:8765 --label mine
./venv/bin/python -m pipelines.eval_answers --compare before mine
```

The evaluation asks the 100 questions in `data/eval/questions_100.tsv` and refuses to run
against production.

## Where things are

- How the code fits together: [ARCHITECTURE.md](ARCHITECTURE.md)
- The HTTP API, for any frontend: [API.md](API.md)
- Releasing to staging and production: [RELEASING.md](RELEASING.md)
