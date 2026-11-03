'use client';

import type { CatalogLayer } from '@/lib/catalog';
import { useLayers } from '@/lib/layers';

// A layer's provenance: what it is, who made it, when, and how sure La Maraña is.
const STATUS: Record<string, { es: string; en: string }> = {
  confirmed: { es: 'confirmado', en: 'confirmed' }, inferred: { es: 'inferido', en: 'inferred' },
  reconstructed: { es: 'reconstruido', en: 'reconstructed' }, unknown: { es: 'desconocido', en: 'unknown' },
};

export default function LayerAbout({ layer, onClose }: { layer: CatalogLayer | null; onClose: () => void }) {
  const { lang } = useLayers();
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
    </div>
  );
}
