# Mappealo — engineering log

A running record of what exists, how it was built, where every piece of data came
from, and why the design is the way it is. Written so that the next phase can
start without re-deriving any of it, and so La Maraña can audit any claim the
system makes back to a file they gave us.

**Append to this file as work lands. Do not rewrite history — corrections go in
as corrections, because knowing something was once wrong is the useful part.**

Last updated: 2026-10-02

---

## 1. What this is

A bilingual (ES/EN) planning and risk assistant for Puerto Rico, built for
La Maraña and handed over to them in April 2027. Two halves that have to agree
with each other:

- **A document assistant** that answers from La Maraña's own planning corpus and
  cites the document, declining when the corpus does not say.
- **A map** serving their GIS layers, which the assistant can query for real
  numbers rather than narrating them out of retrieved text.

The governing rule, set by La Maraña and repeated since: **nothing enters the
system that did not come from them.** No document downloaded from a public site
on our initiative, no layer from a third party, no citation pointing at a
government URL.

---

## 2. Where the data comes from

Everything traces to one of three deliveries from La Maraña.

| Source | What it is | Where it lives |
|---|---|---|
| `Inventario_Territorial_Docs_GIS.xlsx` | Their master inventory: 403 document rows, 649 GIS layer rows | `document_registry`, `layer_inventory` |
| Their Drive folder, *Documentos de planificación* | 392 PDFs | `data/raw/lamarana_docs/`, `gs://mappa-lamarana-aecc-raw/documents/lamarana/` |
| `la_marana.gpkg` | 3 GB GeoPackage, 108 GIS layers | `gs://mappa-lamarana-aecc-raw/spatial/`, `data/raw/la_marana.gpkg` |

**The inventory is the registry of record.** A document's ID, title, year and
municipality come from their sheet, never from the file's contents. This matters
most for scans: an OCR'd cover page reading `Ley Núm. 11Z- ZO!` can never become
a citation, because identity was never taken from it.

### Documents currently in the corpus

- **440 documents / 110,784 chunks**
- **319 from their own files.**
- **35 from our downloads — every one of them a row on their inventory** where
  they listed the document and supplied a link rather than a file. Listed in
  `data/eval/link_sourced_documents.csv`. Nothing in the corpus was found by us
  independently. These 35 should be requested as files.
- **73 of their PDFs cannot be read** — scans with no text layer. Full list with
  filename, folder and reason in `data/eval/failed_documents.csv`. OCR pipeline
  built; run in progress.

### Layers currently loaded

- **107 of the 649 on their inventory are drawable.** The data for them came from
  the GeoPackage, which holds 108 layers — the rest of the 649 have no data in
  anything they have given us. **This is an open question for La Maraña**: is
  there a second GIS delivery, or does the sheet catalogue layers held elsewhere?
- Of the 108, **57 tie to exactly one inventory row**. The other 51 carry their
  own registry row citing the GeoPackage, because their export tooling renamed
  things (`corredor_agricola_de_Project`, `g07_g13_fincas_autoridad_de_tierras_2010`)
  and their sheet has genuine duplicates — three rows named *Hospitales*, two
  named *Refugios_2023*. Guessing a match would fabricate provenance.
  Unresolved matches are in `data/eval/layer_match_review.csv`.

---

## 3. Architecture

```
                    ┌──────────────────────────────────────────┐
  Browser           │  frontend/index.html + app.js            │
                    │  chat · MapLibre GL · layer panel        │
                    └───────────────┬──────────────────────────┘
                                    │  /ask  /catalog/*  /tiles/*  /places  /locate
                    ┌───────────────▼──────────────────────────┐
  FastAPI           │  api/main.py                             │
                    │  ├─ retrieval.py   pgvector search        │
                    │  ├─ llm.py         Gemini narration       │
                    │  ├─ spatial_ops.py PostGIS analysis       │
                    │  ├─ catalog.py     layer metadata         │
                    │  ├─ tiles.py       MVT vector tiles       │
                    │  └─ db.py          one shared pool        │
                    └───────────────┬──────────────────────────┘
                    ┌───────────────▼──────────────────────────┐
  Cloud SQL         │  PostgreSQL + PostGIS + pgvector          │
                    │  documents · document_chunks             │
                    │  document_registry · layer_inventory     │
                    │  layer_registry · layer_* (107 tables)   │
                    │  reference_units                         │
                    └──────────────────────────────────────────┘
```

