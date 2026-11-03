'use client';

// Which layers are on the map, shared by the panel, the map and the legend.
import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { LAYER_COLOURS, type CatalogLayer, type Lang } from './catalog';

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

  const value = useMemo<LayersState>(() => ({
    lang, setLang, active: [...active].sort((a, b) => a.order - b.order),
    isOn: id => active.some(a => a.layer.id === id), add, remove, toggle, toFront, clear,
  }), [lang, active, add, remove, toggle, toFront, clear]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLayers(): LayersState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useLayers outside LayersProvider');
  return v;
}
