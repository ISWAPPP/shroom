import React, {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {ask as confirm, toast} from './Feedback';
import {api} from './Auth';
import {Ic, X, Trash2, Edit, Play, Pause, History, OpenInNew, Schedule, Send, TriangleAlert} from './Icons';
import {Markdown} from './Markdown';

type Job = {
  id: string;
  name: string;
  prompt: string;
  schedule: string;
  enabled: boolean;
  state: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
  last_error: boolean;
  created_at: string | null;
  dialog: string | null;
  unread: number;
  note: string | null;
  runs: string[];
  repeat?: {times: number | null; completed: number} | null;
};
type Data = {jobs: Job[]; limits: {max_jobs: number; min_minutes: number} | null; scheduler_ok: boolean};

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('uk-UA', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}) : '';
const runAt = (file: string) => when(file.slice(0, 10) + 'T' + file.slice(11, 19).replace(/-/g, ':') + 'Z');
const hm = (h: string, m: string) => h.padStart(2, '0') + ':' + m.padStart(2, '0');
/** Hermes stores schedules in its own notation ("every 120m", "0 9 * * *"); show the common shapes in words. */
export function humanSchedule(s: string): string {
  let m = /^every (\d+)m$/.exec(s);
  if (m) {
    const n = +m[1];
    return n % 1440 === 0
      ? n === 1440
        ? 'щодня'
        : `кожні ${n / 1440} дн.`
      : n % 60 === 0
        ? n === 60
          ? 'щогодини'
          : `кожні ${n / 60} год`
        : `кожні ${n} хв`;
  }
  m = /^(\d{1,2}) (\d{1,2}) \* \* \*$/.exec(s);
  if (m) return 'щодня о ' + hm(m[2], m[1]);
  m = /^(\d{1,2}) (\d{1,2}) \* \* 1-5$/.exec(s);
  if (m) return 'у будні о ' + hm(m[2], m[1]);
  m = /^(\d{1,2}) (\d{1,2}) \* \* ([0-6])$/.exec(s);
  if (m)
    return ['щонеділі', 'щопонеділка', 'щовівторка', 'щосереди', 'щочетверга', 'щопʼятниці', 'щосуботи'][+m[3]] + ' о ' + hm(m[2], m[1]);
  m = /^once at (.+)$/.exec(s);
  if (m) return 'один раз ' + m[1];
  return s;
}
const EXAMPLE =
  'Щоранку о 9:00 перевіряй ціни на вживаний Samsung Galaxy S24 Ultra (OLX, Prom, Rozetka) і надсилай короткий звіт: найдешевші пропозиції зі станом, ціною й посиланням.';

