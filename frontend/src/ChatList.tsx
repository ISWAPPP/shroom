import React, {useEffect, useRef, useState} from 'react';
import {
  Ic,
  IconT,
  MoreVert,
  Edit,
  Trash2,
  ChevronDown,
  SearchIcon,
  X,
  AutoAwesome,
  MoreHoriz,
  FrontHand,
  HelpIcon,
  CheckCircle,
  ErrorIcon,
  StopCircle,
  PushPin,
  Share,
} from './Icons';

export type MessageHit = {id: string; title: string; role: string; snippet: string; ts?: number};
export type SearchResult = {titles: Dialog[]; messages: MessageHit[]};
export type Dialog = {
  id: string;
  title: string;
  title_source?: string;
  created?: number;
  last?: number;
  unread?: number;
  job?: string | null;
  pinned?: boolean;
  runtime?: {provider: string | null; model: string | null; effort: string | null};
};
const HOUR = 3600;

/** Sidebar chat list grouped by last activity: last hour, last 8 hours, archive (collapsed).
 * Overflow menu per chat: rename, name it with the profile's title provider, delete. */
export function ChatList({
  dialogs,
  loading = false,
  archiveTotal,
  archiveMore = false,
  moreLoading = false,
  onMore,
  search: searchAll,
  status = {},
  q = '',
  active,
  busy,
  naming,
  onOpen,
  onRename,
  onAutoTitle,
  onDelete,
  onPin,
  onShare,
}: {
  dialogs: Dialog[];
  loading?: boolean;
  archiveTotal?: number;
  archiveMore?: boolean;
  moreLoading?: boolean;
  onMore?: () => void;
  search?: (q: string) => Promise<SearchResult>;
  status?: Record<string, ChatStatus>;
  q?: string;
  active: string;
  busy: boolean;
  naming: string[];
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onAutoTitle: (id: string) => void;
  onDelete: (d: Dialog) => void;
  onPin?: (d: Dialog, pinned: boolean) => void;
  onShare?: (d: Dialog) => void;
}) {
  const [archive, setArchive] = useState(() => localStorage.getItem('hermes-archive-open') === '1');
  const [menu, setMenu] = useState(''),
    [pos, setPos] = useState<{top: number; left: number}>({top: 0, left: 0}),
    [editing, setEditing] = useState('');
  // Search covers every chat (the archive is paged), so it asks the server; until it answers, filter what is loaded.
  const [results, setResults] = useState<{q: string; r: SearchResult} | null>(null),
    [searching, setSearching] = useState(false);
  useEffect(() => {
    const t = q.trim().toLowerCase();
    if (!t || !searchAll) {
      setResults(null);
      return;
    }
    let live = true;
    const h = setTimeout(() => {
      if (t.length < 2) return;
      setSearching(true);
      searchAll(t)
        .then(r => {
          if (live) setResults({q: t, r});
        })
        .catch(() => {})
        .finally(() => {
          if (live) setSearching(false);
        });
    }, 300);
    return () => {
      live = false;
      clearTimeout(h);
    };
  }, [q]);
  const now = Date.now() / 1000,
    at = (d: Dialog) => d.last ?? d.created ?? 0;
  const loose = dialogs.filter(d => !d.pinned);
  const groups: [string, Dialog[]][] = [
    ['Закріплені', dialogs.filter(d => d.pinned)],
    ['Остання година', loose.filter(d => now - at(d) < HOUR)],
    ['Останні 8 годин', loose.filter(d => now - at(d) >= HOUR && now - at(d) < 8 * HOUR)],
  ];
  const old = loose.filter(d => now - at(d) >= 8 * HOUR);
  const activeOld = old.some(d => d.id === active);
  useEffect(() => {
    localStorage.setItem('hermes-archive-open', archive ? '1' : '0');
  }, [archive]);
  useEffect(() => {
    if (!menu) return;
    const f = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest('.chat-menu, .kebab')) setMenu('');
    };
    document.addEventListener('mousedown', f);
    return () => document.removeEventListener('mousedown', f);
  }, [menu]);
  const menuTrigger = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (!menu) return;
    document.querySelector<HTMLButtonElement>('.chat-menu button')?.focus();
    const close = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        setMenu('');
        menuTrigger.current?.focus();
      }
      if (e.key === 'Tab') {
        setMenu('');
        menuTrigger.current?.focus();
      }
    };
    window.addEventListener('keydown', close, true);
    return () => window.removeEventListener('keydown', close, true);
  }, [menu]);
  const item = (d: Dialog) => (
    <div key={d.id} className={'chat-item' + (d.id === active ? ' selected' : '') + (menu === d.id ? ' menu-open' : '')}>
      {editing === d.id ? (
        <RenameField
          d={d}
          done={async t => {
            if (t && t !== d.title) await onRename(d.id, t);
            setEditing('');
          }}
        />
      ) : (
        <>
          <button
            className={'chat-open' + (naming.includes(d.id) ? ' naming' : '')}
            title={d.title + (status[d.id] ? ' · ' + STATUS[status[d.id]].label : '')}
            aria-busy={naming.includes(d.id)}
            onClick={() => onOpen(d.id)}
          >
            {status[d.id] && <StatusMark s={status[d.id]} />}
            {naming.includes(d.id) ? (
              <span className="chat-title-skeleton" role="status" aria-label="Складаємо назву" />
            ) : (
              <span key={d.title} className="chat-title">
                {d.title}
              </span>
            )}
            <small>
              {d.unread && d.id !== active ? <b className="unread-dot" aria-label="Новий звіт" /> : null}
              {when(at(d), now)}
            </small>
          </button>
          <button
            className="icon kebab"
            title="Дії"
            aria-haspopup="menu"
            aria-expanded={menu === d.id}
            onClick={e => {
              menuTrigger.current = e.currentTarget;
              const r = e.currentTarget.getBoundingClientRect();
              setPos({top: r.bottom + 236 > window.innerHeight ? r.top - 240 : r.bottom + 4, left: r.right - 220});
              setMenu(menu === d.id ? '' : d.id);
            }}
          >
            <Ic i={MoreVert} />
          </button>
        </>
      )}
      {menu === d.id && (
        <div
          className="chat-menu"
          role="menu"
          style={pos}
          onKeyDown={e => {
            if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
            e.preventDefault();
            const items = [...e.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];
            const index = items.indexOf(document.activeElement as HTMLButtonElement);
            const next =
              e.key === 'Home'
                ? 0
                : e.key === 'End'
                  ? items.length - 1
                  : (index + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
            items[next]?.focus();
          }}
        >
          {onPin && (
            <button
              role="menuitem"
              onClick={() => {
                setMenu('');
                onPin(d, !d.pinned);
              }}
            >
              <Ic i={PushPin} /> {d.pinned ? 'Відкріпити' : 'Закріпити'}
            </button>
          )}
          {onShare && (
            <button
              role="menuitem"
              onClick={() => {
                setMenu('');
                onShare(d);
              }}
            >
              <Ic i={Share} /> Поділитися
            </button>
          )}
          <button
            role="menuitem"
            onClick={() => {
              setMenu('');
              setEditing(d.id);
            }}
          >
            <Ic i={Edit} /> Перейменувати
          </button>
          <button
            role="menuitem"
            disabled={naming.includes(d.id)}
            title="Назву запропонує модель для заголовків вашого профілю"
            onClick={() => {
              setMenu('');
              onAutoTitle(d.id);
            }}
          >
            <Ic i={AutoAwesome} /> Назвати автоматично
          </button>
          <button
            role="menuitem"
            className="danger"
            disabled={(busy && d.id === active) || ['running', 'approval', 'question'].includes(status[d.id] ?? '')}
            onClick={() => {
              setMenu('');
              onDelete(d);
            }}
          >
            <Ic i={Trash2} /> Видалити
          </button>
        </div>
      )}
    </div>
  );
  if (loading)
    return (
      <nav className="chat-list" aria-busy="true" aria-label="Завантажуємо чати">
        {[0, 1, 2, 3, 4].map(i => (
          <div key={i} className="chat-item chat-item-skeleton">
            <span className="chat-title-skeleton" style={{maxWidth: [150, 120, 170, 100, 140][i]}} />
          </div>
        ))}
      </nav>
    );
  const t = q.trim().toLowerCase();
  if (t) {
    const ready = results && results.q === t,
      found = ready ? results.r.titles : dialogs.filter(d => d.title.toLowerCase().includes(t));
    const msgs = ready ? results.r.messages : [];
    return (
      <ScrollFade>
        <div className="chat-group">Назви: {found.length}</div>
        {found.map(item)}
        <div className="chat-group">У повідомленнях{ready ? ': ' + msgs.length : ''}</div>
        {!ready && (searching || t.length >= 2) && (
          <div className="chat-item chat-item-skeleton">
            <span className="chat-title-skeleton" style={{maxWidth: 160}} />
          </div>
        )}
        {msgs.map((m, i) => (
          <button key={m.id + i} className={'msg-hit' + (m.id === active ? ' selected' : '')} onClick={() => onOpen(m.id)} title={m.title}>
            <span className="msg-hit-title">
              {m.title}
              <small>
                {m.role === 'user' ? 'ви' : 'агент'}
                {m.ts ? ' · ' + when(m.ts, now) : ''}
              </small>
            </span>
            <span className="msg-hit-snip">{snip(m.snippet)}</span>
          </button>
        ))}
        {ready && !found.length && !msgs.length && (
          <p className="hint chat-empty">Нічого не знайдено. Пошук бере слова цілком; для початку слова додайте «*», напр. «гриб*».</p>
        )}
      </ScrollFade>
    );
  }
  return (
    <ScrollFade>
      {groups.map(
        ([g, list]) =>
          list.length > 0 && (
            <React.Fragment key={g}>
              <div className="chat-group">{g}</div>
              {list.map(item)}
            </React.Fragment>
          )
      )}
      {!dialogs.some(d => d.pinned || now - at(d) < 8 * HOUR) && (
        <p className="hint chat-empty">Немає свіжих чатів. Почніть новий кнопкою «+».</p>
      )}
      {(old.length > 0 || (archiveTotal ?? 0) > 0) && (
        <>
          <button
            className={'chat-group archive-toggle' + (archive ? ' open' : '')}
            aria-expanded={archive || activeOld}
            onClick={() => setArchive(!archive)}
          >
            <span>Архів</span>
            <small>{archiveTotal ?? old.length}</small>
            <Ic i={ChevronDown} size={18} />
          </button>
          {(archive ? old : old.filter(d => d.id === active)).map(item)}
          {archive && archiveMore && (
            <button
              className="load-more"
              disabled={moreLoading}
              aria-busy={moreLoading}
              title="Показати ще"
              aria-label="Показати ще чати"
              onClick={onMore}
            >
              {moreLoading ? <span className="chat-title-skeleton" /> : <Ic i={MoreHoriz} />}
            </button>
          )}
        </>
      )}
    </ScrollFade>
  );
}

