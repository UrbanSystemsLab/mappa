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

import functools
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# Matches markdown links [text](url), bare http(s):// URLs, and www.* addresses.
_MD_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)")
_BARE_URL = re.compile(r"\(?\b(?:https?://|www\.)\S+\)?")


# Phrases the model uses when the sources don't answer the question (both languages).
_DECLINE_MARKERS = (
    "not enough information",
    "isn't enough information",
    "is not enough information",
    "there is not enough",
    "do not contain",
    "does not contain",
    "couldn't find",
    "could not find",
    "no hay información suficiente",
    "no hay suficiente información",
    "no cuento con",
    "no encontré",
    "no se encontró",
    "no contienen",
    "no contiene",
    "información suficiente en los documentos",
)


# A refusal is a sentence or two. Anything longer has gone on to say something,
# and that something came from the documents.
DECLINE_MAX_CHARS = 320


def _is_decline(text: str) -> bool:
    """True if the answer is only a 'the sources don't cover this' non-answer.

    It used to be any answer containing such a phrase anywhere. An answer that
    hedged once and then quoted the Reglamento Conjunto's definition of a flood
    zone had every source removed - so it showed the Reglamento's words with
    nothing saying where they came from. Found on staging, 6 Oct 2026, when a
    flood question in Ponce asked with three layers on the map.
    """
    t = text.lower().strip()
    return len(t) <= DECLINE_MAX_CHARS and any(m in t for m in _DECLINE_MARKERS)


from .retrieval import citation_id, display_title

# The model cites the map-facts block the way it cites a document. It appears
# alone - "[MAP FACTS]" - and also mixed into a citation list - "[1, MAP FACTS]" -
# which the first version of this missed, so readers saw it in the answer.
_MAP_LABEL = r"(?:MAP FACTS?|DATOS? DEL MAPA|Dato del mapa|Map data|Datos del mapa)"
_MAP_MARKER_ALONE = re.compile(rf"\s*[\[(]\s*{_MAP_LABEL}\s*[\])]", re.I)
_MAP_MARKER_IN_LIST = re.compile(
    rf"(?<=[\[(])([^\[\]()]*?){_MAP_LABEL}([^\[\]()]*?)(?=[\])])", re.I
)


def _strip_map_markers(text: str) -> str:
    """Drop the model's references to the map-facts block itself.

    Inside a citation list the surrounding numbers are kept, so "[1, MAP FACTS]"
    becomes "[1]" rather than losing the real citation with it.
    """
    text = _MAP_MARKER_ALONE.sub("", text)

    def tidy(m: re.Match) -> str:
        rest = m.group(1) + m.group(2)
        rest = re.sub(r"\s*,\s*,\s*", ", ", rest)  # gap left in the middle
        return re.sub(r"^[\s,]+|[\s,]+$", "", rest)  # or at either end

    return _MAP_MARKER_IN_LIST.sub(tidy, text)


def _strip_urls(text: str) -> str:
    """Remove any link/URL the model may have emitted. All source links come from the
    database citations shown in the UI, never from the model's prose — this enforces
    that the LLM contributes no resources of its own."""
    text = _MD_LINK.sub(r"\1", text)  # keep the link text, drop the URL
    text = _BARE_URL.sub("", text)
    text = re.sub(r"(?m)^\s*[\*\-]\s+", "• ", text)  # normalize markdown bullets to •
    return re.sub(r"[ \t]{2,}", " ", text).strip()


# Provider: "gemini" (Vertex AI — GCP-native, no key, auth via the service
# account), "ollama" (a local model), or "openai" (any OpenAI-compatible API).
#
# Gemini is the default wherever Google credentials are present, which means a
# laptop is running what production runs. The default used to be ollama, so local
# answers came from Mistral on the machine - 16 seconds against Gemini's 2, and a
# different model from the one the product actually ships.
def _default_provider() -> str:
    # K_SERVICE is set by Cloud Run, where credentials come from the metadata
    # server and neither file below exists. Without this check the deployed
    # service would fall back to a local model that is not running there.
    if os.environ.get("K_SERVICE") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return "gemini"
    adc = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    return "gemini" if adc.exists() else "ollama"


