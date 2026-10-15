import React, {useEffect, useState} from 'react';
import {api} from './Auth';
import {ask, toast} from './Feedback';

const TITLES = {soul: 'SOUL.md', memory: 'MEMORY.md', user: 'USER.md'};
type Doc = keyof typeof TITLES;
type DocumentData = {document: Doc; content: string; revision: string; limit: number};
type MemoryValues = {
  memory_enabled: boolean;
  user_profile_enabled: boolean;
  write_approval: boolean;
  memory_char_limit: number;
  user_char_limit: number;
  nudge_interval: number;
};
export async function confirmAgentDraft(): Promise<boolean> {
  return (
    !document.querySelector('[data-agent-dirty="true"]') ||
    ask('Відкинути незбережені зміни?', {text: 'Чернетку SOUL.md або памʼяті не буде збережено.', ok: 'Відкинути', danger: true})
  );
}
export function ProfileAgentEditor({
  base,
  soul = true,
  memory = true,
  admin = false,
}: {
  base: string;
  soul?: boolean;
  memory?: boolean;
  admin?: boolean;
}) {
  const available: Doc[] = [...(soul ? ['soul' as Doc] : []), ...(memory ? ['memory' as Doc, 'user' as Doc] : [])];
  const [kind, setKind] = useState<Doc>(available[0] ?? 'soul');
  const [data, setData] = useState<DocumentData | null>(null),
    [text, setText] = useState(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const dirty = !!data && text !== data.content;
  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError('');
    api(`${base}/documents/${kind}`)
      .then(d => {
        if (!cancelled) {
          setData(d);
          setText(d.content);
        }
      })
      .catch(e => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [base, kind]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  async function reload() {
    if (
      dirty &&
      !(await ask('Оновити документ із сервера?', {
        text: 'Спочатку скопіюйте чернетку, якщо хочете зберегти свої зміни. Оновлення замінить текст редактора.',
        ok: 'Оновити',
        danger: true,
      }))
    )
      return;
    setBusy(true);
    setError('');
    try {
      const d = await api(`${base}/documents/${kind}`);
      setData(d);
      setText(d.content);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (!data || busy) return;
    setBusy(true);
    setError('');
    try {
      const d = await api(`${base}/documents/${kind}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({content: text, revision: data.revision}),
      });
      setData(d);
      setText(d.content);
      toast('Документ збережено. Зміни застосуються в новому діалозі.');
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="agent-editor" data-agent-dirty={dirty ? 'true' : 'false'}>
      <div className="card">
        <h3>Особистість і памʼять</h3>
        <p className="hint">
          SOUL.md — характер та інструкції агента. MEMORY.md — його довготривалі нотатки. USER.md — відомості про користувача. Зміни
          діятимуть у нових діалогах; поточний контекст не перезаписується.
        </p>
        <div className="tabs" role="tablist" aria-label="Документи профілю">
          {available.map(k => (
            <button
              role="tab"
              aria-selected={kind === k}
              className={kind === k ? 'on' : ''}
              disabled={busy}
              key={k}
              onClick={async () => {
                if (k === kind) return;
                if (!dirty || (await confirmAgentDraft())) setKind(k);
              }}
            >
              {TITLES[k]}
            </button>
          ))}
        </div>
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        {!data ? (
          !error && (
            <div className="skeleton-block">
              <i />
              <i />
              <i />
            </div>
          )
        ) : (
          <>
            <label className="agent-document-label">
              {TITLES[kind]}
              <textarea
                className="agent-document-text"
                aria-label={`Редактор ${TITLES[kind]}`}
                value={text}
                disabled={busy}
                spellCheck={false}
                onChange={e => setText(e.target.value)}
              />
            </label>
            <div className="row agent-document-meta">
              <span className={Array.from(text).length > data.limit ? 'error' : 'hint'}>
                {Array.from(text).length} / {data.limit} символів{dirty ? ' · незбережені зміни' : ''}
              </span>
              <span className="hint">Попередня версія зберігається автоматично.</span>
            </div>
          </>
        )}
        <div className="actions">
          <button disabled={busy} onClick={reload}>
            Оновити із сервера
          </button>
          <button className="send" disabled={!data || !dirty || busy || Array.from(text).length > (data?.limit ?? 0)} onClick={save}>
            {busy ? 'Зберігаємо…' : 'Зберегти'}
          </button>
        </div>
      </div>
      {admin && <MemoryConfiguration base={base} />}
    </div>
  );
}
function MemoryConfiguration({base}: {base: string}) {
  const [values, setValues] = useState<MemoryValues | null>(null),
    [saved, setSaved] = useState<MemoryValues | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  useEffect(() => {
    let cancelled = false;
    api(`${base}/memory-config`)
      .then(d => {
        if (!cancelled) {
          setValues(d.values);
          setSaved(d.values);
        }
      })
      .catch(e => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [base]);
  const dirty = !!values && JSON.stringify(values) !== JSON.stringify(saved);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty]);
  async function save() {
    if (!values || !saved) return;
    const changes = Object.fromEntries(Object.entries(values).filter(([k, v]) => v !== saved[k as keyof MemoryValues]));
    setBusy(true);
    setError('');
    try {
      const d = await api(`${base}/memory-config`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({changes}),
      });
      setValues(d.values);
      setSaved(d.values);
      toast('Параметри памʼяті збережено для нових діалогів.');
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="card" data-agent-dirty={dirty ? 'true' : 'false'}>
      <h3>Конфігурація памʼяті</h3>
      <p className="hint">Лише для адміністратора. Нативні параметри Hermes, без доступу до ключів або довільного config.yaml.</p>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      {!values ? (
        !error && (
          <div className="skeleton-block">
            <i />
            <i />
          </div>
        )
      ) : (
        <>
          {(
            [
              ['memory_enabled', 'Памʼять агента'],
              ['user_profile_enabled', 'Профіль користувача'],
              ['write_approval', 'Підтвердження записів агента в памʼять'],
            ] as const
          ).map(([k, label]) => (
            <label className="row" key={k}>
              <input type="checkbox" checked={values[k]} disabled={busy} onChange={e => setValues({...values, [k]: e.target.checked})} />
              {label}
            </label>
          ))}
          <div className="row grow">
            {(
              [
                ['memory_char_limit', 'Ліміт MEMORY.md', 100, 20000],
                ['user_char_limit', 'Ліміт USER.md', 100, 20000],
                ['nudge_interval', 'Перегляд памʼяті кожні N кроків (0 — вимкнено)', 0, 100],
              ] as const
            ).map(([k, label, min, max]) => (
              <label key={k}>
                {label}
                <input
                  type="number"
                  min={min}
                  max={max}
                  step={1}
                  value={values[k]}
                  disabled={busy}
                  onChange={e => setValues({...values, [k]: Number(e.target.value)})}
                />
              </label>
            ))}
          </div>
          <div className="actions">
            <button className="send" disabled={!dirty || busy} onClick={save}>
              {busy ? 'Зберігаємо…' : 'Зберегти параметри'}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
