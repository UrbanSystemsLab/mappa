"""The map leads with La Maraña's prioritised layers.

They sent a Data Quality Prioritization Matrix on 28 July 2026, and for ten
weeks the map was chosen by us instead. These keep their list applied: every
layer on it is featured and drawable, and nothing is featured that is not on it.
"""

import csv
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "data" / "lamarana_priority_layers.csv"


def _their_tables() -> set[str]:
    with SOURCE.open(encoding="utf-8") as f:
        return {t for row in csv.DictReader(f) for t in row["tables"].split(";")}


def test_their_matrix_has_sixteen_rows():
    with SOURCE.open(encoding="utf-8") as f:
        assert len(list(csv.DictReader(f))) == 16


def test_every_layer_on_their_list_is_featured_and_on_the_map(cur):
    cur.execute("SELECT table_name FROM layer_registry WHERE featured AND status = 'published'")
    live = {r[0] for r in cur.fetchall()}
    missing = _their_tables() - live
    assert missing == set(), f"on their list but not featured on the map: {missing}"


def test_nothing_is_featured_that_they_did_not_choose(cur):
    cur.execute("SELECT table_name FROM layer_registry WHERE featured")
    extra = {r[0] for r in cur.fetchall()} - _their_tables()
    assert extra == set(), f"featured without being on their list: {extra}"


def test_their_notes_travel_with_the_layer(cur):
    """They marked two layers 'Needs verification'. That has to reach the panel."""
    cur.execute("SELECT count(*) FROM layer_registry WHERE featured_note = 'Needs verification'")
    assert cur.fetchone()[0] == 2
