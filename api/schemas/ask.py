"""Request and response for a question.

This is the contract the frontend is written against, so a change here is a
change to something already deployed in browsers. The comments say what each
field is *for*, because several exist only to answer a question the user did not
put into words - what they have on screen, where they clicked, what they asked
a moment ago.
"""

from __future__ import annotations

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
    id: str
    title: str
    year: int | None = None
    # Their inventory ID. No URL: an answer cites a document La Maraña holds,
    # not a page on a government site.
    doc_id: str = ""


class AskResponse(BaseModel):
    answer_es: str
    citations: list[Citation]
    suggested_layers: list[str]
    confidence: str
    disclaimer: str
    # The place the answer is scoped to, and its bounding box so the map can fly
    # there. Named municipio for the frontend's sake; it may be a barrio.
    municipio: str | None = None
    focus: list[float] | None = None
