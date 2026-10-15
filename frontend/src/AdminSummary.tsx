// Admin summaries and charts shown in the Settings window.
import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {api, peek} from './Auth';

type UsageRow = {turns: number; tokens: number; cost: number; limit: number | null};
export type AdminUsage = {
  since: number;
  users: (UsageRow & {id: string; username: string; profile: string})[];
  profiles: (UsageRow & {name: string})[];
  daily: {day: number; cost: number}[];
};
const money = (v: number) => '$' + v.toFixed(v < 1 ? 2 : 2);
const ago = (t?: number | null) => {
  if (!t) return 'не входив';
  const s = Date.now() / 1000 - t;
  return s < 3600
    ? Math.max(1, Math.round(s / 60)) + ' хв тому'
    : s < 86400
      ? Math.round(s / 3600) + ' год тому'
      : Math.round(s / 86400) + ' дн. тому';
};

/** Month usage, shared by the overview tables (cached like other slow pages). */
function useUsage() {
  const [d, setD] = useState<AdminUsage | null>(() => peek('/admin/usage') ?? null);
  useEffect(() => {
    api('/admin/usage')
      .then(setD)
      .catch(() => {});
  }, []);
  return d;
}

type U = {id: string; username: string; role: string; profile: string; blocked: number; last_login?: number | null; totp?: boolean};
/** Users page with nothing selected: every account at a glance; a row opens the account. */
export function UsersSummary({users, onPick}: {users: U[]; onPick: (id: string) => void}) {
  const usage = useUsage(),
    by = Object.fromEntries((usage?.users ?? []).map(u => [u.id, u]));
  return (
    <div className="card summary">
      <h3>Усі користувачі</h3>
      <p className="hint">Витрати й запити за поточний місяць (UTC). Натисніть рядок, щоб відкрити користувача.</p>
      <table className="usage clickable">
        <thead>
          <tr>
            <th>Користувач</th>
            <th>Профіль</th>
            <th>Останній вхід</th>
            <th className="num">Запитів</th>
            <th className="num">Вартість</th>
            <th className="num">Ліміт</th>
          </tr>
        </thead>
        <tbody>
          {users.map(u => {
            const x = by[u.id];
            return (
              <tr
                key={u.id}
                tabIndex={0}
                onClick={() => onPick(u.id)}
                onKeyDown={e => {
                  if (e.key === 'Enter') onPick(u.id);
                }}
              >
                <td>
                  <b>{u.username}</b>
                  {u.role === 'admin' && <small> адмін</small>}
                  {u.blocked ? <small className="bad"> заблоковано</small> : null}
                </td>
                <td>{u.profile}</td>
                <td>{ago(u.last_login)}</td>
                <td className="num">{x ? x.turns : '—'}</td>
                <td className="num">{x ? money(x.cost) : '—'}</td>
                <td className="num">{x?.limit != null ? money(x.limit) : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

type P = {name: string; model: string; bridge: string; users: number; owner: boolean};
/** Profiles page with nothing selected: model, bridge state, users and month usage of every profile. */
export function ProfilesSummary({list, onPick}: {list: P[]; onPick: (name: string) => void}) {
  const usage = useUsage(),
    by = Object.fromEntries((usage?.profiles ?? []).map(p => [p.name, p]));
  return (
    <div className="card summary">
      <h3>Усі профілі</h3>
      <p className="hint">Профіль — окремий Shroom: модель, ключі, скіли, памʼять, історія. Витрати за поточний місяць (UTC).</p>
      <table className="usage clickable">
        <thead>
          <tr>
            <th>Профіль</th>
            <th>Модель</th>
            <th>Міст</th>
            <th className="num">Запитів</th>
            <th className="num">Вартість</th>
          </tr>
        </thead>
        <tbody>
          {list.map(p => {
            const x = by[p.name];
            return (
              <tr
                key={p.name}
                tabIndex={0}
                onClick={() => onPick(p.name)}
                onKeyDown={e => {
                  if (e.key === 'Enter') onPick(p.name);
                }}
              >
                <td>
                  <b>{p.name}</b>
                  {p.owner && <small> власник</small>}
                </td>
                <td className="meta">{p.model || '—'}</td>
                <td>
                  <span className={'st ' + p.bridge}>
                    <i className="dot" />
                    {p.bridge === 'active' ? 'працює' : 'зупинено'}
                  </span>
                </td>
                <td className="num">{x ? x.turns : '—'}</td>
                <td className="num">{x ? money(x.cost) : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Daily cost of the current month: bars with a $ axis, day labels and a hover readout. Hand-written SVG. */
export function CostChart({daily}: {daily: {day: number; cost: number}[]}) {
  const box = useRef<HTMLDivElement>(null),
    [w, setW] = useState(600),
    [hover, setHover] = useState<number | null>(null);
  useLayoutEffect(() => {
    const n = box.current;
    if (!n) return;
    const ro = new ResizeObserver(() => setW(n.clientWidth || 600));
    ro.observe(n);
    setW(n.clientWidth || 600);
    return () => ro.disconnect();
  }, []);
  const now = new Date(),
    year = now.getUTCFullYear(),
    month = now.getUTCMonth(),
    today = now.getUTCDate() - 1;
  const n = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const cost = Array.from({length: n}, (_, i) => daily.find(x => x.day === i)?.cost ?? 0);
  const top = niceMax(Math.max(...cost, 0.01));
  const H = 150,
    L = 48,
    R = 8,
    T = 10,
    B = 22,
    pw = Math.max(50, w - L - R),
    ph = H - T - B,
    slot = pw / n,
    bw = Math.max(2, Math.min(22, slot * 0.7));
  const y = (v: number) => T + ph - (v / top) * ph;
  const ticks = [0, top / 2, top];
  const labelDays = new Set([0, 4, 9, 14, 19, 24, n - 1].filter(i => i < n));
  const mon = now.toLocaleDateString('uk-UA', {month: 'short', timeZone: 'UTC'}).replace('.', '');
  return (
    <div ref={box} className="cost-chart">
      <svg width={w} height={H} role="img" aria-label="Вартість по днях поточного місяця" onMouseLeave={() => setHover(null)}>
        {ticks.map(t => (
          <g key={t}>
            <line x1={L} x2={L + pw} y1={y(t)} y2={y(t)} className={t ? 'grid' : 'axis'} />
            <text x={L - 6} y={y(t) + 4} textAnchor="end">
              {'$' + fmtTick(t)}
            </text>
          </g>
        ))}
        {cost.map((c, i) => {
          const x = L + i * slot + (slot - bw) / 2;
          return (
            <g key={i} onMouseEnter={() => setHover(i)}>
              <rect x={L + i * slot} y={T} width={slot} height={ph} className="hit" />
              <rect
                x={x}
                y={y(c)}
                width={bw}
                height={Math.max(c > 0 ? 1.5 : 0, T + ph - y(c))}
                rx={Math.min(3, bw / 3)}
                className={'cbar' + (i === today ? ' today' : '') + (i > today ? ' future' : '') + (hover === i ? ' on' : '')}
              />
              {labelDays.has(i) && (
                <text x={L + i * slot + slot / 2} y={H - 6} textAnchor="middle">
                  {i + 1}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="cost-readout" aria-live="polite">
        {hover !== null ? `${hover + 1} ${mon}: ${money(cost[hover])}` : `Сьогодні, ${today + 1} ${mon}: ${money(cost[today] ?? 0)}`}
      </div>
    </div>
  );
}
function niceMax(v: number) {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}
const fmtTick = (v: number) => (v === 0 ? '0' : v < 1 ? v.toFixed(2) : v < 10 ? v.toFixed(v % 1 ? 1 : 0) : String(Math.round(v)));
