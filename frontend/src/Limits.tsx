import React, {useEffect, useState} from 'react';
import {api, peek} from './Auth';

export type Window = {label: string; used: number | null; resets_at: string | null; detail: string | null};
export type Limits = {
  provider: string;
  name: string;
  plan?: string | null;
  windows: Window[];
  details: string[];
  unavailable: string | null;
  own?: boolean;
  stale?: boolean;
  fetched_at?: number | string | null;
};

const LABELS: Record<string, string> = {'Current session': '5 годин', Session: '5 годин', 'Current week': 'Тиждень', Weekly: 'Тиждень'};
export const label = (l: string) => LABELS[l] ?? l.replace(/^Current week \((.+)\)$/, 'Тиждень · $1');
export function resetIn(iso: string | null) {
  if (!iso) return '';
  const s = Math.max(0, (new Date(iso).getTime() - Date.now()) / 1000),
    h = Math.floor(s / 3600),
    m = Math.floor((s % 3600) / 60);
  return h >= 24 ? `${Math.floor(h / 24)} д ${h % 24} год` : h ? `${h} год ${m} хв` : `${m} хв`;
}
/** Gauges show what is LEFT of each window (100 = untouched, 10 = almost exhausted), not what was used. */
export const left = (w: Window) => Math.max(0, Math.min(100, 100 - (w.used ?? 0)));
const level = (l: number) => (l <= 10 ? 'hot' : l <= 30 ? 'warm' : '');

const fetchedAt = (d: Limits) => {
  const t = typeof d.fetched_at === 'number' ? d.fetched_at * 1000 : d.fetched_at ? Date.parse(d.fetched_at) : NaN;
  return isNaN(t) ? '' : new Date(t).toLocaleTimeString('uk-UA', {hour: '2-digit', minute: '2-digit'});
};

/** Compact gauges in the chat header: provider of the user's current model, every window as a thin bar.
 *  The provider's usage endpoint fails now and then (rate limits, restarts), so the last good reading is kept
 *  (also across reloads, per user) and shown dimmed until a fresh one arrives. It hides only when the current
 *  provider really has no limits. */
export function LimitsBadge({refreshKey, cacheKey, provider = ''}: {refreshKey: unknown; cacheKey: string; provider?: string}) {
  const key = 'hermes-limits-' + cacheKey + (provider ? '-' + provider : '');
  const [d, setD] = useState<Limits | null>(() => {
    try {
      const v = JSON.parse(localStorage.getItem(key) ?? 'null');
      return v?.windows?.length ? {...v, stale: true} : null;
    } catch {
      return null;
    }
  });
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let on = true;
    setLoading(true);
    const load = () =>
      api('/me/limits' + (provider ? '?provider=' + encodeURIComponent(provider) : ''))
        .then((x: Limits) => {
          if (!on) return;
          if (x.windows?.length) {
            setD(x);
            if (!x.stale) localStorage.setItem(key, JSON.stringify(x));
          } else setD(prev => (prev && prev.provider === x.provider ? {...prev, stale: true} : null)); // same provider: transient failure
        })
        .catch(() => on && setD(prev => prev && {...prev, stale: true}))
        .finally(() => on && setLoading(false));
    load();
    const t = setInterval(() => {
      if (!document.hidden) load();
    }, 60000);
    return () => {
      on = false;
      clearInterval(t);
    };
  }, [refreshKey, key]);
  // another chat may use another provider: drop the previous provider's gauges instead of showing them as this one's
  useEffect(() => {
    try {
      const v = JSON.parse(localStorage.getItem(key) ?? 'null');
      setD(v?.windows?.length ? {...v, stale: true} : null);
    } catch {
      setD(null);
    }
  }, [key]);
  if (loading && !d)
    return (
      <div className="limits-badge skeleton" aria-busy="true">
        <i />
        <i />
        <i />
      </div>
    );
  if (!d || !d.windows.length) return null;
  const tip =
    `${d.name}${d.plan ? ' ' + d.plan : ''} · ${d.own ? 'ваша підписка' : 'спільна підписка'}\n` +
    d.windows
      .map(
        w =>
          `${label(w.label)}: залишилось ${Math.round(left(w))}%` +
          (w.resets_at ? `, скидання через ${resetIn(w.resets_at)}` : w.detail ? `, ${w.detail}` : '')
      )
      .join('\n') +
    (d.stale ? `\nДані${fetchedAt(d) ? ' на ' + fetchedAt(d) : ''}: провайдер зараз не відповідає, оновимо автоматично` : '');
  return (
    <div className={'limits-badge' + (loading ? ' refreshing' : '') + (d.stale ? ' stale' : '')} title={tip} aria-label={tip}>
      {d.windows.slice(0, 2).map(w => (
        <span key={w.label} className="lb-win">
          <small>{label(w.label)}</small>
          <span className="lb-bar">
            <i className={level(left(w))} style={{width: left(w) + '%'}} />
          </span>
          <b>{Math.round(left(w))}%</b>
        </span>
      ))}
    </div>
  );
}

