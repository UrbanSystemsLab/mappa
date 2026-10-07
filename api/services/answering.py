"""One question, from arrival to finished answer.

    1. the assistant reads the question and calls the tools it needs
    2. as soon as it starts answering, the map is told where to go and what to show
    3. the answer streams as it is written
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
    """("meta" | "delta" | "done", payload) events, in that order."""
    session = Session(lang=ask.lang)
    session.place = places.from_selection(ask.location)
    context = assistant.Context(
        clicked=ask.spatial,
        active_layers=[str(x.get("name")) for x in ask.active_layers if x.get("name")],
        history=[(t.question, t.answer) for t in ask.history],
    )
    sent_meta, written = False, []
    try:
        for piece in assistant.answer(ask.question, session, context):
            if not sent_meta:
                yield "meta", _map(session)
                sent_meta = True
            written.append(piece)
            yield "delta", {"text": piece}
    except assistant.AssistantUnavailable:
        written = [UNAVAILABLE[ask.lang]]
        yield "delta", {"text": written[0]}
    if not sent_meta:
        yield "meta", _map(session)
    yield "done", _finish("".join(written), session)


def answer(ask: Ask) -> dict[str, Any]:
    """The whole answer at once - the streaming events, gathered."""
    out: dict[str, Any] = {}
    for kind, payload in stream(ask):
        if kind != "delta":
            out.update(payload)
    return out


def _map(session: Session) -> dict[str, Any]:
    """Where the map should go and what it should show."""
    place: Place | None = session.place
    return {
        "municipio": place.label if place else None,
        "focus": places.bbox(place),
        "suggested_layers": [layer.id for layer in session.layers_used if layer.on_map][:3],
    }


def _finish(text: str, session: Session) -> dict[str, Any]:
    """The cleaned answer, its sources and the steps behind it.

    A source is a document whose passage the answer cited by number - and only
    that. Documents that were searched but not cited are not listed: an answer
    that says the documents do not cover a question has no sources.
    """
    numbers = assistant.cited_numbers(text)
    passages = [session.passages[n - 1] for n in numbers if 0 < n <= len(session.passages)]
    citations, seen = [], set()
    for p in passages:
        key = (p.title.lower(), p.year)
        if key in seen:
            continue
        seen.add(key)
        citations.append({"id": p.doc_id, "title": p.title, "year": p.year, "doc_id": p.reference})
    return {
        "answer": assistant.clean(text),
        "citations": citations[:MAX_SOURCES],
        "steps": session.steps,
    }
