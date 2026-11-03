'use client';

// The page, in the same structure and class names as the current site
// (frontend/index.html), so its stylesheet applies unchanged.
import dynamic from 'next/dynamic';
import { useState } from 'react';
import type { CatalogLayer } from '@/lib/catalog';
import { ChatProvider } from '@/lib/chat';
import { LayersProvider, useLayers } from '@/lib/layers';
import { MapRefProvider } from '@/lib/mapref';
import ChatPanel from './ChatPanel';
import PlaceSearch from './PlaceSearch';
import LayerAbout from './LayerAbout';
import LayerPanel from './LayerPanel';
import Legend from './Legend';

// The map needs the browser (WebGL), so it is not rendered on the server.
const MapView = dynamic(() => import('./MapView'), { ssr: false });

function Topbar({ onChat }: { onChat: () => void }) {
  const { lang, setLang } = useLayers();
  return (
    <div className="topbar">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <span className="brand" translate="no"><img src="/logo.png" alt="" width={32} height={32} />Mappa</span>
      <span className="tag">{lang === 'es' ? 'Asistente de planificación y riesgos de Puerto Rico'
                                           : 'Planning & hazard assistant for Puerto Rico'}</span>
      <button id="chattoggle" className="chattog" onClick={onChat}
              title={lang === 'es' ? 'Mostrar/ocultar chat' : 'Show/hide chat'}>&#9776;</button>
      <span className="langtog">
        {(['es', 'en'] as const).map(l => (
          <a key={l} className={lang === l ? 'on' : ''} role="button" tabIndex={0} aria-pressed={lang === l}
             onClick={() => setLang(l)} onKeyDown={e => e.key === 'Enter' && setLang(l)}>{l.toUpperCase()}</a>
        ))}
      </span>
    </div>
  );
}

export default function App() {
  const [about, setAbout] = useState<CatalogLayer | null>(null);
  const [chatHidden, setChatHidden] = useState(false);
  return (
    <LayersProvider><MapRefProvider><ChatProvider>
      <Topbar onChat={() => setChatHidden(h => !h)} />
      <main className={chatHidden ? 'chat-hidden' : undefined}>
        <ChatPanel />
        <section className="mappanel">
          <div id="map"><MapView /></div>
          <PlaceSearch />
          <Legend />
          <LayerPanel onAbout={setAbout} about={<LayerAbout layer={about} onClose={() => setAbout(null)} />} />
        </section>
      </main>
    </ChatProvider></MapRefProvider></LayersProvider>
  );
}
