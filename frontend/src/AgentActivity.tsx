import React, {useEffect, useState} from 'react';

export type ActivityStep = {
  id: string;
  name: string;
  context: string;
  started: number;
  finished?: number;
  duration?: number;
  result?: string;
};
export type ActivityEvent = {type: string; payload?: Record<string, any>};
export function applyActivity(steps: ActivityStep[], events: ActivityEvent[], now = Date.now()): ActivityStep[] {
  let next = [...steps];
  for (const event of events) {
    if (!['tool.start', 'tool.complete'].includes(event.type)) continue;
    const p = event.payload ?? {},
      id = String(p.tool_id ?? '');
    if (!id) continue;
    const index = next.findIndex(s => s.id === id);
    if (event.type === 'tool.start') {
      if (index < 0)
        next.push({id, name: String(p.name ?? 'Інструмент'), context: String(p.context ?? p.preview ?? '').slice(0, 300), started: now});
    } else {
      const prior = next[index];
      const step: ActivityStep = {
        ...(prior ?? {id, name: String(p.name ?? 'Інструмент'), context: '', started: now}),
        finished: now,
        duration: typeof p.duration_s === 'number' ? p.duration_s : prior ? (now - prior.started) / 1000 : undefined,
        result: String(
          p.result_text ||
            p.summary ||
            (typeof p.result === 'string' ? p.result : p.result != null ? JSON.stringify(p.result, null, 2) : '')
        ).slice(0, 12000),
      };
      if (index < 0) next.push(step);
      else next[index] = step;
    }
  }
  return next.slice(-100);
}
const elapsed = (seconds: number) =>
  seconds < 60 ? `${Math.floor(seconds)} с` : `${Math.floor(seconds / 60)} хв ${Math.floor(seconds % 60)} с`;

/** A compact live tool-run disclosure below the reply, not a separate drawer. */
export function AgentActivity({steps, busy, state, connected}: {steps: ActivityStep[]; busy: boolean; state: string; connected: boolean}) {
  const [expanded, setExpanded] = useState(false),
    [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [busy]);
  if (!steps.length && !busy) return null;
  const done = steps.filter(s => s.finished !== undefined).length;
  const current = [...steps].reverse().find(s => s.finished === undefined);
  const status = !connected
    ? 'Звʼязок відновлюється'
    : busy
      ? state === 'waiting'
        ? 'Потрібна ваша відповідь'
        : 'Агент працює'
      : state === 'interrupted'
        ? 'Виконання зупинено'
        : state === 'error'
          ? 'Виконання перервано'
          : 'Виконання завершено';
  return (
    <section className="agent-activity" aria-label="Хід виконання">
      <details open={expanded} onToggle={e => setExpanded(e.currentTarget.open)}>
        <summary className="activity-summary">
          <span className={'activity-indicator' + (busy && connected ? ' live' : '')} aria-hidden="true" />
          <strong>{status}</strong>
          <span className="activity-current">
            {busy ? current?.context || current?.name || 'Очікуємо наступний крок…' : 'Кроки виконання'}
          </span>
          <span className="activity-count">
            {done}/{steps.length}
          </span>
          {current && busy && <time>{elapsed(Math.max(0, (now - current.started) / 1000))}</time>}
        </summary>
        {!steps.length && <p className="hint">Очікуємо перший крок агента…</p>}
        <ol>
          {steps.map(step => (
            <li key={step.id} className={step.finished !== undefined ? 'finished' : 'running'}>
              <div className="activity-step">
                <span className="activity-state">
                  {step.finished !== undefined ? 'Завершено' : busy ? 'Виконується' : 'Без підтвердження завершення'}
                </span>
                <strong>{step.name}</strong>
                <time>{elapsed(step.duration ?? Math.max(0, ((step.finished ?? now) - step.started) / 1000))}</time>
              </div>
              {step.context && <p>{step.context}</p>}
              {step.result && (
                <details>
                  <summary>Результат кроку</summary>
                  <pre>
                    {step.result}
                    {step.result.length === 12000 ? '\n… показано перші 12 000 символів' : ''}
                  </pre>
                </details>
              )}
            </li>
          ))}
        </ol>
        {steps.length === 100 && <p className="hint">Показано останні 100 кроків.</p>}
      </details>
    </section>
  );
}
