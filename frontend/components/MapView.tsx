'use client';

// The map. react-map-gl draws it with MapLibre today; switching to Mapbox later
// is a change of import ('react-map-gl/mapbox') and a token, not a rewrite.
import { useCallback, useRef, useState } from 'react';
import Map, { AttributionControl, Marker, NavigationControl, Popup, ScaleControl,
              type MapLayerMouseEvent, type MapRef } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import { API } from '@/lib/api';
import { useChat, type Pending } from '@/lib/chat';
import { useLayers } from '@/lib/layers';
import { BASEMAP_STYLE, HOME, WORLD, prefersCalm } from '@/lib/map';
import { useMapRef } from '@/lib/mapref';
import ClickPopup, { fieldLabel, isEmpty, valueLabel, type Check, type Hit } from './ClickPopup';
import MapLayers from './MapLayers';

interface Clicked { lng: number; lat: number; municipio: string | null; checks: Check[]; hits: Hit[]; pending: Pending | null }

export default function MapView() {
  const ref = useRef<MapRef>(null);
  const mapRef = useMapRef();
  const { lang, active } = useLayers();
  const { askAbout } = useChat();
  const [clicked, setClicked] = useState<Clicked | null>(null);

  // Opens on the world and flies in to Puerto Rico, so the first thing a
  // visitor sees is where they are. Straight there for reduced motion.
  const onLoad = useCallback(() => {
    const map = ref.current?.getMap() ?? null;
    mapRef.current = map;
    // Redraw at the new size when the chat is hidden or shown.
    const box = map?.getContainer().parentElement;
    if (map && box) new ResizeObserver(() => map.resize()).observe(box);
    if (prefersCalm()) return;
    ref.current?.flyTo({ center: [HOME.longitude, HOME.latitude], zoom: HOME.zoom,
                         duration: 2800, curve: 1.5, essential: false });
  }, [mapRef]);

  // One handler for every active layer: one popup listing everything under the click.
  const onClick = useCallback(async (e: MapLayerMouseEvent) => {
    const map = ref.current?.getMap();
    if (!map) return;
    const ids = active.flatMap(a => [`lyr_${a.layer.id}`, `lyr_${a.layer.id}_ln`]).filter(x => map.getLayer(x));
    const features = ids.length ? map.queryRenderedFeatures(e.point, { layers: ids }) : [];
    // One card per layer: a click often lands on a polygon and its own outline.
    const byLayer = new globalThis.Map<string, Record<string, unknown>>();
    features.forEach(f => {
      const lid = f.layer.id.replace(/^lyr_/, '').replace(/_ln$/, '');
      if (!byLayer.has(lid)) byLayer.set(lid, (f.properties || {}) as Record<string, unknown>);
    });
    const hits: Hit[] = [...byLayer.entries()]
      .map(([lid, props]) => ({ layer: active.find(a => a.layer.id === lid)!, props }))
      .filter(h => h.layer);

    const { lng, lat } = e.lngLat;
    let info: { municipio?: string | null; hazards?: Check[] } = {};
    try { info = await (await fetch(`${API}/locate?lng=${lng}&lat=${lat}`)).json(); } catch { /* empty ground */ }
    const municipio = info.municipio || null;
    const checks = Array.isArray(info.hazards) ? info.hazards : [];
    const es = lang === 'es';
    // The values the cards show, sent with the question so the answer can say
    // what is at this spot, in the same words the popup used.
    const shown = hits.map(({ layer: a, props }) => {
      const values: Record<string, string> = {};
      (a.layer.tile_properties_order || Object.keys(props)).filter(k => k !== 'id' && !isEmpty(props[k])).slice(0, 8)
        .forEach(k => { values[fieldLabel(a.layer, k, lang)] = valueLabel(a.layer, props[k], lang); });
      return { layer: a.layer.name, values };
    });
    const pending: Pending | null = municipio ? {
      municipio, spatial: { ...info, lng, lat, features: shown },
      here: hits.map(h => h.layer.layer.name),
      on: active.map(a => a.layer.name),
      inside: checks.filter(c => c.inside).map(c => (es ? c.name_es : c.name_en) || c.key),
    } : null;
    setClicked({ lng, lat, municipio, checks, hits, pending });
  }, [active, lang]);

  return (
    <Map
      ref={ref}
      initialViewState={prefersCalm() ? HOME : WORLD}
      mapStyle={BASEMAP_STYLE}
      onLoad={onLoad}
      onClick={onClick}
      attributionControl={false}
      style={{ width: '100%', height: '100%' }}
    >
      <AttributionControl compact />
      <NavigationControl position="top-right" showCompass={false} />
      <ScaleControl position="bottom-left" unit="metric" maxWidth={110} />
      <MapLayers />
      {clicked && <Marker longitude={clicked.lng} latitude={clicked.lat} color="#09814A" />}
      {clicked && (
        <Popup longitude={clicked.lng} latitude={clicked.lat} maxWidth="290px" closeOnClick={false}
               onClose={() => setClicked(null)}>
          <ClickPopup lang={lang} municipio={clicked.municipio} checks={clicked.checks} hits={clicked.hits}
                      onAsk={() => { if (clicked.pending) { askAbout(clicked.pending); setClicked(null); } }} />
        </Popup>
      )}
    </Map>
  );
}
