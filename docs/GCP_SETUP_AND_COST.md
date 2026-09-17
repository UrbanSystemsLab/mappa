# MAPPA — GCP Setup, Ownership & Cost

Covers the tasks Rajan owns: cost estimation, GCP setup, Drive→GCP migration, and
pipeline setup — built from the start for **La Maraña ownership and handoff**.

---

## 1. Ownership & handoff model (the core requirement)

Chris's point: NYU builds it, but **La Maraña must end up owning all of it** — NYU
can't host their data indefinitely. The clean way to do that on GCP is to make the
**GCP project itself the unit of ownership**, owned by La Maraña from day one.

```
GCP Project:  mappa-lamarana   ← owned by La Maraña (prsostenible@lamarana.org = Owner)
   │
   ├── Cloud Storage (raw + processed data)
   ├── Cloud SQL (PostgreSQL + PostGIS + pgvector)
   ├── Cloud Run (the assistant API)
   └── Service accounts + pipelines

Billing account:  NYU's (during build; NYU credits land here)
                  → switched to La Maraña's billing at handoff
```

**Why this works for handoff:** the project holds all the data, config, and services.
Transferring ownership = (a) La Maraña attaches their own billing account, (b) NYU
members are removed from the project. Nothing has to be rebuilt or migrated.

**Roles (IAM) — grant to *emails*, no passwords ever shared:**

| Who | Role | Why |
|---|---|---|
| `prsostenible@lamarana.org` (La Maraña) | **Owner** | Permanent owner; controls the project |
| NYU builders (Rajan, Ahmed) | **Editor** | Build + run pipelines during the project |
| Pipeline service account | Least-privilege (Storage, Cloud SQL, Secrets) | Automated jobs |

At handoff: remove the NYU Editors, switch billing, done. La Maraña keeps everything.

> **Note on credits + ownership.** GCP credits attach to a *billing account*, not a
> project. So during the build we link the La Maraña-owned project to **NYU's billing
> account** (where the requested credits land). At handoff we detach NYU billing and La
> Maraña attaches theirs. This is a standard, clean switch — decide it explicitly with
> Chris/Ahmed so the credits are applied to the right billing account.

---

## 2. Access setup — no password required

You do **not** need La Maraña's password. Steps:

1. Create the project (see `infra/gcp_bootstrap.sh`).
2. In IAM, add `prsostenible@lamarana.org` as **Owner**. They accept the invite and
   log in with their own Google credentials + 2FA.
3. Add NYU builders as **Editor**.
4. Because the password was shared in Slack, ask La Maraña to **rotate it and enable
   2FA** on that account regardless.

---

## 3. Drive → GCP migration (Rajan)

1. Bootstrap the project + buckets (`infra/gcp_bootstrap.sh`).
2. Grant the pipeline service account **Viewer** on Drive folder
   `1KUiyOWsO5e2DBHj3fiYJaf1LJZPQkdSt`.
3. `python -m pipelines.sync_drive --folder-id 1KUiyOWsO5e2DBHj3fiYJaf1LJZPQkdSt`
   (dry run, then `--commit`) → mirrors Drive into `gs://…-raw/`, tree intact.
4. Parse docs → embed → load spatial layers (see [NEXT_STEPS.md](NEXT_STEPS.md)).
5. **Drive stays the master copy** partners edit; GCP holds the working copy the app
   reads. Re-run the sync to refresh.

---

## 4. Monthly cost estimate (full stack)

