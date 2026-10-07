"""The tools the assistant calls, without a database.

Each tool is run against stand-in repositories, so these check the rules the
tools enforce - not today's data.
"""

import pytest

from api import tools
from api.repositories.layers import Layer
from api.repositories.places import Place

SCHOOLS = Layer("schools", "layer_schools", "Escuelas", "Schools", "POINT", 853, "published")
FLOOD = Layer(
    "flood", "layer_flood", "Inundación", "Flood zones", "MULTIPOLYGON", 2516, "published"
)
PONCE = Place("72113", "Ponce", "municipio", None)


@pytest.fixture(autouse=True)
def stand_ins(monkeypatch):
    monkeypatch.setattr(tools.layers, "get", {"schools": SCHOOLS, "flood": FLOOD}.get)
    monkeypatch.setattr(tools.layers, "role_of", lambda layer: None)
    monkeypatch.setattr(tools.places, "by_code", {"72113": PONCE}.get)
    monkeypatch.setattr(
        tools.places, "lookup", lambda name, municipio=None: [PONCE] if name == "Ponce" else []
    )
    monkeypatch.setattr(tools.spatial, "count", lambda layer, place=None: 42)
    monkeypatch.setattr(tools.spatial, "count_inside", lambda layer, area, place=None: (3, 7))


def test_every_tool_declares_a_valid_schema():
    for t in tools.TOOLS:
        assert t.parameters["type"] == "object"
        assert set(t.parameters["required"]) <= set(t.parameters["properties"])
        assert t.description and len(t.description) > 30


def test_a_call_is_recorded_as_a_step():
    s = tools.Session()
    out = tools.call(s, "count_features", {"layer_id": "schools", "place_id": "72113"})
    assert out["count"] == 42 and out["place"] == "Ponce"
    assert s.steps[-1]["summary"] == "42 Schools in Ponce"
    assert s.measured and s.place == PONCE


def test_a_bad_call_is_told_to_the_model_not_raised():
    s = tools.Session()
    assert "unknown layer_id" in tools.call(s, "count_features", {"layer_id": "nope"})["error"]
    assert "bad arguments" in tools.call(s, "count_features", {"wrong": 1})["error"]
    assert "no tool" in tools.call(s, "delete_everything", {})["error"]
    assert not s.measured


def test_inside_needs_an_area_layer():
    s = tools.Session()
    out = tools.call(s, "count_inside", {"layer_id": "flood", "area_layer_id": "schools"})
    assert "not an area layer" in out["error"]


def test_inside_returns_its_own_percentage():
    """So the model never works one out - an invented 44% is what the figure check catches."""
    out = tools.call(
        tools.Session(), "count_inside", {"layer_id": "schools", "area_layer_id": "flood"}
    )
    assert out["share_percent"] == 42.9


def test_a_shared_name_asks_which():
    s = tools.Session()
    assert tools.call(s, "find_place", {"name": "Nowhere"})["note"] == "No place by that name."
    assert s.place is None


def test_a_measurement_that_takes_too_long_is_told_to_the_model(monkeypatch):
    import psycopg2

    def slow(layer, place=None):
        raise psycopg2.errors.QueryCanceled("canceling statement due to statement timeout")

    monkeypatch.setattr(tools.spatial, "count", slow)
    s = tools.Session()
    out = tools.call(s, "count_features", {"layer_id": "schools"})
    assert "too long" in out["error"]
    assert not s.measured and s.steps[-1]["summary"] == "took too long"


def test_layers_found_count_as_something_found(monkeypatch):
    monkeypatch.setattr(tools.layers, "search", lambda topic, limit=8: [(SCHOOLS, 0.8)])
    s = tools.Session()
    tools.call(s, "find_layers", {"topic": "schools"})
    assert s.has_evidence
