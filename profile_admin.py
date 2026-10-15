"""Host-side profile administration for the portal (called only by the owner bridge, admin-gated in backend)."""

import time, json, os, re, subprocess, shutil
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERMES = '/root/.local/bin/hermes'
ROOT = Path('/root/.hermes')
SHARED = ROOT / 'shared-skills'  # admin-curated library, mounted into profiles via skills.external_dirs
NAME_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,31}$')
MODEL_RE = re.compile(r'^[A-Za-z0-9._:/@+-]{1,120}$')
TOOL_RE = re.compile(r'^[a-z0-9_:-]{1,60}$')
# Tools that touch the host through the terminal backend: allowed only when the profile runs its
# terminal backend in a Docker sandbox (file + code tools are routed through the same backend).
SANDBOXED_TOOLS = {'terminal', 'file', 'code_execution'}
# Dangerous for non-isolated (root) bridges: off by default on new profiles.
DEFAULT_DISABLED = [
    'browser',
    'terminal',
    'file',
    'code_execution',
    'computer_use',
    'cronjob',
    'delegation',
    'connections',
    'image_gen',
    'tts',
]
ENV = {**{k: v for k, v in os.environ.items() if k not in ('HERMES_HOME', 'HERMES_MANAGED_DIR')}, 'COLUMNS': '400', 'NO_COLOR': '1'}


def run(args, timeout=120):
    r = subprocess.run([HERMES, *args], capture_output=True, text=True, timeout=timeout, env=ENV)
    if r.returncode:
        raise ValueError((r.stderr or r.stdout).strip()[-400:] or 'hermes command failed')
    return r.stdout


def home(name):
    return ROOT if name == 'default' else ROOT / 'profiles' / name


def check(name, allow_default=False):
    if not NAME_RE.match(name or '') or (name == 'default' and not allow_default):
        raise ValueError('Invalid profile name')
    if not home(name).is_dir():
        raise ValueError('No such profile')


def unit(name):
    return 'hermes-web-bridge.service' if name == 'default' else f'hermes-web-bridge@{name}.service'


def bridge_state(name):
    return subprocess.run(['systemctl', 'is-active', unit(name)], capture_output=True, text=True).stdout.strip()


def cfg(name, key):
    """Fast read of a top-level 'section.key' scalar from config.yaml (read-only; writes still go through the CLI)."""
    section, _, leaf = key.partition('.')
    try:
        text = (home(name) / 'config.yaml').read_text()
    except OSError:
        return ''
    m = re.search(r'^%s:\s*\n((?:[ \t]+.*\n?|\s*\n)*)' % re.escape(section), text, re.M)
    if not m:
        return ''
    v = re.search(r'^[ \t]+%s:[ \t]*(.*?)[ \t]*$' % re.escape(leaf), m.group(1), re.M)
    return v.group(1).strip().strip('"\'') if v else ''


def info(name):
    desc = ''
    pf = home(name) / 'profile.yaml'
    if pf.exists():
        m = re.search(r'^description:\s*(.+)$', pf.read_text(), re.M)
        desc = m.group(1).strip().strip('"\'') if m else ''
    pool = {}
    try:
        pool = json.loads((home(name) / 'auth.json').read_text()).get('credential_pool', {})
    except Exception:
        pass
    return {
        'name': name,
        'provider': cfg(name, 'model.provider'),
        'model': cfg(name, 'model.default'),
        'description': desc,
        'bridge': bridge_state(name),
        'credentials': sorted(pool.keys()),
        'owner': name == 'default',
    }


def list_profiles():
    names = ['default'] + sorted(p.name for p in (ROOT / 'profiles').iterdir() if p.is_dir() and NAME_RE.match(p.name))
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(info, names))


def owner_providers():
    try:
        pool = json.loads((ROOT / 'auth.json').read_text()).get('credential_pool', {})
    except Exception:
        pool = {}
    out = []
    for k, v in pool.items():
        entries = v if isinstance(v, list) else [v]
        out.append(
            {
                'provider': k,
                'auth_type': entries[0].get('auth_type', '') if entries else '',
                'rotating': any('refresh_token' in e for e in entries),
            }
        )
    return out


