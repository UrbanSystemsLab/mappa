'use client';

import { useLayers } from '@/lib/layers';

// What is on the map, and where it came from - every source on screen, once.
export default function Legend() {
  const { lang, active } = useLayers();
  const shown = active.filter(a => !a.hidden);
  if (!shown.length) return null;
  const sources = [...new Set(shown.map(a => a.layer.source?.inventory).filter(Boolean))];
  return (
    <div id="legend" className="legend" style={{ display: 'block' }}>
      <div className="lg-h">{lang === 'es' ? 'Leyenda' : 'Legend'}</div>
      {shown.map(a => (
        <div className="lg-r" key={a.layer.id}><span className="lg-k" style={{ background: a.colour }} /><span>{a.layer.name}</span></div>
      ))}
      {sources.length > 0 && <div className="lg-src">{lang === 'es' ? 'Fuente' : 'Source'}: {sources.join(' · ')}</div>}
    </div>
  );
}
