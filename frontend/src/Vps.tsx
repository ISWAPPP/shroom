// Admin dashboard: VPS resources in one card (fill gauges, history charts, who uses the memory).
// Data: GET /api/admin/vps?range=..; the backend samples the host every 15 s and keeps 8 days of history.
import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
import {api} from './Auth';
import './Vps.css';

type Unit = {group: string; name: string; mem: number; cpu: number | null; count: number};
type Disk = {mount: string; device: string; fs: string; total: number; used: number; free: number};
type Now = {
  ts: number;
  cores: number;
  cpu: {total: number; user: number; system: number; iowait: number; steal: number} | null;
  load: number[];
  mem: {total: number; used: number; available: number; cached: number; swap_total: number; swap_used: number};
  disks: Disk[];
  rates: {rx: number; tx: number; read: number; write: number} | null;
  psi: {cpu?: number; memory?: number; io?: number};
  units: Unit[];
  uptime: number;
  procs: number;
  hostname: string;
  kernel: string;
};
type Point = {
  t: number;
  cpu: number;
  cpu_max: number;
  steal: number;
  iowait: number;
  mem: number;
  mem_max: number;
  swap: number;
  disk: number;
  load1: number;
  rx: number;
  tx: number;
  rd: number;
  wr: number;
};
type VpsData = {range: Range; step: number; since: number; series: Point[]; now: Now | null; stale: boolean};
type Range = '1h' | '6h' | '24h' | '7d';

const RANGES: [Range, string][] = [
  ['1h', '1 год'],
  ['6h', '6 год'],
  ['24h', '24 год'],
  ['7d', '7 дн'],
];
const GROUPS: Record<string, string> = {
  bridges: 'Агенти Hermes',
  sandboxes: 'Пісочниці',
  portal: 'Портал',
  system: 'Docker',
  other: 'Система та кеш',
};
const UNITS = ['Б', 'КБ', 'МБ', 'ГБ', 'ТБ'];
export function bytes(n: number, digits = 1) {
  let i = 0;
  while (Math.abs(n) >= 1024 && i < UNITS.length - 1) {
    n /= 1024;
    i++;
  }
  return (i === 0 ? Math.round(n) : n.toFixed(n >= 100 ? 0 : digits)).toString().replace('.', ',') + ' ' + UNITS[i];
}
const rate = (n: number) => bytes(n) + '/с';
const pct = (v: number) => Math.round(v * 100) + '%';
const level = (v: number) => (v >= 0.9 ? 'hot' : v >= 0.7 ? 'warm' : '');
function uptime(s: number) {
  const d = Math.floor(s / 86400),
    h = Math.floor((s % 86400) / 3600),
    m = Math.floor((s % 3600) / 60);
  return d ? `${d} дн ${h} год` : h ? `${h} год ${m} хв` : `${m} хв`;
}
const two = (n: number) => String(n).padStart(2, '0');
const hm = (t: number) => {
  const d = new Date(t * 1000);
  return two(d.getHours()) + ':' + two(d.getMinutes());
};
const dm = (t: number) => {
  const d = new Date(t * 1000);
  return two(d.getDate()) + '.' + two(d.getMonth() + 1);
};

/** Three-quarter ring gauge: fill level + colour by threshold. */
function Ring({value, label, main, sub}: {value: number | null; label: string; main: string; sub: React.ReactNode}) {
  const C = 2 * Math.PI * 40,
    arc = C * 0.75,
    v = Math.max(0, Math.min(1, value ?? 0));
  return (
    <div
      className={'vps-gauge ' + (value == null ? 'empty' : level(v))}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value == null ? undefined : Math.round(v * 100)}
    >
      <svg viewBox="0 0 100 100">
        <circle className="track" cx="50" cy="50" r="40" strokeDasharray={`${arc} ${C}`} transform="rotate(135 50 50)" />
        <circle className="fill" cx="50" cy="50" r="40" strokeDasharray={`${arc * v} ${C}`} transform="rotate(135 50 50)" />
        <text x="50" y="52" className="val">
          {value == null ? '—' : pct(v)}
        </text>
        <text x="50" y="68" className="lbl">
          {label}
        </text>
      </svg>
      <div className="vps-gauge-text">
        <b>{main}</b>
        <span>{sub}</span>
      </div>
    </div>
  );
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null),
    [w, setW] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setW(el.clientWidth);
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

