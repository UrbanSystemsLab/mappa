"""One question, from arrival to finished answer.

    1. the assistant reads the question and calls the tools it needs
    2. the answer streams as it is written
    3. the map is told where to go, what to turn on and what to highlight
    4. the finished answer is cleaned, and its sources are the passages it cited

Both routes - the streaming one and the plain one - use this, so they cannot
answer differently. Nothing here knows about HTTP.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .. import assistant
from ..repositories import places
from ..repositories.places import Place
from ..tools import Session

MAX_SOURCES = 5
MAX_LAYER_SOURCES = 4
MAX_LAYERS_SHOWN = 3  # more at once and the map stops being readable

UNAVAILABLE = {
    "en": "The assistant could not answer just now. Please try again in a moment.",
    "es": "El asistente no pudo responder en este momento. Inténtalo de nuevo en un momento.",
}


@dataclass(slots=True)
class Turn:
    question: str
    answer: str


@dataclass(slots=True)
class Ask:
    question: str
    lang: str = "en"
    history: list[Turn] = field(default_factory=list)
    location: str | None = None  # a place picked in the search box
    spatial: dict[str, Any] | None = None  # what /locate said about a clicked point
    active_layers: list[dict[str, Any]] = field(default_factory=list)


def stream(ask: Ask) -> Iterator[tuple[str, dict[str, Any]]]:
    """("delta"..., "meta", "done", ["map"]) events: the text as it is written, what
    the map should do, the finished answer and its sources - and, when layers
    were chosen to illustrate the answer, a later map update."""
    session = Session(lang=ask.lang, question=ask.question)
    session.place = places.from_selection(ask.location)
    session.point = _clicked_point(ask.spatial)
    named = [] if session.place else places.mentioned(ask.question)
    if len(named) == 1:
        session.place = named[0]
    context = assistant.Context(
        places=named,
        clicked=ask.spatial,
        active_layers=[str(x.get("name")) for x in ask.active_layers if x.get("name")],
        history=[(t.question, t.answer) for t in ask.history],
    )
    written = []
    try:
        for piece in assistant.answer(ask.question, session, context):
            if isinstance(piece, assistant.Status):
                yield "status", {"text": str(piece)}
                continue
            written.append(piece)
            yield "delta", {"text": piece}
    except assistant.AssistantUnavailable:
        written = [UNAVAILABLE[ask.lang]]
        yield "delta", {"text": written[0]}
    yield "meta", _map(session)
    yield "done", _finish("".join(written), session)
    # The reader has everything; layers picked beside the answer arrive after.
    if assistant.chosen_layers(session):
        yield "map", _map(session)


def _clicked_point(spatial: dict[str, Any] | None) -> tuple[float, float] | None:
    """The (lng, lat) the user clicked, when the request carries one inside Puerto Rico."""
    try:
        lng, lat = float(spatial["lng"]), float(spatial["lat"])  # type: ignore[index]
    except (TypeError, KeyError, ValueError):
        return None
    return (lng, lat) if -68.5 <= lng <= -64.5 and 17.5 <= lat <= 19.0 else None


def answer(ask: Ask) -> dict[str, Any]:
    """The whole answer at once - the streaming events, gathered."""
    out: dict[str, Any] = {}
    for kind, payload in stream(ask):
        if kind not in ("delta", "status"):
            out.update(payload)  # a later map event replaces the first
    return out


def _map(session: Session) -> dict[str, Any]:
    """What the map should do with this answer.

    Turn on the layers the answer measured - the ones holding what it found
    first - and fly to what it found, or else to the place. Only layers the map
    can draw are named.
    """
    place: Place | None = session.place
    holding = {f["layer_id"] for f in session.found}
    order = [
        *(x for x in session.measured_layers if x.id in holding),
        *session.measured_layers,
        *session.shown_layers,
        *session.layers_used,
    ]
    shown: list[str] = []
    for layer in order:
        if layer.on_map and layer.id not in shown:
            shown.append(layer.id)
    return {
        "municipio": place.label if place else None,
        "focus": _around(session.found) or places.bbox(place),
        "suggested_layers": shown[:MAX_LAYERS_SHOWN],
        "found": session.found,
    }


def _around(found: list[dict[str, Any]]) -> list[float] | None:
    """The box around the features found, with a margin, or None."""
    if not found:
        return None
    lngs, lats = [f["lng"] for f in found], [f["lat"] for f in found]
    pad = 0.004 if len(found) > 1 else 0.008  # about 400 m; more for a single feature
    return [min(lngs) - pad, min(lats) - pad, max(lngs) + pad, max(lats) + pad]


def _finish(text: str, session: Session) -> dict[str, Any]:
    """The cleaned answer, its sources and the steps behind it.

    Sources are the documents whose passages the answer cited by number, then
    the map layers a figure was measured from. Documents searched but not cited
    are not listed: an answer that says the documents do not cover a question
    has no document sources.
    """
    numbers = assistant.cited_numbers(text)
    passages = [session.passages[n - 1] for n in numbers if 0 < n <= len(session.passages)]
    documents, seen = [], set()
    for p in passages:
        key = (p.title.lower(), p.year)
        if key in seen:
            continue
        seen.add(key)
        documents.append(
            {
                "kind": "document",
                "id": p.doc_id,
                "title": p.title,
                "year": p.year,
                "doc_id": p.reference,
            }
        )
    layers = [
        {
            "kind": "layer",
            "id": layer.id,
            "title": layer.name(session.lang),
            "year": layer.year,
            "source": layer.agency or "",
            "doc_id": layer.reference or "",
        }
        for layer in session.measured_layers
    ]
    return {
        "answer": assistant.clean(text),
        "citations": documents[:MAX_SOURCES] + layers[:MAX_LAYER_SOURCES],
        "steps": session.steps,
    }