/** Chat list without a visible scrollbar: a fade at the bottom (and top once scrolled) shows there is more. */
function ScrollFade({children}: {children: React.ReactNode}) {
  const ref = useRef<HTMLElement>(null),
    [fade, setFade] = useState('');
  const measure = () => {
    const n = ref.current;
    if (!n) return;
    const top = n.scrollTop > 4,
      bottom = n.scrollHeight - n.scrollTop - n.clientHeight > 4;
    setFade((top ? ' fade-top' : '') + (bottom ? ' fade-bottom' : ''));
  };
  useEffect(() => {
    measure();
    const n = ref.current;
    if (!n) return;
    const ro = new ResizeObserver(measure);
    ro.observe(n);
    [...n.children].forEach(c => ro.observe(c));
    const mo = new MutationObserver(() => {
      [...n.children].forEach(c => ro.observe(c));
      measure();
    });
    mo.observe(n, {childList: true, subtree: true});
    return () => {
      ro.disconnect();
      mo.disconnect();
    };
  }, []);
  return (
    <nav ref={ref} className={'chat-list' + fade} onScroll={measure}>
      {children}
    </nav>
  );
}

/** Search toggle in the "Чати" header: the icon sits left of "+", the field slides out to the left over the label. */
export function ChatSearch({q, setQ, open, setOpen}: {q: string; setQ: (q: string) => void; open: boolean; setOpen: (o: boolean) => void}) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (open) input.current?.focus();
  }, [open]);
  const close = () => {
    setQ('');
    setOpen(false);
  };
  return (
    <div className={'chat-search' + (open ? ' open' : '')}>
      <input
        ref={input}
        placeholder="Пошук чатів"
        aria-label="Пошук чатів"
        tabIndex={open ? 0 : -1}
        aria-hidden={!open}
        value={q}
        onChange={e => setQ(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Escape') {
            e.stopPropagation();
            close();
          }
        }}
        onBlur={() => {
          if (!q.trim()) setOpen(false);
        }}
      />
      <button
        className="icon"
        title={open ? 'Закрити пошук (Esc)' : 'Пошук чатів (Ctrl+K)'}
        aria-label={open ? 'Закрити пошук' : 'Пошук чатів'}
        aria-expanded={open}
        onMouseDown={e => e.preventDefault()}
        onClick={() => (open ? close() : setOpen(true))}
      >
        <Ic i={open ? X : SearchIcon} />
      </button>
    </div>
  );
}

