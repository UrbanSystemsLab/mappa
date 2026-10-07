"""The model that answers questions, and the loop that lets it use tools.

The model (Gemini on Vertex AI) is given the question and the tools in
api/tools.py. It calls the tools it needs - find the place, search the
documents, count features - and each call is run and its result handed back,
for a few rounds, until it writes the answer. The answer is streamed as it is
written.

The instructions hold it to what the tools returned: no knowledge of its own, no
figure that a tool did not compute, every claim from a document cited by passage
number.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from core import settings

from .cache import cached
from .tools import TOOLS, Session, call

log = logging.getLogger("mappa.assistant")

# flash, not flash-lite: flash-lite sometimes returns an empty reply after a tool
# result. flash is a few seconds slower and costs about $0.002 a question.
MODEL = settings.llm_model
MAX_ROUNDS = 6  # tool rounds before the model must answer with what it has

INSTRUCTIONS = {
    "en": """You are Mappa, a planning and hazard assistant for Puerto Rico communities, built for La Maraña.

Answer only from what your tools return. Never use your own knowledge, even if you know the answer.
- For every place the question names, call find_place first and use its place_id.
- For rules, permits, plans, laws or what a document says: call search_documents.
- For how many, where, what share, inside or near: call find_layers, then count_features,
  count_inside, count_within_distance or area_share. Every number you state must come from one of
  these tools; never take a figure from a passage as a count.
- Call several tools when the question needs both documents and map data.

Write in English. Start with one sentence that answers directly. Then up to six '• ' bullets or one
to three sentences. Cite document passages by their number, like [2], after the claim they support.
Mention the year of a layer or document you rely on. If the tools found nothing that answers the
question, say plainly what is missing and point to the Junta de Planificación, OGPe, DRNA or the
municipio. If they answer it in part, give that part first, then say what is not covered.
Never show layer_id or place_id values to the reader. No links. This is guidance, not legal advice.""",
    "es": """Eres Mappa, un asistente de planificación y riesgos para comunidades de Puerto Rico, creado para La Maraña.

Responde solo con lo que devuelven tus herramientas. Nunca uses conocimiento propio, aunque sepas la respuesta.
- Por cada lugar que nombre la pregunta, llama primero a find_place y usa su place_id.
- Para reglas, permisos, planes, leyes o lo que dice un documento: llama a search_documents.
- Para cuántos, dónde, qué porcentaje, dentro o cerca: llama a find_layers y luego a count_features,
  count_inside, count_within_distance o area_share. Toda cifra que digas debe venir de una de esas
  herramientas; nunca tomes una cifra de un pasaje como conteo.
- Llama varias herramientas cuando la pregunta necesite documentos y datos del mapa.

