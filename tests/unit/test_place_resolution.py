"""The rules that decide which place a question is about.

Every case here is one the resolver got wrong at some point while it was being
written, or one that the gazetteer's shape makes dangerous. They run against a
fixed stand-in gazetteer rather than the database, so they assert the rules
rather than today's data.

The expensive mistake this guards is not failing to find a place. It is finding
the wrong one: a question about "la costa" scoped to a two-square-kilometre
barrio in Isabela, answered with a precise number about somewhere nobody asked
about.
"""

from __future__ import annotations

import pytest

from api import places
from api.places import Place

GAZETTEER = [
    Place("mun-1", "San Juan", "municipio", None),
    Place("mun-2", "Ponce", "municipio", None),
    Place("mun-3", "Arecibo", "municipio", None),
    Place("mun-4", "Isabela", "municipio", None),
    Place("mun-5", "Bayamón", "municipio", None),
    Place("mun-6", "Añasco", "municipio", None),
    Place("bar-1", "Santurce", "barrio", "San Juan"),
    Place("bar-2", "Pueblo", "barrio", "San Juan"),
    Place("bar-3", "Pueblo", "barrio", "Ponce"),
    Place("bar-4", "Playa", "barrio", "Isabela", common_word=True),
    Place("bar-5", "Costa", "barrio", "Isabela", common_word=True),
    Place("bar-6", "Caño", "barrio", "Isabela"),
    Place("bar-7", "Buena Vista", "barrio", "Bayamón"),
    Place("bar-8", "Buena Vista", "barrio", "Ponce"),
    Place("com-1", "Villa Palmeras", "comunidad", "San Juan"),
]


@pytest.fixture(autouse=True)
def gazetteer(monkeypatch):
    """A fixed gazetteer, so these assert the rules and not the current data."""
    places.reset_cache()
    by_name: dict[str, list[Place]] = {}
    for p in GAZETTEER:
        by_name.setdefault(places._strip(p.name), []).append(p)
    import re

    names = sorted(by_name, key=len, reverse=True)
    pattern = re.compile(
        places._EDGE + "(?:" + "|".join(re.escape(n) for n in names) + ")" + places._EDGE_END
    )
    monkeypatch.setattr(places, "_load", lambda: (by_name, pattern))
    yield
    places.reset_cache()


def resolved(question: str) -> str | None:
    place = places.resolve(question)
    return place.unit_code if place else None


class TestFindsAPlace:
    def test_municipality(self):
        assert resolved("How many schools are in Arecibo?") == "mun-3"

    def test_accents_are_not_required(self):
        assert resolved("riesgo de inundacion en Bayamon") == "mun-5"
        assert resolved("escuelas en anasco") == "mun-6"

    def test_a_barrio_on_its_own_when_the_name_is_unique(self):
        # The headline of the whole change: Santurce was unreachable, and a
        # question about it was quietly answered for all of San Juan.
        assert resolved("¿cuántas escuelas hay en Santurce?") == "bar-1"

    def test_a_comunidad(self):
        assert resolved("how many wells in Villa Palmeras") == "com-1"

    def test_a_repeated_name_with_its_municipality(self):
        assert resolved("flood risk in Pueblo, Ponce") == "bar-3"
        assert resolved("escuelas en Buena Vista, Bayamón") == "bar-7"

    def test_an_ordinary_word_when_a_place_word_introduces_it(self):
        assert resolved("escuelas en el barrio Playa") == "bar-4"
        assert resolved("sector Costa") == "bar-5"


class TestRefusesToGuess:
    def test_no_place_named(self):
        assert resolved("how many wells are there in total?") is None

    def test_an_ordinary_word_is_not_a_place(self):
        # The dangerous one: this must not be scoped to a barrio in Isabela.
        assert resolved("¿cuántos humedales hay cerca de la costa?") is None
        assert resolved("how many hotels are on the playa?") is None

    def test_a_name_shared_by_several_places(self):
        # "Pueblo" names 74 places island-wide. It names none of them.
        assert resolved("what is the flood risk in Pueblo?") is None
        assert resolved("Buena Vista") is None

    def test_a_fragment_of_a_name_the_gazetteer_does_not_have(self):
        # Caño Martín Peña is not in the gazetteer, and resolving it to barrio
        # Caño in Isabela answers about somewhere forty miles away.
        assert resolved("¿qué pasa en Caño Martín Peña?") is None

    def test_a_name_inside_a_longer_word(self):
        assert resolved("la costanera") is None
        assert resolved("Puebloviejo") is None


class TestHowAPlaceIsNamed:
    def test_a_barrio_carries_its_municipality(self):
        assert places.resolve("escuelas en Santurce").label == "Santurce, San Juan"

    def test_a_municipality_stands_alone(self):
        assert places.resolve("escuelas en Ponce").label == "Ponce"

    def test_documents_are_read_for_the_municipality_a_barrio_sits_in(self):
        # There is no plan filed under "Santurce"; San Juan's plans cover it.
        assert places.resolve("escuelas en Santurce").municipio == "San Juan"
        assert places.resolve("escuelas en Ponce").municipio == "Ponce"
