'use client';

// Puts the active layers on the map and keeps them in step with the panel:
// added, removed, shown or hidden, faded in, and stacked by kind - areas at the
// bottom, then boundaries, lines and points - then by the order the user added
// them or brought them to the front.
import { useEffect } from 'react';
import { useMap } from 'react-map-gl/maplibre';
import type { Map as MLMap } from 'maplibre-gl';
import { API_ORIGIN } from '@/lib/api';
import { DRAW_ORDER, kindOf } from '@/lib/catalog';
import { useLayers, type ActiveLayer } from '@/lib/layers';
import { prefersCalm } from '@/lib/map';

const AREA_FILL = 0.3;
const OUTLINE = ['interpolate', ['linear'], ['zoom'], 8, 0.2, 12, 0.6, 15, 1.2];
const BOUNDARY = ['interpolate', ['linear'], ['zoom'], 8, 0.9, 12, 1.5, 15, 2.2];

// The fade ("…-transition") paint settings work in MapLibre but are missing
// from its TypeScript types, so layer specs pass through this.
type LayerSpec = Parameters<MLMap['addLayer']>[0];
const spec = (s: object) => s as LayerSpec;

const SRC = (id: string) => `src_${id}`;
const LYR = (id: string) => `lyr_${id}`;

// Data is drawn beneath the background map's place names, points above them.
function labelAnchor(map: MLMap): string | undefined {
  return map.getStyle()?.layers?.find(l => l.type === 'symbol')?.id;
}

function addOne(map: MLMap, a: ActiveLayer, fade: { duration: number; delay: number }) {
  const l = a.layer;
  if (!l.tiles_url || map.getLayer(LYR(l.id))) return;
  if (!map.getSource(SRC(l.id))) {
    const base = API_ORIGIN || window.location.origin;
    map.addSource(SRC(l.id), {
      type: 'vector',
      tiles: [base + l.tiles_url],
      minzoom: l.min_zoom ?? 0,
      maxzoom: l.max_zoom ?? 14,
    });
  }
  const common = { source: SRC(l.id), 'source-layer': 'layer' };
  const kind = kindOf(l);
  const under = labelAnchor(map);
  // Everything starts invisible and fades to its level once on the map.
  if (kind === 'area' || kind === 'boundary') {
    map.addLayer(spec({ id: LYR(l.id), type: 'fill', ...common,
      paint: { 'fill-color': a.colour, 'fill-opacity': 0, 'fill-opacity-transition': fade } }), under);
    map.addLayer(spec({ id: `${LYR(l.id)}_ln`, type: 'line', ...common,
      paint: { 'line-color': a.colour, 'line-width': (kind === 'boundary' ? BOUNDARY : OUTLINE) as never,
               'line-opacity': 0, 'line-opacity-transition': fade } }), under);
  } else if (kind === 'line') {
    map.addLayer(spec({ id: LYR(l.id), type: 'line', ...common,
      paint: { 'line-color': a.colour, 'line-width': 1.4, 'line-opacity': 0,
               'line-opacity-transition': fade } }), under);
  } else {
    map.addLayer(spec({ id: LYR(l.id), type: 'circle', ...common,
      paint: { 'circle-radius': 5, 'circle-color': a.colour, 'circle-opacity': 0,
               'circle-stroke-color': '#fff', 'circle-stroke-width': 1.5, 'circle-stroke-opacity': 0,
               'circle-opacity-transition': fade, 'circle-stroke-opacity-transition': fade } }));
  }
}

function removeOne(map: MLMap, id: string) {
  [LYR(id), `${LYR(id)}_ln`].forEach(x => map.getLayer(x) && map.removeLayer(x));
  if (map.getSource(SRC(id))) map.removeSource(SRC(id));
}

function restyle(map: MLMap, active: ActiveLayer[]) {
  const ordered = [...active].sort(
    (a, b) => DRAW_ORDER[kindOf(a.layer)] - DRAW_ORDER[kindOf(b.layer)] || a.order - b.order,
  );
  for (const a of ordered) {
    const id = LYR(a.layer.id);
    const ln = `${id}_ln`;
    const vis = a.hidden ? 'none' : 'visible';
    [id, ln].forEach(x => map.getLayer(x) && map.setLayoutProperty(x, 'visibility', vis));
    const type = map.getLayer(id)?.type;
    const boundary = kindOf(a.layer) === 'boundary';
    if (type === 'fill') map.setPaintProperty(id, 'fill-opacity', boundary ? 0 : AREA_FILL);
    if (type === 'line') map.setPaintProperty(id, 'line-opacity', 0.9);
    if (type === 'circle') {
      map.setPaintProperty(id, 'circle-opacity', 1);
      map.setPaintProperty(id, 'circle-stroke-opacity', 1);
    }
    if (map.getLayer(ln)) map.setPaintProperty(ln, 'line-opacity', boundary ? 0.9 : 0.7);
    // Re-assert the stacking: each moved to just under the place names, in order.
    const under = type === 'circle' ? undefined : labelAnchor(map);
    [id, ln].forEach(x => map.getLayer(x) && map.moveLayer(x, under));
  }
}

export default function MapLayers() {
  const { current } = useMap();
  const { active } = useLayers();

  useEffect(() => {
    const map = current?.getMap();
    if (!map) return;
    const sync = () => {
      const fade = { duration: prefersCalm() ? 0 : 600, delay: 0 };
      const want = new Set(active.map(a => a.layer.id));
      // Layers this component added that are no longer active.
      map.getStyle().layers?.forEach(l => {
        const m = /^lyr_(.+?)(_ln)?$/.exec(l.id);
        if (m && !want.has(m[1])) removeOne(map, m[1]);
      });
      active.forEach(a => addOne(map, a, fade));
      // A frame later, so the map has drawn them at 0 and the change can fade in.
      requestAnimationFrame(() => restyle(map, active));
    };
    if (map.isStyleLoaded()) sync();
    else map.once('load', sync);
  }, [current, active]);

  return null;
}