def copy_credential(name, provider, accept_rotation=False):
    check(name)
    src = json.loads((ROOT / 'auth.json').read_text())
    pool = src.get('credential_pool', {})
    if provider not in pool:
        raise ValueError('Owner has no credential for this provider')
    entries = pool[provider] if isinstance(pool[provider], list) else [pool[provider]]
    if any('refresh_token' in e for e in entries) and not accept_rotation:
        raise ValueError('This credential uses a rotating refresh token; sharing it may log the owner out. Confirm explicitly.')
    p = home(name) / 'auth.json'
    try:
        dst = json.loads(p.read_text())
    except Exception:
        dst = {'version': src.get('version', 1), 'providers': {}, 'active_provider': None, 'credential_pool': {}}
    dst.setdefault('credential_pool', {})[provider] = pool[provider]
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(dst, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(p)
    return info(name)


def remove_credential(name, provider):
    check(name)
    p = home(name) / 'auth.json'
    dst = json.loads(p.read_text())
    dst.get('credential_pool', {}).pop(provider, None)
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(dst, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(p)
    return info(name)


def set_model(name, provider, model, allow_default=False):
    check(name, allow_default)
    if not MODEL_RE.match(provider or '') or not MODEL_RE.match(model or ''):
        raise ValueError('Invalid provider/model')
    run(['-p', name, 'config', 'set', 'model.provider', provider])
    run(['-p', name, 'config', 'set', 'model.default', model])
    return info(name)


def tools(name):
    check(name, True)
    out = []
    for line in run(['-p', name, 'tools', 'list'], 60).splitlines():
        m = re.match(r'\s*[✓✗]\s+(enabled|disabled)\s+(\S+)\s+(.*)$', line)
        # cronjob on portal profiles follows the permission feature:cron (portal reconciler), not this list
        if m and not (name != 'default' and m.group(2) == 'cronjob'):
            out.append(
                {
                    'name': m.group(2),
                    'enabled': m.group(1) == 'enabled',
                    'label': m.group(3).strip(),
                    'risky': m.group(2) in DEFAULT_DISABLED,
                }
            )
    return out


def set_tools(name, enable, disable):
    check(name)
    for t in [*enable, *disable]:
        if not TOOL_RE.match(t):
            raise ValueError('Invalid tool name')
        if t == 'cronjob':
            raise ValueError('Scheduled jobs are governed by the permission feature:cron')
    if SANDBOXED_TOOLS & set(enable) and not isolation(name)['enabled']:
        raise ValueError('Terminal, file and code tools require the Docker sandbox; enable isolation for this profile first')
    if enable:
        run(['-p', name, 'tools', 'enable', *enable])
    if disable:
        run(['-p', name, 'tools', 'disable', *disable])
    _sync_cron_platform(name)
    return tools(name)


def bridge(name, action):
    check(name, True)
    if action not in ('start', 'stop', 'restart', 'sleep', 'wake'):
        raise ValueError('Bad action')
    if name == 'default' and action in ('stop', 'sleep'):
        raise ValueError('Owner bridge cannot be stopped from the portal')
    # sleep/wake = idle saving: stop/start WITHOUT touching the enabled flag, so a bridge the admin stopped on purpose
    # (disabled unit) is never woken, and a sleeping one still starts after a host reboot.
    if action == 'sleep':
        subprocess.run(['systemctl', 'stop', unit(name)], capture_output=True, timeout=60)
        return {'name': name, 'bridge': bridge_state(name)}
    if action == 'wake':
        enabled = subprocess.run(['systemctl', 'is-enabled', unit(name)], capture_output=True, text=True).stdout.strip()
        if enabled != 'enabled':
            return {'name': name, 'bridge': bridge_state(name), 'woken': False}
        subprocess.run(['systemctl', 'start', '--no-block', unit(name)], capture_output=True, timeout=30)
        return {'name': name, 'bridge': 'activating', 'woken': True}
    if action == 'start':
        subprocess.run(['systemctl', 'enable', unit(name)], capture_output=True)
    if action == 'stop':
        subprocess.run(['systemctl', 'disable', unit(name)], capture_output=True)
    if name == 'default' and action == 'restart':
        # this code runs inside the owner bridge: a blocking restart kills the request it is answering
        subprocess.run(
            [
                'systemd-run',
                '--quiet',
                '--on-active=1s',
                '--unit=hermes-web-owner-restart-' + str(int(time.time())),
                'systemctl',
                'restart',
                unit(name),
            ],
            capture_output=True,
        )
        return {'name': name, 'bridge': 'restarting'}
    subprocess.run(['systemctl', action, unit(name)], capture_output=True, timeout=60)
    return info(name)


def create(name, provider, model, description='', credential_from=None, accept_rotation=False):
    if not NAME_RE.match(name or '') or name == 'default':
        raise ValueError('Name: lowercase a-z 0-9 _ -, up to 32 chars')
    if home(name).exists():
        raise ValueError('Profile already exists')
    if not MODEL_RE.match(provider or '') or not MODEL_RE.match(model or ''):
        raise ValueError('Invalid provider/model')
    args = ['profile', 'create', name, '--no-alias']
    if description:
        args += ['--description', description[:300]]
    run(args, 180)
    run(['-p', name, 'config', 'set', 'model.provider', provider])
    run(['-p', name, 'config', 'set', 'model.default', model])
    run(['-p', name, 'tools', 'disable', *DEFAULT_DISABLED])
    _sync_cron_platform(name)
    if credential_from:
        copy_credential(name, credential_from, accept_rotation)
    set_library(name, True)
    bridge(name, 'start')
    return info(name)


def delete(name, confirm):
    check(name)
    if confirm != name:
        raise ValueError('Type the profile name to confirm')
    bridge(name, 'stop')
    run(['profile', 'delete', '-y', name], 180)
    (Path(__file__).parent / 'bridge-ipc' / f'bridge-{name}.sock').unlink(missing_ok=True)  # no stale socket in the profile lists
    return {'deleted': name}


def usage(name, session_id):
    """Token/cost totals for a stored session and its continuation chain (compression rotates ids)."""
    import sqlite3

    check(name, True)
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', session_id or ''):
        raise ValueError('bad session id')
    db = home(name) / 'state.db'
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=5)
    try:
        ids = [session_id]
        frontier = [session_id]
        while frontier:
            q = 'SELECT id FROM sessions WHERE parent_session_id IN (%s)' % ','.join('?' * len(frontier))
            frontier = [r[0] for r in c.execute(q, frontier) if r[0] not in ids]
            ids += frontier
        q = (
            'SELECT COALESCE(SUM(input_tokens),0),COALESCE(SUM(output_tokens),0),COALESCE(SUM(cache_read_tokens),0),COALESCE(SUM(cache_write_tokens),0),COALESCE(SUM(COALESCE(actual_cost_usd,estimated_cost_usd,0)),0),GROUP_CONCAT(DISTINCT model),GROUP_CONCAT(DISTINCT billing_provider) FROM sessions WHERE id IN (%s)'
            % ','.join('?' * len(ids))
        )
        i, o, cr, cw, cost, models, providers = c.execute(q, ids).fetchone()
    finally:
        c.close()
    return {
        'input': i,
        'output': o,
        'cache_read': cr,
        'cache_write': cw,
        'cost': round(cost, 6),
        'models': models or '',
        'providers': providers or '',
        'sessions': len(ids),
    }


_MACHINE_OPENERS = ('[CONTEXT COMPACTION', '[Runtime note:', '[System note:', '[SYSTEM]', '[System: ')


def _opening_text(content):
    """Typed text of a stored user message (attachment footers and machine openers dropped)."""
    if not isinstance(content, str):
        return ''
    try:
        parsed = json.loads(content) if content[:1] in '[{' else None
        if isinstance(parsed, list):
            content = '\n'.join(p.get('text', '') for p in parsed if isinstance(p, dict))
    except ValueError:
        pass
    text = content.split('\n--- Attached Context ---')[0].split('\n--- Context Warnings ---')[0].strip()
    return '' if text.startswith(_MACHINE_OPENERS) else text


def session_titles(name, ids):
    """Native Hermes titles (title, provenance) for stored sessions, read-only from the profile's state.db.
    A compression rotation may move the title onto the continuation, so the whole chain is checked.
    'first' (the opening user text) is returned only when Hermes has no automatic title to offer."""
    import sqlite3

    check(name, True)
    ids = [i for i in (ids or [])[:200] if isinstance(i, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', i)]
    db = home(name) / 'state.db'
    if not ids or not db.exists():
        return {}
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True, timeout=5)
    out = {}
    try:
        for sid in ids:
            chain = [sid]
            frontier = [sid]
            while frontier and len(chain) < 50:
                q = 'SELECT id FROM sessions WHERE parent_session_id IN (%s)' % ','.join('?' * len(frontier))
                frontier = [r[0] for r in c.execute(q, frontier) if r[0] not in chain]
                chain += frontier
            marks = ','.join('?' * len(chain))
            rows = c.execute(
                f'SELECT id,title,title_source FROM sessions WHERE id IN ({marks}) AND title IS NOT NULL ORDER BY (id=?) DESC,started_at DESC',
                (*chain, sid),
            ).fetchall()
            title, source = (rows[0][1], rows[0][2] or 'user') if rows else (None, None)
            item = {'title': title, 'source': source}
            if source in (None, 'user'):
                for (content,) in c.execute(
                    f"SELECT content FROM messages WHERE session_id IN ({marks}) AND role='user' ORDER BY id LIMIT 6", chain
                ):
                    if text := _opening_text(content):
                        item['first'] = text[:1000]
                        break
            out[sid] = item
    finally:
        c.close()
    return out


SKILL_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')


def cfg_list(name, section, key):
    try:
        text = (home(name) / 'config.yaml').read_text()
    except OSError:
        return []
    m = re.search(r'^%s:\s*\n((?:[ \t]+.*\n?|\s*\n)*)' % re.escape(section), text, re.M)
    if not m:
        return []
    block = m.group(1)
    inline = re.search(r'^([ \t]+)%s:[ \t]*\[(.*)\][ \t]*$' % re.escape(key), block, re.M)
    if inline:
        return [x.strip().strip('"\'') for x in inline.group(2).split(',') if x.strip()]
    km = re.search(r'^([ \t]+)%s:[ \t]*\n((?:\1[ \t]*-[ \t]*.*\n?)*)' % re.escape(key), block, re.M)
    return [l.split('-', 1)[1].strip().strip('"\'') for l in km.group(2).splitlines() if l.strip()] if km else []


def frontmatter(md):
    try:
        text = md.read_text(errors='replace')[:4000]
    except OSError:
        return {}
    m = re.match(r'---\s*\n(.*?)\n---', text, re.S)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(':')
            if k.strip() in ('name', 'description') and v.strip():
                out[k.strip()] = v.strip().strip('"\'')
    return out


def library():
    SHARED.mkdir(parents=True, exist_ok=True)
    out = []
    for md in sorted(SHARED.glob('*/*/SKILL.md')):
        fm = frontmatter(md)
        out.append({'name': fm.get('name', md.parent.name), 'category': md.parent.parent.name, 'description': fm.get('description', '')})
    return out


def find_skill_dir(base, skill):
    for md in base.glob('**/SKILL.md'):
        if md.parent.name == skill or frontmatter(md).get('name') == skill:
            return md.parent
    return None


def library_enabled(name):
    return str(SHARED) in cfg_list(name, 'skills', 'external_dirs')


def skills(name):
    check(name, True)
    out = []
    for line in run(['-p', name, 'skills', 'list', '--source', 'all'], 90).splitlines():
        cells = [c.strip() for c in line.strip().strip('│').split('│')]
        if len(cells) == 5 and cells[2] in ('builtin', 'hub', 'local', 'external'):
            n, cat, src, trust, status = cells
            item = {'name': n, 'category': cat, 'source': src, 'enabled': status == 'enabled', 'description': ''}
            if src in ('local', 'external'):
                d = find_skill_dir(SHARED if src == 'external' else home(name) / 'skills', n)
                if d:
                    item['description'] = frontmatter(d / 'SKILL.md').get('description', '')
            out.append(item)
    return {'library_enabled': library_enabled(name), 'skills': out}


def set_skill(name, skill, enabled):
    check(name)
    if not SKILL_RE.match(skill or ''):
        raise ValueError('Invalid skill name')
    disabled = [x for x in cfg_list(name, 'skills', 'disabled') if x != skill]
    if not enabled:
        disabled.append(skill)
    run(['-p', name, 'config', 'set', 'skills.disabled', json.dumps(sorted(set(disabled)))])
    return skills(name)


def set_library(name, enabled):
    check(name)
    SHARED.mkdir(parents=True, exist_ok=True)
    dirs = [d for d in cfg_list(name, 'skills', 'external_dirs') if d != str(SHARED)]
    if enabled:
        dirs.append(str(SHARED))
    run(['-p', name, 'config', 'set', 'skills.external_dirs', json.dumps(dirs)])
    return {'library_enabled': library_enabled(name)}


def promote(name, skill):
    check(name, True)
    if not SKILL_RE.match(skill or ''):
        raise ValueError('Invalid skill name')
    if any(s['name'] == skill for s in library()):
        raise ValueError('Library already has a skill with this name')
    src = next((s for s in skills(name)['skills'] if s['name'] == skill), None)
    if not src or src['source'] != 'local':
        raise ValueError('Only personal (agent-created) skills can be added to the library')
    d = find_skill_dir(home(name) / 'skills', skill)
    if not d:
        raise ValueError('Skill files not found')
    dst = SHARED / (src['category'] if re.match(r'^[a-z0-9_-]{1,40}$', src['category'] or '') else 'general') / skill
    shutil.copytree(d, dst)
    return library()


def library_delete(skill):
    if not SKILL_RE.match(skill or ''):
        raise ValueError('Invalid skill name')
    d = find_skill_dir(SHARED, skill)
    if not d or SHARED not in d.parents:
        raise ValueError('No such library skill')
    shutil.rmtree(d)
    if not any(d.parent.iterdir()):
        d.parent.rmdir()
    return library()


def delete_personal(name, skill):
    check(name)
    if not SKILL_RE.match(skill or ''):
        raise ValueError('Invalid skill name')
    src = next((s for s in skills(name)['skills'] if s['name'] == skill), None)
    if not src or src['source'] != 'local':
        raise ValueError('Only personal skills can be deleted')
    d = find_skill_dir(home(name) / 'skills', skill)
    if not d or (home(name) / 'skills') not in d.parents:
        raise ValueError('Skill files not found')
    shutil.rmtree(d)
    return skills(name)


def env_keys(name):
    """Names (never values) of credential env vars stored in the profile's own .env."""
    check(name, True)
    try:
        lines = (home(name) / '.env').read_text().splitlines()
    except OSError:
        return []
    return sorted({l.split('=', 1)[0].strip() for l in lines if '=' in l and not l.lstrip().startswith('#') and l.split('=', 1)[1].strip()})


# ---- Cursor Agent CLI key (portal feature:cursor_agent): stored as CURSOR_API_KEY in the profile .env; the shared
# skill `cursor-agent` declares it in required_environment_variables, so Hermes forwards it only into the profile's
# Docker sandbox, where cursor-agent runs. The value never leaves the host (status returns account metadata only).
CURSOR_ENV = 'CURSOR_API_KEY'
CURSOR_KEY_RE = re.compile(r'^[A-Za-z0-9_.:-]{16,400}$')
CURSOR_CACHE = {}  # sha256(key) -> (ts, account|None)


def _cursor_account(key, fresh=False):
    """Validate a key against Cursor's API (GET /v0/me, basic auth). None = rejected key."""
    import urllib.request, urllib.error, base64, hashlib

    h = hashlib.sha256(key.encode()).hexdigest()
    hit = CURSOR_CACHE.get(h)
    if hit and not fresh and time.time() - hit[0] < 300:
        return hit[1]
    req = urllib.request.Request(
        'https://api.cursor.com/v0/me',
        headers={'Authorization': 'Basic ' + base64.b64encode((key + ':').encode()).decode(), 'User-Agent': 'shroom-portal'},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode() or '{}')
        acc = {'email': str(d.get('userEmail') or '')[:200], 'key_name': str(d.get('apiKeyName') or '')[:200]}
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403):
            raise ValueError(f'Cursor API відповів помилкою {e.code}; спробуйте пізніше') from None
        acc = None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('Cursor API недоступний; спробуйте пізніше') from None
    CURSOR_CACHE[h] = (time.time(), acc)
    return acc


def cursor_status(name):
    check(name)
    key = hermes_py(name, 'env_get', {'key': CURSOR_ENV})['value']
    iso = isolation(name)
    out = {
        'connected': bool(key),
        'valid': None,
        'email': '',
        'key_name': '',
        'sandbox': iso['enabled'],
        'network': iso['network'],
        'terminal': any(t['name'] == 'terminal' and t['enabled'] for t in tools(name)),
    }
    if key:
        try:
            acc = _cursor_account(key)
            out['valid'] = acc is not None
            if acc:
                out.update(acc)
        except ValueError as e:
            out['check_error'] = str(e)
    return out


def set_cursor_key(name, key):
    check(name)
    key = (key or '').strip()
    if not CURSOR_KEY_RE.match(key):
        raise ValueError('Це не схоже на ключ Cursor')
    if _cursor_account(key, fresh=True) is None:
        raise ValueError('Cursor не прийняв цей ключ')
    hermes_py(name, 'env_set', {'key': CURSOR_ENV, 'value': key})
    return cursor_status(name)


def remove_cursor_key(name):
    check(name)
    hermes_py(name, 'env_unset', {'key': CURSOR_ENV})
    return cursor_status(name)


def isolation(name):
    check(name, True)
    return {
        'enabled': cfg(name, 'terminal.backend') == 'docker',
        'memory_mb': int(cfg(name, 'terminal.container_memory') or 5120),
        'cpus': float(cfg(name, 'terminal.container_cpu') or 1),
        'image': cfg(name, 'terminal.docker_image') or 'nousresearch/hermes-sandbox:desktop',
        'network': cfg(name, 'terminal.docker_network') != 'false',
    }


def set_isolation(name, enabled, memory_mb=2048, cpus=1.0, network=True):
    check(name)
    if not enabled:
        on = [t['name'] for t in tools(name) if t['enabled'] and t['name'] in SANDBOXED_TOOLS]
        if on:
            run(['-p', name, 'tools', 'disable', *on])
        run(['-p', name, 'config', 'set', 'terminal.backend', 'local'])
        return isolation(name)
    if not (256 <= int(memory_mb) <= 6144) or not (0.25 <= float(cpus) <= 2):
        raise ValueError('Memory 256-6144 MB, CPUs 0.25-2')
    for k, v in (
        ('terminal.backend', 'docker'),
        ('terminal.container_memory', str(int(memory_mb))),
        ('terminal.container_cpu', str(float(cpus))),
        ('terminal.docker_mount_cwd_to_workspace', 'false'),
        ('terminal.docker_volumes', '[]'),
        ('terminal.docker_forward_env', '[]'),
        ('terminal.docker_network', 'true' if network else 'false'),
        ('terminal.docker_persist_across_processes', 'true'),
        ('terminal.cwd', '/workspace'),
    ):
        run(['-p', name, 'config', 'set', k, v])
    return isolation(name)


# ---- provider OAuth via the native CLI device-code flow (`hermes auth add <p> --type oauth --no-browser`) ----
OAUTH_PROVIDERS = {'openai-codex', 'nous', 'xai-oauth', 'anthropic'}
# Anthropic (Claude Pro/Max) uses PKCE with a paste-back code instead of a device code: the CLI prints a claude.ai
# link and reads "code#state" from stdin, so its job keeps a stdin pipe that oauth_code() feeds.
PASTE_CODE = {'anthropic'}
JOBS = {}  # job id -> {'proc','log','profile','provider','started'}


def oauth_start(name, provider):
    import uuid, time

    check(name)
    if provider not in OAUTH_PROVIDERS:
        raise ValueError('OAuth sign-in is not supported for this provider')
    for j in JOBS.values():
        if j['profile'] == name and j['proc'].poll() is None:
            j['proc'].terminate()
    for stale in Path('/srv/hermes-web/bridge-ipc').glob('.oauth-*.log'):
        if stale.stem[len('.oauth-') :] not in JOBS:
            stale.unlink(missing_ok=True)
    jid = uuid.uuid4().hex
    log = Path('/srv/hermes-web/bridge-ipc') / f'.oauth-{jid}.log'
    fh = open(log, 'w')
    os.chmod(log, 0o600)
    paste = provider in PASTE_CODE
    # priority 0: the user's own grant is tried before anything else left in the profile pool
    cmd = [HERMES, '-p', name, 'auth', 'add', provider, '--type', 'oauth', '--no-browser', '--timeout', '600'] + (
        ['--priority', '0'] if paste else []
    )
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE if paste else subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, env=ENV, start_new_session=True
    )
    JOBS[jid] = {'proc': proc, 'log': log, 'profile': name, 'provider': provider, 'started': time.time(), 'paste': paste}
    for _ in range(40):
        time.sleep(0.5)
        st = oauth_status(jid)
        if (st['url'] and (st['code'] or paste)) or st['state'] != 'running':
            return st
    return oauth_status(jid)


