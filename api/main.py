from pathlib import Path

from fastapi import FastAPI, HTTPException
import hashlib
import json
import re

from fastapi.responses import (FileResponse, JSONResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import catalog, llm, spatial, spatial_ops, tiles
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


def municipality_in_scope(req: AskRequest) -> str | None:
    """Which municipality the question is about, including when it does not say.

    A follow-up rarely repeats the name: "and the flood risk there?", "how many
    schools in that municipality?". Reading only the current question left those
    turns with no region at all - the spatial engine could not count anything and
    the map did not move - so the place carries forward from the conversation.

    A place named in the current question still wins, so changing subject works;
    the map's own location is the last resort.
    """
    named = detect_municipio(req.question)
    if named:
        return named
    for turn in reversed(req.history or []):
        earlier = detect_municipio(turn.question)
        if earlier:
            return earlier
    return req.location


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    lang = "es" if (req.lang or llm.RESPONSE_LANG or "en").lower() == "es" else "en"
    disclaimer = DISCLAIMER_ES if lang == "es" else DISCLAIMER_EN
    # For follow-up questions, fold the previous question into the retrieval query
    # so "what about in Ponce?" still finds the right documents.
    retrieval_query = req.question
    if req.history:
        retrieval_query = f"{req.history[-1].question} {req.question}"
    # Location-aware: scope to the clicked municipio, or one named in the question.
    # A place named in the question wins over the one the map happens to be on.
    # It used to be the other way round, so after searching for Mayaguez on the
    # map, asking about Loiza returned Mayaguez documents and the answer said
    # there was nothing on Loiza.
    municipio = municipality_in_scope(req)
    scored = retrieve_with_scores(retrieval_query, top_k=6, jurisdiction=municipio)
    layers = infer_layers(req.question)
    # Catalog IDs the map can actually switch on, resolved through the registry.
    map_layers = spatial_ops.suggested_layer_ids(req.question)

    # Facility questions (schools/hospitals/shelters/roads) are answered from the map
    # data, not the hazard documents. Build a combined context for the model.
    facilities = spatial.facility_counts(req.question, municipio)
    context = dict(req.spatial or {})
    if facilities:
        context["facilities"] = facilities

    # Counts, overlays and distances are computed against their layers rather than
    # read out of retrieved prose. When the question asks for a figure and the
    # layers cannot produce one, that absence is passed through too, so the model
    # is told to say so instead of finding a number in the text.
    analysis = spatial_ops.analyze(req.question, municipio,
                                   [h.question for h in (req.history or [])])
    if analysis:
        context["analysis"] = spatial_ops.describe(analysis, lang)
    elif spatial_ops.wants_number(req.question):
        context["no_figure"] = True
    if req.active_layers:
        context["active_layers"] = req.active_layers
    # Layers on screen count as context too: 'what am I looking at?' is a real
    # question and should not be turned away by the relevance gate.
    has_context = (bool(req.spatial) or bool(facilities) or bool(req.active_layers)
                   or bool(analysis))

    focus = spatial.municipio_bbox(municipio)

    # Relevance gate: decline gibberish/off-topic questions. If we have real map
    # context (a click or facility counts), we always answer.
    if not has_context and (not scored or scored[0][0] < MIN_RELEVANCE):
        return AskResponse(
            answer_es=NO_MATCH[lang],
            citations=[],
            suggested_layers=(map_layers or layers),
            confidence="baja" if lang == "es" else "low",
            disclaimer=disclaimer,
            municipio=municipio,
            focus=focus,
        )

    docs = [doc for _, doc in scored]
    history = [(t.question, t.answer) for t in req.history]
    # Prefer the local LLM for narration; fall back to the templated composer
    # if Ollama is unreachable or errors, so the app always responds.
    if (docs or has_context) and llm.is_available():
        try:
            result = llm.narrate(req.question, docs, layers, history=history, spatial=context or None, lang=lang)
        except Exception:
            result = compose_answer(req.question, docs, layers)
    else:
        result = compose_answer(req.question, docs, layers)
    # The narrator returns the themes it was given; the map needs catalog IDs it
    # can actually switch on, so the resolved ones win where we have them.
    if map_layers:
        result["suggested_layers"] = map_layers
    return AskResponse(disclaimer=disclaimer, municipio=municipio, focus=focus, **result)


@app.post("/ask/stream")
def ask_stream(req: AskRequest) -> StreamingResponse:
    """The same answer as /ask, sent as it is written.

    The map facts arrive first, in a `meta` event, so the map can fly to the place
    and switch on the right layers while the text is still being written. Then
    `delta` events carry the answer, and `done` carries citations and confidence.

    An answer that takes two seconds is fine; two seconds of a blank panel reading
    'Thinking...' is what people experience as the product being broken.
    """
    lang = "es" if (req.lang or llm.RESPONSE_LANG or "en").lower() == "es" else "en"
    disclaimer = DISCLAIMER_ES if lang == "es" else DISCLAIMER_EN

    def event(name: str, payload: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    def generate():
        # The map's answer is cheap to work out - a name match and a bounding box -
        # so it goes out first. Retrieval and the spatial analysis run afterwards.
        # Doing them before the first yield meant nothing reached the screen until
        # the whole pipeline had finished, which put the map three seconds behind
        # for no reason.
        municipio = municipality_in_scope(req)
        layers = infer_layers(req.question)
        map_layers = spatial_ops.suggested_layer_ids(req.question)
        focus = spatial.municipio_bbox(municipio)
        yield event("meta", {"municipio": municipio, "focus": focus,
                             "suggested_layers": (map_layers or layers),
                             "disclaimer": disclaimer})

        retrieval_query = req.question
        if req.history:
            retrieval_query = f"{req.history[-1].question} {req.question}"
        scored = retrieve_with_scores(retrieval_query, top_k=6, jurisdiction=municipio)
        docs = [doc for _, doc in scored]

        facilities = spatial.facility_counts(req.question, municipio)
        context = dict(req.spatial or {})
        if facilities:
            context["facilities"] = facilities
        analysis = spatial_ops.analyze(req.question, municipio,
                                   [h.question for h in (req.history or [])])
        if analysis:
            context["analysis"] = spatial_ops.describe(analysis, lang)
        elif spatial_ops.wants_number(req.question):
            context["no_figure"] = True
        if req.active_layers:
            context["active_layers"] = req.active_layers
        has_context = (bool(req.spatial) or bool(facilities) or bool(req.active_layers)
                       or bool(analysis))

        if not has_context and (not scored or scored[0][0] < MIN_RELEVANCE):
            yield event("delta", {"text": NO_MATCH[lang]})
            yield event("done", {"citations": [], "confidence":
                                 "baja" if lang == "es" else "low"})
            return

        if (docs or has_context) and llm.is_available():
            try:
                messages = llm.build_messages(req.question, docs, layers,
                                              [(t.question, t.answer) for t in req.history],
                                              context or None, lang)
                parts = []
                for piece in llm.stream_answer(messages):
                    parts.append(piece)
                    yield event("delta", {"text": piece})
                result = llm.finish("".join(parts), docs, (map_layers or layers), lang)
            except Exception:
                # Any transport or parse failure falls back to the templated
                # composer, so the panel always resolves to something.
                result = compose_answer(req.question, docs, layers)
                yield event("delta", {"text": result["answer_es"]})
        else:
            result = compose_answer(req.question, docs, layers)
            yield event("delta", {"text": result["answer_es"]})

        yield event("done", {"citations": result.get("citations", []),
                             "confidence": result.get("confidence", "")})

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.get("/layers")
def layers() -> JSONResponse:
    """Catalog of spatial layers available to toggle on the map."""
    return JSONResponse(spatial.list_layers(), headers={"Cache-Control": "public, max-age=3600"})


@app.get("/places")
def places(q: str, limit: int = 8) -> JSONResponse:
    """Search municipios and barrios by name, for the map's location search."""
    return JSONResponse(spatial.search_places(q, min(limit, 20)),
                        headers={"Cache-Control": "public, max-age=600"})


@app.get("/locate")
def locate(lng: float, lat: float) -> dict:
    """What municipio + hazards apply at a clicked point."""
    return spatial.locate(lng, lat)


@app.get("/catalog/layers")
def catalog_layers(lang: str = "es", q: str | None = None, category: str | None = None,
                   available_only: bool = False,
                   limit: int = 100, offset: int = 0) -> JSONResponse:
    """Search/filter the layer catalog. Replaces the hardcoded layer list that used
    to ship inside the frontend bundle."""
    limit = max(1, min(limit, 1000))
    return JSONResponse(
        catalog.list_layers(lang=lang, q=q, category=category,
                            available_only=available_only, limit=limit, offset=offset),
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/catalog/categories")
def catalog_categories(lang: str = "es", available_only: bool = False) -> JSONResponse:
    return JSONResponse(catalog.categories(lang, available_only=available_only),
                        headers={"Cache-Control": "public, max-age=300"})


@app.get("/catalog/layers/{layer_id}")
def catalog_layer(layer_id: str, lang: str = "es") -> JSONResponse:
    """Full metadata for one layer, including provenance and how confident that
    metadata is — this is what the per-layer info popup shows."""
    row = catalog.get_layer(layer_id, lang)
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown layer: {layer_id}")
    return JSONResponse(row, headers={"Cache-Control": "public, max-age=300"})


@app.get("/tiles/{name}/{z}/{x}/{y}.mvt")
def tile(name: str, z: int, x: int, y: int) -> Response:
    """One vector tile. Carries the whole layer (generalized per zoom), unlike
    /layer/{name}, which caps features and ships the entire layer at once."""
    try:
        data = tiles.tile(name, z, x, y)
    except Exception as exc:
        # Returning an empty tile here would render as "no features here", which on
        # a hazard layer is indistinguishable from "no hazard here". A 503 makes the
        # client retry and keeps missing data visible rather than silent.
        raise HTTPException(status_code=503, detail=f"tile temporarily unavailable: {exc}") from exc
    if data is None:
        raise HTTPException(status_code=404, detail=f"unknown layer: {name}")
    return Response(
        content=data,
        media_type="application/vnd.mapbox-vector-tile",
        # Tiles are immutable for a given layer version — safe to cache hard.
        headers={"Cache-Control": "public, max-age=86400, immutable"},
    )


@app.get("/tiles/{name}.json")
def tile_json(name: str) -> JSONResponse:
    """TileJSON descriptor for a layer, so MapLibre can register it as a source."""
    tj = tiles.tilejson(name, "")
    if tj is None:
        raise HTTPException(status_code=404, detail=f"unknown layer: {name}")
    return JSONResponse(tj, headers={"Cache-Control": "public, max-age=3600"})


@app.get("/layer/{name}")
def layer(name: str) -> JSONResponse:
    """One spatial layer as GeoJSON (simplified, capped, cached)."""
    gj = spatial.layer_geojson(name)
    if gj is None:
        raise HTTPException(status_code=404, detail=f"unknown layer: {name}")
    return JSONResponse(gj, headers={"Cache-Control": "public, max-age=86400"})


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
        html = re.sub(rf"/static/{re.escape(asset)}(\?v=[^\"\']*)?",
                      f"/static/{asset}?v={digest}", html)
    return Response(html, media_type="text/html",
                    headers={"Cache-Control": "no-store"})
