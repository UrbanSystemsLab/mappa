'use client';

// Which layers are on the map, shared by the panel, the map and the legend.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { API } from './api';
import { LAYER_COLOURS, type CatalogLayer, type Lang } from './catalog';

async function layerById(id: string, lang: Lang): Promise<CatalogLayer | null> {
  try {
    const l = await (await fetch(`${API}/catalog/layers/${id}?lang=${lang}`)).json();
    return l && l.tiles_url ? l : null;
  } catch { return null; }
}

export interface ActiveLayer { layer: CatalogLayer; colour: string; hidden: boolean; order: number }

interface LayersState {
  lang: Lang;
  setLang: (l: Lang) => void;
  active: ActiveLayer[];                      // in the order they were added or raised
  isOn: (id: string) => boolean;
  add: (l: CatalogLayer) => void;
  remove: (id: string) => void;
  toggle: (id: string) => void;
  toFront: (id: string) => void;
  clear: () => void;
  // Layers an answer turns on. The previous answer's go, never the user's own.
  autoShow: (ids: string[]) => Promise<void>;
}

const Ctx = createContext<LayersState | null>(null);

export function LayersProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLang] = useState<Lang>('es');
  const [active, setActive] = useState<ActiveLayer[]>([]);
  const [counter, setCounter] = useState(0);

  const add = useCallback((l: CatalogLayer) => {
    setActive(cur => {
      if (cur.some(a => a.layer.id === l.id)) return cur;
      const used = new Set(cur.map(a => a.colour));
      const colour = LAYER_COLOURS.find(c => !used.has(c)) ?? LAYER_COLOURS[cur.length % LAYER_COLOURS.length];
      return [...cur, { layer: l, colour, hidden: false, order: counter }];
    });
    setCounter(c => c + 1);
  }, [counter]);
  const remove = useCallback((id: string) => setActive(cur => cur.filter(a => a.layer.id !== id)), []);
  const toggle = useCallback((id: string) =>
    setActive(cur => cur.map(a => (a.layer.id === id ? { ...a, hidden: !a.hidden } : a))), []);
  const toFront = useCallback((id: string) => {
    setActive(cur => cur.map(a => (a.layer.id === id ? { ...a, order: counter } : a)));
    setCounter(c => c + 1);
  }, [counter]);
  const clear = useCallback(() => setActive([]), []);

  // A layer the user turns on or off is theirs; answers leave it alone.
  const auto = useRef<Set<string>>(new Set());
  const userAdd = useCallback((l: CatalogLayer) => { auto.current.delete(l.id); add(l); }, [add]);
  const userRemove = useCallback((id: string) => { auto.current.delete(id); remove(id); }, [remove]);
  const autoShow = useCallback(async (ids: string[]) => {
    const wanted = ids.slice(0, 3);
    [...auto.current].filter(id => !wanted.includes(id)).forEach(id => { auto.current.delete(id); remove(id); });
    for (const id of wanted) {
      if (active.some(a => a.layer.id === id)) continue;
      const l = await layerById(id, lang);
      if (l) { auto.current.add(id); add(l); }
    }
  }, [active, add, remove, lang]);

  // Names come from the server per language; refresh the layers already on.
  useEffect(() => {
    setActive(cur => { cur.forEach(a => layerById(a.layer.id, lang).then(l => l &&
      setActive(now => now.map(x => (x.layer.id === l.id ? { ...x, layer: l } : x))))); return cur; });
  }, [lang]);

  const value = useMemo<LayersState>(() => ({
    lang, setLang, active: [...active].sort((a, b) => a.order - b.order),
    isOn: id => active.some(a => a.layer.id === id), add: userAdd, remove: userRemove, toggle, toFront,
    clear, autoShow,
  }), [lang, active, userAdd, userRemove, toggle, toFront, clear, autoShow]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLayers(): LayersState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useLayers outside LayersProvider');
  return v;
}
