"""Load La Maraña's master inventory as the system's registry of record.

Source: Inventario_Territorial_Docs_GIS.xlsx, shared by La Maraña on 22 Jul 2026.
It is the catalogue they maintain of every planning document and GIS layer they
have identified — 403 documents and 637 layers, with their own IDs, categories,
sources and quality assessments.

This is the file the product should be built around. Everything we hold is
recorded against their ID, so "where did this come from?" is answered by a column
rather than by reasoning. The `Enlace` column is provenance — where a document
originally came from — not an instruction to fetch it; La Maraña supplied the PDFs
themselves in a separate folder.

Run:
    python -m pipelines.import_lamarana_inventory --file data/raw/lamarana_master_inventory.xlsx
"""

from __future__ import annotations

import argparse
import os

import openpyxl
import psycopg2
from psycopg2.extras import execute_batch

INVENTORY_NAME = "La Maraña — Inventario_Territorial_Docs_GIS"

DDL = """
-- Their document inventory, verbatim. Our loaded copies reference this.
CREATE TABLE IF NOT EXISTS document_registry (
    doc_id            text PRIMARY KEY,          -- their ID_DOC, e.g. DOC-033
    title             text NOT NULL,
    year              int,
    author            text,
    doc_type          text,
    jurisdiction      text,
    region            text,
    municipio         text,
    community         text,
    category          text,
    subcategory       text,
    source_link       text,                      -- Enlace: where it came from originally
    file_location     text,                      -- Ubicación del archivo
    file_format       text,
    available         text,                      -- Disponible
    accessibility     text,                      -- Accesibilidad
    currency          text,                      -- Actualización: Vigente / Desactualizado
    identified_gap    text,                      -- Brecha identificada
    action_required   text,                      -- Acción requerida
    related_layer     text,                      -- Capa asociada — links a doc to a map layer
    status            text,                      -- Estado: Validado / ...
    comments          text,
    source_inventory  text NOT NULL DEFAULT '""" + INVENTORY_NAME + """',
    -- how far this document has got in our pipeline
    load_state        text NOT NULL DEFAULT 'not_attempted',
    load_note         text,
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT document_registry_load_state_check
        CHECK (load_state IN ('not_attempted','loaded','failed_link','no_text_layer','excluded'))
);
CREATE INDEX IF NOT EXISTS idx_docreg_municipio ON document_registry (municipio);
CREATE INDEX IF NOT EXISTS idx_docreg_category  ON document_registry (category);
CREATE INDEX IF NOT EXISTS idx_docreg_state     ON document_registry (load_state);

-- Their GIS layer inventory. layer_registry holds what we actually serve; this
-- holds everything they catalogued, so the gap between the two is visible.
CREATE TABLE IF NOT EXISTS layer_inventory (
    gis_id            text PRIMARY KEY,          -- their ID (GIS-016 etc.)
    layer_name        text NOT NULL,             -- Nombre de capa
    platform_name     text,                      -- Nombre Plataforma: their display name
    gdb_name          text,                      -- Nombre GDB
    original_name     text,                      -- Nombre de capa original
    feature_dataset   text,                      -- thematic grouping in the GDB
    geometry_type     text,
    category          text,
    subcategory       text,
    file_format       text,
    description       text,
    data_source       text,
    publication_date  text,
    revision_date     text,
    coverage          text,
    crs               text,
    attribute_defs    text,
    usage_restrictions text,
    related_document  text,                      -- Documento relacionado
    identified_gap    text,
    quality_level     text,                      -- Nivel de calidad
    priority          text,                      -- Prioridad
    status            text,
    source_inventory  text NOT NULL DEFAULT '""" + INVENTORY_NAME + """',
    served_layer_id   text,                      -- FK-ish to layer_registry.id when loaded
    updated_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_layinv_category ON layer_inventory (category);
CREATE INDEX IF NOT EXISTS idx_layinv_served   ON layer_inventory (served_layer_id);
"""


