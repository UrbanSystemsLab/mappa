"""main.py assembles the application and does nothing else.

It was 388 lines and the place every change landed: the HTTP layer, the
orchestration between a question and an answer, the SQL behind both, and the
wire contract. Splitting it is only worth something if it stays split, and
nothing but a test makes that true.
"""

from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
MAIN = ROOT / "api" / "main.py"


def test_the_app_file_stays_small():
    lines = len(MAIN.read_text().splitlines())
    assert lines < 150, f"main.py is {lines} lines and drifting back to a god module"


def test_it_does_not_talk_to_the_database():
    """A query here means orchestration has leaked back into the HTTP layer."""
    text = MAIN.read_text()
    for sign in ("SELECT ", "db.connection", "psycopg2", "cur.execute"):
        assert sign not in text, f"main.py should not contain {sign!r}"


def test_it_does_not_define_the_wire_contract():
    """Request and response shapes live in api/schemas, because they change when
    the frontend needs a field, not when the service is wired differently."""
    tree = ast.parse(MAIN.read_text())
    models = [
        n.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef)
        and any(getattr(b, "id", getattr(b, "attr", "")) == "BaseModel" for b in n.bases)
    ]
    assert models == [], f"these belong in api/schemas: {models}"


def test_every_route_is_reachable():
    """A router that is defined but never included serves nothing, and the only
    symptom is a 404 somebody reports later."""
    from api.main import app

    paths = {r.path for r in app.routes if hasattr(r, "path")}
    for required in ("/", "/health", "/ask", "/ask/stream", "/catalog/layers", "/places"):
        assert required in paths, f"{required} is not mounted"