Approximate, US region, 2026 pricing (cross-check with Google's calculator). Covers
storage, data pipeline, database, backend, and **LLM deployment** — the last is the
single biggest budget driver, so it's called out separately below. Keeping the running
cost lean matters — **La Maraña inherits this bill.**

### Build / MVP tier — ~$50–100 / month

| Component | Config | ~ Monthly |
|---|---|---|
| Cloud SQL (PostgreSQL + PostGIS + pgvector) | `db-g1-small` + ~20 GB SSD | $35–50 |
| Cloud Storage (raw + processed data) | ~50 GB standard | $2–5 |
| Cloud Run (FastAPI backend) | Low traffic, scales to zero | $0–10 |
| Data-pipeline compute (ingest/embed jobs, occasional) | Batch / manual | $5–15 |
| **LLM** (pay-per-use API, low volume) | Gemini Flash-tier | $5–20 |
| Secret Manager, logging, networking | | $3–8 |
| **Total** | | **≈ $50–100 / month** |

### Beta / production tier — depends on LLM deployment (see next section)

| Component | Config | ~ Monthly |
|---|---|---|
| Cloud SQL | `db-custom-2-7680` (2 vCPU / 7.5 GB) + storage + backups | $120–180 |
| Cloud Storage | More layers / documents | $5–15 |
| Cloud Run | Moderate traffic | $15–40 |
| Data-pipeline compute | Scheduled refresh jobs | $15–40 |
| Misc (secrets, logging, egress) | | $10–25 |
| Subtotal **(excluding LLM)** | | **≈ $165–300 / month** |
| **+ LLM** | pay-per-use API | **+$30–150** |
| **+ LLM** | *or* self-hosted open model (GPU) | **+$350–600** |

So beta lands at **~$200–450/mo with a pay-per-use LLM**, or **~$550–900/mo if we
self-host the open-source model on a GPU.**

### The LLM deployment decision (biggest lever)

| Option | What it is | Cost | Trade-off |
|---|---|---|---|
| **Pay-per-use API** (recommended to start) | Call a hosted model (Gemini Flash / Mistral API / Claude) per query | ~$0.001–0.01 per query → **$5–150/mo** at MVP/beta volume | Cheapest, no ops; data leaves to the provider |
| **Self-host open model on GPU** | Run Mistral on a GCP GPU (NVIDIA L4, ~24/7) | **~$350–600/mo** (or ~$300–370 with 1-yr commitment) | Full data control + ownership goal; fixed monthly cost regardless of usage |
| **Serverless GPU** (Cloud Run GPU) | Open model, scales to zero between requests | ~$50–250/mo at low/bursty volume | Middle ground; cold-start latency |

At MVP/beta query volumes, **pay-per-use is dramatically cheaper** than a GPU. Self-hosting
only wins financially at high, steady traffic — or if data-control/ownership requires it.
Recommendation: **start pay-per-use, revisit self-hosting only if volume or policy demands.**

### Annual totals (for the budget)

| Phase | Monthly | Annual |
|---|---|---|
| Build / MVP | ~$50–100 | **~$600–1,200** |
| Beta (pay-per-use LLM) | ~$200–450 | **~$2,400–5,400** |
| Beta (self-hosted GPU LLM) | ~$550–900 | **~$6,600–10,800** |

**One-time / other:** domain name ~$12–15/yr. **Not included:** personnel/developer time
(handled separately by NYU), which is not a GCP cost.

**Credits offset:** the NYU GCP credits Ahmed is requesting (plus GCP's $300 new-account
credit) can realistically cover most/all of the build/MVP phase. Confirm they're applied
to the billing account linked to this project (ClimateIQ chartfield per Timon, 2026-07-22).

---

## 5. Task split (from the 2026-07-14 sync)

| Task | Owner |
|---|---|
| Cost estimation | Rajan |
| GCP setup (project, roles, buckets, DB) | Rajan |
| Drive → GCP migration | Rajan |
| Pipeline setup (ingest docs + spatial, embeddings) | Rajan |
| Requesting NYU GCP credits | Chris / Ahmed |
| Confirm La Maraña owner email + billing/handoff decision | Chris + La Maraña |
| Data dictionary + reference spatial unit | Partner (La Maraña) |

---

## Open decisions to confirm with the team

1. **Billing during build:** link the La Maraña-owned project to **NYU's billing account**
   (so credits apply), switch to La Maraña's at handoff. Confirm with Chris/Ahmed.
2. **Handoff timing / trigger:** when does ownership fully transfer? (e.g., at beta, or
   at project end.)
3. **La Maraña account security:** rotate the shared password, enable 2FA.
