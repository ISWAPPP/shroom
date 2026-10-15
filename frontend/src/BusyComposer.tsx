// Composer controls while the agent works: a split button (last chosen action + menu of all actions)
// next to a compact stop button, and the editable list of queued follow-up messages.
import React, {useEffect, useRef, useState} from 'react';
import {Ic, IconT, ChevronDown, Square, PlaylistAdd, AltRoute, CallSplit, ContactSupport, Edit, X, Send, Check} from './Icons';

export type BusyMode = 'queue' | 'steer' | 'bg' | 'btw';
export type Queued = {id: string; text: string};

export const BUSY_ACTIONS: {mode: BusyMode; icon: IconT; label: string; hint: string; perm?: string}[] = [
  {mode: 'queue', icon: PlaylistAdd, label: 'У чергу', hint: 'Надішлеться автоматично, коли агент закінчить'},
  {
    mode: 'steer',
    icon: AltRoute,
    label: 'Уточнити зараз',
    hint: 'Агент врахує після поточного кроку, не перериваючи роботу',
    perm: 'cmd:steer',
  },
  {
    mode: 'bg',
    icon: CallSplit,
    label: 'У фоні',
    hint: 'Окремий агент виконає паралельно, відповідь зʼявиться в цьому чаті',
    perm: 'cmd:bg',
  },
  {
    mode: 'btw',
    icon: ContactSupport,
    label: 'Бічне питання',
    hint: 'Коротка відповідь за контекстом розмови, без впливу на неї',
    perm: 'cmd:btw',
  },
];

export function availableActions(perms: Record<string, boolean>) {
  return BUSY_ACTIONS.filter(a => !a.perm || perms[a.perm]);
}

export function BusyActions({
  actions,
  mode,
  onMode,
  canRun,
  sending,
  run,
  stop,
  stopping,
}: {
  actions: typeof BUSY_ACTIONS;
  mode: BusyMode;
  onMode: (m: BusyMode) => void;
  canRun: boolean;
  sending: boolean;
  run: (m: BusyMode) => void;
  stop: () => void;
  stopping: boolean;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  const current = actions.find(a => a.mode === mode) ?? actions[0];
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', away);
    window.addEventListener('keydown', esc, true);
    return () => {
      document.removeEventListener('mousedown', away);
      window.removeEventListener('keydown', esc, true);
    };
  }, [open]);
  return (
    <span className="busy-actions" role="group" aria-label="Дії під час роботи агента" ref={box}>
      <span className="split-btn">
        <button
          className="send split-main"
          disabled={!canRun || sending}
          aria-busy={sending}
          title={current.hint + ' (Ctrl + Enter)'}
          onClick={() => run(current.mode)}
        >
          <Ic i={current.icon} size={18} /> {current.label}
        </button>
        {actions.length > 1 && (
          <button className="send split-more" aria-haspopup="menu" aria-expanded={open} title="Інші дії" onClick={() => setOpen(o => !o)}>
            <Ic i={ChevronDown} size={18} />
          </button>
        )}
      </span>
      {open && (
        <span className="busy-menu" role="menu" aria-label="Що зробити з повідомленням">
          {actions.map(a => (
            <button
              key={a.mode}
              role="menuitemradio"
              aria-checked={a.mode === mode}
              className={a.mode === mode ? 'on' : ''}
              onClick={() => {
                onMode(a.mode);
                setOpen(false);
                if (canRun) run(a.mode);
              }}
            >
              <Ic i={a.icon} size={20} />
              <span>
                <b>{a.label}</b>
                <small>{a.hint}</small>
              </span>
              {a.mode === mode && <Ic i={Check} size={18} className="tick" />}
            </button>
          ))}
        </span>
      )}
      <button
        className="stop-mini"
        disabled={stopping}
        aria-busy={stopping}
        title={stopping ? 'Зупиняємо…' : 'Зупинити'}
        aria-label="Зупинити"
        onClick={stop}
      >
        <Ic i={Square} size={16} fill />
      </button>
    </span>
  );
}

export function QueueList({
  items,
  idle,
  onChange,
  onSendNow,
}: {
  items: Queued[];
  idle: boolean;
  onChange: (items: Queued[]) => void;
  onSendNow: (q: Queued) => void;
}) {
  const [editing, setEditing] = useState<string>(''),
    [draft, setDraft] = useState('');
  if (!items.length) return null;
  const save = () => {
    const t = draft.trim();
    onChange(t ? items.map(q => (q.id === editing ? {...q, text: t} : q)) : items.filter(q => q.id !== editing));
    setEditing('');
  };
  return (
    <div className="queue" aria-label="Повідомлення в черзі">
      <div className="queue-head">
        У черзі: {items.length}
        {idle ? ' · агент вільний, надішліть вручну' : ' · надішлються по черзі, коли агент закінчить'}
      </div>
      {items.map((q, i) => (
        <div key={q.id} className="queue-item">
          <span className="queue-n">{i + 1}</span>
          {editing === q.id ? (
            <>
              <textarea
                autoFocus
                aria-label="Редагувати повідомлення в черзі"
                value={draft}
                rows={2}
                onChange={e => setDraft(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    save();
                  }
                  if (e.key === 'Escape') {
                    e.stopPropagation();
                    setEditing('');
                  }
                }}
              />
              <button className="icon" title="Зберегти (Ctrl + Enter)" onClick={save}>
                <Ic i={Check} size={18} />
              </button>
              <button className="icon" title="Скасувати (Esc)" onClick={() => setEditing('')}>
                <Ic i={X} size={18} />
              </button>
            </>
          ) : (
            <>
              <span className="queue-text" title={q.text}>
                {q.text}
              </span>
              {idle && i === 0 && (
                <button className="icon" title="Надіслати зараз" onClick={() => onSendNow(q)}>
                  <Ic i={Send} size={18} />
                </button>
              )}
              <button
                className="icon"
                title="Редагувати"
                onClick={() => {
                  setEditing(q.id);
                  setDraft(q.text);
                }}
              >
                <Ic i={Edit} size={18} />
              </button>
              <button className="icon" title="Прибрати з черги" onClick={() => onChange(items.filter(x => x.id !== q.id))}>
                <Ic i={X} size={18} />
              </button>
            </>
          )}
        </div>
      ))}
    </div>
  );
}
