let map = null;
try {
  map = new maplibregl.Map({
  container: 'map',
  // Free, no-key basemap (Carto Voyager) — real streets + municipio labels.
  style: {
    version: 8,
    sources: {
      basemap: {
        type: 'raster',
        tiles: [
          'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
          'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
          'https://c.tile.openstreetmap.org/{z}/{x}/{y}.png',
        ],
        tileSize: 256,
        maxzoom: 19,
        attribution: '© OpenStreetMap contributors',
      },
    },
    layers: [{
      id: 'basemap', type: 'raster', source: 'basemap',
      paint: {
        'raster-saturation': -0.35,   // step the ground back without killing it
        'raster-contrast': -0.05,
        'raster-brightness-min': 0.04,
        'raster-brightness-max': 1,
        'raster-opacity': 0.94,
      },
    }],
  },
    center: [-66.25, 18.22],
    zoom: 8.4,
  });
  map.addControl(new maplibregl.NavigationControl());
} catch (err) {
  // No WebGL (old browser, blocklisted GPU, headless). Degrade to chat + catalog
  // rather than taking the whole page down.
  const el = document.getElementById('map');
  if (el) el.innerHTML = '<div style="padding:20px;color:#6b7770;font-size:13px">' +
    'El mapa no está disponible en este navegador. / Map unavailable in this browser.</div>';
}

const q = document.getElementById('q');
const out = document.getElementById('out');
const disc = document.getElementById('disc');
const btn = document.getElementById('go');
const clearBtn = document.getElementById('clear');

// The conversation persists here until the page is refreshed.
let conversation = [];
// When set (by clicking a town on the map), questions are scoped to this municipio,
// and the clicked point's map facts (flood/landslide) are sent as context.
let activeLocation = null;
let activeSpatial = null;
const locEl = document.getElementById('loc');

// --- Language (in-app toggle; not browser translate) ---
let LANG = 'es';
const I18N = {
  es: { tagline: 'Asistente de planificación y riesgos de Puerto Rico',
        ph: 'Escribe tu pregunta… o haz clic en el mapa', clear: 'Nueva conversación',
        sources: 'Fuentes', layersTitle: 'Capas del mapa', emptyT: 'Pregúntale a Mappealo',
        emptyB: 'Uso de terrenos, riesgo de inundación o deslizamiento, permisos y planificación en Puerto Rico. También puedes hacer clic en el mapa para preguntar sobre un lugar.' },
  en: { tagline: 'Planning & hazard assistant for Puerto Rico',
        ph: 'Type your question… or click the map', clear: 'New conversation',
        sources: 'Sources', layersTitle: 'Map layers', emptyT: 'Ask Mappealo',
        emptyB: 'Land use, flood or landslide risk, permits, and planning in Puerto Rico. You can also click the map to ask about a place.' },
};
const t = k => I18N[LANG][k];
const CATS = {
  Riesgos: { es: 'Riesgos', en: 'Hazards' }, Servicios: { es: 'Servicios', en: 'Services' },
  'Planificación': { es: 'Planificación', en: 'Planning' }, Infraestructura: { es: 'Infraestructura', en: 'Infrastructure' },
  'Límites': { es: 'Límites', en: 'Boundaries' }, Otros: { es: 'Otros', en: 'Other' },
};
const catLabel = c => (CATS[c] ? CATS[c][LANG] : c);
function applyLang() {
  const tag = document.querySelector('.topbar .tag');
  if (tag) tag.textContent = t('tagline');
  q.placeholder = t('ph');
  if (clearBtn) clearBtn.textContent = t('clear');
  const es = document.getElementById('lang-es'), en = document.getElementById('lang-en');
  if (es) es.classList.toggle('on', LANG === 'es');
  if (en) en.classList.toggle('on', LANG === 'en');
  // Relabel the map-layer panel. Rebuilt from state, so active layers are preserved.
  const h = document.querySelector('#layerctl .h');
  if (h) h.textContent = t('layersTitle');
  // Layer names are resolved server-side per language, so re-fetch rather than
  // relabel in place. Active layers are keyed by id and survive the reload.
  loadCatalog();
  render();
}

