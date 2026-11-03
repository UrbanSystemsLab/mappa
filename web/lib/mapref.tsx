'use client';

// A handle on the map for things outside it - an answer zooming to a place and
// marking what it found. MapView sets it once the map has loaded.
import { createContext, useContext, useRef, type MutableRefObject } from 'react';
import type { Map as MLMap, GeoJSONSource } from 'maplibre-gl';
import { prefersCalm } from './map';

type Ref = MutableRefObject<MLMap | null>;
const Ctx = createContext<Ref | null>(null);

export function MapRefProvider({ children }: { children: React.ReactNode }) {
  const ref = useRef<MLMap | null>(null);
  return <Ctx.Provider value={ref}>{children}</Ctx.Provider>;
}
export function useMapRef(): Ref {
  const v = useContext(Ctx);
  if (!v) throw new Error('useMapRef outside MapRefProvider');
  return v;
}

// Fly to a box [w, s, e, n]. A place stays at municipio scale; features found
// can be shown close up.
export function focusBBox(map: MLMap | null, bbox?: number[] | null, maxZoom = 11) {
  if (!map || !bbox || bbox.length !== 4) return;
  map.fitBounds([[bbox[0], bbox[1]], [bbox[2], bbox[3]]],
                { padding: 60, duration: prefersCalm() ? 0 : 1600, maxZoom });
}

export interface Found { name?: string; lng: number; lat: number }

// The features an answer found, drawn above every layer with their names. Each
// answer replaces the last answer's.
export function showFound(map: MLMap | null, found: Found[]) {
  if (!map) return;
  const data = {
    type: 'FeatureCollection' as const,
    features: found.map(f => ({ type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: [f.lng, f.lat] },
                                properties: { name: f.name || '' } })),
  };
  const apply = () => {
    const src = map.getSource('found') as GeoJSONSource | undefined;
    if (src) src.setData(data);
    else {
      map.addSource('found', { type: 'geojson', data });
      map.addLayer({ id: 'found', type: 'circle', source: 'found', paint: {
        'circle-radius': 7, 'circle-color': '#ffd400', 'circle-stroke-color': '#1a1a1a', 'circle-stroke-width': 2 } });
      map.addLayer({ id: 'found_label', type: 'symbol', source: 'found', layout: {
        'text-field': ['get', 'name'], 'text-size': 12, 'text-offset': [0, 1.1], 'text-anchor': 'top',
        'text-font': ['Noto Sans Regular'] },
        paint: { 'text-color': '#1a1a1a', 'text-halo-color': '#fff', 'text-halo-width': 1.5 } });
    }
    map.moveLayer('found'); map.moveLayer('found_label');
  };
  map.isStyleLoaded() ? apply() : map.once('load', apply);
}
