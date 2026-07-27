"""Run the retrieval evaluation against the validated eval set.

Measures how well semantic retrieval surfaces the expected documents for each
labeled question. Reports recall@k and mean reciprocal rank (MRR) over the set,
plus per-question misses so you can see WHERE retrieval fails.

This is the smoke/quality harness referenced in the plan. It intentionally
evaluates *retrieval* (the part we control and are tuning) rather than final LLM
answer text — answer-quality grading is a later, LLM-specialist-owned step.

Run (uses the in-memory semantic index over data/documents.json by default):
    python -m pipelines.run_eval --eval data/eval_set.jsonl --k 5

Notes:
    - Retrieval is compared by document source_id. The eval set's
      `expected_doc_ids` must match the `id` field of documents in the corpus.
    - Swap the embedding model via EMBED_MODEL to benchmark (Project 10).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from api.retrieval import retrieve_with_scores


def load_eval(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(eval_items: list[dict[str, Any]], k: int) -> dict[str, Any]:
    recall_hits = 0
    reciprocal_ranks = 0.0
    per_item: list[dict[str, Any]] = []

    for item in eval_items:
        expected = set(item["expected_doc_ids"])
        results = retrieve_with_scores(item["question_es"], top_k=k)
        retrieved_ids = [doc["id"] for _, doc in results]

        # rank (1-based) of the first expected doc that appears, else None
        first_hit_rank = next(
            (i + 1 for i, doc_id in enumerate(retrieved_ids) if doc_id in expected),
            None,
        )
        hit = first_hit_rank is not None
        recall_hits += int(hit)
        reciprocal_ranks += (1.0 / first_hit_rank) if first_hit_rank else 0.0

        per_item.append({
            "id": item["id"],
            "question": item["question_es"],
            "expected": sorted(expected),
            "retrieved": retrieved_ids,
            "hit_rank": first_hit_rank,
        })

    n = len(eval_items) or 1
    return {
        "n": len(eval_items),
        "k": k,
        "recall_at_k": recall_hits / n,
        "mrr": reciprocal_ranks / n,
        "per_item": per_item,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Mappa retrieval against the eval set.")
    parser.add_argument("--eval", type=Path, default=Path("data/eval_set.jsonl"))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--show-misses", action="store_true", help="Print questions with no expected doc in top-k.")
    args = parser.parse_args()

    if not args.eval.exists():
        raise SystemExit(f"eval set not found: {args.eval} (build it with pipelines.build_eval_set)")

    eval_items = load_eval(args.eval)
    if not eval_items:
        raise SystemExit("eval set is empty")

    report = evaluate(eval_items, args.k)
    print(f"[eval] n={report['n']}  k={report['k']}")
    print(f"[eval] recall@{report['k']} = {report['recall_at_k']:.3f}")
    print(f"[eval] MRR            = {report['mrr']:.3f}")

    misses = [it for it in report["per_item"] if it["hit_rank"] is None]
    print(f"[eval] misses: {len(misses)}/{report['n']}")
    if args.show_misses:
        for m in misses:
            print(f"  ✗ {m['id']}: {m['question'][:70]!r}")
            print(f"      expected {m['expected']}  got {m['retrieved']}")


if __name__ == "__main__":
    main()
