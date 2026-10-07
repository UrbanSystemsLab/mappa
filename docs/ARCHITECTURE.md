# How Mappa is put together

## The parts

```
 browser (frontend/)            any other frontend
        \                         /
         HTTP  /api/v1/...  (docs/API.md)
                    |
   api/routers/      one file per area: ask, places, catalog, tiles.
                     Reads the request, returns the response. No SQL, no logic.
                    |
   api/services/     answering.py: one question from arrival to finished answer.
                    |
   api/assistant.py  Gemini, and the loop that lets it call tools.
   api/tools.py      the seven tools it may call.
                    |
   api/repositories/ every SQL query, grouped by what it is about:
                     places, documents, layers, spatial.
                    |
   api/db.py         the connection pool.
                    |
   Cloud SQL (Postgres + PostGIS + pgvector)
```

Supporting pieces: `api/schemas/` defines every request and response shape, which become
[openapi.json](openapi.json). `core/settings.py` reads every setting from the environment,
in one place. `api/cache.py` holds the one caching helper. `api/limits.py` is the rate limit
on questions. `api/catalog.py` and `api/tiles.py` build the layer list and draw map tiles.

## What happens when someone asks a question

Take "How many schools in Carolina are in a flood zone?"

1. **`routers/ask.py`** receives `POST /api/v1/ask/stream` and hands the question to
   `services/answering.stream()`.
2. **`services/answering.py`** opens a `Session`, which records everything found while
   answering, and asks `assistant.answer()` for the text.
3. **`assistant.py`** sends Gemini the question, its instructions, the list of standard
   layers (from the `layer_roles` table) and the seven tools. Gemini decides which tools
   it needs:
   - `find_place("Carolina")` → `repositories/places.lookup` → the place id
   - `find_layers("public schools")` → `repositories/layers.search` (vector search over
     layer descriptions) → candidate layers
   - `count_inside(schools, flood zones, Carolina)` → `repositories/spatial.count_inside`
     → a PostGIS `ST_Intersects` query → 8 of 25
4. Each tool call runs in **`tools.py`**, and its result goes back to Gemini. This repeats
   for at most six rounds.
5. Before the answer is released, `assistant.py` checks two things:
   - that something was actually found (documents or a measurement)
   - that every number in the text appears in a tool result

   If either fails, Gemini is sent back once to rewrite. A sentence that still has an
   unsupported number is removed.
6. **`answering.py`** streams `meta` (where to move the map, which layers to show), then
   the text, then `done` with the sources. A source is only a document whose passage the
   answer actually cited.

A question about rules ("What does the Reglamento Conjunto say about building near a
river?") follows the same path but uses `search_documents`. That embeds the question and
finds the closest passages in `document_chunks` with pgvector. Passages from the place's
own municipio come first, then island-wide documents.

No list of keywords decides what a question means. The model chooses the tools; the code
makes sure that what they return is exact and that the answer sticks to it.

## The database

One Cloud SQL server, `mappa-pg`, holds two databases: `mappa` (production) and
`mappa_staging` (a full copy for testing). Their structure is managed by Alembic
(`migrations/`). The main tables:

| Table | Holds |
|---|---|
| `documents`, `document_chunks` | La Maraña's plans and regulations, split into passages, each with an embedding |
| `document_registry` | which documents from their inventory are loaded, and from where |
| `layer_registry` | every layer in La Maraña's inventory: names, source, year, geometry, whether its data is loaded, what a click shows |
| `layer_<name>` tables | the shapes of each layer (PostGIS) |
| `layer_roles` | the standard layer for common questions (flood zones, schools...) |
| `reference_units` | municipios, barrios and comunidades, with their boundaries |

[DATA_MODEL.md](DATA_MODEL.md) has the full detail.

## How data gets in

The scripts in `pipelines/` load data. They do not run while the app is serving.
`sync_drive` and `ingest_lamarana_docs` load documents from La Maraña's Drive.
`load_gpkg_layers` and `rebuild_layer_registry` load map layers. `build_gazetteer` builds
the places. `embed_layers` and `profile_layers` prepare layers for search and display.
`eval_answers` measures answer quality on 100 test questions.

## Where it runs

| | Service | Database |
|---|---|---|
| Local | your laptop, `scripts/run_local.sh` | `mappa_staging` |
| Staging | Cloud Run `mappa-staging` | `mappa_staging` |
| Production | Cloud Run `mappa`, https://app.mappealo.org | `mappa` |

A change goes local → staging → production. Production runs the exact image that passed
on staging. See [RELEASING.md](RELEASING.md).
