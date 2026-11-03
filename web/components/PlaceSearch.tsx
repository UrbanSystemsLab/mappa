'use client';

// Find a municipio or barrio and fly there. Searching for a place also scopes
// the conversation to it.
import { useEffect, useState } from 'react';
import { API } from '@/lib/api';
import { useChat } from '@/lib/chat';
import { useLayers } from '@/lib/layers';
import { focusBBox, useMapRef } from '@/lib/mapref';

interface Place { name: string; label?: string; parent?: string; type: string; bbox: number[] }

export default function PlaceSearch() {
  const { lang } = useLayers();
  const { setLocation } = useChat();
  const mapRef = useMapRef();
  const [q, setQ] = useState('');
  const [rows, setRows] = useState<Place[]>([]);
  const es = lang === 'es';

  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) { setRows([]); return; }
    const t = setTimeout(async () => {
      try { setRows(await (await fetch(`${API}/places?q=${encodeURIComponent(term)}`)).json()); }
      catch { setRows([]); }
    }, 220);
    return () => clearTimeout(t);
  }, [q]);

  const kind = (t: string) => t === 'municipio' ? (es ? 'Municipio' : 'Municipality')
    : t === 'comunidad' ? (es ? 'Comunidad' : 'Community') : 'Barrio';

  return (
    <div className="mapsearch">
      <input id="placeq" type="search" autoComplete="off" value={q} onChange={e => setQ(e.target.value)}
             onKeyDown={e => { if (e.key === 'Escape') { setQ(''); setRows([]); } }}
             onBlur={() => setTimeout(() => setRows([]), 160)}
             placeholder={es ? 'Buscar municipio o barrio…' : 'Search municipality or barrio…'}
             aria-label={es ? 'Buscar lugar' : 'Search place'} />
      <div id="placeres" className={`placeres${rows.length ? ' on' : ''}`}>
        {rows.map(r => (
          <button key={`${r.type}-${r.name}-${r.parent}`} onMouseDown={e => e.preventDefault()} onClick={() => {
            focusBBox(mapRef.current, r.bbox);
            setLocation(r.label || r.name);
            setQ(r.label || r.name); setRows([]);
          }}>
            <span>{r.name}{r.parent && r.type !== 'municipio' ? <span className="sub">, {r.parent}</span> : null}</span>
            <span className="kind">{kind(r.type)}</span>
          </button>))}
      </div>
    </div>
  );
}
