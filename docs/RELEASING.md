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

```bash
./scripts/release.sh staging       # build, test and deploy to staging
# ...check the staging site...
./scripts/release.sh production    # the same build, to the live site
```

`release.sh staging` refuses to run with uncommitted changes, then:

1. lint and unit tests
2. database migrations on `mappa_staging`
3. loads the data files in `data/` (layer roles, English names, document places)
4. integration tests against `mappa_staging` — the real data
5. builds the site from the commit and deploys it to `mappa-staging`
6. checks the site answers, including one real question

`release.sh production` additionally refuses unless the commit is on `main`, is the
same as `main` on GitHub, and **is already what staging is running**. It then asks
you to type `production`, applies the same database steps to `mappa`, and deploys
**the exact build staging was checked on** — it is not rebuilt.

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

## Letting GitHub release instead of a laptop

`.github/workflows/release.yml` runs the same steps, but GitHub cannot sign in to
Google Cloud yet. A project admin needs to:

1. Create a service account, e.g. `github-deploy@mappa-lamarana-aecc.iam.gserviceaccount.com`,
   with: `roles/run.admin`, `roles/iam.serviceAccountUser` (on `mappa-pipeline`),
   `roles/cloudsql.client`, `roles/secretmanager.secretAccessor`,
   `roles/artifactregistry.writer`, `roles/cloudbuild.builds.editor`,
   `roles/resourcemanager.tagUser`.
2. Create a Workload Identity pool and GitHub provider limited to the repository
   `UrbanSystemsLab/mappa`, and let it impersonate that service account.
3. Add two repository secrets on GitHub: `WIF_PROVIDER` and `DEPLOY_SA`.
4. Create a GitHub environment `production` with a required reviewer.

Nobody currently on the project has the permissions for steps 1–2.