Everything the UI shows is read from the database. There is no hardcoded layer
list, no layer names in the frontend bundle, no per-layer code.

### The registry is the single source of truth

`layer_registry` holds one row per layer with its name, category, source agency,
geometry type, feature count, tile properties and status. Status is the important
part:

- `published` — data is loaded, it has a table, it draws, it serves tiles.
- `catalogued` — on their inventory, no data yet. Searchable, carries **no tile
  URL**, reports `available: false`.

This distinction is what lets the catalog hold all 649 honestly instead of either
hiding 542 of them or offering toggles that silently fail.

---

## 4. How each part works

### 4.1 Retrieval (`api/retrieval.py`)

- 384-dimension multilingual MiniLM embeddings (`paraphrase-multilingual-MiniLM-L12-v2`),
  chosen because the corpus is Spanish and the questions arrive in both languages.
- pgvector with an HNSW index over `document_chunks`.
- Top-6 chunks, optionally scoped to a municipality detected in the question.
- A relevance gate declines gibberish and off-corpus questions before the model
  ever sees them.

### 4.2 Narration (`api/llm.py`)

- Gemini 2.5-flash-lite via Vertex AI.
  **Why flash-lite and not flash:** `gemini-2.5-flash` spends its output budget on
  thinking tokens and truncates mid-answer. Flash-lite plus a structured prompt
  produces complete answers.
- The prompt forbids outside knowledge and URLs; `_strip_urls()` enforces it on
  the way out.
- Citations are deduplicated per document — retrieval returns several chunks from
  one plan, which used to list the same plan six times.

### 4.3 Spatial analysis (`api/spatial_ops.py`)

Counts, overlays, distances, coverage, nearest, point profile — all computed in
PostGIS against their layers.

- Concepts (`schools`, `flood`, `rivers`, `protected`…) map to tables through a
  fixed alias table in code, validated against `layer_registry` before reaching
  SQL. Nothing user-typed is interpolated.
- Distance is measured on the `geography` type, so metres are metres. Candidates
  are cut down by region and then by bounding-box overlap so the expensive check
  runs on few rows.
- Coverage unions overlapping polygons before measuring area, so a layer whose
  polygons overlap is not double-counted.
- **A distance binds to the layer named after it.** "In flood zones or within 500
  metres of a river" is one overlay and one distance, not two distances.

### 4.4 Tiles (`api/tiles.py`)

- `ST_AsMVT` / `ST_AsMVTGeom`, tile bounds computed in Python and passed to
  `ST_MakeEnvelope`.
  **Why:** `ST_Transform` is STABLE, not IMMUTABLE, so it cannot be folded to a
  constant and a `WHERE` clause containing it will not use the spatial index.
- Two-level geometry pyramid on heavy layers: `geom_coarse` (~350 m) below zoom
  10, `geom_simple` (~30 m) below 14, full geometry above. 95–99% vertex
  reduction. Layers loaded from the GeoPackage do **not** have this yet.
- Semaphore limits concurrent tile builds; per-connection `statement_timeout`.
  **Why connection-level:** killing the web process does not cancel a running
  Postgres query. Orphaned queries ran for 36 minutes.

### 4.5 Frontend (`frontend/`)

- MapLibre GL 4.7.1, OpenFreeMap basemaps.
- Catalog-driven: the layer panel is built from `/catalog/layers`.
- One map-level click handler using `queryRenderedFeatures`. Per-layer handlers
  overwrote each other, so every click showed the same layer.
- Asset version is a hash of the file's contents, not a hand-edited number.

---

## 5. Decisions and why

