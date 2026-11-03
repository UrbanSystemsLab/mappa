// The layer catalogue, read from the API. Nothing about a layer is hardcoded:
// names, categories and sources come from /catalog, as on the current site.
import { API } from './api';

export type Lang = 'es' | 'en';

export interface CatalogLayer {
  id: string;
  name: string;
  description?: string | null;
  category: string;
  category_source?: string | null;
  theme?: string | null;
  geometry_type?: string | null;
  feature_count?: number | null;
  min_zoom?: number | null;
  max_zoom?: number | null;
  tiles_url?: string | null;
  available?: boolean;
  source?: { agency?: string | null; inventory?: string | null; year?: number | null;
             metadata_status?: string | null };
  property_labels?: Record<string, { en?: string; es?: string }>;
  value_labels?: Record<string, { en?: string; es?: string }>;
  tile_properties_order?: string[];
}

export interface Category { category: string; available: number; count: number }

export async function fetchCategories(lang: Lang): Promise<Category[]> {
  const r = await fetch(`${API}/catalog/categories?lang=${lang}&available_only=true`);
  return r.json();
}

export async function fetchLayers(lang: Lang, q = ''): Promise<CatalogLayer[]> {
  const p = new URLSearchParams({ lang, limit: '700', available_only: 'true' });
  if (q) p.set('q', q);
  const d = await (await fetch(`${API}/catalog/layers?${p}`)).json();
  return d.layers || [];
}

// Category headings. Where La Maraña's prioritization matrix names a category
// in English, their word is used.
const CATS: Record<string, { es: string; en: string }> = {
  Riesgos: { es: 'Riesgos', en: 'Hazards' },
  'Conservación': { es: 'Conservación', en: 'Conservation' },
  'Geología': { es: 'Geología', en: 'Geology' },
  'Hidrografía': { es: 'Hidrografía', en: 'Hydrography' },
  Recreacion: { es: 'Recreación', en: 'Recreation' },
  Infraestructura: { es: 'Infraestructura', en: 'Infrastructure' },
  'Uso Suelo': { es: 'Uso de suelo', en: 'Soil Use' },
  Ambiente: { es: 'Ambiente', en: 'Environment' },
  'Desarrollo Económico': { es: 'Desarrollo Económico', en: 'Economic Development' },
  Electricidad: { es: 'Electricidad', en: 'Electricity' },
  'Límites': { es: 'Límites', en: 'Boundaries' },
  'Límites geográficos': { es: 'Límites geográficos', en: 'Geographic Boundaries' },
  'Planificación': { es: 'Planificación', en: 'Planning' },
  Servicios: { es: 'Servicios', en: 'Services' },
  Transportacion: { es: 'Transportación', en: 'Transportation' },
  'Otras capas': { es: 'Otras capas', en: 'Other layers' },
  Otros: { es: 'Otros', en: 'Other' },
};
export const catLabel = (c: string, lang: Lang) => CATS[c]?.[lang] ?? c;

// How a layer is drawn, so several stay readable together without settings:
// boundaries as outlines, areas with one light fill, lines and points above.
export type Kind = 'area' | 'boundary' | 'line' | 'point';
const isBoundary = (l: CatalogLayer) =>
  l.theme === 'political' ||
  /bound|l[ií]mite|division|divisi[oó]n/i.test(`${l.category || ''} ${l.category_source || ''}`);
export function kindOf(l: CatalogLayer): Kind {
  const g = (l.geometry_type || '').toLowerCase();
  if (g.includes('point')) return 'point';
  if (g.includes('line')) return 'line';
  return isBoundary(l) ? 'boundary' : 'area';
}
export const DRAW_ORDER: Record<Kind, number> = { area: 0, boundary: 1, line: 2, point: 3 };

// One colour per layer on screen, never red: red reads as danger on a hazard map.
export const LAYER_COLOURS = ['#2b6cb0', '#d97706', '#0f8b8d', '#7c3aed', '#c2410c',
                              '#4d7c0f', '#be185d', '#475569', '#a16207', '#0e7490'];
