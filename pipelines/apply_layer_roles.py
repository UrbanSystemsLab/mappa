"""Load data/layer_roles.csv into the layer_roles table.

Each row says which layer does a job for the assistant - 'flood', 'schools' - and
how it is called. This replaces three hand-written lists in the code. Editing the
file and running this changes the assistant's behaviour without a code change.

The file names a layer by table; this resolves it to the registry row, and stops
on any row whose layer is not loaded, rather than recording a role nothing can
answer from.

Dry run by default, against whatever DATABASE_URL names - staging first.

Run:
    python -m pipelines.apply_layer_roles            # dry run
    python -m pipelines.apply_layer_roles --commit
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

import psycopg2

SOURCE = Path("data/layer_roles.csv")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")
    with SOURCE.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    problems = []
    cur.execute("DELETE FROM layer_roles")  # the file is the whole truth
    for r in rows:
        cur.execute(
            "SELECT id FROM layer_registry WHERE table_name = %s AND status IN ('published','loaded')",
            (r["table_name"],),
        )
        hit = cur.fetchone()
        if not hit:
            problems.append(f"{r['role']}: {r['table_name']} is not a loaded layer")
            continue
        cur.execute(
            """INSERT INTO layer_roles
                 (role, layer_id, words, countable, checked_on_click, name_col, muni_col)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                r["role"],
                hit[0],
                [w for w in r["words"].split("|") if w.strip()],
                r["countable"].strip().lower() == "yes",
                r["checked_on_click"].strip().lower() == "yes",
                r["name_col"] or None,
                r["muni_col"] or None,
            ),
        )
    for p in problems:
        print(f"  ! {p}")
    print(f"[roles] {len(rows) - len(problems)} of {len(rows)} roles loaded")
    if problems:
        conn.rollback()
        raise SystemExit("[roles] not written - fix the rows above first")
    if args.commit:
        conn.commit()
        print("[roles] committed")
    else:
        conn.rollback()
        print("[roles] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