| Decision | Why |
|---|---|
| Vector tiles (MVT) instead of whole-layer GeoJSON | GeoJSON was capped at 6,000 features, so the west half of the island was blank. Tiles have no cap. |
| Tile bounds computed in Python | `ST_Transform` in a `WHERE` clause defeats the spatial index. |
| Two-level geometry pyramid | Island-wide views ship detail finer than a pixel. FEMA flood went from 5.7M vertices to 77k. |
| Registry in the database, not a config file | 649 layers cannot live in a frontend bundle, and La Maraña must be able to change metadata without a deploy. |
| `catalogued` as a distinct status | The alternative is hiding 542 layers or offering toggles that do nothing. |
| Citations carry no URL | An answer about their documents pointed at a government site. Now it cites their inventory ID. |
| Spatial answers computed, never narrated | See §6. |
| Tesseract locally, not Cloud Document AI | Free, and La Maraña inherits the bill after handover. Quality on their Spanish body text is good. |
| `load_state` set after commit, not before | Staging used to write `loaded` before embedding, so a document that failed halfway still read as loaded. |

---

## 6. Faults found, and what they teach

These are recorded because each one was invisible until something forced a check,
and the pattern is consistent: **verifying that a thing ran is not verifying that
it was right.**

| Fault | Effect | Cause |
|---|---|---|
| **44% of documents never extracted** | 171 of 392 PDFs silently missing | `unzip` hit a write error on an accented filename, prompted `Continue? (y/n)`, and with no stdin abandoned the rest of each archive. Files had been checked for corruption, never for absence. Re-extracted with `ditto`. |
| **Fabricated count** | "10 public schools in Arecibo in flood zones" | No such figure exists. The plan's tables are headed `1 pie, 4 pies, 7 pies, 10 pies` and a school address is on `Carr. 10`. Real answers: 0 and 14. Fixed by computing, and by passing the *absence* of a computable figure to the model. |
| **8 municipality names truncated at their accent** | `Bayam`, `Mayag`, `Juana D`, `San Sebasti` — those municipalities could not be queried at all | Encoding loss on import. Same class as an earlier fix (`A2asco` → Añasco). |
| **5 layers loaded as 3D measured geometry** | Cabo Rojo read as having zero protected area; it has 24.8 km² | `ST_Intersection` against a 2D boundary collapses for XYZM geometry. Loader now passes `-dim XY`. |
| **Tile service read the wrong table** | Every layer loaded after the first ten returned 404 while the panel offered it | `tiles.py` looked layers up in `spatial_layers`, the old ten-row table, not `layer_registry`. |
| **Stale asset version** | Panel stayed on an old build no matter what was deployed | `index.html` pointed at `app.js?v=80`, a number edited by hand. Now a content hash. |
| **Place search invisible** | No way to find a place on the map | The CSS and the JavaScript existed; the markup never did. |
| **Local answers took 16 seconds** | Every question felt broken | `LLM_PROVIDER` defaulted to `ollama`, so a laptop answered from Mistral running locally — 16.2s against Gemini's 2.1s, and a different model from the one the product ships. Default now follows the credentials present. |
| **Model embellished a computed count** | Told "3 of 7 schools intersect the flood zone", it named the one school it claimed was outside. Four were. | It was given figures, not feature names, and filled in the rest. Prompt now forbids naming or inferring individual features. |
| **Place questions returned the wrong place** | A question about Loíza came back with one chunk out of 1,652, and the answer said the corpus had nothing on Loíza | HNSW finds the nearest chunks across the whole corpus and applies the municipality filter *afterwards*, discarding nearly all of them. Fixed with `hnsw.iterative_scan = relaxed_order`. **Any filtered vector search has this problem — check row counts, not just scores.** |
| **Map location overrode the question** | After searching Mayagüez on the map, asking about Loíza returned Mayagüez documents | `req.location or detect_municipio(...)` — the sticky location won. The question wins now. |
| **Dead pooled connections** | Requests intermittently returned nothing at all | The Cloud SQL proxy drops idle connections and the pool handed them back. Connections are tested on checkout. |
| **8 placeholder documents cited** | A FEMA source appeared that was not in their inventory | Scaffold rows in `documents.json`. Purged; prompts hardened. This is the incident the provenance rule comes from. |
| **Registry marked `loaded` before commit** | False provenance record | Marking moved after the embedding run; `--reconcile` sets state from what is actually in the corpus. |

