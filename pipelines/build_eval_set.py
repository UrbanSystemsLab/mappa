"""Normalize labeled Q&A into Mappa's validated evaluation set.

Reads whatever labeled Q&A came from Drive (JSON array, JSONL, or CSV) in an
input directory and emits a single validated `eval_set.jsonl`, one object per
line, in the canonical schema:

    {
      "id": "eval-001",
      "question_es": "¿Puedo construir en zona inundable cerca del río en Ponce?",
      "question_en": "",                         # optional
      "expected_doc_ids": ["doc-firm-fema-pr"],  # document source_ids that SHOULD retrieve
      "expected_layers": ["inundacion"],         # optional: suggested map layers
      "location": "Ponce",                       # optional: jurisdiction / place
      "notes": ""
    }

Input field names are mapped loosely (question/pregunta/q → question_es, etc.)
so partner spreadsheets don't need to match exactly. Rows missing a question or
any expected_doc_ids are reported and dropped (a retrieval eval needs a target).

Run:
    python -m pipelines.build_eval_set --input data/raw/eval --output data/eval_set.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable

QUESTION_KEYS = ("question_es", "question", "pregunta", "q", "consulta")
QUESTION_EN_KEYS = ("question_en", "question_english", "pregunta_en")
DOCIDS_KEYS = ("expected_doc_ids", "expected_docs", "doc_ids", "documentos", "gold_docs")
LAYERS_KEYS = ("expected_layers", "layers", "capas")
LOCATION_KEYS = ("location", "lugar", "municipio", "jurisdiction")


def _first(row: dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [t.strip() for t in re.split(r"[;,|]", str(value)) if t.strip()]


def read_rows(path: Path) -> list[dict[str, Any]]:
    ext = path.suffix.lower()
    if ext == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if ext == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else [data]
    if ext == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    return []


def normalize(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    question = _first(row, QUESTION_KEYS)
    if not question:
        return None, "missing question"
    doc_ids = _as_list(_first(row, DOCIDS_KEYS))
    if not doc_ids:
        return None, f"missing expected_doc_ids for question: {str(question)[:60]!r}"
    return {
        "question_es": str(question).strip(),
        "question_en": str(_first(row, QUESTION_EN_KEYS) or "").strip(),
        "expected_doc_ids": doc_ids,
        "expected_layers": _as_list(_first(row, LAYERS_KEYS)),
        "location": str(_first(row, LOCATION_KEYS) or "").strip(),
        "notes": str(row.get("notes") or "").strip(),
    }, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the validated Mappa eval set.")
    parser.add_argument("--input", type=Path, required=True, help="Directory of labeled Q&A (json/jsonl/csv).")
    parser.add_argument("--output", type=Path, default=Path("data/eval_set.jsonl"))
    args = parser.parse_args()

    if not args.input.is_dir():
        raise SystemExit(f"input dir not found: {args.input}")

    raw_rows: list[dict[str, Any]] = []
    for path in sorted(args.input.rglob("*")):
        if path.suffix.lower() in {".json", ".jsonl", ".csv"}:
            rows = read_rows(path)
            print(f"[eval-build] {path.name}: {len(rows)} rows")
            raw_rows.extend(rows)

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    dropped: list[str] = []
    for row in raw_rows:
        record, err = normalize(row)
        if err:
            dropped.append(err)
            continue
        key = record["question_es"].lower()
        if key in seen:
            dropped.append(f"duplicate: {record['question_es'][:60]!r}")
            continue
        seen.add(key)
        record["id"] = f"eval-{len(out) + 1:03d}"
        out.append(record)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for record in out:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"[eval-build] wrote {len(out)} eval items → {args.output}")
    if dropped:
        print(f"[eval-build] dropped {len(dropped)}:")
        for d in dropped:
            print(f"  - {d}")


if __name__ == "__main__":
    main()