Escribe en español. Empieza con una oración que responda directamente. Luego hasta seis viñetas '• '
o de una a tres oraciones. Cita los pasajes por su número, como [2], después de lo que apoyan.
Menciona el año de la capa o documento que uses. Si las herramientas no encontraron nada que
responda, di claramente qué falta y remite a la Junta de Planificación, la OGPe, el DRNA o el
municipio. Si responden en parte, da esa parte primero y luego di qué no cubren.
Nunca muestres valores de layer_id ni place_id al lector. Sin enlaces. Es orientación, no asesoría legal.""",
}


NOTHING_FOUND = {
    "en": "I could not find this in La Maraña's documents or map layers. The Junta de "
    "Planificación, OGPe, DRNA or the municipio may be able to help.",
    "es": "No encontré esto en los documentos ni en las capas de La Maraña. La Junta de "
    "Planificación, la OGPe, el DRNA o el municipio pueden ayudar.",
}


class AssistantUnavailable(Exception):
    """The model could not be reached or failed."""


@dataclass
class Context:
    """What the user did besides asking: a clicked point, layers on the map."""

    clicked: dict[str, Any] | None = None
    active_layers: list[str] = field(default_factory=list)
    history: list[tuple[str, str]] = field(default_factory=list)

    def note(self, lang: str) -> str:
        lines = []
        if self.clicked and self.clicked.get("municipio"):
            checks = self.clicked.get("hazards") or []
            facts = "; ".join(
                f"{c.get('name_es' if lang == 'es' else 'name_en')}: {'yes' if c.get('inside') else 'no'}"
                for c in checks
                if isinstance(c, dict)
            )
            lines.append(
                f"The user clicked a point in {self.clicked['municipio']}. At that exact point only - "
                f"not the whole municipio: {facts or 'no layers checked'}."
            )
        if self.active_layers:
            lines.append("Layers the user has on the map: " + ", ".join(self.active_layers) + ".")
        return "\n".join(lines)


@cached()
def _client():
    from google import genai

    return genai.Client(
        vertexai=True, project=settings.gcp_project, location=settings.vertex_location
    )


def _standard_layers(lang: str) -> str:
    """The layer roles, so the model uses the standard layer for a common
    question - FEMA's 2009 flood zones for "flood zones" - without searching."""
    from .repositories.layers import roles

    lines = [
        f"- {name.replace('_', ' ')}: {r.layer.name(lang)} - layer_id {r.layer.id} "
        f"({r.layer.geometry.lower() or 'unknown'})"
        for name, r in sorted(roles().items())
    ]
    head = (
        "Standard layers for common questions:"
        if lang == "en"
        else "Capas estándar para preguntas comunes:"
    )
    return head + "\n" + "\n".join(lines) if lines else ""


def _config(lang: str):
    from google.genai import types

    return types.GenerateContentConfig(
        system_instruction=INSTRUCTIONS[lang] + "\n\n" + _standard_layers(lang),
        temperature=0.2,
        thinking_config=None
        if settings.llm_thinking_budget is None
        else types.ThinkingConfig(thinking_budget=settings.llm_thinking_budget),
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=t.name, description=t.description, parameters_json_schema=t.parameters
                    )
                    for t in TOOLS
                ]
            )
        ],
    )


def _contents(question: str, context: Context, lang: str) -> list:
    from google.genai import types

    out = []
    for asked, answered in context.history[-6:]:
        out.append(types.Content(role="user", parts=[types.Part.from_text(text=asked)]))
        out.append(types.Content(role="model", parts=[types.Part.from_text(text=answered)]))
    note = context.note(lang)
    text = f"{note}\n\nQuestion: {question}" if note else question
    out.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
    return out


def answer(question: str, session: Session, context: Context) -> Iterator[str]:
    """The answer, once it has been checked against what the tools found.

    The model calls tools for a few rounds, then writes. Before the text is
    released two things are checked, and the model is sent back once if either
    fails:

      evidence  it searched the documents or measured the map. An answer with
                neither is its own knowledge, which it must not use.
      figures   every number it states appears in something a tool returned.
                A number that does not is invented.

    A figure still unsupported after that is removed with its sentence.
    """
    from google.genai import types

    client, config = _client(), _config(session.lang)
    contents = _contents(question, context, session.lang)
    sent_back = retried = False
    for round_ in range(MAX_ROUNDS + 2):
        last = round_ >= MAX_ROUNDS
        if last and not session.has_evidence:
            # Every round was spent and nothing was found. Whatever the model
            # wrote now would come from its own knowledge.
            log.info("no evidence after %d rounds", round_)
            yield NOTHING_FOUND[session.lang]
            return
        calls, text, finish = [], "", None
        started = time.monotonic()
        try:
            # Until something has been found, the model must call a tool rather
            # than answer from what it already knows.
            round_config = (
                _without_tools(config)
                if last
                else config
                if session.has_evidence
                else _must_call(config)
            )
            for chunk in client.models.generate_content_stream(
                model=MODEL, contents=contents, config=round_config
            ):
                finish = _finish_reason(chunk) or finish
                for part in _parts(chunk):
                    if part.function_call:
                        calls.append(part.function_call)
                    elif part.text:
                        text += part.text
        except Exception as exc:
            log.warning("round %d failed after %.1fs: %s", round_, time.monotonic() - started, exc)
            raise AssistantUnavailable(str(exc)) from exc
        log.info(
            "round %d: %.1fs, finish=%s, calls=%s, text=%d chars",
            round_,
            time.monotonic() - started,
            finish,
            [c.name for c in calls],
            len(text),
        )

        if calls:
            contents.append(
                types.Content(role="model", parts=[types.Part(function_call=c) for c in calls])
            )
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=c.name, response=call(session, c.name, dict(c.args or {}))
                        )
                        for c in calls
                    ],
                )
            )
            continue

        if not text.strip():
            # Neither a tool call nor text - it happens, most often right after a
            # tool result. Asking again usually works.
            if retried:
                raise AssistantUnavailable(f"empty response, finish={finish}")
            retried = True
            continue

        problem = None if last else _check(text, session)
        if problem and not sent_back:
            sent_back = True
            log.info("sent back: %s", problem)
            contents.append(types.Content(role="model", parts=[types.Part.from_text(text=text)]))
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=problem)]))
            continue
        yield _drop_unsupported(text, session)
        return
    raise AssistantUnavailable("no answer within the round limit")


