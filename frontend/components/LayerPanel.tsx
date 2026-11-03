'use client';

// The layer panel, in the current site's markup: search, the layers on the map
// (pinned at the top), and the catalogue by category.
import { useEffect, useMemo, useState } from 'react';
import { catLabel, fetchCategories, fetchLayers, type CatalogLayer, type Category } from '@/lib/catalog';
import { useLayers } from '@/lib/layers';
import { Close, Eye, EyeOff } from './Icons';

export default function LayerPanel({ onAbout, about }: { onAbout: (l: CatalogLayer) => void; about: React.ReactNode }) {
  const { lang, active, isOn, add, remove, toggle, toFront, clear } = useLayers();
  const es = lang === 'es';
  const [cats, setCats] = useState<Category[]>([]);
  const [layers, setLayers] = useState<CatalogLayer[] | null>(null);
  const [q, setQ] = useState('');
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [error, setError] = useState(false);

  useEffect(() => { fetchCategories(lang).then(setCats).catch(() => setError(true)); }, [lang]);
  useEffect(() => {
    const t = setTimeout(() => fetchLayers(lang, q.trim()).then(setLayers).catch(() => setError(true)), 250);
    return () => clearTimeout(t);
  }, [lang, q]);

  const byCat = useMemo(() => {
    const m = new Map<string, CatalogLayer[]>();
    (layers || []).filter(l => !isOn(l.id)).forEach(l => m.set(l.category, [...(m.get(l.category) || []), l]));
    return m;
  }, [layers, isOn]);
  const order = cats.length ? cats.map(c => c.category).filter(c => byCat.has(c)) : [...byCat.keys()];
  const frontId = active.length ? active[active.length - 1].layer.id : null;
  const flip = (c: string) => setOpen(s => { const n = new Set(s); n.has(c) ? n.delete(c) : n.add(c); return n; });

  return (
    <aside id="layerctl">
      <div className="h"><span>{es ? 'Capas del mapa' : 'Map layers'}</span></div>
      <input id="lyrq" className="lyrq" type="search" autoComplete="off" value={q}
             onChange={e => setQ(e.target.value)} placeholder={es ? 'Buscar capas…' : 'Search layers…'} />
      <div id="layerlist">
        {error ? (es ? 'No se pudieron cargar las capas.' : 'Could not load layers.')
          : layers === null ? (es ? 'Cargando capas…' : 'Loading layers…') : null}

        {active.length > 0 && (
          <div className="lsec">
            <div className="lsec-h">
              <span>{es ? 'Activas' : 'Active'} ({active.length})</span>
              <a role="button" tabIndex={0} onClick={clear}>{es ? 'Quitar todas' : 'Clear all'}</a>
            </div>
            {[...active].reverse().map(a => (
              <div key={a.layer.id} className={`arow${a.hidden ? ' hid' : ''}`}>
                <div className="arow-top">
                  <span className="sw" style={{ background: a.colour }} />
                  <span className="nm">{a.layer.name}</span>
                  <button className="ic eye" onClick={() => toggle(a.layer.id)} aria-pressed={!a.hidden}
                          title={a.hidden ? (es ? 'Mostrar' : 'Show') : (es ? 'Ocultar' : 'Hide')}>
                    {a.hidden ? <EyeOff /> : <Eye />}
                  </button>
                  <button className="ic rm" onClick={() => remove(a.layer.id)}
                          title={es ? 'Quitar del mapa' : 'Remove from map'}><Close /></button>
                </div>
                <div className="arow-ctl">
                  {active.length > 1 && a.layer.id !== frontId && (
                    <button className="lk" onClick={() => toFront(a.layer.id)}>{es ? 'Traer al frente' : 'Bring to front'}</button>
                  )}
                  <button className="lk" onClick={() => onAbout(a.layer)}>{es ? 'Acerca de' : 'About'}</button>
                </div>
              </div>
            ))}
          </div>
        )}

        {order.map(c => {
          const rows = byCat.get(c) || [];
          const isOpen = open.has(c) || !!q;
          return (
            <div className="lsec" key={c}>
              <div className="lsec-h clickable" role="button" tabIndex={0} aria-expanded={isOpen}
                   onClick={() => flip(c)} onKeyDown={e => e.key === 'Enter' && flip(c)}>
                <span>{isOpen ? '▾' : '▸'} {catLabel(c, lang)}</span>
                <span className="cnt">{rows.filter(r => r.available !== false).length}</span>
              </div>
              {isOpen && rows.map(l => (
                <div key={l.id} className="lrow" role="button" tabIndex={0}
                     onClick={() => add(l)} onKeyDown={e => e.key === 'Enter' && add(l)}>
                  <span className="sw" style={{ background: '#c3cbd3' }} />
                  <span className="nm">{l.name}<span className="yr">{l.source?.year ? ` · ${l.source.year}` : ''}</span></span>
                  <button className="ic info" title={es ? 'Sobre esta capa' : 'About this layer'}
                          onClick={e => { e.stopPropagation(); onAbout(l); }}>i</button>
                  <button className="ic add" onClick={e => { e.stopPropagation(); add(l); }}>+</button>
                </div>
              ))}
            </div>
          );
        })}
      </div>
      {about}
    </aside>
  );
}
