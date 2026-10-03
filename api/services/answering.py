"""Everything that happens between a question and an answer.

This existed twice: once in the /ask handler and again in /ask/stream, copied
rather than shared. The two drifted - the streaming path sent the map's answer
first while the plain one did not, each had its own copy of the place detection,
and a fix to one did not reach the other. Both routes now call this.

The order matters and is the product's behaviour rather than an implementation
detail:

  1. the place, because everything else is scoped by it
  2. what the map should show, which is cheap and can be sent immediately
  3. the documents, and the figures computed against their layers
  4. the answer, written only from those two

Nothing here knows about HTTP. That is what makes it testable without a server,
and what stops the two routes diverging again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from .. import llm, spatial, spatial_ops
from ..retrieval import compose_answer, detect_municipio, infer_layers, retrieve_with_scores

# Below this, the closest passage is not about the question.
MIN_RELEVANCE = 0.25


@dataclass(slots=True)
class Turn:
    question: str
    answer: str


@dataclass(slots=True)
class Ask:
    """A question, and everything the caller knows that might bear on it."""
    question: str
    lang: str = "en"
    history: list[Turn] = field(default_factory=list)
    location: str | None = None
    spatial: dict[str, Any] | None = None
    active_layers: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class MapAnswer:
    """What the map can show before a single word has been written."""
    municipality: str | None
    focus: list[float] | None
    layers: list[str]


@dataclass(slots=True)
class Evidence:
    """What the answer is allowed to be written from."""
    documents: list[dict[str, Any]]
    context: dict[str, Any]
    relevant: bool


def place_in_scope(ask: Ask) -> str | None:
    """Which municipality the question is about, including when it does not say.

    A follow-up rarely repeats the name - "and the flood risk there?", "how many
    schools in that municipality?". Reading only the current question left those
    turns with no region, so nothing could be counted and the map did not move.
    A place named now still wins, so changing subject works.
    """
    named = detect_municipio(ask.question)
    if named:
        return named
    for turn in reversed(ask.history):
        earlier = detect_municipio(turn.question)
        if earlier:
            return earlier
    return ask.location


def map_answer(ask: Ask, municipality: str | None) -> MapAnswer:
    """The map's half, which is a name match and a bounding box.

    Cheap enough to send before anything else, which is why the map moves in
    about a sixth of a second while the text is still being written.
    """
    layers = spatial_ops.suggested_layer_ids(ask.question) or infer_layers(ask.question)
    return MapAnswer(municipality=municipality,
                     focus=spatial.municipio_bbox(municipality),
                     layers=layers)


def gather(ask: Ask, municipality: str | None) -> Evidence:
    """The documents and the computed figures, and nothing else.

    When the question asks for a number the layers cannot produce, that absence
    is recorded. Without it the model had retrieved prose and no figure, and
    filled the gap - which is how a table headed "10 pies" became "10 schools".
    """
    query = ask.question
    if ask.history:
        query = f"{ask.history[-1].question} {ask.question}"
    scored = retrieve_with_scores(query, top_k=6, jurisdiction=municipality)
    documents = [doc for _, doc in scored]

    context: dict[str, Any] = dict(ask.spatial or {})
    facilities = spatial.facility_counts(ask.question, municipality)
    if facilities:
        context["facilities"] = facilities

    analysis = spatial_ops.analyze(ask.question, municipality,
                                   [t.question for t in ask.history])
    if analysis:
        context["analysis"] = spatial_ops.describe(analysis, ask.lang)
    elif spatial_ops.wants_number(ask.question):
        context["no_figure"] = True

    if ask.active_layers:
        context["active_layers"] = ask.active_layers

    # Layers on screen and a clicked point are context too: "what am I looking
    # at?" is a real question and should not be turned away by the gate below.
    has_context = bool(ask.spatial or facilities or ask.active_layers or analysis)
    relevant = has_context or bool(scored and scored[0][0] >= MIN_RELEVANCE)
    return Evidence(documents=documents, context=context, relevant=relevant)


def write(ask: Ask, evidence: Evidence, layers: list[str]) -> dict[str, Any]:
    """The finished answer, with citations and confidence."""
    if (evidence.documents or evidence.context) and llm.is_available():
        try:
            return llm.narrate(ask.question, evidence.documents, layers,
                               history=[(t.question, t.answer) for t in ask.history],
                               spatial=evidence.context or None, lang=ask.lang)
        except Exception:
            # Any transport or parse failure falls back to the templated
            # composer, so the panel always resolves to something.
            pass
    return compose_answer(ask.question, evidence.documents, layers)


def stream(ask: Ask, evidence: Evidence, layers: list[str]) -> Iterator[str]:
    """The answer as it is written, provider permitting."""
    messages = llm.build_messages(ask.question, evidence.documents, layers,
                                  [(t.question, t.answer) for t in ask.history],
                                  evidence.context or None, ask.lang)
    yield from llm.stream_answer(messages)


def finish(text: str, evidence: Evidence, layers: list[str], lang: str) -> dict[str, Any]:
    """Citations and confidence for a streamed answer, by the same rules as a
    written one - so an answer cannot be grounded differently depending on which
    route served it."""
    return llm.finish(text, evidence.documents, layers, lang)
