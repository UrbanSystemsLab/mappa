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

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from core import APP_ENV

from . import limits
from .routers import ask as ask_router
from .routers import catalog as catalog_router
from .routers import places as places_router
from .routers import tiles as tiles_router

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def warm() -> None:
    """Load the embedding model and the gazetteer before taking traffic.

    Both were loaded lazily, on the first question a new container received. That
    made the first question after every deploy take forty-five seconds to show
    anything, which reads as broken - and it is the question most likely to be
    asked by whoever we just told to go and look.

    Doing it here costs the same seconds, but spends them while Cloud Run is
    still starting the container rather than while someone is waiting.

    A failure is logged and swallowed: a container that cannot warm up can still
    serve the map and the catalogue, and refusing to start would take those down
    too.
    """
    from . import places, retrieval

    for step, load in (
        ("embedding model", retrieval._get_query_model),
        ("gazetteer", places._load),
    ):
        start = time.monotonic()
        try:
            load()
            print(f"[warm] {step} ready in {time.monotonic() - start:.1f}s", flush=True)
        except Exception as exc:  # startup must not fail on this
            print(f"[warm] {step} failed after {time.monotonic() - start:.1f}s: {exc}", flush=True)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    warm()
    yield


app = FastAPI(
    title="Mappa — Asistente Geoespacial de Puerto Rico (MVP)",
    lifespan=lifespan,
)

# The app is public and has no sign-in, so this is the only thing between a
# loop pointed at /ask and both the bill and the database the map is served from.
app.middleware("http")(limits.middleware)

app.include_router(ask_router.router)
app.include_router(catalog_router.router)
app.include_router(places_router.router)
app.include_router(tiles_router.router)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def index() -> Response:
    """Serve the app shell, stamped with the current asset versions.

    The version in ?v= used to be a number edited by hand, so an app.js change
    shipped behind a token that had not moved reached every browser that already
    had the old file - the app looked unchanged no matter what was deployed.
    The stamp is now a hash of the file's own contents, so it moves exactly when
    the file does and never when it does not.
    """
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
    if APP_ENV != "production":
        # A test copy says so on every screen, and stays out of search results.
        banner = (
            # Fixed, so it sits over the page rather than pushing its
            # full-height layout down.
            '<div style="position:fixed;top:0;left:50%;transform:translateX(-50%);z-index:9999;'
            "background:#b45309;color:#fff;font:600 12px/1.7 system-ui,sans-serif;"
            f'padding:2px 12px;border-radius:0 0 7px 7px">{APP_ENV.upper()} · test copy, not '
            "the live site · copia de prueba</div>"
        )
        html = html.replace("<body>", "<body>" + banner, 1)
        headers["X-Robots-Tag"] = "noindex, nofollow"
    return Response(html, media_type="text/html", headers=headers)
