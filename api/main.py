"""The application, assembled.

This file used to hold the HTTP layer, the orchestration between a question and
an answer, the SQL behind both, and the wire contract. It was 388 lines and the
place every change landed. It now does one thing: decide what the service is
made of and in what order it starts.

Nothing here answers a question, queries the database, or defines a shape. If
something in this file starts doing any of those, it belongs in a router, a
service, or a schema.
"""

import hashlib
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from core import settings

from . import limits
from .routers import ask as ask_router
from .routers import catalog as catalog_router
from .routers import places as places_router
from .routers import tiles as tiles_router

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def warm() -> None:
    """Load the embedding model, the gazetteer and the layer roles before taking
    traffic, so the first question after a deploy is not the slow one. A failure
    is logged, not raised: the map and the catalogue still work without them."""
    from .embeddings import encoder
    from .repositories.layers import roles
    from .repositories.places import _all as gazetteer

    for step, load in (
        ("embedding model", encoder),
        ("gazetteer", gazetteer),
        ("layer roles", roles),
    ):
        start = time.monotonic()
        try:
            load()
            print(f"[warm] {step} ready in {time.monotonic() - start:.1f}s", flush=True)
        except Exception as exc:
            print(f"[warm] {step} failed after {time.monotonic() - start:.1f}s: {exc}", flush=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    warm()
    yield


app = FastAPI(
    title="Mappa API",
    description="Planning and hazard assistant for Puerto Rico. "
    "Everything a frontend needs is under /api/v1; see docs/API.md.",
    version="1",
    lifespan=lifespan,
    docs_url=f"{settings.api_prefix}/docs",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    redoc_url=None,
)

# The app is public and has no sign-in, so this is the only thing between a
# loop pointed at the question endpoint and both the bill and the database.
app.middleware("http")(limits.middleware)

# A frontend on another origin - a React or Angular app hosted elsewhere -
# needs the browser's permission to call this API.
if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

api = APIRouter(prefix=settings.api_prefix)
api.include_router(ask_router.router)
api.include_router(catalog_router.router)
api.include_router(places_router.router)
api.include_router(tiles_router.router)


@api.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api)
# Also at the root, where the hosting platform and uptime checks look.
app.add_api_route("/health", health, include_in_schema=False)

if settings.serve_frontend and FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index() -> Response:
    """Serve the app shell, stamped with the current asset versions.

    The version in ?v= used to be a number edited by hand, so an app.js change
    shipped behind a token that had not moved reached every browser that already
    had the old file - the app looked unchanged no matter what was deployed.
    The stamp is now a hash of the file's own contents, so it moves exactly when
    the file does and never when it does not.
    """
    if not (settings.serve_frontend and FRONTEND_DIR.exists()):
        return Response(status_code=404)
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    for asset in ("app.js", "app.css"):
        path = FRONTEND_DIR / asset
        if not path.exists():
            continue
        digest = hashlib.sha1(path.read_bytes()).hexdigest()[:10]
        html = re.sub(
            rf"/static/{re.escape(asset)}(\?v=[^\"\']*)?", f"/static/{asset}?v={digest}", html
        )
    headers = {"Cache-Control": "no-store"}
    if settings.app_env != "production":
        # A test copy says so on every screen, and stays out of search results.
        banner = (
            # Fixed, so it sits over the page rather than pushing its
            # full-height layout down.
            '<div style="position:fixed;top:0;left:50%;transform:translateX(-50%);z-index:9999;'
            "background:#b45309;color:#fff;font:600 12px/1.7 system-ui,sans-serif;"
            f'padding:2px 12px;border-radius:0 0 7px 7px">{settings.app_env.upper()} · test copy, not '
            "the live site · copia de prueba</div>"
        )
        html = html.replace("<body>", "<body>" + banner, 1)
        headers["X-Robots-Tag"] = "noindex, nofollow"
    return Response(html, media_type="text/html", headers=headers)