---

## 6a. Latency

Measured per stage on a warm process, one question:

| Stage | Time |
|---|---|
| `detect_municipio` | 0.55s |
| `retrieve_with_scores` (pgvector, top-6) | 0.55s |
| `spatial_ops.analyze` | <0.01s |
| `suggested_layer_ids` | 0.52s |
| `municipio_bbox` | 0.44s |
| **LLM narration (Gemini 2.5-flash-lite)** | **2.1s** |
| **Total, warm** | **~2s** |

The first request after a restart is ~8s while the Vertex client is built; it is
cached for the life of the process after that.

Everything outside the model is about two seconds combined, and several of those
stages are separate round trips that could be folded together if it ever matters.
It does not yet — the model dominates.

**Streaming is the next real win.** Two seconds to first token is fine; two
seconds of blank screen is what people notice. Server-sent events from `/ask`
would show the answer as it is written.

---

## 7. Pipelines

| Script | What it does |
|---|---|
| `pipelines/import_lamarana_inventory.py` | Loads their Excel into `document_registry` + `layer_inventory` |
| `pipelines/ingest_lamarana_docs.py` | Stages their PDFs keyed to their IDs; `--reconcile` fixes `load_state` from the corpus |
| `pipelines/ingest_documents.py` | Chunks and embeds into `document_chunks` |
| `pipelines/ocr_documents.py` | OCRs scans; records image-only documents rather than ingesting noise |
| `pipelines/ocr_pilot.py` | Samples a few scans to judge quality before committing to a full run |
| `pipelines/load_gpkg_layers.py` | Loads the GeoPackage into PostGIS, flips registry rows to `published` |
| `pipelines/rebuild_layer_registry.py` | Rebuilds the catalog from their inventory |
| `pipelines/simplify_layers.py` | Builds the geometry pyramid |

---

## 8. Where this stands

**Working:** document Q&A with citations and refusals; 107 drawable layers; the
full 649 catalogued; spatial counts, overlays, distances and coverage; place
search; map click; chat driving the map.

**Open:**

1. **~541 layers have no data.** The biggest open question for La Maraña.
2. **Geometry pyramid not built for the 93 new layers** — tiles are 300–500 KB at
   low zoom where they should be a few KB.
3. **OCR incomplete** — 73 scans, run in progress.
4. **35 documents still from links** — request the files.
5. **S3/S4 questions unsupported** — drawn polygons, uploaded documents,
   multi-region comparisons. Half of the 100-question bank.
6. **No auth, no quotas.** Required before any public launch.
7. **Duplicate downloads not yet removed** — DOC-033/DOC-034 exist twice, and
   `documents/planning/` still holds 176 PDFs we downloaded. Both need sign-off.
8. **Live Cloud Run service returns 403.**

---

## 9. Verification habits worth keeping

- Diff against the manifest, not the exit code. The extractor said it succeeded.
- Check absence, not just corruption. Every file present was valid; 171 were missing.
- Sanity-check a zero. "No schools in a flood zone" was right for Arecibo and wrong
  for Cabo Rojo's protected areas — only comparing against island-wide totals
  separated them.
- Look at the screen. Three separate bugs survived because the API was checked
  and the page was not.

---

## 12. Since the first entry (18 Sep – 2 Oct)

### It is live on its own domain

**https://app.mappealo.org** — public, no login, TLS issued by Google and
auto-renewing. Getting there took longer than the work deserved, because NYU
enforces `run.managed.requireInvokerIam` on the project and that rejects any new
revision of a publicly-invokable Cloud Run service. Two routes around it were
closed: an external load balancer still needs `allUsers`, which domain-restricted
sharing blocks, and climateiq is not a counterexample because its public traffic
is GKE, not Cloud Run.

