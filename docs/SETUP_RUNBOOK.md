# MAPPA — GCP Setup Runbook (step by step)

A checkpointed guide to stand up the whole pipeline on GCP. Do the phases **in order**;
each ends with a ✅ check before moving on. Commands assume macOS + zsh.

Current machine state (verified 2026-07-14): `gcloud`, `docker`, `ogr2ogr` (GDAL),
`python3`, `brew` installed; signed in to gcloud as `rmj7591@nyu.edu`; **no billing
account yet**; missing `psql` and `cloud-sql-proxy`.

Config used throughout (change if you like):
```
PROJECT_ID=mappa-lamarana
REGION=us-central1
```

---

## Phase 0 — Install the two missing tools

```bash
brew install libpq            # provides psql (Postgres client)
brew link --force libpq       # put psql on PATH
brew install cloud-sql-proxy  # secure tunnel to Cloud SQL
```
✅ Check: `psql --version` and `cloud-sql-proxy --version` both print a version.

---

## Phase 1 — Get a billing account (the blocker)

Nothing paid happens here; this just makes services *available*. Options:

- **Fastest (recommended to start): GCP $300 free trial.** Go to
  <https://console.cloud.google.com/freetrial>, sign in as `rmj7591@nyu.edu`, add a card
  (used for identity — it will **not** be charged during the trial). You get a billing
  account with $300 / ~90 days of credit.
- **NYU credits:** the credits Ahmed is requesting attach to a billing account. When they
  land, we switch to that account (see docs/GCP_SETUP_AND_COST.md).

✅ Check: `gcloud billing accounts list` shows one `ACCOUNT_ID` with `OPEN  True`.
Copy that ID — you'll need it in Phase 2.

---

## Phase 2 — Create the MAPPA project

> Ownership note: to start now, Rajan creates the project under his own account. We add
> La Maraña as Owner in Phase 3 and switch billing later — the project transfers as-is.

```bash
gcloud projects create mappa-lamarana --name="MAPPA - La Marana"
gcloud config set project mappa-lamarana

# Link the billing account from Phase 1 (paste its ID):
gcloud billing projects link mappa-lamarana --billing-account=XXXXXX-XXXXXX-XXXXXX
```
✅ Check: `gcloud billing projects describe mappa-lamarana` shows `billingEnabled: true`.

---

## Phase 3 — Bootstrap the infrastructure

This creates: enabled APIs, two Cloud Storage buckets, the **Cloud SQL PostgreSQL
instance with PostGIS + pgvector**, a least-privilege pipeline service account, and grants
La Maraña Owner. Takes several minutes (the database is the slow part).

```bash
export PROJECT_ID=mappa-lamarana
export REGION=us-central1
# DB_TIER defaults to db-g1-small (~$30-45/mo build tier). Override for beta.
bash infra/gcp_bootstrap.sh
```
The script prints the bucket names and stores the DB password in Secret Manager.
✅ Check: it ends with "Bootstrap complete" and
`gcloud sql instances describe mappa-pg` shows `RUNNABLE`.

---

## Phase 4 — Load the database schema

The schema creates the tables and turns on PostGIS + pgvector inside the database.
We reach the cloud database through the proxy (a secure local tunnel).

```bash
# Terminal A — open the tunnel (leave it running):
cloud-sql-proxy mappa-lamarana:us-central1:mappa-pg

# Terminal B — get the password and load the schema:
DB_PW=$(gcloud secrets versions access latest --secret=mappa-db-password)
export DATABASE_URL="postgresql://mappa:${DB_PW}@127.0.0.1:5432/mappa"
psql "$DATABASE_URL" -f db/schema.sql
```
✅ Check: `psql "$DATABASE_URL" -c "\dt"` lists `documents`, `document_chunks`,
`spatial_layers`, `reference_units`.

---

## Phase 5 — Connect Drive → Cloud Storage and copy the data

Give the pipeline's service account read access to the Drive folder, then mirror it.

1. In the Google Drive folder `1KUiyOWsO5e2DBHj3fiYJaf1LJZPQkdSt`, click Share and add
   the service account email (printed by the bootstrap, ends `@mappa-lamarana.iam.gserviceaccount.com`)
   as **Viewer**.
2. Point the pipeline at that service account and mirror:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/mappa-pipeline-key.json   # see note below
export RAW_BUCKET=mappa-lamarana-mappa-raw
python -m pipelines.sync_drive --folder-id 1KUiyOWsO5e2DBHj3fiYJaf1LJZPQkdSt   # dry run
python -m pipelines.sync_drive --folder-id 1KUiyOWsO5e2DBHj3fiYJaf1LJZPQkdSt --commit
```
> Key note: create the key once with
> `gcloud iam service-accounts keys create ~/mappa-pipeline-key.json --iam-account=mappa-pipeline@mappa-lamarana.iam.gserviceaccount.com`
> Treat it like a password; do not commit it (it's covered by .gitignore patterns).

✅ Check: `gcloud storage ls -r gs://mappa-lamarana-mappa-raw | head` shows your files,
and shapefile sidecars / `.gdb` folders arrived together.

---

## Phase 6 — Run the pipelines

```bash
# Documents: parse PDFs/DOCX from the raw mirror → corpus → chunk + embed → Cloud SQL
python -m pipelines.parse_documents --input <local copy of documents/> --output data/corpus
python -m pipelines.ingest_documents --source data/corpus --commit

# Spatial: load priority layers (see data/mvp_layers.csv) into PostGIS
python -m pipelines.ingest_spatial --source <a .gpkg> --layer <name> --commit
```
✅ Check: `psql "$DATABASE_URL" -c "SELECT count(*) FROM document_chunks;"` > 0, and
`SELECT layer_name FROM spatial_layers;` lists what you loaded.

---

## Phase 7 — Verify end to end

```bash
python -m pipelines.build_eval_set --input <labeled Q&A dir> --output data/eval_set.jsonl
python -m pipelines.run_eval --eval data/eval_set.jsonl --k 5
```
✅ Check: prints recall@k and MRR. That confirms retrieval works against real data.

---

## What still needs decisions (not blockers to start)

- **Billing at handoff:** switch to La Maraña's billing account (Phase 1 note).
- **Reference spatial unit** (municipio / barrio / parcel) → fills `reference_units`.
- **Narration provider** (Vertex AI Gemini vs Mistral) for the answer step (later phase).
- **Data dictionary** for the GIS layers (partner) — improves ingest quality.
```