OAUTH_CODE_RE = re.compile(r'^[A-Za-z0-9_\-.~]{8,400}#[A-Za-z0-9_\-.~]{8,200}$')


def oauth_code(jid, code):
    """Hand the paste-back code ("code#state" from the claude.ai callback page) to a running PKCE sign-in."""
    j = JOBS.get(jid)
    if not j or not j.get('paste'):
        raise ValueError('Unknown sign-in job')
    code = (code or '').strip()
    if not OAUTH_CODE_RE.match(code):
        raise ValueError('Скопіюйте код повністю: він має вигляд «код#стан».')
    if j['proc'].poll() is not None or j.get('code_sent'):
        raise ValueError('Sign-in is no longer waiting for a code')
    j['code_sent'] = True
    j['proc'].stdin.write((code + '\n').encode())
    j['proc'].stdin.close()
    try:
        j['proc'].wait(30)
    except subprocess.TimeoutExpired:
        pass
    return oauth_status(jid)


def oauth_status(jid):
    j = JOBS.get(jid)
    if not j:
        raise ValueError('Unknown sign-in job')
    text = j['log'].read_text(errors='replace') if j['log'].exists() else ''
    text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text)  # CLI colours
    url = re.search(r'https://\S+', text)
    code = (
        None
        if j.get('paste')
        else re.search(r'(?<![\w/-])([A-Z0-9]{3,6}(?:-[A-Z0-9]{3,6})+)(?![\w/-])', text.split(url.group(0), 1)[-1] if url else text)
    )
    rc = j['proc'].poll()
    state = 'running' if rc is None else ('succeeded' if rc == 0 else 'failed')
    if state == 'succeeded' and j['provider'] == 'anthropic' and not j.get('isolated'):
        anthropic_own(j['profile'], True)
        j['isolated'] = True
    if rc is not None and j['log'].exists():
        j['log'].unlink()
    return {
        'job': jid,
        'state': state,
        'url': url.group(0) if url else '',
        'code': code.group(1) if code else '',
        'paste': bool(j.get('paste')),
        'profile': j['profile'],
        'provider': j['provider'],
    }