function renderLoc() {
  if (!locEl) return;
  if (activeLocation) {
    locEl.style.display = 'inline-block';
    locEl.innerHTML = `📍 ${esc(activeLocation)} <span class="x" title="Quitar filtro">✕</span>`;
    locEl.querySelector('.x').onclick = () => { activeLocation = null; activeSpatial = null; renderLoc(); };
  } else {
    locEl.style.display = 'none';
    locEl.innerHTML = '';
  }
}

document.querySelectorAll('.samples a').forEach(a => {
  a.onclick = () => { q.value = a.dataset.q; ask(); };
});
btn.onclick = ask;
q.addEventListener('keydown', e => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) ask();
});
if (clearBtn) clearBtn.onclick = () => { conversation = []; disc.textContent = ''; render(); };
{
  const es = document.getElementById('lang-es'), en = document.getElementById('lang-en');
  if (es) es.onclick = () => { LANG = 'es'; applyLang(); };
  if (en) en.onclick = () => { LANG = 'en'; applyLang(); };
}

function confClass(c) {
  c = (c || '').toLowerCase();
  if (c === 'alta' || c === 'high') return 'ok';
  if (c === 'media' || c === 'medium') return 'warn';
  return 'low';
}

function render() {
  if (!conversation.length) {
    const hint = LANG === 'es'
      ? '<b>Cada respuesta cita su fuente.</b> Si los documentos cargados no lo dicen, Mappealo lo dirá en vez de inventarlo.'
      : '<b>Every answer cites its source.</b> If the loaded documents do not say it, Mappealo will say so rather than fill the gap.';
    out.innerHTML = `<div class="empty">
      <div class="icon">🗺️</div>
      <h3 translate="no">${t('emptyT')}</h3>
      <p>${t('emptyB')}</p>
      <div class="hint">${hint}</div>
    </div>`;
    return;
  }
  out.innerHTML = conversation.map(m => {
    const layers = (m.suggested_layers || []).map(l => `<span class="tag">${esc(l)}</span>`).join('');
    const cites = (m.citations || []).map(c =>
      `<div class="cite">📄 <a href="${c.url}" target="_blank">${esc(c.title)}</a>${c.year ? ` · ${c.year}` : ''}</div>`
    ).join('');
    const thinking = m.answer === '…';
    const conf = (m.confidence && !thinking) ? `<span class="badge ${confClass(m.confidence)}">${esc(m.confidence)}</span>` : '';
    return `
      <div class="row user"><div class="bubble">${esc(m.question)}</div></div>
      <div class="row bot"><div class="bubble">
        <div class="who">Mappealo ${conf}</div>
        <div class="answer${thinking ? ' typing' : ''}">${thinking ? (LANG === 'es' ? 'Consultando…' : 'Thinking…') : esc(m.answer)}</div>
        ${cites ? `<div class="cites"><div class="cites-h">${t('sources')}</div>${cites}</div>` : ''}
        ${layers ? `<div class="layers">${layers}</div>` : ''}
      </div></div>`;
  }).join('');
  out.scrollTop = out.scrollHeight;
}

async function ask() {
  const question = q.value.trim();
  if (!question) return;
  btn.disabled = true;
  const turn = { question, answer: '…', citations: [], suggested_layers: [], confidence: '' };
  conversation.push(turn);
  render();
  q.value = '';
  try {
    const r = await fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        history: conversation.slice(0, -1).map(t => ({ question: t.question, answer: t.answer })),
        location: activeLocation,
        spatial: activeSpatial,
        lang: LANG,
        // What the user is actually looking at, so the answer can speak to the
        // layers on screen instead of guessing what they mean.
        active_layers: [...ACTIVE.values()].map(l => ({
          id: l.id, name: l.name, theme: l.theme,
          year: l.source && l.source.year, agency: l.source && l.source.agency,
        })),
      }),
    });
    const d = await r.json();
    turn.answer = d.answer_es;
    turn.citations = d.citations || [];
    turn.suggested_layers = d.suggested_layers || [];
    turn.confidence = d.confidence || '';
    disc.textContent = d.disclaimer || '';
    render();
    autoShowLayers(turn.suggested_layers);  // surface relevant layers on the map
    if (d.focus) focusBBox(d.focus);        // fly the map to the place being discussed
  } catch (e) {
    turn.answer = 'Error: ' + e.message;
    render();
  } finally {
    btn.disabled = false;
    q.focus();
  }
}

