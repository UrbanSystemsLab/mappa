#!/usr/bin/env bash
# Copy the live database (mappa) into the staging database (mappa_staging).
#
# The copy happens inside Google Cloud: the server exports itself to a storage
# bucket and imports that file into staging. Nothing passes through this laptop,
# which is what made the first attempt take most of a day.
#
# Safe for the live site's data: the live database is only read. The export is
# "serverless" (--offload), run by Google on separate machines, so it does not
# use the live server's CPU. The import does run on the same server, so the
# live site may be a little slower while it lasts - roughly 30-60 minutes.
#
# Run it again any time staging should be refreshed from production; it empties
# staging first.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT=mappa-lamarana-aecc
INSTANCE=mappa-pg
BUCKET=gs://mappa-lamarana-aecc-processed
FILE="$BUCKET/staging-copy/mappa-$(date +%Y%m%d-%H%M).sql.gz"

echo "1/5  Letting the database server write its export to the bucket"
SA=$(gcloud sql instances describe "$INSTANCE" --project "$PROJECT" --format='value(serviceAccountEmailAddress)')
gcloud storage buckets add-iam-policy-binding "$BUCKET" --project "$PROJECT" \
  --member="serviceAccount:$SA" --role=roles/storage.objectAdmin --format=none

echo "2/5  Exporting the live database to $FILE (serverless, does not load the live server)"
# Started in the background and then waited on, because gcloud otherwise gives up
# watching a long operation and returns an error while it is still running.
OP=$(gcloud sql export sql "$INSTANCE" "$FILE" --project "$PROJECT" --database=mappa --offload \
       --async --format='value(name)')
gcloud sql operations wait "$OP" --project "$PROJECT" --timeout=unlimited

echo "3/5  Emptying staging and importing the copy into it (30-60 minutes)"
export PGPASSWORD="$(cat .mappa_db_pw)"
PSQL=/opt/homebrew/opt/libpq/bin/psql
"$PSQL" -h 127.0.0.1 -p 5432 -U mappa -d mappa_staging -q -c \
  "DROP SCHEMA public CASCADE; CREATE SCHEMA public; CREATE EXTENSION IF NOT EXISTS postgis; CREATE EXTENSION IF NOT EXISTS vector;"
OP=$(gcloud sql import sql "$INSTANCE" "$FILE" --project "$PROJECT" --database=mappa_staging \
       --user=mappa --quiet --async --format='value(name)')
gcloud sql operations wait "$OP" --project "$PROJECT" --timeout=unlimited

echo "4/5  Checking the copy"
"$PSQL" -h 127.0.0.1 -p 5432 -U mappa -d mappa -Atc \
  "SELECT 'live:    ' || (SELECT count(*) FROM layer_registry) || ' layers, ' || (SELECT count(*) FROM documents) || ' documents, ' || pg_size_pretty(pg_database_size('mappa'))"
"$PSQL" -h 127.0.0.1 -p 5432 -U mappa -d mappa_staging -Atc \
  "SELECT 'staging: ' || (SELECT count(*) FROM layer_registry) || ' layers, ' || (SELECT count(*) FROM documents) || ' documents, ' || pg_size_pretty(pg_database_size('mappa_staging'))"
echo "5/5  Deleting the temporary export file"
# The file was only the hand-off between the two databases. Keeping it would
# cost about $0.20 a month for nothing.
gcloud storage rm "$FILE" --project "$PROJECT" --quiet && echo "Removed the temporary export file."
echo "Done. Staging is a copy of production as of $(date)."
