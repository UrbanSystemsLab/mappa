'use client';

import { useEffect, useState } from 'react';
import { API } from '@/lib/api';
import type { CatalogLayer } from '@/lib/catalog';
import { useLayers } from '@/lib/layers';

interface LayerDocument { title: string; year?: number | null; passages: number }

// A layer's provenance: what it is, who made it, when, and how sure La Maraña is.
const STATUS: Record<string, { es: string; en: string }> = {
  confirmed: { es: 'confirmado', en: 'confirmed' }, inferred: { es: 'inferido', en: 'inferred' },
  reconstructed: { es: 'reconstruido', en: 'reconstructed' }, unknown: { es: 'desconocido', en: 'unknown' },
};

export default function LayerAbout({ layer, onClose }: { layer: CatalogLayer | null; onClose: () => void }) {
  const { lang } = useLayers();
  // The documents that discuss this layer come with its full record.
  const [docs, setDocs] = useState<LayerDocument[]>([]);
  useEffect(() => {
    setDocs([]);
    if (!layer) return;
    let live = true;
    fetch(`${API}/catalog/layers/${encodeURIComponent(layer.id)}?lang=${lang}`)
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (live && d?.documents) setDocs(d.documents); })
      .catch(() => {});
    return () => { live = false; };
  }, [layer, lang]);
  if (!layer) return null;
  const es = lang === 'es';
  const s = layer.source || {};
  const st = s.metadata_status ? (STATUS[s.metadata_status]?.[lang] ?? s.metadata_status) : null;
  return (
    <div className="layerinfo" style={{ display: 'block' }} role="dialog" aria-label={layer.name}>
      <div className="li-h"><b>{layer.name}</b><button className="ic" onClick={onClose} aria-label={es ? 'Cerrar' : 'Close'}>×</button></div>
      {layer.description && layer.description !== 'Not provided' && <p>{layer.description}</p>}
      <dl>
        <dt>{es ? 'Agencia' : 'Agency'}</dt><dd>{s.agency || '—'}</dd>
        <dt>{es ? 'Año' : 'Year'}</dt><dd>{s.year || '—'}</dd>
        <dt>{es ? 'Elementos' : 'Features'}</dt><dd>{(layer.feature_count || 0).toLocaleString()}</dd>
        <dt>{es ? 'Procedencia' : 'Provenance'}</dt><dd>{s.inventory || '—'}</dd>
        {st && <><dt>{es ? 'Evaluación de La Maraña' : 'La Maraña rating'}</dt><dd>{st}</dd></>}
      </dl>
      {docs.length > 0 && (
        <div className="li-docs">
          <div className="cites-h">{es ? 'Documentos que tratan esta capa' : 'Documents that discuss this layer'}</div>
          {docs.map(d => (
            <div className="cite" key={d.title}>📄 <span className="ct">{d.title}</span>{d.year ? ` · ${d.year}` : ''}</div>))}
        </div>)}
    </div>
  );
}