LLM_PROVIDER = os.environ.get("LLM_PROVIDER", _default_provider()).lower()
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
        "Eres Mappa, un asistente de planificación y riesgos para comunidades de Puerto Rico. "
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
        "Si las FUENTES no contienen la respuesta en absoluto, di exactamente que no hay información "
        "suficiente en los documentos disponibles y remite a la Junta de Planificación, la OGPe, el "
        "DRNA o el municipio — sin inventar una respuesta. Si la responden solo en parte, empieza "
        "por lo que SÍ dicen y luego indica con claridad qué parte no cubren; no empieces diciendo "
        "que falta información. No brindas asesoría legal vinculante."
    ),
    "en": (
        "You are Mappa, a planning and hazard assistant for Puerto Rico communities. Answer in English. "
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
        "If the SOURCES do not contain the answer at all, say exactly that there isn't enough information "
        "in the available documents and point to the Junta de Planificación, OGPe, DRNA, or the "
        "municipality — do not make up an answer. If they answer it only in part, lead with what they DO "
        "say, then state plainly which part they do not cover; do not open by saying information is "
        "missing. Do not give binding legal advice."
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
    from google.genai import types

    client = _gemini_client()
    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    contents = [
        types.Content(
            role=("model" if m["role"] == "assistant" else "user"),
            parts=[types.Part.from_text(text=m["content"])],
        )
        for m in messages
        if m["role"] != "system"
    ]
    resp = client.models.generate_content(
        model=LLM_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system, temperature=0.2, max_output_tokens=900
        ),
    )
    return (resp.text or "").strip()


def _chat_gemini_stream(messages: list[dict[str, str]]):
    """Same call as _chat_gemini, yielding text as the model writes it.

    Two seconds to an answer is fine; two seconds of blank panel is what people
    read as the thing being slow.
    """
    from google.genai import types

    client = _gemini_client()
    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    contents = [
        types.Content(
            role=("model" if m["role"] == "assistant" else "user"),
            parts=[types.Part.from_text(text=m["content"])],
        )
        for m in messages
        if m["role"] != "system"
    ]
    for chunk in client.models.generate_content_stream(
        model=LLM_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system, temperature=0.2, max_output_tokens=900
        ),
    ):
        if chunk.text:
            yield chunk.text


@functools.lru_cache(maxsize=1)
def _gemini_client():
    """One Vertex client for the process. Building it per request repeated the
    credential handshake on every question."""
    from google import genai

    return genai.Client(vertexai=True, project=GCP_PROJECT, location=VERTEX_LOCATION)


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
        {
            "model": LLM_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.2},
        },
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


def _spatial_block(spatial: dict[str, Any], lang: str) -> str:
    """Format the clicked point's map facts as grounded context for the model."""
    yes = "Sí" if lang == "es" else "Yes"
    no = "No"
    lines = []
    muni = spatial.get("municipio")
    if muni:
        lines.append(f"- Municipio: {muni}")
    # These are checked at the single spot the user clicked, not across the
    # municipality. Unlabelled, the model read "flood zone: No" for one spot in
    # Mayagüez as "Mayagüez is not in a flood zone" - when 41% of it is.
    hazards = spatial.get("hazards") or {}
    if hazards:
        lines.append(
            "- En el punto exacto donde el usuario hizo clic (NO en todo el municipio; "
            "no lo generalices al municipio):"
            if lang == "es"
            else "- At the single spot the user clicked (NOT the whole municipality; "
            "never generalise this to the municipality):"
        )
    # Each entry names the layer it checked, from the registry. An older page
    # sends a plain {key: true/false} instead; that is still understood.
    items = (
        [{"name_es": k, "name_en": k, "inside": v} for k, v in hazards.items()]
        if isinstance(hazards, dict)
        else hazards
    )
    for h in items:
        name = h.get("name_es") if lang == "es" else h.get("name_en")
        lines.append(f"  - {name or h.get('key')}: {yes if h.get('inside') else no}")
    for label, count in (spatial.get("facilities") or {}).items():
        lines.append(f"- {label}: {count}")
    for line in spatial.get("analysis") or []:
        lines.append(f"- {line}")
    shown = spatial.get("active_layers") or []
    if shown:
        head_l = (
            "Capas visibles ahora en el mapa"
            if lang == "es"
            else "Layers the user currently has on the map"
        )
        names = ", ".join(
            f"{lay.get('name')}" + (f" ({lay.get('year')})" if lay.get("year") else "")
            for lay in shown
            if lay.get("name")
        )
        lines.append(f"- {head_l}: {names}")
    # A figure was asked for and the layers could not produce one. Saying nothing
    # here is what let a number be lifted out of the retrieved text - a table
    # headed "10 pies" once became "10 schools".
    if spatial.get("no_figure"):
        warn = (
            "NO HAY CIFRA CALCULABLE: las capas cargadas no permiten contar ni medir "
            "lo que pide esta pregunta. No des ningún número. Di que los datos "
            "disponibles no permiten calcularlo y explica qué haría falta."
            if lang == "es"
            else "NO FIGURE CAN BE COMPUTED: the loaded layers cannot count or measure what "
            "this question asks. Do not give any number. Say the available data cannot "
            "answer it and explain what would be needed."
        )
        return warn + "\n\n" + (("\n".join(lines) + "\n\n") if lines else "")
    if not lines:
        return ""
    # Naming which features made up a count is the tempting next sentence, and the
    # model does not have them: told "3 of 7 schools", it named the one school it
    # claimed was outside the flood zone. Four were.
    head = (
        "DATOS DEL MAPA (calculados sobre las capas oficiales; son las únicas cifras "
        "que puedes dar, cítalas con su año). Repórtalas tal cual: no nombres "
        "instalaciones concretas ni deduzcas cuáles son, porque no se te han dado."
        if lang == "es"
        else "MAP FACTS (computed against the official layers; these are the only "
        "figures you may state, cite them with their year). Report them as given: "
        "do not name individual facilities or infer which ones they are - you have "
        "not been told."
    )
    return head + "\n" + "\n".join(lines) + "\n\n"


