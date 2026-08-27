const map = new maplibregl.Map({
  container: 'map',
  // Free, no-key basemap (Carto Voyager) — real streets + municipio labels.
  style: {
    version: 8,
    sources: {
      basemap: {
        type: 'raster',
        tiles: [
          'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
          'https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
          'https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
        ],
        tileSize: 256,
        attribution: '© OpenStreetMap contributors, © CARTO',
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
      <h3>Pregúntale a MAPPA</h3>
      <p>Uso de terrenos, riesgo de inundación o deslizamiento, permisos y planificación en Puerto Rico. También puedes hacer clic en el mapa para preguntar sobre un lugar.</p>
    </div>`;
    return;
  }
  out.innerHTML = conversation.map(t => {
    const layers = (t.suggested_layers || []).map(l => `<span class="tag">${esc(l)}</span>`).join('');
    const cites = (t.citations || []).map(c =>
      `<div class="cite">📄 <a href="${c.url}" target="_blank">${esc(c.title)}</a>${c.year ? ` · ${c.year}` : ''}</div>`
    ).join('');
    const thinking = t.answer === '…';
    const conf = (t.confidence && !thinking) ? `<span class="badge ${confClass(t.confidence)}">${esc(t.confidence)}</span>` : '';
    return `
      <div class="row user"><div class="bubble">${esc(t.question)}</div></div>
      <div class="row bot"><div class="bubble">
        <div class="who">MAPPA ${conf}</div>
        <div class="answer${thinking ? ' typing' : ''}">${thinking ? 'Consultando…' : esc(t.answer)}</div>
        ${cites ? `<div class="cites"><div class="cites-h">Fuentes</div>${cites}</div>` : ''}
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

async function loadLayerList() {
  const list = document.getElementById('layerlist');
  try {
    const layers = await (await fetch('/layers')).json();
    const groups = {};
    layers.forEach(l => { const c = CATEGORY[l.theme] || 'Otros'; (groups[c] = groups[c] || []).push(l); });
    const cats = CAT_ORDER.filter(c => groups[c]).concat(Object.keys(groups).filter(c => !CAT_ORDER.includes(c)));
    list.innerHTML = cats.map(cat => `
      <div class="lyr-group">
        <div class="lyr-group-title">${esc(cat)}</div>
        ${groups[cat].map(l => {
          const nm = l.description || themeLabel(l.theme);
          const yr = l.year ? ` <span style="color:var(--muted)">· ${l.year}</span>` : '';
          return `<div class="lyr-row">
            <span class="swatch" style="background:${themeColor(l.theme)}"></span>
            <span class="name">${esc(nm)}${yr}</span>
            <label class="switch"><input type="checkbox" data-layer="${l.layer_name}" data-theme="${l.theme}" data-gtype="${l.geometry_type}"><span class="slider"></span></label>
          </div>`;
        }).join('')}
      </div>`).join('');
    list.querySelectorAll('input').forEach(cb => cb.onchange = () => toggleLayer(cb));
    // Clicking anywhere on a row toggles its switch.
    list.querySelectorAll('.lyr-row').forEach(row => row.onclick = (e) => {
      if (e.target.tagName === 'INPUT') return;
      const cb = row.querySelector('input'); cb.checked = !cb.checked; toggleLayer(cb);
    });
  } catch (e) {
    list.textContent = 'No se pudieron cargar las capas.';
  }
}

async function toggleLayer(cb) {
  const name = cb.dataset.layer, theme = cb.dataset.theme, gtype = cb.dataset.gtype;
  const srcId = 'src_' + name, lyrId = 'lyr_' + name;
  if (cb.checked) {
    cb.disabled = true;
    try {
      const gj = await (await fetch('/layer/' + name)).json();
      if (!map.getSource(srcId)) map.addSource(srcId, { type: 'geojson', data: gj });
      addStyledLayer(lyrId, srcId, gtype, themeColor(theme));
    } catch (e) {
      cb.checked = false;
    } finally {
      cb.disabled = false;
    }
  } else {
    [lyrId, lyrId + '_outline'].forEach(id => { if (map.getLayer(id)) map.removeLayer(id); });
    if (map.getSource(srcId)) map.removeSource(srcId);
  }
}

function featurePopup(e) {
  const p = (e.features && e.features[0] && e.features[0].properties) || {};
  const title = p.name || 'Sin nombre';
  const sub = p.sub ? `<br><span style="color:#667">${esc(p.sub)}</span>` : '';
  new maplibregl.Popup({ closeOnClick: true, maxWidth: '240px' })
    .setLngLat(e.lngLat).setHTML(`<div style="font-size:13px"><b>${esc(title)}</b>${sub}</div>`).addTo(map);
}

function addStyledLayer(lyrId, srcId, gtype, color) {
  if (gtype.includes('Polygon')) {
    map.addLayer({ id: lyrId, type: 'fill', source: srcId, paint: { 'fill-color': color, 'fill-opacity': 0.35 } });
    map.addLayer({ id: lyrId + '_outline', type: 'line', source: srcId, paint: { 'line-color': color, 'line-width': 0.8 } });
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

// When an answer references themes (flood, landslide, zoning...), auto-show those
// layers on the map so the chat and map stay in sync.
function autoShowLayers(themes) {
  const alias = { zonificacion: 'uso_de_terrenos' };
  const wanted = new Set((themes || []).map(t => alias[t] || t));
  document.querySelectorAll('#layerlist input').forEach(cb => {
    if (wanted.has(cb.dataset.theme) && !cb.checked) {
      cb.checked = true;
      toggleLayer(cb);
    }
  });
}

// ---------------------------------------------------------------------------
// Click the map -> which municipio + hazards apply here, and ask about it.
// ---------------------------------------------------------------------------
let locMarker = null;
map.on('click', async (e) => {
  // If a loaded data feature was clicked, its own popup handles it — skip the location popup.
  const onFeature = map.queryRenderedFeatures(e.point)
    .some(f => f.layer && (f.layer.id || '').startsWith('lyr_'));
  if (onFeature) return;
  const { lng, lat } = e.lngLat;
  let info;
  try {
    info = await (await fetch(`/locate?lng=${lng}&lat=${lat}`)).json();
  } catch (err) { return; }
  if (locMarker) locMarker.remove();
  locMarker = new maplibregl.Marker({ color: '#0b5d4b' }).setLngLat([lng, lat]).addTo(map);
  map.flyTo({ center: [lng, lat], zoom: Math.max(map.getZoom(), 10), duration: 800 });

  const muni = info.municipio || '(fuera de Puerto Rico)';
  const h = info.hazards || {};
  const yn = b => b ? '<b style="color:#c53030">Sí</b>' : 'No';
  const html = `
    <div style="font-size:13px;line-height:1.5">
      <b>📍 ${esc(muni)}</b><br>
      Zona inundable FEMA (2009): ${yn(h.flood_2009)}<br>
      Zona inundable 0.2% (2018): ${yn(h.flood_0_2pct_2018)}<br>
      Área de deslizamiento: ${yn(h.landslide)}<br>
      ${info.municipio ? `<button id="askhere" style="margin-top:6px">Preguntar sobre este lugar</button>` : ''}
    </div>`;
  const popup = new maplibregl.Popup({ closeOnClick: true, maxWidth: '260px' })
    .setLngLat([lng, lat]).setHTML(html).addTo(map);

  // Attach the button handler via the popup's own DOM element (reliable, no timing race).
  const el = popup.getElement();
  const btnAsk = el && el.querySelector('#askhere');
  if (btnAsk) btnAsk.addEventListener('click', () => {
    if (info.municipio) { activeLocation = info.municipio; renderLoc(); }
    activeSpatial = info;  // send this point's flood/landslide facts as context
    // Build a question specific to this place and the hazards actually found there.
    const hz = [];
    if (h.flood_2009 || h.flood_0_2pct_2018) hz.push('flood');
    if (h.landslide) hz.push('landslide');
    const risk = hz.length ? hz.join(' and ') + ' risks' : 'natural hazard risks';
    q.value = `What are the ${risk} and building/planning rules in ${muni}?`;
    popup.remove();
    ask();
  });
});

// initial paint (welcome state)
render();
