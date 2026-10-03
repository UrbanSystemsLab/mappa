"""Give every layer an embedding, so questions find layers by meaning.

The assistant could reach fifteen layers, because fifteen were listed in a
hand-written dictionary mapping words to tables. There are now 601 layers with
data. Writing 601 dictionary entries would not work either: La Maraña's catalogue
changes, their names are inconsistent, and nobody would keep it current.

So a layer gets the same treatment as a document. Its name, description,
category, source agency and the metadata their team reconstructed are embedded
into the same 384-dimension space the questions live in. "Where are the wells?"
then finds Pozo without anyone having written down that a pozo is a well.

The alias table stays, but shrinks to what it should always have been: overrides
for the handful of cases where meaning alone picks the wrong layer.

Run:
    python -m pipelines.embed_layers --commit
"""

from __future__ import annotations

import argparse
import os

import psycopg2
from psycopg2.extras import execute_batch

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def describe(row: dict) -> str:
    """The text that represents a layer.

    Everything a person might say when looking for it: what it is called in both
    languages, what it holds, who made it, and the words their inventory files it
    under. Repeating the name is deliberate - it is the strongest signal and the
    one most likely to appear in a question.
    """
    parts = [
        row.get("name_es"), row.get("name_es"), row.get("name_en"),
        row.get("description_es"), row.get("purpose"),
        row.get("category"), row.get("subcategory"),
        row.get("source_agency"),
        " ".join(row.get("keywords") or []),
    ]
    return " · ".join(p for p in parts if p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--batch", type=int, default=128)
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    from sentence_transformers import SentenceTransformer

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET statement_timeout='300s'")
    cur.execute("ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS embedding vector(384)")
    cur.execute("ALTER TABLE layer_registry ADD COLUMN IF NOT EXISTS embed_text text")
    conn.commit()

    cur.execute("""
        SELECT id, name_es, name_en, description_es, purpose, category,
               subcategory, source_agency, keywords
        FROM layer_registry ORDER BY id
    """)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    print(f"[embed] {len(rows)} layers")

    model = SentenceTransformer(MODEL)
    texts = [describe(r) for r in rows]
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=args.batch,
                        show_progress_bar=False)

    payload = [("[" + ",".join(f"{x:.6f}" for x in v) + "]", t, r["id"])
               for r, t, v in zip(rows, texts, vecs)]
    execute_batch(cur,
                  "UPDATE layer_registry SET embedding=%s::vector, embed_text=%s WHERE id=%s",
                  payload, page_size=100)

    # An index is only worth it above a few thousand rows; at 700 a scan is
    # faster than maintaining a graph, and exact beats approximate here.
    print(f"[embed] embedded {len(payload)} layers")
    if args.commit:
        conn.commit()
        print("[embed] committed")
    else:
        conn.rollback()
        print("[embed] dry run — rolled back. Use --commit to write.")


if __name__ == "__main__":
    main()