def anthropic_own(name, own):
    """Own Claude subscription in a user profile: stop the profile from adopting the host's Claude Code login
    (the owner's shared subscription in /root/.claude, which every root-run bridge can read). Native switches only:
    `auth.adopt_external_logins` (the single reader of ~/.claude, so no resolver or 401-refresh fallback reaches it)
    plus the `suppressed_sources` marker for anthropic/claude_code. own=False restores the defaults on disconnect."""
    check(name)
    run(['-p', name, 'config', 'set', 'auth.adopt_external_logins', 'false' if own else 'true'])
    hermes_py(name, 'claude_isolation', {'own': bool(own)})
    return anthropic_own_status(name)


def anthropic_own_status(name):
    check(name, True)
    cfg = (home(name) / 'config.yaml').read_text(errors='replace') if (home(name) / 'config.yaml').exists() else ''
    m = re.search(r'(?m)^auth:\s*\n(?:[ \t]+.*\n)*?[ \t]+adopt_external_logins:\s*(\S+)', cfg)
    try:
        sup = json.loads((home(name) / 'auth.json').read_text()).get('suppressed_sources', {}).get('anthropic', [])
    except (OSError, ValueError):
        sup = []
    return {'adopt_external_logins': not (m and m.group(1).strip('\'"').lower() == 'false'), 'claude_code_suppressed': 'claude_code' in sup}


def oauth_cancel(jid):
    j = JOBS.pop(jid, None)
    if not j:
        return {'state': 'cancelled'}
    if j['proc'].poll() is None:
        j['proc'].terminate()
        try:
            j['proc'].wait(5)
        except subprocess.TimeoutExpired:
            j['proc'].kill()
    j['log'].unlink(missing_ok=True)
    return {'job': jid, 'state': 'cancelled', 'url': '', 'code': '', 'profile': j['profile'], 'provider': j['provider']}


# ---- plugins (native `hermes plugins list --json / enable / disable`) ----
def plugin_group(n):
    if n.endswith('-platform'):
        return None  # messenger adapters: gateway-only, not used by the portal
    if n.startswith(('browser-', 'web-')):
        return 'Пошук і браузер'
    if n in ('basic', 'drain', 'nous', 'self-hosted', 'chronos'):
        return 'Службові'
    if n in ('deepinfra', 'fal', 'krea', 'meta-ai-image-gen', 'openai', 'openai-codex', 'openrouter', 'xai'):
        return 'Генерація зображень і моделі'
    return 'Можливості'


def plugins(name):
    check(name, allow_default=True)
    raw = json.loads(run(['-p', name, 'plugins', 'list', '--json'], 90) or '[]')
    seen = set()
    out = []
    for x in raw:
        g = plugin_group(x['name'])
        if not g or x['name'] in seen:
            continue
        seen.add(x['name'])
        out.append(
            {
                'name': x['name'],
                'enabled': x.get('status') == 'enabled',
                'description': x.get('description') or '',
                'source': x.get('source'),
                'group': g,
            }
        )
    return {'sandbox': isolation(name)['enabled'] if name != 'default' else False, 'plugins': out}


def set_plugin(name, plugin, enabled):
    check(name)
    known = {x['name'] for x in plugins(name)['plugins']}
    if plugin not in known:
        raise ValueError('Unknown plugin')
    if enabled and not isolation(name)['enabled']:
        raise ValueError('Plugins can be enabled only for profiles with the Docker sandbox')
    run(['-p', name, 'plugins', 'enable' if enabled else 'disable', plugin] + (['--no-allow-tool-override'] if enabled else []), 90)
    if bridge_state(name) == 'active':
        bridge(name, 'restart')
    return plugins(name)


# ---- subscription limits (native `hermes usage --json`: Anthropic OAuth windows, Codex 5h/weekly, OpenRouter credits) ----
_LIMITS = {}


def configured_provider(name):
    return cfg(name, 'model.provider') or ''


_LIMITS_FILE = ROOT / 'cache' / 'portal-limits.json'  # last good reading per (profile, provider); survives bridge restarts


def _limits_store(key=None, value=None):
    try:
        data = json.loads(_LIMITS_FILE.read_text())
    except (OSError, ValueError):
        data = {}
    if key is None:
        return data
    data[key] = value
    tmp = _LIMITS_FILE.with_suffix('.tmp')
    try:
        _LIMITS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data))
        os.chmod(tmp, 0o600)
        tmp.replace(_LIMITS_FILE)
    except OSError:
        pass


