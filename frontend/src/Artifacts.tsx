import React, {useEffect, useState} from 'react';
import {createPortal} from 'react-dom';
import {ask, toast} from './Feedback';
import {api} from './Auth';
import {Ic, X, Trash2, Download, FileText, Image, Folder, OpenInNew} from './Icons';
import {TextView} from './Attachments';

type Artifact = {
  id: string;
  name: string;
  mime: string;
  size: number;
  created: number | null;
  dialog: string;
  title: string;
  preview?: string;
};
const kb = (n: number) => (n < 1024 * 1024 ? Math.ceil(n / 1024) + ' KiB' : (n / 1048576).toFixed(1) + ' MiB');
const when = (t: number | null) =>
  t ? new Date(t * 1000).toLocaleString('uk-UA', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : '';

/** All files the user attached to dialogs (uploads, clipboard images, long pasted text). One place to find, open, download or delete them. */
export function Artifacts({onClose, openDialog}: {onClose: () => void; openDialog: (id: string) => void}) {
  const [items, setItems] = useState<Artifact[] | null>(null),
    [error, setError] = useState('');
  const [kind, setKind] = useState<'all' | 'image' | 'text'>('all'),
    [q, setQ] = useState(''),
    [view, setView] = useState<Artifact | null>(null);
  const load = () =>
    api('/me/files')
      .then(setItems)
      .catch(e => setError(String(e)));
  useEffect(() => {
    load();
    const f = (e: KeyboardEvent) => {
      if (e.key === 'Escape') view ? setView(null) : onClose();
    };
    window.addEventListener('keydown', f);
    return () => window.removeEventListener('keydown', f);
  }, [view]);
  async function del(a: Artifact) {
    if (!(await ask(`Видалити ${a.name}? Агент більше не зможе його відкрити.`, {danger: true, ok: 'Так'}))) return;
    try {
      await api('/me/files/' + a.id, {method: 'DELETE'});
      setView(null);
      load();
    } catch (e) {
      setError(String(e));
    }
  }
  const t = q.trim().toLowerCase();
  const list = (items ?? []).filter(
    a =>
      (kind === 'all' || (kind === 'image') === a.mime.startsWith('image/')) &&
      (!t || (a.name + ' ' + a.title + ' ' + (a.preview ?? '')).toLowerCase().includes(t))
  );
  const total = (items ?? []).reduce((s, a) => s + a.size, 0);
  return createPortal(
    <div
      className="overlay settings-overlay"
      onMouseDown={e => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="settings-window artifacts" role="dialog" aria-label="Артефакти">
        <main className="settings-main">
          <button className="close icon" title="Закрити (Esc)" onClick={onClose}>
            <Ic i={X} />
          </button>
          <div className="detail-pane">
            <div className="page-head">
              <h1>Артефакти</h1>
              <p className="hint">
                Файли, які ви додавали в діалоги: зображення з буфера, довгі вставлені тексти, завантаження.{' '}
                {items && `${items.length} шт. · ${kb(total)}`}
              </p>
            </div>
            <div className="row filters">
              <div className="tri">
                {(
                  [
                    ['all', 'Усі'],
                    ['image', 'Зображення'],
                    ['text', 'Тексти'],
                  ] as const
                ).map(([k, l]) => (
                  <button key={k} className={kind === k ? 'on' : ''} onClick={() => setKind(k)}>
                    {l}
                  </button>
                ))}
              </div>
              <input placeholder="Пошук за назвою, діалогом або текстом" value={q} onChange={e => setQ(e.target.value)} />
            </div>
            {error && <div className="error">{error}</div>}
            {!items ? (
              <div className="skeleton-block" aria-busy="true">
                <i />
                <i />
                <i />
              </div>
            ) : !list.length ? (
              <p className="hint">
                {items.length
                  ? 'Нічого не знайдено.'
                  : 'Поки порожньо. Вставте зображення або довгий текст у поле повідомлення — він з’явиться тут.'}
              </p>
            ) : (
              <div className="art-grid">
                {list.map(a => (
                  <div className="art" key={a.id}>
                    <button className="art-prev" onClick={() => setView(a)} title="Переглянути">
                      {a.mime.startsWith('image/') ? (
                        <img src={`/api/me/files/${a.id}`} alt={a.name} loading="lazy" />
                      ) : (
                        <pre>{(a.preview ?? '').slice(0, 300)}</pre>
                      )}
                    </button>
                    <div className="art-meta">
                      <b title={a.name}>
                        <Ic i={a.mime.startsWith('image/') ? Image : FileText} size={16} /> {a.name}
                      </b>
                      <small>
                        {kb(a.size)}
                        {a.created ? ' · ' + when(a.created) : ''}
                      </small>
                      <small className="art-dialog" title={a.title}>
                        <Ic i={Folder} size={14} /> {a.title}
                      </small>
                    </div>
                    <div className="art-actions">
                      <button
                        className="icon"
                        title="Відкрити діалог"
                        onClick={() => {
                          openDialog(a.dialog);
                          onClose();
                        }}
                      >
                        <Ic i={OpenInNew} />
                      </button>
                      <a className="icon-link" title="Завантажити" href={`/api/me/files/${a.id}?download=1`}>
                        <Ic i={Download} />
                      </a>
                      <button className="icon" title="Видалити" onClick={() => del(a)}>
                        <Ic i={Trash2} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </main>
        {view && (
          <div
            className="art-viewer"
            onMouseDown={e => {
              if (e.target === e.currentTarget) setView(null);
            }}
          >
            <div className="art-viewer-bar">
              <b>{view.name}</b>
              <span className="hint">
                {kb(view.size)} · {view.title}
              </span>
              <a className="icon-link" title="Завантажити" href={`/api/me/files/${view.id}?download=1`}>
                <Ic i={Download} />
              </a>
              <button className="icon" title="Закрити" onClick={() => setView(null)}>
                <Ic i={X} />
              </button>
            </div>
            {view.mime.startsWith('image/') ? <img src={`/api/me/files/${view.id}`} alt={view.name} /> : <TextView id={view.id} />}
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
