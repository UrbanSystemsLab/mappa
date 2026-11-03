// The background map, the same as the current site: OpenFreeMap's full-colour
// street style, no key and no per-view billing.
export const BASEMAP_STYLE = 'https://tiles.openfreemap.org/styles/liberty';

// Where the map settles, and where it starts before flying in.
export const HOME = { longitude: -66.25, latitude: 18.22, zoom: 8.3 };
export const WORLD = { longitude: -45, latitude: 22, zoom: 1.3 };

export const prefersCalm = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