def _stale(good, now):
    """Last good reading marked stale; a window whose reset time has passed is shown as reset."""
    out = {**good, 'stale': True, 'windows': []}
    for w in good.get('windows') or []:
        try:
            passed = bool(w.get('resets_at')) and datetime.fromisoformat(str(w['resets_at']).replace('Z', '+00:00')).timestamp() < now
        except ValueError:
            passed = False
        out['windows'].append({**w, 'used': 0, 'resets_at': None, 'detail': 'вікно вже скинулось'} if passed else w)
    return out


def account_limits(name, provider=None, max_age=120):  # the Anthropic usage endpoint rate-limits frequent reads
    """`hermes usage --json` for the profile's provider. A failed or empty read (provider rate limit, timeout,
    network) falls back to the last good reading for the same provider, flagged stale, instead of nothing."""
    check(name, allow_default=True)
    prov = provider or configured_provider(name)
    key = (name, prov)
    now = time.time()
    if key in _LIMITS and now - _LIMITS[key][0] < max_age:
        return _LIMITS[key][1]
    try:
        r = subprocess.run(
            [HERMES, '-p', name, 'usage', '--json'] + (['--provider', prov] if prov else []),
            capture_output=True,
            text=True,
            timeout=45,
            env=ENV,
        )
        d = json.loads(r.stdout)
    except Exception:
        d = None
    if d is not None:
        out = {
            'provider': d.get('provider') or prov,
            'plan': d.get('plan'),
            'fetched_at': d.get('fetched_at') or now,
            'windows': [
                {'label': w.get('label'), 'used': w.get('used_percent'), 'resets_at': w.get('resets_at'), 'detail': w.get('detail')}
                for w in d.get('windows') or []
            ],
            'details': d.get('details') or [],
            'unavailable': d.get('unavailable_reason')
            or (None if d.get('windows') or d.get('details') else 'Ліміти для цього провайдера недоступні'),
        }
    else:
        out = {
            'provider': prov,
            'plan': None,
            'fetched_at': None,
            'windows': [],
            'details': [],
            'unavailable': 'Ліміти для цього провайдера недоступні',
        }
    skey = f'{name}|{prov}'
    if out['windows']:
        _limits_store(skey, {**out, 'fetched_at': out['fetched_at'] if isinstance(out['fetched_at'], (int, float)) else now})
    elif (good := _limits_store().get(skey)) and now - good.get('fetched_at', 0) < 7 * 86400:
        out = _stale(good, now)
        _LIMITS[key] = (now - max_age + 15, out)
        return out  # retry the live read sooner than the normal cache window
    _LIMITS[key] = (now, out)
    return out


EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh')


def reasoning(name):
    check(name, True)
    return {'effort': cfg(name, 'agent.reasoning_effort') or ''}


def set_reasoning(name, effort, allow_default=False):
    check(name, allow_default)
    if effort and effort not in EFFORTS:
        raise ValueError('Invalid reasoning effort')
    run(['-p', name, 'config', 'set', 'agent.reasoning_effort', effort or ''])
    return reasoning(name)


def backup_status():
    d = Path('/srv/hermes-web-backups/daily')
    dbs = sorted(d.glob('portal-*.db'), key=lambda f: f.stat().st_mtime) if d.is_dir() else []
    return {
        'last': dbs[-1].stat().st_mtime if dbs else None,
        'count': len(dbs),
        'size': sum(f.stat().st_size for f in d.iterdir()) if d.is_dir() else 0,
    }


# ---- Safe profile documents and allowlisted native memory configuration ----
# These operations do not restart bridges: prompt snapshots change next session.
import hashlib, stat, uuid, fcntl
from contextlib import contextmanager, ExitStack

PROFILE_DOCUMENTS = {'soul': ('SOUL.md',), 'memory': ('memories', 'MEMORY.md'), 'user': ('memories', 'USER.md')}
MEMORY_DEFAULTS = {
    'memory_enabled': True,
    'user_profile_enabled': True,
    'write_approval': False,
    'memory_char_limit': 2200,
    'user_char_limit': 1375,
    'nudge_interval': 10,
}
SOUL_CHAR_LIMIT = 20000
_DOCUMENT_READ_BYTES = 1024 * 1024


