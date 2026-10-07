"""The two question routes: the answer as it is written, and the answer at once.

Both call api/services/answering.py, so they cannot differ in what they answer.
The streaming route sends server-sent events - meta, delta..., done - whose
shapes are api/schemas/ask.py's StreamMeta, StreamDelta and StreamDone.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..schemas import AskRequest, AskResponse
from ..services import answering

router = APIRouter(tags=["ask"])

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
DISCLAIMERS = {"es": DISCLAIMER_ES, "en": DISCLAIMER_EN}


def _ask(req: AskRequest) -> answering.Ask:
    return answering.Ask(
        question=req.question,
        lang="es" if (req.lang or "en").lower() == "es" else "en",
        history=[answering.Turn(t.question, t.answer) for t in req.history],
        location=req.location,
        spatial=req.spatial,
        active_layers=req.active_layers or [],
    )


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """The finished answer in one response."""
    a = _ask(req)
    out = answering.answer(a)
    return AskResponse(
        answer=out["answer"],
        citations=out["citations"],
        steps=out["steps"],
        suggested_layers=out["suggested_layers"],
        municipio=out["municipio"],
        focus=out["focus"],
        disclaimer=DISCLAIMERS[a.lang],
    )


@router.post(
    "/ask/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "meta, delta..., done"}},
)
def ask_stream(req: AskRequest) -> StreamingResponse:
    """The answer as it is written, as server-sent events."""
    a = _ask(req)

    def events():
        for kind, payload in answering.stream(a):
            if kind == "meta":
                payload = {**payload, "disclaimer": DISCLAIMERS[a.lang], "disclaimers": DISCLAIMERS}
            yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
