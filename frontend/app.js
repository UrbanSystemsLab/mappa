const map = new maplibregl.Map({
  container: 'map',
  style: 'https://demotiles.maplibre.org/style.json',
  center: [-66.4, 18.22],
  zoom: 8.2,
});
map.addControl(new maplibregl.NavigationControl());

const q = document.getElementById('q');
const out = document.getElementById('out');
const disc = document.getElementById('disc');
const btn = document.getElementById('go');
const clearBtn = document.getElementById('clear');

// The conversation persists here until the page is refreshed.
let conversation = [];
// When set (by clicking a town on the map), questions are scoped to this municipio.
let activeLocation = null;
const locEl = document.getElementById('loc');

function renderLoc() {
  if (activeLocation) {
    locEl.style.display = 'inline-block';
    locEl.innerHTML = `📍 ${esc(activeLocation)} <span class="x" title="Quitar filtro">✕</span>`;
    locEl.querySelector('.x').onclick = () => { activeLocation = null; renderLoc(); };
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

function render() {
  out.innerHTML = conversation.map(t => {
    const layers = (t.suggested_layers || []).map(l => `<span class="tag">${l}</span>`).join('');
    const cites = (t.citations || []).map(c =>
      `<div class="cite">• <a href="${c.url}" target="_blank">${esc(c.title)}</a>${c.year ? ` (${c.year})` : ''}</div>`
    ).join('');
    return `
      <div class="msg user">${esc(t.question)}</div>
      <div class="msg bot">
        <div class="answer">${esc(t.answer)}</div>
        ${t.confidence ? `<div class="meta">Confianza: <b>${t.confidence}</b> ${layers}</div>` : ''}
        ${cites ? `<div class="cites"><b>Fuentes</b>${cites}</div>` : ''}
      </div>`;
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
      }),
    });
    const d = await r.json();
    turn.answer = d.answer_es;
    turn.citations = d.citations || [];
    turn.suggested_layers = d.suggested_layers || [];
    turn.confidence = d.confidence || '';
    disc.textContent = d.disclaimer || '';
    render();
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

async function loadLayerList() {
  try {
    const layers = await (await fetch('/layers')).json();
    const list = document.getElementById('layerlist');
    list.innerHTML = layers.map(l => {
      const yr = l.year ? ` (${l.year})` : '';
      const name = l.description || l.layer_name;
      return `<label>
        <input type="checkbox" data-layer="${l.layer_name}" data-theme="${l.theme}" data-gtype="${l.geometry_type}">
        <span class="swatch" style="background:${themeColor(l.theme)}"></span>
        ${esc(themeLabel(l.theme))} — ${esc(name)}${yr}
      </label>`;
    }).join('');
    list.querySelectorAll('input').forEach(cb => cb.onchange = () => toggleLayer(cb));
  } catch (e) {
    document.getElementById('layerlist').textContent = 'No se pudieron cargar las capas.';
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

function addStyledLayer(lyrId, srcId, gtype, color) {
  if (gtype.includes('Polygon')) {
    map.addLayer({ id: lyrId, type: 'fill', source: srcId, paint: { 'fill-color': color, 'fill-opacity': 0.35 } });
    map.addLayer({ id: lyrId + '_outline', type: 'line', source: srcId, paint: { 'line-color': color, 'line-width': 0.8 } });
  } else if (gtype.includes('LineString')) {
    map.addLayer({ id: lyrId, type: 'line', source: srcId, paint: { 'line-color': color, 'line-width': 1.4 } });
  } else {
    map.addLayer({ id: lyrId, type: 'circle', source: srcId, paint: { 'circle-radius': 4, 'circle-color': color, 'circle-stroke-color': '#fff', 'circle-stroke-width': 1 } });
  }
}

map.on('load', loadLayerList);

// ---------------------------------------------------------------------------
// Click the map -> which municipio + hazards apply here, and ask about it.
// ---------------------------------------------------------------------------
let locMarker = null;
map.on('click', async (e) => {
  const { lng, lat } = e.lngLat;
  let info;
  try {
    info = await (await fetch(`/locate?lng=${lng}&lat=${lat}`)).json();
  } catch (err) { return; }
  if (locMarker) locMarker.remove();
  locMarker = new maplibregl.Marker({ color: '#0b5d4b' }).setLngLat([lng, lat]).addTo(map);

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

  setTimeout(() => {
    const b = document.getElementById('askhere');
    if (b) b.onclick = () => {
      activeLocation = info.municipio;  // scope subsequent questions to this town
      renderLoc();
      q.value = `What are the flood and landslide risks and planning rules in ${muni}?`;
      popup.remove();
      ask();
    };
  }, 30);
});