export type ChatStatus = 'running' | 'approval' | 'question' | 'done' | 'error' | 'stopped';
const STATUS: Record<ChatStatus, {label: string; icon?: IconT}> = {
  running: {label: 'агент працює'},
  approval: {label: 'потрібен ваш дозвіл', icon: FrontHand},
  question: {label: 'агент чекає на відповідь', icon: HelpIcon},
  done: {label: 'відповідь готова, ще не переглянута', icon: CheckCircle},
  error: {label: 'завершилось з помилкою', icon: ErrorIcon},
  stopped: {label: 'зупинено, ще не переглянуто', icon: StopCircle},
};
/** Small state mark before a chat title (the open chat shows its state in the chat itself). */
function StatusMark({s}: {s: ChatStatus}) {
  const m = STATUS[s];
  return (
    <span className={'chat-status st-' + s} role="img" aria-label={m.label}>
      {m.icon ? <Ic i={m.icon} size={16} fill={s !== 'stopped'} /> : <i />}
    </span>
  );
}

function RenameField({d, done}: {d: Dialog; done: (t: string) => void}) {
  const [v, setV] = useState(d.title),
    [saving, setSaving] = useState(false),
    [error, setError] = useState('');
  const ref = useRef<HTMLInputElement>(null),
    locked = useRef(false);
  useEffect(() => {
    ref.current?.focus();
    ref.current?.select();
  }, []);
  const submit = async (cancel = false) => {
    if (locked.current) return;
    locked.current = true;
    setSaving(true);
    setError('');
    try {
      await done(cancel ? '' : v.trim());
    } catch (e) {
      locked.current = false;
      setSaving(false);
      setError(String(e).replace(/^Error: /, ''));
      ref.current?.focus();
    }
  };
  return (
    <div className="chat-rename-wrap" aria-busy={saving}>
      <input
        ref={ref}
        className="chat-rename"
        value={v}
        maxLength={120}
        readOnly={saving}
        aria-label="Нова назва чату"
        aria-invalid={!!error}
        onChange={e => setV(e.target.value)}
        onKeyDown={e => {
          if (e.nativeEvent.isComposing) return;
          if (e.key === 'Enter') {
            e.preventDefault();
            void submit();
          }
          if (e.key === 'Escape') {
            e.stopPropagation();
            void submit(true);
          }
        }}
        onBlur={() => {
          void submit();
        }}
      />
      {saving && <small role="status">Зберігаємо назву…</small>}
      {error && (
        <small className="error" role="alert">
          {error}
        </small>
      )}
    </div>
  );
}

