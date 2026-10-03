"""The gazetteer as it actually stands in the database.

The unit tests assert the resolution rules against a stand-in. These assert that
the real 1,693 rows are shaped the way those rules assume - that every place has
a municipality to fall back on, that the names people actually ask about are
present, and that the ordinary-word flag was computed rather than left null.
"""

from api import places


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


def test_ordinary_words_were_measured(cur):
    """A null flag means the pipeline never ran the measurement, and every
    ordinary word would resolve as a place."""
    cur.execute("SELECT count(*) FROM reference_units WHERE common_word IS NULL")
    assert cur.fetchone()[0] == 0

    cur.execute(
        "SELECT count(*) FROM reference_units WHERE common_word AND unit_type <> 'municipio'"
    )
    assert cur.fetchone()[0] > 0, "Playa, Centro and Costa are all barrio names"

    cur.execute(
        "SELECT count(*) FROM reference_units WHERE common_word AND unit_type = 'municipio'"
    )
    assert cur.fetchone()[0] == 0, "the 78 municipalities are authoritative names"


def test_the_places_people_ask_about_resolve(cur):
    """Named cases, against the live gazetteer rather than the stand-in."""
    places.reset_cache()
    assert places.resolve("¿cuántas escuelas hay en Santurce?").label == "Santurce, San Juan"
    assert places.resolve("How many schools are in Arecibo?").label == "Arecibo"
    assert places.resolve("deslizamientos en Mariana, Humacao").label == "Mariana, Humacao"


def test_ordinary_words_do_not_become_places(cur):
    """The failure this is all guarding: a question about the coast answered with
    a precise count for a barrio in Isabela."""
    places.reset_cache()
    assert places.resolve("¿cuántos humedales hay cerca de la costa?") is None
    assert places.resolve("how many wells are there?") is None
    # Not in the gazetteer, and must not resolve to barrio Caño in Guánica.
    assert places.resolve("¿qué pasa en Caño Martín Peña?") is None


def test_a_barrio_scopes_a_real_count(cur):
    """A barrio has to work end to end, not just resolve: Santurce's schools are
    some of San Juan's, and both numbers have to be real."""
    from api import spatial

    places.reset_cache()
    barrio = places.resolve("escuelas en Santurce")
    municipio = places.municipio("San Juan")
    inner = spatial.facility_counts("how many schools", barrio)
    outer = spatial.facility_counts("how many schools", municipio)
    assert inner and outer
    assert 0 < next(iter(inner.values())) < next(iter(outer.values()))
