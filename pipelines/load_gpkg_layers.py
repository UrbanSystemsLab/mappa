"""Load La Maraña's GeoPackage into PostGIS, so their layers can actually be drawn.

The catalog lists 649 layers because that is what their inventory sheet holds.
The GeoPackage they supplied carries the data for 108 of them, and only ten were
ever loaded - which is why the panel reads 'sin cargar' against almost every row.

For each layer this reprojects to EPSG:4326, loads it into its own table, indexes
it, and flips its catalog row from 'catalogued' to 'published' so the map can
serve tiles for it.

A layer in the GeoPackage that cannot be tied to exactly one inventory row gets
its own registry row citing the GeoPackage - it is still their file, so it is
still their data - rather than being attached to a row it might not be.

Resumable: a layer already loaded is skipped, so a run that dies partway can be
restarted without redoing the large ones.

Run:
    python -m pipelines.load_gpkg_layers --limit 3       # try a few
    python -m pipelines.load_gpkg_layers                 # the rest
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import subprocess
import unicodedata
from pathlib import Path

import psycopg2

DEFAULT_GPKG = Path("data/raw/la_marana.gpkg")
GPKG = DEFAULT_GPKG  # replaced by --source at startup

# Provenance recorded against each layer: which file La Maraña sent it in.
SOURCES = {
    "la_marana.gpkg": "La Maraña — la_marana.gpkg",
    "IPRS_DATA.gpkg": "La Maraña — IPRS_DATA.gpkg",
}
SOURCE = SOURCES["la_marana.gpkg"]
MAX_IDENT = 63  # Postgres identifier limit; a truncated name still has to be unique.

# Noise their export tooling added to layer names. Stripped only when looking for
# a match, never when recording what the layer is called.
NOISE = re.compile(r"(_exportfeatures|_project|_projected|_copy)+$")
THEME_CODE = re.compile(r"^g\d+_(?:g\d+_)*")


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", t)


def match_key(name: str) -> str:
    """Name with the export tooling's noise and theme codes removed."""
    base = NOISE.sub("", name.lower())
    base = THEME_CODE.sub("", base)
    return norm(base)


