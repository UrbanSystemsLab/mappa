"""Request and response for a question.

This is the contract the frontend is written against, so a change here is a
change to something already deployed in browsers. The comments say what each
field is *for*, because several exist only to answer a question the user did not
put into words - what they have on screen, where they clicked, what they asked
a moment ago.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Turn(BaseModel):
    """One exchange already on screen."""

    question: str
    answer: str


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    # Prior turns in this conversation. A follow-up rarely repeats the subject -
    # "and the flood risk there?" - so without these it cannot be scoped.
    history: list[Turn] = Field(default_factory=list)
    # A place picked in the search box, as the box displayed it: "Santurce, San
    # Juan". The municipality after the comma is what tells the nine places
    # called Buena Vista apart.
    location: str | None = None
    # What the map says about a clicked point, so the answer can reason over real
    # conditions rather than only over prose.
    spatial: dict | None = None
    # Answer language chosen in the UI ("es" or "en").
    lang: str | None = None
    # Layers currently on the map, so "what am I looking at?" is answerable.
    active_layers: list[dict] = Field(default_factory=list)


class Citation(BaseModel):
    kind: Literal["document", "layer"] = Field(
        "document",
        description="A document passage the answer cited, or a map layer a figure came from.",
    )
    id: str
    title: str
    year: int | None = None
    source: str = Field("", description="For a layer: the agency that made the data.")
    # Their inventory ID (DOC-124, GIS-328). No URL: an answer cites what La
    # Maraña holds, not a page on a government site.
    doc_id: str = ""


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    suggested_layers: list[str]
    disclaimer: str
    # The place the answer is scoped to, and its bounding box so the map can fly
    # there. Named municipio for the frontend's sake; it may be a barrio.
    municipio: str | None = None
    focus: list[float] | None = None
    steps: list[Step] = Field(default_factory=list, description="What the assistant did to answer.")


class Step(BaseModel):
    """One thing the assistant did to reach the answer - a tool it called."""

    tool: str = Field(description="find_place, search_documents, count_features...")
    arguments: dict = Field(default_factory=dict)
    summary: str = Field("", description="What it found, in a few words.")


# Server-sent events from POST /api/v1/ask/stream, in this order:
#
#   event: meta    once, as soon as the place and layers are known
#   event: delta   many times, each a piece of the answer text
#   event: done    once, with the cleaned final text, citations and steps
#
# Each event's `data:` line is one JSON object with the fields below.


class StreamMeta(BaseModel):
    municipio: str | None = Field(None, description="The place the answer is about.")
    focus: list[float] | None = Field(None, description="Its bounding box, to fly the map to.")
    suggested_layers: list[str] = Field(default_factory=list, description="Layer ids to turn on.")
    disclaimer: str
    disclaimers: dict[str, str] = Field(
        default_factory=dict, description="The disclaimer in es and en."
    )


class StreamDelta(BaseModel):
    text: str


class StreamDone(BaseModel):
    answer: str = Field("", description="The final text. Replaces everything streamed so far.")
    citations: list[Citation] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
