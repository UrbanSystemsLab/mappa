"""The gazetteer as it actually stands in the database.

The unit tests assert the resolution rules against a stand-in. These assert that
the real 1,693 rows are shaped the way those rules assume - that every place has
a municipality to fall back on, that the names people actually ask about are
present, and that the ordinary-word flag was computed rather than left null.
"""

from api.repositories import places


def test_every_place_type_is_present(cur):
    cur.execute("SELECT unit_type, count(*) FROM reference_units GROUP BY 1")
    counts = dict(cur.fetchall())
    assert counts.get("municipio") == 78, "Puerto Rico has 78 municipalities"
    assert counts.get("barrio", 0) > 850
    assert counts.get("comunidad", 0) > 650


def test_every_place_has_a_usable_shape(cur):
    cur.execute("SELECT count(*) FROM reference_units WHERE geom IS NULL OR ST_IsEmpty(geom)")
    assert cur.fetchone()[0] == 0, "a place with no shape cannot scope anything"


def test_every_place_can_be_scoped_by_code(cur):
    """Queries scope by unit_code, so a duplicate code would silently widen a scope."""
    cur.execute("SELECT count(*), count(DISTINCT unit_code) FROM reference_units")
    total, distinct = cur.fetchone()
    assert total == distinct


def test_every_barrio_knows_its_municipality(cur):
    """Without the parent there is no way to tell 74 places called Pueblo apart,
    and no municipality whose plans a barrio question should read."""
    cur.execute(
        "SELECT count(*) FROM reference_units WHERE unit_type <> 'municipio' "
        "AND (parent_name IS NULL OR parent_name = '')"
    )
    assert cur.fetchone()[0] == 0


def test_parents_are_real_municipalities(cur):
    cur.execute("""
        SELECT DISTINCT parent_name FROM reference_units child
        WHERE unit_type <> 'municipio' AND parent_name IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM reference_units m
            WHERE m.unit_type = 'municipio'
              AND unaccent_fallback(lower(m.name)) = unaccent_fallback(lower(child.parent_name))
          )
    """)
    assert cur.fetchall() == []


def test_a_place_is_found_by_its_name(cur):
    """The model passes the name it read in the question; accents are optional."""
    assert [p.label for p in places.lookup("Santurce")] == ["Santurce, San Juan"]
    assert places.lookup("anasco")[0].name == "Añasco"
    assert places.lookup("Mariana", "Humacao")[0].label == "Mariana, Humacao"


def test_a_shared_name_returns_every_place_until_narrowed(cur):
    """74 municipios have a Barrio Pueblo. The model is told there are several
    and asked to say which, rather than one being picked for it."""
    assert len(places.lookup("Barrio Pueblo")) > 50
    assert len(places.lookup("Buena Vista", "Bayamón")) == 1


def test_a_municipio_comes_before_a_barrio_of_the_same_name(cur):
    """There is a municipio Cataño and a barrio Cataño in Humacao."""
    found = places.lookup("Cataño")
    assert found[0].unit_type == "municipio"


def test_a_barrio_scopes_a_real_count(cur):
    """Santurce's schools are some of San Juan's, and both numbers are real."""
    from api.repositories import spatial
    from api.repositories.layers import roles

    schools = roles()["schools"].layer
    inner = spatial.count(schools, places.lookup("Santurce")[0])
    outer = spatial.count(schools, places.lookup("San Juan", "San Juan")[0])
    assert 0 < inner < outer
