from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .retrieval import compose_answer, infer_layers, retrieve

DISCLAIMER_ES = (
    "Esta herramienta ofrece orientación informativa basada en los documentos y datos "
    "disponibles. No constituye asesoría legal ni determinación regulatoria vinculante. "
    "Verifique los requisitos con la Junta de Planificación, OGPe, DRNA o el municipio "
    "correspondiente antes de tomar decisiones."
)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Mappa — Asistente Geoespacial de Puerto Rico (MVP)")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class Citation(BaseModel):
    id: str
    title: str
    year: int
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
    result = compose_answer(req.question, docs, layers)
    return AskResponse(disclaimer=DISCLAIMER_ES, **result)


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")
