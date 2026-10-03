"""The two answer routes.

Both call one service, so they cannot drift - they already did once, and the
streamed path shipped a defect for weeks that the plain one never had. What is
left here is only the difference between them: whether the answer arrives in one
piece or as it is written.

The user-facing copy lives here too. It is not configuration and not a schema -
it is what the product says when it has nothing to say, and it belongs next to
the code that decides to say it.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .. import llm
from ..schemas import AskRequest, AskResponse
from ..services import answering

router = APIRouter(tags=["ask"])

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


def _language(req: AskRequest) -> str:
    return "es" if (req.lang or llm.RESPONSE_LANG or "en").lower() == "es" else "en"


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


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """A complete answer. Same service as /ask/stream, so they cannot diverge."""
    lang = _language(req)
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


@router.post("/ask/stream")
def ask_stream(req: AskRequest) -> StreamingResponse:
    """The same answer, sent as it is written.

    The map's half goes first, in a `meta` event, so the map moves while the text
    is still being written. An answer that takes two seconds is fine; two seconds
    of a blank panel reading 'Thinking...' is what people experience as broken.
    """
    lang = _language(req)
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
