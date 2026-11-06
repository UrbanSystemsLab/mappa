'use client';

// The conversation: asking, the live events the server streams back, and what
// an answer does to the map - the same flow as the current site's ask().
import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import { API } from './api';
import { useLayers } from './layers';
import { focusBBox, showFound, useMapRef, type Found } from './mapref';
import { prefersCalm } from './map';

export interface Citation { kind?: string; title: string; source?: string; year?: number; doc_id?: string }
export interface Turn {
  question: string; answer: string; shown: number | null;  // shown: characters revealed so far
  steps: string[]; citations: Citation[];
  next: string[];  // questions the reader might ask next
}
// What a click found at a spot, for "Ask about this place".
export interface Pending {
  municipio: string; spatial: Record<string, unknown>;
  here: string[]; on: string[]; inside: string[];
}

interface ChatState {
  turns: Turn[]; busy: boolean; disclaimer: string;
  location: string | null; setLocation: (m: string | null, spatial?: Record<string, unknown> | null) => void;
  ask: (question: string, at?: { location: string; spatial: Record<string, unknown> }) => void; askAbout: (p: Pending) => void; clear: () => void;
}
const Ctx = createContext<ChatState | null>(null);

export function ChatProvider({ children }: { children: React.ReactNode }) {
  const { lang, active, autoShow } = useLayers();
  const mapRef = useMapRef();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [disclaimers, setDisclaimers] = useState<Record<string, string>>({});
  const [location, setLoc] = useState<string | null>(null);
  const spatial = useRef<Record<string, unknown> | null>(null);

  const setLocation = useCallback((m: string | null, sp: Record<string, unknown> | null = null) => {
    setLoc(m); spatial.current = m ? sp : null;
  }, []);
  const update = (i: number, f: (t: Turn) => Turn) => setTurns(ts => ts.map((t, j) => (j === i ? f(t) : t)));

  // The answer arrives whole - every figure in it is checked first - so it is
  // shown a few words at a time over about a second.
  // The animation only moves how much is shown: the text itself is set once
  // here and replaced by the server's cleaned answer on 'done', which a later
  // tick must not undo.
  const reveal = (i: number, text: string) => {
    if (prefersCalm()) { update(i, t => ({ ...t, answer: text, shown: null })); return; }
    update(i, t => ({ ...t, answer: text, shown: 0 }));
    const started = performance.now();
    const tick = (now: number) => {
      const want = Math.min(text.length, Math.round(text.length * (now - started) / 900));
      const cut = text.indexOf(' ', want);
      const shown = want >= text.length || cut < 0 ? null : cut;
      update(i, t => ({ ...t, shown }));
      if (shown !== null) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  };

  const ask = useCallback(async (question: string, at?: { location: string; spatial: Record<string, unknown> }) => {
    question = question.trim();
    if (!question || busy) return;
    setBusy(true);
    const history = turns.map(t => ({ question: t.question, answer: t.answer }));
    const i = turns.length;
    setTurns(ts => [...ts, { question, answer: '', shown: null, steps: [], citations: [], next: [] }]);

    // A request with no deadline once sat on "Thinking…" for ten minutes.
    const ctl = new AbortController();
    const deadline = setTimeout(() => ctl.abort(), 90000);
    let got = '';
    try {
      const r = await fetch(`${API}/ask/stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctl.signal,
        body: JSON.stringify({
          question, history, location: at?.location ?? location, spatial: at?.spatial ?? spatial.current, lang,
          active_layers: active.map(a => ({ id: a.layer.id, name: a.layer.name, theme: a.layer.theme,
                                            year: a.layer.source?.year, agency: a.layer.source?.agency })),
        }),
      });
      if (r.status === 429) {
        const d = await r.json().catch(() => ({}));
        const s = d.retry_after;
        got = lang === 'es'
          ? `Demasiadas preguntas a la vez. ${s ? `Espere ${s} segundos.` : 'Espere un momento.'}`
          : `Too many questions at once. ${s ? `Please wait ${s} seconds.` : 'Please wait a moment.'}`;
        update(i, t => ({ ...t, answer: got }));
        return;
      }
      if (!r.ok || !r.body) throw new Error('HTTP ' + r.status);
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const chunks = buf.split('\n\n');
        buf = chunks.pop() || '';
        for (const chunk of chunks) {
          const ev = /^event: (\w+)/m.exec(chunk)?.[1];
          const raw = /^data: (.*)$/m.exec(chunk)?.[1];
          if (!ev || !raw) continue;
          let d: any; try { d = JSON.parse(raw); } catch { continue; }
          const map = mapRef.current;
          if (ev === 'meta' || ev === 'map') {
            // What the map should do; a later 'map' event replaces the first.
            if (d.disclaimers) setDisclaimers(d.disclaimers);
            const found: Found[] = d.found || [];
            autoShow(d.suggested_layers || []).then(() => showFound(map, found));
            if (d.focus) focusBBox(map, d.focus, found.length ? 15 : 11);
          } else if (ev === 'status') {
            update(i, t => ({ ...t, steps: [...t.steps, d.text || ''] }));
          } else if (ev === 'delta') {
            got += d.text || '';
            reveal(i, got);
          } else if (ev === 'done') {
            // The server's cleaned answer replaces the streamed text.
            if (d.answer) got = d.answer;
            update(i, t => ({ ...t, citations: d.citations || [], answer: got }));
          } else if (ev === 'followups') {
            update(i, t => ({ ...t, next: d.questions || [] }));
          }
        }
      }
      if (!got) throw new Error('empty response');
    } catch (e: any) {
      const msg = e?.name === 'AbortError'
        ? (lang === 'es' ? 'La respuesta tardó demasiado. Inténtalo de nuevo.' : 'That took too long to answer. Please try again.')
        : 'Error: ' + (e?.message || e);
      update(i, t => ({ ...t, answer: msg, shown: null }));
    } finally {
      clearTimeout(deadline);
      setBusy(false);
    }
  }, [busy, turns, location, lang, active, autoShow, mapRef]);

  const askAbout = useCallback((p: Pending) => {
    setLocation(p.municipio, p.spatial);
    ask(placeQuestion(p, lang === 'es'), { location: p.municipio, spatial: p.spatial });
  }, [ask, lang, setLocation]);

  const clear = useCallback(() => { setTurns([]); setDisclaimers({}); }, []);

  const value = useMemo<ChatState>(() => ({
    turns, busy, disclaimer: disclaimers[lang] || '', location, setLocation, ask, askAbout, clear,
  }), [turns, busy, disclaimers, lang, location, setLocation, ask, askAbout, clear]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useChat(): ChatState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useChat outside ChatProvider');
  return v;
}

// The question a click asks: about what is on the map there, so it changes
// with the layers the user has on, not the same sentence every time.
export function placeQuestion(p: Pending, es: boolean): string {
  const list = (names: string[]) => {
    const n = names.slice(0, 3);
    const and = es ? ' y ' : ' and ';
    return n.length > 1 ? n.slice(0, -1).join(', ') + and + n[n.length - 1] : n[0];
  };
  const m = p.municipio;
  if (p.here.length) return es
    ? `¿Qué muestra${p.here.length > 1 ? 'n' : ''} ${list(p.here)} en este punto de ${m}, y qué significa para este lugar?`
    : `What does ${list(p.here)} show at this spot in ${m}, and what does it mean for this place?`;
  if (p.on.length) return es
    ? `¿Qué dice${p.on.length > 1 ? 'n' : ''} ${list(p.on)} sobre esta zona de ${m}?`
    : `What does ${list(p.on)} say about this area of ${m}?`;
  if (p.inside.length) return es
    ? `Este punto de ${m} está en ${list(p.inside)}. ¿Qué significa y qué reglas de planificación aplican aquí?`
    : `This spot in ${m} is in ${list(p.inside)}. What does that mean, and what planning rules apply here?`;
  return es
    ? `¿Qué debo saber sobre este punto de ${m}: riesgos naturales, uso de terrenos y reglas de planificación?`
    : `What should I know about this spot in ${m}: natural hazards, land use, and planning rules?`;
}