/** Full gauges for settings pages. */
export function LimitBars({d, compact = false}: {d: Limits; compact?: boolean}) {
  if (d.unavailable || !d.windows.length)
    return <p className="hint">{d.name || d.provider || 'Провайдер'}: ліміти недоступні для цієї підписки.</p>;
  return (
    <div className={'limit-bars' + (compact ? ' compact' : '')}>
      {d.windows.map(w => (
        <div key={w.label} className="lbar">
          <div className="row">
            <span>{label(w.label)}</span>
            <span className="hint">
              залишилось {Math.round(left(w))}% · {w.resets_at ? 'скидання через ' + resetIn(w.resets_at) : (w.detail ?? '')}
            </span>
          </div>
          <div className="bar wide">
            <i className={level(left(w))} style={{width: left(w) + '%'}} />
          </div>
        </div>
      ))}
      {d.details.map(x => (
        <p key={x} className="hint">
          {x}
        </p>
      ))}
      {d.stale && (
        <p className="hint">
          Останні відомі дані{fetchedAt(d) ? ' на ' + fetchedAt(d) : ''}: провайдер зараз не відповідає, оновимо автоматично.
        </p>
      )}
    </div>
  );
}

export function MyLimitsCard() {
  const [d, setD] = useState<Limits | null>(() => peek('/me/limits') ?? null),
    [err, setErr] = useState('');
  useEffect(() => {
    api('/me/limits')
      .then(setD)
      .catch(e => setErr(String(e)));
  }, []);
  return (
    <div className="card">
      <div className="row">
        <h3>Ліміти підписки</h3>
        {d && (
          <span className="hint">
            {d.name}
            {d.plan ? ' ' + d.plan : ''} · {d.own ? 'ваша підписка' : 'спільна підписка власника'}
          </span>
        )}
      </div>
      {err && !d ? (
        <p className="hint">Не вдалося отримати ліміти.</p>
      ) : !d ? (
        <div className="skeleton-block" aria-busy="true">
          <i />
          <i />
          <i />
        </div>
      ) : (
        <LimitBars d={d} />
      )}
      <p className="hint">Дані надає сам провайдер (зараз Claude і ChatGPT). Спільна підписка — одна на всіх, хто нею користується.</p>
    </div>
  );
}

type AdminLimits = {shared: Limits[]; users: {id: string; username: string; profile: string; limits: Limits}[]};
export function AdminLimitsCards() {
  const [d, setD] = useState<AdminLimits | null>(() => peek('/admin/limits') ?? null),
    [err, setErr] = useState('');
  useEffect(() => {
    api('/admin/limits')
      .then(setD)
      .catch(e => setErr(String(e)));
  }, []);
  if (err && !d)
    return (
      <div className="card">
        <h3>Ліміти підписок</h3>
        <p className="hint">Не вдалося отримати ліміти.</p>
      </div>
    );
  if (!d)
    return (
      <div className="card">
        <h3>Ліміти підписок</h3>
        <div className="skeleton-block" aria-busy="true">
          <i />
          <i />
        </div>
      </div>
    );
  return (
    <>
      <div className="card">
        <h3>Спільні підписки власника</h3>
        <p className="hint">Одна шкала на всіх користувачів, чий профіль працює через підписку власника.</p>
        <div className="limit-grid">
          {d.shared.map(s => (
            <div key={s.provider}>
              <b>
                {s.name}
                {s.plan ? ' ' + s.plan : ''}
              </b>
              <LimitBars d={s} />
            </div>
          ))}
        </div>
      </div>
      <div className="card">
        <h3>По користувачах</h3>
        <table>
          <thead>
            <tr>
              <th>Користувач</th>
              <th>Підписка</th>
              <th>Ліміти</th>
            </tr>
          </thead>
          <tbody>
            {d.users.map(u => (
              <tr key={u.id}>
                <td>
                  <b>{u.username}</b> <small>{u.profile}</small>
                </td>
                <td>
                  {u.limits.name || '—'}
                  <br />
                  <small>{u.limits.own ? 'власна' : 'спільна'}</small>
                </td>
                <td className="meta">
                  <LimitBars d={u.limits} compact />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
