"""The spatial engine against answers verified by hand in the database.

Asked how many schools in Arecibo were in a flood zone or within 500 metres of a
river, the assistant once answered '10' with a citation. No such figure existed -
the plan's tables are headed '1 pie, 4 pies, 7 pies, 10 pies' and a school address
is on 'Carr. 10'. These lock the real numbers in place.
"""

import pytest

from api import spatial_ops as S


class TestKnownCounts:
    @pytest.mark.parametrize(
        "municipality,expected",
        [
            ("Cataño", 5),
            ("Carolina", 25),
            ("Loíza", 7),
            ("Utuado", 12),
        ],
    )
    def test_schools_per_municipality(self, db, municipality, expected):
        got = S.count_features("schools", municipality)
        assert got["count"] == expected


class TestKnownOverlays:
    @pytest.mark.parametrize(
        "municipality,inside,total",
        [
            ("Cataño", 5, 5),  # every school, which is the striking finding
            ("Carolina", 8, 25),
            ("Loíza", 3, 7),
            ("Arecibo", 0, 21),  # a real zero, verified against island-wide totals
        ],
    )
    def test_schools_in_the_flood_zone(self, db, municipality, inside, total):
        got = S.count_intersecting("schools", "flood", municipality)
        assert (got["count"], got["total"]) == (inside, total)

    def test_island_wide_sanity(self, db):
        """A zero in one municipality must be read against the whole island.

        Arecibo genuinely has none; only comparing against 140 of 853 island-wide
        showed that was a real answer rather than a broken query.
        """
        got = S.count_intersecting("schools", "flood")
        assert got["count"] == 140 and got["total"] == 853


class TestDistance:
    def test_schools_near_a_river(self, db):
        """The question that produced the fabricated '10'."""
        got = S.count_within_distance("schools", "rivers", 500, "Arecibo")
        assert (got["count"], got["total"]) == (14, 21)


class TestCoverage:
    def test_protected_share(self, db):
        """Cabo Rojo reported zero until the 3D geometry was flattened."""
        got = S.coverage_share("protected", "Cabo Rojo")
        assert 13.0 < got["share"] * 100 < 13.6
        assert 24 < got["covered_km2"] < 26


class TestRefusal:
    def test_declines_when_nothing_matches(self, db):
        """A question about nothing in the catalogue computes nothing."""
        assert S.analyze("what is the weather today?", None) == []

    def test_recognises_a_figure_was_wanted(self):
        """So the model is told to decline rather than find a number in the prose."""
        assert S.wants_number("How many toll plazas are in San Juan and Caguas?")
