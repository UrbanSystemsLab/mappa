"""Rebuild layer_registry from La Maraña's GIS inventory.

The registry held ten layers we had loaded by hand. Their inventory lists 649,
and that sheet — not our list — is the record of what exists. This makes every
one of the 649 discoverable, carrying their name, their category and their
source, and marks each with whether we can actually draw it yet.

A layer we have not loaded is 'catalogued': it shows up in search and says so,
rather than being invisible or pretending to be a toggle that does nothing. As
each layer's data lands it flips to 'published'.

Nothing here invents metadata. A field their sheet leaves blank stays blank.

No trust rating is set here. A rating is recorded only where their team wrote
one, by import_reconstructed_metadata.

Run:
    python -m pipelines.rebuild_layer_registry            # dry run
    python -m pipelines.rebuild_layer_registry --commit
"""

from __future__ import annotations

import argparse
import os
import re
import unicodedata
from pathlib import Path

import psycopg2

SOURCE = "La Maraña — Inventario_Territorial_Docs_GIS"

# Their sheet writes geometry in Spanish, English, and a few mixed forms. Map to
# what PostGIS and the map client use; anything unrecognised stays unknown rather
# than being guessed into a shape that would render wrong.
GEOMETRY = {
    "polígono": "Polygon",
    "poligono": "Polygon",
    "poligono/vector": "Polygon",
    "punto": "Point",
    "point": "Point",
    "points": "Point",
    "línea": "LineString",
    "linea": "LineString",
    "line": "LineString",
    "raster": "Raster",
}


