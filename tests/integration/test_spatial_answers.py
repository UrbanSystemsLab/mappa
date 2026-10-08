"""The measurements against answers verified by hand in the database.

Asked how many schools in Arecibo were in a flood zone or within 500 metres of a
river, the assistant once answered '10' with a citation. No such figure existed.
These lock the real numbers in place, through the same functions the assistant's
tools call.
"""

import pytest

from api.repositories import places, spatial
from api.repositories.layers import roles


def layer(role: str):
    return roles()[role].layer


def place(name: str):
    return places.lookup(name)[0]


class TestKnownCounts:
    @pytest.mark.parametrize(
        "municipality,expected", [("Cataño", 5), ("Carolina", 25), ("Loíza", 7), ("Utuado", 12)]
    )
    def test_schools_per_municipality(self, db, municipality, expected):
        assert spatial.count(layer("schools"), place(municipality)) == expected


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
        got = spatial.count_inside(layer("schools"), layer("flood"), place(municipality))
        assert got == (inside, total)

    def test_island_wide_sanity(self, db):
        """A zero in one municipality must be read against the whole island."""
        assert spatial.count_inside(layer("schools"), layer("flood")) == (140, 853)


class TestDistance:
    def test_schools_near_a_river(self, db):
        """The question that produced the fabricated '10'."""
        got = spatial.count_within(layer("schools"), layer("rivers"), 500, place("Arecibo"))
        assert got == (14, 21)


class TestCoverage:
    def test_protected_share(self, db):
        """Cabo Rojo reported zero until the 3D geometry was flattened."""
        total, covered = spatial.area_share(layer("protected"), place("Cabo Rojo"))
        assert 13.0 < 100 * covered / total < 13.6
        assert 24 < covered < 26


class TestPointCheck:
    def test_a_click_checks_the_layers_the_roles_mark(self, db):
        municipio, checks = spatial.at_point(-66.61, 18.01)
        assert municipio == "Ponce"
        assert {c.key for c in checks} == {r for r, x in roles().items() if x.checked_on_click}
