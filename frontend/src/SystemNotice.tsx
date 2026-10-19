import React, {useState} from 'react';
import {ChevronDown, Ic, Terminal} from './Icons';

/** Machine notices Hermes itself writes into the transcript as user-role rows (a background process finished,
 * background subagents finished, an interrupted turn resumed, model/personality switched). Nobody typed them, so
 * they render as a compact system event, never as the user's message (same set as the native desktop hydration). */
export type Notice = {title: string; body: string};
const LABELS: Record<string, string> = {
  process_complete: 'Фоновий процес завершився',
  async_delegation_complete: 'Фонова робота агента завершена',
  auto_continue: 'Перервану відповідь продовжено',
  model_switch: 'Модель змінено',
  personality_switch: 'Особистість змінено',
};
// Rows persisted before Hermes typed them (and share snapshots made before `kind` was kept): Hermes' own prefix sniff.
const SYNTHETIC =
  /^\s*(?:\[IMPORTANT: Background process |\[ASYNC (?:DELEGATION )?(?:BATCH )?(?:TASK FAILED|COMPLETE)\b|A background fan-out of \d+ subagent\(s\) you dispatched earlier has finished\.|A background subagent you dispatched earlier has finished\.)/i;

export function parseNotice(m: {role?: string; display_kind?: string; kind?: string}, text: string): Notice | null {
  if (m.role !== 'user') return null;
  const typed = m.display_kind ?? m.kind;
  let kind = typed && LABELS[typed] ? typed : '';
  if (!kind && SYNTHETIC.test(text))
    kind = /^\s*\[IMPORTANT: Background process/i.test(text) ? 'process_complete' : 'async_delegation_complete';
  if (!kind) return null;
  const exit = /exited \(exit code (\d+)\)/.exec(text);
  return {title: LABELS[kind] + (exit ? ` (код ${exit[1]})` : ''), body: text.trim()};
}

export function SystemNotice({n}: {n: Notice}) {
  const [open, setOpen] = useState(false);
  return (
    <article className="assistant sys-notice" role="note">
      <button
        type="button"
        className="sys-notice-head"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        title="Автоматичне сповіщення Hermes, не від користувача"
      >
        <Ic i={Terminal} size={14} />
        <span className="sys-notice-title">{n.title}</span>
        <Ic i={ChevronDown} size={16} className={open ? 'sys-notice-chev open' : 'sys-notice-chev'} />
      </button>
      {open && <pre className="sys-notice-body">{n.body}</pre>}
    </article>
  );
}
