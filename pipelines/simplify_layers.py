"""Build a pre-simplified geometry column for heavy layers.

Some source layers carry far more detail than any screen can show: Plan de Uso holds
29 million vertices across 996 polygons, and one landslide polygon alone has 567,000.
Generalising that on every tile request is what makes zoomed-out tiles slow, so it is
done once here instead.

`geom_simple` is read below zoom 12, where the dropped detail is finer than a pixel.
Full-precision `geom` is used when zoomed in, and is never modified.

Written to survive the run rather than assume it: work is committed in batches, so a
dropped connection loses one batch instead of an hour, and re-running resumes where it
stopped. A single 29M-vertex UPDATE in one transaction will take down a small Cloud SQL
instance — which is how this script came to be written this way.

Run:
    python -m pipelines.simplify_layers                  # every heavy layer, resumable
    python -m pipelines.simplify_layers --layer land_use_2015
"""

from __future__ import annotations

import argparse
import os
import time

import psycopg2

# ~30m at Puerto Rico's latitude; below zoom 12 a screen pixel is coarser than this.
TOLERANCE_DEG = 0.0003
MIN_VERTICES = 200_000
BATCH = 200          # rows per transaction; small because single polygons can be huge


def connect():
    return psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=30)


def simplify_layer(conn, lid: str, table: str, tol: float) -> None:
    cur = conn.cursor()
    cur.execute(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS geom_simple geometry')
    conn.commit()

    cur.execute(f'SELECT count(*) FROM "{table}" WHERE geom IS NOT NULL AND geom_simple IS NULL')
    todo = cur.fetchone()[0]
    if todo == 0:
        print(f"[ok]   {lid:22} already complete")
        return
    print(f"[work] {lid:22} {todo:,} rows to simplify")

    done, t0 = 0, time.time()
    while True:
        try:
            cur = conn.cursor()
            # ST_MakeValid guards against self-intersections simplification can
            # introduce; one invalid geometry fails ST_AsMVTGeom for the whole tile.
            cur.execute(
                f'UPDATE "{table}" SET geom_simple = '
                f'ST_MakeValid(ST_SimplifyPreserveTopology(geom, %s)) '
                f'WHERE id IN (SELECT id FROM "{table}" '
                f'             WHERE geom IS NOT NULL AND geom_simple IS NULL LIMIT %s)',
                (tol, BATCH),
            )
            n = cur.rowcount
            conn.commit()
        except psycopg2.OperationalError as exc:
            print(f"       connection lost ({str(exc).strip()[:60]}) — reconnecting")
            time.sleep(5)
            conn = connect()
            continue
        if not n:
            break
        done += n
        print(f"       {done:,}/{todo:,}  ({time.time() - t0:5.0f}s)", flush=True)

    cur = conn.cursor()
    cur.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_geom_simple ON "{table}" USING gist (geom_simple)')
    cur.execute(f'SELECT coalesce(sum(ST_NPoints(geom)),0), coalesce(sum(ST_NPoints(geom_simple)),0) FROM "{table}"')
    before, after = cur.fetchone()
    cur.execute("UPDATE layer_registry SET simplified = true WHERE id = %s", (lid,))
    conn.commit()
    pct = (1 - after / before) * 100 if before else 0
    print(f"[done] {lid:22} {before:,} -> {after:,} vertices ({pct:.1f}% smaller)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer")
    ap.add_argument("--tolerance", type=float, default=TOLERANCE_DEG)
    args = ap.parse_args()
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL not set")

    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS simplified boolean NOT NULL DEFAULT false")
    conn.commit()

    if args.layer:
        cur.execute("SELECT id, table_name FROM layer_registry WHERE id = %s", (args.layer,))
    else:
        cur.execute("SELECT id, table_name FROM layer_registry "
                    "WHERE geometry_type ILIKE '%%polygon%%' OR geometry_type ILIKE '%%line%%' "
                    "ORDER BY id")
    for lid, table in cur.fetchall():
        c2 = conn.cursor()
        c2.execute(f'SELECT coalesce(sum(ST_NPoints(geom)),0) FROM "{table}"')
        nverts = c2.fetchone()[0]
        conn.commit()
        if nverts < MIN_VERTICES and not args.layer:
            print(f"[skip] {lid:22} {nverts:>12,} vertices — cheap enough as-is")
            continue
        simplify_layer(conn, lid, table, args.tolerance)


if __name__ == "__main__":
    main()
