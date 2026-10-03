import hashlib
import json
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import limits, llm
from .routers import catalog as catalog_router
from .routers import places as places_router
from .routers import tiles as tiles_router
from .services import answering

# Minimum retrieval relevance (cosine similarity) to attempt an answer. Below this,
# nothing in the corpus is genuinely relevant (gibberish / off-topic), so we decline
# instead of fabricating. Calibrated: real questions score ~0.6+, gibberish ~0.3.
MIN_RELEVANCE = 0.45

NO_MATCH = {
    "en": (
        "I couldn't find relevant information in the available documents for that "
        "question. Try rephrasing it, or ask about land use, permits, flood or "
        "landslide risk, or planning in Puerto Rico."
    ),
    "es": (
        "No encontré información relevante en los documentos disponibles para esa "
        "pregunta. Intente reformularla o pregunte sobre uso de terrenos, permisos, "
        "riesgo de inundación o deslizamiento, o planificación en Puerto Rico."
    ),
}

DISCLAIMER_ES = (
    "Esta herramienta ofrece orientación informativa basada en los documentos y datos "
    "disponibles. No constituye asesoría legal ni determinación regulatoria vinculante. "
    "Verifique los requisitos con la Junta de Planificación, OGPe, DRNA o el municipio "
    "correspondiente antes de tomar decisiones."
)
DISCLAIMER_EN = (
    "This tool provides informational guidance based on the available documents and data. "
    "It is not legal advice or a binding regulatory determination. Verify requirements with "
    "the Planning Board (Junta de Planificación), OGPe, DRNA, or the relevant municipality "
    "before making decisions."
)
DISCLAIMER = DISCLAIMER_ES if llm.RESPONSE_LANG == "es" else DISCLAIMER_EN

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Mappa — Asistente Geoespacial de Puerto Rico (MVP)")

# The app is public and has no sign-in, so this is the only thing between a
# loop pointed at /ask and both the bill and the database the map is served from.
app.middleware("http")(limits.middleware)


class Turn(BaseModel):
    question: str
    answer: str


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    # Prior turns in this conversation (for follow-up / "deeper" questions).
    history: list[Turn] = Field(default_factory=list)
    # Optional municipio to scope the answer to (e.g. set by clicking the map).
    location: str | None = None
    # Optional map facts for the clicked point (municipio + hazard flags), so the
    # answer can reason over real spatial conditions, not just documents.
    spatial: dict | None = None
    # Answer language chosen in the UI ("es" or "en").
    lang: str | None = None
    # Layers currently displayed on the map, so the answer can reference what the
    # user is actually looking at rather than guessing.
    active_layers: list[dict] = Field(default_factory=list)


class Citation(BaseModel):
    id: str
    title: str
    year: int | None = None
    # Their inventory ID. No URL: an answer cites a document La Maraña holds,
    # not a page on a government site.
    doc_id: str = ""


class AskResponse(BaseModel):
    answer_es: str
    citations: list[Citation]
    suggested_layers: list[str]
    confidence: str
    disclaimer: str
    # Municipio the answer is scoped to + its bbox, so the map can fly there.
    municipio: str | None = None
    focus: list[float] | None = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _to_ask(req: AskRequest, lang: str) -> answering.Ask:
    """The HTTP request as the service understands it. This is the only place
    that knows about both shapes."""
    return answering.Ask(
        question=req.question,
        lang=lang,
        history=[answering.Turn(t.question, t.answer) for t in req.history],
        location=req.location,
        spatial=req.spatial,
        active_layers=req.active_layers or [],
    )


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """A complete answer. Same service as /ask/stream, so they cannot diverge."""
    lang = "es" if (req.lang or llm.RESPONSE_LANG or "en").lower() == "es" else "en"
    disclaimer = DISCLAIMER_ES if lang == "es" else DISCLAIMER_EN
    ask_in = _to_ask(req, lang)

    place = answering.place_in_scope(ask_in)
    on_map = answering.map_answer(ask_in, place)
    evidence = answering.gather(ask_in, place)

    if not evidence.relevant:
        return AskResponse(
            answer_es=NO_MATCH[lang],
            citations=[],
            suggested_layers=on_map.layers,
            confidence="baja" if lang == "es" else "low",
            disclaimer=disclaimer,
            municipio=on_map.municipality,
            focus=on_map.focus,
        )

    result = answering.write(ask_in, evidence, on_map.layers)
    result["suggested_layers"] = on_map.layers
    return AskResponse(
        disclaimer=disclaimer, municipio=on_map.municipality, focus=on_map.focus, **result
    )


@app.post("/ask/stream")
def ask_stream(req: AskRequest) -> StreamingResponse:
    """The same answer, sent as it is written.

    The map's half goes first, in a `meta` event, so the map moves while the text
    is still being written. An answer that takes two seconds is fine; two seconds
    of a blank panel reading 'Thinking...' is what people experience as broken.
    """
    lang = "es" if (req.lang or llm.RESPONSE_LANG or "en").lower() == "es" else "en"
    disclaimer = DISCLAIMER_ES if lang == "es" else DISCLAIMER_EN
    ask_in = _to_ask(req, lang)

    def event(name: str, payload: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def generate():
        place = answering.place_in_scope(ask_in)
        on_map = answering.map_answer(ask_in, place)
        yield event(
            "meta",
            {
                "municipio": on_map.municipality,
                "focus": on_map.focus,
                "suggested_layers": on_map.layers,
                "disclaimer": disclaimer,
            },
        )

        evidence = answering.gather(ask_in, place)
        if not evidence.relevant:
            yield event("delta", {"text": NO_MATCH[lang]})
            yield event("done", {"citations": [], "confidence": "baja" if lang == "es" else "low"})
            return

        try:
            parts = []
            for piece in answering.stream(ask_in, evidence, on_map.layers):
                parts.append(piece)
                yield event("delta", {"text": piece})
            result = answering.finish("".join(parts), evidence, on_map.layers, lang)
        except Exception:
            result = answering.write(ask_in, evidence, on_map.layers)
            yield event("delta", {"text": result["answer_es"]})

        # The deltas went out raw, so anything the cleaning step removes - a
        # stray URL, the model citing the computed-facts block as though it were
        # a document - stayed on screen. The finished text comes with the done
        # event and replaces what was streamed.
        yield event(
            "done",
            {
                "citations": result.get("citations", []),
                "confidence": result.get("confidence", ""),
                "answer": result.get("answer_es", ""),
            },
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.include_router(catalog_router.router)
app.include_router(places_router.router)
app.include_router(tiles_router.router)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


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
    return Response(html, media_type="text/html", headers={"Cache-Control": "no-store"})