/** Scheduled jobs (native Hermes cron). Creation is a request to Hermes in a new chat; reports land in that chat. */
export function Tasks({
  onClose,
  openDialog,
  ask,
}: {
  onClose: () => void;
  openDialog: (id: string) => void;
  ask: (text: string) => Promise<void>;
}) {
  const [data, setData] = useState<Data | null>(null),
    [error, setError] = useState(''),
    [text, setText] = useState(''),
    [preparing, setPreparing] = useState(false);
  const [editing, setEditing] = useState(''),
    [history, setHistory] = useState(''),
    [view, setView] = useState<{job: Job; file: string} | null>(null),
    [pending, setPending] = useState('');
  const load = () =>
    api('/cron')
      .then(d => {
        setData(d);
        setError('');
      })
      .catch(e => setError(String(e).replace(/^Error: /, '')));
  useEffect(() => {
    load();
    const t = setInterval(() => {
      if (!document.hidden) load();
    }, 15000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      if (e.key === 'Escape') view ? setView(null) : onClose();
    };
    window.addEventListener('keydown', f);
    return () => window.removeEventListener('keydown', f);
  }, [view]);
  const active = data?.jobs.filter(j => j.enabled).length ?? 0,
    full = !!data?.limits && active >= data.limits.max_jobs;
  async function submit() {
    const t = text.trim();
    if (!t || preparing) return;
    setPreparing(true);
    setError('');
    try {
      await api('/cron/prepare', {method: 'POST'});
      await ask('Створи заплановане завдання (звіти портал сам надсилатиме в цей чат, доставку не налаштовуй): ' + t);
    } catch (e) {
      setError(String(e).replace(/^Error: /, ''));
      setPreparing(false);
    }
  }
  async function act(j: Job, action: 'pause' | 'resume' | 'run') {
    setPending(j.id + action);
    try {
      await api(`/cron/${j.id}/action`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({action})});
      toast(
        action === 'run'
          ? `«${j.name}» запущено. Звіт прийде в чат завдання.`
          : action === 'pause'
            ? `«${j.name}» призупинено`
            : `«${j.name}» знову за розкладом`
      );
      await load();
    } catch (e) {
      toast(String(e).replace(/^Error: /, ''), 'error');
    } finally {
      setPending('');
    }
  }
  async function remove(j: Job) {
    if (!(await confirm(`Видалити завдання «${j.name}»? Розклад зупиниться; чат зі звітами залишиться.`, {danger: true, ok: 'Видалити'})))
      return;
    setPending(j.id + 'del');
    try {
      await api(`/cron/${j.id}`, {method: 'DELETE'});
      toast('Завдання видалено');
      await load();
    } catch (e) {
      toast(String(e).replace(/^Error: /, ''), 'error');
    } finally {
      setPending('');
    }
  }
  return createPortal(
    <div
      className="overlay settings-overlay"
      onMouseDown={e => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="settings-window tasks" role="dialog" aria-label="Завдання">
        <main className="settings-main">
          <button className="close icon" title="Закрити (Esc)" onClick={onClose}>
            <Ic i={X} />
          </button>
          <div className="detail-pane">
            <div className="page-head">
              <h1>Завдання</h1>
              <p className="hint">
                Hermes виконує доручення за розкладом і надсилає звіт у чат завдання, де можна відповісти чи уточнити.
                {data?.limits &&
                  ` Активних: ${active} з ${data.limits.max_jobs}, не частіше ніж раз на годину. Запуски враховуються у ваших витратах.`}
              </p>
            </div>
            {data && !data.scheduler_ok && (
              <div className="warning" role="status">
                <Ic i={TriangleAlert} size={16} /> Планувальник Hermes зараз не відповідає: завдання збережені, але не запускаються.
                Повідомте адміністратора.
              </div>
            )}
            <div className="card task-ask">
              <label htmlFor="task-ask">
                <b>Що й коли робити?</b>
              </label>
              <textarea
                id="task-ask"
                rows={3}
                value={text}
                maxLength={4000}
                placeholder={'Наприклад: ' + EXAMPLE}
                disabled={preparing || full}
                onChange={e => setText(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    submit();
                  }
                }}
              />
              <div className="row task-ask-row">
                <span className="hint">
                  {full
                    ? `Досягнуто ліміту ${data!.limits!.max_jobs} активних завдань: призупиніть або видаліть одне.`
                    : 'Hermes відкриє новий чат, створить розклад і підтвердить його. Ctrl+Enter — надіслати.'}
                </span>
                {!text && !full && (
                  <button className="text" onClick={() => setText(EXAMPLE)}>
                    Приклад
                  </button>
                )}
                <button className="send" disabled={!text.trim() || preparing || full} aria-busy={preparing} onClick={submit}>
                  <Ic i={Send} /> {preparing ? 'Готуємо агента…' : 'Доручити'}
                </button>
              </div>
            </div>
            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            {!data ? (
              <div className="skeleton-block" aria-busy="true">
                <i />
                <i />
                <i />
              </div>
            ) : !data.jobs.length ? (
              <p className="hint">
                Поки немає завдань. Опишіть доручення вище або попросіть Hermes у будь-якому чаті: «щопонеділка надсилай…».
              </p>
            ) : (
              <div className="task-list">
                {data.jobs.map(j => (
                  <section key={j.id} className={'task' + (j.enabled ? '' : ' off')}>
                    {editing === j.id ? (
                      <EditJob
                        job={j}
                        done={async changed => {
                          setEditing('');
                          if (changed) await load();
                        }}
                      />
                    ) : (
                      <>
                        <div className="task-head">
                          <b title={j.name}>{j.name}</b>
                          <span className={'badge' + (j.enabled ? '' : ' muted')}>
                            {j.enabled ? 'Активне' : j.state === 'completed' ? 'Завершене' : 'Призупинене'}
                          </span>
                          {j.unread > 0 && <span className="badge new">{j.unread} нов.</span>}
                        </div>
                        <div className="task-meta">
                          <span title={j.schedule}>
                            <Ic i={Schedule} size={16} /> {humanSchedule(j.schedule)}
                          </span>
                          {j.enabled && j.next_run_at && <span>Наступний: {when(j.next_run_at)}</span>}
                          {j.last_run_at && (
                            <span className={j.last_status && j.last_status !== 'ok' ? 'bad' : ''}>
                              Останній: {when(j.last_run_at)}
                              {j.last_status && j.last_status !== 'ok' ? ' · помилка' : ''}
                            </span>
                          )}
                        </div>
                        {j.note && (
                          <div className="warning task-note">
                            <Ic i={TriangleAlert} size={16} /> {j.note}
                          </div>
                        )}
                        <p className="task-prompt">{j.prompt}</p>
                        <div className="task-actions">
                          {j.dialog && (
                            <button
                              className="text"
                              onClick={() => {
                                openDialog(j.dialog!);
                                onClose();
                              }}
                            >
                              <Ic i={OpenInNew} /> Чат зі звітами
                            </button>
                          )}
                          <button
                            className="text"
                            disabled={!j.runs.length}
                            onClick={() => setHistory(history === j.id ? '' : j.id)}
                            aria-expanded={history === j.id}
                          >
                            <Ic i={History} /> Історія ({j.runs.length})
                          </button>
                          <span className="spacer" />
                          <button
                            className="icon"
                            title="Запустити зараз"
                            disabled={!!pending}
                            aria-busy={pending === j.id + 'run'}
                            onClick={() => act(j, 'run')}
                          >
                            <Ic i={Play} />
                          </button>
                          {j.state !== 'completed' && (
                            <button
                              className="icon"
                              title={j.enabled ? 'Призупинити' : 'Відновити розклад'}
                              disabled={!!pending}
                              onClick={() => act(j, j.enabled ? 'pause' : 'resume')}
                            >
                              <Ic i={j.enabled ? Pause : Schedule} />
                            </button>
                          )}
                          <button className="icon" title="Змінити" disabled={!!pending} onClick={() => setEditing(j.id)}>
                            <Ic i={Edit} />
                          </button>
                          <button className="icon" title="Видалити" disabled={!!pending} onClick={() => remove(j)}>
                            <Ic i={Trash2} />
                          </button>
                        </div>
                        {history === j.id && (
                          <ul className="task-runs">
                            {j.runs.map(f => (
                              <li key={f}>
                                <button className="text" onClick={() => setView({job: j, file: f})}>
                                  {runAt(f)}
                                </button>
                              </li>
                            ))}
                          </ul>
                        )}
                      </>
                    )}
                  </section>
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
              <b>{view.job.name}</b>
              <span className="hint">{runAt(view.file)}</span>
              <button className="icon" title="Закрити" onClick={() => setView(null)}>
                <Ic i={X} />
              </button>
            </div>
            <RunView job={view.job.id} file={view.file} />
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}

function RunView({job, file}: {job: string; file: string}) {
  const [r, setR] = useState<{answer: string | null; failed: boolean; silent: boolean} | null>(null),
    [err, setErr] = useState('');
  useEffect(() => {
    setR(null);
    api(`/cron/${job}/runs/${file}`)
      .then(setR)
      .catch(e => setErr(String(e).replace(/^Error: /, '')));
  }, [job, file]);
  return (
    <div className="art-text task-run">
      {err ? (
        err
      ) : !r ? (
        <div className="skeleton-block">
          <i />
          <i />
        </div>
      ) : r.answer ? (
        <Markdown text={r.answer} />
      ) : (
        <p className="hint">
          {r.failed ? 'Запуск завершився помилкою.' : 'Нічого нового: Hermes вирішив не надсилати звіт за цей запуск.'}
        </p>
      )}
    </div>
  );
}

function EditJob({job, done}: {job: Job; done: (changed: boolean) => void}) {
  const [name, setName] = useState(job.name),
    [schedule, setSchedule] = useState(job.schedule),
    [prompt, setPrompt] = useState(job.prompt);
  const [saving, setSaving] = useState(false),
    [error, setError] = useState('');
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => {
    first.current?.focus();
  }, []);
  async function save() {
    const body: Record<string, string> = {};
    if (name.trim() !== job.name) body.name = name.trim();
    if (schedule.trim() !== job.schedule) body.schedule = schedule.trim();
    if (prompt.trim() !== job.prompt.trim()) body.prompt = prompt.trim();
    if (!Object.keys(body).length) return done(false);
    setSaving(true);
    setError('');
    try {
      await api(`/cron/${job.id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      toast('Збережено');
      done(true);
    } catch (e) {
      setError(String(e).replace(/^Error: /, ''));
      setSaving(false);
    }
  }
  return (
    <div
      className="task-edit"
      onKeyDown={e => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          done(false);
        }
      }}
    >
      <label>
        Назва
        <input ref={first} value={name} maxLength={120} onChange={e => setName(e.target.value)} />
      </label>
      <label>
        Розклад
        <input value={schedule} maxLength={120} onChange={e => setSchedule(e.target.value)} aria-describedby={'sch-' + job.id} />
      </label>
      <small className="hint" id={'sch-' + job.id}>
        Зараз: {humanSchedule(schedule)}. Формати Hermes: «every 2h», «every day at 9am», «weekdays at 8:30am», «0 9 * * 1» (cron).
      </small>
      <label>
        Що робити
        <textarea rows={4} value={prompt} maxLength={8000} onChange={e => setPrompt(e.target.value)} />
      </label>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <div className="row">
        <button onClick={() => done(false)} disabled={saving}>
          Скасувати
        </button>
        <button className="send" onClick={save} disabled={saving || !name.trim() || !schedule.trim() || !prompt.trim()} aria-busy={saving}>
          {saving ? 'Зберігаємо…' : 'Зберегти'}
        </button>
      </div>
    </div>
  );
}
