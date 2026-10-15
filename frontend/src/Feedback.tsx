import React, {useEffect, useState} from 'react';
import {createPortal} from 'react-dom';

/** App-wide feedback: ask() replaces window.confirm with a styled dialog; toast() shows a short status at the bottom. */
type Ask = {title: string; text?: string; ok?: string; danger?: boolean; resolve: (v: boolean) => void};
type Toast = {id: number; text: string; kind: 'ok' | 'error'};
let pushAsk: (a: Ask) => void = () => {};
let pushToast: (t: Toast) => void = () => {};

export function ask(title: string, opts: {text?: string; ok?: string; danger?: boolean} = {}): Promise<boolean> {
  return new Promise(resolve => pushAsk({title, ...opts, resolve}));
}
export function toast(text: string, kind: 'ok' | 'error' = 'ok') {
  pushToast({id: Date.now() + Math.random(), text, kind});
}

export function FeedbackHost() {
  const [q, setQ] = useState<Ask | null>(null),
    [toasts, setToasts] = useState<Toast[]>([]);
  useEffect(() => {
    pushAsk = a => setQ(a);
    pushToast = t => {
      setToasts(x => [...x.slice(-2), t]);
      setTimeout(() => setToasts(x => x.filter(y => y.id !== t.id)), t.kind === 'error' ? 6000 : 2500);
    };
  }, []);
  const close = (v: boolean) => {
    q?.resolve(v);
    setQ(null);
  };
  useEffect(() => {
    if (!q) return;
    const f = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        close(false);
      }
      if (e.key === 'Enter' && !q.danger) close(true);
    };
    window.addEventListener('keydown', f, true);
    return () => window.removeEventListener('keydown', f, true);
  }, [q]);
  return createPortal(
    <>
      {q && (
        <div
          className="overlay ask-overlay"
          onMouseDown={e => {
            if (e.target === e.currentTarget) close(false);
          }}
        >
          <div className="modal narrow" role="alertdialog" aria-label={q.title}>
            <h2>{q.title}</h2>
            {q.text && <p>{q.text}</p>}
            <div>
              <button autoFocus={q.danger} onClick={() => close(false)}>
                Скасувати
              </button>
              <button autoFocus={!q.danger} className={'send' + (q.danger ? ' danger' : '')} onClick={() => close(true)}>
                {q.ok ?? 'Підтвердити'}
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="toasts" aria-live="polite">
        {toasts.map(t => (
          <div key={t.id} className={'toast ' + t.kind}>
            {t.text}
          </div>
        ))}
      </div>
    </>,
    document.body
  );
}
