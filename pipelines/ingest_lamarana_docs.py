"""Ingest documents supplied by La Maraña, keyed to their own inventory IDs.

Reads PDFs from a staging directory, matches each to a row in document_registry by
the ID in its filename (WCRP-014.pdf -> WCRP-014), extracts the text, embeds it and
records the source as La Maraña's folder rather than a government URL.

This is the correct path for documents. The Enlace column in their inventory is
provenance — where a document originally came from — not a place to fetch from.
La Maraña supplied the files themselves; 49 of those links are now dead, and every
one of them has a copy in their folder.

Staging is deliberately separate from acquisition, so it does not matter whether a
file arrived through a Drive download, an unzipped folder, or a GCS copy.

Run:
    python -m pipelines.ingest_lamarana_docs --dir data/raw/lamarana_docs --commit
    python -m pipelines.ingest_lamarana_docs --dir data/raw/lamarana_docs   # dry run
"""

from __future__ import annotations

import argparse
import os
import re
import unicodedata
from pathlib import Path

import fitz
import psycopg2

SOURCE = "La Maraña — Documentos de planificación (Drive)"
# Their document IDs, as used in both the inventory and their filenames.
ID_RE = re.compile(r"\b((?:DOC|HMP|WCRP|RV|POT|GIS)-\d{2,4})\b", re.I)
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")   # Postgres rejects NUL


def doc_id_for(path: Path, cur) -> tuple[str | None, str]:
    """Resolve a file to one of their IDs.

    Nothing they supplied is dropped for failing to match. A file that carries one
    of their IDs uses it; anything else is still ingested under an ID derived from
    its own filename, because the alternative is discarding a document they gave us
    because our lookup was strict. That is how Reglamento Conjunto 2020 - one of the
    most important regulations in the corpus - was nearly lost.
    """
    m = ID_RE.search(path.stem)
    if m:
        return m.group(1).upper(), "filename id"
    # fall back to a title match against their inventory
    stem = unicodedata.normalize("NFKD", path.stem.lower())
    stem = "".join(c for c in stem if not unicodedata.combining(c))
    stem = re.sub(r"[^a-z0-9]+", " ", stem).strip()
    if len(stem) < 8:
        return None, "name too short to match"
    cur.execute(
        """SELECT doc_id FROM document_registry
           WHERE regexp_replace(lower(unaccent_fallback(title)), '[^a-z0-9]+', ' ', 'g') LIKE %s
           LIMIT 2""",
        (f"%{stem[:40]}%",),
    )
    rows = cur.fetchall()
    if len(rows) == 1:
        return rows[0][0], "title match"
    # Unmatched but still theirs: keep it, under a stable ID from the filename.
    slug = re.sub(r"[^A-Za-z0-9]+", "-", path.stem).strip("-")[:48].upper()
    return f"LM-{slug}", "kept, no inventory row"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/raw/lamarana_docs")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    cur = conn.cursor()
    # unaccent may not be installed; provide a plain-SQL fallback either way.
    cur.execute("""
        CREATE OR REPLACE FUNCTION unaccent_fallback(t text) RETURNS text AS $$
          SELECT translate($1, 'áéíóúñüÁÉÍÓÚÑÜ', 'aeiounuAEIOUNU')
        $$ LANGUAGE sql IMMUTABLE;
    """)

    pdfs = sorted(Path(args.dir).glob("**/*.pdf"))
    print(f"[lamarana] {len(pdfs)} PDF(s) staged in {args.dir}")
    out, unmatched = [], []
    for p in pdfs:
        did, how = doc_id_for(p, cur)
        if not did:
            unmatched.append((p.name, how))
            continue
        cur.execute("SELECT title, year, municipio, doc_type FROM document_registry WHERE doc_id=%s", (did,))
        row = cur.fetchone()
        if not row:
            # Not on the Documentos sheet. GIS-* ids are catalogued on their layer
            # sheets; anything else is a file they supplied that the inventory has
            # not caught up with. Either way it is theirs, so register and keep it.
            cur.execute("SELECT layer_name, category FROM layer_inventory WHERE gis_id=%s", (did,))
            lay = cur.fetchone()
            title = (lay[0] if lay else p.stem)
            dtype = ("Documentación de capa" if lay else "Sin clasificar en inventario")
            year, muni = None, None
            cur.execute("""INSERT INTO document_registry (doc_id,title,doc_type,category,
                               source_inventory,load_state,load_note)
                           VALUES (%s,%s,%s,%s,%s,'not_attempted',%s)
                           ON CONFLICT (doc_id) DO NOTHING""",
                        (did, title, dtype, (lay[1] if lay else None), SOURCE,
                         "added from their folder; not on the Documentos sheet"))
            how = f"{how}, registered from folder"
        else:
            title, year, muni, dtype = row
        try:
            doc = fitz.open(p)
            text = CTRL.sub("", "\n".join(pg.get_text("text") for pg in doc)).strip()
            doc.close()
        except Exception as exc:
            unmatched.append((p.name, f"unreadable: {exc}"))
            continue
        if len(text) < 500:
            cur.execute("UPDATE document_registry SET load_state='no_text_layer', "
                        "load_note='scanned, no text layer' WHERE doc_id=%s", (did,))
            unmatched.append((p.name, "no text layer (scanned)"))
            continue
        out.append({"id": did, "title": title or p.stem, "jurisdiction": muni,
                    "doc_type": dtype, "year": year, "url": "", "language": "es",
                    "tags": [t for t in (muni, dtype) if t], "text": text,
                    "source_inventory": SOURCE})
        print(f"  {did:10} {len(text):>9,} chars  ({how})")

    if unmatched:
        print(f"\n[lamarana] {len(unmatched)} not ingested:")
        for n, why in unmatched[:12]:
            print(f"    {n[:52]:52} {why}")

    if not args.commit:
        print(f"\n[lamarana] dry run — {len(out)} ready. Use --commit to write.")
        return

    import collections, json
    # Their folder can hold a document split across files (POT-065.1.pdf and
    # POT-065.2.pdf). Both resolve to one inventory id, which collides on insert,
    # so suffix the extras rather than dropping a document they supplied.
    by = collections.defaultdict(list)
    for d in out:
        by[d["id"]].append(d)
    deduped = []
    for did, xs in by.items():
        xs.sort(key=lambda x: len(x["text"]), reverse=True)
        deduped.append(xs[0])
        for i, extra in enumerate(xs[1:], start=2):
            extra["id"], extra["title"] = f"{did}-{i}", f"{extra['title']} ({i})"
            deduped.append(extra)
    out = deduped
    staged = Path("data/corpus_lamarana.json")
    staged.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n[lamarana] wrote {staged} ({len(out)} docs)")
    print("[lamarana] now run: python -m pipelines.ingest_documents "
          f"--source {staged} --commit")
    for d in out:
        cur.execute("UPDATE document_registry SET load_state='loaded', load_note=%s "
                    "WHERE doc_id=%s", (SOURCE, d["id"]))
    print(f"[lamarana] marked {len(out)} documents as sourced from their folder")


if __name__ == "__main__":
    main()
