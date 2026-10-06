"""The API a frontend is built against does not change by accident.

docs/openapi.json is the published contract: every path, parameter and response
shape a React, Angular or Mapbox frontend relies on. If the code changes the API,
this fails until the document is regenerated on purpose - so a breaking change is
a decision someone made, visible in review, not a surprise in production.

To regenerate after an intended change:
    python -c "import json,api.main as m; json.dump(m.app.openapi(), open('docs/openapi.json','w'), indent=2, ensure_ascii=False)"
"""

import json
from pathlib import Path

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def test_the_api_matches_its_published_contract():
    from api.main import app

    published = json.loads(CONTRACT.read_text(encoding="utf-8"))
    current = json.loads(json.dumps(app.openapi()))
    assert current["paths"].keys() == published["paths"].keys(), "endpoints added or removed"
    assert current == published, "the API changed - regenerate docs/openapi.json if intended"


def test_every_endpoint_is_versioned():
    from api.main import app

    paths = app.openapi()["paths"]
    assert paths and all(p.startswith("/api/v1/") for p in paths)


def test_every_endpoint_declares_what_it_returns():
    """A frontend developer can only rely on a shape the contract states."""
    from api.main import app

    undeclared = []
    for path, ops in app.openapi()["paths"].items():
        for method, op in ops.items():
            ok = op.get("responses", {}).get("200", {}).get("content", {})
            schema = next(iter(ok.values()), {}).get("schema", {}) if ok else {}
            if path.endswith(".mvt") or path.endswith("/stream"):
                continue  # binary tiles and an event stream, documented in docs/API.md
            if not schema or schema == {}:
                undeclared.append(f"{method.upper()} {path}")
    assert undeclared == [], f"no declared response: {undeclared}"
