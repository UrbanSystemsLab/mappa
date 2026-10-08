# Mappa API

Everything the app does goes through this HTTP API. A frontend built in any framework
(React, Angular, plain MapLibre or Mapbox GL) needs only this document and
[openapi.json](openapi.json), the machine-readable contract. A test fails if the code and
that file disagree.

Base path: `/api/v1`. Interactive docs: `/api/v1/docs` on any running server.

| Server | Address |
|---|---|
| Production | https://app.mappealo.org |
| Local | http://127.0.0.1:8765 (see [RUN_LOCAL.md](RUN_LOCAL.md)) |

## Asking a question

### `POST /api/v1/ask/stream` (what the app uses)

Request body:

```json
{
  "question": "¿Cuántas escuelas hay en zona inundable en Carolina?",
  "lang": "es",
  "history": [{"question": "...", "answer": "..."}],
  "location": "Santurce, San Juan",
  "spatial": {"municipio": "Ponce", "hazards": [...]},
  "active_layers": [{"name": "Zonas inundables"}]
}
```

Only `question` is required (3–1000 characters). `lang` is `"es"` or `"en"`.
`location` is a place label from `/places`. `spatial` is what `/locate` returned for a
point the user clicked. `history` holds earlier turns; the last six are used.

The response is server-sent events, in this order:

| Event | Data | Use it to |
|---|---|---|
| `meta` (once) | `municipio`, `focus` (bbox `[w, s, e, n]` or null), `suggested_layers` (layer ids), `disclaimer`, `disclaimers` (`{es, en}`) | move the map, turn on layers |
| `delta` (one or more) | `text` | append to the answer on screen |
| `done` (once) | `answer` (final cleaned text), `citations`, `steps` | replace the streamed text with `answer`, list sources |

Each event arrives as `event: <name>\ndata: <json>\n\n`. Browsers' `EventSource` only
does GET, so read the stream with `fetch` and split on blank lines:

```js
const res = await fetch(`${API}/ask/stream`, {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({question, lang}),
});
const reader = res.body.getReader(), dec = new TextDecoder();
let buf = '';
for (;;) {
  const {value, done} = await reader.read();
  if (done) break;
  buf += dec.decode(value, {stream: true});
  let i;
  while ((i = buf.indexOf('\n\n')) >= 0) {
    const block = buf.slice(0, i); buf = buf.slice(i + 2);
    const event = /^event: (.*)$/m.exec(block)?.[1];
    const data = JSON.parse(/^data: (.*)$/m.exec(block)?.[1] || '{}');
    handle(event, data);
  }
}
```

### `POST /api/v1/ask`

Same request. Returns the whole answer at once, as one JSON object with `answer`,
`citations`, `steps`, `suggested_layers`, `municipio`, `focus` and `disclaimer`. Use it
for scripts, tests and anything that does not show text as it arrives.

**Citations** are the answer's sources: `{kind, id, title, year, source, doc_id}`.
`kind` is `"document"` for a document passage the answer cited, or `"layer"` for a map
layer a figure was measured from (then `source` is the agency that made the data).
`doc_id` is La Maraña's inventory reference (e.g. `POT-012`, `GIS-328`) when there is one.
**Steps** are the lookups behind the answer, `{tool, arguments, summary}`, for showing
how it was worked out.

**Limits:** both ask routes allow 15 questions a minute and 150 an hour per address.
Beyond that the reply is `429` with a `Retry-After` header in seconds.

## Places

| Route | Returns |
|---|---|
| `GET /places?q=santur&limit=8` | matches for a search box: `{name, type, parent, label, bbox}` |
| `GET /locate?lng=-66.6&lat=18.0` | the municipio at a point and which standard layers (flood zones, protected areas...) cover it: `{municipio, hazards: [{name_es, name_en, inside}]}` |

## Map layers

| Route | Returns |
|---|---|
| `GET /catalog/layers?lang=en&q=&category=&available_only=true&limit=&offset=` | `{layers, total}`; each layer has its names, description, source, year, geometry, `tiles_url` and the fields a click should show |
| `GET /catalog/layers/{layer_id}?lang=en` | one layer |
| `GET /catalog/categories?lang=en` | categories with counts |
| `GET /tiles/{name}.json` | TileJSON for a layer |
| `GET /tiles/{name}/{z}/{x}/{y}.mvt` | Mapbox Vector Tile, zoom 4–14; the source layer inside each tile is named `layer` |

`tiles_url` is a path, so prefix it with the API's origin. With MapLibre or Mapbox GL:

```js
map.addSource(layer.id, {type: 'vector', tiles: [API_ORIGIN + layer.tiles_url], minzoom: 4, maxzoom: 14});
map.addLayer({id: layer.id, source: layer.id, 'source-layer': 'layer', type: 'fill', paint: {...}});
```

Fields in a feature that equal `-9999` mean "no value" in La Maraña's data; hide them.

## Hosting a frontend elsewhere

1. Serve your frontend from its own origin.
2. On the API's Cloud Run service set `CORS_ORIGINS=https://your-frontend.example`
   (comma-separated for several) and, if this repo's frontend is no longer wanted,
   `SERVE_FRONTEND=false`.
3. The existing frontend reads the API location from `window.MAPPA_API_ORIGIN`; set it
   before `app.js` loads, e.g. `<script>window.MAPPA_API_ORIGIN = 'https://app.mappealo.org'</script>`.

`GET /api/v1/health` returns `{"status": "ok"}` for uptime checks.
