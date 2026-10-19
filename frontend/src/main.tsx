import React, {useEffect, useState, useRef} from 'react';
import {createRoot} from 'react-dom/client';
import '@fontsource-variable/inter';
import './AgentActivity.css';
import {AgentActivity, applyActivity, ActivityStep} from './AgentActivity';
import {SessionLoading} from './SessionLoading';
import './style.css';
import './ColorPalettes.css';
import {RequestCard, Interaction} from './RequestCard';
import {ChatBackground} from './Backgrounds';
import {
  Ic,
  Diamond,
  SettingsIcon,
  LogOut,
  FileText,
  Paperclip,
  SquareSlash,
  Square,
  ArrowUp,
  Plus,
  Inventory,
  Edit,
  Lightbulb,
  MoreHoriz,
  MenuIcon,
  UserIcon,
  Schedule,
} from './Icons';
import {useSlash, SlashMenu} from './Perms';
import {Typewriter} from './Typewriter';
import {BusyActions, QueueList, availableActions, BusyMode, Queued} from './BusyComposer';
import {api, setCsrf, clearCache, Login, User} from './Auth';
const Settings = React.lazy(() => import('./Settings').then(m => ({default: m.Settings})));
import {FeedbackHost, toast} from './Feedback';
import {Logo} from './Logo';
import {Markdown} from './Markdown';
import {MessageItem} from './MessageItem';
import {WakeWindow, AsleepBanner, BridgeState, isAsleepText} from './BridgeWake';
import {ShareDialog, SharedChat, captureShareLink, pendingShare, clearShare} from './Share';
captureShareLink();
import {notify, notifyOn, notifyPref, notifySupported, NotifyOffer, registerWorker} from './Notify';
import {ModelSwitch, Runtime} from './ModelSwitch';
const Artifacts = React.lazy(() => import('./Artifacts').then(m => ({default: m.Artifacts})));
const Tasks = React.lazy(() => import('./Tasks').then(m => ({default: m.Tasks})));
import {CronReport, parseReport} from './CronReport';
import {parseNotice, SystemNotice} from './SystemNotice';
import {LimitsBadge} from './Limits';
import {initTheme, syncTheme} from './Theme';
initTheme();
import {ChatList, ChatSearch, ConfirmDelete, Dialog, ChatStatus} from './ChatList';
import {AttachmentCards, FileCard} from './Attachments';
type Attachment = FileCard & {id: string; size: number};
type Message = {
  role?: string;
  text?: string;
  content?: unknown;
  type?: string;
  row_id?: number;
  timestamp?: number;
  files?: FileCard[];
  display_kind?: string;
};
function userMatches(ms: Message[], text: string) {
  return ms.filter(m => m.role === 'user' && content(m).trim().startsWith(text.slice(0, 200))).length;
}
const REF_LINE = /^@(file|image):[^\n]*$/gm;
function rawText(m: Message): string {
  return (
    m.text ?? (typeof m.content === 'string' ? m.content : Array.isArray(m.content) ? m.content.map(x => x.text ?? '').join('\n') : '')
  );
}
/** Files of a user message that still exist: edit/regenerate attach them again, so the new turn keeps them. */
const keptFiles = (m: Message) => (m.files ?? []).filter(f => f.id && !f.missing).map(f => f.id as string);
function content(m: Message): string {
  let value = rawText(m);
  if (m.role === 'user') {
    value = value.split('\n--- Attached Context ---')[0];
    // with `files` the refs render as attachment cards under the text; without (older shape) as a short label
    value = m.files
      ? value
          .replace(REF_LINE, '')
          .replace(/^\[screenshot\]$/gm, '')
          .trim()
      : value
          .replace(
            /@(file|image):([^\n]+)/g,
            (_all, kind: string, path: string) => (kind === 'image' ? '[зображення] ' : '[файл] ') + path.trim().split('/').pop()
          )
          .replace(/\n\[screenshot\]/g, '');
  }
  return value;
}
// Streamed text of the running turn minus the parts Hermes already persisted as separate assistant messages
// (a turn with tool calls stores each segment on its own, while deltas keep accumulating in one buffer).
function unseen(progress: string, msgs: Message[]): string {
  let lastUser = -1;
  msgs.forEach((m, i) => {
    if (m.role === 'user') lastUser = i;
  });
  let rest = progress.trim();
  for (const m of msgs.slice(lastUser + 1)) {
    if (m.role !== 'assistant') continue;
    const c = content(m).trim();
    if (!c) continue;
    const i = rest.indexOf(c);
    if (i >= 0) rest = (rest.slice(0, i) + rest.slice(i + c.length)).trim();
  }
  return rest;
}
const preload = () => {
  import('./Settings');
  import('./Artifacts');
  import('./Tasks');
};
if ('requestIdleCallback' in window) (window as any).requestIdleCallback(() => setTimeout(preload, 3000));
const STARTERS: [typeof FileText, string, string][] = [
  [Edit, 'Написати текст', 'Допоможи написати лист: '],
  [FileText, 'Розібрати документ', 'Стисло перекажи вкладений файл і виділи головне.'],
  [Lightbulb, 'Обміркувати ідею', 'Давай обміркуємо ідею: '],
  [SquareSlash, 'Розібратися з кодом', 'Поясни, що робить цей код, і знайди помилки:\n'],
];
const greeting = () => {
  const h = new Date().getHours();
  return h < 5 ? 'Доброї ночі' : h < 12 ? 'Доброго ранку' : h < 18 ? 'Доброго дня' : 'Доброго вечора';
};
function App({user, onLogout}: {user: User; onLogout: () => void}) {
  const [view, setView] = useState<'chat' | 'settings' | 'artifacts' | 'tasks'>('chat');
  const [perms, setPerms] = useState<Record<string, boolean>>({});
  const canCron = !!perms['feature:cron'];
  useEffect(() => {
    api('/me/permissions')
      .then(setPerms)
      .catch(() => {});
  }, []);
  // Per-chat model/reasoning: picks made in this tab (dialog id -> runtime; '' = the draft) override the list's copy.
  const [runtimes, setRuntimes] = useState<Record<string, Runtime>>({}),
    [chatProvider, setChatProvider] = useState('');
  const runtimesRef = useRef(runtimes);
  runtimesRef.current = runtimes;
  const [drawer, setDrawer] = useState(false),
    [searchOpen, setSearchOpen] = useState(false),
    [chatQuery, setChatQuery] = useState('');
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && k === 'k') {
        e.preventDefault();
        setDrawer(true);
        setSearchOpen(true);
        setTimeout(() => (document.querySelector('.chat-search input') as HTMLInputElement | null)?.focus(), 50);
      } else if ((e.ctrlKey || e.metaKey) && e.shiftKey && k === 'o') {
        e.preventDefault();
        document.querySelector<HTMLButtonElement>('.side-label button')?.click();
      } else if (k === 'escape') setDrawer(false);
    };
    window.addEventListener('keydown', f);
    return () => window.removeEventListener('keydown', f);
  }, []);
  const [deleting, setDeleting] = useState<Dialog | null>(null);
  const storeKey = 'hermes-dialog-' + user.id;
  const [outputs, setOutputs] = useState<{dialog: string; cmd: string; text: string}[]>([]);
  const [dialogs, setDialogs] = useState<Dialog[]>([]),
    [active, setActive] = useState(localStorage.getItem(storeKey) ?? ''),
    [messages, setMessages] = useState<Message[]>([]),
    [text, setText] = useState(''),
    [attachments, setAttachments] = useState<Attachment[]>([]),
    [busy, setBusy] = useState(false),
    [uploading, setUploading] = useState(false),
    [error, setErrorRaw] = useState(''),
    [progress, setProgress] = useState('');
  // A sleeping agent is shown once, by the banner above the composer: its 503 text never becomes a second error line.
  const setError = (v: string | ((prev: string) => string)) =>
    setErrorRaw(prev => {
      const next = typeof v === 'function' ? v(prev) : v;
      return isAsleepText(next) ? prev : next;
    });
  const [activity, setActivity] = useState<ActivityStep[]>([]);
  const [notifyOffer, setNotifyOffer] = useState(false);
  const [sharing, setSharing] = useState<Dialog | null>(null),
    [shareToken, setShareToken] = useState(pendingShare);
  // Sleeping agent: woken behind a window on load; a banner when it falls asleep while the tab is open.
  const [waking, setWaking] = useState(false),
    [asleep, setAsleep] = useState(false),
    asleepRef = useRef(false);
  asleepRef.current = asleep;
  useEffect(() => {
    api('/me/bridge')
      .then(r => {
        if (r.state === 'asleep' || r.state === 'starting') setWaking(true);
      })
      .catch(() => {});
    const f = () => {
      asleepRef.current = true;
      setAsleep(true);
    };
    window.addEventListener('hermes-asleep', f);
    return () => window.removeEventListener('hermes-asleep', f);
  }, []);
  function woke(s: BridgeState) {
    setWaking(false);
    if (s === 'ready') {
      setAsleep(false);
      asleepRef.current = false;
      if (activeRef.current) history(activeRef.current).catch(() => {});
      window.dispatchEvent(new Event('hermes-awake'));
    }
  }
  useEffect(() => registerWorker(id => setActive(id)), []);
  const activityRequest = useRef('');
  const input = useRef<HTMLTextAreaElement>(null);
  const fieldSizing = typeof CSS !== 'undefined' && CSS.supports('field-sizing', 'content');
  useEffect(() => {
    const t = input.current;
    if (!t || fieldSizing) return;
    t.style.height = '0';
    t.style.height = Math.min(t.scrollHeight, Math.round(window.innerHeight * 0.6)) + 'px';
  }, [text]);
  const LONG_PASTE = 2000,
    LONG_LINES = 40;
  const stamp = () => new Date().toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '-');
  function onPaste(e: React.ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(e.clipboardData.files);
    if (files.length) {
      e.preventDefault();
      upload(
        files.map((f, i) =>
          f.type.startsWith('image/') && /^image\.\w+$/i.test(f.name)
            ? new File([f], `clipboard-${stamp()}${i ? '-' + i : ''}.${f.type.split('/')[1].replace('jpeg', 'jpg')}`, {type: f.type})
            : f
        )
      );
      return;
    }
    const t = e.clipboardData.getData('text/plain');
    if (t.length >= LONG_PASTE || t.split('\n').length >= LONG_LINES) {
      e.preventDefault();
      upload([new File([t], `pasted-text-${stamp()}.txt`, {type: 'text/plain'})]);
    }
  }
  const [requests, setRequests] = useState<Interaction[]>([]),
    [state, setState] = useState('complete'),
    [notice, setNotice] = useState(''),
    [connected, setConnected] = useState(true);
  const busyRef = useRef(false);
  const pendingSend = useRef<{id: string; text: string; files: string[]} | null>(null);
  // Optimistic echo of the message being sent: shown at once (no empty page / skeleton flash while a new chat is created),
  // hidden as soon as history holds one more matching user message than when it was sent.
  const [pending, setPending] = useState<{text: string; files: Attachment[]; seen: number; posted: boolean} | null>(null);
  const pendingRef = useRef(pending);
  pendingRef.current = pending;
  const picker = useRef<HTMLInputElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const [dialogsLoaded, setDialogsLoaded] = useState(false);
  // Gradual loading: the archive comes in pages (ARCHIVE_PAGE more per click), the chat in pages of MSG_PAGE messages.
  const ARCHIVE_PAGE = 20,
    MSG_PAGE = 30;
  const archiveLimit = useRef(ARCHIVE_PAGE),
    activeRef = useRef('');
  const [archive, setArchive] = useState({total: 0, more: false}),
    [unreadTotal, setUnreadTotal] = useState(0),
    [moreLoading, setMoreLoading] = useState(false);
  async function refresh() {
    const r = await api(`/dialogs?limit=${archiveLimit.current}&include=${encodeURIComponent(activeRef.current)}`);
    setDialogs(r.items);
    setArchive({total: r.archive_total, more: r.more});
    setUnreadTotal(r.unread ?? 0);
    setDialogsLoaded(true);
  }
  async function moreArchive() {
    setMoreLoading(true);
    archiveLimit.current += ARCHIVE_PAGE;
    try {
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setMoreLoading(false);
    }
  }
  const searchDialogs = async (q: string) => await api(`/dialogs/search?q=${encodeURIComponent(q)}`);
  // Reload / chat switch: until this dialog's history arrives show a skeleton, never the empty "new chat" page or the previous chat.
  const [loadedFor, setLoadedFor] = useState('');
  const loadingChat = !!active && loadedFor !== active;
  // Polling returns the same history most of the time: keep the old array so nothing re-renders (scroll, selection).
  function keepMessages(next: Message[]) {
    setMessages(prev => (prev.length === next.length && JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
  }
  const tail = useRef(MSG_PAGE),
    [olderMore, setOlderMore] = useState(false),
    [olderLoading, setOlderLoading] = useState(false);
  const keepBottom = useRef<number | null>(null);
  async function history(id: string) {
    try {
      const h = await api(`/dialogs/${id}/history?tail=${tail.current}`);
      if (id === activeRef.current) {
        keepMessages(h.messages ?? []);
        setOlderMore(!!h.more);
      }
    } finally {
      setLoadedFor(id);
    }
  }
  async function loadOlder() {
    const c = chatBox.current;
    if (!active || olderLoading) return;
    keepBottom.current = c ? c.scrollHeight - c.scrollTop : null;
    stick.current = false;
    setOlderLoading(true);
    tail.current += MSG_PAGE;
    try {
      await history(active);
    } catch (e) {
      setError(String(e));
    } finally {
      setOlderLoading(false);
    }
  }
  React.useLayoutEffect(() => {
    const c = chatBox.current;
    if (c && keepBottom.current !== null) {
      c.scrollTop = c.scrollHeight - keepBottom.current;
      keepBottom.current = null;
    }
  }, [messages]);
  function startNew() {
    setRuntimes(r => {
      const {['']: _, ...rest} = r;
      return rest;
    });
    setActive('');
    setMessages([]);
    setText('');
    localStorage.removeItem(storeKey);
    setTimeout(() => input.current?.focus(), 0);
  }
  async function newDialog(title?: string) {
    try {
      const draft = runtimesRef.current[''];
      const d = await api('/dialogs', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          ...(title ? {title} : {}),
          ...(draft?.model ? {provider: draft.provider, model: draft.model} : {}),
          ...(draft?.effort ? {effort: draft.effort} : {}),
        }),
      });
      if (d.runtime)
        setRuntimes(r => {
          const {['']: _, ...rest} = r;
          return {...rest, [d.id]: d.runtime};
        });
      if (creating.current) setLoadedFor(d.id);
      setActive(d.id);
      await refresh();
      return d.id;
    } catch (e) {
      setError(String(e));
      return '';
    }
  }
  const [naming, setNaming] = useState<string[]>([]);
  // Chats keep working in the background: the sidebar shows each other chat's state (asked every 4 s).
  const creating = useRef(false);
  // True while send() waits for POST /chat: /sync may still say `complete` then, which must not flip the composer to idle.
  const posting = useRef(false);
  const [chatStatus, setChatStatus] = useState<Record<string, ChatStatus>>({});
  const prevStatus = useRef<Record<string, ChatStatus>>({}),
    prevTurn = useRef<Record<string, string>>({}),
    statusSeen = useRef(false);
  useEffect(() => {
    let live = true,
      timer: ReturnType<typeof setTimeout>;
    async function tick() {
      try {
        if (!document.hidden || notifyOn(user.id)) {
          const raw: Record<string, {status: ChatStatus; turn: string}> = await api(
            `/dialogs/activity?turns=1&exclude=${encodeURIComponent(activeRef.current)}`
          );
          if (!live) return;
          const st: Record<string, ChatStatus> = Object.fromEntries(Object.entries(raw).map(([k, v]) => [k, v.status]));
          for (const [id, {status: s, turn}] of Object.entries(raw)) {
            const was = prevTurn.current[id];
            if (statusSeen.current && was !== s + turn && id !== activeRef.current) {
              const t = dialogsRef.current.find(d => d.id === id)?.title ?? 'чат';
              const msg =
                s === 'done'
                  ? 'відповідь готова'
                  : s === 'approval'
                    ? 'агент просить дозволу на команду'
                    : s === 'question'
                      ? 'агент чекає на вашу відповідь'
                      : s === 'error'
                        ? 'завершилось з помилкою'
                        : '';
              if (msg) {
                toast(`«${t}»: ${msg}`, s === 'error' ? 'error' : 'ok');
                notify(user.id, t, msg[0].toUpperCase() + msg.slice(1), 'chat-' + id, () => setActive(id));
              }
            }
          }
          prevStatus.current = st;
          prevTurn.current = Object.fromEntries(Object.entries(raw).map(([k, v]) => [k, v.status + v.turn]));
          statusSeen.current = true;
          setChatStatus(st);
        }
      } catch {
      } finally {
        if (live) timer = setTimeout(tick, document.hidden ? 15000 : 4000);
      }
    }
    tick();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, []);
  // Drop the echo once history holds the sent message. Idle is only a delayed fallback: the new dialog's first /sync
  // reports `complete` before the turn row exists, so busy flips false mid-send and an instant drop flashes the empty page.
  useEffect(() => {
    if (!pending) return;
    if (userMatches(messages, pending.text) > pending.seen) {
      setPending(null);
      return;
    }
    if (pending.posted && !busy) {
      const t = setTimeout(() => setPending(null), 4000);
      return () => clearTimeout(t);
    }
  }, [messages, busy, pending]);
  const dialogsRef = useRef<Dialog[]>([]);
  dialogsRef.current = dialogs;
  async function autoTitle(id: string) {
    setNaming(n => [...n, id]);
    try {
      const r = await api(`/dialogs/${id}/title`, {method: 'POST'});
      setDialogs(ds => ds.map(d => (d.id === id ? {...d, title: r.title, title_source: r.title_source} : d)));
      toast('Нова назва: «' + r.title + '»');
    } catch (e) {
      toast(String(e).replace(/^Error: /, ''), 'error');
    } finally {
      setNaming(n => n.filter(x => x !== id));
    }
  }
  useEffect(() => {
    refresh().catch(e => {
      setDialogsLoaded(true);
      setError(String(e));
    });
    const t = setInterval(() => {
      if (!document.hidden) refresh().catch(() => {});
    }, 60000);
    return () => clearInterval(t);
  }, []);
  const unreadReports = unreadTotal;
  useEffect(() => {
    activeRef.current = active;
    tail.current = MSG_PAGE;
    setOlderMore(false);
    if (!creating.current) {
      setBusy(false);
      busyRef.current = false;
      setState('complete');
      setRequests([]);
      setNotice('');
      setPending(null);
    }
    creating.current = false;
    if (active && dialogsLoaded && !dialogs.some(d => d.id === active)) refresh().catch(() => {});
    if (active) {
      localStorage.setItem(storeKey, active);
      history(active).catch(e => setError(String(e)));
    }
    setAttachments([]);
    setProgress('');
    setActivity([]);
    activityRequest.current = '';
  }, [active]);
  useEffect(() => {
    if (!active) return;
    let cancelled = false,
      cursor = 0,
      epoch = '',
      lastState = '',
      lastHist = 0,
      settleUntil = 0,
      lastReq: string | null | undefined = undefined;
    let timer: ReturnType<typeof setTimeout>;
    const wake = () => {
      if (!document.hidden && !cancelled) {
        clearTimeout(timer);
        poll();
      }
    };
    document.addEventListener('visibilitychange', wake);
    async function poll() {
      clearTimeout(timer);
      try {
        const s = await api(`/dialogs/${active}/sync?after=${cursor}&epoch=${epoch}`);
        if (cancelled) return;
        const now = Date.now(),
          live = ['running', 'waiting'].includes(s.state);
        {
          const title = dialogsRef.current.find(d => d.id === active)?.title || 'Shroom',
            was = lastState,
            fresh = lastReq !== undefined && s.request_id && s.request_id !== lastReq;
          if (s.state === 'complete' && (['running', 'waiting'].includes(was) || fresh)) {
            notify(user.id, title, 'Відповідь готова', 'chat-' + active);
            if (notifySupported() && !notifyPref(user.id) && Notification.permission !== 'denied') setNotifyOffer(true);
          } else if (s.state === 'waiting' && ((was && was !== 'waiting') || fresh))
            notify(user.id, title, 'Агент чекає на вашу відповідь', 'chat-' + active);
          else if (s.state === 'error' && (['running', 'waiting'].includes(was) || fresh))
            notify(user.id, title, 'Завершилось з помилкою', 'chat-' + active);
          lastReq = s.request_id ?? null;
        }
        if (s.state !== lastState) {
          if (lastState) settleUntil = now + 6000;
          lastState = s.state;
        }
        const segment = s.events.some((e: any) => e.type === 'message.complete' || e.type === 'tool.complete');
        if (s.reset || segment || pendingRef.current || now < settleUntil || now - lastHist > (live ? 3000 : 15000)) {
          lastHist = now;
          const h = await api(`/dialogs/${active}/history?tail=${tail.current}`);
          if (cancelled) return;
          if (active === activeRef.current) {
            keepMessages(h.messages ?? []);
            setOlderMore(!!h.more);
            setLoadedFor(active);
          }
        }
        if (s.reset) setProgress('');
        cursor = s.cursor;
        epoch = s.epoch;
        setConnected(true);
        if (asleepRef.current) {
          asleepRef.current = false;
          setAsleep(false);
        }
        setError(e => (e.startsWith('Зʼєднання втрачено.') ? '' : e));
        setState(s.state);
        const working = ['running', 'waiting'].includes(s.state) || posting.current;
        setBusy(working);
        busyRef.current = working;
        setRequests(s.open_requests);
        setNotice(s.notice);
        if (s.title)
          setDialogs(ds =>
            ds.some(d => d.id === active && d.title !== s.title) ? ds.map(d => (d.id === active ? {...d, title: s.title} : d)) : ds
          );
        const activityReset = s.reset || activityRequest.current !== s.request_id;
        activityRequest.current = s.request_id;
        setActivity(previous =>
          applyActivity(
            activityReset ? [] : previous,
            s.events.filter((e: any) => e.seq > (s.activity_since ?? 0))
          )
        );
        for (const event of s.events) {
          if (event.type === 'message.start') setProgress('');
          if (event.type === 'message.delta') setProgress(p => p + (event.payload?.text ?? event.payload?.delta ?? ''));
          if (event.type === 'background.complete')
            setOutputs(o =>
              o.some(x => x.cmd === 'bg:' + event.payload?.task_id)
                ? o
                : [
                    ...o,
                    {
                      dialog: active,
                      cmd: 'bg:' + event.payload?.task_id,
                      text:
                        (bgTasks.current[event.payload?.task_id] ? 'Завдання: ' + bgTasks.current[event.payload?.task_id] + '\n\n' : '') +
                        (event.payload?.text ?? ''),
                    },
                  ]
            );
          if (event.type === 'btw.complete')
            setOutputs(o =>
              o.some(x => x.cmd === 'btw:' + event.payload?.task_id)
                ? o
                : [
                    ...o,
                    {
                      dialog: active,
                      cmd: 'btw:' + event.payload?.task_id,
                      text: 'Питання: ' + (event.payload?.question ?? '') + '\n\n' + (event.payload?.text ?? ''),
                    },
                  ]
            );
        }
      } catch (e) {
        if (!cancelled) {
          if (asleepRef.current) {
            setLoadedFor(active);
          } else {
            setConnected(false);
            setState('error');
            setError('Зʼєднання втрачено. Відновлюємо без повторного запуску. ' + String(e));
          }
        }
      } finally {
        if (!cancelled)
          timer = setTimeout(
            poll,
            asleepRef.current ? 15000 : document.hidden ? (busyRef.current ? 3000 : 10000) : busyRef.current ? 500 : 1500
          );
      }
    }
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', wake);
    };
  }, [active]);
  async function answer(request: Interaction, result: object) {
    try {
      await api(`/dialogs/${active}/requests/${request.id}/respond`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({result}),
      });
      setRequests(rs => rs.filter(r => r.id !== request.id));
      setError('');
    } catch (e) {
      setError(String(e));
    }
  }
  // Follow new output only while the reader is at the bottom; never yank them back from history.
  const chatBox = useRef<HTMLElement>(null),
    stick = useRef(true);
  const onChatScroll = () => {
    const c = chatBox.current;
    if (c) stick.current = c.scrollHeight - c.scrollTop - c.clientHeight < 120;
  };
  const contentKey =
    activity.map(s => s.id + ':' + (s.finished ?? '')).join(',') +
    ':' +
    messages.length +
    ':' +
    (messages.length ? content(messages[messages.length - 1]).length : 0) +
    ':' +
    (progress?.length ?? 0) +
    ':' +
    outputs.length;
  useEffect(() => {
    const c = chatBox.current;
    if (!c) return;
    if (!messages.length && !busy) {
      c.scrollTop = 0;
      return;
    }
    if (stick.current) c.scrollTop = c.scrollHeight;
  }, [contentKey]);
  useEffect(() => {
    stick.current = true;
    const c = chatBox.current;
    if (c)
      requestAnimationFrame(() => {
        c.scrollTop = active ? c.scrollHeight : 0;
      });
  }, [active]);
  // A new approval/clarify card blocks the agent until answered (5 min timeout): always bring it fully into view,
  // even when the reader scrolled up. Without this the card landed below the fold and timed out unseen.
  const requestKey = requests.map(r => r.id).join(',');
  useEffect(() => {
    if (!requestKey) return;
    requestAnimationFrame(() => {
      const cards = chatBox.current?.querySelectorAll('.interaction');
      const last = cards?.[cards.length - 1];
      if (last) last.scrollIntoView({block: 'nearest'});
    });
  }, [requestKey]);
  async function upload(files: File[]) {
    setError('');
    setUploading(true);
    try {
      const id = active || (await newDialog());
      if (!id) return;
      const uploaded: Attachment[] = [];
      for (const f of files) {
        const form = new FormData();
        form.append('file', f);
        const got: Attachment = await api(`/dialogs/${id}/files`, {method: 'POST', body: form});
        if (got.mime === 'text/plain') {
          const t = await f.text();
          got.preview = t.slice(0, 400);
          got.lines = t.split('\n').length - (t.endsWith('\n') ? 1 : 0);
        }
        uploaded.push(got);
      }
      setAttachments(a => [...a, ...uploaded]);
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
    }
  }
  async function send(override?: string, fresh = false) {
    const text = override ?? textRef.current;
    if (busy || uploading || asleepRef.current || (!text.trim() && !attachments.length)) return;
    stick.current = true;
    if (override === undefined && text.trim().startsWith('/') && !attachments.length) {
      await command(text.trim());
      return;
    }
    setError('');
    setBusy(true);
    setProgress('Shroom працює…');
    const sentFiles = fresh ? [] : attachments;
    const echo = text.trim();
    setPending({text: echo, files: sentFiles, seen: fresh ? 0 : userMatches(messages, echo), posted: false});
    if (override === undefined) {
      setText('');
      setAttachments([]);
    }
    const restore = () => {
      setPending(null);
      if (override === undefined) {
        setText(t => t || text);
        setAttachments(a => (a.length ? a : sentFiles));
      }
    };
    try {
      if (fresh || !active) creating.current = true;
      const id = (!fresh && active) || (await newDialog());
      if (!id) {
        restore();
        setBusy(false);
        setProgress('');
        return;
      }
      const files = sentFiles.map(a => a.id);
      const previous = pendingSend.current;
      const key =
        previous && previous.text === text && JSON.stringify(previous.files) === JSON.stringify(files) ? previous.id : crypto.randomUUID();
      pendingSend.current = {id: key, text, files};
      posting.current = true;
      await api(`/dialogs/${id}/chat`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text, files, request_id: key, stream: false}),
      });
      pendingSend.current = null;
      setPending(p => p && {...p, posted: true});
      setState('running');
      setBusy(true);
      busyRef.current = true;
      await refresh();
    } catch (e) {
      restore();
      setError('Надсилання не підтверджене. Перевірте стан; повтор тієї ж чернетки використовує той самий ID. ' + String(e));
      setBusy(false);
    } finally {
      posting.current = false;
    }
  }
  async function command(cmd: string) {
    setError('');
    const nm = cmd.match(/^\/(new|reset|clear)(?:\s+([\s\S]*))?$/);
    if (nm) {
      const id = await newDialog(nm[2]?.trim() || undefined);
      if (id) {
        setText('');
        setMessages([]);
      }
      return;
    }
    try {
      const id = active || (await newDialog());
      if (!id) return;
      const r = await api(`/dialogs/${id}/command`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({command: cmd, request_id: crypto.randomUUID()}),
      });
      setText('');
      if (r.type === 'new_dialog') {
        await refresh();
        setActive(r.id);
        return;
      }
      if (r.type === 'retitled') await refresh();
      if (r.type === 'history_changed') await history(id);
      if (['output', 'retitled', 'history_changed'].includes(r.type)) setOutputs(o => [...o, {dialog: id, cmd, text: r.output}]);
      else {
        setOutputs(o => [...o, {dialog: id, cmd, text: r.notice || 'Запущено'}]);
        setState('running');
        setBusy(true);
      }
    } catch (e) {
      setError(String(e).replace(/^Error: /, ''));
    }
  }
  const textRef = useRef(text);
  textRef.current = text;
  const slash = useSlash(text);
  function pick(t: string) {
    setText('/' + t.trim().replace(/^\//, '') + ' ');
  }
  const [stopping, setStopping] = useState(false);
  useEffect(() => {
    if (!busy) setStopping(false);
  }, [busy]);
  async function stop() {
    if (stopping) return;
    if (!active) {
      setBusy(false);
      setProgress('');
      return;
    }
    setStopping(true);
    setProgress('Зупиняємо…');
    try {
      await api(`/dialogs/${active}/stop`, {method: 'POST'});
    } catch (e) {
      setStopping(false);
      setError(String(e));
    }
  }
  // While the agent works the composer stays open: queue (client-side, drained after a completed turn), steer, background, btw.
  const actions = availableActions(user.role === 'admin' ? {'cmd:steer': true, 'cmd:bg': true, 'cmd:btw': true} : perms);
  const modeKey = 'hermes-busy-action-' + user.id,
    queueKey = 'hermes-queue-' + user.id;
  const [busyMode, setBusyModeState] = useState<BusyMode>(() => (localStorage.getItem(modeKey) as BusyMode) || 'queue');
  const mode: BusyMode = actions.some(a => a.mode === busyMode) ? busyMode : 'queue';
  function setBusyMode(m: BusyMode) {
    setBusyModeState(m);
    localStorage.setItem(modeKey, m);
  }
  const [queues, setQueuesState] = useState<Record<string, Queued[]>>(() => {
    try {
      return JSON.parse(localStorage.getItem(queueKey) || '{}');
    } catch {
      return {};
    }
  });
  function setQueue(id: string, items: Queued[]) {
    setQueuesState(q => {
      const n = {...q};
      if (items.length) n[id] = items;
      else delete n[id];
      localStorage.setItem(queueKey, JSON.stringify(n));
      return n;
    });
  }
  const queue = active ? (queues[active] ?? []) : [];
  const bgTasks = useRef<Record<string, string>>({});
  const [sideSending, setSideSending] = useState(false);
  async function runBusy(m: BusyMode) {
    const t = textRef.current.trim();
    if (!t || !active || sideSending) return;
    if (m === 'queue') {
      setQueue(active, [...queue, {id: crypto.randomUUID(), text: t}]);
      setText('');
      return;
    }
    setSideSending(true);
    setError('');
    try {
      const r = await api(`/dialogs/${active}/side`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({mode: m, text: t}),
      });
      setText('');
      if (m === 'steer') {
        if (r.status === 'rejected') {
          setQueue(active, [...queue, {id: crypto.randomUUID(), text: t}]);
          toast('Агент уже завершує відповідь, тому повідомлення поставлено в чергу');
        } else {
          setOutputs(o => [...o, {dialog: active, cmd: 'steer', text: t}]);
          toast('Уточнення передано: агент врахує його після поточного кроку');
        }
      } else if (m === 'bg') {
        if (r.task_id) bgTasks.current[r.task_id] = t;
        toast('Запущено у фоні: відповідь зʼявиться в цьому чаті');
      } else toast('Бічне питання прийнято: відповідь зʼявиться тут окремо');
    } catch (e) {
      setError(String(e).replace(/^Error: /, ''));
    } finally {
      setSideSending(false);
    }
  }
  async function sendQueued(q: Queued) {
    if (!active) return;
    setQueue(
      active,
      (queues[active] ?? []).filter(x => x.id !== q.id)
    );
    if (q.text.startsWith('/')) await command(q.text);
    else await send(q.text);
  }
  const prevBusy = useRef(false);
  useEffect(() => {
    const was = prevBusy.current;
    prevBusy.current = busy;
    if (was && !busy && state === 'complete' && queue.length && !uploading) void sendQueued(queue[0]);
  }, [busy, state]);
  useEffect(() => {
    prevBusy.current = false;
  }, [active]);
  function submit() {
    if (asleepRef.current) return; // the agent must be woken with the banner button first
    if (busy) void runBusy(mode);
    else void send();
  }
  // Messages as shown + what each one may do: copy always; edit (cmd:undo) on the user's own messages; regenerate
  // (cmd:retry) on the latest reply only. Both are native rewinds, so only while idle.
  const shown = messages.filter(m => ['user', 'assistant'].includes(m.role ?? '') && (content(m) || m.files?.length));
  const canEdit = user.role === 'admin' || !!perms['cmd:undo'],
    canRetry = user.role === 'admin' || !!perms['cmd:retry'];
  const lastUserIdx = shown.reduce((a, m, i) => (m.role === 'user' && !parseReport(content(m)) && !parseNotice(m, content(m)) ? i : a), -1);
  function msgProps(i: number) {
    const m = shown[i],
      t = content(m),
      user = m.role === 'user';
    const endOfTurn = !user && (i === shown.length - 1 || shown[i + 1].role === 'user');
    let turnText: string | undefined;
    if (endOfTurn) {
      let k = i;
      while (k > 0 && shown[k - 1].role === 'assistant') k--;
      turnText = shown
        .slice(k, i + 1)
        .map(content)
        .join('\n\n');
    }
    const idle = !busy && !pending && !loadingChat && !uploading;
    return {
      m,
      text: t,
      turnText,
      showActions: user || endOfTurn,
      canEdit,
      canRetry: canRetry && endOfTurn && i === shown.length - 1 && lastUserIdx >= 0 && !!shown[lastUserIdx].row_id,
      idle,
      laterTurns: i < lastUserIdx,
      onEdit: (row: number, text: string) => rewind(row, text, 'edit', keptFiles(m)),
      onRetry: () => {
        const u = shown[lastUserIdx];
        if (u?.row_id) void rewind(u.row_id, content(u), 'retry', keptFiles(u));
      },
    };
  }
  async function rewind(row: number, text: string, kind: 'edit' | 'retry', files: string[] = []): Promise<boolean> {
    if (!active || busy) return false;
    setError('');
    stick.current = true;
    try {
      posting.current = true;
      setBusy(true);
      busyRef.current = true;
      setProgress('Shroom працює…');
      await api(`/dialogs/${active}/chat`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text, files, request_id: crypto.randomUUID(), rewind: kind, rewind_row_id: row}),
      });
      setMessages(ms => {
        const cut = ms.findIndex(x => x.row_id === row);
        return cut < 0 ? ms : [...ms.slice(0, cut), {role: 'user', text, timestamp: Date.now() / 1000, files: ms[cut].files}];
      });
      setState('running');
      setActivity([]);
      return true;
    } catch (e) {
      setBusy(false);
      busyRef.current = false;
      setProgress('');
      setError(String(e).replace(/^Error: /, ''));
      return false;
    } finally {
      posting.current = false;
    }
  }
  // Open chat: tell the user (when the tab is hidden) that the reply is ready or the agent waits; offer it once.
  const activeTitle = active ? (dialogs.find(d => d.id === active)?.title ?? 'Новий діалог') : 'Новий чат';
  return (
    <div
      className={'layout' + (drawer ? ' drawer-open' : '')}
      onClickCapture={e => {
        if (drawer && (e.target as HTMLElement).closest('.chat-open,.selector,.side-label button')) setTimeout(() => setDrawer(false), 0);
      }}
    >
      <div className="scrim" onClick={() => setDrawer(false)} />
      <aside className="side">
        <div className="side-top">
          <div className="brand-mini">
            <Logo size={18} /> SHROOM
          </div>
          <button className="selector" title={'Налаштування · ' + user.username + ' · ' + user.profile} onClick={() => setView('settings')}>
            <span>
              <Ic i={SettingsIcon} /> Налаштування
            </span>
          </button>
          <button className="selector" title="Артефакти: зображення й тексти з діалогів" onClick={() => setView('artifacts')}>
            <span>
              <Ic i={Inventory} /> Артефакти
            </span>
          </button>
          {canCron && (
            <button className="selector" title="Завдання за розкладом, зі звітами в чат" onClick={() => setView('tasks')}>
              <span>
                <Ic i={Schedule} /> Завдання
                {unreadReports > 0 && (
                  <b className="badge" aria-label={unreadReports + ' нових звітів'}>
                    {unreadReports}
                  </b>
                )}
              </span>
            </button>
          )}
        </div>
        <div className="side-chats">
          <div className={'side-label' + (searchOpen ? ' searching' : '')}>
            <span>Чати</span>
            <ChatSearch q={chatQuery} setQ={setChatQuery} open={searchOpen} setOpen={setSearchOpen} />
            <button className="icon" title="Новий чат (Ctrl+Shift+O)" onClick={startNew}>
              <Ic i={Plus} />
            </button>
          </div>
          <ChatList
            q={chatQuery}
            dialogs={dialogs}
            status={Object.fromEntries(Object.entries(chatStatus).filter(([id]) => id !== active))}
            loading={!dialogsLoaded}
            archiveTotal={archive.total}
            archiveMore={archive.more}
            moreLoading={moreLoading}
            onMore={moreArchive}
            search={searchDialogs}
            active={active}
            busy={busy}
            naming={naming}
            onAutoTitle={autoTitle}
            onOpen={setActive}
            onRename={async (id, title) => {
              await api(`/dialogs/${id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({title})});
              await refresh();
            }}
            onDelete={setDeleting}
            onShare={setSharing}
            onPin={async (d, pinned) => {
              setDialogs(ds => ds.map(x => (x.id === d.id ? {...x, pinned} : x)));
              try {
                await api(`/dialogs/${d.id}`, {
                  method: 'PATCH',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({pinned}),
                });
                toast(pinned ? 'Чат закріплено' : 'Чат відкріплено');
              } catch (e) {
                toast(String(e).replace(/^Error: /, ''), 'error');
              }
              await refresh().catch(() => {});
            }}
          />
        </div>
        <button className="logout" onClick={onLogout}>
          <Ic i={LogOut} /> {user.impersonated_by ? 'Повернутися до свого акаунта' : 'Вийти'}
        </button>
      </aside>
      <main>
        <ChatBackground />
        {waking && <WakeWindow onDone={woke} />}
        {sharing && <ShareDialog dialog={sharing.id} title={sharing.title} onClose={() => setSharing(null)} />}
        {shareToken && !waking && (
          <SharedChat
            token={shareToken}
            onClose={() => {
              clearShare();
              setShareToken('');
            }}
            onCopied={async id => {
              clearShare();
              setShareToken('');
              await refresh();
              setActive(id);
            }}
          />
        )}
        <React.Suspense
          fallback={
            <div className="overlay settings-overlay">
              <div className="settings-window loading" aria-busy="true">
                <aside>
                  <div className="skeleton-block">
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                  </div>
                </aside>
                <div className="settings-main">
                  <div className="skeleton-block">
                    <i />
                    <i />
                    <i />
                    <i />
                  </div>
                </div>
              </div>
            </div>
          }
        >
          {view === 'settings' && <Settings me={user} onClose={() => setView('chat')} />}
          {deleting && (
            <ConfirmDelete
              d={deleting}
              onCancel={() => setDeleting(null)}
              onConfirm={async () => {
                await api(`/dialogs/${deleting.id}`, {method: 'DELETE'});
                if (deleting.id === active) {
                  setActive('');
                  setMessages([]);
                }
                setDeleting(null);
                await refresh();
              }}
            />
          )}
          {view === 'artifacts' && <Artifacts onClose={() => setView('chat')} openDialog={id => setActive(id)} />}
          {view === 'tasks' && (
            <Tasks
              onClose={() => setView('chat')}
              openDialog={id => {
                setActive(id);
                refresh();
              }}
              ask={async t => {
                if (busy) throw new Error('Дочекайтеся завершення відповіді в поточному чаті');
                setView('chat');
                startNew();
                setAttachments([]);
                await send(t, true);
              }}
            />
          )}
        </React.Suspense>
        <header>
          <button className="icon menu-btn" title="Меню" aria-label="Меню" onClick={() => setDrawer(true)}>
            <Ic i={MenuIcon} />
          </button>
          <div className="chat-head" title={activeTitle}>
            <span className="dot" />{' '}
            {active && (naming.includes(active) || !dialogsLoaded) ? (
              <span
                className="chat-title-skeleton head"
                role="status"
                aria-label={dialogsLoaded ? 'Складаємо назву' : 'Завантажуємо назву'}
              />
            ) : (
              <span key={activeTitle} className="chat-title">
                {activeTitle}
              </span>
            )}
          </div>
          <div className="header-right">
            <ModelSwitch
              busy={busy}
              dialog={active}
              runtime={runtimes[active] ?? dialogs.find(d => d.id === active)?.runtime ?? null}
              onRuntime={r => setRuntimes(x => ({...x, [active]: r}))}
              onProvider={setChatProvider}
            />
            <LimitsBadge cacheKey={user.id} provider={chatProvider} refreshKey={String(busy)} />
          </div>
        </header>
        {user.impersonated_by && (
          <div className="warning impersonating" role="status">
            <Ic i={UserIcon} size={16} />
            <span>
              Ви в порталі як <b>{user.username}</b> (вхід адміністратора {user.impersonated_by}). Дії записуються в журнал.
            </span>
            <button
              onClick={async () => {
                try {
                  await api('/auth/impersonate/stop', {method: 'POST'});
                } catch {}
                location.assign('/');
              }}
            >
              Повернутися до свого акаунта
            </button>
          </div>
        )}
        {(!connected || notice) && (
          <div className="warning" role="status">
            {connected ? '' : 'Відновлення зʼєднання з агентом…'}
            {notice && <strong>{notice}</strong>}
          </div>
        )}
        <section
          className="chat"
          ref={chatBox}
          onScroll={onChatScroll}
          onDragOver={e => e.preventDefault()}
          onDrop={e => {
            e.preventDefault();
            if (!busy) upload(Array.from(e.dataTransfer.files));
          }}
        >
          {loadingChat && (
            <div className="chat-skeleton" role="status" aria-busy="true" aria-label="Завантажуємо чат">
              <div className="sk-user">
                <i />
              </div>
              <div className="skeleton-block">
                <i />
                <i />
                <i />
              </div>
              <div className="sk-user">
                <i />
              </div>
              <div className="skeleton-block">
                <i />
                <i />
              </div>
            </div>
          )}
          {!messages.length && !loadingChat && !pending && (
            <div className="empty">
              <div className="glyph">
                <Logo size={56} />
              </div>
              <h1>
                {greeting()}, {user.username}
              </h1>
              <p>З чого почнемо?</p>
              <div className="starters">
                {STARTERS.map(([icon, title, prompt]) => (
                  <button
                    key={title}
                    onClick={() => {
                      setText(prompt);
                      setTimeout(() => {
                        const t = input.current;
                        if (t) {
                          t.focus();
                          t.setSelectionRange(prompt.length, prompt.length);
                        }
                      }, 0);
                    }}
                  >
                    <Ic i={icon} />
                    <b>{title}</b>
                    <small>{prompt}</small>
                  </button>
                ))}
              </div>
              <p className="hint empty-tips">
                <Ic i={FileText} size={16} /> Довгий текст і скріншоти з буфера стають файлами · <Ic i={SquareSlash} size={16} /> «/» —
                команди
              </p>
            </div>
          )}
          {!loadingChat && olderMore && (
            <button
              className="load-more older"
              disabled={olderLoading}
              aria-busy={olderLoading}
              title="Показати старіші повідомлення"
              aria-label="Показати старіші повідомлення"
              onClick={() => void loadOlder()}
            >
              {olderLoading ? (
                <span className="chat-title-skeleton" />
              ) : (
                <>
                  <Ic i={MoreHoriz} /> <span>Старіші повідомлення</span>
                </>
              )}
            </button>
          )}
          {!loadingChat &&
            shown.map((m, i) => {
              const r = m.role === 'user' ? parseReport(content(m)) : null;
              if (r) return <CronReport key={i} r={r} />;
              const n = parseNotice(m, content(m));
              return n ? <SystemNotice key={m.row_id ?? i} n={n} /> : <MessageItem key={m.row_id ?? i} {...msgProps(i)} />;
            })}
          {pending && !loadingChat && (
            <article className="user pending" aria-busy="true">
              <label>ВИ</label>
              {pending.text && <div>{pending.text}</div>}
              <AttachmentCards files={pending.files} />
            </article>
          )}
          {outputs
            .filter(o => o.dialog === active)
            .map((o, i) => (
              <article key={'o' + i} className="assistant cmd-out">
                <label>
                  <Ic i={SquareSlash} size={12} />{' '}
                  {o.cmd.startsWith('btw:')
                    ? 'Бічне питання'
                    : o.cmd.startsWith('bg:')
                      ? 'Фонове завдання'
                      : o.cmd === 'steer'
                        ? 'Уточнення під час роботи'
                        : o.cmd}
                </label>
                <div>{o.text}</div>
              </article>
            ))}
          {requests.map(r => (
            <RequestCard key={r.id} request={r} answer={answer} />
          ))}
          {busy &&
            progress &&
            progress !== 'Shroom працює…' &&
            (progress === 'Зупиняємо…' || progress.startsWith('Інструмент:') || unseen(progress, messages)) && (
              <article className="assistant">
                <label className="assistant-name-row">SHROOM · {state === 'waiting' ? 'ОЧІКУЄ ВАС' : 'ПРАЦЮЄ'}</label>
                <div>
                  {progress && !progress.startsWith('Інструмент:') && progress !== 'Shroom працює…' && progress !== 'Зупиняємо…' ? (
                    <Typewriter text={unseen(progress, messages)} />
                  ) : (
                    <span className="thinking">{progress || 'Очікуємо відповідь…'}</span>
                  )}
                </div>
              </article>
            )}
          <AgentActivity key={active + ':' + activityRequest.current} steps={activity} busy={busy} state={state} connected={connected} />
          <div ref={bottom} />
        </section>
        <footer>
          {asleep && !busy && <AsleepBanner onWake={() => setWaking(true)} />}
          {notifyOffer && <NotifyOffer uid={user.id} onDone={() => setNotifyOffer(false)} />}
          {error && (
            <div className="error" role="alert">
              {error}
            </div>
          )}
          {attachments.length > 0 && (
            <AttachmentCards files={attachments} onRemove={f => setAttachments(x => x.filter(a => a.id !== f.id))} />
          )}
          <QueueList items={queue} idle={!busy} onChange={items => active && setQueue(active, items)} onSendNow={q => void sendQueued(q)} />
          <div className="composer">
            <SlashMenu items={slash.items} index={slash.index} pick={pick} />
            <textarea
              aria-label="Повідомлення"
              placeholder={
                busy
                  ? 'Наступне повідомлення… Ctrl + Enter — ' + (actions.find(a => a.mode === mode)?.label ?? 'У чергу').toLowerCase()
                  : 'Напишіть повідомлення… або перетягніть файл сюди'
              }
              value={text}
              onChange={e => setText(e.target.value)}
              ref={input}
              rows={1}
              onPaste={onPaste}
              onKeyDown={e => {
                const n = slash.items.length;
                if (n && e.key === 'ArrowDown') {
                  e.preventDefault();
                  slash.setIndex((slash.index + 1) % n);
                  return;
                }
                if (n && e.key === 'ArrowUp') {
                  e.preventDefault();
                  slash.setIndex((slash.index - 1 + n) % n);
                  return;
                }
                const exact = n && slash.items.some(it => '/' + it.text.trim().replace(/^\//, '') === text.trim());
                if (n && (e.key === 'Tab' || (e.key === 'Enter' && !exact && !e.ctrlKey && !e.metaKey && !text.includes(' ')))) {
                  e.preventDefault();
                  pick(slash.items[slash.index].text);
                  return;
                }
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey || (text.startsWith('/') && !e.shiftKey))) {
                  e.preventDefault();
                  submit();
                }
              }}
            />
            <div className="controls">
              <div>
                <button disabled={busy || uploading} onClick={() => picker.current?.click()}>
                  <Ic i={Paperclip} /> Файл / зображення
                </button>
                <input
                  ref={picker}
                  hidden
                  type="file"
                  multiple
                  accept=".txt,.md,.csv,.json,.log,.png,.jpg,.jpeg,.webp"
                  onChange={e => {
                    upload(Array.from(e.target.files ?? []));
                    e.target.value = '';
                  }}
                />
              </div>
              {busy ? (
                <BusyActions
                  actions={actions}
                  mode={mode}
                  onMode={setBusyMode}
                  canRun={!!text.trim() && !!active}
                  sending={sideSending}
                  run={m => void runBusy(m)}
                  stop={stop}
                  stopping={stopping}
                />
              ) : (
                <button
                  className="send"
                  disabled={uploading || asleep || (!text.trim() && !attachments.length)}
                  title={asleep ? 'Спершу розбудіть агента' : undefined}
                  onClick={() => send()}
                >
                  {uploading ? (
                    'Завантаження…'
                  ) : (
                    <>
                      Надіслати <Ic i={ArrowUp} />
                    </>
                  )}
                </button>
              )}
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}
function Root() {
  const [user, setUser] = useState<User | null>(null),
    [checked, setChecked] = useState(false);
  useEffect(() => {
    api('/auth/me')
      .then(r => {
        setCsrf(r.csrf);
        setUser(r.user);
      })
      .catch(() => {})
      .finally(() => setChecked(true));
    const out = () => setUser(null);
    window.addEventListener('hermes-logout', out);
    return () => window.removeEventListener('hermes-logout', out);
  }, []);
  async function logout() {
    if (user?.impersonated_by) {
      try {
        await api('/auth/impersonate/stop', {method: 'POST'});
      } catch {}
      clearCache();
      location.assign('/');
      return;
    }
    try {
      await api('/auth/logout', {method: 'POST'});
    } catch {}
    clearCache();
    setUser(null);
  }
  useEffect(() => {
    if (user) syncTheme();
  }, [user]);
  if (!checked) return <SessionLoading />;
  if (!user) return <Login onLogin={setUser} />;
  if (location.pathname !== '/') history.replaceState(null, '', '/');
  if (user.must_enroll)
    return (
      <React.Suspense fallback={null}>
        <Settings me={user} onClose={() => location.reload()} />
      </React.Suspense>
    );
  return <App key={user.id} user={user} onLogout={logout} />;
}
createRoot(document.getElementById('root')!).render(
  <>
    <Root />
    <FeedbackHost />
  </>
);