def strip_accents(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    return "".join(c for c in t if not unicodedata.combining(c))


def normalize_geometry(raw: str | None) -> str | None:
    if not raw:
        return None
    return GEOMETRY.get(raw.strip().lower())


def readable(layer_name: str) -> str:
    """Their layer names are file names: Areas_Protegidas_2018. Make them read as
    a label without translating or editorialising — underscores become spaces."""
    return re.sub(r"\s+", " ", layer_name.replace("_", " ")).strip()


def registry_id(gis_id: str) -> str:
    """Key the registry on their GIS ID, so a row here always traces to a row on
    their sheet. Our ten hand-loaded layers keep their existing slugs."""
    return gis_id.strip().lower()


def keywords_for(name: str, category: str | None, subcategory: str | None) -> list[str]:
    """Search terms from what the sheet already says. Accent-stripped duplicates
    are included so a search for 'poligono' finds 'Polígono'."""
    parts = [p for p in (name, category, subcategory) if p]
    words = {w for p in parts for w in re.split(r"[^\wÀ-ÿ]+", p.lower()) if len(w) > 2}
    return sorted(words | {strip_accents(w) for w in words})


def link_loaded_layers(cur) -> list[tuple]:
    """Attach each already-loaded layer to its row on their sheet.

    Only an exact name match counts. Their sheet carries genuine duplicates -
    three separate rows named Hospitales - so a near match would pick one at
    random and record it as provenance. Anything short of exact is returned for
    La Maraña to resolve, because only they can say which row is the real one.
    """
    cur.execute("SELECT id, table_name FROM layer_registry WHERE status='published'")
    loaded = cur.fetchall()
    cur.execute("SELECT gis_id, layer_name FROM layer_inventory WHERE layer_name IS NOT NULL")
    inventory = [(g, n, _key(n)) for g, n in cur.fetchall()]

    ambiguous = []
    for rid, table in loaded:
        if not table:
            continue
        target = _key(table[len("layer_") :] if table.startswith("layer_") else table)
        exact = [(g, n) for g, n, k in inventory if k == target]
        if len(exact) == 1:
            cur.execute("UPDATE layer_registry SET gis_id=%s WHERE id=%s", (exact[0][0], rid))
            cur.execute(
                "UPDATE layer_inventory SET served_layer_id=%s WHERE gis_id=%s", (rid, exact[0][0])
            )
            continue
        near = [
            (g, n)
            for g, n, k in inventory
            if k and (k in target or target in k) and abs(len(k) - len(target)) < 24
        ]
        ambiguous.append(
            (rid, table, "; ".join(g for g, _ in near[:6]), "; ".join(n for _, n in near[:6]))
        )
    return ambiguous


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", strip_accents(name or "").lower())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("SET statement_timeout='180s'")

    # A catalogued layer has no table yet, and a registry row needs to say which
    # of their inventory rows it came from.
    cur.execute("ALTER TABLE layer_registry ALTER COLUMN table_name DROP NOT NULL")
    # Their sheet is Spanish. An English name we made up would read as theirs.
    cur.execute("ALTER TABLE layer_registry ALTER COLUMN name_en DROP NOT NULL")
    cur.execute("ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS gis_id text")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_layer_registry_gis ON layer_registry (gis_id)")
    cur.execute("ALTER TABLE layer_registry DROP CONSTRAINT IF EXISTS layer_registry_status_check")
    cur.execute("""ALTER TABLE layer_registry ADD CONSTRAINT layer_registry_status_check
                   CHECK (status IN ('published','catalogued','draft','hidden'))""")

    cur.execute("SELECT id FROM layer_registry")
    existing = {r[0] for r in cur.fetchall()}

    cur.execute("""
        SELECT gis_id, layer_name, category, subcategory, geometry_type, description,
               data_source, crs, publication_date, file_format, usage_restrictions
        FROM layer_inventory WHERE gis_id IS NOT NULL AND layer_name IS NOT NULL
        ORDER BY gis_id
    """)
    rows = cur.fetchall()

    added = skipped = 0
    for (
        gis_id,
        layer_name,
        category,
        subcategory,
        geom,
        desc,
        source,
        _crs,
        pub,
        _fmt,
        restrictions,
    ) in rows:
        rid = registry_id(gis_id)
        if rid in existing:
            skipped += 1
            continue
        geometry = normalize_geometry(geom)
        year = None
        if pub:
            m = re.search(r"(19|20)\d{2}", str(pub))
            year = int(m.group(0)) if m else None
        cur.execute(
            """
            INSERT INTO layer_registry
                (id, gis_id, table_name, name_es, name_en, description_es,
                 category, subcategory, geometry_type, keywords, source_agency,
                 source_inventory, vintage_year, license, status)
            VALUES (%s,%s,NULL,%s,NULL,%s,%s,%s,%s,%s,%s,%s,%s,%s,'catalogued')
            ON CONFLICT (id) DO NOTHING
        """,
            (
                rid,
                gis_id,
                readable(layer_name),
                desc,
                category or "Sin clasificar",
                subcategory,
                geometry,
                keywords_for(layer_name, category, subcategory),
                source,
                SOURCE,
                year,
                restrictions,
            ),
        )
        added += cur.rowcount

    # Point their sheet back at the registry, so the inventory row and the layer
    # the map serves are linked in both directions.
    cur.execute("""
        UPDATE layer_inventory i SET served_layer_id = r.id
        FROM layer_registry r WHERE r.gis_id = i.gis_id AND i.served_layer_id IS DISTINCT FROM r.id
    """)
    linked = cur.rowcount
    ambiguous = link_loaded_layers(cur)

    cur.execute("SELECT status, count(*) FROM layer_registry GROUP BY 1 ORDER BY 2 DESC")
    dist = cur.fetchall()

    print(f"[layers] inventory rows      {len(rows)}")
    print(f"[layers] already in registry {skipped}")
    print(f"[layers] added as catalogued {added}")
    print(f"[layers] inventory linked    {linked}")
    print("\n[layers] registry by status:")
    for s, n in dist:
        print(f"    {n:>4}  {s}")
    if ambiguous:
        import csv

        out = Path("data/eval/layer_match_review.csv")
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["loaded_layer", "our_table", "candidate_gis_ids", "candidate_names"])
            for row in ambiguous:
                w.writerow(row)
        print(
            f"\n[layers] {len(ambiguous)} loaded layers could not be matched to one "
            f"inventory row -> {out}"
        )
        for rid, _tbl, gids, _names in ambiguous:
            print(f"    {rid:22} {gids or 'no candidate'}")

    if args.commit:
        conn.commit()
        print("\n[layers] committed")
    else:
        conn.rollback()
        print("\n[layers] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
