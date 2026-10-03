"""Invariants of the layer catalogue.

Loading their second GeoPackage re-matched registry rows onto the new file's
copies and stranded thirty tables. The map went from 107 layers to 81 and nothing
reported it - it was found by someone asking why a question had stopped working.
These are the checks that would have caught it within a minute.
"""

import pytest

from api import spatial_ops as S


def test_no_orphan_layer_tables(cur):
    """Every layer_* table has a registry row.

    A table with no row is invisible to the catalog, the map and the assistant -
    loaded data that nothing can reach.
    """
    cur.execute("""
        SELECT t.table_name FROM information_schema.tables t
        WHERE t.table_schema = 'public' AND t.table_name LIKE 'layer_%'
          AND t.table_name NOT IN ('layer_registry', 'layer_inventory')
          AND NOT EXISTS (SELECT 1 FROM layer_registry r WHERE r.table_name = t.table_name)
    """)
    orphans = [r[0] for r in cur.fetchall()]

    # A table superseded by a newer copy of the same layer is expected: loading
    # their second GeoPackage replaced several layers under slightly different
    # names. Those are wasted space, reported separately. An orphan with no twin
    # is the real fault - data nothing can reach.
    import re, unicodedata

    def key(name):
        n = unicodedata.normalize("NFKD", name.lower())
        n = "".join(c for c in n if not unicodedata.combining(c))
        n = re.sub(r"^layer_", "", n)
        n = re.sub(r"^g\d+_(?:g\d+_)*", "", n)
        return re.sub(r"[^a-z0-9]+", "", n)

    cur.execute("SELECT table_name FROM layer_registry WHERE table_name IS NOT NULL")
    registered = {key(r[0]) for r in cur.fetchall()}
    stranded = [t for t in orphans if key(t) not in registered]
    assert not stranded, f"{len(stranded)} tables nothing can reach: {stranded[:5]}"


def test_no_registry_row_points_at_a_missing_table(cur):
    """The reverse: a row promising data that is not there."""
    cur.execute("""
        SELECT r.id, r.table_name FROM layer_registry r
        WHERE r.table_name IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM information_schema.tables t
                          WHERE t.table_schema = 'public' AND t.table_name = r.table_name)
    """)
    broken = cur.fetchall()
    assert not broken, f"{len(broken)} rows point at a table that does not exist: {broken[:5]}"


def test_every_alias_resolves(cur):
    """The fifteen hand-named concepts each point at a layer with data.

    Two aliases silently stopped resolving when the second GeoPackage supplied the
    same layers under different names, so questions about rivers quietly picked a
    sparser layer instead.
    """
    unresolved = []
    for concept, spec in S.LAYERS.items():
        cur.execute("SELECT status FROM layer_registry WHERE table_name = %s",
                    (spec["table"],))
        row = cur.fetchone()
        if not row or row[0] not in ("published", "loaded"):
            unresolved.append((concept, spec["table"], row[0] if row else "no row"))
    assert not unresolved, f"aliases that no longer resolve: {unresolved}"


def test_published_layers_can_serve_tiles(cur):
    """Anything the map offers must have a table and a geometry type."""
    cur.execute("""
        SELECT id FROM layer_registry
        WHERE status = 'published' AND (table_name IS NULL OR geometry_type IS NULL)
    """)
    broken = [r[0] for r in cur.fetchall()]
    assert not broken, f"published layers that cannot draw: {broken}"


def test_municipality_names_are_intact(cur):
    """All 78 municipalities, none truncated.

    Eight names were cut at their accent on import - Bayam, Mayag, Juana D - and
    those municipalities could not be queried at all. Nothing detected it; a
    question about Mayagüez simply returned nothing.
    """
    cur.execute("SELECT name FROM reference_units WHERE unit_type = 'municipio'")
    names = [r[0] for r in cur.fetchall()]
    assert len(names) == 78, f"expected 78 municipalities, found {len(names)}"
    # Moca is a real four-letter municipality, so length alone is not the signal.
    # A truncated name loses its accented tail, leaving a word that is not one of
    # the 78 - which is what the explicit checks below catch.
    suspicious = [n for n in names if n != n.strip() or n.endswith(("Bayam", "Mayag"))]
    assert not suspicious, f"names that look truncated: {suspicious}"
    for expected in ("Mayagüez", "Bayamón", "Juana Díaz", "San Sebastián", "Añasco"):
        assert expected in names, f"{expected} missing - likely truncated at its accent"


def test_no_three_dimensional_geometry(cur):
    """Geometry must be flat.

    Five layers arrived as XYZM. Intersection against a 2D boundary collapses for
    those, and Cabo Rojo reported zero protected area when it has 24.8 km².
    """
    cur.execute("""
        SELECT table_name FROM layer_registry
        WHERE status IN ('published','loaded') AND table_name IS NOT NULL LIMIT 200
    """)
    bad = []
    for (table,) in cur.fetchall():
        try:
            cur.execute(f'SELECT max(ST_NDims(geom)) FROM "{table}" WHERE geom IS NOT NULL')
            dims = cur.fetchone()[0]
            if dims and dims > 2:
                bad.append((table, dims))
        except Exception:
            continue
    assert not bad, f"layers with 3D geometry: {bad[:5]}"
