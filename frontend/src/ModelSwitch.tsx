import React, {useEffect, useRef, useState} from 'react';
import {api} from './Auth';
import {toast} from './Feedback';
import {Ic, ChevronDown, Check, Lightbulb} from './Icons';

type Prov = {slug: string; name: string; kind: 'own' | 'shared' | 'owner'; models: string[]};
export type ModelsData = {
  current: {provider: string; model: string};
  providers: Prov[];
  can_switch: boolean;
  can_reason: boolean;
  chat_switch: boolean;
  chat_reason: boolean;
  effort: string;
  efforts: string[];
};
/** A chat's own pick; null fields follow the profile default (Settings > Модель і підписки). */
export type Runtime = {provider: string | null; model: string | null; effort: string | null};
export const EFFORT: Record<string, string> = {
  '': 'Типово',
  none: 'Без міркувань',
  minimal: 'Мінімальні',
  low: 'Низькі',
  medium: 'Середні',
  high: 'Високі',
  xhigh: 'Максимальні',
};
export const GROUP: Record<string, string> = {own: 'Мої підписки', shared: 'Спільна підписка', owner: 'Підключені'};
/** Fired by the defaults card in Settings so the header re-reads the profile default. */
export const MODELS_CHANGED = 'shroom-models-changed';
const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

/** Loads /me/models; while the profile bridge restarts the call fails, so retry and keep the last good data. */
export async function fetchModels(tries = 1): Promise<ModelsData> {
  for (let i = 0; ; i++) {
    try {
      return await api('/me/models');
    } catch (e) {
      if (i >= tries - 1) throw e;
      await sleep(1500);
    }
  }
}

/** Chat header: model and reasoning of THIS chat (native session-scoped switch, no agent restart, other chats keep
 *  theirs). In a draft (no dialog yet) the pick is held by the parent and sent with the dialog creation. */