@contextmanager
def _document_directory(name):
    """Walk every ancestor with O_NOFOLLOW; keep descriptors pinned for all I/O."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ValueError('Некоректна назва профілю')
    root = Path(ROOT)
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('Небезпечний шлях профілю')
    with ExitStack() as stack:
        try:
            fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            stack.callback(os.close, fd)
            parts = list(root.parts[1:]) + ([] if name == 'default' else ['profiles', name])
            for part in parts:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                stack.callback(os.close, fd)
            yield fd
        except OSError:
            raise ValueError('Небезпечний або недоступний шлях профілю') from None


@contextmanager
def _document_child(fd, part, create=False):
    if create:
        try:
            os.mkdir(part, 0o700, dir_fd=fd)
        except FileExistsError:
            pass
    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        yield child
    finally:
        os.close(child)


def _document_read(fd, leaf, max_bytes=_DOCUMENT_READ_BYTES):
    try:
        raw = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return b''
    with os.fdopen(raw, 'rb') as stream:
        st = os.fstat(stream.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ValueError('Документ має бути звичайним файлом без посилань')
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError('Файл перевищує допустимий розмір')
    return data


def _document_text(data):
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        raise ValueError('Документ має бути у кодуванні UTF-8') from None


@contextmanager
def _document_lock(fd, leaf):
    raw = os.open(leaf, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=fd)
    try:
        st = os.fstat(raw)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise ValueError('Небезпечний файл блокування')
        os.fchmod(raw, 0o600)
        fcntl.flock(raw, fcntl.LOCK_EX)
        yield
    finally:
        os.close(raw)


def _document_atomic(fd, leaf, data):
    tmp = '.portal-' + uuid.uuid4().hex + '.tmp'
    raw = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(raw, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, leaf, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(tmp, dir_fd=fd)
        except FileNotFoundError:
            pass


def _memory_values(fd):
    text = _document_text(_document_read(fd, 'config.yaml', 2 * 1024 * 1024))
    try:
        import yaml
    except ImportError:
        raise ValueError('Для безпечного читання конфігурації потрібен PyYAML') from None
    try:
        config = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        raise ValueError('Некоректна конфігурація профілю') from None
    if not isinstance(config, dict):
        raise ValueError('Некоректна конфігурація профілю')
    memory = config.get('memory', {})
    if memory is None:
        memory = {}
    if not isinstance(memory, dict):
        raise ValueError('Некоректна конфігурація пам’яті')
    values = {key: memory.get(key, default) for key, default in MEMORY_DEFAULTS.items()}
    _validate_memory_changes(values)
    return values


def _validate_memory_changes(changes):
    if not isinstance(changes, dict) or any(k not in MEMORY_DEFAULTS for k in changes):
        raise ValueError('Дозволені лише безпечні поля конфігурації пам’яті')
    for key, value in changes.items():
        if type(MEMORY_DEFAULTS[key]) is bool:
            if type(value) is not bool:
                raise ValueError('Поле ' + key + ' має бути логічним значенням')
        else:
            low, high = (0, 100) if key == 'nudge_interval' else (100, 20000)
            if type(value) is not int or not low <= value <= high:
                raise ValueError('Поле ' + key + ' має бути цілим числом від ' + str(low) + ' до ' + str(high))


def _document_parts(document):
    if not isinstance(document, str) or document not in PROFILE_DOCUMENTS:
        raise ValueError('Невідомий документ профілю')
    return PROFILE_DOCUMENTS[document]


def _document_bytes(fd, document):
    parts = _document_parts(document)
    if len(parts) == 1:
        return _document_read(fd, parts[0])
    try:
        with _document_child(fd, parts[0]) as child:
            return _document_read(child, parts[1])
    except FileNotFoundError:
        return b''


def _document_result(fd, document):
    data = _document_bytes(fd, document)
    values = _memory_values(fd)
    limit = SOUL_CHAR_LIMIT if document == 'soul' else values['memory_char_limit' if document == 'memory' else 'user_char_limit']
    return {'document': document, 'content': _document_text(data), 'revision': hashlib.sha256(data).hexdigest(), 'limit': limit}


def profile_document(name, document):
    _document_parts(document)
    with _document_directory(name) as fd:
        return _document_result(fd, document)


def _document_backup(fd, document, data):
    # Never store prior prompt content under memories/ or skills/.
    with _document_child(fd, 'backups', True) as backups:
        with _document_child(backups, 'profile-documents', True) as docs:
            with _document_child(docs, document, True) as versions:
                for leaf in os.listdir(versions):
                    st = os.stat(leaf, dir_fd=versions, follow_symlinks=False)
                    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                        raise ValueError('Небезпечний файл резервної копії')
                leaf = f'{time.time_ns():020d}-{uuid.uuid4().hex}.bak'
                _document_atomic(versions, leaf, data)
                for old in sorted(os.listdir(versions))[:-10]:
                    os.unlink(old, dir_fd=versions)
                os.fsync(versions)


def set_profile_document(name, document, content, revision):
    parts = _document_parts(document)
    if not isinstance(content, str):
        raise ValueError('Вміст документа має бути текстом')
    try:
        data = content.encode('utf-8')
    except UnicodeEncodeError:
        raise ValueError('Документ має бути у кодуванні UTF-8') from None
    if len(content) > SOUL_CHAR_LIMIT or len(data) > _DOCUMENT_READ_BYTES:
        raise ValueError('Документ перевищує допустимий розмір')
    if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{64}', revision):
        raise ValueError('Некоректна ревізія документа')
    with _document_directory(name) as fd, _document_lock(fd, '.portal-documents.lock'):
        with ExitStack() as stack:
            target = fd if len(parts) == 1 else stack.enter_context(_document_child(fd, parts[0], True))
            # Same lock as native MemoryStore: do not overwrite concurrent agent writes.
            stack.enter_context(_document_lock(target, parts[-1] + '.lock'))
            current = _document_result(fd, document)
            if current['revision'] != revision:
                raise ValueError('Document changed: документ змінився; перечитайте його перед збереженням')
            if len(content) > current['limit']:
                raise ValueError('Документ перевищує ліміт символів')
            previous = _document_bytes(fd, document)
            if previous != data:
                _document_backup(fd, document, previous)
                # Re-check external writers that do not honor the native lock.
                if hashlib.sha256(_document_bytes(fd, document)).hexdigest() != revision:
                    raise ValueError('Document changed: документ змінився; перечитайте його перед збереженням')
                _document_atomic(target, parts[-1], data)
            return _document_result(fd, document)


def profile_memory_config(name):
    with _document_directory(name) as fd:
        return {'values': _memory_values(fd)}


def set_profile_memory_config(name, changes):
    _validate_memory_changes(changes)  # Validate the entire payload before any CLI write.
    with _document_directory(name) as fd, _document_lock(fd, '.portal-documents.lock'):
        _memory_values(fd)
        with ExitStack() as stack:
            memories = stack.enter_context(_document_child(fd, 'memories', True))
            for leaf in ('MEMORY.md', 'USER.md'):
                stack.enter_context(_document_lock(memories, leaf + '.lock'))
            _memory_values(fd)
            for document, key in (('memory', 'memory_char_limit'), ('user', 'user_char_limit')):
                if key in changes and changes[key] < len(_document_text(_document_bytes(fd, document))):
                    raise ValueError('Ліміт не може бути меншим за поточний вміст документа')
            for key, value in changes.items():
                # Native CLI resolves paths itself: reject a replaced profile/ancestor
                # as well as linked config files immediately before invoking it.
                with _document_directory(name) as live:
                    held_stat, live_stat = os.fstat(fd), os.fstat(live)
                    if (held_stat.st_dev, held_stat.st_ino) != (live_stat.st_dev, live_stat.st_ino):
                        raise ValueError('Шлях профілю змінився; повторіть операцію')
                    _memory_values(live)
                try:
                    run(['-p', name, 'config', 'set', 'memory.' + key, str(value)])
                except ValueError:
                    raise ValueError('Не вдалося зберегти конфігурацію пам’яті; перечитайте поточні значення') from None
            result = {'values': _memory_values(fd)}
            if any(result['values'][key] != value for key, value in changes.items()):
                raise ValueError('Не вдалося перевірити збережену конфігурацію пам’яті')
            return result


# ---------------- scheduled jobs (native Hermes cron; the host gateway's ticker fires them) ----------------
CRON_ID_RE = re.compile(r'^[a-f0-9]{6,40}$')
RUN_FILE_RE = re.compile(r'^\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d[A-Za-z0-9_.-]{0,40}\.md$')
HELPER = Path(__file__).parent / 'ops' / 'cron_helper.py'


def _hermes_python():
    found = sorted((ROOT / 'tools').glob('python-3*/bin/python3'))
    if not found:
        raise ValueError('Hermes Python not found')
    return str(found[-1])


def hermes_py(name, cmd, args, timeout=60):
    """Run ops/cron_helper.py inside Hermes' own interpreter for one profile (native modules, not reimplemented)."""
    env = {**ENV, 'HERMES_HOME': str(home(name))}
    r = subprocess.run(
        [_hermes_python(), '-I', str(HELPER), cmd], input=json.dumps(args), capture_output=True, text=True, timeout=timeout, env=env
    )
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise ValueError('cron helper failed: ' + (r.stderr or r.stdout)[-300:])
    if isinstance(out, dict) and isinstance(out.get('error'), str):
        raise ValueError(out['error'])
    return out


def _cron_jobs(name):
    try:
        return json.loads((home(name) / 'cron' / 'jobs.json').read_text()).get('jobs', [])
    except (OSError, ValueError):
        return []


def _cron_job(name, jid):
    if not CRON_ID_RE.match(jid or ''):
        raise ValueError('bad job id')
    for j in _cron_jobs(name):
        if j.get('id') == jid:
            return j
    raise ValueError('No such job')


CRON_KEYS = (
    'id',
    'name',
    'prompt',
    'schedule',
    'schedule_display',
    'enabled',
    'state',
    'paused_reason',
    'created_at',
    'next_run_at',
    'last_run_at',
    'last_status',
    'last_error',
    'deliver',
    'script',
    'no_agent',
    'monitor_script',
    'monitor_url',
    'workdir',
    'enabled_toolsets',
    'repeat',
    'skills',
)


def cron_list(name):
    check(name, True)
    out = []
    for j in _cron_jobs(name):
        d = home(name) / 'cron' / 'output' / str(j.get('id'))
        runs = sorted((f.name for f in d.glob('*.md') if RUN_FILE_RE.match(f.name)), reverse=True)[:30] if d.is_dir() else []
        out.append({**{k: j.get(k) for k in CRON_KEYS}, 'runs': runs})
    hb = home(name) / 'cron' / 'ticker_heartbeat'
    return {'jobs': out, 'ticker_age': round(time.time() - hb.stat().st_mtime) if hb.exists() else None}


