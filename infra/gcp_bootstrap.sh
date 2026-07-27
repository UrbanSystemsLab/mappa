#!/usr/bin/env bash
# Mappa — GCP bootstrap
#
# Provisions the RAG data-pipeline infrastructure, built for LA MARAÑA OWNERSHIP
# (see docs/GCP_SETUP_AND_COST.md). NYU builds it; La Maraña owns the project.
#   - Enables required APIs
#   - Cloud SQL for PostgreSQL 16 with PostGIS + pgvector
#   - GCS raw/processed buckets (versioned)
#   - A least-privilege pipeline service account
#   - Grants La Maraña's account the Owner role (handoff-ready)
#
# This is a one-shot bootstrap. It is idempotent where the gcloud API allows it
# (creates are guarded), but REVIEW the variables below before running, and run
# the steps interactively the first time rather than piping to bash blind.
#
# Prereqs: gcloud CLI authenticated (`gcloud auth login`), billing enabled.
# Billing note: during the build, link this project to NYU's billing account (so
# NYU credits apply). At handoff, La Maraña attaches their own billing account and
# NYU members are removed — the project, data, and config transfer as-is.
#
# Usage:
#   Review vars → export overrides → `bash infra/gcp_bootstrap.sh`
set -euo pipefail

# ----------------------------------------------------------------------------
# Config — override via environment before running.
# ----------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:?set PROJECT_ID (e.g. export PROJECT_ID=mappa-lamarana)}"
REGION="${REGION:-us-central1}"
# La Maraña's Google account — becomes the permanent project Owner (handoff).
# We grant a ROLE to this email; we never need or store its password.
LAMARANA_OWNER_EMAIL="${LAMARANA_OWNER_EMAIL:-prsostenible@lamarana.org}"
# Cost lever: db-g1-small (~$30-45/mo, build tier) vs db-custom-2-7680 (beta).
DB_TIER="${DB_TIER:-db-g1-small}"
DB_INSTANCE="${DB_INSTANCE:-mappa-pg}"
DB_NAME="${DB_NAME:-mappa}"
DB_USER="${DB_USER:-mappa}"
DB_VERSION="${DB_VERSION:-POSTGRES_16}"
RAW_BUCKET="${RAW_BUCKET:-${PROJECT_ID}-mappa-raw}"
PROC_BUCKET="${PROC_BUCKET:-${PROJECT_ID}-mappa-processed}"
SA_NAME="${SA_NAME:-mappa-pipeline}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo ">> Project: $PROJECT_ID  Region: $REGION"
gcloud config set project "$PROJECT_ID"

# ----------------------------------------------------------------------------
# 1. Enable APIs
# ----------------------------------------------------------------------------
echo ">> Enabling APIs"
gcloud services enable \
  sqladmin.googleapis.com \
  run.googleapis.com \
  storage.googleapis.com \
  aiplatform.googleapis.com \
  drive.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com

# ----------------------------------------------------------------------------
# 2. GCS buckets (two-zone: raw immutable, processed derived). Versioned.
# ----------------------------------------------------------------------------
for BUCKET in "$RAW_BUCKET" "$PROC_BUCKET"; do
  if gsutil ls -b "gs://${BUCKET}" >/dev/null 2>&1; then
    echo ">> Bucket gs://${BUCKET} exists"
  else
    echo ">> Creating gs://${BUCKET}"
    gcloud storage buckets create "gs://${BUCKET}" \
      --location="$REGION" --uniform-bucket-level-access
    gcloud storage buckets update "gs://${BUCKET}" --versioning
  fi
done

# ----------------------------------------------------------------------------
# 3. Cloud SQL Postgres with PostGIS + pgvector
#    NOTE: extensions are enabled from db/schema.sql (CREATE EXTENSION ...).
#    Cloud SQL supports postgis and vector on Postgres 16.
# ----------------------------------------------------------------------------
if gcloud sql instances describe "$DB_INSTANCE" >/dev/null 2>&1; then
  echo ">> Cloud SQL instance $DB_INSTANCE exists"
else
  echo ">> Creating Cloud SQL instance $DB_INSTANCE (this takes several minutes)"
  gcloud sql instances create "$DB_INSTANCE" \
    --database-version="$DB_VERSION" \
    --tier="$DB_TIER" \
    --region="$REGION" \
    --storage-auto-increase \
    --database-flags=cloudsql.enable_pgvector=on
fi

echo ">> Ensuring database + user exist"
gcloud sql databases create "$DB_NAME" --instance="$DB_INSTANCE" 2>/dev/null \
  || echo "   database $DB_NAME already present"

if ! gcloud sql users list --instance="$DB_INSTANCE" --format="value(name)" | grep -qx "$DB_USER"; then
  DB_PASSWORD="$(openssl rand -base64 24)"
  gcloud sql users create "$DB_USER" --instance="$DB_INSTANCE" --password="$DB_PASSWORD"
  echo ">> Storing DB password in Secret Manager: mappa-db-password"
  printf '%s' "$DB_PASSWORD" | gcloud secrets create mappa-db-password --data-file=- 2>/dev/null \
    || printf '%s' "$DB_PASSWORD" | gcloud secrets versions add mappa-db-password --data-file=-
else
  echo ">> DB user $DB_USER already exists (password unchanged)"
fi

# ----------------------------------------------------------------------------
# 4. Pipeline service account (least privilege)
# ----------------------------------------------------------------------------
if gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
  echo ">> Service account $SA_EMAIL exists"
else
  echo ">> Creating service account $SA_EMAIL"
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="Mappa data pipeline"
fi

echo ">> Granting roles to $SA_EMAIL"
for ROLE in roles/cloudsql.client roles/storage.objectAdmin roles/aiplatform.user roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" --role="$ROLE" --condition=None >/dev/null
done

# ----------------------------------------------------------------------------
# 5. Ownership — grant La Maraña's account Owner (handoff-ready).
#    We grant a role to their email; their password is never needed or stored.
# ----------------------------------------------------------------------------
echo ">> Granting Owner to $LAMARANA_OWNER_EMAIL (La Maraña)"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="user:${LAMARANA_OWNER_EMAIL}" --role="roles/owner" --condition=None >/dev/null
echo ">> NOTE: add NYU builders as Editors manually, e.g.:"
echo "     gcloud projects add-iam-policy-binding $PROJECT_ID --member='user:you@nyu.edu' --role='roles/editor'"

cat <<EOF

============================================================
Bootstrap complete.

Next:
  1. Load the schema (from a machine that can reach the instance,
     e.g. via the Cloud SQL Auth Proxy):
       cloud-sql-proxy ${PROJECT_ID}:${REGION}:${DB_INSTANCE} &
       export DATABASE_URL="postgresql://${DB_USER}:<password>@127.0.0.1:5432/${DB_NAME}"
       psql "\$DATABASE_URL" -f db/schema.sql

  2. Grant the Drive shared-folder Viewer access to:
       ${SA_EMAIL}
     then run pipelines/sync_drive.py.

  3. Buckets:
       raw:       gs://${RAW_BUCKET}
       processed: gs://${PROC_BUCKET}

  DB password is in Secret Manager (mappa-db-password):
    gcloud secrets versions access latest --secret=mappa-db-password
============================================================
EOF
