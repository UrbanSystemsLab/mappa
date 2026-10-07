#!/usr/bin/env bash
# Release Mappa: to staging first, then the same thing to production.
#
#   ./scripts/release.sh staging      test copy  -> https://mappa-staging-...run.app
#   ./scripts/release.sh production   live site  -> https://app.mappealo.org
#
# Every change, code or data, takes the same path:
#
#   commit -> tests -> STAGING (database + site) -> someone looks -> PRODUCTION
#
# Production only ever receives the exact build staging is already running, and
# only from main. It cannot be released to directly, and nothing here changes
# the live database unless "production" is typed to confirm.
#
# This runs from a laptop because the project does not yet let GitHub deploy
# (that needs a Google Cloud admin). The steps are the same ones GitHub will run
# once it can; see .github/workflows/release.yml.
set -euo pipefail
cd "$(dirname "$0")/.."

TARGET="${1:-}"
PROJECT=mappa-lamarana-aecc
REGION=us-central1
INSTANCE="$PROJECT:$REGION:mappa-pg"
RUNTIME_SA="mappa-pipeline@$PROJECT.iam.gserviceaccount.com"
PUBLIC_TAG=tagValues/281478759989807   # mappa-public-ingress/true - NYU's exception for public sites

case "$TARGET" in
  staging)    SERVICE=mappa-staging; DB=mappa_staging ;;
  production) SERVICE=mappa;         DB=mappa ;;
  *) echo "Usage: $0 staging|production"; exit 1 ;;
esac

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mSTOPPED: %s\033[0m\n' "$*"; exit 1; }

# --- what is being released ---------------------------------------------------
[ -z "$(git status --porcelain)" ] || fail "there are uncommitted changes. Commit them first, so what is released is a commit anyone can find."
SHA=$(git rev-parse --short HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
nc -z 127.0.0.1 5432 2>/dev/null || fail "the Cloud SQL proxy is not running on port 5432."
DB_URL="postgresql://mappa:$(cat .mappa_db_pw)@127.0.0.1:5432/$DB"

if [ "$TARGET" = production ]; then
  [ "$BRANCH" = main ] || fail "production is released from main only (this is $BRANCH)."
  git fetch -q origin main
  [ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || fail "main here is not the same as main on GitHub. Push or pull first."
  STAGED_SHA=$(gcloud run services describe mappa-staging --region $REGION --project $PROJECT \
                 --format='value(spec.template.metadata.labels.git-sha)' 2>/dev/null || true)
  [ "$STAGED_SHA" = "$SHA" ] || fail "staging is running ${STAGED_SHA:-nothing}, not $SHA. Release this to staging and check it there first."
  IMAGE=$(gcloud run services describe mappa-staging --region $REGION --project $PROJECT \
            --format='value(status.latestReadyRevisionName)' | xargs -I{} \
          gcloud run revisions describe {} --region $REGION --project $PROJECT \
            --format='value(status.imageDigest)')
  echo "Releasing $SHA to PRODUCTION (app.mappealo.org) - the build staging runs:"
  echo "  $IMAGE"
  read -r -p "Type 'production' to continue: " ok
  [ "$ok" = production ] || fail "not confirmed."
fi

# --- 1. tests that need no database --------------------------------------------
say "1/6  Lint and unit tests"
./venv/bin/ruff check api pipelines tests core
./venv/bin/ruff format --check api pipelines tests core
./venv/bin/python -m pytest tests/unit -q

# --- 2. database: structure, then data files -----------------------------------
say "2/6  Database $DB: migrations"
DATABASE_URL="$DB_URL" ./venv/bin/alembic upgrade head

say "3/6  Database $DB: data from the repository's files"
# Each of these reads a reviewed file in data/ and is safe to run again.
DATABASE_URL="$DB_URL" ./venv/bin/python -m pipelines.apply_layer_roles --commit
DATABASE_URL="$DB_URL" ./venv/bin/python -m pipelines.apply_layer_names --commit
DATABASE_URL="$DB_URL" ./venv/bin/python -m pipelines.fill_document_places --commit
DATABASE_URL="$DB_URL" ./venv/bin/python -m pipelines.embed_layers --commit
# What each layer shows when clicked, decided from its own data (a few minutes).
DATABASE_URL="$DB_URL" ./venv/bin/python -m pipelines.profile_layers --commit

say "4/6  Integration tests against $DB"
DATABASE_URL="$DB_URL" ./venv/bin/python -m pytest tests/integration -q
# Known questions through the model itself: the figure and the tool behind it.
DATABASE_URL="$DB_URL" ./venv/bin/python -m pytest tests/e2e -q

# --- 3. the site ---------------------------------------------------------------
say "5/6  Deploying $SHA to $SERVICE"
COMMON=(--region "$REGION" --project "$PROJECT" --labels "git-sha=$SHA,env=$TARGET")
if [ "$TARGET" = staging ]; then
  # Built here, from this commit. Production later reuses this exact build.
  gcloud run deploy "$SERVICE" --source . "${COMMON[@]}" \
    --service-account "$RUNTIME_SA" --add-cloudsql-instances "$INSTANCE" \
    --set-secrets "DATABASE_URL=mappa-database-url:latest" \
    --set-env-vars "APP_ENV=staging,DATABASE_NAME=$DB,LLM_PROVIDER=gemini,GCP_PROJECT=$PROJECT,VERTEX_LOCATION=$REGION,RESPONSE_LANG=en" \
    --cpu 2 --memory 4Gi --concurrency 4 --min-instances 0 --max-instances 3 \
    --allow-unauthenticated --quiet
  # NYU allows a public site only once it carries this tag. On the first deploy
  # the service did not exist yet, so the tag could not be there and opening it
  # to everyone failed - staging answered 403. Tag first, then open it.
  gcloud resource-manager tags bindings create --tag-value="$PUBLIC_TAG" --location="$REGION" \
    --parent="//run.googleapis.com/projects/$PROJECT/locations/$REGION/services/$SERVICE" \
    >/dev/null 2>&1 || true   # already tagged on later deploys
  gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" --project "$PROJECT" \
    --member=allUsers --role=roles/run.invoker --format=none
else
  # Not rebuilt: the exact image staging was checked on.
  gcloud run deploy "$SERVICE" --image "$IMAGE" "${COMMON[@]}" --quiet
fi
URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format='value(status.url)')
[ "$TARGET" = production ] && URL=https://app.mappealo.org

# --- 4. is it actually working -------------------------------------------------
say "6/6  Checking $URL"
for path in /health "/api/v1/catalog/layers?limit=1" "/api/v1/places?q=ponce"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL$path")
  printf '  %-28s %s\n' "$path" "$code"
  [ "$code" = 200 ] || fail "$path returned $code"
done
answer=$(curl -s --max-time 90 -X POST "$URL/api/v1/ask" -H 'Content-Type: application/json' \
          -d '{"question":"How many schools are in Arecibo?","lang":"en"}' |
         ./venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["answer"][:120])')
echo "  a question: $answer"

say "Released $SHA to $TARGET: $URL"
