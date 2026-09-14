const map = new maplibregl.Map({
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
    layers: [{ id: 'basemap', type: 'raster', source: 'basemap' }],
  },
  center: [-66.25, 18.22],
  zoom: 8.4,
});
map.addControl(new maplibregl.NavigationControl());

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
const LAYER_LABELS = {
  layer_g03_legales_municipios_2015: { es: 'Municipios', en: 'Municipalities' },
  layer_barrios_2015_geoid_corrected_16_nov17: { es: 'Barrios', en: 'Barrios (wards)' },
  layer_g23_riesgo_inundacion_fema_firms_2009: { es: 'Zonas inundables FEMA 2009', en: 'FEMA flood zones 2009' },
  layer_g23_riesgo_inundacion_floodzone_0_2pct_seamless_2018: { es: 'Inundación 0.2% anual FEMA 2018', en: 'FEMA 0.2% flood zone 2018' },
  layer_landsl_monroe_plus_slop50pct: { es: 'Susceptibilidad a deslizamientos', en: 'Landslide susceptibility' },
  layer_plan_uso_terrenos_2015: { es: 'Plan de Uso de Terrenos 2015', en: 'Land Use Plan 2015' },
  layer_hospitales: { es: 'Hospitales y CDTs', en: 'Hospitals & CDTs' },
  layer_dotacional_educacion_escuelas_2021: { es: 'Escuelas públicas 2021', en: 'Public schools 2021' },
  layer_refugios_2023: { es: 'Refugios de emergencia 2023', en: 'Emergency shelters 2023' },
  layer_carreteras_estatales_segmentadas_agosto_2021: { es: 'Carreteras estatales 2021', en: 'State roads 2021' },
};
const layerLabel = l => (LAYER_LABELS[l.layer_name] ? LAYER_LABELS[l.layer_name][LANG] : (l.description || themeLabel(l.theme)));

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
  if (CATALOG.length) renderLayerPanel();
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
    out.innerHTML = `<div class="empty">
      <div class="icon">🗺️</div>
      <h3 translate="no">${t('emptyT')}</h3>
      <p>${t('emptyB')}</p>
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
const THEME = {
  political:       { color: '#555555', label: 'Límites' },
  inundacion:      { color: '#2b6cb0', label: 'Inundación' },
  deslizamiento:   { color: '#b7791f', label: 'Deslizamiento' },
  uso_de_terrenos: { color: '#2f855a', label: 'Uso de terrenos' },
  salud:           { color: '#c53030', label: 'Salud' },
  educacion:       { color: '#6b46c1', label: 'Educación' },
  refugios:        { color: '#0d9488', label: 'Refugios' },
  vias:            { color: '#333333', label: 'Vías' },
};
const themeColor = t => (THEME[t] || { color: '#0b5d4b' }).color;
const themeLabel = t => (THEME[t] || { label: t }).label;

const CATEGORY = {
  inundacion: 'Riesgos', deslizamiento: 'Riesgos',
  salud: 'Servicios', educacion: 'Servicios', refugios: 'Servicios',
  uso_de_terrenos: 'Planificación', vias: 'Infraestructura',
  political: 'Límites',
};
const CAT_ORDER = ['Riesgos', 'Servicios', 'Planificación', 'Infraestructura', 'Límites'];

// ---------------------------------------------------------------------------
// Layer panel. State lives here (not in the DOM), and every click goes through
// ONE delegated handler — so a click can never fire two competing toggles.
// ---------------------------------------------------------------------------
let CATALOG = [];                       // all layers from /layers
const ACTIVE = new Map();               // layer_name -> { layer, opacity }
const GEOJSON_CACHE = {};               // layer_name -> geojson (fetch once)
const BUSY = new Set();                 // layer_names mid-fetch
let layerQuery = '';                    // search box text

const layerByName = n => CATALOG.find(l => l.layer_name === n);

async function loadLayerList() {
  const list = document.getElementById('layerlist');
  try {
    CATALOG = await (await fetch('/layers')).json();
    renderLayerPanel();
  } catch (e) {
    list.textContent = LANG === 'es' ? 'No se pudieron cargar las capas.' : 'Could not load layers.';
  }
}

function renderLayerPanel() {
  const list = document.getElementById('layerlist');
  if (!list) return;
  const es = LANG === 'es';
  const filter = layerQuery.trim().toLowerCase();

  // Active layers first, so you always see what's on.
  let html = `<div class="lyr-search">
      <input id="lyrq" type="text" placeholder="${es ? 'Buscar capas…' : 'Search layers…'}" value="${esc(layerQuery)}">
    </div>`;

  if (ACTIVE.size) {
    html += `<div class="lyr-sec">
      <div class="lyr-sec-h">
        <span>${es ? 'Activas' : 'Active'} (${ACTIVE.size})</span>
        <a data-act="clear">${es ? 'Quitar todas' : 'Clear all'}</a>
      </div>`;
    for (const [name, st] of ACTIVE) {
      const l = st.layer;
      html += `<div class="lyr-item on">
        <span class="swatch" style="background:${themeColor(l.theme)}"></span>
        <span class="lyr-name">${esc(layerLabel(l))}${l.year ? `<span class="yr"> · ${l.year}</span>` : ''}</span>
        <input class="op" type="range" min="10" max="100" value="${Math.round(st.opacity * 100)}"
               data-act="opacity" data-name="${esc(name)}" title="${es ? 'Opacidad' : 'Opacity'}">
        <button class="lyr-btn rm" data-act="remove" data-name="${esc(name)}"
                title="${es ? 'Quitar' : 'Remove'}">✕</button>
      </div>`;
    }
    html += `</div>`;
  }

  // Catalog of everything not active, grouped by category, filtered by search.
  const avail = CATALOG.filter(l => !ACTIVE.has(l.layer_name))
    .filter(l => !filter || layerLabel(l).toLowerCase().includes(filter) || catLabel(CATEGORY[l.theme] || 'Otros').toLowerCase().includes(filter));
  const groups = {};
  avail.forEach(l => { const c = CATEGORY[l.theme] || 'Otros'; (groups[c] = groups[c] || []).push(l); });
  const cats = CAT_ORDER.filter(c => groups[c]).concat(Object.keys(groups).filter(c => !CAT_ORDER.includes(c)));

  if (!avail.length) {
    html += `<div class="lyr-none">${filter ? (es ? 'Sin resultados' : 'No matches') : (es ? 'Todas las capas están activas' : 'All layers active')}</div>`;
  }
  cats.forEach(cat => {
    html += `<div class="lyr-sec">
      <div class="lyr-sec-h"><span>${esc(catLabel(cat))}</span></div>
      ${groups[cat].map(l => {
        const busy = BUSY.has(l.layer_name);
        return `<div class="lyr-item${busy ? ' loading' : ''}" data-act="add" data-name="${esc(l.layer_name)}">
          <span class="swatch off" style="border-color:${themeColor(l.theme)}"></span>
          <span class="lyr-name">${esc(layerLabel(l))}${l.year ? `<span class="yr"> · ${l.year}</span>` : ''}</span>
          <span class="lyr-btn add">${busy ? '<span class="spin"></span>' : '+'}</span>
        </div>`;
      }).join('')}
    </div>`;
  });

  list.innerHTML = html;
}

// Single delegated handler for the whole panel — no competing listeners.
document.getElementById('layerlist').addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (!el) return;
  const act = el.dataset.act;
  if (act === 'add') addLayer(el.dataset.name);
  else if (act === 'remove') removeLayer(el.dataset.name);
  else if (act === 'clear') { [...ACTIVE.keys()].forEach(removeLayer); }
});
document.getElementById('layerlist').addEventListener('input', (e) => {
  if (e.target.id === 'lyrq') {
    layerQuery = e.target.value;
    renderLayerPanel();
    const box = document.getElementById('lyrq');
    if (box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); }
  } else if (e.target.dataset.act === 'opacity') {
    setLayerOpacity(e.target.dataset.name, e.target.value / 100);
  }
});

async function addLayer(name) {
  if (ACTIVE.has(name) || BUSY.has(name)) return;   // idempotent
  const l = layerByName(name);
  if (!l) return;
  const srcId = 'src_' + name, lyrId = 'lyr_' + name;
  BUSY.add(name); renderLayerPanel();
  try {
    if (!GEOJSON_CACHE[name]) GEOJSON_CACHE[name] = await (await fetch('/layer/' + name)).json();
    if (!map.getSource(srcId)) map.addSource(srcId, { type: 'geojson', data: GEOJSON_CACHE[name] });
    addStyledLayer(lyrId, srcId, l.geometry_type, themeColor(l.theme), l.theme);
    ACTIVE.set(name, { layer: l, opacity: l.geometry_type.includes('Polygon') && l.theme !== 'political' ? 0.35 : 1 });
  } catch (err) {
    console.error('layer add failed', name, err);
  } finally {
    BUSY.delete(name); renderLayerPanel();
  }
}

function removeLayer(name) {
  const lyrId = 'lyr_' + name, srcId = 'src_' + name;
  [lyrId, lyrId + '_outline'].forEach(id => { if (map.getLayer(id)) map.removeLayer(id); });
  if (map.getSource(srcId)) map.removeSource(srcId);
  ACTIVE.delete(name);
  renderLayerPanel();
}

function setLayerOpacity(name, val) {
  const st = ACTIVE.get(name);
  if (!st) return;
  st.opacity = val;
  ['lyr_' + name, 'lyr_' + name + '_outline'].forEach(id => {
    if (!map.getLayer(id)) return;
    const type = map.getLayer(id).type;
    const prop = type === 'fill' ? 'fill-opacity' : type === 'line' ? 'line-opacity' : 'circle-opacity';
    // Polygon fills top out at 0.35 so the basemap stays readable.
    const cap = type === 'fill' ? 0.35 : 1;
    map.setPaintProperty(id, prop, val * cap);
  });
}

function featurePopup(e) {
  const p = (e.features && e.features[0] && e.features[0].properties) || {};
  const title = p.name || 'Sin nombre';
  const sub = p.sub ? `<br><span style="color:#667">${esc(p.sub)}</span>` : '';
  new maplibregl.Popup({ closeOnClick: true, maxWidth: '240px' })
    .setLngLat(e.lngLat).setHTML(`<div style="font-size:13px"><b>${esc(title)}</b>${sub}</div>`).addTo(map);
}

function addStyledLayer(lyrId, srcId, gtype, color, theme) {
  if (gtype.includes('Polygon')) {
    // Boundaries (municipios/barrios) look best as clean outlines; hazards/land use get a fill.
    if (theme !== 'political') {
      map.addLayer({ id: lyrId, type: 'fill', source: srcId, paint: { 'fill-color': color, 'fill-opacity': 0.35 } });
    }
    map.addLayer({ id: lyrId + '_outline', type: 'line', source: srcId, paint: { 'line-color': color, 'line-width': theme === 'political' ? 1.1 : 0.8 } });
  } else if (gtype.includes('LineString')) {
    map.addLayer({ id: lyrId, type: 'line', source: srcId, paint: { 'line-color': color, 'line-width': 1.4 } });
  } else {
    map.addLayer({ id: lyrId, type: 'circle', source: srcId, paint: { 'circle-radius': 5, 'circle-color': color, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5 } });
    // Click a point (hospital/school/shelter) → show its name, not the flood popup.
    map.on('click', lyrId, featurePopup);
    map.on('mouseenter', lyrId, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', lyrId, () => { map.getCanvas().style.cursor = ''; });
  }
}

map.on('load', loadLayerList);

// Fly/zoom the map to a bbox [w,s,e,n] the chat is answering about.
function focusBBox(bbox) {
  if (!bbox || bbox.length !== 4) return;
  map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]], { padding: 60, duration: 1600, maxZoom: 11 });
}

// When an answer references themes (flood, landslide, zoning...), auto-show those
// layers on the map so the chat and map stay in sync.
function autoShowLayers(themes) {
  const alias = { zonificacion: 'uso_de_terrenos' };
  const wanted = new Set((themes || []).map(t => alias[t] || t));
  CATALOG.filter(l => wanted.has(l.theme) && !ACTIVE.has(l.layer_name))
    .forEach(l => addLayer(l.layer_name));
}

// ---------------------------------------------------------------------------
// Click the map -> which municipio + hazards apply here, and ask about it.
// ---------------------------------------------------------------------------
let locMarker = null;
let pending = null;

map.on('click', async (e) => {
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
  new maplibregl.Popup({ closeOnClick: true, maxWidth: '260px' })
    .setLngLat([lng, lat]).setHTML(html).addTo(map);
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