def build_messages(question, docs, layers=None, history=None, spatial=None, lang=None):
    """Assemble the prompt. Shared so the streaming and non-streaming paths cannot
    drift apart - the grounding rules live here, and an answer written under
    different rules would be a different product."""
    lang = lang or RESPONSE_LANG
    lang = lang if lang in SYSTEM_PROMPTS else "en"
    loc = _spatial_block(spatial, lang) if spatial else ""
    user = (
        f"QUESTION:\n{question.strip()}\n\n"
        f"{loc}"
        f"SOURCES:\n{_sources_block(docs)}\n\n"
        f"{_USER_INSTRUCTION[lang]}"
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPTS[lang]}]
    for prev_q, prev_a in (history or [])[-4:]:
        messages.append({"role": "user", "content": prev_q})
        messages.append({"role": "assistant", "content": prev_a})
    messages.append({"role": "user", "content": user})
    return messages


def stream_answer(messages):
    """Yield the answer as it is written, provider permitting."""
    if LLM_PROVIDER == "gemini":
        yield from _chat_gemini_stream(messages)
    else:
        yield _chat(messages)


# "[1, 2, 3, 4]" after every sentence. The model is asked to cite by number
# because it keeps the answer tied to its documents, but a reader got nothing
# from the numbers: most sentences carried four to six of them, which says
# "several documents" and nothing else. They are removed from what is shown; the
# sources are still listed under the answer.
_CITE_NUMBERS = re.compile(r"\s*\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]")


def strip_citation_numbers(text: str) -> str:
    return _CITE_NUMBERS.sub("", text)


def finish(answer: str, docs, layers, lang: str) -> dict:
    """Post-process a finished answer the same way narrate() does - strip URLs,
    the map-facts marker and the citation numbers, decide citations."""
    answer = strip_citation_numbers(_strip_map_markers(_strip_urls(answer))).strip()
    return _assemble(answer, docs, layers, lang)


def _assemble(answer: str, docs, layers, lang: str) -> dict[str, Any]:
    """Citations for a finished answer. Shared by the streaming
    and non-streaming paths so they cannot disagree about what backed an answer."""

    # If the model declined (couldn't answer from the sources), don't present the
    # retrieved docs as if they backed an answer — show no citations and low
    # confidence, so "sources" always match what was actually answered.
    declined = _is_decline(answer)
    if declined:
        citations: list[dict[str, Any]] = []
    else:
        # One citation per document. Retrieval returns several chunks from the same
        # plan, and listing each as its own source made one document appear six
        # times in the sources panel.
        citations = []
        seen_docs: set[str] = set()
        for d in docs:
            # By the title as shown: their Drive holds some files twice ("Transit
            # Plan Caguas 2024" and "...(2)"), which read as one document.
            key = display_title(d.get("title") or "").lower() + str(d.get("year") or "")
            if key in seen_docs:
                continue
            seen_docs.add(key)
            # No outbound link. A citation used to carry the document's original
            # URL, which for the documents La Maraña catalogued but supplied only
            # a link for meant the answer pointed at a government site. Every
            # answer now cites their document by the ID on their own inventory,
            # which is the thing they can look up and verify.
            citations.append(
                {
                    "id": d["id"],
                    "title": display_title(d["title"]),
                    "year": d.get("year"),
                    "doc_id": citation_id(d["id"]),
                }
            )
    # There is no confidence rating. One used to be derived here - two or more
    # documents meant "alta" - and nobody on La Maraña's side asked for it or
    # agreed what it should mean. The citations are the evidence; the reader can
    # judge from those.
    return {
        "answer_es": answer,
        "citations": citations,
        "suggested_layers": layers,
    }


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
    messages = build_messages(question, docs, layers, history, spatial, lang)
    answer = _chat(messages)
    if not answer:
        raise RuntimeError("empty LLM response")
    answer = strip_citation_numbers(_strip_map_markers(_strip_urls(answer))).strip()
    return _assemble(answer, docs, layers, lang)
