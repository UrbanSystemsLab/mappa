"""Put the reviewed English layer names into the database.

Reads data/layer_names_en.csv - their name, the translation, and where the
translation came from - and writes name_en and name_en_source. A name La Maraña
has given themselves is never overwritten by a translation.

Dry run by default, and the database it writes to is the one DATABASE_URL names:
point it at staging first.

Run:
    python -m pipelines.apply_layer_names            # dry run
    python -m pipelines.apply_layer_names --commit
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

import psycopg2

SOURCE = Path("data/layer_names_en.csv")
THEIRS = "La Maraña"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")
    with SOURCE.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["name_en"].strip()]

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    written = kept = 0
    for r in rows:
        cur.execute(
            """UPDATE layer_registry SET name_en = %s, name_en_source = %s
               WHERE id = %s AND coalesce(name_en_source, '') NOT LIKE %s""",
            (r["name_en"].strip(), r["source"], r["id"], THEIRS + "%"),
        )
        if cur.rowcount:
            written += 1
        else:
            kept += 1
    print(f"[names] {written} English names written, {kept} left as they were")
    if args.commit:
        conn.commit()
        print("[names] committed")
    else:
        conn.rollback()
        print("[names] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
