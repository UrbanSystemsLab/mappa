"""Name each layer the way La Maraña named it for the platform.

Their inventory's Capas_Nombres sheet gives every layer a "Nombre Plataforma":
the name users should see ("Catastro de Aguada", not "Mapa Catastral de
Aguada"). pipelines/import_lamarana_inventory loads that sheet into
layer_inventory; this writes their platform name as the layer's Spanish name,
matched by GIS ID. Layers they gave no platform name keep the name they have.

English names are translated from these by translate_layer_names and applied
by apply_layer_names, which runs after this.

Dry run by default, and the database it writes to is the one DATABASE_URL names:
point it at staging first.

Run:
    python -m pipelines.apply_platform_names            # dry run
    python -m pipelines.apply_platform_names --commit
"""

from __future__ import annotations

import argparse
import os

import psycopg2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("SELECT to_regclass('layer_inventory')")
    if cur.fetchone()[0] is None:
        print("[platform names] no layer_inventory here: run import_lamarana_inventory first")
        return
    cur.execute(
        """UPDATE layer_registry r SET name_es = btrim(i.platform_name)
           FROM layer_inventory i
           WHERE r.gis_id = i.gis_id
             AND nullif(btrim(i.platform_name), '') IS NOT NULL
             AND r.name_es IS DISTINCT FROM btrim(i.platform_name)"""
    )
    print(f"[platform names] {cur.rowcount} layers renamed to their platform name")
    cur.execute(
        """SELECT count(*) FROM layer_inventory i
           WHERE nullif(btrim(i.platform_name), '') IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM layer_registry r
                             WHERE r.gis_id = i.gis_id AND r.table_name IS NOT NULL)"""
    )
    print(f"[platform names] {cur.fetchone()[0]} of their names have no layer with data")
    if args.commit:
        conn.commit()
        print("[platform names] committed")
    else:
        conn.rollback()
        print("[platform names] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
