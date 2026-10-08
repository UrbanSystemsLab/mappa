# How the data fits together

Measured on the live database, 6 October 2026.

```
   LA MARAÑA'S INVENTORY                  WHAT WE HOLD
   (their spreadsheet, imported)

   layer_inventory ──── gis_id ────► layer_registry  (722)  ──table_name──► layer_* tables (630)
   their Capas_GIS tab                │ one row per layer          one table per layer: the shapes
                                      │ name, source, status
                                      │ embedding (for search)
                                      ▼
                                 layer_roles  (15)
                                 which layer does which job:
                                 "flood", "schools"...

   document_registry ── doc_id ────► documents  (440)  ──── id ────► document_chunks  (110,784)
   their Documentos tab               title, municipality             passages, each with an
                                                                      embedding (for search)

                                 reference_units  (1,693)
                                 every named place: 78 municipios, 902 barrios,
                                 713 comunidades — with their boundaries
```

## The three kinds of thing

**Layers** — map data. `layer_registry` is the catalogue: every layer La Maraña
listed, whether we hold its data, and where. The shapes themselves are in one table
per layer. A layer is `published` (on the map, 82), `loaded` (the assistant can use
it, not on the map, 521), `catalogued` (listed, no data, 102) or `duplicate` (listed
twice on their sheet, 17).

**Documents** — plans, laws and reports. `documents` is one row per file we have;
`document_chunks` is each document cut into passages of a few hundred words, about
250 per document, so a question can be matched to the right paragraph.

**Places** — `reference_units`, the boundaries of every municipio, barrio and
comunidad, so "in Santurce" can be turned into a shape.

## How a question uses all three

1. **The place** is recognised in the question and becomes a shape from `reference_units`.
2. **Documents** are searched by meaning (their embeddings), limited to that
   municipality's documents plus the island-wide ones.
3. **Layers** are found two ways: by role (`layer_roles` — "flood" is always the
   FEMA 2009 layer) and by meaning (each layer has an embedding too). Figures are
   computed against their shapes inside the place's boundary — "22 schools in
   Santurce" is counted, not read from a document.
4. The answer is written from the passages and the computed figures together.

## What links what — and what does not

| From | To | How | Enforced by the database? |
|---|---|---|---|
| a passage | its document | `document_chunks.document_id` | **yes** — the only declared link |
| a layer | its shapes | `layer_registry.table_name` | no — by name |
| a layer | their inventory row | `gis_id` | no — 652 of 722 match |
| a document | their inventory row | `documents.source_id = doc_id` | no — 339 of 440 match; the rest are files they sent that are not on the sheet |
| a role | its layer | `layer_roles.layer_id` | yes (since migration 0009) |
| a document | a place | municipality name in `documents.jurisdiction` | no |
| a layer | a place | the shapes overlap — computed when asked | — |
| **a document** | **a layer** | **nothing direct** | — |

**Documents and layers are not linked to each other.** They meet through the
place and through meaning, and in the answer itself. La Maraña's inventory looks
as though it links them, but the 13 layers that name a document are PDF map
images (pages of 7 plans), and the 18 documents that name a layer give a theme
("Red vial / carreteras"), not a layer.

## Known problems

- **Island-wide documents were excluded from every place-specific question.** The
  Reglamento Conjunto and the island-wide laws are marked "N/A" or left blank,
  and search accepted only "Puerto Rico". Fixed in code on 6 October.
- **96 documents had no municipality**, mostly municipal transport plans whose
  title names it. 73 are filled from their own title by
  `pipelines/fill_document_places`; 22 name none and count as island-wide; 1
  names two municipalities and needs a person.
- **Most links are by name, not enforced.** A renamed table or inventory ID breaks
  a link silently. Tests check the important ones (`tests/integration`).
- **27 superseded copies** of layers (628 MB) remain from loading their second
  GeoPackage. Harmless, but they could be removed.