NYU HPC resolved it with a **resource-manager tag** on the single service
(`mappa-lamarana-aecc/mappa-public-ingress/true`), scoped to one resource rather
than the project. Worth remembering: that is the sanctioned pattern, and asking
for it directly would have saved two days.

The app sits on a subdomain so the bare `mappealo.org` stays free for a landing
page — a decision La Maraña still has to make.

### Name, logo and palette

Renamed Mappealo → **Mappa** in ten places, including the model's own system
prompt, where it had been introducing itself by the old name. La Maraña's palette
applied: navy `#0B3954` on the chrome, green `#09814A` on the actions, the other
three colours held for semantic use only. Logo in the header, the welcome panel
and as the favicon — there had been no favicon at all.

### Answers stream now

The panel used to sit on "Thinking…" until the entire pipeline finished. Worse,
the browser request had no deadline, so a stalled connection never resolved and
never errored — one question sat there for ten minutes.

`/ask/stream` sends the map's answer first as a `meta` event. Municipality,
bounding box and which layers to switch on are a name match and a lookup, so the
map moves in about **0.15 s** while the text is still being written. The browser
now also gives up after 90 seconds and says so.

### Follow-up questions work

A follow-up rarely repeats itself. "How many schools are in that municipality?"
had no place, so the spatial engine had no region. "How many of those are in a
flood zone?" had no subject, so it read as uncountable and declined — having just
answered 25. Both now carry forward from the conversation, with anything named in
the current question still winning.

```
"What should I know about Carolina…"          → Carolina
"How many schools are in that municipality?"  → 25 public schools
"How many of those are in a flood zone?"      → 8 of the 25
```

### Baked tiles (proven, not yet shipped)

`pipelines/bake_tiles.py` cuts a layer into a PMTiles archive with tippecanoe.
Proven on one layer:

| | baked | on demand |
|---|---|---|
| z8 | 145 KB · 0.025 s | 171 KB · 0.205 s |
| z9 | 149 KB · 0.025 s | 188 KB · 0.797 s |

Smaller and 8–30× faster, and a baked tile is static bytes — no database, no CPU,
near-zero serving cost. The trade is staleness, which suits a published GIS
inventory and would not suit live data.

**First attempt produced tiles three times heavier than the ones they replaced.**
Tippecanoe's default thins uniformly and only once a tile is already oversized;
the on-demand path drops the smallest features first. `--drop-smallest-as-needed`
with a 160 KB budget matches it.

### Faults found in this period

| Fault | Effect | Cause |
|---|---|---|
| **Streaming edit deleted 18 functions** | Page loaded and did nothing — blank chat, layer panel stuck | The edit was bounded by a comment that sat 500 lines below the function. A screenshot after the change looked fine, because the welcome state renders from HTML and exercised none of the deleted code. **Checking that a page paints is not checking that it works.** |
| **Container OOM-killed** | Questions hung then timed out, intermittently | 2 GiB was not enough for PyTorch plus the embedding model plus concurrent requests. Compounded by `containerConcurrency: 160` on 2 CPU. Now 4 GiB, 4 CPU, concurrency 4. |
| **Case-sensitive geometry filter** | One tile 7.1 MB in 28 s | Test for `"Polygon"` missed `"MULTIPOLYGON"`, disabling the sub-pixel filter for 97 of 107 layers. And the threshold kept features 1/64th of a pixel across. Now 232 KB in 3.6 s. |
| **MAP FACTS leaked into answers** | Readers saw `[1, MAP FACTS]` as if it were a citation | The strip only matched the marker alone, not folded into a citation list. |
| **Local answers took 16 s** | Everything felt broken | `LLM_PROVIDER` defaulted to `ollama`, so a laptop answered from Mistral locally — a different model from the one that ships. Default now follows the credentials present. |

### Things we learned that are not code

**Their inventory already links documents to layers, and we are not using it.**
13 of 649 layers name a related document by ID; 18 of 507 documents name a related
layer, though as themes rather than IDs. Surfacing those links is the piece that
would make documents and layers feel like one product.

