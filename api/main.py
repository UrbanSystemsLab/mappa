from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import llm, spatial
from .retrieval import compose_answer, detect_municipio, infer_layers, retrieve_with_scores

# Minimum retrieval relevance (cosine similarity) to attempt an answer. Below this,
# nothing in the corpus is genuinely relevant (gibberish / off-topic), so we decline
# instead of fabricating. Calibrated: real questions score ~0.6+, gibberish ~0.3.
MIN_RELEVANCE = 0.45

NO_MATCH = {
    "en": ("I couldn't find relevant information in the available documents for that "
           "question. Try rephrasing it, or ask about land use, permits, flood or "
           "landslide risk, or planning in Puerto Rico."),
    "es": ("No encontré información relevante en los documentos disponibles para esa "
           "pregunta. Intente reformularla o pregunte sobre uso de terrenos, permisos, "
           "riesgo de inundación o deslizamiento, o planificación en Puerto Rico."),
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


class Citation(BaseModel):
    id: str
    title: str
    year: int | None = None
    url: str = ""


class AskResponse(BaseModel):
    answer_es: str
    citations: list[Citation]
    suggested_layers: list[str]
    confidence: str
    disclaimer: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    # For follow-up questions, fold the previous question into the retrieval query
    # so "what about in Ponce?" still finds the right documents.
    retrieval_query = req.question
    if req.history:
        retrieval_query = f"{req.history[-1].question} {req.question}"
    # Location-aware: scope to the clicked municipio, or one named in the question.
    municipio = req.location or detect_municipio(req.question)
    scored = retrieve_with_scores(retrieval_query, top_k=3, jurisdiction=municipio)
    layers = infer_layers(req.question)

    # Facility questions (schools/hospitals/shelters/roads) are answered from the map
    # data, not the hazard documents. Build a combined context for the model.
    facilities = spatial.facility_counts(req.question, municipio)
    context = dict(req.spatial or {})
    if facilities:
        context["facilities"] = facilities
    has_context = bool(req.spatial) or bool(facilities)

    # Relevance gate: decline gibberish/off-topic questions. If we have real map
    # context (a click or facility counts), we always answer.
    if not has_context and (not scored or scored[0][0] < MIN_RELEVANCE):
        lang = "es" if llm.RESPONSE_LANG == "es" else "en"
        return AskResponse(
            answer_es=NO_MATCH[lang],
            citations=[],
            suggested_layers=layers,
            confidence="baja" if lang == "es" else "low",
            disclaimer=DISCLAIMER,
        )

    docs = [doc for _, doc in scored]
    history = [(t.question, t.answer) for t in req.history]
    # Prefer the local LLM for narration; fall back to the templated composer
    # if Ollama is unreachable or errors, so the app always responds.
    if (docs or has_context) and llm.is_available():
        try:
            result = llm.narrate(req.question, docs, layers, history=history, spatial=context or None)
        except Exception:
            result = compose_answer(req.question, docs, layers)
    else:
        result = compose_answer(req.question, docs, layers)
    return AskResponse(disclaimer=DISCLAIMER, **result)


@app.get("/layers")
def layers() -> JSONResponse:
    """Catalog of spatial layers available to toggle on the map."""
    return JSONResponse(spatial.list_layers(), headers={"Cache-Control": "public, max-age=3600"})


@app.get("/locate")
def locate(lng: float, lat: float) -> dict:
    """What municipio + hazards apply at a clicked point."""
    return spatial.locate(lng, lat)


@app.get("/layer/{name}")
def layer(name: str) -> JSONResponse:
    """One spatial layer as GeoJSON (simplified, capped, cached)."""
    gj = spatial.layer_geojson(name)
    if gj is None:
        raise HTTPException(status_code=404, detail=f"unknown layer: {name}")
    return JSONResponse(gj, headers={"Cache-Control": "public, max-age=86400"})


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    # Never cache the HTML, so the browser always picks up the current app.js version.
    return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-store"})
