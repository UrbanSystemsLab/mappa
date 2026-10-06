"""Ask the 100 evaluation questions and score the answers.

Runs every question in data/eval/questions_100.tsv against a running Mappa (a
local copy or staging - never production), records what came back, and has a
grader model score each answer. The point is comparison: the same questions,
before and after a change, judged the same way.

Recorded for each question:
    answered      the assistant gave an answer rather than "not enough information"
    sources       citations shown, and how many distinct documents
    place         whether the place in the question was recognised
    figure        whether a computed number from the map data was used
    seconds       how long the answer took

Graded, 0-2 each, by a model reading the question, the answer and the sources:
    relevant      does it answer what was asked
    grounded      is every claim supported by the sources shown
    specific      does it give concrete facts rather than generalities

A model grading another model's answers has known biases - it is lenient, and
it cannot tell whether a source is the right one. Treat the scores as a way to
compare two runs, not as a measure of truth.

Run:
    python -m pipelines.eval_answers --url http://127.0.0.1:8765 --label before
    python -m pipelines.eval_answers --compare before after
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import json
import os
import time
import urllib.request
from pathlib import Path

QUESTIONS = Path("data/eval/questions_100.tsv")
RESULTS = Path("data/eval/results")
GRADER_MODEL = os.environ.get("GRADER_MODEL", "gemini-2.5-flash")

GRADER_PROMPT = """You grade answers from a planning assistant for Puerto Rico.

Question: {question}

Answer:
{answer}

Sources the answer cited (titles only):
{sources}

Score each from 0 to 2:
- relevant: 2 = answers what was asked; 1 = partly; 0 = does not.
- grounded: 2 = nothing claimed beyond what such sources would plausibly say, no invented
  numbers; 1 = some unsupported claims; 0 = clearly invented content. An honest "the
  documents do not say" is grounded.
- specific: 2 = concrete facts (names, figures, rules); 1 = some; 0 = generalities only.

Return JSON: {{"relevant": n, "grounded": n, "specific": n, "note": "one short sentence"}}"""


def ask(url: str, question: str, lang: str) -> dict:
    body = json.dumps({"question": question, "lang": lang}).encode()
    req = urllib.request.Request(f"{url}/ask", body, {"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read())
    except Exception as exc:
        return {"error": str(exc)[:200], "seconds": round(time.monotonic() - t0, 1)}
    data["seconds"] = round(time.monotonic() - t0, 1)
    return data


def grade(question: str, answer: str, sources: list[str]) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(
        vertexai=True,
        project=os.environ.get("GCP_PROJECT", "mappa-lamarana-aecc"),
        location=os.environ.get("VERTEX_LOCATION", "us-central1"),
    )
    prompt = GRADER_PROMPT.format(
        question=question, answer=answer, sources="\n".join(sources) or "(none)"
    )
    resp = client.models.generate_content(
        model=GRADER_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
    )
    return json.loads(resp.text)


def run(url: str, label: str, workers: int) -> None:
    rows = list(csv.DictReader(QUESTIONS.open(encoding="utf-8"), delimiter="\t"))

    def one(row: dict) -> dict:
        got = ask(url, row["question"], "en")
        answer = got.get("answer_es", "")
        sources = [c.get("title", "") for c in got.get("citations", [])]
        rec = {
            "id": row["id"],
            "question": row["question"],
            "category": row["category"],
            "target": row["target"],
            "geo": row["geo"],
            "answer": answer,
            "sources": sources,
            "distinct_sources": len(set(sources)),
            "place": got.get("municipio"),
            "layers": got.get("suggested_layers", []),
            "seconds": got.get("seconds"),
            "error": got.get("error"),
            "tools": got.get("tools", []),
        }
        rec["answered"] = bool(answer) and not answer.lower().startswith(
            ("there isn't enough", "there is not enough", "i couldn't find", "no hay información")
        )
        if answer:
            try:
                rec["grade"] = grade(row["question"], answer, sources)
            except Exception as exc:
                rec["grade"] = {"error": str(exc)[:120]}
        return rec

    out = []
    with cf.ThreadPoolExecutor(workers) as pool:
        for i, rec in enumerate(pool.map(one, rows), 1):
            out.append(rec)
            if i % 10 == 0:
                print(f"  {i}/{len(rows)}", flush=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"{label}.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n", encoding="utf-8"
    )
    print(f"\n[eval] {label}: written to {path}")
    summary(out, label)


def summary(recs: list[dict], label: str) -> dict:
    n = len(recs)
    graded = [
        r["grade"] for r in recs if isinstance(r.get("grade"), dict) and "relevant" in r["grade"]
    ]

    def avg(k: str) -> float:
        return sum(g[k] for g in graded) / len(graded) if graded else 0.0

    secs = sorted(r["seconds"] for r in recs if r.get("seconds") is not None)
    s = {
        "label": label,
        "questions": n,
        "errors": sum(1 for r in recs if r.get("error")),
        "answered": sum(1 for r in recs if r.get("answered")),
        "avg_distinct_sources": round(sum(r["distinct_sources"] for r in recs) / n, 2),
        "relevant": round(avg("relevant"), 2),
        "grounded": round(avg("grounded"), 2),
        "specific": round(avg("specific"), 2),
        "median_seconds": secs[len(secs) // 2] if secs else None,
        "p90_seconds": secs[int(len(secs) * 0.9)] if secs else None,
    }
    for k, v in s.items():
        print(f"  {k:<22} {v}")
    return s


def compare(a: str, b: str) -> None:
    def load(lbl: str) -> list[dict]:
        return [json.loads(x) for x in (RESULTS / f"{lbl}.jsonl").read_text().splitlines() if x]

    ra, rb = load(a), load(b)
    sa, sb = summary(ra, a), summary(rb, b)
    print(f"\n{'':<22} {a:>10} {b:>10}")
    for k in sa:
        if k != "label":
            print(f"  {k:<20} {sa[k]!s:>10} {sb[k]!s:>10}")
    by_id = {r["id"]: r for r in ra}
    worse = [
        r
        for r in rb
        if r.get("grade", {}).get("relevant", 0)
        < by_id.get(r["id"], {}).get("grade", {}).get("relevant", 0)
    ]
    print(f"\n  {len(worse)} questions graded less relevant in {b}:")
    for r in worse[:10]:
        print(f"    {r['id']} {r['question'][:80]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--label")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--compare", nargs=2)
    args = ap.parse_args()
    if args.compare:
        compare(*args.compare)
    elif args.url and args.label:
        if "mappealo.org" in args.url or args.url.rstrip("/").endswith(
            "mappa-7z7lt72m5q-uc.a.run.app"
        ):
            raise SystemExit("Not against production - use a local copy or staging.")
        run(args.url.rstrip("/"), args.label, args.workers)
    else:
        ap.error("give --url and --label, or --compare A B")


if __name__ == "__main__":
    main()
