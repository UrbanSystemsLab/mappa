"""Record which documents discuss each map layer.

A layer and a document passage are embedded by the same model, so the passages
closest in meaning to a layer are the ones that talk about what it maps: FEMA's
flood zones reach the flood sections of each municipio's hazard mitigation plan,
the Land Use Plan reaches the territorial plans and the Reglamento Conjunto.
For each layer with data, every document is scored by how many of its passages
come within PASSAGE_SCORE of the layer, and the documents with any are kept in
layer_documents.

Nothing is named in code: the links come from the layers' own text (name,
description, what profile_layers found in them) and the documents' own words.

A layer is only scored again when its text or the documents change, so a
release after the first takes seconds. The first run takes about 2-3 s a layer.

Run:
    python -m pipelines.link_layer_documents            # dry run: counts only
    python -m pipelines.link_layer_documents --commit
    python -m pipelines.link_layer_documents --commit --layer fema_flood_2009
"""

from __future__ import annotations

import argparse
import os
import time

import psycopg2

# A passage at least this close to a layer is about what the layer maps. Checked
# by reading the passages it keeps for flood zones, land use, shelters and
# protected areas: above it they are about the topic, below it they drift.
PASSAGE_SCORE = 0.55


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--layer", help="only this layer id")
    ap.add_argument("--all", action="store_true", help="score every layer, changed or not")
    args = ap.parse_args()
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()
    cur.execute("SELECT to_regclass('layer_documents')")
    if cur.fetchone()[0] is None:
        raise SystemExit("layer_documents does not exist: run alembic upgrade head first")
    # The documents' state: any passage added or removed changes it.
    cur.execute("SELECT count(*), coalesce(max(id), 0) FROM document_chunks")
    chunks, last = cur.fetchone()
    corpus = f"{chunks}:{last}"
    cur.execute(
        """SELECT r.id, md5(r.embedding::text) || ':' || %s, d.signature
           FROM layer_registry r LEFT JOIN layer_document_runs d ON d.layer_id = r.id
           WHERE r.status IN ('published', 'loaded') AND r.table_name IS NOT NULL
             AND r.embedding IS NOT NULL AND (%s::text IS NULL OR r.id = %s)
           ORDER BY r.status DESC, r.id""",
        (corpus, args.layer, args.layer),
    )
    todo = [(lid, sig) for lid, sig, done in cur.fetchall() if args.all or sig != done]
    print(f"[layer documents] {len(todo)} layers to score")
    if not args.commit:
        print("[layer documents] dry run - nothing written. Use --commit to score and write.")
        return

    cur.execute("SET max_parallel_workers_per_gather = 4")
    started, links = time.monotonic(), 0
    for i, (layer_id, signature) in enumerate(todo, 1):
        cur.execute("DELETE FROM layer_documents WHERE layer_id = %s", (layer_id,))
        cur.execute(
            """INSERT INTO layer_documents (layer_id, document_id, passages, best)
               SELECT %s, document_id, passages, best FROM (
                   SELECT c.document_id,
                          count(*) FILTER (WHERE s.score >= %s) AS passages,
                          max(s.score) AS best
                   FROM (SELECT embedding FROM layer_registry WHERE id = %s) r,
                        document_chunks c,
                        LATERAL (SELECT 1 - (c.embedding <=> r.embedding) AS score) s
                   GROUP BY c.document_id) x
               WHERE passages > 0""",
            (layer_id, PASSAGE_SCORE, layer_id),
        )
        links += cur.rowcount
        cur.execute(
            """INSERT INTO layer_document_runs (layer_id, signature) VALUES (%s, %s)
               ON CONFLICT (layer_id) DO UPDATE SET signature = EXCLUDED.signature,
                                                    computed_at = now()""",
            (layer_id, signature),
        )
        conn.commit()  # each layer on its own, so a dropped connection loses one
        if i % 25 == 0 or i == len(todo):
            print(f"[layer documents] {i}/{len(todo)} layers, {time.monotonic() - started:.0f}s")
    print(f"[layer documents] {links} links written")


if __name__ == "__main__":
    main()
