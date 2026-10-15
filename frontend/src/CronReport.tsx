import React from 'react';
import {Ic, Schedule, TriangleAlert} from './Icons';
import {Markdown} from './Markdown';

/** A scheduled-job report or policy notice mirrored into the chat transcript by the portal (backend cron_deliver).
 * Stored as a user-role row so the agent sees it as context; shown here as the agent's report, not as the user's words. */
export type Report = {kind: 'report' | 'notice'; job: string; at: string; failed: boolean; title: string; body: string};
const HEAD = /^\[cron-(report|notice) job=([a-f0-9]{6,40})(?: at=([0-9-]+ [0-9:]+) UTC)?( failed)?\]\s*([^\n]*)\n?/;

export function parseReport(text: string): Report | null {
  const m = HEAD.exec(text);
  if (!m) return null;
  const name = /«([^»]*)»/.exec(m[5]);
  return {
    kind: m[1] as Report['kind'],
    job: m[2],
    at: m[3] ?? '',
    failed: !!m[4],
    title: name ? name[1] : '',
    body: m[1] === 'notice' ? m[5] : text.slice(m[0].length).trim(),
  };
}

const local = (at: string) => {
  const d = new Date(at.replace(' ', 'T') + ':00Z');
  return isNaN(+d) ? at : d.toLocaleString('uk-UA', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});
};

export function CronReport({r}: {r: Report}) {
  if (r.kind === 'notice')
    return (
      <article className="assistant cron-notice" role="note">
        <label>
          <Ic i={TriangleAlert} size={14} /> Розклад
        </label>
        <div>{r.body}</div>
      </article>
    );
  return (
    <article className={'assistant cron-report' + (r.failed ? ' failed' : '')}>
      <label className="assistant-name-row">
        <Ic i={Schedule} size={14} /> Звіт за розкладом{r.title ? ' · ' + r.title : ''}
        {r.at ? ' · ' + local(r.at) : ''}
      </label>
      {r.failed ? <div className="hint">{r.body}</div> : <Markdown text={r.body} />}
    </article>
  );
}
