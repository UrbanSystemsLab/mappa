"""Values that two parts of the system have to agree on are stated once.

This is not a style rule. Each of these had been written out two or three times,
and one pair had already drifted to different numbers without anyone noticing,
because nothing fails when they disagree - the system keeps answering, using the
wrong value.

The embedding model is the worst of them. A second model still returns 384
floats, the database still stores them, and the search still returns its nearest
rows. They are simply the wrong rows, for every question, until somebody notices.
"""

from __future__ import annotations

import ast
import pathlib
import re

import core

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCES = sorted((ROOT / "api").rglob("*.py")) + sorted((ROOT / "pipelines").glob("*.py"))


def _literal_assignments(name_pattern: str, value_pattern: str) -> list[str]:
    """Where a literal matching `value_pattern` is assigned outside core/."""
    found = []
    for path in SOURCES:
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                continue
            value = node.value.value
            if not isinstance(value, str | int | float) or isinstance(value, bool):
                continue
            if not re.search(value_pattern, str(value)):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and re.search(name_pattern, target.id):
                    found.append(f"{path.relative_to(ROOT)}:{target.id}")
    return found


def test_the_embedding_model_is_named_once():
    """Questions, documents and layers must be embedded by the same model."""
    assert _literal_assignments(r".*", r"sentence-transformers/") == []
    assert core.EMBEDDING_MODEL.startswith("sentence-transformers/")


def test_the_vector_width_matches_the_schema():
    assert core.EMBED_DIM == 384, "the pgvector columns are vector(384)"


def test_the_service_reads_the_database_url_in_one_place():
    """Four modules inside api/ each called os.environ.get("DATABASE_URL") at
    import time - four places to change and four chances to miss one.

    The pipelines are deliberately not held to this. They are command-line
    scripts, so reading the variable inside main() lets it be set after import
    and lets each one exit with a clear message when it is missing, which a
    constant captured at import time cannot do.
    """
    offenders = []
    for path in sorted((ROOT / "api").rglob("*.py")):
        text = path.read_text()
        for match in re.finditer(r"""environ(?:\.get)?\(\s*["']DATABASE_URL["']""", text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line}")
    assert offenders == [], f"should use core.settings.database_url: {offenders}"


def test_the_served_and_baked_zoom_ranges_are_the_same():
    """The baking pipeline has to stop where the tile server stops, or it bakes
    tiles nothing asks for and misses the ones it does."""
    from api import tiles
    from pipelines import bake_tiles

    assert tiles.MAX_ZOOM == core.TILE_MAX_ZOOM
    assert bake_tiles.MAX_ZOOM == core.TILE_MAX_ZOOM
    assert bake_tiles.MIN_ZOOM == core.TILE_MIN_ZOOM


def test_the_relevance_gate_has_one_value():
    """It was declared twice, 0.45 in the route and 0.25 in the service, and only
    the 0.25 was ever read - so the route documented a gate that did not exist."""
    from api.repositories import documents

    assert documents.MIN_RELEVANCE == core.MIN_RELEVANCE
    assert _literal_assignments(r"MIN_RELEVANCE", r".*") == []


def test_core_holds_only_what_crosses_a_boundary():
    """Settings live on one object; fixed facts are a short list. core/ is not
    a cupboard for every constant - a threshold used in one place belongs beside
    the code it tunes."""
    from core import constants

    facts = [n for n in vars(constants) if n.isupper()]
    assert len(facts) <= 8, f"core/constants.py is growing into a dumping ground: {facts}"


def test_settings_reject_a_mistyped_environment():
    """APP_ENV=prod used to be silently treated as not-production."""
    import pytest
    from pydantic import ValidationError

    from core import Settings

    with pytest.raises(ValidationError):
        Settings.from_env({"APP_ENV": "prod"})


def test_staging_picks_its_database_on_the_shared_server():
    from core import Settings

    s = Settings.from_env(
        {
            "DATABASE_URL": "postgresql://u:p@/mappa?host=/cloudsql/x",
            "DATABASE_NAME": "mappa_staging",
        }
    )
    assert s.database_url == "postgresql://u:p@/mappa_staging?host=/cloudsql/x"
