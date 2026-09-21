// ---------------------------------------------------------------------------
// Basemap. A vector style rather than raster tiles: real cartographic hierarchy,
// labels that stay sharp at every zoom, and a muted ground that lets data layers
// read on top of it. OpenFreeMap serves OpenMapTiles-schema vector tiles with no
// key and no per-view billing, which matters for a tool La Marana inherits.
// Falls back to OSM raster if the vector style cannot be reached, so the map
// always draws something.
// ---------------------------------------------------------------------------
// Ordered richest-first. Positron is a deliberately grey, minimal style — useful
// when a dense data layer needs to dominate, and far too flat as a default.
const BASEMAPS = [
  { id: 'calles', es: 'Calles',  en: 'Streets',  style: 'https://tiles.openfreemap.org/styles/liberty' },
  { id: 'relieve',es: 'Detalle', en: 'Detailed', style: 'https://tiles.openfreemap.org/styles/bright' },
  { id: 'claro',  es: 'Tenue',   en: 'Muted',    style: 'https://tiles.openfreemap.org/styles/positron' },
  { id: 'osm',    es: 'OSM',     en: 'OSM',      style: null },   // raster fallback
];
let basemapId = localStorage.getItem('mappealo.basemap.v2') || 'calles';
const basemapStyle = id => {
  const b = BASEMAPS.find(x => x.id === id) || BASEMAPS[0];
  return b.style || RASTER_FALLBACK;
};
const RASTER_FALLBACK = {
  version: 8,
  sources: {
    basemap: {
      type: 'raster',
      tiles: ['https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
              'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
              'https://c.tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256, maxzoom: 19,
      attribution: '© OpenStreetMap contributors',
    },
  },
  layers: [{
    id: 'basemap', type: 'raster', source: 'basemap',
    paint: { 'raster-saturation': -0.35, 'raster-contrast': -0.05, 'raster-opacity': 0.94 },
  }],
};

let map = null;
let usingFallback = false;
try {
  map = new maplibregl.Map({
    container: 'map',
    style: basemapStyle(basemapId),
    center: [-66.25, 18.22],
    zoom: 8.3,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
  map.addControl(new maplibregl.ScaleControl({ maxWidth: 110, unit: 'metric' }), 'bottom-left');

  // If the vector style never arrives, swap to raster once and re-apply any layers
  // the user had turned on.
  map.on('error', (ev) => {
    const failedStyle = ev && ev.error && /style|sprite|glyph/i.test(String(ev.error.message || ''));
    if (usingFallback || !failedStyle || map.isStyleLoaded()) return;
    usingFallback = true;
    map.setStyle(RASTER_FALLBACK);
    map.once('styledata', () => {
      const ids = [...ACTIVE.keys()];
      ACTIVE.clear();
      ids.forEach(addLayer);
    });
  });
} catch (err) {
  const el = document.getElementById('map');
  if (el) el.innerHTML = '<div style="padding:20px;color:#68746e;font-size:13px">' +
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
        // '¡Aló!' is how the brand greets people - the same word in both languages,
        // so the welcome reads as Puerto Rican rather than as a translated label.
        sources: 'Fuentes', layersTitle: 'Capas del mapa', emptyT: '¡Aló!',
        emptyB: 'Pregúntale a Mappa sobre uso de terrenos, riesgo de inundación o deslizamiento, permisos y planificación en Puerto Rico. También puedes hacer clic en el mapa para preguntar sobre un lugar. Puedes preguntar en español o en inglés.' },
  en: { tagline: 'Planning & hazard assistant for Puerto Rico',
        ph: 'Type your question… or click the map', clear: 'New conversation',
        sources: 'Sources', layersTitle: 'Map layers', emptyT: '¡Aló!',
        emptyB: 'Ask Mappa about land use, flood or landslide risk, permits, and planning in Puerto Rico. You can also click the map to ask about a place. Ask questions in Spanish or English.' },
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
  const pqel = document.getElementById('placeq');
  if (pqel) pqel.placeholder = LANG === 'es'
    ? 'Buscar municipio o barrio…' : 'Search municipality or barrio…';
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
      ? '<b>Cada respuesta cita su fuente.</b> Si los documentos cargados no lo dicen, Mappa lo dirá en vez de inventarlo.'
      : '<b>Every answer cites its source.</b> If the loaded documents do not say it, Mappa will say so rather than fill the gap.';
    out.innerHTML = `<div class="empty">
      <div class="icon"><img src="/static/logo.png" alt="" width="76" height="76"></div>
      <h3 translate="no">${t('emptyT')}</h3>
      <p>${t('emptyB')}</p>
      <div class="hint">${hint}</div>
    </div>`;
    return;
  }
  out.innerHTML = conversation.map(m => {
    const layers = (m.suggested_layers || []).map(l => `<span class="tag">${esc(l)}</span>`).join('');
    const cites = (m.citations || []).map(c =>
      `<div class="cite">📄 <span class="ct">${esc(c.title)}</span>${
        c.year ? ` · ${c.year}` : ''}${c.doc_id ? ` · <span class="cid">${esc(c.doc_id)}</span>` : ''}</div>`
    ).join('');
    const thinking = m.answer === '…';
    const conf = (m.confidence && !thinking) ? `<span class="badge ${confClass(m.confidence)}">${esc(m.confidence)}</span>` : '';
    return `
      <div class="row user"><div class="bubble">${esc(m.question)}</div></div>
      <div class="row bot"><div class="bubble">
        <div class="who">Mappa ${conf}</div>
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
  const turn = { question, answer: '', citations: [], suggested_layers: [], confidence: '' };
  conversation.push(turn);
  render();
  q.value = '';

  // A request with no deadline is how the panel came to sit on "Thinking…" for
  // ten minutes: fetch waits forever, so a stalled connection never resolves and
  // never errors either.
  const ctl = new AbortController();
  const deadline = setTimeout(() => ctl.abort(), 90000);

  try {
    const r = await fetch('/ask/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: ctl.signal,
      body: JSON.stringify({
        question,
        history: conversation.slice(0, -1).map(t => ({ question: t.question, answer: t.answer })),
        location: activeLocation,
        spatial: activeSpatial,
        lang: LANG,
        active_layers: [...ACTIVE.values()].map(l => ({
          id: l.id, name: l.name, theme: l.theme,
          year: l.source && l.source.year, agency: l.source && l.source.agency,
        })),
      }),
    });
    if (!r.ok || !r.body) throw new Error('HTTP ' + r.status);

    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      // Server-sent events are separated by a blank line; anything after the last
      // one is a partial event and stays in the buffer.
      const chunks = buf.split('\n\n');
      buf = chunks.pop();
      for (const chunk of chunks) {
        const ev = /^event: (\w+)/m.exec(chunk);
        const dl = /^data: (.*)$/m.exec(chunk);
        if (!ev || !dl) continue;
        let d; try { d = JSON.parse(dl[1]); } catch (e) { continue; }
        if (ev[1] === 'meta') {
          // The map moves before the first word is written.
          disc.textContent = d.disclaimer || '';
          turn.suggested_layers = d.suggested_layers || [];
          autoShowLayers(turn.suggested_layers);
          if (d.focus) focusBBox(d.focus);
        } else if (ev[1] === 'delta') {
          turn.answer += d.text || '';
          render();
        } else if (ev[1] === 'done') {
          turn.citations = d.citations || [];
          turn.confidence = d.confidence || '';
          render();
        }
      }
    }
    if (!turn.answer) throw new Error('empty response');
  } catch (e) {
    turn.answer = e.name === 'AbortError'
      ? (LANG === 'es'
          ? 'La respuesta tardó demasiado. Inténtalo de nuevo.'
          : 'That took too long to answer. Please try again.')
      : 'Error: ' + e.message;
    render();
  } finally {
    clearTimeout(deadline);
    btn.disabled = false;
    q.focus();
  }
}

// Global so the popup button's onclick works with no DOM-timing issues.
function askHere() {
  if (!pending) return;
  activeLocation = pending.municipio;
  activeSpatial = pending.spatial;
  renderLoc();
  q.value = LANG === 'es'
    ? `¿Qué debo saber sobre ${pending.municipio}: riesgos naturales, uso de terrenos y reglas de planificación?`
    : `What should I know about ${pending.municipio}: natural hazards, land use, and planning rules?`;
  ask();
}

// initial paint (welcome state) + language labels
applyLang();
