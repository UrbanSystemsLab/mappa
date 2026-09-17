# Mappealo — engineering log

A running record of what exists, how it was built, where every piece of data came
from, and why the design is the way it is. Written so that the next phase can
start without re-deriving any of it, and so La Maraña can audit any claim the
system makes back to a file they gave us.

**Append to this file as work lands. Do not rewrite history — corrections go in
as corrections, because knowing something was once wrong is the useful part.**

Last updated: 2026-09-17

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
| **8 placeholder documents cited** | A FEMA source appeared that was not in their inventory | Scaffold rows in `documents.json`. Purged; prompts hardened. This is the incident the provenance rule comes from. |
| **Registry marked `loaded` before commit** | False provenance record | Marking moved after the embedding run; `--reconcile` sets state from what is actually in the corpus. |

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