/** Hermes marks matches as >>>word<<<: render them bold. */
function snip(s: string) {
  return s.split(/(>>>[\s\S]*?<<<)/).map((p, i) => (p.startsWith('>>>') ? <b key={i}>{p.slice(3, -3)}</b> : p));
}

function when(t: number, now: number) {
  if (!t) return '';
  const s = now - t;
  if (s < 60) return 'щойно';
  if (s < HOUR) return Math.floor(s / 60) + ' хв';
  if (s < 24 * HOUR) return new Date(t * 1000).toLocaleTimeString('uk-UA', {hour: '2-digit', minute: '2-digit'});
  return new Date(t * 1000).toLocaleDateString('uk-UA', {day: '2-digit', month: '2-digit'});
}

/** M3 basic dialog for confirming chat deletion (replaces native confirm). */
export function ConfirmDelete({d, onCancel, onConfirm}: {d: Dialog; onCancel: () => void; onConfirm: () => Promise<void>}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const modalRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    modalRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
    return () => {
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onCancel();
      if (e.key === 'Tab') {
        const buttons = [...(modalRef.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])];
        const first = buttons[0],
          last = buttons[buttons.length - 1];
        if (!first) {
          e.preventDefault();
          modalRef.current?.focus();
        } else if (e.shiftKey && (document.activeElement === first || !modalRef.current?.contains(document.activeElement))) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && (document.activeElement === last || !modalRef.current?.contains(document.activeElement))) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener('keydown', f);
    return () => window.removeEventListener('keydown', f);
  }, [busy, onCancel]);
  return (
    <div
      className="overlay"
      onMouseDown={e => {
        if (e.target === e.currentTarget && !busy) onCancel();
      }}
    >
      <div
        ref={modalRef}
        tabIndex={-1}
        className="modal narrow"
        role="alertdialog"
        aria-modal="true"
        aria-busy={busy}
        aria-label="Видалити чат"
      >
        <h2>Видалити чат?</h2>
        <p>«{d.title}» буде видалено разом з історією в Shroom і прикріпленими файлами. Скасувати це неможливо.</p>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        {busy && (
          <p className="hint" role="status">
            Видаляємо чат та його файли. Зачекайте…
          </p>
        )}
        <div>
          <button disabled={busy} onClick={onCancel}>
            Скасувати
          </button>
          <button
            className="send danger"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError('');
              try {
                await onConfirm();
              } catch (e) {
                setError(String(e).replace(/^Error: /, ''));
                setBusy(false);
              }
            }}
          >
            {busy ? 'Видаляємо…' : 'Видалити'}
          </button>
        </div>
      </div>
    </div>
  );
}