export function ModelSwitch({
  dialog,
  runtime,
  onRuntime,
  onProvider,
  busy,
}: {
  dialog: string;
  runtime: Runtime | null;
  onRuntime: (r: Runtime) => void;
  onProvider?: (p: string) => void;
  busy: boolean;
}) {
  const [d, setD] = useState<ModelsData | null>(null),
    [failed, setFailed] = useState(false),
    [open, setOpen] = useState<'' | 'model' | 'effort'>('');
  const [prov, setProv] = useState(''),
    [q, setQ] = useState(''),
    [saving, setSaving] = useState(''),
    box = useRef<HTMLDivElement>(null);
  const load = async (tries = 1) => {
    try {
      setD(await fetchModels(tries));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  };
  useEffect(() => {
    load(3);
    const f = () => load(20);
    window.addEventListener(MODELS_CHANGED, f);
    return () => window.removeEventListener(MODELS_CHANGED, f);
  }, []);
  useEffect(() => {
    if (!open) return;
    const f = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen('');
    };
    document.addEventListener('mousedown', f);
    return () => document.removeEventListener('mousedown', f);
  }, [open]);
  const pinned = !!(runtime?.model && runtime?.provider);
  const cur = d ? {provider: pinned ? runtime!.provider! : d.current.provider, model: pinned ? runtime!.model! : d.current.model} : null;
  const effort = runtime?.effort ?? d?.effort ?? '';
  useEffect(() => {
    if (cur?.provider) onProvider?.(cur.provider);
  }, [cur?.provider]);
  if (!d || !cur)
    return failed ? null : (
      <div className="model-switch skeleton" aria-busy="true">
        <i />
        <i />
      </div>
    );
  const all = d.providers,
    curProv = all.find(p => p.slug === cur.provider);
  async function apply(kind: 'model' | 'effort', body: {provider?: string; model?: string; effort?: string}, shown: string) {
    setOpen('');
    setQ('');
    const next: Runtime = {provider: runtime?.provider ?? null, model: runtime?.model ?? null, effort: runtime?.effort ?? null, ...body};
    if (!dialog) {
      onRuntime(next);
      return;
    } // draft: applied when the chat is created
    setSaving(shown);
    try {
      const r = await api(`/dialogs/${dialog}/${kind === 'model' ? 'model' : 'reasoning'}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
      });
      onRuntime(r);
      if (busy) toast('Застосується з наступного повідомлення');
    } catch (e) {
      toast(String(e).replace(/^Error: /, ''), 'error');
    } finally {
      setSaving('');
    }
  }
  const p = all.find(x => x.slug === prov) ?? all[0];
  const t = q.trim().toLowerCase(),
    list = p ? p.models.filter(m => !t || m.toLowerCase().includes(t)) : [];
  const canPick = d.chat_switch && all.length > 0;
  const groups = (['own', 'shared', 'owner'] as const).map(k => [k, all.filter(x => x.kind === k)] as const).filter(([, v]) => v.length);
  const pick = (m: string) => {
    if (p.slug === cur.provider && m === cur.model) {
      setOpen('');
      return;
    }
    apply('model', {provider: p.slug, model: m}, m);
  };
  return (
    <div className="model-switch-wrap" ref={box}>
      <button
        className={'model-switch' + (saving ? ' saving' : '') + (canPick ? '' : ' static')}
        disabled={!canPick || !!saving}
        title={!canPick ? 'Модель задає адміністратор' : 'Модель цього чату' + (pinned ? '' : ' (типова з налаштувань)')}
        onClick={() => {
          setProv(cur.provider);
          setOpen(open === 'model' ? '' : 'model');
        }}
      >
        <span className="ms-prov">{curProv?.name ?? cur.provider}</span>
        <span className="ms-model">{saving || cur.model}</span>
        {saving ? <span className="spinner" /> : canPick && <Ic i={ChevronDown} size={18} />}
      </button>
      {d.chat_reason && (
        <button
          className="model-switch effort"
          disabled={!!saving}
          title="Глибина міркувань у цьому чаті"
          onClick={() => setOpen(open === 'effort' ? '' : 'effort')}
        >
          <Ic i={Lightbulb} size={18} />
          <span className="ms-model">Міркування:</span>
          <span className="ms-prov">{EFFORT[effort] ?? effort}</span>
          <Ic i={ChevronDown} size={18} />
        </button>
      )}
      {open === 'effort' && (
        <div className="ms-menu effort-menu">
          {d.efforts.map(e => (
            <button
              key={e}
              className={e === effort ? 'on' : ''}
              onClick={() => (e === effort ? setOpen('') : apply('effort', {effort: e}, cur.model))}
            >
              <span>{EFFORT[e] ?? e}</span>
              {e === effort && <Ic i={Check} size={18} />}
            </button>
          ))}
          <p className="hint ms-note">
            Лише для цього чату. Типовий рівень — у Налаштуваннях. Більше міркувань — точніше, але повільніше й дорожче.
          </p>
        </div>
      )}
      {open === 'model' && p && (
        <div className="ms-menu" role="dialog" aria-label="Вибір моделі">
          <div className="ms-provs">
            {groups.map(([k, v]) => (
              <React.Fragment key={k}>
                <div className="ms-group">{GROUP[k]}</div>
                {v.map(x => (
                  <button
                    key={x.slug}
                    className={x.slug === p.slug ? 'on' : ''}
                    onClick={() => {
                      setProv(x.slug);
                      setQ('');
                    }}
                  >
                    <span>{x.name}</span>
                  </button>
                ))}
              </React.Fragment>
            ))}
          </div>
          <div className="ms-models">
            <input
              autoFocus
              placeholder={`Пошук серед ${p.models.length}…`}
              value={q}
              onChange={e => setQ(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && list[0]) pick(list[0]);
                if (e.key === 'Escape') setOpen('');
              }}
            />
            <div className="ms-list">
              {list.map(m => {
                const on = p.slug === cur.provider && m === cur.model;
                return (
                  <button key={m} className={on ? 'on' : ''} onClick={() => pick(m)}>
                    <span>{m}</span>
                    {on && <Ic i={Check} size={18} />}
                  </button>
                );
              })}
              {p.kind !== 'shared' && t && !p.models.includes(q.trim()) && (
                <button className="custom" onClick={() => pick(q.trim())}>
                  Використати «{q.trim()}»
                </button>
              )}
              {!list.length && <p className="hint">Нічого не знайдено.</p>}
            </div>
            <p className="hint ms-note">
              {p.kind === 'shared' ? 'Спільна підписка: доступні моделі визначає адміністратор. ' : ''}Лише для цього чату, без перезапуску
              агента. Типова модель для нових чатів — у Налаштуваннях.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

/** Admin: which models of the shared (owner's) subscription a user may pick. */
export function SharedModelsEditor({uid}: {uid: string}) {
  const [d, setD] = useState<{
    shared: {slug: string; name: string; models: string[]}[];
    allowed: string[];
    assigned: {provider: string; model: string} | null;
  } | null>(null);
  const [err, setErr] = useState(''),
    [saved, setSaved] = useState('');
  useEffect(() => {
    api(`/admin/users/${uid}/models`)
      .then(setD)
      .catch(e => setErr(String(e)));
  }, [uid]);
  if (err) return <div className="error">{err}</div>;
  if (!d)
    return (
      <div className="skeleton-block">
        <i />
        <i />
        <i />
      </div>
    );
  async function toggle(key: string, on: boolean) {
    const next = on ? [...d!.allowed, key] : d!.allowed.filter(x => x !== key);
    try {
      const r = await api(`/admin/users/${uid}/models`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({allowed: next}),
      });
      setD({...d!, allowed: r.allowed});
      setSaved('Збережено');
      setTimeout(() => setSaved(''), 1500);
    } catch (e) {
      setErr(String(e));
    }
  }
  return (
    <>
      {!d.shared.length && <p className="hint">У профілі користувача немає спільних підписок.</p>}
      {d.shared.map(s => (
        <div key={s.slug}>
          <h3>{s.name}</h3>
          <div className="tools">
            {s.models.map(m => {
              const key = `${s.slug}/${m}`,
                base = d.assigned?.provider === s.slug && d.assigned?.model === m;
              return (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={base || d.allowed.includes(key)}
                    disabled={base}
                    onChange={e => toggle(key, e.target.checked)}
                  />
                  <span>
                    {m}
                    {base && <small className="hint"> · призначена</small>}
                  </span>
                </label>
              );
            })}
          </div>
        </div>
      ))}
      <p className="hint">
        Моделі власних підписок користувач обирає без обмежень. Призначену адміністратором модель доступно завжди. {saved}
      </p>
    </>
  );
}
