"""Create and seed layer_registry — the catalog that replaces hardcoded frontend metadata.

Layer names, categories, colours and translations currently live as literals in
frontend/app.js, so adding a layer means a code change and a deploy. That does not
survive 600 layers, and it means La Maraña could not add a layer themselves after
handoff. This moves all of it into the database.

The schema is shaped around what La Maraña actually sends us: their reconstructed
metadata workbooks carry a confidence level per layer (Confirmed / Inferred /
Unknown / Reconstructed), so `metadata_status` adopts that vocabulary directly
rather than inventing a parallel one. `source_inventory` records which inventory a
layer came from, which is the provenance guarantee the product is built on.

Idempotent — safe to re-run.

Run:
    python -m pipelines.create_layer_registry            # create + seed
    python -m pipelines.create_layer_registry --dry-run
"""

from __future__ import annotations

import argparse
import json
import os

import psycopg2

DDL = """
CREATE TABLE IF NOT EXISTS layer_registry (
    id                text PRIMARY KEY,
    table_name        text NOT NULL,

    -- Bilingual presentation. Two languages only, so columns beat a join table.
    name_es           text NOT NULL,
    name_en           text NOT NULL,
    description_es    text,
    description_en    text,

    -- Browsing and search across a 600-layer catalog.
    category          text NOT NULL,
    subcategory       text,
    theme             text,
    keywords          text[] NOT NULL DEFAULT '{}',

    -- Provenance. source_inventory answers "where did this come from?", which is
    -- the question the whole product is accountable to.
    source_agency     text,
    source_inventory  text,
    source_url        text,
    vintage_year      int,
    license           text,
    metadata_status   text NOT NULL DEFAULT 'unknown',

    -- Geometry + rendering.
    geometry_type     text,
    srid              int NOT NULL DEFAULT 4326,
    feature_count     bigint,
    min_zoom          int NOT NULL DEFAULT 0,
    max_zoom          int NOT NULL DEFAULT 14,
    label_column      text,      -- feature name shown in click popups
    sublabel_column   text,
    style             jsonb NOT NULL DEFAULT '{}'::jsonb,

    -- Bump dataset_version to invalidate cached tiles for this layer.
    dataset_version   text NOT NULL DEFAULT '1',
    -- draft keeps a layer out of the public catalog without deleting it, which is
    -- how layers with unrecoverable metadata are held back.
    status            text NOT NULL DEFAULT 'published',

    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT layer_registry_metadata_status_check
        CHECK (metadata_status IN ('confirmed','inferred','reconstructed','unknown')),
    CONSTRAINT layer_registry_status_check
        CHECK (status IN ('published','draft','hidden'))
);

CREATE INDEX IF NOT EXISTS idx_layer_registry_category ON layer_registry (category, status);
CREATE INDEX IF NOT EXISTS idx_layer_registry_status   ON layer_registry (status);
CREATE INDEX IF NOT EXISTS idx_layer_registry_keywords ON layer_registry USING gin (keywords);
-- Free-text search over the prose columns. Keywords are excluded here because
-- array_to_string is STABLE, not IMMUTABLE, so it cannot appear in an index
-- expression; the GIN index on keywords above covers array matching instead.
CREATE INDEX IF NOT EXISTS idx_layer_registry_search   ON layer_registry USING gin (
    to_tsvector('simple',
        coalesce(name_es,'') || ' ' || coalesce(name_en,'') || ' ' ||
        coalesce(description_es,'') || ' ' || coalesce(description_en,'') || ' ' ||
        coalesce(source_agency,''))
);

CREATE OR REPLACE FUNCTION layer_registry_touch() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_layer_registry_touch ON layer_registry;
CREATE TRIGGER trg_layer_registry_touch BEFORE UPDATE ON layer_registry
    FOR EACH ROW EXECUTE FUNCTION layer_registry_touch();
"""

THEME_COLOR = {
    "political": "#555555", "inundacion": "#2b6cb0", "deslizamiento": "#b7791f",
    "uso_de_terrenos": "#2f855a", "salud": "#c53030", "educacion": "#6b46c1",
    "refugios": "#0d9488", "vias": "#333333",
}
THEME_CATEGORY = {
    "inundacion": "Riesgos", "deslizamiento": "Riesgos",
    "salud": "Servicios", "educacion": "Servicios", "refugios": "Servicios",
    "uso_de_terrenos": "Planificación", "vias": "Infraestructura",
    "political": "Límites",
}

