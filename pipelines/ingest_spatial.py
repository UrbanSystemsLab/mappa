"""Ingest spatial layers from a GeoPackage (or shapefile) into Mappa's PostGIS.

For each layer requested, this pipeline:
    1. Reads metadata (feature count, geometry type, source CRS).
    2. Inserts/updates a row in `spatial_layers`.
    3. Copies the layer into its own table `layer_<layer_name>` (reprojected to EPSG:4326)
       using ogr2ogr, which handles CRS conversion and attribute mapping.

Run:
    python -m pipelines.ingest_spatial \\
        --source data/raw/la_marana.gpkg \\
        --layer g03_legales_municipios_2015 \\
        --layer barrios_2015_geoid_corrected_16_nov17 \\
        --commit

Env:
    DATABASE_URL   Postgres connection string (required for --commit)
    OGR2OGR_BIN    Optional path to the ogr2ogr binary (default: 'ogr2ogr')
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parent.parent

# Priority layers we plan to ingest for the MVP. Users may pass --layer to override.
DEFAULT_LAYERS = [
    "g03_legales_municipios_2015",
    "barrios_2015_geoid_corrected_16_nov17",
    "g23_riesgo_inundacion_fema_firms_2009",
    "refugios_2023",
    "Hospitales",
]


def read_layer_metadata(gpkg_path: Path, layer_name: str) -> dict:
    """Read basic metadata for a layer directly from the GeoPackage's SQLite tables."""
    conn = sqlite3.connect(str(gpkg_path))
    try:
        cur = conn.execute(
            "SELECT srs_id FROM gpkg_contents WHERE table_name = ?", (layer_name,)
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"layer '{layer_name}' not found in {gpkg_path}")
        srid = row[0]

        cur = conn.execute(
            "SELECT geometry_type_name FROM gpkg_geometry_columns WHERE table_name = ?",
            (layer_name,),
        )
        geom_row = cur.fetchone()
        geometry_type = geom_row[0] if geom_row else None

        feature_count = conn.execute(
            f"SELECT COUNT(*) FROM \"{layer_name}\""
        ).fetchone()[0]
    finally:
        conn.close()
    return {"srid": srid, "geometry_type": geometry_type, "feature_count": feature_count}


def upsert_layer_row(conn, layer_name: str, source_file: Path, meta: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO spatial_layers (layer_name, source_file, source_srid, geometry_type, feature_count)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (layer_name) DO UPDATE SET
                source_file = EXCLUDED.source_file,
                source_srid = EXCLUDED.source_srid,
                geometry_type = EXCLUDED.geometry_type,
                feature_count = EXCLUDED.feature_count,
                ingested_at = NOW();
            """,
            (
                layer_name,
                str(source_file),
                meta["srid"],
                meta["geometry_type"],
                meta["feature_count"],
            ),
        )


def load_layer_via_ogr2ogr(gpkg_path: Path, layer_name: str, dsn: str) -> None:
    """Copy a layer from the GeoPackage into PostGIS as table `layer_<layer_name>`.
    Reprojects to EPSG:4326 for consistent downstream use.
    """
    ogr2ogr = os.environ.get("OGR2OGR_BIN", "ogr2ogr")
    if not shutil.which(ogr2ogr):
        raise SystemExit(
            f"ogr2ogr not found on PATH (looked for '{ogr2ogr}'). "
            "Install GDAL (e.g. `brew install gdal`) or set OGR2OGR_BIN."
        )
    target_table = f"layer_{layer_name}".lower()
    cmd = [
        ogr2ogr,
        "-f",
        "PostgreSQL",
        f"PG:{dsn}",
        str(gpkg_path),
        layer_name,
        "-nln",
        target_table,
        "-t_srs",
        "EPSG:4326",
        "-overwrite",
        "-lco",
        "GEOMETRY_NAME=geom",
        "-lco",
        "FID=id",
        "-nlt",
        "PROMOTE_TO_MULTI",
    ]
    print("[ingest-spatial] running ogr2ogr:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest spatial layers into Mappa PostGIS.")
    parser.add_argument("--source", type=Path, required=True, help="Path to GeoPackage or shapefile.")
    parser.add_argument(
        "--layer",
        action="append",
        default=None,
        help="Layer name to ingest. Repeat flag for multiple. Defaults to Mappa's priority set.",
    )
    parser.add_argument("--commit", action="store_true", help="Actually run ogr2ogr and write rows.")
    args = parser.parse_args()

    layers = args.layer or DEFAULT_LAYERS

    print(f"[ingest-spatial] source: {args.source}")
    print(f"[ingest-spatial] layers: {layers}")

    if not args.source.exists():
        raise SystemExit(f"source not found: {args.source}")

    metadata: dict[str, dict] = {}
    for layer in layers:
        meta = read_layer_metadata(args.source, layer)
        print(
            f"[ingest-spatial] {layer}: srid={meta['srid']}, "
            f"geometry={meta['geometry_type']}, features={meta['feature_count']}"
        )
        metadata[layer] = meta

    if not args.commit:
        print("[ingest-spatial] dry run — no ogr2ogr, no DB writes. Use --commit to persist.")
        return

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set. Set it or omit --commit.")

    with psycopg2.connect(dsn) as conn:
        for layer, meta in metadata.items():
            upsert_layer_row(conn, layer, args.source, meta)
        conn.commit()
    print("[ingest-spatial] metadata rows committed. Loading features via ogr2ogr...")

    for layer in layers:
        load_layer_via_ogr2ogr(args.source, layer, dsn)

    print("[ingest-spatial] done.")


if __name__ == "__main__":
    main()
