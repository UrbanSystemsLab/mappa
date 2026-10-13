# Releasing Mappa

Every change, code or data, goes to **staging** first and to **production** only
once someone has looked at it there.

```
 commit ──► tests ──► STAGING ──► someone checks it ──► PRODUCTION
                     test copy                          app.mappealo.org
                     mappa_staging database             mappa database
```

| | Staging | Production |
|---|---|---|
| Site | `mappa-staging` on Cloud Run — URL printed by the release | `mappa`, at https://app.mappealo.org |
| Database | `mappa_staging` | `mappa` |
| Same server? | yes — both databases are on `mappa-pg` | |
| Who sees it | anyone with the link; marked **STAGING** on every screen and hidden from search engines | everyone |
| Cost when idle | nothing — it shuts down when unused | always on |

## Releasing

The same flow as climateiq. Once GitHub deploys are switched on (below):

| Do this | GitHub does |
|---|---|
| open a pull request | tests (`ci.yml`); `ci-ok` must pass before merging |
| merge to `main` | tests, then releases to **staging** |
| check the staging site, then push `main` to `release` | releases the same build to **production**, after approval |
| Actions → Deploy → Run workflow | releases a chosen commit to either, by hand |

```bash
git push origin main:release      # promote what staging is running to production
```

Until they are switched on, the same steps run from a laptop:

```bash
./scripts/release.sh staging       # build, test and deploy to staging
# ...check the staging site...
./scripts/release.sh production    # the same build, to the live site
```

Both ways run `scripts/release.sh`. For staging it refuses to run with
uncommitted changes, then:

1. lint and unit tests
2. database migrations on `mappa_staging`
3. loads the data files in `data/` and profiles the layers
4. integration and answer tests against `mappa_staging` - the real data
5. builds the site from the commit and deploys it to `mappa-staging`
6. checks the site answers, including one real question

For production it additionally refuses unless the commit is on `main` or
`release`, is the same as that branch on GitHub, and **is already what staging is
running**. It then asks for confirmation (on a laptop: typing `production`; on
GitHub: the production environment's approval), applies the same database steps
to `mappa`, and deploys **the exact build staging was checked on** - it is not
rebuilt.

## Changing data

Data changes are files in `data/`, reviewed like code, and applied by the
release — never by running a pipeline with `--commit` against the live database.

| File | What it controls |
|---|---|
| `data/layer_roles.csv` | which layer answers which kind of question, and what a map click checks |
| `data/layer_names_en.csv` | English layer names (machine translations of La Maraña's names, until they give their own) |
| `data/lamarana_priority_layers.csv` | La Maraña's prioritization matrix |

## Refreshing staging from production

```bash
./venv/bin/python scripts/copy_prod_to_staging.py
```

Copies the live database into `mappa_staging` on the server itself, in under an
hour, without any Google Cloud permission. The live database is only read, but
the live site may be slower while it runs.

## Switching on GitHub deploys

The workflows are in place (`ci.yml`, `_deploy.yml`, `deploy.yml`); deploys are
skipped until GitHub can sign in to Google Cloud. As for climateiq, that is a
deploy service account whose key is stored in GitHub. A project admin needs to:

1. Create a service account `github-deployer@mappa-lamarana-aecc.iam.gserviceaccount.com`
   with these roles on the project:
   `roles/run.admin`, `roles/cloudbuild.builds.editor`, `roles/artifactregistry.writer`,
   `roles/storage.admin` (the build's source bucket), `roles/cloudsql.client`,
   `roles/secretmanager.secretAccessor`, `roles/aiplatform.user` (the answer tests),
   `roles/serviceusage.serviceUsageConsumer`, `roles/logging.viewer` (build logs),
   `roles/resourcemanager.tagUser`; and `roles/iam.serviceAccountUser` on the
   runtime account `mappa-pipeline@mappa-lamarana-aecc.iam.gserviceaccount.com`.
2. Create a JSON key for it.
3. Make sure the secret `mappa-db-password` exists in Secret Manager (the
   database password for the `mappa` user).

Then, in the GitHub repository settings:

4. Environments: create `staging` and `production`. Add the key as the secret
   `GCP_SA_KEY` in both. On `production`, add a required reviewer.
5. Variables: set `DEPLOY_ENABLED` to `true`.
6. Branches: protect `main` and `release`, requiring the `ci-ok` check.

The current project roles of the people on Mappa are not enough for steps 1-3.