function esc(s) { return (s || '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])); }

// ---------------------------------------------------------------------------
// Map layers: toggle the PostGIS layers on/off, styled by theme + geometry.
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// Layers: catalog-driven (server search/facets) + vector tiles.
// Nothing about a layer is hardcoded here any more - names, colours, categories
// and provenance all come from /catalog, which is what makes 600 layers workable
// and lets La Marana add layers without a frontend deploy.
// ---------------------------------------------------------------------------
const ACTIVE = new Map();        // layerId -> catalog row (+ opacity)
const EXPANDED = new Set();      // categories the user has opened
let CATEGORIES = [];             // [{category, count}]
let RESULTS = [];                // current catalog page
let RESULT_TOTAL = 0;
let layerQuery = '';
let searchTimer = null;

const SRC = id => 'src_' + id;
const LYR = id => 'lyr_' + id;
const paintKey = type => (type === 'fill' ? 'fill-opacity'
                        : type === 'line' ? 'line-opacity' : 'circle-opacity');

async function loadCatalog() {
  try {
    CATEGORIES = await (await fetch(`/catalog/categories?lang=${LANG}`)).json();
    await fetchLayers();
  } catch (e) {
    document.getElementById('layerlist').textContent =
      LANG === 'es' ? 'No se pudieron cargar las capas.' : 'Could not load layers.';
  }
}

async function fetchLayers() {
  const p = new URLSearchParams({ lang: LANG, limit: '200' });
  if (layerQuery) p.set('q', layerQuery);
  const d = await (await fetch('/catalog/layers?' + p)).json();
  RESULTS = d.layers || [];
  RESULT_TOTAL = d.total || 0;
  // Collapsed groups are the right default for a large catalog, but pointless when
  // there are only a few layers - open everything while the catalog is small, and
  // while searching, so matches are visible without extra clicks.
  if (layerQuery || RESULT_TOTAL <= 25) RESULTS.forEach(l => EXPANDED.add(l.category));
  renderLayerPanel();
}

function statusChip(st) {
  const L = {
    confirmed:     { es: 'confirmado', en: 'confirmed', c: 'ok' },
    inferred:      { es: 'inferido', en: 'inferred', c: 'mid' },
    reconstructed: { es: 'reconstruido', en: 'reconstructed', c: 'mid' },
    unknown:       { es: 'sin documentar', en: 'undocumented', c: 'low' },
  }[st] || { es: st, en: st, c: 'low' };
  return `<span class="mstat ${L.c}">${esc(L[LANG] || st)}</span>`;
}

function layerRow(l, isActive) {
  const yr = l.source && l.source.year ? ` · ${l.source.year}` : '';
  const sw = `<span class="sw" style="background:${(l.style && l.style.color) || '#0b5d4b'}"></span>`;
  const info = `<button class="ic info" data-act="info" data-id="${l.id}" title="${
    LANG === 'es' ? 'Sobre esta capa' : 'About this layer'}">i</button>`;
  if (isActive) {
    return `<div class="lrow on" data-id="${l.id}">
      ${sw}<span class="nm">${esc(l.name)}</span>
      <button class="ic up" data-act="raise" data-id="${l.id}" title="${
        LANG === 'es' ? 'Traer al frente' : 'Bring to front'}">&#8593;</button>
      ${info}
      <button class="ic rm" data-act="remove" data-id="${l.id}" title="${
        LANG === 'es' ? 'Quitar' : 'Remove'}">&times;</button></div>`;
  }
  return `<div class="lrow" data-act="add" data-id="${l.id}">
    ${sw}<span class="nm">${esc(l.name)}<span class="yr">${yr}</span></span>
    ${info}<button class="ic add" data-act="add" data-id="${l.id}">+</button></div>`;
}

function renderLayerPanel() {
  const el = document.getElementById('layerlist');
  const active = [...ACTIVE.values()];
  const activeIds = new Set(ACTIVE.keys());
  let html = '';

  // Active layers pinned to the top - as more layers load, the ones in use stay
  // reachable without scrolling (La Marana's feedback).
  if (active.length) {
    html += `<div class="lsec"><div class="lsec-h">
        <span>${LANG === 'es' ? 'Activas' : 'Active'} (${active.length})</span>
        <a data-act="clear">${LANG === 'es' ? 'Quitar todas' : 'Clear all'}</a>
      </div>${active.map(l => layerRow(l, true)).join('')}</div>`;
  }

  const shown = RESULTS.filter(l => !activeIds.has(l.id));
  const byCat = {};
  shown.forEach(l => (byCat[l.category] = byCat[l.category] || []).push(l));
  const cats = CATEGORIES.length
    ? CATEGORIES.map(c => c.category).filter(c => byCat[c])
    : Object.keys(byCat);

  cats.forEach(c => {
    const rows = byCat[c] || [];
    const open = EXPANDED.has(c);
    html += `<div class="lsec">
      <div class="lsec-h clickable" data-act="cat" data-cat="${esc(c)}">
        <span>${open ? '&#9662;' : '&#9656;'} ${esc(catLabel(c))}</span><span class="cnt">${rows.length}</span>
      </div>${open ? rows.map(l => layerRow(l, false)).join('') : ''}</div>`;
  });

  if (!shown.length && !active.length) {
    html += `<div class="lempty">${LANG === 'es' ? 'Sin resultados' : 'No results'}</div>`;
  }
  if (RESULT_TOTAL > RESULTS.length) {
    html += `<div class="lmore">${LANG === 'es' ? 'Mostrando' : 'Showing'} ${RESULTS.length} / ${RESULT_TOTAL}</div>`;
  }
  el.innerHTML = html;
  renderLegend();
}

function renderLegend() {
  const el = document.getElementById('legend');
  if (!el) return;
  const active = [...ACTIVE.values()];
  if (!active.length) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  el.innerHTML = `<div class="lg-h">${LANG === 'es' ? 'Leyenda' : 'Legend'}</div>` +
    active.map(l => `<div class="lg-r">
        <span class="lg-k" style="background:${(l.style && l.style.color) || '#0b5d4b'}"></span>
        <span>${esc(l.name)}</span></div>`).join('') +
    `<div class="lg-src">${LANG === 'es' ? 'Fuente' : 'Source'}: ${
      esc(active[0].source && active[0].source.inventory || '')}</div>`;
}

// --- one delegated handler for the whole panel ---
document.getElementById('layerlist').addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  const act = el.dataset.act, id = el.dataset.id;
  if (act === 'add') addLayer(id);
  else if (act === 'remove') removeLayer(id);
  else if (act === 'info') showLayerInfo(id);
  else if (act === 'raise') raiseLayer(id);
  else if (act === 'clear') [...ACTIVE.keys()].forEach(removeLayer);
  else if (act === 'cat') {
    const c = el.dataset.cat;
    EXPANDED.has(c) ? EXPANDED.delete(c) : EXPANDED.add(c);
    renderLayerPanel();
  }
});
document.getElementById('lyrq').addEventListener('input', (e) => {
  layerQuery = e.target.value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(fetchLayers, 250);   // debounce: search runs server-side
});

