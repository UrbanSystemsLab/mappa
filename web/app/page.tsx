import dynamic from 'next/dynamic';

// The map needs the browser (WebGL), so it is not rendered on the server.
const MapView = dynamic(() => import('@/components/MapView'), { ssr: false });

export default function Home() {
  return (
    <main className="shell">
      <header className="top">
        <span className="brand">Mappa</span>
        <span className="tag">Planning &amp; hazard assistant for Puerto Rico</span>
      </header>
      <section className="map">
        <MapView />
      </section>
    </main>
  );
}
