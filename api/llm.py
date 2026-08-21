"""Local LLM narration via Ollama.

Turns the retrieved documents into a grounded, cited Spanish answer using a
locally hosted open-source model (Mistral by default) served by Ollama at
localhost:11434 — no API keys, nothing leaves the machine.

If Ollama is unreachable, callers fall back to the templated composer, so the
app always responds.

Env:
    OLLAMA_URL   default http://localhost:11434
    LLM_MODEL    default "mistral"
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = os.environ.get("LLM_MODEL", "mistral")
# Answer language: "en" (default, for verification) or "es" (the real product default).
RESPONSE_LANG = os.environ.get("RESPONSE_LANG", "en").lower()
_GEN_TIMEOUT = 120

SYSTEM_PROMPTS = {
    "es": (
        "Eres MAPPA, un asistente de planificación territorial y resiliencia para Puerto Rico. "
        "Respondes SIEMPRE en español, de forma clara, breve y práctica. "
        "Usa ÚNICAMENTE la información contenida en las FUENTES proporcionadas; no inventes datos "
        "ni cites leyes que no aparezcan en las fuentes. "
        "Cita las fuentes por su número entre corchetes, por ejemplo [1] o [2]. "
        "Si las fuentes no contienen la respuesta, dilo claramente y sugiere verificar con la "
        "Junta de Planificación, la OGPe, el DRNA o el municipio correspondiente. "
        "No brindas asesoría legal vinculante."
    ),
    "en": (
        "You are MAPPA, a land-use planning and resilience assistant for Puerto Rico. "
        "Always answer in English, clearly, briefly, and practically. "
        "Use ONLY the information in the provided SOURCES; do not invent facts or cite laws "
        "that do not appear in the sources. "
        "Cite sources by their number in brackets, e.g. [1] or [2]. "
        "If the sources do not contain the answer, say so clearly and suggest verifying with the "
        "Puerto Rico Planning Board (Junta de Planificación), OGPe, DRNA, or the relevant municipality. "
        "You do not provide binding legal advice."
    ),
}

_USER_INSTRUCTION = {
    "es": "Redacta la respuesta en español, citando las fuentes con [n].",
    "en": "Write the answer in English, citing the sources with [n].",
}


def is_available() -> bool:
    """True if the Ollama server responds."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _sources_block(docs: list[dict[str, Any]]) -> str:
    lines = []
    for i, d in enumerate(docs, 1):
        text = (d.get("text") or "").strip()
        if len(text) > 900:
            text = text[:900].rstrip() + "…"
        lines.append(f"[{i}] {d.get('title', '?')} ({d.get('year', 's.f.')}):\n{text}")
    return "\n\n".join(lines)


def narrate(
    question: str,
    docs: list[dict[str, Any]],
    layers: list[str],
    history: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Call the local LLM to write a cited answer over the retrieved docs.

    `history` is prior (question, answer) turns so follow-up / "deeper" questions
    keep context. Raises on transport/parse errors so the caller can fall back.
    """
    lang = RESPONSE_LANG if RESPONSE_LANG in SYSTEM_PROMPTS else "en"
    user = (
        f"QUESTION:\n{question.strip()}\n\n"
        f"SOURCES:\n{_sources_block(docs)}\n\n"
        f"{_USER_INSTRUCTION[lang]}"
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPTS[lang]}]
    # Include recent conversation so the model can answer follow-ups in context.
    for prev_q, prev_a in (history or [])[-4:]:
        messages.append({"role": "user", "content": prev_q})
        messages.append({"role": "assistant", "content": prev_a})
    messages.append({"role": "user", "content": user})
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=_GEN_TIMEOUT) as r:
        resp = json.loads(r.read().decode("utf-8"))

    answer = (resp.get("message", {}).get("content") or "").strip()
    if not answer:
        raise RuntimeError("empty LLM response")

    citations = [
        {"id": d["id"], "title": d["title"], "year": d.get("year"), "url": d.get("url", "")}
        for d in docs
    ]
    return {
        "answer_es": answer,
        "citations": citations,
        "suggested_layers": layers,
        "confidence": "alta" if len(docs) >= 2 else "media",
    }
