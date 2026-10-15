// Shared chats: the owner makes a link (snapshot of the chat); any signed-in portal user who opens it reads the
// conversation and can copy it into their own profile as a new chat ("Скопіювати та продовжити"), optionally
// compressed first so a long chat does not cost many tokens.
import React, {useEffect, useRef, useState} from 'react';
import {api} from './Auth';
import {Ic, X, ContentCopy, Check, Refresh, Trash2} from './Icons';
import {Markdown} from './Markdown';
import {toast} from './Feedback';
import {shortTime} from './MessageItem';

const KEY = 'hermes-share';
/** Remember a /s/<token> link across the login page (Root resets the path to "/"). */
export function captureShareLink() {
  const m = location.pathname.match(/^\/s\/([A-Za-z0-9_-]{16,40})\/?$/);
  if (m) sessionStorage.setItem(KEY, m[1]);
}
export const pendingShare = () => sessionStorage.getItem(KEY) || '';
export const clearShare = () => sessionStorage.removeItem(KEY);
const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: {'Content-Type': 'application/json'},
  body: body === undefined ? undefined : JSON.stringify(body),
});

function useModal(onClose: () => void) {
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', f);
    return () => window.removeEventListener('keydown', f);
  }, [onClose]);
}

/** Owner side: make / refresh / revoke the link of one chat. */
export function ShareDialog({dialog, title, onClose}: {dialog: string; title: string; onClose: () => void}) {
  const [st, setSt] = useState<{token: string | null; path?: string; created?: number; messages?: number} | null>(null),
    [busy, setBusy] = useState(''),
    [err, setErr] = useState('');
  useModal(onClose);
  useEffect(() => {
    api(`/dialogs/${dialog}/share`)
      .then(setSt)
      .catch(e => setErr(String(e)));
  }, [dialog]);
  const url = st?.path ? location.origin + st.path : '';
  async function run(kind: string, fn: () => Promise<void>) {
    setBusy(kind);
    setErr('');
    try {
      await fn();
    } catch (e) {
      setErr(String(e).replace(/^Error: /, ''));
    } finally {
      setBusy('');
    }
  }
  const make = () =>
    run('make', async () => {
      const r = await api(`/dialogs/${dialog}/share`, json('POST'));
      setSt(r);
      toast(st?.token ? 'Знімок оновлено' : 'Посилання створено');
    });
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      toast('Посилання скопійовано');
    } catch {
      toast('Не вдалося скопіювати', 'error');
    }
  };
  return (
    <div
      className="overlay"
      onMouseDown={e => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal share-modal" role="dialog" aria-modal="true" aria-label="Поділитися чатом">
        <div className="row">
          <h2>Поділитися чатом</h2>
          <button className="icon" aria-label="Закрити" onClick={onClose}>
            <Ic i={X} />
          </button>
        </div>
        <p className="hint">
          «{title}». Посилання відкриє будь-хто з користувачів Shroom, хто увійшов у портал. Він побачить розмову на момент створення
          посилання і зможе скопіювати її собі, щоб продовжити.
        </p>
        {err && (
          <div className="error" role="alert">
            {err}
          </div>
        )}
        {!st ? (
          <div className="skeleton-block" aria-busy="true">
            <i />
            <i />
          </div>
        ) : st.token ? (
          <>
            <div className="share-link">
              <input readOnly value={url} onFocus={e => e.currentTarget.select()} aria-label="Посилання" />
              <button className="send" onClick={copy}>
                <Ic i={ContentCopy} size={18} /> Копіювати
              </button>
            </div>
            <p className="hint">
              Знімок: {st.messages} повідомл., {st.created ? new Date(st.created * 1000).toLocaleString('uk-UA') : ''}. Нові повідомлення
              зʼявляться за посиланням після оновлення знімка.
            </p>
            <div className="actions">
              <button disabled={!!busy} onClick={make}>
                <Ic i={Refresh} size={18} /> Оновити знімок
              </button>
              <button
                className="danger"
                disabled={!!busy}
                onClick={() =>
                  run('off', async () => {
                    await api(`/dialogs/${dialog}/share`, json('DELETE'));
                    setSt({token: null});
                    toast('Доступ за посиланням закрито');
                  })
                }
              >
                <Ic i={Trash2} size={18} /> Закрити доступ
              </button>
            </div>
          </>
        ) : (
          <div className="actions">
            <button className="send" disabled={!!busy} aria-busy={busy === 'make'} onClick={make}>
              {busy === 'make' ? <span className="spinner" /> : 'Створити посилання'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

type Shared = {
  title: string;
  owner: string;
  own: boolean;
  created: number;
  messages: {role: string; text: string; timestamp?: number}[];
  chars: number;
  approx_tokens: number;
  full_allowed: boolean;
  suggest_compress: boolean;
};
/** Reader side: read-only transcript + "copy and continue". */
export function SharedChat({token, onClose, onCopied}: {token: string; onClose: () => void; onCopied: (id: string) => void}) {
  const [d, setD] = useState<Shared | null>(null),
    [err, setErr] = useState(''),
    [compress, setCompress] = useState(false),
    [busy, setBusy] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useModal(onClose);
  useEffect(() => {
    api('/shares/' + token)
      .then((x: Shared) => {
        setD(x);
        setCompress(x.suggest_compress || !x.full_allowed);
      })
      .catch(e => setErr(String(e).replace(/^Error: /, '')));
  }, [token]);
  async function copy() {
    setBusy(true);
    setErr('');
    try {
      const r = await api(`/shares/${token}/copy`, json('POST', {compress}));
      toast(compress ? 'Розмову стиснуто й скопійовано' : 'Розмову скопійовано');
      onCopied(r.id);
    } catch (e) {
      setErr(String(e).replace(/^Error: /, ''));
    } finally {
      setBusy(false);
    }
  }
  const k = (n: number) => (n >= 1000 ? Math.round(n / 1000) + ' тис.' : String(n));
  return (
    <div
      className="overlay settings-overlay"
      onMouseDown={e => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div className="settings-window shared-window" role="dialog" aria-modal="true" aria-label="Спільний чат">
        <main className="settings-main">
          <button className="icon close" aria-label="Закрити" onClick={onClose}>
            <Ic i={X} />
          </button>
          {!d ? (
            err ? (
              <div className="detail-pane">
                <div className="page-head">
                  <h1>Спільний чат</h1>
                </div>
                <div className="error">{err}</div>
              </div>
            ) : (
              <div className="detail-pane">
                <div className="skeleton-block" aria-busy="true">
                  <i />
                  <i />
                  <i />
                  <i />
                </div>
              </div>
            )
          ) : (
            <>
              <div className="detail-pane shared-scroll" ref={box}>
                <div className="page-head">
                  <h1>{d.title}</h1>
                  <p className="hint">
                    Поділився {d.own ? 'ви' : d.owner} · {new Date(d.created * 1000).toLocaleString('uk-UA')} · {d.messages.length}{' '}
                    повідомл. · ~{k(d.approx_tokens)} токенів. Лише читання.
                  </p>
                </div>
                <section className="chat shared-transcript">
                  {d.messages.map((m, i) => (
                    <article key={i} className={m.role === 'user' ? 'user' : 'assistant'}>
                      <label className={m.role === 'user' ? undefined : 'assistant-name-row'}>
                        {m.role === 'user' ? (d.own ? 'ВИ' : d.owner.toUpperCase()) : 'SHROOM'}
                        {m.timestamp && <time className="msg-time">{shortTime(m.timestamp)}</time>}
                      </label>
                      {m.role === 'user' ? <div>{m.text}</div> : <Markdown text={m.text} />}
                    </article>
                  ))}
                </section>
              </div>
              <div className="shared-bar">
                {err && (
                  <div className="error" role="alert">
                    {err}
                  </div>
                )}
                <label className="warn-check">
                  <input
                    type="checkbox"
                    checked={compress}
                    disabled={busy || !d.full_allowed}
                    onChange={e => setCompress(e.target.checked)}
                  />
                  Стиснути перед копіюванням{d.suggest_compress || !d.full_allowed ? ' (рекомендовано: розмова велика)' : ''}
                </label>
                <p className="hint">
                  {compress
                    ? 'Ваша модель коротко перекаже розмову: ціли, рішення, факти й відкриті питання. Новий чат почнеться з цього переказу, тому кожна відповідь коштуватиме менше.'
                    : `Новий чат отримає всю розмову (~${k(d.approx_tokens)} токенів), і агент читатиме її з кожним вашим повідомленням.`}
                </p>
                <div className="actions">
                  <button onClick={onClose} disabled={busy}>
                    Закрити
                  </button>
                  <button className="send" onClick={copy} disabled={busy} aria-busy={busy}>
                    {busy ? (
                      <>
                        <span className="spinner" /> {compress ? 'Стискаємо…' : 'Копіюємо…'}
                      </>
                    ) : (
                      <>
                        <Ic i={Check} size={18} /> Скопіювати та продовжити
                      </>
                    )}
                  </button>
                </div>
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
