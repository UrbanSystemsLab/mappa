"""What the map shows for each layer is decided from the layer's own data.

Every layer used to be one flat colour, and 72 of the 82 on the map showed
nothing when clicked. pipelines/profile_layers now decides both. These hold the
rules it was built on - above all, that nothing about a private person is ever
shown, because the 78 cadastral maps carry owners' names and mailing addresses.
"""

import re

PERSONAL = re.compile(
    r"^(owner_.*|propietario|mailadd|mail.*|buyer.*|seller.*|saleprice|saledate|taxamt|"
    r"address|address2|direccion.*|direccio_\d|original_a|lat|lon)$",
    re.I,
)


def test_nothing_about_a_private_person_is_shown(cur):
    cur.execute(
        """SELECT table_name, coalesce(tile_properties, '{}'), coalesce(style->>'by', '')
           FROM layer_registry WHERE status IN ('published', 'loaded')"""
    )
    leaks = [
        (t, [c for c in [*props, by] if PERSONAL.match(c)])
        for t, props, by in cur.fetchall()
        if any(PERSONAL.match(c) for c in [*props, by])
    ]
    assert leaks == [], f"personal fields reach the map: {leaks[:5]}"


def test_a_coloured_layer_sends_the_column_it_is_coloured_by(cur):
    """The map can only colour by a value the tile carries."""
    cur.execute(
        """SELECT table_name FROM layer_registry
           WHERE style ? 'by' AND NOT (style->>'by' = ANY(coalesce(tile_properties, '{}')))"""
    )
    assert cur.fetchall() == []


def test_a_legend_stays_readable(cur):
    cur.execute(
        """SELECT table_name, jsonb_array_length(style->'categories') FROM layer_registry
           WHERE style ? 'categories'
             AND jsonb_array_length(style->'categories') NOT BETWEEN 2 AND 20"""
    )
    assert cur.fetchall() == []


def test_most_layers_show_something_when_clicked(cur):
    cur.execute(
        """SELECT count(*), count(*) FILTER (WHERE cardinality(coalesce(tile_properties,'{}')) > 0)
           FROM layer_registry WHERE status IN ('published', 'loaded')"""
    )
    total, clickable = cur.fetchone()
    assert clickable / total > 0.9, f"only {clickable} of {total} layers show anything"