def cell(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def as_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def rows_of(wb, sheet):
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    hdr = [cell(h) for h in next(it)]
    for r in it:
        if not any(c not in (None, "") for c in r):
            continue
        yield dict(zip(hdr, r))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="data/raw/lamarana_master_inventory.xlsx")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    wb = openpyxl.load_workbook(args.file, read_only=True, data_only=True)
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(DDL)

    # ---- documents ----
    docs = []
    for r in rows_of(wb, "Documentos"):
        did = cell(r.get("ID_DOC"))
        if not did:
            continue
        docs.append((
            did, cell(r.get("Título")) or did, as_int(r.get("Año")), cell(r.get("Autor")),
            cell(r.get("Tipo de documento")), cell(r.get("Jurisdicción")), cell(r.get("Región")),
            cell(r.get("Municipio")), cell(r.get("Comunidad")), cell(r.get("Categoría")),
            cell(r.get("Subcategoría")), cell(r.get("Enlace")), cell(r.get("Ubicación del archivo")),
            cell(r.get("Formato")), cell(r.get("Disponible")), cell(r.get("Accesibilidad")),
            cell(r.get("Actualización")), cell(r.get("Brecha identificada")),
            cell(r.get("Acción requerida")), cell(r.get("Capa asociada")),
            cell(r.get("Estado")), cell(r.get("Comentarios")),
        ))
    execute_batch(cur, """
        INSERT INTO document_registry (doc_id,title,year,author,doc_type,jurisdiction,region,
            municipio,community,category,subcategory,source_link,file_location,file_format,
            available,accessibility,currency,identified_gap,action_required,related_layer,
            status,comments)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (doc_id) DO UPDATE SET
            title=EXCLUDED.title, year=EXCLUDED.year, author=EXCLUDED.author,
            doc_type=EXCLUDED.doc_type, category=EXCLUDED.category,
            subcategory=EXCLUDED.subcategory, source_link=EXCLUDED.source_link,
            currency=EXCLUDED.currency, related_layer=EXCLUDED.related_layer,
            status=EXCLUDED.status, updated_at=now()
    """, docs, page_size=100)
    print(f"[inventory] documents: {len(docs)}")

    # ---- layers: Capas_GIS, enriched with the name-mapping sheet ----
    names = {}
    for r in rows_of(wb, "Coordenadas_Capas_Nombres"):
        gdb = cell(r.get("Nombre GDB"))
        if gdb:
            names[gdb.lower()] = {
                "platform": cell(r.get("Nombre Plataforma")),
                "original": cell(r.get("Nombre de capa orginal ")) or cell(r.get("Nombre de capa orginal")),
                "dataset": cell(r.get("Feature Dataset")),
                "crs": cell(r.get("Coordenada ")) or cell(r.get("Coordenada")),
            }

    layers, seen = [], set()
    for sheet, idcol in (("Capas_GIS", "x"), ("Capas_GIS_DRAFT", "ID_GIS")):
        for r in rows_of(wb, sheet):
            gid = cell(r.get(idcol)) or cell(r.get("ID_GIS"))
            lname = cell(r.get("Nombre de capa"))
            if not gid or not lname or gid in seen:
                continue
            seen.add(gid)
            nm = names.get(lname.lower(), {})
            layers.append((
                gid, lname, nm.get("platform"), lname if nm else None, nm.get("original"),
                nm.get("dataset"), cell(r.get("Tipo de geometría")), cell(r.get("Categoría")),
                cell(r.get("Subcategoría")), cell(r.get("File format")) or cell(r.get("Formato")),
                cell(r.get("Description")), cell(r.get("Data source")) or cell(r.get("Fuente")),
                cell(r.get("Publication date")), cell(r.get("Revision date")),
                cell(r.get("Geographic coverage")) or cell(r.get("Cobertura")),
                cell(r.get("CRS")) or nm.get("crs") or cell(r.get("Proyección")),
                cell(r.get("Attribute definitions")), cell(r.get("Usage restrictions/license")),
                cell(r.get("Documento relacionado")), cell(r.get("Brecha identificada")),
                cell(r.get("Nivel de calidad")), cell(r.get("Prioridad")), cell(r.get("Estado")),
            ))
    execute_batch(cur, """
        INSERT INTO layer_inventory (gis_id,layer_name,platform_name,gdb_name,original_name,
            feature_dataset,geometry_type,category,subcategory,file_format,description,
            data_source,publication_date,revision_date,coverage,crs,attribute_defs,
            usage_restrictions,related_document,identified_gap,quality_level,priority,status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (gis_id) DO UPDATE SET
            layer_name=EXCLUDED.layer_name, platform_name=EXCLUDED.platform_name,
            category=EXCLUDED.category, data_source=EXCLUDED.data_source,
            crs=EXCLUDED.crs, priority=EXCLUDED.priority, updated_at=now()
    """, layers, page_size=100)
    print(f"[inventory] layers: {len(layers)}")

    # ---- mark what we have actually loaded ----
    cur.execute("""
        UPDATE document_registry r SET load_state='loaded'
        WHERE EXISTS (SELECT 1 FROM documents d
                      WHERE split_part(d.source_id,'-c',1) = r.doc_id)
    """)
    print(f"[inventory] marked loaded: {cur.rowcount}")
    cur.execute("""
        UPDATE layer_inventory i SET served_layer_id = g.id
        FROM layer_registry g
        WHERE lower(replace(i.layer_name,' ','_')) = lower(replace(g.name_es,' ','_'))
           OR lower(i.layer_name) = lower(g.id)
    """)
    print(f"[inventory] layers matched to served: {cur.rowcount}")


if __name__ == "__main__":
    main()
