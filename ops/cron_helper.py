"""Hermes-side helper for portal cron features. Run with Hermes' own Python (profile_admin.hermes_py):
HERMES_HOME selects the profile. Commands (JSON on stdin, JSON on stdout):
  mirror  {"session_id": str, "text": str}   append a report into a session transcript (native gateway.mirror)
  search  {"q": str[, "limit": int]}         native FTS5 message search with session parent chains
  gap     {"schedule": str}                  parse a schedule and return its shortest gap in minutes
  env_get / env_set / env_unset {"key": str[, "value": str]}  profile .env through native hermes_cli.config
          (only keys in ENV_KEYS; values never leave the host)
"""

import json, sys

sys.path.insert(0, '/root/.hermes/hermes-agent')
sys._hermes_pin_default_home = True
import hermes_bootstrap  # noqa: E402,F401  (same import-path setup as the hermes launcher)


def mirror(a):
    from gateway.mirror import mirror_to_session

    # role=user: a report is not the agent speaking in this session; user-role rows merge safely with the
    # next user message instead of producing assistant->assistant pairs (see mirror_to_session docstring).
    ok = mirror_to_session('webui', 'portal', a['text'], source_label='portal-cron', role='user', session_id=a['session_id'])
    return {'ok': bool(ok)}


def gap(a):
    from datetime import datetime, timezone
    from cron.jobs import parse_schedule

    s = a['schedule'] if isinstance(a['schedule'], dict) else parse_schedule(a['schedule'])
    kind = s.get('kind')
    if kind == 'once':
        return {'kind': kind, 'minutes': None, 'display': s.get('display') or a['schedule']}
    if kind == 'interval':
        return {'kind': kind, 'minutes': float(s['minutes']), 'display': s.get('display')}
    from croniter import croniter

    it = croniter(s['expr'], datetime.now(timezone.utc))
    prev = it.get_next(datetime)
    best = None
    for _ in range(200):  # irregular expressions (e.g. "0 9,9-10 * * *") — check a window of fires, not one gap
        nxt = it.get_next(datetime)
        g = (nxt - prev).total_seconds() / 60
        prev = nxt
        best = g if best is None else min(best, g)
    return {'kind': kind, 'minutes': best, 'display': s.get('display') or s.get('expr')}


def report(a):
    """Answer text of one stored run via the native archive reader; silent runs -> None."""
    from cron.scheduler_prompt import _archive_answer

    text = open(a['path'], encoding='utf-8', errors='replace').read()
    return {'answer': _archive_answer(text), 'failed': '\n## Error\n' in text or text.startswith('## Error')}


ENV_KEYS = {'CURSOR_API_KEY'}  # portal-managed non-provider secrets


def _env_key(a):
    if a.get('key') not in ENV_KEYS:
        raise ValueError('env key not allowed')
    return a['key']


def env_get(a):
    from hermes_cli.config import load_env

    return {'value': (load_env() or {}).get(_env_key(a), '')}


def env_set(a):
    from hermes_cli.config import save_env_value, load_env, invalidate_env_cache

    key = _env_key(a)
    save_env_value(key, str(a['value']))
    invalidate_env_cache()
    if (load_env() or {}).get(key) != str(a['value']):
        raise ValueError('value was not saved')
    return {'ok': True}


def env_unset(a):
    from hermes_cli.config import remove_env_value

    return {'removed': bool(remove_env_value(_env_key(a)))}


def claude_isolation(a):
    """Own Claude subscription: suppress (or restore) the borrowed host Claude Code login for this profile."""
    from hermes_cli.auth import suppress_credential_source, unsuppress_credential_source

    if a.get('own'):
        suppress_credential_source('anthropic', 'claude_code')
    else:
        unsuppress_credential_source('anthropic', 'claude_code')
    return {'ok': True}


def search(a):
    """Native FTS5 search over this profile's chat messages (user + assistant). Each hit carries its session's parent
    chain, so the portal can map continuation sessions (after compression) back to the dialog's stored session."""
    from hermes_state import SessionDB

    db = SessionDB()
    rows = db.search_messages(
        str(a.get('q', ''))[:200], role_filter=['user', 'assistant'], limit=int(a.get('limit', 60)), sort=a.get('sort')
    )
    chains, out = {}, []
    for r in rows:
        sid = r.get('session_id')
        if sid not in chains:
            chain, cur = [], sid
            while cur and len(chain) < 30:
                chain.append(cur)
                s = db.get_session(cur) or {}
                cur = s.get('parent_session_id')
            chains[sid] = chain
        out.append(
            {
                'session': sid,
                'chain': chains[sid],
                'role': r.get('role'),
                'snippet': (r.get('snippet') or '')[:400],
                'ts': r.get('timestamp'),
            }
        )
    return {'hits': out}


if __name__ == '__main__':
    args = json.loads(sys.stdin.read() or '{}')
    try:
        out = {
            'mirror': mirror,
            'gap': gap,
            'report': report,
            'env_get': env_get,
            'env_set': env_set,
            'env_unset': env_unset,
            'claude_isolation': claude_isolation,
            'search': search,
        }[sys.argv[1]](args)
    except Exception as exc:
        out = {'error': str(exc)[:300]}
    print(json.dumps(out))
