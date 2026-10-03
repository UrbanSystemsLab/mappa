"""Bake a layer into a PMTiles archive, so tiles are read rather than computed.

Tiles are currently built on demand by PostGIS. For most layers that is fine, but
the heavy ones are not: one landcover tile takes 15 seconds and 465 KB because the
database generalises 1.7 million polygons on every request, for every viewer.

Baking does that work once. The result is a single file of pre-cut tiles served as
static bytes - no database, no CPU, and a cost close to zero. That last part
matters more than speed here, because La Maraña inherits the bill.

The trade is staleness: a baked layer does not change until it is rebuilt. That is
the right trade for their data, which is a published GIS inventory that changes
rarely, not live telemetry.

Run:
    python -m pipelines.bake_tiles --layer layer_landcover_2006
    python -m pipelines.bake_tiles --all          # every published layer
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from pathlib import Path

import psycopg2

from core import TILE_MAX_ZOOM as MAX_ZOOM
from core import TILE_MIN_ZOOM as MIN_ZOOM

OUT = Path("data/tiles")

# Zoom range. Below 4 the whole island is a few pixels; above 14 the full-precision
# geometry is small enough that building on demand is cheap.
# Roughly what the on-demand path produces at low zoom, so baking is a
# straight improvement rather than a trade of speed against weight.
MAX_TILE_BYTES = 160_000


def layer_meta(cur, table: str) -> tuple[str, str, list[str]]:
    """The layer's catalog id, geometry type, and the columns worth carrying."""
    cur.execute(
        """SELECT id, geometry_type, label_column, sublabel_column, tile_properties
                   FROM layer_registry WHERE table_name = %s AND status = 'published'""",
        (table,),
    )
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"{table} is not a published layer")
    lid, geom, label, sub, props = row
    cols = [c for c in ([label, sub, *list(props or [])]) if c]
    return lid, geom or "", sorted(set(cols))


def dump_geojson(table: str, cols: list[str], dsn: str, path: Path) -> None:
    """Export the layer as newline-delimited GeoJSON for tippecanoe.

    GeoJSONSeq rather than one array, so tippecanoe can stream it instead of
    holding 1.7 million features in memory.
    """
    select = ", ".join([f'"{c}"' for c in cols]) or "1 AS _"
    subprocess.run(
        [
            "ogr2ogr",
            "-f",
            "GeoJSONSeq",
            str(path),
            f"PG:{dsn}",
            "-sql",
            f'SELECT {select}, geom FROM "{table}" WHERE geom IS NOT NULL',
            "-lco",
            "RS=NO",
        ],
        check=True,
        capture_output=True,
    )


def bake(path_in: Path, path_out: Path, layer_name: str) -> None:
    """Cut the GeoJSON into a PMTiles archive.

    --drop-densest-as-needed keeps every tile under the size limit by thinning
    features where they are too dense to distinguish anyway, rather than failing
    or producing a tile no browser will accept.
    """
    subprocess.run(
        [
            "tippecanoe",
            "-o",
            str(path_out),
            "-f",
            "-l",
            layer_name,
            "-Z",
            str(MIN_ZOOM),
            "-z",
            str(MAX_ZOOM),
            # Drop the smallest features first, which is what the on-demand path
            # does: a shape under a pixel across costs bytes and draws nothing.
            # The default (--drop-densest-as-needed) thins uniformly and only once a
            # tile is already oversized, which produced tiles three times heavier
            # than the ones it was replacing.
            "--drop-smallest-as-needed",
            "--extend-zooms-if-still-dropping",
            "--simplification=10",
            f"--maximum-tile-bytes={MAX_TILE_BYTES}",
            str(path_in),
        ],
        check=True,
        capture_output=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")
    OUT.mkdir(parents=True, exist_ok=True)

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("SET statement_timeout='0'")

    if args.all:
        cur.execute("""SELECT table_name FROM layer_registry
                       WHERE status='published' AND table_name IS NOT NULL
                       ORDER BY feature_count DESC NULLS LAST""")
        tables = [r[0] for r in cur.fetchall()]
    elif args.layer:
        tables = [args.layer]
    else:
        raise SystemExit("pass --layer or --all")

    for table in tables:
        lid, _geom, cols = layer_meta(cur, table)
        gj = OUT / f"{table}.geojsonl"
        pm = OUT / f"{table}.pmtiles"
        t0 = time.time()
        print(f"[bake] {table}")
        dump_geojson(table, cols, dsn, gj)
        print(f"       exported {gj.stat().st_size / 1e6:.1f} MB  ({time.time() - t0:.0f}s)")
        bake(gj, pm, lid)
        gj.unlink()
        print(
            f"       -> {pm.name}  {pm.stat().st_size / 1e6:.1f} MB  total {time.time() - t0:.0f}s"
        )


if __name__ == "__main__":
    main()
