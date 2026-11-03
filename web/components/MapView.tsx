'use client';

// The map. react-map-gl draws it with MapLibre today; switching to Mapbox later
// is a change of import ('react-map-gl/mapbox') and a token, not a rewrite.
import { useCallback, useRef } from 'react';
import Map, { AttributionControl, NavigationControl, ScaleControl, type MapRef } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import { BASEMAP_STYLE, HOME, WORLD, prefersCalm } from '@/lib/map';
import MapLayers from './MapLayers';

export default function MapView() {
  const ref = useRef<MapRef>(null);

  // Opens on the world and flies in to Puerto Rico, so the first thing a
  // visitor sees is where they are. Straight there for reduced motion.
  const onLoad = useCallback(() => {
    if (prefersCalm()) return;
    ref.current?.flyTo({ center: [HOME.longitude, HOME.latitude], zoom: HOME.zoom,
                         duration: 2800, curve: 1.5, essential: false });
  }, []);

  return (
    <Map
      ref={ref}
      initialViewState={prefersCalm() ? HOME : WORLD}
      mapStyle={BASEMAP_STYLE}
      onLoad={onLoad}
      attributionControl={false}
      style={{ width: '100%', height: '100%' }}
    >
      <AttributionControl compact />
      <NavigationControl position="top-right" showCompass={false} />
      <ScaleControl position="bottom-left" unit="metric" maxWidth={110} />
      <MapLayers />
    </Map>
  );
}
