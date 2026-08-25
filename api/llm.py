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

# Provider: "ollama" (local, default), "gemini" (Vertex AI — GCP-native, no key,
# auth via the service account), or "openai" (any OpenAI-compatible API).
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
GCP_PROJECT = os.environ.get("GCP_PROJECT", "mappa-lamarana-aecc")
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "us-central1")
_DEFAULT_MODELS = {"ollama": "mistral", "openai": "gpt-4o-mini", "gemini": "gemini-2.5-flash-lite"}
LLM_MODEL = os.environ.get("LLM_MODEL", _DEFAULT_MODELS.get(LLM_PROVIDER, "mistral"))
# Answer language: "en" (default, for verification) or "es" (the real product default).
RESPONSE_LANG = os.environ.get("RESPONSE_LANG", "en").lower()
_GEN_TIMEOUT = 120

SYSTEM_PROMPTS = {
    "es": (
        "Eres MAPPA, un asistente de planificación y riesgos para comunidades de Puerto Rico. "
        "Responde en español. Empieza con una respuesta directa y útil en la primera oración, "
        "luego los detalles clave — conciso (2 a 5 oraciones), sin relleno ni repetición. "
        "Fundamenta TODO únicamente en las FUENTES y los DATOS DEL LUGAR proporcionados; nunca "
        "inventes datos ni cites leyes que no aparezcan en ellos. "
        "Cuando uses una fuente o capa con fecha, menciona su año para que se sepa qué tan actual es "
        "(por ejemplo, «según la capa FEMA de 2018»). Cita las fuentes por número, p. ej. [1]. "
        "Si las fuentes no responden, dilo brevemente y remite a la Junta de Planificación, la OGPe, "
        "el DRNA o el municipio. No brindas asesoría legal vinculante."
    ),
    "en": (
        "You are MAPPA, a planning and hazard assistant for Puerto Rico communities. Answer in English. "
        "Lead with a direct, useful answer in the first sentence, then the key specifics — concise "
        "(2–5 sentences), no filler or repetition. "
        "Ground EVERYTHING only in the provided SOURCES and MAP FACTS; never invent facts or cite laws "
        "not in them. When you rely on a dated source or map layer, note its year so the reader knows how "
        "current it is (e.g., 'per the 2018 FEMA layer'). Cite sources by number, e.g. [1]. "
        "If the sources don't answer the question, say so briefly and point to the Junta de Planificación, "
        "OGPe, DRNA, or the municipality. Do not give binding legal advice."
    ),
}

_USER_INSTRUCTION = {
    "es": "Redacta la respuesta en español, citando las fuentes con [n].",
    "en": "Write the answer in English, citing the sources with [n].",
}


def is_available() -> bool:
    """True if the configured LLM provider is reachable/configured."""
    if LLM_PROVIDER == "gemini":
        return True  # authenticated via the service account on GCP
    if LLM_PROVIDER == "openai":
        return bool(OPENAI_API_KEY)
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _chat_gemini(messages: list[dict[str, str]]) -> str:
    """Vertex AI Gemini via the google-genai SDK. Auth via the service account (ADC)."""
    from google import genai
    from google.genai import types

    client = genai.Client(vertexai=True, project=GCP_PROJECT, location=VERTEX_LOCATION)
    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    contents = [
        types.Content(role=("model" if m["role"] == "assistant" else "user"),
                      parts=[types.Part.from_text(text=m["content"])])
        for m in messages if m["role"] != "system"
    ]
    resp = client.models.generate_content(
        model=LLM_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=system, temperature=0.2, max_output_tokens=800),
    )
    return (resp.text or "").strip()


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=_GEN_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _chat(messages: list[dict[str, str]]) -> str:
    """Send chat messages to the configured provider, return the answer text."""
    if LLM_PROVIDER == "gemini":
        return _chat_gemini(messages)
    if LLM_PROVIDER == "openai":
        resp = _post_json(
            f"{OPENAI_BASE_URL}/chat/completions",
            {"model": LLM_MODEL, "messages": messages, "temperature": 0.2},
            {"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"},
        )
        return (resp["choices"][0]["message"]["content"] or "").strip()
    # default: local Ollama
    resp = _post_json(
        f"{OLLAMA_URL}/api/chat",
        {"model": LLM_MODEL, "messages": messages, "stream": False, "options": {"temperature": 0.2}},
        {"Content-Type": "application/json"},
    )
    return (resp.get("message", {}).get("content") or "").strip()


def _sources_block(docs: list[dict[str, Any]]) -> str:
    lines = []
    for i, d in enumerate(docs, 1):
        text = (d.get("text") or "").strip()
        if len(text) > 900:
            text = text[:900].rstrip() + "…"
        lines.append(f"[{i}] {d.get('title', '?')} ({d.get('year', 's.f.')}):\n{text}")
    return "\n\n".join(lines)


_HAZARD_LABELS = {
    "flood_2009": "FEMA flood zone (FIRM 2009)",
    "flood_0_2pct_2018": "FEMA 0.2%-annual flood zone (2018)",
    "landslide": "Landslide-susceptible area",
}


def _spatial_block(spatial: dict[str, Any], lang: str) -> str:
    """Format the clicked point's map facts as grounded context for the model."""
    yes = "Sí" if lang == "es" else "Yes"
    no = "No"
    lines = []
    muni = spatial.get("municipio")
    if muni:
        lines.append(f"- Municipio: {muni}")
    for key, val in (spatial.get("hazards") or {}).items():
        lines.append(f"- {_HAZARD_LABELS.get(key, key)}: {yes if val else no}")
    for label, count in (spatial.get("facilities") or {}).items():
        lines.append(f"- {label}: {count}")
    if not lines:
        return ""
    head = ("DATOS DEL LUGAR SELECCIONADO (de las capas oficiales del mapa; cítalos como "
            "datos de mapa con su año):" if lang == "es"
            else "MAP FACTS FOR THE SELECTED LOCATION (from official map layers; cite these "
            "as map data with their year):")
    return head + "\n" + "\n".join(lines) + "\n\n"


def narrate(
    question: str,
    docs: list[dict[str, Any]],
    layers: list[str],
    history: list[tuple[str, str]] | None = None,
    spatial: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the local LLM to write a cited answer over the retrieved docs.

    `history` is prior (question, answer) turns so follow-ups keep context.
    `spatial` is the clicked point's map facts, folded in so the answer can reason
    over real conditions (flood/landslide) alongside the documents. Raises on
    transport/parse errors so the caller can fall back.
    """
    lang = RESPONSE_LANG if RESPONSE_LANG in SYSTEM_PROMPTS else "en"
    loc = _spatial_block(spatial, lang) if spatial else ""
    user = (
        f"QUESTION:\n{question.strip()}\n\n"
        f"{loc}"
        f"SOURCES:\n{_sources_block(docs)}\n\n"
        f"{_USER_INSTRUCTION[lang]}"
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPTS[lang]}]
    # Include recent conversation so the model can answer follow-ups in context.
    for prev_q, prev_a in (history or [])[-4:]:
        messages.append({"role": "user", "content": prev_q})
        messages.append({"role": "assistant", "content": prev_a})
    messages.append({"role": "user", "content": user})
    answer = _chat(messages)
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
