"""The tools the assistant may call to answer a question.

The model reads the question and decides which tools to call; this module runs
them exactly, against the database, and hands back what they found. Nothing here
interprets the wording of a question - that is the model's job. What this owns is
correctness: every place, passage and figure an answer uses comes from a tool.

Each call is recorded on the Session, which is how the answer gets its sources,
the map knows where to fly and which layers to show, and a reader can see the
steps that produced the answer.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg2

from .repositories import documents, layers, places, spatial
from .repositories.documents import Passage
from .repositories.layers import Layer
from .repositories.places import Place

log = logging.getLogger("mappa.tools")

PASSAGE_CHARS = 1200  # enough of a passage to answer from, without flooding the model


@dataclass
class Session:
    """Everything the tools found while answering one question."""

    lang: str = "en"
    place: Place | None = None
    passages: list[Passage] = field(default_factory=list)
    layers_used: list[Layer] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    results: list[str] = field(default_factory=list)  # every tool result, as text
    measured: bool = False  # a map tool computed something
    found_layers: bool = False  # find_layers returned at least one layer

    @property
    def has_evidence(self) -> bool:
        """Something was found: passages, layers, or a measurement."""
        return bool(self.passages) or self.measured or self.found_layers

    def known_numbers(self) -> set[str]:
        """Every number any tool returned, in the form the answer would write it."""
        from .assistant import _numbers

        return _numbers(" ".join(self.results))

    def use_layer(self, layer: Layer) -> None:
        if all(x.id != layer.id for x in self.layers_used):
            self.layers_used.append(layer)


class ToolError(Exception):
    """A problem with the call itself; told to the model so it can correct it."""


def _place(session: Session, place_id: str | None) -> Place | None:
    if not place_id:
        return None
    place = places.by_code(place_id)
    if place is None:
        raise ToolError(f"unknown place_id {place_id!r}; call find_place first")
    session.place = session.place or place
    return place


def _layer(session: Session, layer_id: str, area: bool = False) -> Layer:
    layer = layers.get(layer_id)
    if layer is None:
        raise ToolError(f"unknown layer_id {layer_id!r}; call find_layers first")
    if area and not layer.is_area:
        raise ToolError(f"{layer.name('en')} is {layer.geometry.lower()}, not an area layer")
    session.use_layer(layer)
    return layer


def _where(place: Place | None) -> str:
    return place.label if place else "Puerto Rico"


# ---------------------------------------------------------------- the tools


def find_place(session: Session, name: str, municipio: str | None = None) -> dict:
    found = places.lookup(name, municipio)
    if len(found) == 1:
        session.place = session.place or found[0]
    return {
        "places": [
            {"place_id": p.unit_code, "name": p.label, "type": p.unit_type} for p in found[:12]
        ],
        "note": "Several places share this name; ask which, or pass municipio."
        if len(found) > 1
        else ("No place by that name." if not found else ""),
    }


def search_documents(session: Session, query: str, place_id: str | None = None) -> dict:
    place = _place(session, place_id)
    found = documents.search(query, place.municipio if place else None)
    out = []
    for p in found:
        session.passages.append(p)
        out.append(
            {
                "n": len(session.passages),
                "title": p.title,
                "year": p.year,
                "text": p.text[:PASSAGE_CHARS],
            }
        )
    return (
        {"passages": out} if out else {"passages": [], "note": "Nothing in the documents on this."}
    )


def find_layers(session: Session, topic: str) -> dict:
    return {
        "layers": [
            {
                "layer_id": layer.id,
                "name": layer.name(session.lang),
                "geometry": layer.geometry.lower(),
                "features": layer.features,
                "standard_for": layers.role_of(layer),
                "relevance": round(score, 2),
            }
            for layer, score in layers.search(topic)
        ]
    }


def count_features(session: Session, layer_id: str, place_id: str | None = None) -> dict:
    layer, place = _layer(session, layer_id), _place(session, place_id)
    return {
        "layer": layer.name(session.lang),
        "place": _where(place),
        "count": spatial.count(layer, place),
    }


def count_inside(
    session: Session, layer_id: str, area_layer_id: str, place_id: str | None = None
) -> dict:
    layer = _layer(session, layer_id)
    area = _layer(session, area_layer_id, area=True)
    place = _place(session, place_id)
    inside, total = spatial.count_inside(layer, area, place)
    return {
        "layer": layer.name(session.lang),
        "area_layer": area.name(session.lang),
        "place": _where(place),
        "inside": inside,
        "total": total,
        "share_percent": round(100 * inside / total, 1) if total else 0.0,
    }


def count_within_distance(
    session: Session, layer_id: str, other_layer_id: str, metres: int, place_id: str | None = None
) -> dict:
    if not 1 <= metres <= 50_000:
        raise ToolError("metres must be between 1 and 50000")
    metres = int(metres)
    layer, other = _layer(session, layer_id), _layer(session, other_layer_id)
    place = _place(session, place_id)
    near, total = spatial.count_within(layer, other, metres, place)
    return {
        "layer": layer.name(session.lang),
        "near_layer": other.name(session.lang),
        "metres": metres,
        "place": _where(place),
        "within": near,
        "total": total,
        "share_percent": round(100 * near / total, 1) if total else 0.0,
    }


def area_share(session: Session, area_layer_id: str, place_id: str) -> dict:
    area = _layer(session, area_layer_id, area=True)
    place = _place(session, place_id)
    if place is None:
        raise ToolError("area_share needs a place_id")
    total, covered = spatial.area_share(area, place)
    return {
        "area_layer": area.name(session.lang),
        "place": place.label,
        "place_km2": round(total, 1),
        "covered_km2": round(covered, 1),
        "share_percent": round(100 * covered / total, 1) if total else 0.0,
    }


# ---------------------------------------------------------------- the catalogue


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., dict]
    summary: Callable[[dict], str]


def _p(**props: tuple[str, str]) -> dict[str, Any]:
    """Parameters as JSON Schema. Each value is (type, description); a type
    ending in '?' is optional."""
    return {
        "type": "object",
        "properties": {k: {"type": t.rstrip("?"), "description": d} for k, (t, d) in props.items()},
        "required": [k for k, (t, _) in props.items() if not t.endswith("?")],
    }


PLACE_ID = (
    "string?",
    "A place_id from find_place, to limit to that place. Omit for all of Puerto Rico.",
)

TOOLS: list[Tool] = [
    Tool(
        "find_place",
        "Look up a place in Puerto Rico by name: a municipio, barrio or comunidad especial. "
        "Call this for every place the question names, before using it elsewhere.",
        _p(
            name=("string", "The place's name, e.g. 'Santurce' or 'Ponce'."),
            municipio=("string?", "The municipio it is in, when the name is shared, e.g. 'Ponce'."),
        ),
        find_place,
        lambda r: ", ".join(p["name"] for p in r["places"][:3]) or "no match",
    ),
    Tool(
        "search_documents",
        "Search La Maraña's planning documents, regulations and laws (Reglamento Conjunto, municipal "
        "territorial plans, hazard mitigation plans, transport plans). Returns numbered passages. "
        "Use for anything about rules, permits, plans, policies or what a document says.",
        _p(
            query=("string", "What to look for, in the words a document would use."),
            place_id=PLACE_ID,
        ),
        search_documents,
        lambda r: f"{len(r['passages'])} passages",
    ),
    Tool(
        "find_layers",
        "Find map data layers about a topic - schools, wells, flood zones, roads, protected areas, "
        "land use. Returns candidate layer_ids, closest first; choose the one that fits. The "
        "standard layers listed in your instructions can be used without calling this.",
        _p(topic=("string", "The kind of thing, e.g. 'public schools' or 'flood zones'.")),
        find_layers,
        lambda r: ", ".join(x["name"] for x in r["layers"][:3]) or "none",
    ),
    Tool(
        "count_features",
        "Count the features of a layer (schools, wells, shelters...) in Puerto Rico or in a place.",
        _p(layer_id=("string", "From find_layers."), place_id=PLACE_ID),
        count_features,
        lambda r: f"{r['count']} {r['layer']} in {r['place']}",
    ),
    Tool(
        "count_inside",
        "How many features of one layer fall inside the areas of another - e.g. schools inside flood "
        "zones, wells inside protected areas.",
        _p(
            layer_id=("string", "The things to count, from find_layers."),
            area_layer_id=("string", "The areas, from find_layers; must be an area layer."),
            place_id=PLACE_ID,
        ),
        count_inside,
        lambda r: f"{r['inside']} of {r['total']} {r['layer']} inside {r['area_layer']}",
    ),
    Tool(
        "count_within_distance",
        "How many features of one layer lie within a distance of another - e.g. schools within 500 m "
        "of a river.",
        _p(
            layer_id=("string", "The things to count, from find_layers."),
            other_layer_id=("string", "What to measure the distance to, from find_layers."),
            metres=("integer", "The distance in metres."),
            place_id=PLACE_ID,
        ),
        count_within_distance,
        lambda r: f"{r['within']} of {r['total']} within {r['metres']} m of {r['near_layer']}",
    ),
    Tool(
        "area_share",
        "How much of a place an area layer covers - e.g. what share of Cabo Rojo is protected, or in "
        "a flood zone. Returns km² and a percentage.",
        _p(
            area_layer_id=("string", "An area layer from find_layers."),
            place_id=("string", "A place_id from find_place."),
        ),
        area_share,
        lambda r: f"{r['share_percent']}% of {r['place']} ({r['covered_km2']} km²)",
    ),
]

BY_NAME = {t.name: t for t in TOOLS}
MEASURING = {"count_features", "count_inside", "count_within_distance", "area_share"}


def call(session: Session, name: str, args: dict[str, Any]) -> dict:
    """Run one tool call and record it. Errors are returned, not raised, so the
    model can see what was wrong and try again."""
    tool = BY_NAME.get(name)
    if tool is None:
        return {"error": f"no tool called {name!r}"}
    try:
        result = tool.run(session, **args)
        summary = tool.summary(result)
    except ToolError as exc:
        result, summary = {"error": str(exc)}, f"error: {exc}"
    except TypeError as exc:  # wrong or missing arguments
        result, summary = {"error": f"bad arguments: {exc}"}, "bad arguments"
    except psycopg2.errors.QueryCanceled:
        log.warning("%s timed out: %s", name, args)
        result = {"error": "This took too long to compute. Say it could not be measured."}
        summary = "took too long"
    session.steps.append({"tool": name, "arguments": args, "summary": summary})
    session.results.append(json.dumps(result, ensure_ascii=False))
    if name in MEASURING and "error" not in result:
        session.measured = True
    if name == "find_layers" and result.get("layers"):
        session.found_layers = True
    return result