type Line = {key: keyof Point; label: string; cls: string; area?: boolean; faint?: boolean};
/** Time-series chart: gridlines, gaps where the sampler was down, hover crosshair with a tooltip. */
function Chart({
  title,
  now,
  data,
  lines,
  fmt,
  percent,
  from,
  to,
  step,
}: {
  title: string;
  now: React.ReactNode;
  data: Point[];
  lines: Line[];
  fmt: (v: number) => string;
  percent?: boolean;
  from: number;
  to: number;
  step: number;
}) {
  const [ref, W] = useWidth<HTMLDivElement>(),
    [hover, setHover] = useState<number | null>(null);
  const H = 132,
    L = percent ? 40 : 66,
    R = 4,
    T = 8,
    B = 20,
    w = Math.max(0, W - L - R),
    h = H - T - B;
  const peak = Math.max(0, ...data.flatMap(p => lines.map(l => Number(p[l.key]) || 0)));
  const top = percent ? 1 : niceTop(peak);
  const x = (t: number) => L + ((t - from) / Math.max(1, to - from)) * w,
    y = (v: number) => T + h - Math.min(1, v / top) * h;
  const segs: Point[][] = [];
  data.forEach((p, i) => {
    if (!i || p.t - data[i - 1].t > step * 2.5) segs.push([]);
    segs[segs.length - 1].push(p);
  });
  const path = (s: Point[], k: keyof Point) =>
    s.map((p, i) => (i ? 'L' : 'M') + x(p.t + step / 2).toFixed(1) + ' ' + y(Number(p[k]) || 0).toFixed(1)).join('');
  const area = (s: Point[], k: keyof Point) =>
    path(s, k) + `L${x(s[s.length - 1].t + step / 2).toFixed(1)} ${T + h}L${x(s[0].t + step / 2).toFixed(1)} ${T + h}Z`;
  const ticks = [0, 0.5, 1].map(f => f * top),
    long = to - from > 86400 * 1.5;
  const xt = [from, (from + to) / 2, to];
  function move(e: React.MouseEvent<SVGSVGElement>) {
    if (!data.length) return;
    const r = e.currentTarget.getBoundingClientRect(),
      t = from + ((e.clientX - r.left - L) / Math.max(1, w)) * (to - from);
    let best = 0;
    data.forEach((p, i) => {
      if (Math.abs(p.t + step / 2 - t) < Math.abs(data[best].t + step / 2 - t)) best = i;
    });
    setHover(best);
  }
  const hp = hover != null ? data[hover] : null;
  return (
    <div className="vps-chart">
      <div className="vps-chart-head">
        <span>{title}</span>
        <b>{now}</b>
      </div>
      <div className="vps-plot" ref={ref}>
        {W > 0 && (
          <svg width={W} height={H} onMouseMove={move} onMouseLeave={() => setHover(null)} role="img" aria-label={title}>
            {ticks.map((v, i) => (
              <g key={i}>
                <line className="grid" x1={L} x2={L + w} y1={y(v)} y2={y(v)} />
                <text className="axis" x={L - 6} y={y(v) + 4} textAnchor="end">
                  {percent ? pct(v) : fmt(v)}
                </text>
              </g>
            ))}
            {xt.map((t, i) => (
              <text key={i} className="axis" x={x(t)} y={H - 4} textAnchor={i === 0 ? 'start' : i === 2 ? 'end' : 'middle'}>
                {i === 2 ? 'зараз' : long ? dm(t) : hm(t)}
              </text>
            ))}
            {lines.map(l =>
              segs.map((s, i) => (
                <g key={l.key + i} className={l.cls}>
                  {l.area && <path className="area" d={area(s, l.key)} />}
                  <path className={'line' + (l.faint ? ' faint' : '')} d={path(s, l.key)} />
                </g>
              ))
            )}
            {!data.length && (
              <text className="axis" x={L + w / 2} y={T + h / 2} textAnchor="middle">
                Дані збираються…
              </text>
            )}
            {hp && (
              <g>
                <line className="cross" x1={x(hp.t + step / 2)} x2={x(hp.t + step / 2)} y1={T} y2={T + h} />
                {lines
                  .filter(l => !l.faint)
                  .map(l => (
                    <circle key={l.key} className={'dot ' + l.cls} cx={x(hp.t + step / 2)} cy={y(Number(hp[l.key]) || 0)} r="3.5" />
                  ))}
              </g>
            )}
          </svg>
        )}
      </div>
      {hp && (
        <div className="vps-tip" style={{left: Math.min(W - 170, Math.max(0, x(hp.t + step / 2) - 85))}}>
          <div className="meta">
            {long ? dm(hp.t) + ' ' : ''}
            {hm(hp.t)}
            {step >= 120 ? '–' + hm(hp.t + step) : ''}
          </div>
          {lines.map(l => (
            <div key={l.key}>
              <i className={'sw ' + l.cls} />
              {l.label}
              <b>{percent ? pct(Number(hp[l.key])) : fmt(Number(hp[l.key]))}</b>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
function niceTop(v: number) {
  if (v <= 0) return 1024;
  const e = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * e >= v * 1.1) return m * e;
  return 10 * e;
}

/** Memory by consumer: stacked bar + top list with CPU share. */
function Consumers({n}: {n: Now}) {
  const [all, setAll] = useState(false);
  const sum: Record<string, number> = {};
  n.units.forEach(u => {
    sum[u.group] = (sum[u.group] ?? 0) + u.mem;
  });
  const known = Object.values(sum).reduce((a, b) => a + b, 0);
  sum.other = Math.max(0, n.mem.used - known);
  const order = ['bridges', 'sandboxes', 'portal', 'system', 'other'].filter(g => sum[g] > 0);
  const top = Math.max(1, ...n.units.map(u => u.mem)),
    list = all ? n.units : n.units.slice(0, 8);
  return (
    <div className="vps-consumers">
      <h4>Хто використовує памʼять</h4>
      <div className="vps-stack" role="img" aria-label="Розподіл памʼяті">
        {order.map(g => (
          <i key={g} className={'g-' + g} style={{width: (sum[g] / n.mem.total) * 100 + '%'}} title={`${GROUPS[g]}: ${bytes(sum[g])}`} />
        ))}
      </div>
      <div className="vps-legend">
        {order.map(g => (
          <span key={g}>
            <i className={'sw g-' + g} />
            {GROUPS[g]} <b>{bytes(sum[g])}</b>
          </span>
        ))}
        <span>
          <i className="sw free" />
          Доступно <b>{bytes(n.mem.available)}</b>
        </span>
      </div>
      <table className="usage vps-units">
        <thead>
          <tr>
            <th>Процес</th>
            <th>Памʼять</th>
            <th className="num">CPU</th>
          </tr>
        </thead>
        <tbody>
          {list.map(u => (
            <tr key={u.group + u.name}>
              <td>
                <b>{u.name}</b>
                <span className="meta">
                  {' '}
                  · {GROUPS[u.group]}
                  {u.count > 1 ? ` · ${u.count} конт.` : ''}
                </span>
              </td>
              <td className="vps-membar">
                <div className="bar wide">
                  <i className={'g-' + u.group} style={{width: (u.mem / top) * 100 + '%'}} />
                </div>
                <span>{bytes(u.mem)}</span>
              </td>
              <td className="num">{u.cpu == null ? '—' : (u.cpu * 100).toFixed(u.cpu < 0.1 ? 1 : 0).replace('.', ',') + '%'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {n.units.length > 8 && (
        <div className="actions">
          <button onClick={() => setAll(!all)}>{all ? 'Згорнути' : `Показати всі (${n.units.length})`}</button>
        </div>
      )}
    </div>
  );
}

export function VpsCard() {
  const [range, setRange] = useState<Range>(() => (localStorage.getItem('hermes-vps-range') as Range) || '1h');
  const [d, setD] = useState<VpsData | null>(null),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let on = true;
    setBusy(true);
    const load = () =>
      api('/admin/vps?range=' + range)
        .then(x => {
          if (on) {
            setD(x);
            setError('');
          }
        })
        .catch(e => on && setError(String(e).replace(/^Error: /, '')))
        .finally(() => on && setBusy(false));
    load();
    const t = setInterval(() => {
      if (!document.hidden) load();
    }, 15000);
    return () => {
      on = false;
      clearInterval(t);
    };
  }, [range]);
  const pick = (r: Range) => {
    localStorage.setItem('hermes-vps-range', r);
    setRange(r);
  };
  const n = d?.now,
    to = d ? Math.max(Date.now() / 1000, d.since) : 0;
  const head = (
    <div className="vps-head">
      <div>
        <h3>Ресурси VPS</h3>
        {n && (
          <p className="hint">
            {n.hostname} · {n.cores} ядра · {bytes(n.mem.total, 0)} RAM · працює {uptime(n.uptime)} · {n.procs} процесів
            {d?.stale ? ' · дані застаріли' : ''}
          </p>
        )}
      </div>
      <div className="tri vps-range" role="radiogroup" aria-label="Період графіків">
        {RANGES.map(([r, l]) => (
          <button key={r} role="radio" aria-checked={r === range} className={r === range ? 'on' : ''} onClick={() => pick(r)}>
            {l}
          </button>
        ))}
      </div>
    </div>
  );
  if (!d)
    return (
      <div className="card vps">
        {head}
        {error ? (
          <div className="error">{error}</div>
        ) : (
          <div className="skeleton-block" aria-busy="true">
            <i />
            <i />
            <i />
          </div>
        )}
      </div>
    );
  if (!n)
    return (
      <div className="card vps">
        {head}
        <p className="hint">Перший замір ще не надійшов: збір іде кожні 15 секунд через міст власника.</p>
      </div>
    );
  const m = n.mem,
    root = n.disks.find(x => x.mount === '/') ?? n.disks[0],
    last = d.series[d.series.length - 1];
  const psi = Object.entries(n.psi).filter(([, v]) => v != null) as [string, number][];
  return (
    <div className={'card vps' + (d.stale ? ' stale' : '') + (busy ? ' loading' : '')}>
      {head}
      {error && <div className="error">{error}</div>}
      <div className="vps-gauges">
        <Ring
          label="CPU"
          value={n.cpu?.total ?? null}
          main={`навантаження ${n.load[0].toFixed(2).replace('.', ',')}`}
          sub={
            n.cpu ? (
              <>
                за 5 і 15 хв{' '}
                {n.load
                  .slice(1)
                  .map(v => v.toFixed(2).replace('.', ','))
                  .join(' / ')}{' '}
                на {n.cores} ядра; користувач {pct(n.cpu.user)}, система {pct(n.cpu.system)}
                {n.cpu.iowait >= 0.01 ? `, очікування диска ${pct(n.cpu.iowait)}` : ''}
                {n.cpu.steal >= 0.01 ? `, забирає гіпервізор ${pct(n.cpu.steal)}` : ''}
              </>
            ) : (
              'перший замір'
            )
          }
        />
        <Ring
          label="Памʼять"
          value={m.used / m.total}
          main={`${bytes(m.used)} / ${bytes(m.total, 0)}`}
          sub={
            <>
              доступно {bytes(m.available)}, кеш {bytes(m.cached)}
              {m.swap_total ? `, swap ${bytes(m.swap_used)} з ${bytes(m.swap_total)}` : ', swap немає'}
            </>
          }
        />
        {root && (
          <Ring
            label={'Диск ' + root.mount}
            value={root.used / root.total}
            main={`${bytes(root.used, 0)} / ${bytes(root.total, 0)}`}
            sub={
              <>
                вільно {bytes(root.free)}, {root.device}
              </>
            }
          />
        )}
        <div className="vps-gauge vps-net">
          <div className="vps-io">
            <span>Мережа</span>
            <b>вхідний {n.rates ? rate(n.rates.rx) : '—'}</b>
            <b>вихідний {n.rates ? rate(n.rates.tx) : '—'}</b>
          </div>
          <div className="vps-io">
            <span>Диск</span>
            <b>читання {n.rates ? rate(n.rates.read) : '—'}</b>
            <b>запис {n.rates ? rate(n.rates.write) : '—'}</b>
          </div>
        </div>
      </div>
      {n.disks.length > 1 && (
        <div className="vps-disks">
          {n.disks
            .filter(x => x !== root)
            .map(x => (
              <div key={x.device} className="lbar">
                <div className="row">
                  <span>
                    {x.mount} <span className="meta">{x.device}</span>
                  </span>
                  <span className="meta">
                    {bytes(x.used)} з {bytes(x.total, 0)}
                  </span>
                </div>
                <div className="bar wide">
                  <i className={level(x.used / x.total)} style={{width: (x.used / x.total) * 100 + '%'}} />
                </div>
              </div>
            ))}
        </div>
      )}
      {psi.length > 0 && (
        <p
          className="vps-psi hint"
          title="Pressure Stall Information: частка часу за останні 10 с, коли процеси чекали на ресурс. Стабільно вище 10% означає, що VPS не вистачає цього ресурсу."
        >
          Очікування ресурсів за 10 с:{' '}
          {psi.map(([k, v]) => (
            <span key={k} className={v >= 25 ? 'hot' : v >= 10 ? 'warm' : ''}>
              {{cpu: 'CPU', memory: 'памʼять', io: 'диск'}[k]} {v.toFixed(1).replace('.', ',')}%
            </span>
          ))}
        </p>
      )}
      <div className="vps-charts">
        <Chart
          title="CPU"
          now={n.cpu ? pct(n.cpu.total) : '—'}
          data={d.series}
          percent
          from={d.since}
          to={to}
          step={d.step}
          lines={[
            {key: 'cpu', label: 'середнє', cls: 's1', area: true},
            ...(d.step > 15 ? [{key: 'cpu_max' as const, label: 'пік', cls: 's1', faint: true}] : []),
            {key: 'steal', label: 'гіпервізор', cls: 's2'},
          ]}
          fmt={pct}
        />
        <Chart
          title="Памʼять"
          now={pct(m.used / m.total)}
          data={d.series}
          percent
          from={d.since}
          to={to}
          step={d.step}
          lines={[
            {key: 'mem', label: 'зайнято', cls: 's2', area: true},
            ...(m.swap_total ? [{key: 'swap' as const, label: 'swap', cls: 's3'}] : []),
          ]}
          fmt={pct}
        />
        <Chart
          title="Мережа"
          now={n.rates ? `${rate(n.rates.rx)} · ${rate(n.rates.tx)}` : '—'}
          data={d.series}
          from={d.since}
          to={to}
          step={d.step}
          lines={[
            {key: 'rx', label: 'вхідний', cls: 's1', area: true},
            {key: 'tx', label: 'вихідний', cls: 's2'},
          ]}
          fmt={rate}
        />
        <Chart
          title="Диск, операції"
          now={last ? `${rate(last.rd)} · ${rate(last.wr)}` : '—'}
          data={d.series}
          from={d.since}
          to={to}
          step={d.step}
          lines={[
            {key: 'rd', label: 'читання', cls: 's1', area: true},
            {key: 'wr', label: 'запис', cls: 's2'},
          ]}
          fmt={rate}
        />
      </div>
      <Consumers n={n} />
    </div>
  );
}
