// Attachment cards: the files a user message carries (clipboard images, long pasted texts, uploads), shown under the
// message text and in the composer before sending. Clicking a card opens it in a full-window viewer.
import React, {useEffect, useState} from 'react';
import {createPortal} from 'react-dom';
import {Ic, X, Download, FileText, Image, ContentCopy} from './Icons';
import {toast} from './Feedback';

export type FileCard = {id?: string; name: string; mime: string; size?: number; preview?: string; lines?: number; missing?: boolean};

const kb = (n: number) => (n < 1024 * 1024 ? Math.max(1, Math.ceil(n / 1024)) + ' KiB' : (n / 1048576).toFixed(1) + ' MiB');
const isImage = (f: FileCard) => f.mime.startsWith('image/');
/** Human title: the portal names pasted texts and clipboard shots by time, which says nothing to a person. */
function title(f: FileCard) {
  if (/^pasted-text-/.test(f.name)) return 'Вставлений текст';
  if (/^clipboard-/.test(f.name)) return 'Зображення з буфера';
  return f.name;
}
function lines(n: number) {
  const d = n % 10,
    h = n % 100;
  return n + (d === 1 && h !== 11 ? ' рядок' : d >= 2 && d <= 4 && (h < 12 || h > 14) ? ' рядки' : ' рядків');
}

export function AttachmentCards({files, onRemove}: {files: FileCard[]; onRemove?: (f: FileCard) => void}) {
  const [open, setOpen] = useState<FileCard | null>(null);
  if (!files.length) return null;
  return (
    <div className="att-cards">
      {files.map((f, i) => {
        const meta = [isImage(f) ? '' : f.lines ? lines(f.lines) : '', f.size ? kb(f.size) : ''].filter(Boolean).join(' · ');
        return (
          <div key={f.id ?? f.name + i} className={'att-card' + (isImage(f) ? ' image' : ' text') + (f.missing ? ' missing' : '')}>
            <button
              type="button"
              className="att-open"
              disabled={!f.id || f.missing}
              title={f.missing ? 'Файл видалено з артефактів' : f.name}
              aria-label={(isImage(f) ? 'Відкрити зображення ' : 'Відкрити текст ') + f.name}
              onClick={() => setOpen(f)}
            >
              {isImage(f) && f.id && !f.missing ? (
                <img src={`/api/me/files/${f.id}`} alt={f.name} loading="lazy" />
              ) : (
                <>
                  <span className="att-head">
                    <Ic i={isImage(f) ? Image : FileText} size={16} />
                    <b>{title(f)}</b>
                  </span>
                  {f.missing ? (
                    <small>Файл видалено</small>
                  ) : (
                    <>
                      {f.preview !== undefined && <pre>{f.preview.slice(0, 240)}</pre>}
                      {meta && <small>{meta}</small>}
                    </>
                  )}
                </>
              )}
            </button>
            {onRemove && (
              <button
                type="button"
                className="icon att-remove"
                title="Прибрати"
                aria-label={'Прибрати ' + f.name}
                onClick={() => onRemove(f)}
              >
                <Ic i={X} size={14} />
              </button>
            )}
          </div>
        );
      })}
      {open && <FileViewer file={open} onClose={() => setOpen(null)} />}
    </div>
  );
}

/** Full-window viewer for one file (image or text) with download and, for text, copy. Esc or a click outside closes. */
export function FileViewer({file, onClose}: {file: FileCard; onClose: () => void}) {
  const [text, setText] = useState<string | null>(null);
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', f, true);
    return () => window.removeEventListener('keydown', f, true);
  }, [onClose]);
  return createPortal(
    <div
      className="overlay att-viewer-overlay"
      role="dialog"
      aria-label={file.name}
      onMouseDown={e => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="art-viewer att-viewer">
        <div className="art-viewer-bar">
          <b>{title(file)}</b>
          <span className="hint">
            {file.name}
            {file.size ? ' · ' + kb(file.size) : ''}
          </span>
          {!isImage(file) && (
            <button
              type="button"
              className="icon"
              title="Копіювати текст"
              disabled={text === null}
              onClick={() =>
                navigator.clipboard.writeText(text ?? '').then(
                  () => toast('Скопійовано'),
                  () => toast('Не вдалося скопіювати', 'error')
                )
              }
            >
              <Ic i={ContentCopy} />
            </button>
          )}
          <a className="icon-link" title="Завантажити" href={`/api/me/files/${file.id}?download=1`}>
            <Ic i={Download} />
          </a>
          <button type="button" className="icon" title="Закрити (Esc)" onClick={onClose}>
            <Ic i={X} />
          </button>
        </div>
        {isImage(file) ? <img src={`/api/me/files/${file.id}`} alt={file.name} /> : <TextView id={file.id!} onText={setText} />}
      </div>
    </div>,
    document.body
  );
}

export function TextView({id, onText}: {id: string; onText?: (t: string) => void}) {
  const [t, setT] = useState<string | null>(null);
  useEffect(() => {
    fetch(`/api/me/files/${id}`, {credentials: 'same-origin'})
      .then(r => (r.ok ? r.text() : Promise.reject()))
      .then(x => {
        setT(x);
        onText?.(x);
      })
      .catch(() => setT('Не вдалося відкрити'));
  }, [id]);
  return t === null ? (
    <div className="art-text skeleton-block" aria-busy="true">
      <i />
      <i />
      <i />
    </div>
  ) : (
    <pre className="art-text">{t}</pre>
  );
}