**No sync exists, and the partner believed one did.** La Maraña asked whether
edits to their Drive sheet reach the backend. They do not — the import is a
manual run against a downloaded copy, and it matches column headers by exact
name, so a renamed header silently drops that field. This was corrected with
them, and a scheduled sync is now on the roadmap.

**Open vs closed weights, for grant purposes.** Retrieval and OCR run on open
weights we control (MiniLM, Apache 2.0; Tesseract). Only answer synthesis uses a
closed model (Gemini 2.5 Flash-Lite), and it is replaceable — the platform ran on
Mistral during development. The knowledge base itself is entirely open and in
La Maraña's own project.

### Open, as of 2 October

1. **Rate limiting** — the app is on a memorable domain with no login and no
   limit. Every question bills the project, and La Maraña inherits it. Most
   urgent item.
2. **OCR unfinished** — 39 of 73 scans read. The remainder are mostly municipal
   territorial plans and housing regulations.
3. **Baked tiles** — pipeline proven on one layer, not rolled out or wired into
   the frontend.
4. **Scheduled inventory sync** — promised to La Maraña, not built.
5. **Document ↔ layer links** — their data, unused.
6. **~540 catalogued layers have no data** — the largest open question, and one
   only they can answer.

---

## 13. Engineering foundations (2 Oct)

The product worked; the engineering around it did not meet the standard for
something being handed to someone else to run. Architecture written down as a
specification, then built in a day rather than the nine weeks it was scoped at —
by cutting the frontend rebuild and the handover work, which buy maintainability
and a deadline respectively, not capability.

### What was wrong, measured

```
tests                0 files          every regression found by a human
schema              11 ad-hoc ALTER   database could not be rebuilt
pipelines           21 scripts        6 dead, no ordering, no shared base
CI                  deploys on push   no gate between a bad commit and production
lint                none              style drifted, nothing caught shadowing
main.py            388 lines          HTTP, orchestration and SQL together
```

### What was done

**41 tests**, drawn from this project's defect history rather than a coverage
target: the distance that bound to the wrong layer, the MAP FACTS marker folded
into a citation list, municipality names truncated at their accent, 3D geometry
making Cabo Rojo report no protected area, the registry drift that removed 26
layers from the map.

**They found two real faults on their first run.** A layer was published on the
map with no geometry and no features. And 25 tables superseded by the second
GeoPackage were stranded — expected, but better known than discovered.

**Migrations.** Two Alembic revisions; the database now builds from empty and
rolls back, verified. This was a handover blocker: La Maraña could not have stood
this up themselves.

**Lint and format.** Thirty-six findings. Five were dead imports left by the
refactor an hour earlier. Several `zip()` calls would have truncated silently —
in `embed_layers` that means pairing a layer with another layer's embedding and
writing it without complaint. And `tiles.py` held a dead branch containing a
fullwidth comma that would have produced invalid SQL had anything reached it.

**One service behind both answer routes.** The orchestration existed twice,
copied, and had drifted. Putting them side by side immediately exposed a defect
only the streamed path had: deltas go out raw, so the cleaned text — URLs
stripped, the model's references to the computed-facts block removed — was
computed and thrown away. Users had been seeing `[MAP FACTS]` in every streamed
answer since streaming was added.

**Routers split out.** `main.py` 388 → 230 lines, and now only assembles the app.

### What was deliberately not done

**The repository layer.** Fifty-one SQL statements, twenty-nine in `spatial_ops`
where the query and the spatial logic are one thought — a dynamic table name, a
geometry operation, a region filter — and each is called once. Wrapping them in
repository classes adds indirection and no testability, because what needs
testing is the answer the query gives, which the integration tests already assert.

**The frontend rebuild.** Two weeks for maintainability, not capability. Deferred
deliberately, and the risk is recorded: 766 lines, no modules, no tests, and only
one person can safely change it.

### Database sizing — and a correction

Raised the instance to 4 vCPU / 16 GB against 27 GB of data, then measured:

```
1 vCPU, 3.75 GB     0.90s warm
4 vCPU, 16 GB       0.91s warm
```

