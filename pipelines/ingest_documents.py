"""Ingest documents into Mappa's database.

Reads source documents (JSON corpus for now, PDF/DOCX later),
chunks the text, computes embeddings, and inserts rows into
`documents` and `document_chunks`.

Run:
    python -m pipelines.ingest_documents

Env:
    DATABASE_URL   Postgres connection string (required for --commit)
    EMBED_MODEL    Optional model override
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import psycopg2
from psycopg2.extras import execute_batch
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS_JSON = ROOT / "data" / "documents.json"

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_DIM = 384
CHUNK_TOKENS_TARGET = 400
CHUNK_OVERLAP_TOKENS = 60


@dataclass
class Chunk:
    document_source_id: str
    chunk_index: int
    text: str
    location_tags: list[str]


def load_source_documents(path: Path) -> list[dict]:
    """Load a corpus from either a single JSON array file or a directory of
    per-document JSON files (the default output of pipelines/parse_documents.py).
    A `corpus.json` array inside the directory, if present, is used directly.
    """
    if path.is_dir():
        combined = path / "corpus.json"
        if combined.exists():
            with combined.open(encoding="utf-8") as f:
                return json.load(f)
        docs: list[dict] = []
        for doc_path in sorted(path.glob("*.json")):
            with doc_path.open(encoding="utf-8") as f:
                docs.append(json.load(f))
        return docs
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡])", text)
    return [p for p in parts if p]


def _rough_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def chunk_text(text: str, target: int = CHUNK_TOKENS_TARGET, overlap: int = CHUNK_OVERLAP_TOKENS) -> list[str]:
    """Split text into ~target-token chunks with sentence-aware boundaries and small overlap."""
    sentences = _split_sentences(text)
    chunks: list[str] = []
    buf: list[str] = []
    buf_tokens = 0
    for sentence in sentences:
        s_tokens = _rough_tokens(sentence)
        if buf_tokens + s_tokens > target and buf:
            chunks.append(" ".join(buf))
            if overlap > 0:
                carry: list[str] = []
                carry_tokens = 0
                for prev in reversed(buf):
                    carry.insert(0, prev)
                    carry_tokens += _rough_tokens(prev)
                    if carry_tokens >= overlap:
                        break
                buf = carry
                buf_tokens = carry_tokens
            else:
                buf, buf_tokens = [], 0
        buf.append(sentence)
        buf_tokens += s_tokens
    if buf:
        chunks.append(" ".join(buf))
    return chunks


def build_chunks(documents: Iterable[dict]) -> list[tuple[dict, list[Chunk]]]:
    result: list[tuple[dict, list[Chunk]]] = []
    for doc in documents:
        pieces = chunk_text(doc["text"])
        location_tags = _location_tags_for(doc)
        chunks = [
            Chunk(
                document_source_id=doc["id"],
                chunk_index=i,
                text=p,
                location_tags=location_tags,
            )
            for i, p in enumerate(pieces)
        ]
        result.append((doc, chunks))
    return result


def _location_tags_for(doc: dict) -> list[str]:
    tags: list[str] = []
    juris = (doc.get("jurisdiction") or "").strip()
    if juris:
        tags.append(juris)
    return tags


def embed_chunks(model: SentenceTransformer, chunks: list[Chunk]) -> np.ndarray:
    texts = [c.text for c in chunks]
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def upsert_documents(conn, documents: list[dict]) -> dict[str, int]:
    """Insert or update documents. Returns {source_id: db_id}."""
    sql = """
        INSERT INTO documents (source_id, title, doc_type, jurisdiction, year, url, language, tags)
        VALUES (%(source_id)s, %(title)s, %(doc_type)s, %(jurisdiction)s, %(year)s, %(url)s, %(language)s, %(tags)s)
        ON CONFLICT (source_id) DO UPDATE SET
            title = EXCLUDED.title,
            doc_type = EXCLUDED.doc_type,
            jurisdiction = EXCLUDED.jurisdiction,
            year = EXCLUDED.year,
            url = EXCLUDED.url,
            tags = EXCLUDED.tags
        RETURNING id, source_id;
    """
    id_map: dict[str, int] = {}
    with conn.cursor() as cur:
        for d in documents:
            cur.execute(
                sql,
                {
                    "source_id": d["id"],
                    "title": d["title"],
                    "doc_type": d.get("doc_type"),
                    "jurisdiction": d.get("jurisdiction"),
                    "year": d.get("year"),
                    "url": d.get("url"),
                    "language": d.get("language", "es"),
                    "tags": d.get("tags", []),
                },
            )
            db_id, source_id = cur.fetchone()
            id_map[source_id] = db_id
    return id_map


def replace_chunks(conn, id_map: dict[str, int], chunks: list[Chunk], embeddings: np.ndarray) -> int:
    """Replace chunks for the given documents in one transaction."""
    if not chunks:
        return 0
    doc_ids = tuple({id_map[c.document_source_id] for c in chunks})
    with conn.cursor() as cur:
        cur.execute("DELETE FROM document_chunks WHERE document_id = ANY(%s);", (list(doc_ids),))
        rows = [
            (
                id_map[c.document_source_id],
                c.chunk_index,
                c.text,
                _vector_literal(embeddings[i]),
                c.location_tags,
            )
            for i, c in enumerate(chunks)
        ]
        execute_batch(
            cur,
            """
            INSERT INTO document_chunks (document_id, chunk_index, text, embedding, location_tags)
            VALUES (%s, %s, %s, %s::vector, %s);
            """,
            rows,
            page_size=100,
        )
    return len(rows)


def _vector_literal(vec: np.ndarray) -> str:
    return "[" + ",".join(f"{float(v):.6f}" for v in vec) + "]"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest documents into Mappa database.")
    parser.add_argument("--source", type=Path, default=DOCUMENTS_JSON, help="Path to documents.json")
    parser.add_argument("--commit", action="store_true", help="Actually write to the database (requires DATABASE_URL).")
    parser.add_argument("--model", default=os.environ.get("EMBED_MODEL", DEFAULT_MODEL))
    args = parser.parse_args()

    print(f"[ingest] loading source documents from {args.source}")
    documents = load_source_documents(args.source)
    print(f"[ingest] loaded {len(documents)} documents")

    print(f"[ingest] loading embedding model: {args.model}")
    model = SentenceTransformer(args.model)

    pairs = build_chunks(documents)
    total_chunks = sum(len(cs) for _, cs in pairs)
    print(f"[ingest] built {total_chunks} chunks across {len(pairs)} documents")

    all_chunks: list[Chunk] = [c for _, cs in pairs for c in cs]
    embeddings = embed_chunks(model, all_chunks)
    print(f"[ingest] computed embeddings: shape={embeddings.shape}")

    if not args.commit:
        print("[ingest] dry run — not writing to database. Use --commit to persist.")
        return

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set. Set it or omit --commit.")

    print("[ingest] connecting to database")
    with psycopg2.connect(dsn) as conn:
        id_map = upsert_documents(conn, documents)
        inserted = replace_chunks(conn, id_map, all_chunks, embeddings)
        conn.commit()
    print(f"[ingest] committed {len(id_map)} documents and {inserted} chunks")


if __name__ == "__main__":
    main()
