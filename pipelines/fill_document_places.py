"""Record the municipality of documents whose title names it.

96 documents had no municipality at all. Most are municipal plans whose title
says exactly which municipality they are for - "Mayaguez - Comprehensive
Transportation Study", "TRA-022_Patillas-Short-Range-Transportation-Plan" - but
the field was empty, so a question about Mayagüez never searched Mayagüez's own
transportation study.

The municipality is taken from the document's own title, and only when the
title names exactly one of the 78. A title naming none stays blank and is
treated as island-wide; a title naming two is left for a person to decide.
Nothing is guessed from the text inside the document.

Dry run by default, against whatever DATABASE_URL names - staging first.

Run:
    python -m pipelines.fill_document_places            # dry run
    python -m pipelines.fill_document_places --commit
"""

from __future__ import annotations

import argparse
import os
import re
import unicodedata

import psycopg2


def plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("SELECT name FROM reference_units WHERE unit_type = 'municipio'")
    municipios = [r[0] for r in cur.fetchall()]
    # Longest first, so "San Juan" is not also read as part of "San Juan Bautista"
    # elsewhere, and "Toa Baja" is not mistaken for "Toa Alta". Separators in
    # file names - hyphens, underscores - count as spaces.
    patterns = [
        (
            m,
            re.compile(
                r"(?<![a-z])" + re.escape(plain(m)).replace(r"\ ", r"[\s_-]+") + r"(?![a-z])"
            ),
        )
        for m in sorted(municipios, key=len, reverse=True)
    ]

    cur.execute("SELECT id, title FROM documents WHERE jurisdiction IS NULL OR jurisdiction = ''")
    filled, none, several = [], [], []
    for doc_id, title in cur.fetchall():
        t = plain(title).replace("_", " ").replace("-", " ")
        hits = {m for m, rx in patterns if rx.search(t)}
        if len(hits) == 1:
            m = hits.pop()
            cur.execute("UPDATE documents SET jurisdiction = %s WHERE id = %s", (m, doc_id))
            filled.append((title, m))
        elif hits:
            several.append((title, sorted(hits)))
        else:
            none.append(title)

    print(f"[places] {len(filled)} documents given the municipality their title names")
    for title, m in filled[:8]:
        print(f"    {m:<14} {title[:70]}")
    print(f"[places] {len(none)} name no municipality - island-wide")
    print(f"[places] {len(several)} name more than one - left for a person:")
    for title, ms in several:
        print(f"    {', '.join(ms):<28} {title[:60]}")
    if args.commit:
        conn.commit()
        print("[places] committed")
    else:
        conn.rollback()
        print("[places] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
