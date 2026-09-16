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
import re
import urllib.error
import urllib.request
from typing import Any

# Matches markdown links [text](url), bare http(s):// URLs, and www.* addresses.
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)")
_BARE_URL = re.compile(r"\(?\b(?:https?://|www\.)\S+\)?")


# Phrases the model uses when the sources don't answer the question (both languages).
_DECLINE_MARKERS = (
    "not enough information", "isn't enough information", "is not enough information",
    "there is not enough", "do not contain", "does not contain", "couldn't find",
    "could not find", "no hay información suficiente", "no hay suficiente información",
    "no cuento con", "no encontré", "no se encontró", "no contienen", "no contiene",
    "información suficiente en los documentos",
)


def _is_decline(text: str) -> bool:
    """True if the answer is a 'the sources don't cover this' non-answer."""
    t = text.lower()
    return any(m in t for m in _DECLINE_MARKERS)


def _strip_urls(text: str) -> str:
    """Remove any link/URL the model may have emitted. All source links come from the
    database citations shown in the UI, never from the model's prose — this enforces
    that the LLM contributes no resources of its own."""
    text = _MD_LINK.sub(r"\1", text)  # keep the link text, drop the URL
    text = _BARE_URL.sub("", text)
    text = re.sub(r"(?m)^\s*[\*\-]\s+", "• ", text)  # normalize markdown bullets to •
    return re.sub(r"[ \t]{2,}", " ", text).strip()

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
        "Eres Mappealo, un asistente de planificación y riesgos para comunidades de Puerto Rico. "
        "Responde en español. Empieza con UNA oración de respuesta directa. Luego, si la respuesta "
        "es una lista (metas, riesgos, requisitos, pasos, categorías), añade una lista con viñetas "
        "usando «• » al inicio de cada línea (máximo 6 viñetas), y cita la fuente [n] en cada una; "
        "de lo contrario añade 1 a 3 oraciones concisas. Sin relleno ni repetición. "
        "REGLA ESTRICTA: fundamenta TODO únicamente en las FUENTES y los DATOS DEL LUGAR "
        "proporcionados. Está prohibido usar conocimiento propio o externo, aunque sepas la "
        "respuesta. Si preguntan por algo que no está en las FUENTES ni en los DATOS DEL "
        "LUGAR, dilo — no llenes el vacío. Nunca inventes datos, "
        "cifras, agencias ni leyes que no aparezcan literalmente en las FUENTES. Nunca escribas "
        "enlaces, URLs ni direcciones web — las fuentes se muestran aparte con su enlace. "
        "Cuando uses una fuente o capa con fecha, menciona su año (por ejemplo, «según la capa FEMA "
        "de 2018»). Cita las fuentes por número, p. ej. [1]. "
        "Si las FUENTES no contienen la respuesta, di exactamente que no hay información suficiente "
        "en los documentos disponibles y remite a la Junta de Planificación, la OGPe, el DRNA o el "
        "municipio — sin inventar una respuesta. No brindas asesoría legal vinculante."
    ),
    "en": (
        "You are Mappealo, a planning and hazard assistant for Puerto Rico communities. Answer in English. "
        "Lead with ONE direct-answer sentence. Then, if the answer is a list (goals, hazards, requirements, "
        "steps, categories), add a bullet list using '• ' at the start of each line (max 6 bullets), each "
        "citing its source [n]; otherwise add 1–3 tight sentences. No filler or repetition. "
        "STRICT RULE: ground EVERYTHING only in the provided SOURCES and MAP FACTS. Using your own or "
        "outside knowledge is forbidden, even if you know the answer. If the user asks about something "
        "not in the SOURCES or MAP FACTS, say so rather than filling the gap. "
        "Never invent facts, numbers, agencies, or laws that are not "
        "literally in the SOURCES. Never write links, URLs, or web addresses — sources are shown "
        "separately with their link. "
        "When you rely on a dated source or map layer, note its year (e.g., 'per the 2018 FEMA layer'). "
        "Cite sources by number, e.g. [1]. "
        "If the SOURCES do not contain the answer, say exactly that there isn't enough information in the "
        "available documents and point to the Junta de Planificación, OGPe, DRNA, or the municipality — "
        "do not make up an answer. Do not give binding legal advice."
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
        config=types.GenerateContentConfig(system_instruction=system, temperature=0.2, max_output_tokens=900),
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
    shown = spatial.get("active_layers") or []
    if shown:
        head_l = ("Capas visibles ahora en el mapa" if lang == "es"
                  else "Layers the user currently has on the map")
        names = ", ".join(
            f"{l.get('name')}" + (f" ({l.get('year')})" if l.get("year") else "")
            for l in shown if l.get("name"))
        lines.append(f"- {head_l}: {names}")
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
    lang: str | None = None,
) -> dict[str, Any]:
    """Call the local LLM to write a cited answer over the retrieved docs.

    `history` is prior (question, answer) turns so follow-ups keep context.
    `spatial` is the clicked point's map facts, folded in so the answer can reason
    over real conditions (flood/landslide) alongside the documents. `lang` is the
    UI-selected answer language. Raises on transport/parse errors so callers fall back.
    """
    lang = (lang or RESPONSE_LANG)
    lang = lang if lang in SYSTEM_PROMPTS else "en"
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
    answer = _strip_urls(answer)

    # If the model declined (couldn't answer from the sources), don't present the
    # retrieved docs as if they backed an answer — show no citations and low
    # confidence, so "sources" always match what was actually answered.
    declined = _is_decline(answer)
    if declined:
        citations: list[dict[str, Any]] = []
    else:
        citations = [
            {"id": d["id"], "title": d["title"], "year": d.get("year"), "url": d.get("url", "")}
            for d in docs
        ]
    if declined:
        confidence = "baja" if lang == "es" else "low"
    elif lang == "es":
        confidence = "alta" if len(docs) >= 2 else "media"
    else:
        confidence = "high" if len(docs) >= 2 else "medium"
    return {
        "answer_es": answer,
        "citations": citations,
        "suggested_layers": layers,
        "confidence": confidence,
    }
