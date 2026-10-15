// One chat message: author row with time, body, and the actions under it (copy; edit for the user's messages;
// regenerate for the latest reply). Edit and regenerate are native Hermes rewinds (history from that user message on is
// replaced), so they are offered only while the agent is idle and only with the matching permission.
import React, {useEffect, useRef, useState} from 'react';
import {Markdown} from './Markdown';
import {Ic, ContentCopy, Edit, Refresh, Check} from './Icons';
import {toast} from './Feedback';
import {AttachmentCards, FileCard} from './Attachments';

export type ChatMessage = {
  role?: string;
  text?: string;
  content?: unknown;
  type?: string;
  row_id?: number;
  timestamp?: number;
  files?: FileCard[];
};

const pad = (n: number) => String(n).padStart(2, '0');
/** 14:05 today, «вчора 14:05», 12.10 14:05 this year, 12.10.2025 otherwise. */
export function shortTime(ts?: number): string {
  if (!ts) return '';
  const d = new Date(ts * 1000),
    now = new Date(),
    hm = pad(d.getHours()) + ':' + pad(d.getMinutes());
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86400000);
  if (diff === 0) return hm;
  if (diff === 1) return 'вчора ' + hm;
  return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + (d.getFullYear() === now.getFullYear() ? '' : '.' + d.getFullYear()) + ' ' + hm;
}
const fullTime = (ts?: number) => (ts ? new Date(ts * 1000).toLocaleString('uk-UA', {dateStyle: 'long', timeStyle: 'medium'}) : '');

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Скопійовано');
  } catch {
    // http or a denied permission: fall back to a hidden textarea
    const t = document.createElement('textarea');
    t.value = text;
    t.style.position = 'fixed';
    t.style.opacity = '0';
    document.body.appendChild(t);
    t.select();
    const ok = document.execCommand('copy');
    t.remove();
    toast(ok ? 'Скопійовано' : 'Не вдалося скопіювати', ok ? undefined : 'error');
  }
}

type Props = {
  m: ChatMessage;
  text: string;
  /** Assistant: the whole reply of this turn (all its segments) — what «copy» takes; shown on the last segment only. */
  turnText?: string;
  showActions: boolean;
  canEdit: boolean;
  canRetry: boolean;
  idle: boolean;
  laterTurns: boolean;
  onEdit: (rowId: number, text: string) => Promise<boolean>;
  onRetry: () => void;
};

export function MessageItem({m, text, turnText, showActions, canEdit, canRetry, idle, laterTurns, onEdit, onRetry}: Props) {
  const user = m.role === 'user';
  const [editing, setEditing] = useState(false),
    [draft, setDraft] = useState(text),
    [saving, setSaving] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (editing) {
      const t = area.current;
      if (t) {
        t.focus();
        t.setSelectionRange(t.value.length, t.value.length);
      }
    }
  }, [editing]);
  const time = shortTime(m.timestamp);
  async function save() {
    const t = draft.trim();
    if (!t || !m.row_id) return;
    if (t === text.trim() && !window.confirm('Текст не змінився. Надіслати ще раз і отримати нову відповідь?')) return;
    setSaving(true);
    try {
      if (await onEdit(m.row_id, t)) setEditing(false);
    } finally {
      setSaving(false);
    }
  }
  const label = (
    <label className={user ? undefined : 'assistant-name-row'}>
      {user ? 'ВИ' : 'SHROOM'}
      {time && (
        <time className="msg-time" dateTime={new Date((m.timestamp ?? 0) * 1000).toISOString()} title={fullTime(m.timestamp)}>
          {time}
        </time>
      )}
    </label>
  );
  if (editing)
    return (
      <article className="user editing">
        {label}
        <textarea
          ref={area}
          className="msg-edit"
          value={draft}
          rows={Math.min(12, Math.max(2, draft.split('\n').length))}
          disabled={saving}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Escape') {
              e.preventDefault();
              setEditing(false);
              setDraft(text);
            }
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              void save();
            }
          }}
        />
        <div className="msg-edit-bar">
          <span className="hint">
            {laterTurns ? 'Подальші повідомлення цього чату буде замінено новою відповіддю.' : 'Агент відповість на змінений текст.'}
          </span>
          <button
            type="button"
            onClick={() => {
              setEditing(false);
              setDraft(text);
            }}
            disabled={saving}
          >
            Скасувати
          </button>
          <button type="button" className="send" onClick={() => void save()} disabled={saving || !draft.trim()} aria-busy={saving}>
            {saving ? <span className="spinner" /> : 'Надіслати'}
          </button>
        </div>
      </article>
    );
  return (
    <article className={user ? 'user' : 'assistant'}>
      {label}
      {user ? text && <div>{text}</div> : <Markdown text={text} />}
      {user && m.files && <AttachmentCards files={m.files} />}
      {showActions && (
        <div className="msg-actions" role="toolbar" aria-label="Дії з повідомленням">
          <CopyButton text={user ? text : (turnText ?? text)} />
          {user && canEdit && m.row_id && (
            <button
              type="button"
              className="icon"
              disabled={!idle}
              title={idle ? 'Редагувати й надіслати знову' : 'Дочекайтеся завершення відповіді'}
              aria-label="Редагувати"
              onClick={() => {
                setDraft(text);
                setEditing(true);
              }}
            >
              <Ic i={Edit} size={18} />
            </button>
          )}
          {!user && canRetry && (
            <button
              type="button"
              className="icon"
              disabled={!idle}
              title={idle ? 'Згенерувати відповідь ще раз' : 'Дочекайтеся завершення відповіді'}
              aria-label="Згенерувати ще раз"
              onClick={onRetry}
            >
              <Ic i={Refresh} size={18} />
            </button>
          )}
        </div>
      )}
    </article>
  );
}

function CopyButton({text}: {text: string}) {
  const [done, setDone] = useState(false),
    timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );
  return (
    <button
      type="button"
      className="icon"
      title="Копіювати"
      aria-label="Копіювати"
      onClick={async () => {
        await copyText(text);
        setDone(true);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => setDone(false), 1500);
      }}
    >
      <Ic i={done ? Check : ContentCopy} size={18} />
    </button>
  );
}
