from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import llm
from .retrieval import compose_answer, infer_layers, retrieve

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


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


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
    docs = retrieve(req.question, top_k=3)
    layers = infer_layers(req.question)
    # Prefer the local LLM for narration; fall back to the templated composer
    # if Ollama is unreachable or errors, so the app always responds.
    if docs and llm.is_available():
        try:
            result = llm.narrate(req.question, docs, layers)
        except Exception:
            result = compose_answer(req.question, docs, layers)
    else:
        result = compose_answer(req.question, docs, layers)
    return AskResponse(disclaimer=DISCLAIMER, **result)


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")