# Seed for the 10 layers currently loaded. Everything here previously lived in
# frontend/app.js. Metadata status is honest: these came from La Maraña's GIS
# folder, but per-layer source documentation was not supplied for most of them.
SEED = [
    ("municipios", "layer_g03_legales_municipios_2015", "Municipios", "Municipalities",
     "political", ["municipio", "limites", "boundary", "municipality"],
     "Junta de Planificación", 2015, "confirmed", "municipio", None),
    ("barrios", "layer_barrios_2015_geoid_corrected_16_nov17", "Barrios", "Barrios (wards)",
     "political", ["barrio", "ward", "limites", "boundary"],
     "Junta de Planificación", 2015, "inferred", None, None),
    ("fema_flood_2009", "layer_g23_riesgo_inundacion_fema_firms_2009",
     "Zonas inundables FEMA 2009", "FEMA flood zones 2009",
     "inundacion", ["inundacion", "flood", "fema", "firm", "riesgo"],
     "FEMA", 2009, "confirmed", None, None),
    ("fema_flood_02pct_2018", "layer_g23_riesgo_inundacion_floodzone_0_2pct_seamless_2018",
     "Inundación 0.2% anual FEMA 2018", "FEMA 0.2% flood zone 2018",
     "inundacion", ["inundacion", "flood", "fema", "0.2", "riesgo"],
     "FEMA", 2018, "confirmed", None, None),
    ("landslide", "layer_landsl_monroe_plus_slop50pct",
     "Susceptibilidad a deslizamientos", "Landslide susceptibility",
     "deslizamiento", ["deslizamiento", "landslide", "ladera", "pendiente", "riesgo"],
     "USGS", 2020, "reconstructed", None, None),
    ("land_use_2015", "layer_plan_uso_terrenos_2015",
     "Plan de Uso de Terrenos 2015", "Land Use Plan 2015",
     "uso_de_terrenos", ["uso de terrenos", "land use", "clasificacion", "zonificacion"],
     "Junta de Planificación", 2015, "confirmed", None, None),
    ("hospitals", "layer_hospitales", "Hospitales y CDTs", "Hospitals & CDTs",
     "salud", ["hospital", "cdt", "salud", "health", "clinica"],
     "Departamento de Salud", None, "inferred", "nombre", "muni"),
    ("schools_2021", "layer_dotacional_educacion_escuelas_2021",
     "Escuelas públicas 2021", "Public schools 2021",
     "educacion", ["escuela", "school", "educacion", "education"],
     "Departamento de Educación", 2021, "confirmed", "escuela", "municipio"),
    ("shelters_2023", "layer_refugios_2023", "Refugios de emergencia 2023", "Emergency shelters 2023",
     "refugios", ["refugio", "shelter", "emergencia", "evacuation"],
     "Departamento de la Vivienda", 2023, "confirmed", "instalacio", "municipio"),
    ("state_roads_2021", "layer_carreteras_estatales_segmentadas_agosto_2021",
     "Carreteras estatales 2021", "State roads 2021",
     "vias", ["carretera", "road", "highway", "vial", "transporte"],
     "ACT", 2021, "inferred", None, None),
]

UPSERT = """
INSERT INTO layer_registry (
    id, table_name, name_es, name_en, category, theme, keywords,
    source_agency, source_inventory, vintage_year, metadata_status,
    geometry_type, feature_count, label_column, sublabel_column, style, status
) VALUES (
    %(id)s, %(table_name)s, %(name_es)s, %(name_en)s, %(category)s, %(theme)s, %(keywords)s,
    %(source_agency)s, %(source_inventory)s, %(vintage_year)s, %(metadata_status)s,
    %(geometry_type)s, %(feature_count)s, %(label_column)s, %(sublabel_column)s,
    %(style)s::jsonb, %(status)s
)
ON CONFLICT (id) DO UPDATE SET
    name_es = EXCLUDED.name_es, name_en = EXCLUDED.name_en,
    category = EXCLUDED.category, theme = EXCLUDED.theme, keywords = EXCLUDED.keywords,
    source_agency = EXCLUDED.source_agency, vintage_year = EXCLUDED.vintage_year,
    metadata_status = EXCLUDED.metadata_status, geometry_type = EXCLUDED.geometry_type,
    feature_count = EXCLUDED.feature_count, label_column = EXCLUDED.label_column,
    sublabel_column = EXCLUDED.sublabel_column, style = EXCLUDED.style;
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()

    if args.dry_run:
        print(f"[dry-run] would create layer_registry and seed {len(SEED)} layers")
        return

    print("[registry] creating schema")
    cur.execute(DDL)

    # Pull geometry type / feature count from the existing catalog.
    cur.execute("SELECT layer_name, geometry_type, feature_count FROM spatial_layers")
    facts = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    n = 0
    for (lid, table, name_es, name_en, theme, kw, agency, year, mstatus,
         label_col, sub_col) in SEED:
        gtype, fcount = facts.get(table, (None, None))
        cur.execute(UPSERT, {
            "id": lid, "table_name": table, "name_es": name_es, "name_en": name_en,
            "category": THEME_CATEGORY.get(theme, "Otros"), "theme": theme,
            "keywords": kw, "source_agency": agency,
            "source_inventory": "La Maraña — CAPAS GIS FINAL",
            "vintage_year": year, "metadata_status": mstatus,
            "geometry_type": gtype, "feature_count": fcount,
            "label_column": label_col, "sublabel_column": sub_col,
            "style": json.dumps({"color": THEME_COLOR.get(theme, "#0b5d4b"),
                                 "fillOpacity": 0.35 if theme != "political" else 0,
                                 "lineWidth": 1.1 if theme == "political" else 0.8}),
            "status": "published",
        })
        n += 1

    cur.execute("SELECT count(*), count(*) FILTER (WHERE status='published') FROM layer_registry")
    total, pub = cur.fetchone()
    print(f"[registry] seeded {n} layers — {total} rows, {pub} published")
    cur.execute("""SELECT metadata_status, count(*) FROM layer_registry
                   GROUP BY metadata_status ORDER BY 1""")
    for st, c in cur.fetchall():
        print(f"           {st:14} {c}")


if __name__ == "__main__":
    main()
