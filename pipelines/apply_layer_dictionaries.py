"""Name each layer's fields with La Maraña's own descriptions.

Reads their data dictionaries (see pipelines/layer_dictionaries.py) and writes
property_labels, so a click on the wind layer reads "Average wind speed in
January during the baseline period (1995-2004), in knots." instead of
JanBASEAvg. Their dictionaries are in English; a Spanish label is written only
when they give one, so the Spanish map shows the same English words rather
than a translation of ours.

Which fields a click shows (their Include / Exclude) is applied by
profile_layers, which runs after this.

Dry run by default, and the database it writes to is the one DATABASE_URL names:
point it at staging first.

Run:
    python -m pipelines.apply_layer_dictionaries            # dry run
    python -m pipelines.apply_layer_dictionaries --commit
"""

from __future__ import annotations

import argparse
import json
import os

import psycopg2

from pipelines.layer_dictionaries import resolve, rows_by_sheet, sheets_by_table


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    tables = sheets_by_table()
    sheets = rows_by_sheet()
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    layers = labelled = missing = 0
    for table, sheet in sorted(tables.items()):
        cur.execute(
            "SELECT id, coalesce(property_labels, '{}'::jsonb) FROM layer_registry "
            "WHERE table_name = %s",
            (table,),
        )
        found = cur.fetchall()
        if not found:
            missing += 1
            print(f"    not in the registry: {table}")
            continue
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s",
            (table,),
        )
        fields = resolve(sheets.get(sheet, []), [c for (c,) in cur.fetchall()])
        theirs = {f.column: {"en": f.description} for f in fields if f.description}
        for rid, labels in found:
            # Their description replaces any label for the same column.
            merged = {k: v for k, v in (labels or {}).items() if k not in theirs} | theirs
            cur.execute(
                "UPDATE layer_registry SET property_labels = %s WHERE id = %s",
                (json.dumps(merged, ensure_ascii=False), rid),
            )
        layers += 1
        labelled += len(theirs)

    print(f"[dictionaries] {layers} layers, {labelled} fields named in their words")
    if missing:
        print(f"[dictionaries] {missing} mapped tables are not in the registry")
    if args.commit:
        conn.commit()
        print("[dictionaries] committed")
    else:
        conn.rollback()
        print("[dictionaries] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
