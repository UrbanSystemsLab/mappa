'use client';

// What a click shows: the place and its hazard checks, then one card per layer
// under the click, labelled in La Maraña's words. Same markup as the current site.
import type { CatalogLayer, Lang } from '@/lib/catalog';
import type { ActiveLayer } from '@/lib/layers';

// -9999 is GIS data's code for "no value here".
const NO_VALUE = new Set(['-9999', '-9999.0', '-99999', '-999', '-999.0']);
export const isEmpty = (v: unknown) =>
  v === null || v === undefined || String(v).trim() === '' || NO_VALUE.has(String(v).trim());

export function fieldLabel(rec: CatalogLayer | undefined, key: string, lang: Lang) {
  const m = rec?.property_labels || {};
  const l = m[key] || m[key.toLowerCase()];
  return l ? (l[lang] || l.en || key) : key.replace(/_/g, ' ');
}
export function valueLabel(rec: CatalogLayer | undefined, val: unknown, lang: Lang) {
  const m = rec?.value_labels || {};
  const l = m[String(val)] || m[String(val).toUpperCase()];
  return l ? (l[lang] || l.en || String(val)) : String(val);
}

export interface Check { key: string; name_es?: string; name_en?: string; inside: boolean }
export interface Hit { layer: ActiveLayer; props: Record<string, unknown> }

export default function ClickPopup({ lang, municipio, checks, hits, onAsk }: {
  lang: Lang; municipio: string | null; checks: Check[]; hits: Hit[]; onAsk: () => void;
}) {
  const es = lang === 'es';
  return (
    <>
      <div className="fp-card fp-place">
        <div className="fp-h">📍 {municipio || (es ? 'Fuera de Puerto Rico' : 'Outside Puerto Rico')}</div>
        <table className="fp"><tbody>
          {checks.map(c => (
            <tr key={c.key}><th>{(es ? c.name_es : c.name_en) || c.key}</th>
              <td>{c.inside ? <b className="yes">{es ? 'Sí' : 'Yes'}</b> : <span className="no">No</span>}</td></tr>))}
        </tbody></table>
        <button className="askbtn" onClick={onAsk} disabled={!municipio}>
          {es ? 'Preguntar sobre este lugar' : 'Ask about this place'}</button>
      </div>
      {hits.map(({ layer: a, props }) => {
        const rec = a.layer;
        const keys = (rec.tile_properties_order || Object.keys(props)).filter(k => k !== 'id' && !isEmpty(props[k]));
        return (
          <div className="fp-card" key={rec.id}>
            <div className="fp-h"><span className="fp-sw" style={{ background: a.colour }} />{rec.name}
              {rec.source?.year ? ` · ${rec.source.year}` : ''}</div>
            {keys.length ? (
              <dl className="fv">{keys.map(k => (
                <div key={k}><dt>{fieldLabel(rec, k, lang)}</dt><dd>{valueLabel(rec, props[k], lang)}</dd></div>))}</dl>
            ) : <div className="fp-none">{es ? 'Sin atributos' : 'No attributes'}</div>}
          </div>);
      })}
    </>
  );
}
