"""Reconcile the registry against the tables that actually exist.

Loading their second GeoPackage re-matched registry rows onto the new file's
copies of layers it already had. That is right - the new copies are the same data
and sometimes richer - but it left the old tables with no registry row, so the
map quietly went from 107 layers to 81 and the alias table pointed at a layer the
catalog no longer knew about.

This finds both kinds of drift:

  * a table with no registry row - either superseded by a newer copy, or a layer
    that would otherwise be lost
  * an alias pointing at a table that is no longer registered

A superseded table is reported, never dropped. Reclaiming the space is a separate
decision, and the duplicates are harmless where they are.

Run:
    python -m pipelines.reconcile_layers --commit
"""

from __future__ import annotations

import argparse
import os
import re
import unicodedata

import psycopg2

# Tables that merely start with layer_ but are not layers.
NOT_LAYERS = {"layer_registry", "layer_inventory"}

SOURCE = "La Maraña — recovered during reconciliation"


def key(name: str) -> str:
    n = unicodedata.normalize("NFKD", (name or "").lower())
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = re.sub(r"^layer_", "", n)
    n = re.sub(r"^g\d+_(?:g\d+_)*", "", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("SET statement_timeout='300s'")

    cur.execute("""SELECT table_name FROM information_schema.tables
                   WHERE table_schema='public' AND table_name LIKE 'layer_%'""")
    tables = {r[0] for r in cur.fetchall()} - NOT_LAYERS
    cur.execute("SELECT table_name FROM layer_registry WHERE table_name IS NOT NULL")
    registered = {r[0] for r in cur.fetchall()}
    by_key = {key(t): t for t in registered}

    superseded, recovered = [], []
    for table in sorted(tables - registered):
        twin = by_key.get(key(table))
        if twin:
            superseded.append((table, twin))
            continue
        # Nothing replaced it, so it would simply vanish from the catalog.
        cur.execute(f'SELECT count(*), GeometryType(geom) FROM "{table}" '
                    f'WHERE geom IS NOT NULL GROUP BY 2 ORDER BY 1 DESC LIMIT 1')
        row = cur.fetchone()
        count, gtype = (row[0], row[1]) if row else (0, None)
        rid = key(table)[:60]
        cur.execute("""
            INSERT INTO layer_registry (id, table_name, name_es, category, geometry_type,
                                        feature_count, source_inventory, metadata_status,
                                        status, keywords)
            VALUES (%s,%s,%s,'Otras capas',%s,%s,%s,'unknown','loaded',%s)
            ON CONFLICT (id) DO UPDATE SET table_name=EXCLUDED.table_name,
                status='loaded', feature_count=EXCLUDED.feature_count
        """, (rid, table, table.replace("layer_", "").replace("_", " "),
              gtype, count, SOURCE,
              sorted({w for w in re.split(r"[^a-z0-9]+", key(table)) if len(w) > 2})))
        recovered.append((table, count))

    # An alias is only useful if its table is still registered.
    from api.spatial_ops import LAYERS
    broken = []
    for concept, spec in LAYERS.items():
        if spec["table"] in registered:
            continue
        twin = by_key.get(key(spec["table"]))
        broken.append((concept, spec["table"], twin))

    print(f"[reconcile] {len(superseded)} tables superseded by a newer copy")
    for t, twin in superseded[:6]:
        print(f"    {t[:46]:48} -> {twin[:40]}")
    if len(superseded) > 6:
        print(f"    …and {len(superseded) - 6} more")
    print(f"\n[reconcile] {len(recovered)} layers recovered that had no registry row:")
    for t, n in recovered:
        print(f"    {t[:46]:48} {n:>9,} features")
    print(f"\n[reconcile] {len(broken)} aliases pointing at an unregistered table:")
    for concept, old, twin in broken:
        print(f"    {concept:14} {old[:42]:44} -> {twin or 'NO REPLACEMENT'}")

    if args.commit:
        conn.commit()
        print("\n[reconcile] committed")
    else:
        conn.rollback()
        print("\n[reconcile] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
