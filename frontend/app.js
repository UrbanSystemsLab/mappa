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

document.querySelectorAll('.samples a').forEach(a => {
  a.onclick = () => { q.value = a.dataset.q; ask(); };
});

btn.onclick = ask;

async function ask() {
  const question = q.value.trim();
  if (!question) return;
  btn.disabled = true; out.innerHTML = '<p>Consultando…</p>';
  try {
    const r = await fetch('/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question}),
    });
    const d = await r.json();
    const layers = (d.suggested_layers || []).map(l => `<span class="tag">${l}</span>`).join('');
    const cites = (d.citations || []).map(c =>
      `<div class="cite">• <a href="${c.url}" target="_blank">${c.title}</a> (${c.year})</div>`
    ).join('');
    out.innerHTML = `
      <div class="answer">${escape(d.answer_es)}</div>
      <div class="meta">Confianza: <b>${d.confidence}</b> ${layers}</div>
      <h4>Fuentes</h4>${cites || '<i>Sin fuentes</i>'}`;
    disc.textContent = d.disclaimer;
  } catch (e) {
    out.innerHTML = `<p style="color:red">Error: ${e.message}</p>`;
  } finally {
    btn.disabled = false;
  }
}
function escape(s) { return s.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