The upgrade bought nothing, because almost all of the 27 GB is cold — nobody
queries 600 layers, they query a handful. Reverted to 1 vCPU. **Backups kept**,
which was the part that genuinely needed fixing: there were none at all against
27 GB of their work, days after they sent a 22 GB file.

The trigger for upgrading is concurrent users, not data size. Resizing takes two
minutes.

### Reaching all 601 layers

The assistant could answer about fifteen, because fifteen were listed in a
hand-written dictionary. Layers now carry an embedding, like documents, and a
question finds them by meaning. Toll plazas and wells became answerable without
anyone writing down that a *pozo* is a well.

Three things it needed, each from a failure:

- **Strip the place before matching.** "Wells in Arecibo" matched *tipo de suelo
  arecibo* over *pozos* — the place is a third of the sentence and several layers
  carry a municipality in theirs.
- **Only overlay when asked.** "Fire hydrants in Ponce" paired hydrants against a
  forestry-slope layer that merely scored well.
- **Reconcile the registry.** Loading the second GeoPackage stranded 30 tables;
  three were real layers that would have been lost, including 39,999 building
  footprints.

**A limit worth recording.** Asked about bus terminals, it answers with toll
plazas. The right layer is `RUTAS PÚBLICOS TERMINALES`, and *públicos* in Puerto
Rico are shared vans, not buses, so the words genuinely do not align. Scores for
right and wrong answers overlap — 0.514 wrong against 0.499 right — so no
threshold separates them. The mitigation that works is that **the answer always
names the layer it used**.

### Geography beyond the municipality

`reference_units` held 78 municipios and nothing else, and every spatial function
took a place *name*. Now 1,693 places: 902 barrios and 713 comunidades
especiales. Census blocks were deliberately excluded — "Block Group 2" is a
statistical unit referenced by number, and putting it in a gazetteer people
search by name would bury the real places.

**Barrio Pueblo exists in 74 of 78 municipalities**, which is why every place
carries its parent.

**All 1,693 are now reachable from a question.** Spatial queries scope by a
place *code* rather than a place name, which is what lets a barrio be a scope at
all — the old clause hard-coded `unit_type='municipio'` because a name was the
only handle it had. "¿Cuántas escuelas hay en Santurce?" answers 22, against 84
for the whole of San Juan.

The hard part is not finding a place. It is refusing to find one.

- **A bare repeated name resolves to nothing.** "Pueblo" names 74 places, so it
  names none of them. With a municipality beside it — "Pueblo, Ponce" — it
  resolves.
- **Ordinary words are not places.** There is a barrio called Playa, one called
  Costa and one called Centro. Which names are also ordinary Spanish words is
  *measured*, not hand-listed: the gazetteer pipeline tokenises a sample of the
  corpus and flags a name that turns up lowercase in a fair share of chunks.
  Santurce scores zero, playa scores 104, and 35 names are flagged. A flagged
  name is accepted only when a word like *barrio* or *sector* introduces it.
- **A fragment of a longer name resolves to nothing.** "Caño Martín Peña"
  resolved to barrio Caño in Guánica, forty miles away, because Caño was the only
  name in the sentence the gazetteer held. A match flanked by another capitalised
  word is now treated as part of a name we do not have.

The failure being guarded here is not an unanswered question. It is a precise
number computed over the wrong place — the same shape as every grounding bug
this project has had.

### A corrupt column, found by a test

The new integration tests assert that every place's municipality is one of the
78. It failed on 139 rows: in the comunidades especiales layer the accented
character in the municipality column is replaced by a different one in each row,
so **Añasco appears as Aaasco, Aeasco, Aiasco, Aoasco, AOasco and Asasco**.
Bayamón has eleven spellings, Canóvanas ten.

The fix was to stop reading the column. A place's municipality is **which
municipality it sits in**, which the geometry already says, and the 78 boundaries
are intact. All 1,615 places are now placed by `ST_PointOnSurface` against those
boundaries.

Logged for La Maraña, because the damage suggests the file was converted through
an encoding that lost its accents, and other columns in it may be affected.