_NUMBER = re.compile(r"(?<![\w.-])\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    """Numbers in a text by value: "1,234", "1234" and "1234.0" compare equal."""
    out = set()
    for n in _NUMBER.findall(_CITE.sub("", text)):
        try:
            out.add(f"{float(n.replace(',', '').rstrip('.')):g}")
        except ValueError:
            continue
    return out


def _check(text: str, session: Session) -> str | None:
    """What is wrong with an answer, as an instruction back to the model, or None."""
    if not session.has_evidence:
        return (
            "You answered without calling search_documents or a map tool. Call the tools now, then "
            "write the answer again from scratch from what they return - without apologising or "
            "mentioning this. If they find nothing, say so."
        )
    unsupported = sorted(_numbers(text) - session.known_numbers())
    if unsupported:
        return (
            f"These figures are not in any tool result: {', '.join(unsupported)}. Compute them with "
            "a tool or leave them out, then write the answer again from scratch - without "
            "apologising or mentioning this."
        )
    return None


def _drop_unsupported(text: str, session: Session) -> str:
    """The answer without any sentence stating a number no tool returned."""
    known = session.known_numbers()
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if _numbers(sentence) - known:
            log.warning("dropped an unsupported figure: %s", sentence[:120])
            continue
        kept.append(sentence)
    return " ".join(kept) if len(kept) != len(re.split(r"(?<=[.!?])\s+|\n+", text)) else text


def _must_call(config):
    from google.genai import types

    return config.model_copy(
        update={
            "tool_config": types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            )
        }
    )


def _without_tools(config):
    """The last round: answer with what has been found, no more calls."""
    return config.model_copy(update={"tools": None})


def _finish_reason(chunk):
    for cand in chunk.candidates or []:
        if cand.finish_reason:
            return str(cand.finish_reason)
    return None


def _parts(chunk) -> list:
    out = []
    for cand in chunk.candidates or []:
        out.extend((cand.content.parts if cand.content else None) or [])
    return out


# ---------------------------------------------------------------- the finished text

_LINK = re.compile(r"\[([^\]]+)\]\((?:https?://|www\.)[^)]+\)")
_URL = re.compile(r"\(?\b(?:https?://|www\.)\S+\)?")
_CITE = re.compile(r"\s*\[\s*(\d+(?:\s*[,;\u2013-]\s*\d+)*)\s*\]")


def cited_numbers(text: str) -> list[int]:
    """The passage numbers an answer cites, in order, each once."""
    seen: list[int] = []
    for group in _CITE.findall(text):
        for part in re.split(r"[,;]", group):
            bounds = [int(x) for x in re.findall(r"\d+", part)]
            span = range(bounds[0], bounds[-1] + 1) if len(bounds) == 2 else bounds
            seen.extend(n for n in span if n not in seen)
    return seen


def clean(text: str) -> str:
    """The text a reader sees: no links, no passage numbers, plain bullets."""
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("", text)
    text = _CITE.sub("", text)
    text = re.sub(r"(?m)^\s*[*\-]\s+", "• ", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()