def cron_action(name, jid, action):
    check(name, True)
    _cron_job(name, jid)
    if action == 'run':  # `cron run` executes the job synchronously; never hold the owner bridge for a long run
        subprocess.Popen(
            [HERMES, '-p', name, 'cron', 'run', jid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV, start_new_session=True
        )
        return {'id': jid, 'started': True}
    if action not in ('pause', 'resume', 'remove'):
        raise ValueError('bad action')
    run(['-p', name, 'cron', action, jid])
    return {'id': jid, action: True}


def cron_edit(name, jid, fields):
    check(name, True)
    _cron_job(name, jid)
    args = []
    for k in ('name', 'schedule', 'prompt', 'deliver'):
        v = fields.get(k)
        if v is None:
            continue
        if not isinstance(v, str) or len(v) > (8000 if k == 'prompt' else 200) or (k != 'prompt' and '\n' in v):
            raise ValueError('bad ' + k)
        args += ['--' + k, v]
    if args:
        run(['-p', name, 'cron', 'edit', jid, *args])
    return {k: _cron_job(name, jid).get(k) for k in CRON_KEYS}


def cron_gap(name, schedule):
    check(name, True)
    if not isinstance(schedule, (str, dict)) or (isinstance(schedule, str) and (len(schedule) > 120 or '\n' in schedule)):
        raise ValueError('bad schedule')
    return hermes_py(name, 'gap', {'schedule': schedule})


def cron_report(name, jid, file):
    check(name, True)
    if not CRON_ID_RE.match(jid or '') or not RUN_FILE_RE.match(file or ''):
        raise ValueError('bad run')
    p = home(name) / 'cron' / 'output' / jid / file
    if not p.is_file() or p.is_symlink():
        raise ValueError('No such run')
    return {**hermes_py(name, 'report', {'path': str(p)}), 'file': file}


def _session_tip(name, stored):
    """Newest session in a stored session's continuation chain (compression rotates the id)."""
    import sqlite3

    c = sqlite3.connect(f'file:{home(name)/"state.db"}?mode=ro', uri=True, timeout=5)
    try:
        chain = [stored]
        frontier = [stored]
        while frontier and len(chain) < 200:
            q = 'SELECT id FROM sessions WHERE parent_session_id IN (%s)' % ','.join('?' * len(frontier))
            frontier = [r[0] for r in c.execute(q, frontier) if r[0] not in chain]
            chain += frontier
        row = c.execute(
            'SELECT id FROM sessions WHERE id IN (%s) ORDER BY started_at DESC LIMIT 1' % ','.join('?' * len(chain)), chain
        ).fetchone()
    finally:
        c.close()
    return row[0] if row else stored


def cron_mirror(name, stored, text):
    check(name, True)
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', stored or '') or not isinstance(text, str) or not text.strip() or len(text) > 60000:
        raise ValueError('bad mirror')
    return hermes_py(name, 'mirror', {'session_id': _session_tip(name, stored), 'text': text})


def cron_sessions(name, jid):
    """Native cron run sessions of one job (id cron_<job>_<stamp>) with their token/cost totals."""
    import sqlite3

    check(name, True)
    if not CRON_ID_RE.match(jid or ''):
        raise ValueError('bad job id')
    c = sqlite3.connect(f'file:{home(name)/"state.db"}?mode=ro', uri=True, timeout=5)
    try:
        ids = [
            r[0]
            for r in c.execute(
                "SELECT id FROM sessions WHERE id LIKE ? ESCAPE '\\' AND parent_session_id IS NULL ORDER BY started_at DESC LIMIT 60",
                ('cron\\_' + jid + '\\_%',),
            )
        ]
    finally:
        c.close()
    return [{'id': i, **usage(name, i)} for i in ids]


def _tool_states(name, platform):
    out = {}
    for line in run(['-p', name, 'tools', 'list', '--platform', platform], 60).splitlines():
        m = re.match(r'\s*[✓✗]\s+(enabled|disabled)\s+(\S+)\s', line)
        if m:
            out[m.group(2)] = m.group(1) == 'enabled'
    return out


def _sync_cron_platform(name):
    """Unattended cron runs use platform_toolsets.cron, which defaults to EVERY toolset. For portal profiles it
    must never be wider than what the admin enabled for the chat (cli) platform."""
    if name == 'default':
        return {}
    cli = _tool_states(name, 'cli')
    cron = _tool_states(name, 'cron')
    enable = [t for t, on in cli.items() if on and t in cron and not cron[t]]
    disable = [t for t, on in cron.items() if on and not cli.get(t)]
    if enable:
        run(['-p', name, 'tools', 'enable', '--platform', 'cron', *enable])
    if disable:
        run(['-p', name, 'tools', 'disable', '--platform', 'cron', *disable])
    return {'enabled': enable, 'disabled': disable}


def cron_tool(name, enabled):
    """The cronjob toolset (agent may schedule jobs) follows the portal permission feature:cron."""
    check(name)
    cli = _tool_states(name, 'cli')
    changed = bool(cli.get('cronjob')) != bool(enabled)
    if changed:
        run(['-p', name, 'tools', 'enable' if enabled else 'disable', 'cronjob'])
    sync = _sync_cron_platform(name)
    return {
        'changed': changed,
        'cron_platform': sync,
        'cli_enabled': (
            sorted(t for t, on in _tool_states(name, 'cli').items() if on) if changed else sorted(t for t, on in cli.items() if on)
        ),
    }


# ---- VPS resources (admin dashboard). Read-only /proc + cgroup v2 reads; rates are deltas since the previous call
# (the backend sampler calls this every 15 s), so the first call after a bridge restart returns no rates.
_VPS_PREV = {}
_DOCKER_NAMES = {'ts': 0, 'map': {}}
CG = Path('/sys/fs/cgroup/system.slice')


def _read(p, default=''):
    try:
        return Path(p).read_text()
    except OSError:
        return default


def _kv(text):
    out = {}
    for line in text.splitlines():
        k, _, v = line.partition(' ')
        try:
            out[k] = int(v.split()[0])
        except (ValueError, IndexError):
            pass
    return out


def _docker_names():
    if time.time() - _DOCKER_NAMES['ts'] > 60:
        try:
            r = subprocess.run(
                ['docker', 'ps', '--no-trunc', '--format', '{{.ID}}\t{{.Names}}\t{{.Label "hermes-profile"}}'],
                capture_output=True,
                text=True,
                timeout=10,
            )
            _DOCKER_NAMES['map'] = {l.split('\t')[0]: l.split('\t')[1:] for l in r.stdout.splitlines() if l.count('\t') == 2}
        except Exception:
            pass
        _DOCKER_NAMES['ts'] = time.time()
    return _DOCKER_NAMES['map']


def _cgroups():
    """(group, name, cgroup dir) for portal-relevant units: owner bridge, profile bridges, portal containers, sandboxes."""
    out = []
    if (CG / 'hermes-web-bridge.service').is_dir():
        out.append(('bridges', 'default', CG / 'hermes-web-bridge.service'))
    for d in sorted((CG / 'system-hermes\\x2dweb\\x2dbridge.slice').glob('hermes-web-bridge@*.service')):
        out.append(('bridges', d.name[len('hermes-web-bridge@') : -len('.service')], d))
    names = _docker_names()
    for d in sorted(CG.glob('docker-*.scope')):
        name, profile = names.get(d.name[7:-6], ['', ''])
        if name.startswith('hermes-web-'):
            out.append(('portal', name[len('hermes-web-') :], d))
        elif name:
            out.append(('sandboxes', profile or name, d))
    for svc, label in (('docker.service', 'dockerd'), ('containerd.service', 'containerd')):
        if (CG / svc).is_dir():
            out.append(('system', label, CG / svc))
    return out


def vps_stats():
    now = time.time()
    prev = _VPS_PREV.get('t')
    dt = (now - prev) if prev else 0
    # CPU: jiffies per state
    f = [int(x) for x in _read('/proc/stat').splitlines()[0].split()[1:]]
    f = (f + [0] * 8)[:8]
    total = sum(f)
    cpu = None
    if 'cpu' in _VPS_PREV:
        pt, pv = _VPS_PREV['cpu']
        d = max(total - pt, 1)
        g = lambda i: (f[i] - pv[i]) / d
        cpu = {
            'total': round(1 - g(3) - g(4), 4),
            'user': round(g(0) + g(1), 4),
            'system': round(g(2) + g(5) + g(6), 4),
            'iowait': round(g(4), 4),
            'steal': round(g(7), 4),
        }
    _VPS_PREV["cpu"] = (total, f)
    mi = _kv(_read('/proc/meminfo').replace(':', ''))
    mt = mi.get('MemTotal', 0) * 1024
    ma = mi.get('MemAvailable', 0) * 1024
    mem = {
        'total': mt,
        'used': mt - ma,
        'available': ma,
        'cached': (mi.get('Cached', 0) + mi.get('Buffers', 0)) * 1024,
        'swap_total': mi.get('SwapTotal', 0) * 1024,
        'swap_used': (mi.get('SwapTotal', 0) - mi.get('SwapFree', 0)) * 1024,
    }
    disks = []
    seen = set()
    for line in _read('/proc/mounts').splitlines():
        dev, mnt, fs = line.split()[:3]
        if (
            not dev.startswith('/dev/')
            or dev in seen
            or fs in ('squashfs', 'iso9660')
            or mnt.startswith(('/snap', '/boot/efi', '/var/lib/docker'))
        ):
            continue
        seen.add(dev)
        try:
            s = os.statvfs(mnt)
        except OSError:
            continue
        t = s.f_blocks * s.f_frsize
        free = s.f_bavail * s.f_frsize
        if t:
            disks.append({'mount': mnt, 'device': dev, 'fs': fs, 'total': t, 'used': t - s.f_bfree * s.f_frsize, 'free': free})
    # network: physical-ish interfaces only (docker bridges/veths double-count the same traffic)
    rx = tx = 0
    for line in _read('/proc/net/dev').splitlines()[2:]:
        name, _, rest = line.partition(':')
        name = name.strip()
        v = rest.split()
        if name == 'lo' or name.startswith(('veth', 'docker', 'br-')) or len(v) < 9:
            continue
        rx += int(v[0])
        tx += int(v[8])
    # disk I/O: whole devices (no partitions), 512-byte sectors
    rd = wr = 0
    for line in _read('/proc/diskstats').splitlines():
        v = line.split()
        if len(v) > 9 and re.match(r'^(vd[a-z]|sd[a-z]|xvd[a-z]|nvme\d+n\d+)$', v[2]):
            rd += int(v[5]) * 512
            wr += int(v[9]) * 512
    rates = None
    if dt and 'io' in _VPS_PREV:
        p = _VPS_PREV['io']
        rates = {k: max(0, round((c - o) / dt)) for k, c, o in zip(('rx', 'tx', 'read', 'write'), (rx, tx, rd, wr), p)}
    _VPS_PREV['io'] = (rx, tx, rd, wr)
    psi = {}
    for k in ('cpu', 'memory', 'io'):
        m = re.search(r'some avg10=([\d.]+)', _read(f'/proc/pressure/{k}'))
        if m:
            psi[k] = float(m.group(1))
    # per-unit memory (working set = current - inactive_file, like `docker stats`) and CPU share since last call
    units = []
    pcpu = _VPS_PREV.get('units', {})
    ncpu = {}
    cores = os.cpu_count() or 1
    for group, name, d in _cgroups():
        cur = int(_read(d / 'memory.current', '0') or 0)
        st = _kv(_read(d / 'memory.stat'))
        us = _kv(_read(d / 'cpu.stat')).get('usage_usec', 0)
        key = str(d)
        ncpu[key] = us
        share = round((us - pcpu[key]) / 1e6 / dt / cores, 4) if dt and key in pcpu and us >= pcpu[key] else None
        units.append({'group': group, 'name': name, 'mem': max(0, cur - st.get('inactive_file', 0)), 'cpu': share})
    _VPS_PREV['units'] = ncpu
    _VPS_PREV['t'] = now
    load = [float(x) for x in _read('/proc/loadavg').split()[:3]]
    procs = sum(1 for p in os.listdir('/proc') if p.isdigit())
    return {
        'ts': now,
        'cores': cores,
        'cpu': cpu,
        'load': load,
        'mem': mem,
        'disks': disks,
        'rates': rates,
        'psi': psi,
        'units': units,
        'uptime': float(_read('/proc/uptime', '0').split()[0]),
        'procs': procs,
        'hostname': os.uname().nodename,
        'kernel': os.uname().release,
    }


OPS = {
    'search': lambda a: (check(a['name'], True), hermes_py(a['name'], 'search', {'q': a['q'], 'limit': a.get('limit', 60)}))[1],
    'vps_stats': lambda a: vps_stats(),
    'cron_list': lambda a: cron_list(a['name']),
    'cron_action': lambda a: cron_action(a['name'], a['job'], a['action']),
    'cron_edit': lambda a: cron_edit(a['name'], a['job'], a.get('fields', {})),
    'cron_gap': lambda a: cron_gap(a['name'], a['schedule']),
    'cron_report': lambda a: cron_report(a['name'], a['job'], a['file']),
    'cron_mirror': lambda a: cron_mirror(a['name'], a['stored'], a['text']),
    'cron_sessions': lambda a: cron_sessions(a['name'], a['job']),
    'cron_tool': lambda a: cron_tool(a['name'], bool(a['enabled'])),
    'profile_document': lambda a: profile_document(a['name'], a['document']),
    'set_profile_document': lambda a: set_profile_document(a['name'], a['document'], a['content'], a['revision']),
    'profile_memory_config': lambda a: profile_memory_config(a['name']),
    'set_profile_memory_config': lambda a: set_profile_memory_config(a['name'], a['changes']),
    'backup_status': lambda a: backup_status(),
    'reasoning': lambda a: reasoning(a['name']),
    'set_reasoning': lambda a: set_reasoning(a['name'], a.get('effort', ''), bool(a.get('allow_default'))),
    'limits': lambda a: account_limits(a['name'], a.get('provider')),
    'list': lambda a: list_profiles(),
    'plugins': lambda a: plugins(a['name']),
    'set_plugin': lambda a: set_plugin(a['name'], a['plugin'], bool(a['enabled'])),
    'oauth_start': lambda a: oauth_start(a['name'], a['provider']),
    'oauth_status': lambda a: oauth_status(a['job']),
    'oauth_cancel': lambda a: oauth_cancel(a['job']),
    'oauth_code': lambda a: oauth_code(a['job'], a.get('code', '')),
    'anthropic_own': lambda a: anthropic_own(a['name'], bool(a['own'])),
    'anthropic_own_status': lambda a: anthropic_own_status(a['name']),
    'isolation': lambda a: isolation(a['name']),
    'set_isolation': lambda a: set_isolation(
        a['name'], bool(a['enabled']), a.get('memory_mb', 2048), a.get('cpus', 1.0), a.get('network', True)
    ),
    'env_keys': lambda a: env_keys(a['name']),
    'cursor': lambda a: cursor_status(a['name']),
    'set_cursor': lambda a: set_cursor_key(a['name'], a['key']),
    'remove_cursor': lambda a: remove_cursor_key(a['name']),
    'library': lambda a: library(),
    'skills': lambda a: skills(a['name']),
    'set_skill': lambda a: set_skill(a['name'], a['skill'], bool(a['enabled'])),
    'set_library': lambda a: set_library(a['name'], bool(a['enabled'])),
    'promote': lambda a: promote(a['name'], a['skill']),
    'library_delete': lambda a: library_delete(a['skill']),
    'delete_personal': lambda a: delete_personal(a['name'], a['skill']),
    'usage': lambda a: usage(a['name'], a['session_id']),
    'session_titles': lambda a: session_titles(a['name'], a.get('ids', [])),
    'owner_providers': lambda a: owner_providers(),
    'create': lambda a: create(
        a['name'], a['provider'], a['model'], a.get('description', ''), a.get('credential_from'), bool(a.get('accept_rotation'))
    ),
    'set_model': lambda a: set_model(a['name'], a['provider'], a['model'], bool(a.get('allow_default'))),
    'tools': lambda a: tools(a['name']),
    'set_tools': lambda a: set_tools(a['name'], a.get('enable', []), a.get('disable', [])),
    'bridge': lambda a: bridge(a['name'], a['action']),
    'copy_credential': lambda a: copy_credential(a['name'], a['provider'], bool(a.get('accept_rotation'))),
    'remove_credential': lambda a: remove_credential(a['name'], a['provider']),
    'delete': lambda a: delete(a['name'], a.get('confirm', '')),
}