// --- map wiring: vector tiles, not whole-layer GeoJSON ---
function addLayer(id) {
  if (!map) return;
  if (ACTIVE.has(id)) return;
  const l = RESULTS.find(x => x.id === id);
  if (!l) return;
  if (!mapReady) { if (!pendingAdds.includes(id)) pendingAdds.push(id); return; }
  const srcId = SRC(id), base = LYR(id);
  if (!map.getSource(srcId)) {
    map.addSource(srcId, {
      type: 'vector',
      tiles: [location.origin + l.tiles_url],
      minzoom: l.min_zoom != null ? l.min_zoom : 0,
      maxzoom: l.max_zoom != null ? l.max_zoom : 14,
    });
  }
  const color = (l.style && l.style.color) || '#0b5d4b';
  const g = (l.geometry_type || '').toLowerCase();
  const common = { source: srcId, 'source-layer': 'layer' };
  if (g.includes('polygon')) {
    const fillOp = l.style && l.style.fillOpacity != null ? l.style.fillOpacity : 0.35;
    if (fillOp > 0) map.addLayer({ id: base, type: 'fill', ...common,
      paint: { 'fill-color': color, 'fill-opacity': fillOp } });
    map.addLayer({ id: base + '_ln', type: 'line', ...common,
      paint: { 'line-color': color, 'line-width': (l.style && l.style.lineWidth) || 0.8 } });
  } else if (g.includes('line')) {
    map.addLayer({ id: base, type: 'line', ...common,
      paint: { 'line-color': color, 'line-width': 1.4 } });
  } else {
    map.addLayer({ id: base, type: 'circle', ...common,
      paint: { 'circle-radius': 5, 'circle-color': color,
               'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5 } });
  }
  // Clicking any feature - polygon, line or point - shows its attributes.
  [base, base + '_ln'].forEach(lid => {
    if (!map.getLayer(lid)) return;
    map.on('click', lid, featurePopup);
    map.on('mouseenter', lid, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', lid, () => { map.getCanvas().style.cursor = ''; });
  });
  ACTIVE.set(id, { ...l });
  restyle();
  renderLayerPanel();
}

function removeLayer(id) {
  if (!map) { ACTIVE.delete(id); renderLayerPanel(); return; }
  [LYR(id), LYR(id) + '_ln'].forEach(x => { if (map.getLayer(x)) map.removeLayer(x); });
  if (map.getSource(SRC(id))) map.removeSource(SRC(id));
  ACTIVE.delete(id);
  restyle();
  renderLayerPanel();
}

// Stacking rules. Two flat 35% fills make mud and three are unreadable, so only the
// topmost polygon layer is filled - everything under it keeps its outline and reads
// as a boundary. Draw order follows meaning rather than the order things were
// clicked: boundaries sit under hazards, hazards under facilities.
const STACK_ORDER = { political: 0, uso_de_terrenos: 1, inundacion: 2, deslizamiento: 3,
                      vias: 4, refugios: 5, educacion: 6, salud: 7 };

function restyle() {
  if (!map) return;
  const actives = [...ACTIVE.values()];
  // Sort by meaning, then by the order the user added them.
  const ordered = actives
    .map((l, i) => ({ l, i }))
    .sort((a, b) => (STACK_ORDER[a.l.theme] ?? 2) - (STACK_ORDER[b.l.theme] ?? 2) || a.i - b.i)
    .map(x => x.l);

  const polys = ordered.filter(l => (l.geometry_type || '').toLowerCase().includes('polygon'));
  const topPoly = polys.length ? polys[polys.length - 1].id : null;

  ordered.forEach(l => {
    const fillId = LYR(l.id);
    if (map.getLayer(fillId) && map.getLayer(fillId).type === 'fill') {
      const target = l.id === topPoly
        ? (l.style && l.style.fillOpacity != null ? l.style.fillOpacity : 0.4)
        : 0;                                  // underneath: outline only
      map.setPaintProperty(fillId, 'fill-opacity', target);
    }
    // Outlines get heavier when a layer is not the filled one, so it still reads.
    const lnId = fillId + '_ln';
    if (map.getLayer(lnId)) {
      map.setPaintProperty(lnId, 'line-width', l.id === topPoly ? 0.7 : 1.3);
      map.setPaintProperty(lnId, 'line-opacity', l.id === topPoly ? 0.55 : 0.95);
    }
    // Re-assert draw order.
    [fillId, lnId].forEach(x => { if (map.getLayer(x)) map.moveLayer(x); });
  });
}

// Bring a layer to the front: it becomes the filled one.
function raiseLayer(id) {
  const rec = ACTIVE.get(id);
  if (!rec) return;
  ACTIVE.delete(id);
  ACTIVE.set(id, rec);     // re-insert last = most recently raised
  restyle();
  renderLayerPanel();
}

// Per-layer provenance card - what the layer is, where it came from, and how
// confident that metadata is.
async function showLayerInfo(id) {
  try {
    const l = await (await fetch(`/catalog/layers/${id}?lang=${LANG}`)).json();
    const s = l.source || {};
    const box = document.getElementById('layerinfo');
    box.innerHTML = `<div class="li-h"><b>${esc(l.name)}</b>
        <button class="ic" data-close="1">&times;</button></div>
      ${l.description ? `<p>${esc(l.description)}</p>` : ''}
      <dl>
        <dt>${LANG === 'es' ? 'Agencia' : 'Agency'}</dt><dd>${esc(s.agency || '—')}</dd>
        <dt>${LANG === 'es' ? 'Año' : 'Year'}</dt><dd>${s.year || '—'}</dd>
        <dt>${LANG === 'es' ? 'Elementos' : 'Features'}</dt><dd>${(l.feature_count || 0).toLocaleString()}</dd>
        <dt>${LANG === 'es' ? 'Procedencia' : 'Provenance'}</dt><dd>${esc(s.inventory || '—')}</dd>
        <dt>${LANG === 'es' ? 'Metadatos' : 'Metadata'}</dt><dd>${statusChip(s.metadata_status)}</dd>
      </dl>`;
    box.style.display = 'block';
    box.querySelector('[data-close]').onclick = () => { box.style.display = 'none'; };
  } catch (e) { /* non-fatal */ }
}

function featurePopup(e) {
  const f = e.features && e.features[0];
  if (!f) return;
  const props = f.properties || {};
  // Which layer was clicked, so the popup can say what the feature belongs to.
  const lid = (f.layer && f.layer.id || '').replace(/^lyr_/, '').replace(/_ln$/, '');
  const rec = ACTIVE.get(lid);
  const rows = Object.entries(props)
    .filter(([k, v]) => v !== null && v !== '' && v !== undefined)
    .slice(0, 8)
    .map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(String(v))}</td></tr>`)
    .join('');
  const head = rec ? `<div class="fp-h">${esc(rec.name)}${
    rec.source && rec.source.year ? ` · ${rec.source.year}` : ''}</div>` : '';
  const body = rows
    ? `<table class="fp">${rows}</table>`
    : `<div class="fp-none">${LANG === 'es'
        ? 'Esta capa no trae atributos para este elemento.'
        : 'This layer carries no attributes for this feature.'}</div>`;
  showPopup(e.lngLat, head + body);
}

// Turn on layers the answer referenced, by matching catalog keywords.
function autoShowLayers(themes) {
  if (!themes || !themes.length) return;
  const alias = { zonificacion: 'uso_de_terrenos' };
  const want = new Set((themes || []).map(x => alias[x] || x));
  RESULTS.forEach(l => {
    if (ACTIVE.has(l.id)) return;
    if (want.has(l.theme) || (l.keywords || []).some(k => want.has(k))) addLayer(l.id);
  });
}

// The layer catalog is just data, so it loads independently of the map. If WebGL
// is slow or unavailable the panel still works, and anything the user turns on
// before the map is ready is queued and applied on load.
let mapReady = false;
const pendingAdds = [];
if (map) map.on('load', () => {
  mapReady = true;
  const queued = pendingAdds.splice(0);
  queued.forEach(addLayer);
});
loadCatalog();

// --- panel toggles: give the map more room (La Marana's feedback) ---
{
  const ct = document.getElementById('chattoggle');
  if (ct) ct.onclick = () => {
    document.querySelector('main').classList.toggle('chat-hidden');
    setTimeout(() => { if (map) map.resize(); }, 210);   // let the grid settle, then re-measure
  };
  const lt = document.getElementById('lyrtoggle');
  if (lt) lt.onclick = () => {
    const list = document.getElementById('layerlist');
    const q2 = document.getElementById('lyrq');
    const hidden = list.style.display === 'none';
    list.style.display = hidden ? '' : 'none';
    if (q2) q2.style.display = hidden ? '' : 'none';
    lt.innerHTML = hidden ? '&#9662;' : '&#9656;';
    setTimeout(() => { if (map) map.resize(); }, 210);
  };
}


// Fly/zoom the map to a bbox [w,s,e,n] the chat is answering about.
function focusBBox(bbox) {
  if (!map || !bbox || bbox.length !== 4) return;
  map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: 60, duration: 1600, maxZoom: 11 });
}

// ---------------------------------------------------------------------------
// Click the map -> which municipio + hazards apply here, and ask about it.
// ---------------------------------------------------------------------------
let locMarker = null;
let pending = null;
// Exactly one popup on the map at a time.
let openPopup = null;
function showPopup(lngLat, html) {
  if (openPopup) openPopup.remove();
  openPopup = new maplibregl.Popup({ closeOnClick: true, maxWidth: '290px' })
    .setLngLat(lngLat).setHTML(html).addTo(map);
  openPopup.on('close', () => { openPopup = null; });
  return openPopup;
}

if (map) map.on('click', async (e) => {
  // Only a point feature (hospital/school/shelter dot) shows its own popup; clicking
  // empty land, a boundary, or a hazard area still gives the location card.
  const onPoint = map.queryRenderedFeatures(e.point)
    .some(f => f.layer && f.layer.type === 'circle' && (f.layer.id || '').startsWith('lyr_'));
  if (onPoint) return;
  const { lng, lat } = e.lngLat;
  let info;
  try {
    info = await (await fetch(`/locate?lng=${lng}&lat=${lat}`)).json();
  } catch (err) { info = { municipio: null, hazards: {} }; }
  if (locMarker) locMarker.remove();
  locMarker = new maplibregl.Marker({ color: '#0b5d4b' }).setLngLat([lng, lat]).addTo(map);

  const muni = info.municipio;
  const h = info.hazards || {};
  const es = LANG === 'es';
  const yn = b => b ? `<b style="color:#c53030">${es ? 'Sí' : 'Yes'}</b>` : 'No';
  pending = muni ? { municipio: muni, spatial: info } : null;
  const askTxt = es ? 'Preguntar sobre este lugar' : 'Ask about this place';
  const floodTxt = es ? 'Zona inundable' : 'Flood zone';
  const slideTxt = es ? 'Deslizamiento' : 'Landslide';
  const action = muni
    ? `<button class="askbtn" onclick="askHere()">${askTxt}</button>`
    : `<div style="color:#888;margin-top:6px">${es ? 'Fuera de Puerto Rico' : 'Outside Puerto Rico'}</div>`;
  const html = `<div style="font-size:13px;line-height:1.6">
      <b>📍 ${esc(muni || '—')}</b><br>
      ${floodTxt} — 2009: ${yn(h.flood_2009)} · 2018: ${yn(h.flood_0_2pct_2018)}<br>
      ${slideTxt}: ${yn(h.landslide)}
      <div style="margin-top:8px">${action}</div>
    </div>`;
  showPopup([lng, lat], html);
});

// Global so the popup button's onclick works with no DOM-timing issues.
function askHere() {
  if (!pending) return;
  activeLocation = pending.municipio;
  activeSpatial = pending.spatial;
  renderLoc();
  const h = pending.spatial.hazards || {};
  const es = LANG === 'es';
  const hz = [];
  if (h.flood_2009 || h.flood_0_2pct_2018) hz.push(es ? 'inundación' : 'flood');
  if (h.landslide) hz.push(es ? 'deslizamiento' : 'landslide');
  if (es) {
    const risk = hz.length ? 'riesgos de ' + hz.join(' y ') : 'riesgos naturales';
    q.value = `¿Cuáles son los ${risk} y las reglas de construcción y planificación en ${pending.municipio}?`;
  } else {
    const risk = hz.length ? hz.join(' and ') + ' risks' : 'natural hazard risks';
    q.value = `What are the ${risk} and building/planning rules in ${pending.municipio}?`;
  }
  ask();
}

// initial paint (welcome state) + language labels
applyLang();