def norm_keep_words(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def gpkg_layers() -> list[tuple[str, str, int]]:
    """(layer name, geometry type, srid) straight from the GeoPackage's own tables."""
    conn = sqlite3.connect(str(GPKG))
    try:
        rows = conn.execute("""
            SELECT c.table_name, g.geometry_type_name, c.srs_id
            FROM gpkg_contents c
            JOIN gpkg_geometry_columns g ON g.table_name = c.table_name
            WHERE c.data_type = 'features'
            ORDER BY c.table_name
        """).fetchall()
    finally:
        conn.close()
    return rows


def load_one(layer: str, table: str, dsn: str) -> str:
    """Copy one layer into PostGIS, reprojected to 4326.

    Some of their layers already carry a column called ID, of a type that cannot
    serve as the primary key. Naming the key 'id' then fails the whole layer, so
    on that error the load is retried letting ogr2ogr name the key itself. The
    layer arrives either way; only the key column differs, and the tile service
    does not depend on its name.
    """
    # -dim XY drops Z and M. Several of their layers are 3D measured polygons,
    # and ST_Intersection against a 2D boundary returns a degenerate result for
    # those - Cabo Rojo came back with zero protected area when it has 24 km2.
    base = [
        "ogr2ogr",
        "-f",
        "PostgreSQL",
        f"PG:{dsn}",
        str(GPKG),
        layer,
        "-nln",
        table,
        "-t_srs",
        "EPSG:4326",
        "-overwrite",
        "-lco",
        "GEOMETRY_NAME=geom",
        "-lco",
        "SPATIAL_INDEX=GIST",
        "-nlt",
        "PROMOTE_TO_MULTI",
        "-dim",
        "XY",
        "-gt",
        "20000",
        "--config",
        "PG_USE_COPY",
        "YES",
    ]
    try:
        subprocess.run([*base, "-lco", "FID=id"], check=True, capture_output=True, text=True)
        return "id"
    except subprocess.CalledProcessError as exc:
        if "Wrong field type for ID" not in (exc.stderr or ""):
            raise
    subprocess.run(base, check=True, capture_output=True, text=True)
    return "ogc_fid"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--redo", action="store_true")
    ap.add_argument("--source", default=str(DEFAULT_GPKG), help="GeoPackage to load")
    # Loading 500 layers straight onto the map would make the panel unusable.
    # They arrive queryable by the assistant and invisible to the map until
    # La Maraña names the ones worth showing.
    ap.add_argument(
        "--status",
        default="loaded",
        choices=["loaded", "published"],
        help="loaded = queryable but hidden; published = on the map",
    )
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")
    global GPKG, SOURCE
    GPKG = Path(args.source)
    SOURCE = SOURCES.get(GPKG.name, f"La Maraña — {GPKG.name}")
    if not GPKG.exists():
        raise SystemExit(f"{GPKG} not found")

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SET statement_timeout='0'")

    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
    taken = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT gis_id, layer_name FROM layer_inventory WHERE layer_name IS NOT NULL")
    inventory = [(g, n, match_key(n)) for g, n in cur.fetchall()]
    cur.execute("SELECT table_name FROM layer_registry WHERE table_name IS NOT NULL")
    registered = {r[0] for r in cur.fetchall()}

    layers = gpkg_layers()
    print(f"[gpkg] {len(layers)} layers in {GPKG.name}")
    loaded = skipped = failed = linked = standalone = 0

    for layer, _geom_type, _srid in layers:
        table = f"layer_{re.sub(r'[^a-z0-9]+', '_', norm_keep_words(layer)).strip('_')}"[:MAX_IDENT]
        exists = table in taken
        if exists and not args.redo:
            cur.execute(f'SELECT count(*) FROM "{table}"')
            if cur.fetchone()[0] > 0:
                skipped += 1
                continue
        if args.limit and loaded >= args.limit:
            break
        try:
            load_one(layer, table, dsn)
        except subprocess.CalledProcessError as exc:
            print(f"  FAILED  {layer[:48]:48} {(exc.stderr or '')[:80]}")
            failed += 1
            continue
        taken.add(table)
        cur.execute(
            f'SELECT count(*), GeometryType(geom) FROM "{table}" '
            f"WHERE geom IS NOT NULL GROUP BY 2 ORDER BY 1 DESC LIMIT 1"
        )
        row = cur.fetchone()
        count, gtype = (row[0], row[1]) if row else (0, None)
        loaded += 1

        key = match_key(layer)
        hits = [(g, n) for g, n, k in inventory if k == key]
        if len(hits) == 1:
            gis_id = hits[0][0]
            cur.execute(
                """UPDATE layer_registry
                           SET table_name=%s, status=%s, geometry_type=%s,
                               feature_count=%s, updated_at=now()
                           WHERE gis_id=%s""",
                (table, args.status, gtype, count, gis_id),
            )
            linked += 1
            note = f"-> {gis_id}"
        else:
            # Still their data, from the file they gave us, so it belongs in the
            # catalog on its own terms rather than attached to a guessed row.
            rid = norm(layer)[:60] or table
            if table not in registered:
                cur.execute(
                    """
                    INSERT INTO layer_registry
                        (id, table_name, name_es, category, geometry_type, feature_count,
                         source_inventory, status, keywords)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET table_name=EXCLUDED.table_name,
                        status=EXCLUDED.status, feature_count=EXCLUDED.feature_count
                """,
                    (
                        rid,
                        table,
                        NOISE.sub("", layer).replace("_", " ").strip(),
                        "Sin clasificar",
                        gtype,
                        count,
                        SOURCE,
                        args.status,
                        sorted(
                            {
                                w
                                for w in re.split(r"[^a-z0-9]+", norm_keep_words(layer))
                                if len(w) > 2
                            }
                        ),
                    ),
                )
            standalone += 1
            note = "own row (no single inventory match)"
        print(f"  loaded  {layer[:46]:46} {count:>9,} feats  {gtype or '?':<12} {note}")

    print(f"\n[gpkg] loaded {loaded}, skipped {skipped}, failed {failed}")
    print(f"[gpkg] {linked} tied to an inventory row, {standalone} registered on their own")
    cur.execute("SELECT status, count(*) FROM layer_registry GROUP BY 1 ORDER BY 2 DESC")
    for s, n in cur.fetchall():
        print(f"    {n:>4}  {s}")


if __name__ == "__main__":
    main()
