'use client';

// The chat column, in the current site's markup.
import { Fragment, useEffect, useRef, useState } from 'react';
import { useChat, type Turn } from '@/lib/chat';
import { I18N } from '@/lib/i18n';
import { useLayers } from '@/lib/layers';

// "[1, 2]" citation numbers out, "**bold**" as bold.
function AnswerText({ text }: { text: string }) {
  const clean = text.replace(/\s*\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]/g, '');
  const parts = clean.split(/\*\*([^*\n]+)\*\*/g);
  return <>{parts.map((p, i) => (i % 2 ? <b key={i}>{p}</b> : <Fragment key={i}>{p}</Fragment>))}</>;
}

function TurnView({ t, lang }: { t: Turn; lang: 'es' | 'en' }) {
  const L = I18N[lang];
  const steps = t.steps.length ? t.steps : [L.thinking];
  const text = t.shown != null ? t.answer.slice(0, t.shown) : t.answer;
  return (
    <>
      <div className="row user"><div className="bubble">{t.question}</div></div>
      <div className="row bot"><div className="bubble">
        <div className="who">Mappa</div>
        {!t.answer ? (
          <div className="steps">{steps.map((st, i) => i < steps.length - 1
            ? <div key={i} className="step done">✓ {st}</div>
            : <div key={i} className="step now"><span className="spin" />{st}…</div>)}</div>
        ) : <div className="answer"><AnswerText text={text} /></div>}
        {t.citations.length > 0 && (
          <div className="cites"><div className="cites-h">{L.sources}</div>
            {t.citations.map((c, i) => (
              <div className="cite" key={i}>{c.kind === 'layer' ? '🗺️' : '📄'} <span className="ct">{c.title}</span>
                {c.source ? ` · ${c.source}` : ''}
                {c.year && !String(c.title).includes(String(c.year)) ? ` · ${c.year}` : ''}
                {c.doc_id ? <> · <span className="cid">{c.doc_id}</span></> : null}
              </div>))}
          </div>)}
      </div></div>
    </>
  );
}

export default function ChatPanel() {
  const { lang } = useLayers();
  const { turns, busy, disclaimer, location, setLocation, ask, clear } = useChat();
  const L = I18N[lang];
  const [q, setQ] = useState('');
  const out = useRef<HTMLDivElement>(null);
  useEffect(() => { out.current?.scrollTo({ top: out.current.scrollHeight }); }, [turns]);
  const send = (text: string) => { if (text.trim()) { ask(text); setQ(''); } };

  return (
    <section className="chat">
      <div id="out" className="messages" ref={out}>
        {!turns.length ? (
          <div className="empty">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <div className="icon"><img src="/logo.png" alt="" width={76} height={76} /></div>
            <h3 translate="no">{L.emptyT}</h3>
            <p>{L.emptyB}</p>
            <div className="hint"><b>{L.hint[0]}</b>{L.hint[1]}</div>
          </div>
        ) : turns.map((t, i) => <TurnView key={i} t={t} lang={lang} />)}
      </div>
      <div className="composer">
        <div className="samples">
          {L.samples.map(([label, question]) => (
            <a key={label} role="button" tabIndex={0} onClick={() => send(question)}
               onKeyDown={e => e.key === 'Enter' && send(question)}>{label}</a>))}
        </div>
        <div className="inputrow">
          <textarea id="q" value={q} placeholder={L.ph} onChange={e => setQ(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) send(q); }} />
          <button id="go" title={L.ask} disabled={busy} onClick={() => send(q)}>➤</button>
        </div>
        <div className="composer-meta">
          <a id="clear" role="button" tabIndex={0} onClick={clear}>{L.clear}</a>
          {location && (
            <span id="loc" className="locchip" style={{ display: 'inline-block' }}>
              📍 {location} <span className="x" title={L.removeFilter} role="button" tabIndex={0}
                                 onClick={() => setLocation(null)}>✕</span>
            </span>)}
        </div>
      </div>
      <div className="disc" id="disc">{disclaimer}</div>
    </section>
  );
}
