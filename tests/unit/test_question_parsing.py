"""The question-parsing rules, each of which got something wrong in production."""

import pytest

from api import spatial_ops as S


class TestDistance:
    """A distance binds to the layer named after it.

    'in flood zones or within 500 metres of a river' is one overlay and one
    distance. Before this, the distance applied to both and the answer reported
    schools 'within 500m of a flood zone', which nobody asked.
    """

    @pytest.mark.parametrize("text,metres", [
        ("within 500 meters of a river", 500),
        ("a menos de 500 metros", 500),
        ("within 2 km of a road", 2000),
        ("dentro de 1.5 km", 1500),
    ])
    def test_reads_the_distance(self, text, metres):
        found = S.detect_distance(text)
        assert found and found[0] == metres

    def test_no_distance_is_not_zero(self):
        assert S.detect_distance("how many schools are in Carolina?") is None


class TestNumericIntent:
    """A question asking for a figure must be recognised, because when one cannot
    be computed the model has to be told to decline rather than fill the gap."""

    @pytest.mark.parametrize("q", [
        "How many schools are in Carolina?",
        "¿Cuántas escuelas hay en Cataño?",
        "What percentage of Cabo Rojo is protected?",
        "¿Qué porcentaje del municipio está inundable?",
    ])
    def test_wants_a_number(self, q):
        assert S.wants_number(q)

    @pytest.mark.parametrize("q", [
        "What does the mitigation plan say about flooding?",
        "¿Qué reglas de zonificación aplican en Santurce?",
    ])
    def test_does_not_want_a_number(self, q):
        assert not S.wants_number(q)


class TestPlaceRemoval:
    """The place is stripped before layers are matched.

    'How many wells are in Arecibo?' matched 'tipo de suelo arecibo' ahead of
    'pozos', because the place name is a third of the sentence and several layers
    carry a municipality in theirs.
    """

    def test_removes_the_place(self):
        out = S._without_place("How many wells are in Arecibo?", "Arecibo")
        assert "arecibo" not in out.lower()
        assert "wells" in out.lower()

    def test_survives_a_missing_place(self):
        q = "How many wells are there?"
        assert S._without_place(q, None) == q

    def test_never_empties_the_question(self):
        assert S._without_place("Arecibo", "Arecibo").strip()
