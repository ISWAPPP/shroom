import base64, io, json, os, re, sqlite3, threading, time, uuid, hashlib
from pathlib import Path
import httpx
from PIL import Image, UnidentifiedImageError
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form, Depends, Query, Path as FPath
from fastapi.responses import JSONResponse
import secrets, sys
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from pydantic import BaseModel, Field, StrictBool, StrictInt

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
DATA = Path('/data')
DATA.mkdir(exist_ok=True)
TOKEN = Path('/run/secrets/bridge_key').read_text().strip()
BRIDGE = 'http://127.0.0.1:9121'
LOCK = threading.Lock()
BUSY = set()
LIVE_LOCK = threading.RLock()


def db():
    c = sqlite3.connect(DATA / 'portal.db', timeout=10)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


with db() as c:
    c.execute('PRAGMA journal_mode=WAL')
    c.execute(
        'CREATE TABLE IF NOT EXISTS dialogs(id TEXT PRIMARY KEY, live TEXT NOT NULL, stored TEXT NOT NULL, title TEXT NOT NULL, created REAL NOT NULL)'
    )
    c.execute(
        'CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY, dialog TEXT NOT NULL REFERENCES dialogs(id), fingerprint TEXT NOT NULL, epoch TEXT NOT NULL, cursor INTEGER NOT NULL, state TEXT NOT NULL, created REAL NOT NULL)'
    )
    c.execute(
        'CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY, dialog TEXT NOT NULL REFERENCES dialogs(id), name TEXT NOT NULL, mime TEXT NOT NULL, path TEXT NOT NULL, size INTEGER NOT NULL)'
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, pw TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')), profile TEXT NOT NULL, blocked INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL)"
    )
    c.execute(
        'CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, csrf TEXT NOT NULL, expires REAL NOT NULL, created REAL NOT NULL)'
    )
    cols = [r[1] for r in c.execute('PRAGMA table_info(dialogs)')]
    if 'owner' not in cols:
        c.execute('ALTER TABLE dialogs ADD COLUMN owner TEXT')
    if 'profile' not in cols:
        c.execute("ALTER TABLE dialogs ADD COLUMN profile TEXT NOT NULL DEFAULT 'default'")
    if 'unread' not in cols:
        c.execute('ALTER TABLE dialogs ADD COLUMN unread INTEGER NOT NULL DEFAULT 0')
    for col in ('chat_provider', 'chat_model', 'chat_effort'):  # per-chat model / reasoning pick; NULL = profile default
        if col not in cols:
            c.execute(f'ALTER TABLE dialogs ADD COLUMN {col} TEXT')  # scheduled-job reports not yet seen
    if 'pinned' not in cols:
        c.execute('ALTER TABLE dialogs ADD COLUMN pinned REAL')  # pin time; NULL = not pinned
    if 'seen_turn' not in cols:  # latest turn whose result the owner has looked at (sidebar "finished, not seen" mark)
        c.execute('ALTER TABLE dialogs ADD COLUMN seen_turn TEXT')
        c.execute('UPDATE dialogs SET seen_turn=(SELECT t.id FROM turns t WHERE t.dialog=dialogs.id ORDER BY t.created DESC LIMIT 1)')
    # Native Hermes cron jobs the portal knows about: chat the reports go to, newest run already delivered, policy note.
    c.execute(
        'CREATE TABLE IF NOT EXISTS cron_jobs(profile TEXT NOT NULL, job TEXT NOT NULL, dialog TEXT, seen TEXT NOT NULL DEFAULT \'\', note TEXT, created REAL NOT NULL, PRIMARY KEY(profile,job))'
    )
    scols = [r[1] for r in c.execute('PRAGMA table_info(sessions)')]
    if 'impersonator' not in scols:
        c.execute('ALTER TABLE sessions ADD COLUMN impersonator TEXT REFERENCES users(id) ON DELETE CASCADE')
    if 'title_source' not in cols:
        # auto: no title yet | derived/llm: mirrored from Hermes' native titler | user: named by the user |
        # generated: portal asked the profile's title provider. Old clients sent a dated placeholder as the title.
        c.execute("ALTER TABLE dialogs ADD COLUMN title_source TEXT NOT NULL DEFAULT 'auto'")
        for did, title in c.execute('SELECT id,title FROM dialogs').fetchall():
            if re.match(r'^(Новий діалог|Діалог \d{1,2}\.\d{1,2}\.\d{4},? \d{1,2}:\d{2}(:\d{2})?)$', title or ''):
                c.execute("UPDATE dialogs SET title='Новий діалог' WHERE id=?", (did,))
            else:
                c.execute("UPDATE dialogs SET title_source='user' WHERE id=?", (did,))

# ---------------- authentication ----------------
PH = PasswordHasher()  # argon2id defaults
COOKIE = 'hp_session'
SESSION_TTL = 12 * 3600  # sliding: any authenticated request (polls of an open tab too) pushes the expiry forward
SESSION_MAX = 7 * 24 * 3600  # absolute cap from login, so an open tab keeps the session for at most a week
PROFILE_RE = re.compile(r'^[a-z0-9][a-z0-9_-]{0,31}$')
USER_RE = re.compile(r'^[A-Za-z0-9._-]{3,40}$')
FAILS = {}
FAIL_LOCK = threading.Lock()


def _h(token):
    return hashlib.sha256(token.encode()).hexdigest()


def socket_for(profile):
    if not PROFILE_RE.match(profile):
        raise HTTPException(500, 'Invalid profile binding')
    return '/run/bridge/bridge.sock' if profile == 'default' else f'/run/bridge/bridge-{profile}.sock'


def available_profiles():
    out = []
    import socket as _s

    for f in sorted(Path('/run/bridge').glob('bridge*.sock')):
        # a deleted/stopped profile leaves its socket file behind; only list bridges that accept connections
        try:
            with _s.socket(_s.AF_UNIX) as k:
                k.settimeout(0.3)
                k.connect(str(f))
        except OSError:
            continue
        out.append('default' if f.name == 'bridge.sock' else f.name[len('bridge-') : -len('.sock')])
    return out


# Failed-login budgets per 15 min. A shared IP (NAT, office) must not lock everyone out after a few typos,
# so the pair (ip, user) is strict, the user and the IP alone are looser; a successful login clears its keys.
THROTTLE = {'pair': 5, 'u': 10, 'ip': 30, 'pw': 5}


def throttle_check(key):
    now = time.time()
    limit = THROTTLE.get(key.split(':', 1)[0], 5)
    with FAIL_LOCK:
        recent = [t for t in FAILS.get(key, []) if now - t < 900]
        FAILS[key] = recent
        if len(recent) >= limit:
            raise HTTPException(429, 'Too many failed attempts; try again later')


def throttle_clear(*keys):
    with FAIL_LOCK:
        for k in keys:
            FAILS.pop(k, None)


def throttle_fail(key):
    with FAIL_LOCK:
        FAILS.setdefault(key, []).append(time.time())


def new_password():
    return secrets.token_urlsafe(15)


def create_user(username, role, profile, password=None):
    if not USER_RE.match(username):
        raise HTTPException(400, 'Username: 3-40 chars A-Z a-z 0-9 . _ -')
    if role not in ('admin', 'user'):
        raise HTTPException(400, 'Bad role')
    if not PROFILE_RE.match(profile):
        raise HTTPException(400, 'Bad profile')
    if role != 'admin' and profile == 'default':
        raise HTTPException(400, 'Main profile is reserved for admins')
    password = password or new_password()
    uid = uuid.uuid4().hex
    try:
        with db() as c:
            c.execute(
                'INSERT INTO users(id,username,pw,role,profile,blocked,created) VALUES(?,?,?,?,?,0,?)',
                (uid, username, PH.hash(password), role, profile, time.time()),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'Username already exists')
    return uid, password


IMPERSONATION_DENIED = {'/api/auth/password', '/api/auth/totp/setup', '/api/auth/totp/enable', '/api/auth/totp/disable'}
ENROLL_PATHS = {'/api/auth/me', '/api/auth/logout', '/api/auth/totp/setup', '/api/auth/totp/enable', '/api/auth/password', '/api/health'}


def current_user(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, 'Login required')
    with db() as c:
        row = c.execute(
            'SELECT s.csrf,s.expires,s.created AS s_created,s.impersonator,i.username AS impersonator_name,i.role AS impersonator_role,i.blocked AS impersonator_blocked,u.* FROM sessions s JOIN users u ON u.id=s.user LEFT JOIN users i ON i.id=s.impersonator WHERE s.token=?',
            (_h(token),),
        ).fetchone()
        if (
            not row
            or row['expires'] < time.time()
            or row['blocked']
            or (row['impersonator'] and (row['impersonator_role'] != 'admin' or row['impersonator_blocked']))
        ):
            c.execute('DELETE FROM sessions WHERE token=?', (_h(token),))
            raise HTTPException(401, 'Login required')
        # Sliding expiry (written at most every 5 minutes): an open tab must not get logged out while the agent sleeps.
        ttl, cap = (IMPERSONATION_TTL, IMPERSONATION_MAX) if row['impersonator'] else (SESSION_TTL, SESSION_MAX)
        new_exp = min(time.time() + ttl, row['s_created'] + cap)
        if new_exp - row['expires'] > 300:
            c.execute('UPDATE sessions SET expires=? WHERE token=?', (new_exp, _h(token)))
    user = dict(row)
    if request.method != 'GET' or (request.url.path == '/api/me/bridge' and request.query_params.get('wake') == '1'):
        WAKE_TICKET[user['profile']] = LAST_ACT[user['profile']] = time.time()
    if user['impersonator']:
        CTX_IMP.set(user['impersonator_name'])
        if request.url.path in IMPERSONATION_DENIED:
            raise HTTPException(403, 'Недоступно під час входу від імені користувача')
    user['must_enroll'] = user['role'] == 'admin' and not user.get('totp_secret') and setting('require_admin_totp') == '1'
    if user['must_enroll'] and request.url.path not in ENROLL_PATHS:
        raise HTTPException(403, 'Two-factor authentication must be set up first')
    if request.method not in ('GET', 'HEAD') and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), user['csrf']):
        raise HTTPException(403, 'CSRF token missing or invalid')
    return user


def admin_user(user=Depends(current_user)):
    if user['role'] != 'admin':
        raise HTTPException(403, 'Admin only')
    return user


def public(u):
    return {
        **{k: u.get(k) for k in ('id', 'username', 'role', 'profile', 'blocked', 'created', 'last_login')},
        'totp': bool(u.get('totp_secret')),
    }


# ---------------- audit log ----------------
import contextvars

CTX_IP = contextvars.ContextVar('ip', default='?')
CTX_IMP = contextvars.ContextVar('impersonator', default=None)  # admin acting as this user, if any
with db() as c:
    c.execute(
        'CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT, actor_name TEXT, ip TEXT, action TEXT NOT NULL, target TEXT, details TEXT)'
    )
    c.execute('CREATE INDEX IF NOT EXISTS audit_ts ON audit(ts)')
    cols = [r[1] for r in c.execute('PRAGMA table_info(users)')]
    if 'last_login' not in cols:
        c.execute('ALTER TABLE users ADD COLUMN last_login REAL')


def audit(actor, action, target='', details=None):
    with db() as c:
        c.execute(
            'INSERT INTO audit(ts,actor,actor_name,ip,action,target,details) VALUES(?,?,?,?,?,?,?)',
            (
                time.time(),
                actor['id'] if actor else None,
                (actor['username'] + (f" (від імені; {CTX_IMP.get()})" if CTX_IMP.get() else '')) if actor else None,
                CTX_IP.get(),
                action,
                target,
                json.dumps(details, ensure_ascii=False) if details is not None else None,
            ),
        )


# ---------------- TOTP (RFC 6238, SHA1, 6 digits, 30 s) ----------------
import hmac, struct, base64 as _b64

with db() as c:
    cols = [r[1] for r in c.execute('PRAGMA table_info(users)')]
    if 'totp_secret' not in cols:
        c.execute('ALTER TABLE users ADD COLUMN totp_secret TEXT')
    if 'totp_pending' not in cols:
        c.execute('ALTER TABLE users ADD COLUMN totp_pending TEXT')
    if 'totp_last' not in cols:
        c.execute('ALTER TABLE users ADD COLUMN totp_last INTEGER')
    c.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)')


def totp_at(secret, step):
    key = _b64.b32decode(secret + '=' * (-len(secret) % 8))
    h = hmac.new(key, struct.pack('>Q', step), 'sha1').digest()
    o = h[-1] & 15
    return '%06d' % ((struct.unpack('>I', h[o : o + 4])[0] & 0x7FFFFFFF) % 1000000)


def totp_verify(secret, code, last=None):
    code = (code or '').strip().replace(' ', '')
    if not re.fullmatch(r'\d{6}', code):
        return None
    now = int(time.time() // 30)
    for st in (now - 1, now, now + 1):
        if (last is None or st > last) and hmac.compare_digest(totp_at(secret, st), code):
            return st
    return None


def setting(key, default=None):
    with db() as c:
        r = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return r['value'] if r else default


def uname(uid):
    with db() as c:
        r = c.execute('SELECT username FROM users WHERE id=?', (uid,)).fetchone()
    return r['username'] if r else uid


# Allowed Origin for state-changing requests (set PORTAL_ORIGIN or PORTAL_HOST in .env).
PORTAL_ORIGIN = (os.environ.get('PORTAL_ORIGIN') or 'https://' + os.environ.get('PORTAL_HOST', 'localhost')).rstrip('/')


@app.middleware('http')
async def same_origin(request: Request, call_next):
    CTX_IP.set(request.headers.get('x-real-ip') or (request.client.host if request.client else '?'))
    CTX_IMP.set(None)
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD') and origin and origin != PORTAL_ORIGIN:
        from fastapi.responses import JSONResponse

        return JSONResponse({'detail': 'Cross-origin request denied'}, status_code=403)
    return await call_next(request)


# ---- idle sleep of user bridges (1 h; the admin bridge `default` never sleeps) ----
# A user bridge with no user action and no turn for BRIDGE_IDLE seconds is stopped (host op bridge/sleep: stop without
# disabling the unit). Polls and background jobs never wake it (they get 503 {asleep}); a user action does: any non-GET
# request, GET /api/me/bridge?wake=1 (the "starting" window after login / on return) — the request then waits for it.
BRIDGE_IDLE = 3600
BOOT = time.time()
LAST_ACT = {}
WAKE_LOCK = threading.Lock()
WAKING = {}
WAKE_TICKET = {}  # profile -> time of the last user action (a wake is allowed for a minute after it)


def asleep(P):
    return P != 'default' and setting('asleep:' + P) == '1'


def _set_asleep(P, on):
    with db() as c:
        if on:
            c.execute("INSERT INTO settings(key,value) VALUES(?,'1') ON CONFLICT(key) DO UPDATE SET value='1'", ('asleep:' + P,))
        else:
            c.execute('DELETE FROM settings WHERE key=?', ('asleep:' + P,))


def _sock_up(P, timeout=0.3):
    import socket as _s

    try:
        with _s.socket(_s.AF_UNIX) as k:
            k.settimeout(timeout)
            k.connect(socket_for(P))
            return True
    except OSError:
        return False


def wake_bridge(P, wait=45.0):
    """Start a sleeping bridge (once, even with parallel callers) and wait until Hermes answers."""
    with WAKE_LOCK:
        started = WAKING.get(P)
        if not started or time.time() - started > 120:
            WAKING[P] = time.time()
            r = _host_admin('bridge', {'name': P, 'action': 'wake'})
            if not r.get('woken'):  # the admin stopped it on purpose: stay down
                WAKING.pop(P, None)
                _set_asleep(P, False)
                raise HTTPException(502, 'Hermes bridge unavailable')
            audit(None, 'profile.wake', P)
    end = time.time() + wait
    while time.time() < end:
        if _sock_up(P):
            try:
                v = _bridge_raw(P, '/rpc', {'method': 'model.options', 'params': {}})
                if 'result' in v:
                    _set_asleep(P, False)
                    WAKING.pop(P, None)
                    LAST_ACT[P] = time.time()
                    return True
            except Exception:
                pass
        time.sleep(0.7)
    return False


def bridge_state_for(P):
    if P == 'default' or not asleep(P):
        return 'ready' if _sock_up(P) else 'unavailable'
    if _sock_up(P):
        _set_asleep(P, False)
        return 'ready'  # started by the admin or a host reboot
    return 'starting' if P in WAKING else 'asleep'


def bridge_sleeper():
    while True:
        time.sleep(300)
        try:
            with db() as c:
                users = [dict(r) for r in c.execute("SELECT profile,role FROM users WHERE blocked=0")]
                busy = {
                    r[0]
                    for r in c.execute(
                        "SELECT DISTINCT d.profile FROM turns t JOIN dialogs d ON d.id=t.dialog WHERE t.state IN ('running','waiting') AND t.created>?",
                        (time.time() - 3 * 3600,),
                    )
                }
                last = {
                    r[0]: r[1]
                    for r in c.execute('SELECT d.profile,MAX(t.created) FROM turns t JOIN dialogs d ON d.id=t.dialog GROUP BY d.profile')
                }
            admins = {u['profile'] for u in users if u['role'] == 'admin'}
            for P in sorted({u['profile'] for u in users} - admins - {'default'}):
                if P in busy or P in BUSY or P in WAKING or asleep(P) or not _sock_up(P):
                    continue
                idle = time.time() - max(LAST_ACT.get(P, BOOT), last.get(P) or 0)
                if idle < BRIDGE_IDLE:
                    continue
                try:
                    _host_admin('bridge', {'name': P, 'action': 'sleep'})
                    _set_asleep(P, True)
                    audit(None, 'profile.sleep', P, {'idle_min': int(idle // 60)})
                except Exception:
                    pass
        except Exception:
            pass


threading.Thread(target=bridge_sleeper, daemon=True).start()


def bridge(profile, path, payload):
    if profile != 'default' and asleep(profile):
        if _sock_up(profile):
            _set_asleep(profile, False)
        elif time.time() - WAKE_TICKET.get(profile, 0) < 60:
            if not wake_bridge(profile):
                raise HTTPException(
                    503, {'asleep': True, 'starting': True, 'message': 'Агент ще запускається, спробуйте за кілька секунд.'}
                )
        else:
            raise HTTPException(
                503, {'asleep': True, 'message': 'Агент заснув після години без дій. Він прокинеться, щойно ви щось надішлете.'}
            )
    return _bridge_raw(profile, path, payload)


def _bridge_raw(profile, path, payload):
    try:
        with httpx.Client(transport=httpx.HTTPTransport(uds=socket_for(profile)), timeout=190) as client:
            r = client.post('http://hermes-bridge' + path, json=payload, headers={'Authorization': 'Bearer ' + TOKEN})
            if r.status_code == 409:
                raise HTTPException(409, r.json().get('error', 'Request no longer open'))
            r.raise_for_status()
            return r.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, 'Hermes bridge unavailable') from exc


def rpc(profile, method, params):
    v = bridge(profile, '/rpc', {'method': method, 'params': params})
    if 'error' in v:
        raise HTTPException(502, {'hermes': v['error']})
    return v['result']


def dialog(did, user):
    with db() as c:
        row = c.execute('SELECT * FROM dialogs WHERE id=? AND owner=? AND profile=?', (did, user['id'], user['profile'])).fetchone()
    if row is None:
        raise HTTPException(404, 'Dialog not found')
    return dict(row)


def live(did, user):
    with LIVE_LOCK:
        return _live(did, user)


# ---- idle Hermes sessions ----
# Every opened chat keeps a live agent session in its bridge until closed; nothing closed them, so a long-running bridge
# (the admin `default` profile especially) accumulated memory. Chats nobody has polled for SESSION_IDLE and with no running turn
# get `session.close`; the next open resumes them from disk (`_live` below, code 4001 -> session.resume).
SESSION_IDLE = 2 * 3600
DIALOG_SEEN = {}


def session_reaper():
    while True:
        time.sleep(600)
        try:
            cutoff = time.time() - SESSION_IDLE
            with db() as c:
                rows = [
                    dict(r)
                    for r in c.execute(
                        "SELECT d.id,d.profile,d.live,(SELECT MAX(created) FROM turns t WHERE t.dialog=d.id) AS last FROM dialogs d "
                        "WHERE d.live IS NOT NULL AND d.live<>'' AND NOT EXISTS(SELECT 1 FROM turns t WHERE t.dialog=d.id AND t.state IN ('running','waiting') AND t.created>?)",
                        (time.time() - 3 * 3600,),
                    )
                ]
            up = set(available_profiles())
            closed = 0
            for r in rows:
                if r['profile'] not in up or r['profile'] in BUSY or max(r['last'] or 0, DIALOG_SEEN.get(r['id'], 0)) > cutoff:
                    continue
                try:
                    v = _bridge_raw(r['profile'], '/rpc', {'method': 'session.close', 'params': {'session_id': r['live']}})
                except Exception:
                    continue
                with db() as c:  # '' = closed by the reaper; _live resumes it on the next open
                    c.execute("UPDATE dialogs SET live='' WHERE id=? AND live=?", (r['id'], r['live']))
                closed += bool((v.get('result') or {}).get('closed'))
            if closed:
                audit(None, 'session.reap', '', {'closed': closed})
        except Exception:
            pass


threading.Thread(target=session_reaper, daemon=True).start()


def _live(did, user):
    row = dialog(did, user)
    P = row['profile']
    DIALOG_SEEN[did] = time.time()
    try:
        if not row['live']:
            raise HTTPException(502, {'hermes': {'code': 4001, 'message': 'closed while idle'}})
        rpc(P, 'session.status', {'session_id': row['live']})
    except HTTPException as exc:
        if not isinstance(exc.detail, dict) or exc.detail.get('hermes', {}).get('code') != 4001:
            raise
        resumed = rpc(P, 'session.resume', {'session_id': row['stored']})
        row['live'] = resumed['session_id']
        with db() as c:
            c.execute('UPDATE dialogs SET live=? WHERE id=?', (row['live'], did))
        try:
            apply_chat_runtime(P, row['live'], row.get('chat_provider'), row.get('chat_model'), row.get('chat_effort'))
        except HTTPException:
            pass
    return row['live']


@app.get('/api/health')
def health():
    return {'status': 'ok', 'mode': 'multi-user-preview', 'authentication': True, 'integration': 'Hermes TUI JSON-RPC stdio'}


# ---------------- auth routes ----------------
class Login(BaseModel):
    username: str = Field(max_length=40)
    password: str = Field(max_length=200)
    code: str = Field(default='', max_length=10)


@app.post('/api/auth/login')
def login(body: Login, request: Request, response: Response):
    ip = request.headers.get('x-real-ip') or (request.client.host if request.client else '?')
    uk = body.username.lower()
    throttle_check('pair:' + ip + '|' + uk)
    throttle_check('u:' + uk)
    throttle_check('ip:' + ip)
    with db() as c:
        row = c.execute('SELECT * FROM users WHERE username=?', (body.username,)).fetchone()
    ok = False
    try:
        ok = bool(row) and PH.verify(row['pw'], body.password)
    except (VerifyMismatchError, InvalidHashError):
        ok = False
    if not row:
        PH.hash('timing-equaliser')
    if not ok or row['blocked']:
        for k in ('pair:' + ip + '|' + uk, 'u:' + uk, 'ip:' + ip):
            throttle_fail(k)
        audit(dict(row) if row else None, 'auth.login_failed', body.username[:40], {'blocked': bool(row and row['blocked'])})
        raise HTTPException(401, 'Invalid credentials')
    if row['totp_secret']:
        if not body.code:
            raise HTTPException(401, {'totp_required': True, 'message': 'Enter the 6-digit code from your authenticator'})
        st = totp_verify(row['totp_secret'], body.code, row['totp_last'])
        if st is None:
            for k in ('pair:' + ip + '|' + uk, 'u:' + uk, 'ip:' + ip):
                throttle_fail(k)
            audit(dict(row), 'auth.totp_failed', row['username'])
            raise HTTPException(401, {'totp_required': True, 'message': 'Invalid code'})
        with db() as c:
            c.execute('UPDATE users SET totp_last=? WHERE id=?', (st, row['id']))
    if PH.check_needs_rehash(row['pw']):
        with db() as c:
            c.execute('UPDATE users SET pw=? WHERE id=?', (PH.hash(body.password), row['id']))
    throttle_clear('pair:' + ip + '|' + uk, 'u:' + uk)
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    with db() as c:
        c.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
        c.execute(
            'INSERT INTO sessions(token,user,csrf,expires,created) VALUES(?,?,?,?,?)',
            (_h(token), row['id'], csrf, time.time() + SESSION_TTL, time.time()),
        )
        c.execute('UPDATE users SET last_login=? WHERE id=?', (time.time(), row['id']))
    audit(dict(row), 'auth.login', row['username'])
    response.set_cookie(COOKIE, token, max_age=SESSION_MAX, httponly=True, secure=True, samesite='strict', path='/api')
    return {'user': public(dict(row)), 'csrf': csrf}


@app.get('/api/auth/me')
def me(user=Depends(current_user)):
    return {
        'user': {**public(user), 'must_enroll': user['must_enroll'], 'impersonated_by': user.get('impersonator_name')},
        'csrf': user['csrf'],
    }


@app.post('/api/auth/logout')
def logout(request: Request, response: Response, user=Depends(current_user)):
    with db() as c:
        c.execute('DELETE FROM sessions WHERE token=?', (_h(request.cookies.get(COOKIE, '')),))
        if user.get('impersonator'):  # logging out while acting as a user ends the admin's parked session too
            c.execute('DELETE FROM sessions WHERE token=? AND user=?', (_h(request.cookies.get(ADMIN_COOKIE, '')), user['impersonator']))
    audit(user, 'auth.logout', user['username'])
    response.delete_cookie(ADMIN_COOKIE, path='/api')
    response.delete_cookie(COOKIE, path='/api')
    return {'ok': True}


# ---- admin "log in as" a user: a separate short session marked with the admin; the admin's own session is kept
# aside in an HttpOnly cookie and restored on return. Password/2FA changes are refused while impersonating, every
# action is audited as "<user> (від імені; <admin>)". Admins cannot be impersonated.
ADMIN_COOKIE = 'hp_admin_session'
IMPERSONATION_TTL = 3600  # sliding, like SESSION_TTL
IMPERSONATION_MAX = 12 * 3600


@app.post('/api/admin/users/{uid}/impersonate')
def impersonate(uid: str, request: Request, response: Response, admin=Depends(admin_user)):
    if admin.get('impersonator'):
        raise HTTPException(400, 'Спершу поверніться до свого облікового запису')
    with db() as c:
        target = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not target:
        raise HTTPException(404, 'User not found')
    if target['role'] == 'admin':
        raise HTTPException(403, 'Не можна увійти від імені іншого адміністратора')
    if target['blocked']:
        raise HTTPException(400, 'Користувача заблоковано')
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    with db() as c:
        c.execute(
            'INSERT INTO sessions(token,user,csrf,expires,created,impersonator) VALUES(?,?,?,?,?,?)',
            (_h(token), uid, csrf, time.time() + IMPERSONATION_TTL, time.time(), admin['id']),
        )
        # The parked admin session is not polled meanwhile: keep it valid for the longest impersonation.
        c.execute(
            'UPDATE sessions SET expires=MAX(expires,MIN(created+?,?)) WHERE token=?',
            (SESSION_MAX, time.time() + IMPERSONATION_MAX, _h(request.cookies.get(COOKIE, ''))),
        )
    audit(admin, 'auth.impersonate_start', target['username'])
    response.set_cookie(
        ADMIN_COOKIE, request.cookies.get(COOKIE, ''), max_age=SESSION_MAX, httponly=True, secure=True, samesite='strict', path='/api'
    )
    response.set_cookie(COOKIE, token, max_age=IMPERSONATION_MAX, httponly=True, secure=True, samesite='strict', path='/api')
    return {'user': {**public(dict(target)), 'impersonated_by': admin['username']}, 'csrf': csrf}


@app.post('/api/auth/impersonate/stop')
def impersonate_stop(request: Request, response: Response, user=Depends(current_user)):
    if not user.get('impersonator'):
        raise HTTPException(400, 'Not impersonating')
    with db() as c:
        c.execute('DELETE FROM sessions WHERE token=?', (_h(request.cookies.get(COOKIE, '')),))
        back = request.cookies.get(ADMIN_COOKIE, '')
        row = (
            c.execute(
                'SELECT s.expires,s.created FROM sessions s JOIN users u ON u.id=s.user WHERE s.token=? AND u.id=? AND s.impersonator IS NULL',
                (_h(back), user['impersonator']),
            ).fetchone()
            if back
            else None
        )
    with db() as c:
        admin = c.execute('SELECT * FROM users WHERE id=?', (user['impersonator'],)).fetchone()
    CTX_IMP.set(None)
    audit(dict(admin) if admin else None, 'auth.impersonate_stop', user['username'])
    response.delete_cookie(ADMIN_COOKIE, path='/api')
    if row and row['expires'] > time.time():
        response.set_cookie(
            COOKIE,
            back,
            max_age=int(row['created'] + SESSION_MAX - time.time()),
            httponly=True,
            secure=True,
            samesite='strict',
            path='/api',
        )
        return {'restored': True}
    response.delete_cookie(COOKIE, path='/api')
    return {'restored': False}


class PasswordChange(BaseModel):
    old: str = Field(max_length=200)
    new: str = Field(min_length=12, max_length=200)


@app.post('/api/auth/password')
def change_password(body: PasswordChange, request: Request, user=Depends(current_user)):
    throttle_check('pw:' + user['id'])
    try:
        PH.verify(user['pw'], body.old)
    except (VerifyMismatchError, InvalidHashError):
        throttle_fail('pw:' + user['id'])
        raise HTTPException(403, 'Old password is wrong')
    with db() as c:
        c.execute('UPDATE users SET pw=? WHERE id=?', (PH.hash(body.new), user['id']))
        c.execute('DELETE FROM sessions WHERE user=? AND token<>?', (user['id'], _h(request.cookies.get(COOKIE, ''))))
    audit(user, 'auth.password_change', user['username'])
    return {'ok': True}


@app.post('/api/auth/totp/setup')
def totp_setup(user=Depends(current_user)):
    secret = _b64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')
    with db() as c:
        c.execute('UPDATE users SET totp_pending=? WHERE id=?', (secret, user['id']))
    issuer = 'Hermes portal'
    return {
        'secret': secret,
        'uri': f"otpauth://totp/{issuer.replace(' ','%20')}:{user['username']}?secret={secret}&issuer={issuer.replace(' ','%20')}&digits=6&period=30",
    }


class TotpCode(BaseModel):
    code: str = Field(max_length=10)
    password: str = Field(default='', max_length=200)


@app.post('/api/auth/totp/enable')
def totp_enable(body: TotpCode, user=Depends(current_user)):
    if not user['totp_pending']:
        raise HTTPException(400, 'Start setup first')
    st = totp_verify(user['totp_pending'], body.code)
    if st is None:
        raise HTTPException(400, 'Invalid code')
    with db() as c:
        c.execute('UPDATE users SET totp_secret=totp_pending,totp_pending=NULL,totp_last=? WHERE id=?', (st, user['id']))
    audit(user, 'auth.totp_enabled', user['username'])
    return {'totp': True}


@app.post('/api/auth/totp/disable')
def totp_disable(body: TotpCode, user=Depends(current_user)):
    if not user['totp_secret']:
        return {'totp': False}
    if user['role'] == 'admin' and setting('require_admin_totp') == '1':
        raise HTTPException(403, 'Two-factor authentication is required for administrators')
    try:
        PH.verify(user['pw'], body.password)
    except (VerifyMismatchError, InvalidHashError):
        raise HTTPException(403, 'Wrong password')
    if totp_verify(user['totp_secret'], body.code, user['totp_last']) is None:
        raise HTTPException(400, 'Invalid code')
    with db() as c:
        c.execute('UPDATE users SET totp_secret=NULL,totp_last=NULL WHERE id=?', (user['id'],))
    audit(user, 'auth.totp_disabled', user['username'])
    return {'totp': False}


# ---------------- admin routes ----------------
@app.get('/api/admin/policy')
def get_policy(admin=Depends(admin_user)):
    return {'require_admin_totp': setting('require_admin_totp') == '1'}


class Policy(BaseModel):
    require_admin_totp: bool


@app.put('/api/admin/policy')
def put_policy(body: Policy, admin=Depends(admin_user)):
    if body.require_admin_totp and not admin.get('totp_secret'):
        raise HTTPException(400, 'Enable two-factor authentication for your own account first')
    with db() as c:
        c.execute(
            "INSERT INTO settings VALUES('require_admin_totp',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ('1' if body.require_admin_totp else '0',),
        )
    audit(admin, 'policy.update', 'require_admin_totp', {'value': body.require_admin_totp})
    return get_policy(admin)


@app.post('/api/admin/users/{uid}/totp/reset')
def admin_totp_reset(uid: str, admin=Depends(admin_user)):
    with db() as c:
        if not c.execute('UPDATE users SET totp_secret=NULL,totp_pending=NULL,totp_last=NULL WHERE id=?', (uid,)).rowcount:
            raise HTTPException(404, 'No such user')
        c.execute('DELETE FROM sessions WHERE user=?', (uid,))
    audit(admin, 'user.totp_reset', uname(uid))
    return {'totp': False}


@app.get('/api/admin/users')
def admin_users(admin=Depends(admin_user)):
    with db() as c:
        return [public(dict(r)) for r in c.execute('SELECT * FROM users ORDER BY created')]


@app.get('/api/admin/profiles')
def admin_profiles(admin=Depends(admin_user)):
    return available_profiles()


class NewUser(BaseModel):
    username: str
    role: str = 'user'
    profile: str


@app.post('/api/admin/users')
def admin_create(body: NewUser, admin=Depends(admin_user)):
    if body.profile not in available_profiles():
        raise HTTPException(400, 'Profile has no running bridge')
    uid, pw = create_user(body.username, body.role, body.profile)
    audit(admin, 'user.create', body.username, {'role': body.role, 'profile': body.profile})
    return {'id': uid, 'username': body.username, 'password': pw}


class UserPatch(BaseModel):
    model_config = {'extra': 'forbid'}
    blocked: bool | None = None
    profile: str | None = None
    role: str | None = None


@app.patch('/api/admin/users/{uid}')
def admin_patch(uid: str, body: UserPatch, admin=Depends(admin_user)):
    with db() as c:
        row = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not row:
        raise HTTPException(404, 'No such user')
    u = dict(row)
    if uid == admin['id'] and (body.blocked or (body.role and body.role != 'admin')):
        raise HTTPException(400, 'You cannot block or demote yourself')
    if body.profile is not None:
        if body.profile not in available_profiles():
            raise HTTPException(400, 'Profile has no running bridge')
        u['profile'] = body.profile
    if body.role is not None:
        if body.role not in ('admin', 'user'):
            raise HTTPException(400, 'Bad role')
        u['role'] = body.role
    if u['role'] != 'admin' and u['profile'] == 'default':
        raise HTTPException(400, 'Main profile is reserved for admins')
    if body.blocked is not None:
        u['blocked'] = int(body.blocked)
    with db() as c:
        c.execute('UPDATE users SET profile=?,role=?,blocked=? WHERE id=?', (u['profile'], u['role'], u['blocked'], uid))
        if u['blocked'] or body.role is not None or body.profile is not None:
            c.execute('DELETE FROM sessions WHERE user=?', (uid,))
    audit(admin, 'user.update', u['username'], {k: v for k, v in body.model_dump().items() if v is not None})
    return public(u)


@app.post('/api/admin/users/{uid}/password')
def admin_reset(uid: str, admin=Depends(admin_user)):
    pw = new_password()
    with db() as c:
        if not c.execute('UPDATE users SET pw=? WHERE id=?', (PH.hash(pw), uid)).rowcount:
            raise HTTPException(404, 'No such user')
        c.execute('DELETE FROM sessions WHERE user=?', (uid,))
    audit(admin, 'user.password_reset', uname(uid))
    return {'password': pw}


@app.delete('/api/admin/users/{uid}')
def admin_delete_user(uid: str, purge_history: bool = True, admin=Depends(admin_user)):
    if uid == admin['id']:
        raise HTTPException(400, 'You cannot delete yourself')
    with db() as c:
        u = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
        if not u:
            raise HTTPException(404, 'No such user')
        dialogs = [dict(r) for r in c.execute('SELECT * FROM dialogs WHERE owner=?', (uid,))]
        running = c.execute(
            "SELECT COUNT(*) FROM turns t JOIN dialogs d ON d.id=t.dialog WHERE d.owner=? AND t.state IN ('running','waiting') AND t.created>?",
            (uid, time.time() - 900),
        ).fetchone()[0]
    if running:
        raise HTTPException(409, 'User has an active response; stop it first')
    purged = 0
    kept = 0
    for d in dialogs:
        if purge_history and d['profile'] in available_profiles():
            try:
                bridge(d['profile'], '/rpc', {'method': 'session.close', 'params': {'session_id': d['live']}})
                v = bridge(d['profile'], '/rpc', {'method': 'session.delete', 'params': {'session_id': d['stored']}})
                purged += 'error' not in v
                kept += 'error' in v
            except HTTPException:
                kept += 1
        folder = DATA / 'files' / d['id']
        if folder.is_dir():
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()
    with db() as c:
        ids = [d['id'] for d in dialogs]
        for did in ids:
            c.execute('DELETE FROM files WHERE dialog=?', (did,))
            c.execute('DELETE FROM turns WHERE dialog=?', (did,))
            c.execute('DELETE FROM usage_snap WHERE dialog=?', (did,))
            c.execute('UPDATE cron_jobs SET dialog=NULL WHERE dialog=?', (did,))
        c.execute('DELETE FROM dialogs WHERE owner=?', (uid,))
        c.execute('DELETE FROM sessions WHERE user=?', (uid,))
        c.execute('DELETE FROM perms WHERE subject=?', ('user:' + uid,))
        c.execute('DELETE FROM users WHERE id=?', (uid,))
    audit(admin, 'user.delete', u['username'], {'dialogs': len(dialogs), 'hermes_sessions_deleted': purged, 'hermes_sessions_kept': kept})
    return {'deleted': u['username'], 'dialogs': len(dialogs), 'hermes_sessions_deleted': purged, 'hermes_sessions_kept': kept}


# ---------------- permissions ----------------
# Keys are namespaced so new kinds (providers, tools, ...) plug in without schema changes:
#   cmd:<name> / cmd:*        slash commands
#   skill:<name> / skill:*    skill & bundle slash commands
#   feature:<name>            portal features (e.g. feature:own_subscriptions — planned)
# Resolution (deny by default): admin -> all; user exact > role exact > user wildcard > role wildcard > False.
with db() as c:
    c.execute(
        'CREATE TABLE IF NOT EXISTS perms(subject TEXT NOT NULL, key TEXT NOT NULL, value INTEGER NOT NULL, PRIMARY KEY(subject,key))'
    )
    if not c.execute("SELECT 1 FROM perms WHERE subject='role:user' LIMIT 1").fetchone():
        for k in [
            'help',
            'whoami',
            'new',
            'reset',
            'title',
            'compress',
            'compact',
            'usage',
            'status',
            'context',
            'ctx',
            'history',
            'retry',
            'undo',
            'personality',
            'btw',
            'version',
            'v',
        ]:
            c.execute("INSERT INTO perms VALUES('role:user',?,1)", ('cmd:' + k,))
        c.execute("INSERT INTO perms VALUES('role:user','skill:*',1)")
FEATURES = {
    'feature:own_soul': 'Редагувати SOUL.md свого профілю — характер та інструкції агента',
    'feature:own_memory': 'Редагувати MEMORY.md і USER.md свого профілю — памʼять агента та відомості про користувача',
    'feature:own_subscriptions': 'Підключати власні ШІ-підписки (API-ключ) у своєму профілі; доступні провайдери задаються нижче',
    'feature:own_skills': 'Вмикати й вимикати скіли та бібліотеку у своєму профілі',
    'feature:switch_model': 'Обирати провайдера й модель у шапці чату (серед підключених до профілю)',
    'feature:own_plugins': 'Вмикати й вимикати плагіни у своєму профілі (лише з пісочницею Docker)',
    'feature:cursor_agent': 'Підключати власний ключ Cursor: агент доручає задачі з коду Cursor Agent CLI у пісочниці профілю (оплата з підписки Cursor користувача)',
    'feature:cron': 'Заплановані завдання: Hermes виконує доручення за розкладом і надсилає звіти в чат (до 5 завдань, не частіше ніж раз на годину)',
}
with db() as c:
    for k in (
        'feature:own_skills',
        'feature:own_plugins',
        'feature:switch_model',
        'feature:own_soul',
        'feature:own_memory',
        'feature:cron',
        'feature:cursor_agent',
    ):  # default: allowed
        c.execute(
            "INSERT INTO perms(subject,key,value) SELECT 'role:user',?,1 WHERE NOT EXISTS(SELECT 1 FROM perms WHERE subject='role:user' AND key=?)",
            (k, k),
        )
    # own Claude subscription (OAuth Pro/Max or API key) allowed by default
    c.execute(
        "INSERT INTO perms(subject,key,value) SELECT 'role:user','provider:anthropic',1 WHERE NOT EXISTS(SELECT 1 FROM perms WHERE subject='role:user' AND key='provider:anthropic')"
    )
    # steer only adds a hint to the running turn (no extra session, no extra cost): allowed by default
    c.execute(
        "INSERT INTO perms(subject,key,value) SELECT 'role:user','cmd:steer',1 WHERE NOT EXISTS(SELECT 1 FROM perms WHERE subject='role:user' AND key='cmd:steer')"
    )
KEY_RE = re.compile(r'^(cmd|skill|provider):(\*|[A-Za-z0-9_.-]{1,64})$|^feature:[a-z_]{1,40}$')


def perm_rows(subject):
    with db() as c:
        return {r['key']: bool(r['value']) for r in c.execute('SELECT key,value FROM perms WHERE subject=?', (subject,))}


def allowed(user, key):
    if user['role'] == 'admin':
        return True
    u = perm_rows('user:' + user['id'])
    r = perm_rows('role:' + user['role'])
    kind = key.split(':', 1)[0]
    wild = kind + ':*'
    for table, k in ((u, key), (r, key), (u, wild), (r, wild)):
        if k in table:
            return table[k]
    return False


SLASH_CACHE = {}


def catalog(profile):
    hit = SLASH_CACHE.get(profile)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    items = {}
    for prefix in ['/'] + ['/' + ch for ch in 'abcdefghijklmnopqrstuvwxyz']:
        for it in rpc(profile, 'complete.slash', {'text': prefix}).get('items', []):
            name = it['text'].strip().lstrip('/')
            if name and name not in items:
                items[name] = {'name': name, 'kind': it.get('kind', 'command'), 'meta': it.get('meta', '')}
    out = sorted(items.values(), key=lambda x: (x['kind'], x['name']))
    SLASH_CACHE[profile] = (time.time(), out)
    return out


def item_key(kind, name):
    return ('skill:' if kind == 'skill' else 'cmd:') + name


def kind_of(profile, name):
    for it in catalog(profile):
        if it['name'] == name:
            return it['kind']
    return None


PATH_RE = re.compile(r'(?:/root|/srv|/home/[^/\s]+|~)(?:/[^\s\'",)]*)+')


def redact(text, user):
    """Hide server filesystem layout from ordinary users (install dirs, profile homes, keys paths)."""
    return text if user['role'] == 'admin' else PATH_RE.sub('[шлях на сервері]', text)


@app.get('/api/commands')
def commands(text: str = '/', user=Depends(current_user)):
    if not text.startswith('/') or len(text) > 200:
        return {'items': []}
    items = rpc(user['profile'], 'complete.slash', {'text': text}).get('items', [])
    out = []
    for it in items:
        name = it['text'].strip().lstrip('/')
        if ' ' in text.strip():  # argument stage: only if the base command itself is allowed
            base = text.strip().lstrip('/').split()[0]
            k = kind_of(user['profile'], base)
            if k and allowed(user, item_key(k, base)):
                out.append({'text': it['text'], 'display': it.get('display', ''), 'meta': it.get('meta', ''), 'kind': it.get('kind')})
        elif allowed(user, item_key(it.get('kind', 'command'), name)):
            out.append({'text': it['text'], 'display': it.get('display', ''), 'meta': it.get('meta', ''), 'kind': it.get('kind')})
    return {'items': out[:60]}


class Command(BaseModel):
    command: str = Field(min_length=2, max_length=4000)
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r'^[A-Za-z0-9_-]{16,80}$')


@app.post('/api/dialogs/{did}/command')
def run_command(did: str, body: Command, user=Depends(current_user)):
    P = user['profile']
    text = body.command.strip()
    if not text.startswith('/'):
        raise HTTPException(400, 'Not a slash command')
    parts = text[1:].split(maxsplit=1)
    name = parts[0] if parts else ''
    arg = parts[1] if len(parts) > 1 else ''
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', name):
        raise HTTPException(400, 'Bad command name')
    kind = kind_of(P, name)
    if kind is None:
        raise HTTPException(404, f'Unknown command /{name}')
    if not allowed(user, item_key(kind, name)):
        audit(user, 'command.denied', '/' + name)
        raise HTTPException(403, f'No permission for /{name}')
    audit(user, 'command.run', '/' + name)
    if name in ('retry', 'btw') or kind == 'skill':
        enforce_limits(user)
    sid = live(did, user)
    # Commands the Hermes TUI implements client-side (ui-tui/src/app/slash/commands/core.ts):
    # running them through slash.exec hangs the slash worker. Mirror the TUI here.
    if name in ('help', 'whoami'):
        cat = catalog(P)
        ok = [it for it in cat if allowed(user, item_key(it['kind'], it['name']))]
        cmds = [it for it in ok if it['kind'] != 'skill']
        skills = [it for it in ok if it['kind'] == 'skill']
        if name == 'whoami':
            return {
                'type': 'output',
                'output': f"Користувач: {user['username']}\nРоль: {user['role']}\nПрофіль Hermes: {P}\nДоступні команди ({len(cmds)}): "
                + ' '.join('/' + i['name'] for i in cmds)
                + f"\nДоступні скіли: {len(skills)}",
            }
        lines = ['Доступні команди:'] + [f"  /{i['name']:<14} {i['meta']}" for i in cmds]
        if skills:
            lines += ['', f"Скіли ({len(skills)}): введіть / і першу літеру назви, щоб побачити список."]
        return {'type': 'output', 'output': '\n'.join(lines)}
    if name == 'btw':
        if not arg.strip():
            return {'type': 'output', 'output': 'Використання: /btw <питання>'}
        rpc(P, 'prompt.btw', {'session_id': sid, 'text': arg.strip()[:4000]})
        return {'type': 'output', 'output': 'Бічне питання прийнято, відповідь зʼявиться тут окремо. Основна розмова не змінюється.'}
    if name == 'yolo':
        # TUI client command: slash.exec would flip YOLO only inside the slash worker process,
        # so the live agent kept asking. Mirror the TUI: per-session config.set key=yolo.
        word = arg.strip().lower()
        val = {'on': 'on', 'off': 'off', 'увімкнути': 'on', 'вимкнути': 'off'}.get(word, '') if word else ''
        if word and not val:
            return {'type': 'output', 'output': 'Використання: /yolo [on|off] — без аргументу перемикає'}
        r = rpc(P, 'config.set', {'key': 'yolo', 'value': val, 'session_id': sid})
        on = str(r.get('value')) == '1'
        audit(user, 'yolo.' + ('on' if on else 'off'), '/yolo')
        return {
            'type': 'output',
            'output': (
                'YOLO увімкнено для цього чату: команди виконуються без запиту дозволу. Вимкнути — /yolo ще раз.'
                if on
                else 'YOLO вимкнено: небезпечні команди знову потребують вашого дозволу.'
            ),
        }
    if name in ('new', 'reset', 'clear'):
        title = ' '.join(arg.split())[:120]
        d = create_dialog(NewDialog(title=title), user=user)
        return {'type': 'new_dialog', 'id': d['id'], 'title': d['title']}
    if name == 'title':
        if not arg.strip():
            return {'type': 'output', 'output': 'Назва: ' + (dialog(did, user)['title'] or UNTITLED)}
        title = ' '.join(arg.split())[:120]
        r = rpc(P, 'session.title', {'session_id': sid, 'title': title})
        _set_title(did, title, 'user')
        return {'type': 'retitled', 'output': 'Назву змінено: ' + r.get('title', title)}
    if name in ('undo', 'retry'):
        last = ''
        if name == 'retry':
            hist = rpc(P, 'session.history', {'session_id': sid}).get('messages', [])
            users = [m for m in hist if m.get('role') == 'user']
            if users:
                m = users[-1]
                last = m.get('text') if isinstance(m.get('text'), str) else (m.get('content') if isinstance(m.get('content'), str) else '')
            if not last:
                return {'type': 'output', 'output': 'Немає попереднього повідомлення для повтору.'}
        v = bridge(P, '/rpc', {'method': 'session.undo', 'params': {'session_id': sid, **({'intent': 'retry'} if name == 'retry' else {})}})
        if 'error' in v:
            raise HTTPException(409, v['error'].get('message', 'Undo failed'))
        removed = v['result'].get('removed', 0)
        if name == 'undo':
            return {'type': 'history_changed', 'output': f'Скасовано повідомлень: {removed}' if removed else 'Немає що скасовувати.'}
        if not removed:
            return {'type': 'output', 'output': 'Немає попереднього повідомлення для повтору.'}
        snap = bridge(P, '/events', {'session_id': sid})
        with db() as c:
            c.execute(
                'INSERT INTO turns VALUES(?,?,?,?,?,?,?)',
                (body.request_id, did, 'cmd:retry', snap['epoch'], snap['cursor'], 'running', time.time()),
            )
        rpc(P, 'prompt.submit', {'session_id': sid, 'text': last})
        return {'type': 'turn', 'notice': 'Повторюю останнє повідомлення'}

    def dispatch(n, a):
        v = bridge(P, '/rpc', {'method': 'command.dispatch', 'params': {'name': n, 'arg': a, 'session_id': sid}})
        if 'error' in v:
            raise HTTPException(400, v['error'].get('message', 'Command failed'))
        return v['result']

    if kind == 'skill':
        res = dispatch(name, arg)
    else:
        v = bridge(P, '/rpc', {'method': 'slash.exec', 'params': {'command': text, 'session_id': sid}})
        if 'error' in v:
            msg = v['error'].get('message', 'Command failed')
            if v['error'].get('code') == 5030:
                raise HTTPException(501, f'/{name} не підтримується у веб-інтерфейсі (у Hermes це команда терміналу)')
            if v['error'].get('code') == 4018 and ('command.dispatch' in msg or 'skill' in msg.lower() or 'bundle' in msg.lower()):
                res = dispatch(name, arg)
            elif v['error'].get('code') == 4018:
                return {'type': 'output', 'output': msg}
            else:
                raise HTTPException(400, msg)
        else:
            res = v['result']
    if res.get('type') == 'alias':
        target = res.get('target', '').strip().lstrip('/').split(maxsplit=1)
        tk = kind_of(P, target[0]) if target else None
        if not tk or not allowed(user, item_key(tk, target[0])):
            raise HTTPException(403, 'Alias target not permitted')
        return run_command(did, Command(command='/' + ' '.join(target) + ((' ' + arg) if arg else '')), user)
    if res.get('type') in ('send', 'skill') and res.get('message'):
        # Skill/bundle expands to a prompt: run it as a normal, tracked turn.
        snap = bridge(P, '/events', {'session_id': sid})
        with db() as c:
            c.execute(
                'INSERT INTO turns VALUES(?,?,?,?,?,?,?)',
                (body.request_id, did, 'cmd:' + name, snap['epoch'], snap['cursor'], 'running', time.time()),
            )
        rpc(P, 'prompt.submit', {'session_id': sid, 'text': res['message']})
        return {'type': 'turn', 'notice': res.get('notice') or f'/{name} запущено'}
    out = res.get('output') or res.get('message') or json.dumps(res, ensure_ascii=False)[:4000]
    return {'type': 'output', 'output': redact(str(out), user)[:20000]}


@app.get('/api/admin/catalog')
def admin_catalog(profile: str, admin=Depends(admin_user)):
    if profile not in available_profiles():
        raise HTTPException(400, 'Profile has no running bridge')
    try:
        provs = [{'slug': p['slug'], 'name': p.get('name') or p['slug']} for p in provider_rows(profile)[0]]
    except HTTPException:
        provs = []
    provs = [{'slug': k, 'name': v + ' — вхід через OAuth'} for k, v in OAUTH_NAMES.items()] + [
        p for p in provs if p['slug'] not in OAUTH_NAMES
    ]
    return {'items': catalog(profile), 'features': [{'key': k, 'meta': v} for k, v in FEATURES.items()], 'providers': provs}


def subject_ok(subject):
    if subject == 'role:user':
        return subject
    if subject.startswith('user:'):
        with db() as c:
            if c.execute('SELECT 1 FROM users WHERE id=?', (subject[5:],)).fetchone():
                return subject
    raise HTTPException(404, 'Unknown subject')


@app.get('/api/admin/permissions/{subject}')
def get_perms(subject: str, admin=Depends(admin_user)):
    return perm_rows(subject_ok(subject))


class PermPatch(BaseModel):
    changes: dict[str, bool | None]


@app.put('/api/admin/permissions/{subject}')
def put_perms(subject: str, body: PermPatch, admin=Depends(admin_user)):
    subject_ok(subject)
    for k in body.changes:
        if not KEY_RE.match(k):
            raise HTTPException(400, f'Bad key {k}')
    with db() as c:
        for k, v in body.changes.items():
            if v is None:
                c.execute('DELETE FROM perms WHERE subject=? AND key=?', (subject, k))
            else:
                c.execute(
                    'INSERT INTO perms VALUES(?,?,?) ON CONFLICT(subject,key) DO UPDATE SET value=excluded.value', (subject, k, int(v))
                )
    audit(admin, 'perms.update', 'role:user' if subject == 'role:user' else uname(subject[5:]), body.changes)
    return perm_rows(subject)


SIDE_CMDS = ('cmd:btw', 'cmd:bg', 'cmd:steer')  # composer actions while the agent works


@app.get('/api/me/bridge')
def my_bridge(wake: bool = False, user=Depends(current_user)):
    """State of the user's agent: ready | asleep | starting | unavailable. wake=1 starts a sleeping one (waits ~45 s)."""
    P = user['profile']
    st = bridge_state_for(P)
    if wake and st in ('asleep', 'starting'):
        st = 'ready' if wake_bridge(P) else 'starting'
    return {'state': st, 'idle_sleep_min': BRIDGE_IDLE // 60}


@app.get('/api/me/permissions')
def my_features(user=Depends(current_user)):
    return {k: allowed(user, k) for k in (*FEATURES, *SIDE_CMDS, 'cmd:reasoning', 'cmd:retry', 'cmd:undo')}


# ---------------- admin: profiles (host ops via owner bridge) ----------------
AUDITED_OPS = {
    'set_plugin',
    'set_isolation',
    'create',
    'set_model',
    'set_tools',
    'bridge',
    'copy_credential',
    'remove_credential',
    'delete',
    'set_skill',
    'set_library',
    'promote',
    'library_delete',
    'delete_personal',
}
SKILL_OPS = {'set_skill', 'set_library', 'promote', 'library_delete', 'delete_personal'}


def reload_skills(profiles):
    for p in profiles:
        if p in available_profiles():
            try:
                rpc(p, 'skills.reload', {})
            except HTTPException:
                pass


def host_admin(op, args=None, actor=None):
    res = _host_admin(op, args)
    if op in SKILL_OPS:
        reload_skills([args['name']] if args and args.get('name') else available_profiles())
    if op in AUDITED_OPS:
        a = dict(args or {})
        a.pop('confirm', None)
        audit(actor, 'profile.' + op, a.pop('name', ''), a)
    return res


ADMIN_SOCKET = '/run/bridge/admin.sock'  # admin_host.py (hermes-web-admin.service); no Hermes agent behind it


def _host_admin(op, args=None, timeout=300, readonly=False):
    """Host operations (profile_admin.OPS) through the admin host. Falls back to the owner bridge's legacy /admin
    endpoint only while the admin host socket is missing (e.g. its unit is not installed)."""
    sock = ADMIN_SOCKET if os.path.exists(ADMIN_SOCKET) else socket_for('default')
    try:
        with httpx.Client(transport=httpx.HTTPTransport(uds=sock), timeout=timeout) as client:
            r = client.post('http://hermes-admin/admin', json={'op': op, 'args': args or {}}, headers={'Authorization': 'Bearer ' + TOKEN})
    except Exception as exc:
        raise HTTPException(502, 'Admin host unavailable') from exc
    body = r.json()
    if r.status_code != 200:
        raise HTTPException(r.status_code, body.get('error', 'Profile operation failed'))
    if not readonly:
        SLASH_CACHE.clear()
    return body['result']


def users_by_profile():
    with db() as c:
        return {r['profile']: r['n'] for r in c.execute('SELECT profile,COUNT(*) n FROM users GROUP BY profile')}


@app.get('/api/admin/host/profiles')
def admin_host_profiles(admin=Depends(admin_user)):
    counts = users_by_profile()
    return [{**p, 'users': counts.get(p['name'], 0)} for p in host_admin('list')]


@app.get('/api/admin/host/owner-providers')
def admin_owner_providers(admin=Depends(admin_user)):
    return host_admin('owner_providers')


class ProfileCreate(BaseModel):
    name: str
    provider: str
    model: str
    description: str = ''
    credential_from: str | None = None
    accept_rotation: bool = False


@app.post('/api/admin/host/profiles')
def admin_profile_create(body: ProfileCreate, admin=Depends(admin_user)):
    r = host_admin('create', body.model_dump(), admin)
    remember_assigned(body.name, body.provider, body.model)
    return r


class ProfileModel(BaseModel):
    provider: str
    model: str


@app.put('/api/admin/host/profiles/{name}/model')
def admin_profile_model(name: str, body: ProfileModel, admin=Depends(admin_user)):
    r = host_admin('set_model', {'name': name, **body.model_dump()}, admin)
    remember_assigned(name, body.provider, body.model)
    if r.get('bridge') == 'active':
        host_admin('bridge', {'name': name, 'action': 'restart'}, admin)
    return r


@app.get('/api/admin/host/profiles/{name}/isolation')
def admin_isolation(name: str, admin=Depends(admin_user)):
    return host_admin('isolation', {'name': name})


class IsolationSet(BaseModel):
    enabled: bool
    memory_mb: int = 2048
    cpus: float = 1.0
    network: bool = True


@app.put('/api/admin/host/profiles/{name}/isolation')
def admin_set_isolation(name: str, body: IsolationSet, admin=Depends(admin_user)):
    if busy_profile(name):
        raise HTTPException(409, 'Profile has an active response; wait or stop it first')
    r = host_admin('set_isolation', {'name': name, **body.model_dump()}, admin)
    host_admin('bridge', {'name': name, 'action': 'restart'}, admin)
    return r


@app.get('/api/admin/host/profiles/{name}/tools')
def admin_profile_tools(name: str, admin=Depends(admin_user)):
    return host_admin('tools', {'name': name})


class ToolsPatch(BaseModel):
    enable: list[str] = []
    disable: list[str] = []


@app.put('/api/admin/host/profiles/{name}/tools')
def admin_profile_tools_set(name: str, body: ToolsPatch, admin=Depends(admin_user)):
    r = host_admin('set_tools', {'name': name, **body.model_dump()}, admin)
    host_admin('bridge', {'name': name, 'action': 'restart'}, admin)
    return r


class BridgeAction(BaseModel):
    action: str


@app.post('/api/admin/host/profiles/{name}/bridge')
def admin_profile_bridge(name: str, body: BridgeAction, admin=Depends(admin_user)):
    if body.action not in ('start', 'stop', 'restart', 'sleep'):
        raise HTTPException(400, 'Bad action')
    r = host_admin('bridge', {'name': name, 'action': body.action}, admin)
    if name != 'default':
        _set_asleep(name, body.action == 'sleep')  # sleep = what the idle timer does (wakes on use)
    return r


class CredCopy(BaseModel):
    provider: str
    accept_rotation: bool = False


@app.post('/api/admin/host/profiles/{name}/credentials')
def admin_profile_cred(name: str, body: CredCopy, admin=Depends(admin_user)):
    return host_admin('copy_credential', {'name': name, **body.model_dump()}, admin)


@app.delete('/api/admin/host/profiles/{name}/credentials/{provider}')
def admin_profile_cred_rm(name: str, provider: str, admin=Depends(admin_user)):
    return host_admin('remove_credential', {'name': name, 'provider': provider}, admin)


class ProfileDelete(BaseModel):
    confirm: str


@app.post('/api/admin/host/profiles/{name}/delete')
def admin_profile_delete(name: str, body: ProfileDelete, admin=Depends(admin_user)):
    if users_by_profile().get(name):
        raise HTTPException(400, 'Profile still has portal users; reassign them first')
    return host_admin('delete', {'name': name, 'confirm': body.confirm}, admin)


@app.get('/api/admin/host/profiles/{name}/models')
def admin_profile_models(name: str, admin=Depends(admin_user)):
    if name not in available_profiles():
        raise HTTPException(400, 'Start the profile bridge to list models')
    res = rpc(name, 'model.options', {})
    out = []
    for pr in res.get('providers', []):
        out.append(
            {
                'slug': pr.get('slug'),
                'name': pr.get('name') or pr.get('slug'),
                'authenticated': bool(pr.get('authenticated', pr.get('configured'))),
                'models': [m if isinstance(m, str) else m.get('id') or m.get('name') for m in (pr.get('models') or [])][:200],
            }
        )
    return {'current': {'provider': res.get('provider'), 'model': res.get('model')}, 'providers': out}


@app.get('/api/admin/audit')
def admin_audit(
    limit: int = 100, before: int = 0, action: str = '', actor: str = '', since: float = 0, until: float = 0, admin=Depends(admin_user)
):
    """`since`/`until`: Unix seconds, inclusive start / exclusive end (the UI sends local-day boundaries)."""
    q = 'SELECT * FROM audit WHERE 1=1'
    a = []
    if before:
        q += ' AND id<?'
        a.append(before)
    if since:
        q += ' AND ts>=?'
        a.append(since)
    if until:
        q += ' AND ts<?'
        a.append(until)
    if action:
        q += ' AND action LIKE ?'
        a.append(action.replace('%', '') + '%')
    if actor:
        q += ' AND (actor_name=? OR target=?)'
        a += [actor, actor]
    q += ' ORDER BY id DESC LIMIT ?'
    a.append(max(1, min(limit, 500)))
    with db() as c:
        rows = [dict(r) for r in c.execute(q, a)]
    for r in rows:
        r['details'] = json.loads(r['details']) if r['details'] else None
    return rows


# ---------------- skills ----------------
@app.get('/api/admin/skills/library')
def admin_library(admin=Depends(admin_user)):
    return host_admin('library')


@app.delete('/api/admin/skills/library/{skill}')
def admin_library_delete(skill: str, admin=Depends(admin_user)):
    return host_admin('library_delete', {'skill': skill}, admin)


@app.get('/api/admin/host/profiles/{name}/skills')
def admin_profile_skills(name: str, admin=Depends(admin_user)):
    return host_admin('skills', {'name': name})


class Toggle(BaseModel):
    enabled: bool


@app.put('/api/admin/host/profiles/{name}/skills/{skill}')
def admin_profile_skill(name: str, skill: str, body: Toggle, admin=Depends(admin_user)):
    return host_admin('set_skill', {'name': name, 'skill': skill, 'enabled': body.enabled}, admin)


@app.put('/api/admin/host/profiles/{name}/library')
def admin_profile_library(name: str, body: Toggle, admin=Depends(admin_user)):
    return host_admin('set_library', {'name': name, 'enabled': body.enabled}, admin)


@app.post('/api/admin/host/profiles/{name}/skills/{skill}/promote')
def admin_promote(name: str, skill: str, admin=Depends(admin_user)):
    return host_admin('promote', {'name': name, 'skill': skill}, admin)


@app.delete('/api/admin/host/profiles/{name}/skills/{skill}')
def admin_delete_personal(name: str, skill: str, admin=Depends(admin_user)):
    return host_admin('delete_personal', {'name': name, 'skill': skill}, admin)


def sole_user(user):
    with db() as c:
        return c.execute('SELECT COUNT(*) FROM users WHERE profile=?', (user['profile'],)).fetchone()[0] == 1


@app.get('/api/me/skills')
def my_skills(user=Depends(current_user)):
    r = host_admin('skills', {'name': user['profile']})
    visible = [x for x in r['skills'] if x['enabled'] and x['source'] in ('local', 'external')]
    return {
        'personal': [x for x in visible if x['source'] == 'local'],
        'library': [x for x in visible if x['source'] == 'external'],
        'builtin_count': sum(1 for x in r['skills'] if x['enabled'] and x['source'] in ('builtin', 'hub')),
        'can_delete': sole_user(user),
    }


def require_own(user, feature):
    if not allowed(user, feature):
        raise HTTPException(403, 'Not allowed for you')
    if not sole_user(user):
        raise HTTPException(403, 'Profile is shared; ask the administrator')


@app.get('/api/me/skills/manage')
def my_skills_manage(user=Depends(current_user)):
    require_own(user, 'feature:own_skills')
    return host_admin('skills', {'name': user['profile']})


@app.put('/api/me/skills/{skill}')
def my_skill_toggle(skill: str, body: Toggle, user=Depends(current_user)):
    require_own(user, 'feature:own_skills')
    host_admin('set_skill', {'name': user['profile'], 'skill': skill, 'enabled': body.enabled}, user)
    return my_skills_manage(user)


@app.put('/api/me/library')
def my_library(body: Toggle, user=Depends(current_user)):
    require_own(user, 'feature:own_skills')
    host_admin('set_library', {'name': user['profile'], 'enabled': body.enabled}, user)
    return my_skills_manage(user)


@app.get('/api/admin/host/profiles/{name}/plugins')
def admin_plugins(name: str, admin=Depends(admin_user)):
    return host_admin('plugins', {'name': name})


@app.put('/api/admin/host/profiles/{name}/plugins/{plugin}')
def admin_plugin(name: str, plugin: str, body: Toggle, admin=Depends(admin_user)):
    return host_admin('set_plugin', {'name': name, 'plugin': plugin, 'enabled': body.enabled}, admin)


# ---- Cursor Agent CLI: the user's own Cursor key, used only inside the profile's Docker sandbox (skill cursor-agent) ----
def require_cursor(user):
    if user['profile'] == 'default':
        raise HTTPException(400, 'Cursor підключається лише до особистого профілю користувача')
    require_own(user, 'feature:cursor_agent')


@app.get('/api/me/cursor')
def my_cursor(user=Depends(current_user)):
    require_cursor(user)
    return host_admin('cursor', {'name': user['profile']})


class CursorKey(BaseModel):
    api_key: str = Field(min_length=16, max_length=400)


@app.put('/api/me/cursor')
def my_cursor_set(body: CursorKey, user=Depends(current_user)):
    require_cursor(user)
    restart_own(user)
    P = user['profile']
    r = _host_admin('set_cursor', {'name': P, 'key': body.api_key.strip()})  # not host_admin: the key must never reach the audit log
    audit(user, 'cursor.connect', P, {'account': r.get('email', '')})
    _host_admin('bridge', {'name': P, 'action': 'restart'})
    wait_bridge(P)
    return r


@app.delete('/api/me/cursor')
def my_cursor_remove(user=Depends(current_user)):
    require_cursor(user)
    restart_own(user)
    P = user['profile']
    r = _host_admin('remove_cursor', {'name': P})
    audit(user, 'cursor.disconnect', P)
    _host_admin('bridge', {'name': P, 'action': 'restart'})
    wait_bridge(P)
    return r


@app.get('/api/me/plugins')
def my_plugins(user=Depends(current_user)):
    require_own(user, 'feature:own_plugins')
    return host_admin('plugins', {'name': user['profile']})


@app.put('/api/me/plugins/{plugin}')
def my_plugin(plugin: str, body: Toggle, user=Depends(current_user)):
    require_own(user, 'feature:own_plugins')
    return host_admin('set_plugin', {'name': user['profile'], 'plugin': plugin, 'enabled': body.enabled}, user)


@app.delete('/api/me/skills/{skill}')
def my_skill_delete(skill: str, user=Depends(current_user)):
    if not sole_user(user):
        raise HTTPException(403, 'Profile is shared; ask the administrator')
    host_admin('delete_personal', {'name': user['profile'], 'skill': skill}, user)
    return my_skills(user)


# ---------------- profile identity and memory ----------------
DOCUMENT_FEATURE = {'soul': 'feature:own_soul', 'memory': 'feature:own_memory', 'user': 'feature:own_memory'}


class ProfileDocumentWrite(BaseModel):
    model_config = {'extra': 'forbid'}
    content: str = Field(max_length=40000)
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')


class MemoryConfigWrite(BaseModel):
    model_config = {'extra': 'forbid'}
    changes: dict[str, StrictBool | StrictInt]


def document_kind(document):
    if document not in DOCUMENT_FEATURE:
        raise HTTPException(404, 'Документ не знайдено.')


def profile_edit_idle(name):
    with db() as c:
        active = c.execute(
            "SELECT 1 FROM turns t JOIN dialogs d ON d.id=t.dialog WHERE d.profile=? AND t.state IN ('running','waiting') LIMIT 1", (name,)
        ).fetchone()
    if active:
        raise HTTPException(409, 'Агент зараз працює. Збережіть зміни після завершення відповіді.')


def own_document(user, document):
    document_kind(document)
    if user['profile'] == 'default' and user['role'] != 'admin':
        raise HTTPException(403, 'Профіль власника доступний лише адміністратору.')
    require_own(user, DOCUMENT_FEATURE[document])


def save_document(name, document, body, actor):
    document_kind(document)
    profile_edit_idle(name)
    try:
        result = host_admin('set_profile_document', {'name': name, 'document': document, **body.model_dump()})
    except HTTPException as e:
        if str(e.detail).startswith('Document changed'):
            raise HTTPException(
                409, 'Документ змінився після відкриття. Оновіть його й перенесіть свої зміни; чернетку не видалено.'
            ) from e
        raise
    audit(actor, 'profile.document.edit', name, {'document': document, 'chars': len(body.content)})
    return result


@app.get('/api/admin/host/profiles/{name}/documents/{document}')
def admin_document(name: str, document: str, admin=Depends(admin_user)):
    document_kind(document)
    return host_admin('profile_document', {'name': name, 'document': document})


@app.put('/api/admin/host/profiles/{name}/documents/{document}')
def admin_document_save(name: str, document: str, body: ProfileDocumentWrite, admin=Depends(admin_user)):
    return save_document(name, document, body, admin)


@app.get('/api/me/agent/documents/{document}')
def my_document(document: str, user=Depends(current_user)):
    own_document(user, document)
    return host_admin('profile_document', {'name': user['profile'], 'document': document})


@app.put('/api/me/agent/documents/{document}')
def my_document_save(document: str, body: ProfileDocumentWrite, user=Depends(current_user)):
    own_document(user, document)
    return save_document(user['profile'], document, body, user)


@app.get('/api/admin/host/profiles/{name}/memory-config')
def admin_memory_config(name: str, admin=Depends(admin_user)):
    return host_admin('profile_memory_config', {'name': name})


@app.put('/api/admin/host/profiles/{name}/memory-config')
def admin_memory_config_save(name: str, body: MemoryConfigWrite, admin=Depends(admin_user)):
    profile_edit_idle(name)
    result = host_admin('set_profile_memory_config', {'name': name, 'changes': body.changes})
    audit(admin, 'profile.memory.config', name, {'keys': sorted(body.changes)})
    return result


# ---------------- own AI subscriptions ----------------
with db() as c:
    c.execute('CREATE TABLE IF NOT EXISTS assigned_model(profile TEXT PRIMARY KEY, provider TEXT, model TEXT)')


def remember_assigned(profile, provider, model):
    with db() as c:
        c.execute(
            'INSERT INTO assigned_model VALUES(?,?,?) ON CONFLICT(profile) DO UPDATE SET provider=excluded.provider,model=excluded.model',
            (profile, provider, model),
        )


def assigned(profile):
    with db() as c:
        r = c.execute('SELECT provider,model FROM assigned_model WHERE profile=?', (profile,)).fetchone()
    if r:
        return dict(r)
    cur = next((p for p in _host_admin('list') if p['name'] == profile), None)
    if cur:
        remember_assigned(profile, cur['provider'], cur['model'])
        return {'provider': cur['provider'], 'model': cur['model']}
    return None


with db() as c:
    c.execute('CREATE TABLE IF NOT EXISTS provider_env(slug TEXT PRIMARY KEY, key_env TEXT NOT NULL, name TEXT)')


def provider_rows(profile):
    """API-key providers for a profile. Hermes omits auth_type/key_env on rows that are already
    authenticated, so the slug->env-var mapping is learned from unauthenticated rows and persisted."""
    res = rpc(profile, 'model.options', {'include_unconfigured': True})
    with db() as c:
        for p in res.get('providers', []):
            if p.get('auth_type') == 'api_key' and p.get('key_env') and p.get('slug') != 'custom':
                c.execute(
                    'INSERT INTO provider_env VALUES(?,?,?) ON CONFLICT(slug) DO UPDATE SET key_env=excluded.key_env,name=excluded.name',
                    (p['slug'], p['key_env'], p.get('name')),
                )
        known = {r['slug']: r['key_env'] for r in c.execute('SELECT slug,key_env FROM provider_env')}
    rows = [{**p, 'key_env': known[p['slug']]} for p in res.get('providers', []) if p.get('slug') in known]
    return rows, res


with db() as c:
    c.execute(
        'CREATE TABLE IF NOT EXISTS oauth_owned(profile TEXT, provider TEXT, user TEXT, job TEXT, ts REAL, PRIMARY KEY(profile,provider))'
    )
OAUTH_NAMES = {
    'anthropic': 'Claude (підписка Pro/Max)',
    'openai-codex': 'OpenAI Codex (підписка ChatGPT)',
    'nous': 'Nous Portal',
    'xai-oauth': 'xAI Grok (підписка)',
}


def oauth_owned(profile):
    with db() as c:
        return {r['provider'] for r in c.execute('SELECT provider FROM oauth_owned WHERE profile=? AND job IS NULL', (profile,))}


def own_providers(profile):
    return _own_key_providers(profile) | oauth_owned(profile)


def _own_key_providers(profile):
    keys = set(_host_admin('env_keys', {'name': profile}))
    try:
        rows, _ = provider_rows(profile)
    except HTTPException:
        return set()
    return {p['slug'] for p in rows if p.get('key_env') in keys}


def require_own_subs(user):
    if not allowed(user, 'feature:own_subscriptions'):
        raise HTTPException(403, 'Own subscriptions are not enabled for you')
    with db() as c:
        if c.execute('SELECT COUNT(*) FROM users WHERE profile=?', (user['profile'],)).fetchone()[0] != 1:
            raise HTTPException(409, 'Your Hermes profile is shared with other users; ask the administrator for a personal profile')


def busy_profile(profile):
    with db() as c:
        return (
            c.execute(
                "SELECT COUNT(*) FROM turns t JOIN dialogs d ON d.id=t.dialog WHERE d.profile=? AND t.state IN ('running','waiting') AND t.created>?",
                (profile, time.time() - 900),
            ).fetchone()[0]
            > 0
        )


@app.get('/api/me/providers')
def my_providers(user=Depends(current_user)):
    require_own_subs(user)
    rows, res = provider_rows(user['profile'])
    keys = set(_host_admin('env_keys', {'name': user['profile']}))
    out = [
        {
            'slug': p['slug'],
            'name': p.get('name') or p['slug'],
            'own': p['key_env'] in keys,
            'models': (p.get('featured_models') or p.get('models') or [])[:60],
        }
        for p in rows
        if allowed(user, 'provider:' + p['slug'])
    ]
    owned = oauth_owned(user['profile'])
    oauth = [
        {
            'slug': s,
            'name': n,
            'own': s in owned,
            'models': next(
                ((p.get('featured_models') or p.get('models') or [])[:60] for p in res.get('providers', []) if p.get('slug') == s), []
            ),
        }
        for s, n in OAUTH_NAMES.items()
        if allowed(user, 'provider:' + s)
    ]
    return {
        'providers': out,
        'oauth': oauth,
        'current': {'provider': res.get('provider'), 'model': res.get('model')},
        'assigned': assigned(user['profile']),
    }


# ---- subscription limit gauges ----
LIMIT_NAMES = {'anthropic': 'Claude', 'openai-codex': 'ChatGPT', 'openrouter': 'OpenRouter', 'nous': 'Nous'}
LAST_LIMITS = {}


def limits_for(profile, provider=None):
    key = profile + '|' + (provider or '')
    try:
        d = host_admin('limits', {'name': profile, **({'provider': provider} if provider else {})})
    except HTTPException:  # owner bridge restarting/busy: serve the last reading instead of nothing
        if key in LAST_LIMITS:
            return {**LAST_LIMITS[key], 'stale': True}
        raise
    d['name'] = LIMIT_NAMES.get(d['provider'], d['provider'])
    d['own'] = profile != 'default' and d['provider'] in own_providers(profile)  # else the owner's shared subscription
    if d.get('windows'):
        LAST_LIMITS[key] = d
    return d


# ---- per-user interface preferences (theme); stored server-side so they follow the user across devices ----
THEMES = {'system', 'light', 'dark'}
COLOR_PALETTES = {
    'blue',
    'forest',
    'violet',
    'amber',
    'rose',
    'ocean',
    'mushroom',
    'nord',
    'graphite',
    'coral',
    'plum',
    'matcha',
    'dusk',
    'neon',
    'solarized',
}
BACKGROUNDS = {
    'none',
    'synapse',
    'constellation',
    'waves',
    'aurora',
    'orbits',
    'spores',
    'mycelium',
    'fireflies',
    'ripples',
    'flow',
    'honeycomb',
    'warp',
    'rain',
    'lissajous',
}


class Prefs(BaseModel):
    model_config = {'extra': 'forbid'}
    theme: str | None = None
    palette: str | None = None
    background: str | None = None


@app.get('/api/me/prefs')
def my_prefs(user=Depends(current_user)):
    with db() as c:
        rows = {
            r['key']: r['value']
            for r in c.execute(
                'SELECT key,value FROM settings WHERE key IN (?,?,?)',
                ('theme:' + user['id'], 'palette:' + user['id'], 'background:' + user['id']),
            )
        }
    return {
        'theme': rows.get('theme:' + user['id'], 'system'),
        'themes': sorted(THEMES),
        'palette': rows.get('palette:' + user['id'], 'blue'),
        'palettes': sorted(COLOR_PALETTES),
        'background': rows.get('background:' + user['id'], 'none'),
        'backgrounds': sorted(BACKGROUNDS),
    }


@app.put('/api/me/prefs')
def set_prefs(body: Prefs, user=Depends(current_user)):
    if body.theme is None and body.palette is None and body.background is None:
        raise HTTPException(400, 'Оберіть режим, палітру або фон.')
    if body.background is not None and body.background not in BACKGROUNDS:
        raise HTTPException(400, 'Невідомий фон.')
    if body.theme is not None and body.theme not in THEMES:
        raise HTTPException(400, 'Unknown theme')
    if body.palette is not None and body.palette not in COLOR_PALETTES:
        raise HTTPException(400, 'Невідома кольорова палітра.')
    with db() as c:
        for key, value in (('theme', body.theme), ('palette', body.palette), ('background', body.background)):
            if value is not None:
                c.execute(
                    'INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                    (key + ':' + user['id'], value),
                )
    return my_prefs(user)


@app.get('/api/me/limits')
def my_limits(provider: str = Query('', max_length=60, pattern=r'^[A-Za-z0-9._/@+-]*$'), user=Depends(current_user)):
    return limits_for(user['profile'], provider or None)


ADMIN_LIMITS = {'ts': 0.0, 'data': None, 'busy': False}
ADMIN_LIMITS_LOCK = threading.Lock()


@app.get('/api/admin/limits')
def admin_limits(admin=Depends(admin_user)):
    """Stale-while-revalidate: a cold read of every profile takes ~15 s, so answer from the last reading at once and
    refresh it in the background when it is older than a minute (only the very first call waits)."""
    with ADMIN_LIMITS_LOCK:
        data, age, busy = ADMIN_LIMITS['data'], time.time() - ADMIN_LIMITS['ts'], ADMIN_LIMITS['busy']
        if data is not None and age > 60 and not busy:
            ADMIN_LIMITS['busy'] = True
            threading.Thread(target=_refresh_admin_limits, daemon=True).start()
    if data is None:
        return _refresh_admin_limits()
    return {**data, 'age': round(age)}


def _refresh_admin_limits():
    try:
        data = _admin_limits_now()
        with ADMIN_LIMITS_LOCK:
            ADMIN_LIMITS.update(data=data, ts=time.time())
        return {**data, 'age': 0}
    finally:
        with ADMIN_LIMITS_LOCK:
            ADMIN_LIMITS['busy'] = False


def _admin_limits_now():
    # each lookup shells out to `hermes usage` (1-4 s cold); run them in parallel
    from concurrent.futures import ThreadPoolExecutor

    with db() as c:
        users = [dict(r) for r in c.execute('SELECT id,username,profile FROM users WHERE blocked=0 ORDER BY username')]
    profiles = sorted({u['profile'] for u in users})

    def shared_one(prov):
        try:
            x = host_admin('limits', {'name': 'default', 'provider': prov})
            x['name'] = LIMIT_NAMES[prov]
            return x
        except HTTPException:
            return None

    def per_one(p):
        try:
            return limits_for(p)
        except HTTPException as e:
            return {'provider': '', 'name': '', 'windows': [], 'unavailable': str(e.detail), 'own': False}

    with ThreadPoolExecutor(8) as ex:
        sh = list(ex.map(shared_one, ('anthropic', 'openai-codex')))
        pr = dict(zip(profiles, ex.map(per_one, profiles)))
    return {'shared': [x for x in sh if x], 'users': [{**u, 'limits': pr[u['profile']]} for u in users]}


@app.post('/api/me/oauth/{slug}')
def my_oauth_start(slug: str, user=Depends(current_user)):
    require_own_subs(user)
    if slug not in OAUTH_NAMES or not allowed(user, 'provider:' + slug):
        raise HTTPException(403, 'Provider not allowed')
    st = host_admin('oauth_start', {'name': user['profile'], 'provider': slug})
    with db() as c:
        c.execute(
            'INSERT INTO oauth_owned VALUES(?,?,?,?,?) ON CONFLICT(profile,provider) DO UPDATE SET job=excluded.job,user=excluded.user,ts=excluded.ts',
            (user['profile'], slug, user['id'], st['job'], time.time()),
        )
    audit(user, 'subscription.oauth_start', slug)
    return {k: st.get(k) for k in ('job', 'state', 'url', 'code', 'paste')}


@app.get('/api/me/oauth/{job}')
def my_oauth_status(job: str, user=Depends(current_user)):
    require_own_subs(user)
    with db() as c:
        row = c.execute('SELECT * FROM oauth_owned WHERE job=? AND user=?', (job, user['id'])).fetchone()
    if not row:
        raise HTTPException(404, 'No such sign-in')
    st = host_admin('oauth_status', {'job': job})
    if st['state'] == 'succeeded':
        with db() as c:
            done = c.execute('UPDATE oauth_owned SET job=NULL WHERE job=?', (job,)).rowcount
        if done:
            audit(user, 'subscription.add', row['provider'], {'oauth': True})
            if row['provider'] == 'anthropic':
                restart_after_claude(user)
    elif st['state'] != 'running':
        with db() as c:
            c.execute('DELETE FROM oauth_owned WHERE job=?', (job,))
    return {k: st.get(k) for k in ('job', 'state', 'url', 'code', 'paste')}


class OAuthCode(BaseModel):
    code: str = Field(min_length=10, max_length=700)


@app.post('/api/me/oauth/{job}/code')
def my_oauth_code(job: str, body: OAuthCode, user=Depends(current_user)):
    require_own_subs(user)
    with db() as c:
        row = c.execute('SELECT * FROM oauth_owned WHERE job=? AND user=?', (job, user['id'])).fetchone()
    if not row:
        raise HTTPException(404, 'No such sign-in')
    try:
        _host_admin('oauth_code', {'job': job, 'code': body.code})  # never host_admin: the code must not reach the audit log
    except HTTPException as e:
        if e.status_code >= 500:
            raise
        raise HTTPException(400, e.detail)
    return my_oauth_status(job, user)


def restart_after_claude(user):
    """The running agent may still hold the shared Claude token: restart the user's bridge when it is idle."""
    if busy_profile(user['profile']):
        return
    try:
        host_admin('bridge', {'name': user['profile'], 'action': 'restart'}, user)
        wait_bridge(user['profile'])
    except HTTPException:
        pass


@app.delete('/api/me/oauth/{job}')
def my_oauth_cancel(job: str, user=Depends(current_user)):
    require_own_subs(user)
    with db() as c:
        if not c.execute('SELECT 1 FROM oauth_owned WHERE job=? AND user=?', (job, user['id'])).fetchone():
            raise HTTPException(404, 'No such sign-in')
        c.execute('DELETE FROM oauth_owned WHERE job=?', (job,))
    host_admin('oauth_cancel', {'job': job})
    return {'state': 'cancelled'}


class OwnKey(BaseModel):
    api_key: str = Field(min_length=8, max_length=400)


@app.put('/api/me/providers/{slug}')
def my_provider_save(slug: str, body: OwnKey, user=Depends(current_user)):
    require_own_subs(user)
    if not allowed(user, 'provider:' + slug) or slug not in {p['slug'] for p in provider_rows(user['profile'])[0]}:
        raise HTTPException(403, 'Provider not allowed')
    v = bridge(user['profile'], '/rpc', {'method': 'model.save_key', 'params': {'slug': slug, 'api_key': body.api_key.strip()}})
    if 'error' in v:
        raise HTTPException(400, v['error'].get('message', 'Could not save key'))
    audit(user, 'subscription.add', slug)
    return my_providers(user)


@app.delete('/api/me/providers/{slug}')
def my_provider_remove(slug: str, user=Depends(current_user)):
    require_own_subs(user)
    if slug not in own_providers(user['profile']):
        raise HTTPException(404, 'No own key for this provider')
    if slug in oauth_owned(user['profile']):
        with db() as c:
            c.execute('DELETE FROM oauth_owned WHERE profile=? AND provider=?', (user['profile'], slug))
    v = bridge(user['profile'], '/rpc', {'method': 'model.disconnect', 'params': {'slug': slug}})
    if 'error' in v:
        raise HTTPException(400, v['error'].get('message', 'Could not remove key'))
    audit(user, 'subscription.remove', slug)
    P = user['profile']
    restart = False
    if slug == 'anthropic':
        _host_admin('anthropic_own', {'name': P, 'own': False})
        restart = True
    # Own credentials gone: if the profile still runs on that provider and the administrator assigned another one,
    # return to the assigned model instead of silently borrowing the owner's shared login for the same provider.
    a = assigned(P)
    cur = provider_rows(P)[1].get('provider')
    if cur == slug and a and a.get('provider') != slug and not busy_profile(P):
        host_admin('set_model', {'name': P, 'provider': a['provider'], 'model': a['model']}, user)
        restart = True
    if restart and not busy_profile(P):
        host_admin('bridge', {'name': P, 'action': 'restart'}, user)
        wait_bridge(P)
    return my_providers(user)


class OwnModel(BaseModel):
    provider: str = ''
    model: str = ''
    reset: bool = False


@app.put('/api/me/model')
def my_model(body: OwnModel, user=Depends(current_user)):
    require_own_subs(user)
    if body.reset:
        a = assigned(user['profile'])
        if not a:
            raise HTTPException(404, 'No administrator-assigned model recorded')
        body = OwnModel(provider=a['provider'], model=a['model'])
    elif body.provider not in own_providers(user['profile']):
        raise HTTPException(403, 'Connect your own key for this provider first')
    if busy_profile(user['profile']):
        raise HTTPException(409, 'Wait until the current response finishes')
    host_admin('set_model', {'name': user['profile'], 'provider': body.provider, 'model': body.model}, user)
    host_admin('bridge', {'name': user['profile'], 'action': 'restart'}, user)
    return {'provider': body.provider, 'model': body.model}


# ---- quick model switch (chat header) ----
# Own = credential the user connected himself (unrestricted models). Shared = owner's subscription copied into the profile:
# the admin limits which models of it the user may pick (settings key allowed_models:<uid>; empty -> only the assigned model).
def can_switch(user):
    return user['role'] == 'admin' or (allowed(user, 'feature:switch_model') and sole_user(user))


def shared_allow(uid):
    with db() as c:
        r = c.execute('SELECT value FROM settings WHERE key=?', ('allowed_models:' + uid,)).fetchone()
    return json.loads(r[0]) if r else []


def model_choices(user):
    P = user['profile']
    res = rpc(P, 'model.options', {'include_unconfigured': True})
    own = own_providers(P) if P != 'default' else set()
    admin = user['role'] == 'admin'
    allow = set(shared_allow(user['id']))
    a = assigned(P) if not admin else None
    out = []
    for p in res.get('providers', []):
        slug = p.get('slug')
        # Hermes marks only the active route's credential as authenticated in some cases; the admin-assigned provider is always usable
        if not (p.get('authenticated', p.get('configured')) or slug in own or (a and a['provider'] == slug)):
            continue
        models = [m if isinstance(m, str) else m.get('id') or m.get('name') for m in (p.get('models') or [])][:120]
        kind = 'own' if slug in own else 'shared'
        if kind == 'shared' and not admin:
            base = (
                [a['model']] if a and a['provider'] == slug else []
            )  # assigned alias may be absent from the catalogue (e.g. claude-haiku-4-5)
            models = base + [m for m in models if f'{slug}/{m}' in allow and m not in base]
            if not models:
                continue
        out.append({'slug': slug, 'name': p.get('name') or slug, 'kind': 'owner' if admin else kind, 'models': models})
    return {'current': {'provider': res.get('provider'), 'model': res.get('model')}, 'providers': out}


def wait_bridge(P, timeout=60):
    time.sleep(2)
    end = time.time() + timeout
    while time.time() < end:
        try:
            rpc(P, 'model.options', {})
            return
        except Exception:
            time.sleep(1.5)


def can_reason(user):
    return user['role'] == 'admin' or (allowed(user, 'cmd:reasoning') and sole_user(user))


@app.get('/api/me/models')
def my_models(user=Depends(current_user)):
    # can_switch / can_reason = the profile defaults (Settings, restarts the bridge, sole user only);
    # chat_switch / chat_reason = the per-chat pick in the header (session-scoped, no restart).
    d = model_choices(user)
    d['can_switch'] = can_switch(user)
    d['chat_switch'] = can_switch_chat(user)
    if not (d['can_switch'] or d['chat_switch']):
        d['providers'] = []
    d['can_reason'] = can_reason(user)
    d['chat_reason'] = can_reason_chat(user)
    d['effort'] = host_admin('reasoning', {'name': user['profile']})['effort']
    d['efforts'] = list(EFFORTS)
    return d


class Switch(BaseModel):
    provider: str
    model: str = Field(min_length=1, max_length=120)


def restart_own(user):
    if busy_profile(user['profile']):
        raise HTTPException(409, 'Wait until the current response finishes')


@app.put('/api/me/models')
def my_model_switch(body: Switch, user=Depends(current_user)):
    if not can_switch(user):
        raise HTTPException(403, 'Model switching is not allowed for you')
    p = next((x for x in model_choices(user)['providers'] if x['slug'] == body.provider), None)
    if not p:
        raise HTTPException(403, 'Provider is not available to you')
    if p['kind'] == 'shared' and body.model not in p['models']:
        raise HTTPException(403, 'This model of the shared subscription is not allowed for you')
    restart_own(user)
    P = user['profile']
    host_admin(
        'set_model',
        {'name': P, 'provider': body.provider, 'model': body.model, 'allow_default': P == 'default' and user['role'] == 'admin'},
        user,
    )
    host_admin('bridge', {'name': P, 'action': 'restart'}, user)
    wait_bridge(P)
    return {'provider': body.provider, 'model': body.model}


class Effort(BaseModel):
    effort: str = ''


@app.put('/api/me/reasoning')
def my_reasoning(body: Effort, user=Depends(current_user)):
    if not can_reason(user):
        raise HTTPException(403, 'Reasoning settings are not allowed for you')
    restart_own(user)
    P = user['profile']
    r = host_admin('set_reasoning', {'name': P, 'effort': body.effort, 'allow_default': P == 'default' and user['role'] == 'admin'}, user)
    host_admin('bridge', {'name': P, 'action': 'restart'}, user)
    wait_bridge(P)
    return r


# ---- per-chat model / reasoning (native session-scoped config.set; no bridge restart, other chats untouched) ----
EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh')
MODEL_RE = r'[A-Za-z0-9._:/@+-]{1,120}'
PROVIDER_RE = r'[A-Za-z0-9._/@+-]{1,60}'


def can_switch_chat(user):
    return user['role'] == 'admin' or allowed(user, 'feature:switch_model')


def can_reason_chat(user):
    return user['role'] == 'admin' or allowed(user, 'cmd:reasoning')


def check_chat_model(user, provider, model):
    if not can_switch_chat(user):
        raise HTTPException(403, 'Model switching is not allowed for you')
    if not re.fullmatch(PROVIDER_RE, provider or '') or not re.fullmatch(MODEL_RE, model or ''):
        raise HTTPException(400, 'Bad model name')
    p = next((x for x in model_choices(user)['providers'] if x['slug'] == provider), None)
    if not p:
        raise HTTPException(403, 'Provider is not available to you')
    if p['kind'] == 'shared' and model not in p['models']:
        raise HTTPException(403, 'This model of the shared subscription is not allowed for you')


def check_chat_effort(user, effort):
    if not can_reason_chat(user):
        raise HTTPException(403, 'Reasoning settings are not allowed for you')
    if effort not in EFFORTS:
        raise HTTPException(400, 'Unknown reasoning level')


def apply_chat_runtime(P, sid, provider, model, effort):
    # `provider:model` (not --provider): with an explicit provider Hermes skips building a lazy (just resumed) agent
    # and the pick is silently lost; the combined target builds it first. --session never touches config.yaml.
    if provider and model:
        rpc(P, 'config.set', {'session_id': sid, 'key': 'model', 'value': f'{provider}:{model} --session', 'confirm_expensive_model': True})
    if effort:
        rpc(P, 'config.set', {'session_id': sid, 'key': 'reasoning', 'value': effort})


def chat_runtime(row):
    return {'provider': row.get('chat_provider'), 'model': row.get('chat_model'), 'effort': row.get('chat_effort')}


@app.get('/api/dialogs/{did}/runtime')
def dialog_runtime(did: str, user=Depends(current_user)):
    return chat_runtime(dialog(did, user))


class ChatModel(BaseModel):
    model_config = {'extra': 'forbid'}
    provider: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=120)


@app.put('/api/dialogs/{did}/model')
def dialog_model(did: str, body: ChatModel, user=Depends(current_user)):
    row = dialog(did, user)
    check_chat_model(user, body.provider, body.model)
    apply_chat_runtime(user['profile'], live(did, user), body.provider, body.model, None)  # running turn: Hermes applies it to the next one
    with db() as c:
        c.execute('UPDATE dialogs SET chat_provider=?,chat_model=? WHERE id=?', (body.provider, body.model, did))
    audit(user, 'chat.model', row['title'], {'provider': body.provider, 'model': body.model})
    return {**chat_runtime(row), 'provider': body.provider, 'model': body.model}


class ChatEffort(BaseModel):
    model_config = {'extra': 'forbid'}
    effort: str = Field(max_length=10)


@app.put('/api/dialogs/{did}/reasoning')
def dialog_reasoning(did: str, body: ChatEffort, user=Depends(current_user)):
    row = dialog(did, user)
    check_chat_effort(user, body.effort)
    apply_chat_runtime(user['profile'], live(did, user), None, None, body.effort)
    with db() as c:
        c.execute('UPDATE dialogs SET chat_effort=? WHERE id=?', (body.effort, did))
    return {**chat_runtime(row), 'effort': body.effort}


@app.get('/api/admin/users/{uid}/models')
def admin_user_models(uid: str, admin=Depends(admin_user)):
    with db() as c:
        u = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone()
    if not u:
        raise HTTPException(404, 'No such user')
    res = rpc(u['profile'], 'model.options', {'include_unconfigured': True})
    own = own_providers(u['profile']) if u['profile'] != 'default' else set()
    shared = [
        {
            'slug': p['slug'],
            'name': p.get('name') or p['slug'],
            'models': [m if isinstance(m, str) else m.get('id') or m.get('name') for m in (p.get('models') or [])][:120],
        }
        for p in res.get('providers', [])
        if p.get('authenticated', p.get('configured')) and p.get('slug') not in own
    ]
    asg = assigned(u['profile'])
    for x in shared:
        if asg and x['slug'] == asg['provider'] and asg['model'] not in x['models']:
            x['models'].insert(0, asg['model'])
    return {'shared': shared, 'allowed': shared_allow(uid), 'assigned': asg}


class Allow(BaseModel):
    allowed: list[str] = Field(default_factory=list, max_length=500)


@app.put('/api/admin/users/{uid}/models')
def admin_user_models_set(uid: str, body: Allow, admin=Depends(admin_user)):
    vals = sorted({v for v in body.allowed if re.fullmatch(r'[A-Za-z0-9._:@+-]{1,60}/[A-Za-z0-9._:/@+-]{1,120}', v)})
    with db() as c:
        c.execute(
            'INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            ('allowed_models:' + uid, json.dumps(vals)),
        )
    audit(admin, 'perms.models', uid, {'allowed': vals})
    return {'allowed': vals}


# ---------------- usage & limits ----------------
with db() as c:
    c.execute(
        'CREATE TABLE IF NOT EXISTS usage_snap(dialog TEXT PRIMARY KEY, input INTEGER, output INTEGER, cache_read INTEGER, cache_write INTEGER, cost REAL)'
    )
    c.execute(
        'CREATE TABLE IF NOT EXISTS usage(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, user TEXT, profile TEXT, dialog TEXT, input INTEGER, output INTEGER, cache_read INTEGER, cache_write INTEGER, cost REAL, models TEXT)'
    )
    c.execute('CREATE INDEX IF NOT EXISTS usage_ts ON usage(ts)')
    c.execute('CREATE TABLE IF NOT EXISTS limits(subject TEXT PRIMARY KEY, usd_month REAL)')  # user:<id> | profile:<name>
    if 'own' not in [r[1] for r in c.execute('PRAGMA table_info(usage)')]:
        c.execute('ALTER TABLE usage ADD COLUMN own INTEGER NOT NULL DEFAULT 0')
USAGE_LOCK = threading.Lock()


def month_start():
    t = time.gmtime()
    return time.mktime((t.tm_year, t.tm_mon, 1, 0, 0, 0, 0, 0, 0)) - time.timezone


def record_usage(d):
    """Store the delta since the last snapshot of this dialog's Hermes session chain."""
    try:
        tot = _host_admin('usage', {'name': d['profile'], 'session_id': d['stored']})
    except HTTPException:
        return
    with USAGE_LOCK, db() as c:
        prev = c.execute('SELECT * FROM usage_snap WHERE dialog=?', (d['id'],)).fetchone()
        delta = {k: tot[k] - (prev[k] if prev else 0) for k in ('input', 'output', 'cache_read', 'cache_write', 'cost')}
        if any(v > 0 for v in delta.values()):
            own = int(bool(tot.get('providers')) and all(p in own_providers(d['profile']) for p in tot['providers'].split(',')))
            c.execute(
                'INSERT INTO usage(ts,user,profile,dialog,input,output,cache_read,cache_write,cost,models,own) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (
                    time.time(),
                    d['owner'],
                    d['profile'],
                    d['id'],
                    delta['input'],
                    delta['output'],
                    delta['cache_read'],
                    delta['cache_write'],
                    round(delta['cost'], 6),
                    tot['models'],
                    own,
                ),
            )
        c.execute(
            'INSERT INTO usage_snap VALUES(?,?,?,?,?,?) ON CONFLICT(dialog) DO UPDATE SET input=excluded.input,output=excluded.output,cache_read=excluded.cache_read,cache_write=excluded.cache_write,cost=excluded.cost',
            (d['id'], tot['input'], tot['output'], tot['cache_read'], tot['cache_write'], tot['cost']),
        )


def spent(field, value, since):
    # Limits cover the administrator's subscriptions only: usage on a user's own key is excluded.
    with db() as c:
        return c.execute(f'SELECT COALESCE(SUM(cost),0) FROM usage WHERE {field}=? AND ts>=? AND own=0', (value, since)).fetchone()[0]


def limit_of(subject):
    with db() as c:
        r = c.execute('SELECT usd_month FROM limits WHERE subject=?', (subject,)).fetchone()
    return r['usd_month'] if r else None


def enforce_limits(user):
    since = month_start()
    for subject, field, value, label in (
        ('user:' + user['id'], 'user', user['id'], 'Ваш місячний ліміт'),
        ('profile:' + user['profile'], 'profile', user['profile'], 'Місячний ліміт профілю'),
    ):
        lim = limit_of(subject)
        if lim is not None and spent(field, value, since) >= lim:
            audit(user, 'limit.blocked', subject, {'limit_usd': lim})
            raise HTTPException(
                429,
                (
                    f'{label} (${lim:.4f} ) вичерпано. Зверніться до адміністратора.'.replace(' )', ')')
                    if lim < 1
                    else f'{label} (${lim:.2f}) вичерпано. Зверніться до адміністратора.'
                ),
            )


def usage_summary(field, value, since):
    with db() as c:
        r = c.execute(
            f'SELECT COUNT(*) n,COALESCE(SUM(input+output+cache_read+cache_write),0) tokens,COALESCE(SUM(CASE WHEN own=0 THEN cost END),0) cost,COALESCE(SUM(CASE WHEN own=1 THEN cost END),0) own_cost FROM usage WHERE {field}=? AND ts>=?',
            (value, since),
        ).fetchone()
    return {'turns': r['n'], 'tokens': r['tokens'], 'cost': round(r['cost'], 4), 'own_cost': round(r['own_cost'], 4)}


def usage_reconciler():
    """Every 2 min, re-read Hermes totals for dialogs with turns in the last 24 h. Deltas are idempotent, so this only
    adds what /sync missed (browser closed before the turn settled, or late compression/continuation sessions)."""
    while True:
        time.sleep(120)
        try:
            with db() as c:
                ds = [
                    dict(r)
                    for r in c.execute(
                        'SELECT DISTINCT d.* FROM dialogs d JOIN turns t ON t.dialog=d.id WHERE t.created>?', (time.time() - 86400,)
                    )
                ]
            live_profiles = set(available_profiles())
            for d in ds:
                if d['owner'] and d['profile'] in live_profiles:
                    record_usage(d)
        except Exception:
            pass


threading.Thread(target=usage_reconciler, daemon=True).start()


@app.get('/api/me/usage')
def my_usage(user=Depends(current_user)):
    return {**usage_summary('user', user['id'], month_start()), 'limit': limit_of('user:' + user['id'])}


@app.get('/api/admin/usage')
def admin_usage(admin=Depends(admin_user)):
    since = month_start()
    with db() as c:
        users = [dict(r) for r in c.execute('SELECT id,username,profile,role FROM users ORDER BY username')]
    profiles = sorted({u['profile'] for u in users} | set(available_profiles()))
    with db() as c:
        daily = [
            dict(r)
            for r in c.execute(
                "SELECT CAST((ts-?)/86400 AS INTEGER) day,COALESCE(SUM(cost),0) cost FROM usage WHERE ts>=? GROUP BY day ORDER BY day",
                (since, since),
            )
        ]
    return {
        'since': since,
        'users': [{**u, **usage_summary('user', u['id'], since), 'limit': limit_of('user:' + u['id'])} for u in users],
        'profiles': [{'name': p, **usage_summary('profile', p, since), 'limit': limit_of('profile:' + p)} for p in profiles],
        'daily': daily,
    }


class LimitSet(BaseModel):
    usd_month: float | None = Field(default=None, ge=0, le=100000)


@app.put('/api/admin/limits/{subject}')
def admin_set_limit(subject: str, body: LimitSet, admin=Depends(admin_user)):
    if subject.startswith('user:'):
        with db() as c:
            if not c.execute('SELECT 1 FROM users WHERE id=?', (subject[5:],)).fetchone():
                raise HTTPException(404, 'No such user')
        label = uname(subject[5:])
    elif subject.startswith('profile:') and PROFILE_RE.match(subject[8:]):
        label = 'profile:' + subject[8:]
    else:
        raise HTTPException(400, 'Bad subject')
    with db() as c:
        if body.usd_month is None:
            c.execute('DELETE FROM limits WHERE subject=?', (subject,))
        else:
            c.execute(
                'INSERT INTO limits VALUES(?,?) ON CONFLICT(subject) DO UPDATE SET usd_month=excluded.usd_month', (subject, body.usd_month)
            )
    audit(admin, 'limit.update', label, {'usd_month': body.usd_month})
    return {'subject': subject, 'usd_month': body.usd_month}


def month_total():
    with db() as c:
        return c.execute('SELECT COALESCE(SUM(cost),0) FROM usage WHERE ts>=?', (month_start(),)).fetchone()[0]


@app.get('/api/admin/overview')
def admin_overview(admin=Depends(admin_user)):
    now = time.time()
    with db() as c:
        active = [
            dict(r)
            for r in c.execute(
                "SELECT t.created,t.state,d.title,d.profile,u.username FROM turns t JOIN dialogs d ON d.id=t.dialog LEFT JOIN users u ON u.id=d.owner WHERE t.state IN ('running','waiting') AND t.created>? ORDER BY t.created",
                (now - 3600,),
            )
        ]
        users = [
            dict(r)
            for r in c.execute(
                'SELECT u.username,u.role,u.profile,u.blocked,u.last_login,(SELECT COUNT(*) FROM sessions s WHERE s.user=u.id AND s.expires>?) sessions FROM users u ORDER BY u.last_login DESC',
                (now,),
            )
        ]
        day = c.execute(
            "SELECT SUM(action='chat.turn') turns,SUM(action='auth.login_failed' AND COALESCE(ip,'') NOT LIKE '172.%') failed,SUM(action='auth.login_failed' AND ip LIKE '172.%') failed_internal,SUM(action='command.denied') denied FROM audit WHERE ts>?",
            (now - 86400,),
        ).fetchone()
    try:
        profiles = [{k: p[k] for k in ('name', 'bridge', 'model')} for p in host_admin('list')]
    except HTTPException:
        profiles = []
    try:
        backup = host_admin('backup_status')
    except HTTPException:
        backup = None
    return {
        'backup': backup,
        'active': active,
        'users': users,
        'profiles': profiles,
        'last24h': {
            'turns': day['turns'] or 0,
            'failed_logins': day['failed'] or 0,
            'failed_internal': day['failed_internal'] or 0,
            'denied_commands': day['denied'] or 0,
        },
        'month_cost': round(month_total(), 4),
    }


# ---------------- VPS resources ----------------
# The backend samples the owner bridge's read-only `vps_stats` host op every 15 s, keeps the latest full reading in
# memory and a compact series in sqlite (8 days) so the admin dashboard can draw charts without touching the host.
VPS_EVERY = 15
VPS_KEEP = 8 * 86400
LAST_VPS = {'data': None}
VPS_RANGES = {'1h': 3600, '6h': 6 * 3600, '24h': 86400, '7d': 7 * 86400}
with db() as c:
    c.execute(
        'CREATE TABLE IF NOT EXISTS vps_samples(ts REAL PRIMARY KEY, cpu REAL, steal REAL, iowait REAL, mem REAL, swap REAL, disk REAL, load1 REAL, rx REAL, tx REAL, rd REAL, wr REAL)'
    )


def _vps_units(units):
    """Sum per (group,name): a profile may own several sandbox containers."""
    out = {}
    for u in units or []:
        k = (u['group'], u['name'])
        o = out.setdefault(k, {'group': u['group'], 'name': u['name'], 'mem': 0, 'cpu': None, 'count': 0})
        o['mem'] += u['mem']
        o['count'] += 1
        if u['cpu'] is not None:
            o['cpu'] = round((o['cpu'] or 0) + u['cpu'], 4)
    return sorted(out.values(), key=lambda u: -u['mem'])


def vps_sampler():
    last_prune = 0
    while True:
        try:
            s = _host_admin('vps_stats', timeout=20, readonly=True)
            s['units'] = _vps_units(s.get('units'))
            LAST_VPS['data'] = s
            if s.get('cpu') and s.get('rates'):
                m = s['mem']
                disk = max((d['used'] / d['total'] for d in s['disks']), default=0)
                with db() as c:
                    c.execute(
                        'INSERT OR REPLACE INTO vps_samples VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                        (
                            round(s['ts'], 1),
                            s['cpu']['total'],
                            s['cpu']['steal'],
                            s['cpu']['iowait'],
                            m['used'] / m['total'] if m['total'] else 0,
                            m['swap_used'] / m['swap_total'] if m['swap_total'] else 0,
                            disk,
                            s['load'][0],
                            s['rates']['rx'],
                            s['rates']['tx'],
                            s['rates']['read'],
                            s['rates']['write'],
                        ),
                    )
                    if time.time() - last_prune > 3600:
                        c.execute('DELETE FROM vps_samples WHERE ts<?', (time.time() - VPS_KEEP,))
                        last_prune = time.time()
        except Exception:
            pass
        time.sleep(VPS_EVERY)


threading.Thread(target=vps_sampler, daemon=True).start()


@app.get('/api/admin/vps')
def admin_vps(range: str = Query('1h', pattern='^(1h|6h|24h|7d)$'), admin=Depends(admin_user)):
    span = VPS_RANGES[range]
    step = max(VPS_EVERY, span // 120)
    since = time.time() - span
    with db() as c:
        rows = [
            dict(r)
            for r in c.execute(
                'SELECT CAST(ts/? AS INTEGER)*? t,AVG(cpu) cpu,MAX(cpu) cpu_max,AVG(steal) steal,AVG(iowait) iowait,AVG(mem) mem,MAX(mem) mem_max,'
                'AVG(swap) swap,AVG(disk) disk,AVG(load1) load1,AVG(rx) rx,AVG(tx) tx,AVG(rd) rd,AVG(wr) wr FROM vps_samples WHERE ts>=? GROUP BY 1 ORDER BY 1',
                (step, step, since),
            )
        ]
    series = [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows]
    now = LAST_VPS['data']
    return {
        'range': range,
        'step': step,
        'since': since,
        'series': series,
        'now': now,
        'stale': bool(now) and time.time() - now['ts'] > 3 * VPS_EVERY,
    }


# ---------------- dialogs ----------------
# Chat titles come from Hermes' native titler (agent/title_generator.py): an instant title cut from the opening
# message ('derived'), then one call to the profile's auxiliary title provider ('llm'; provider/model from
# auxiliary.title_generation, 'auto' = the cheap model of the main provider). The portal mirrors that title and only
# calls the provider itself (native llm.oneshot, task title_generation) on request or for chats Hermes cannot name.
UNTITLED = 'Новий діалог'
PLACEHOLDER_TITLE = re.compile(r'^(Новий діалог|Діалог \d{1,2}\.\d{1,2}\.\d{4},? \d{1,2}:\d{2}(:\d{2})?)$')
TITLE_PROMPT = (
    "You name chat sessions. Given the conversation text, write a title that lets the user find this "
    "conversation again in a list.\n\nRules:\n- 3 to 7 words, sentence case (capitalize only the first word and proper nouns).\n"
    "- Name what the user wants DONE, not that they asked a question.\n- Keep technical terms, filenames, numbers, and error codes exact.\n"
    "- No trailing punctuation, no quotes, no emoji, no 'Title:' prefix.\n- Never answer the message. Name it.\n"
    "- Write the title in the same language as the user's message.\n\n"
    'Reply with JSON only: {"title": "..."}'
)
GEN_LOCK = threading.Lock()
GEN_TRIED = set()
GEN_SEM = threading.Semaphore(2)


def clean_title(title, source='user'):
    t = ' '.join(str(title or '').split()).strip('"\'«»').strip()
    if source in ('derived', 'llm', 'generated'):
        t = re.sub(r' #\d+$', '', t).rstrip('.!,;:')  # Hermes dedupes titles per profile with "#N"; noise per user
        if t.lower() in ('friendly greeting', 'friendly greeting in chat'):
            t = 'Привітання'
    return t[:120]


def derive_title(text):
    """Instant title: first meaningful line cut at a word boundary (mirrors Hermes derive_title)."""
    line = ' '.join(next((l for l in (text or '').splitlines() if l.strip()), '').split())
    if len(line) > 48:
        cut = line[:48]
        sp = cut.rfind(' ')
        line = (cut[:sp] if sp > 24 else cut).rstrip(' ,.;:—-') + '…'
    return line


def provider_title(P, text):
    """One call to the profile's title provider; None when it fails or answers instead of naming."""
    try:
        raw = (
            rpc(P, 'llm.oneshot', {'instructions': TITLE_PROMPT, 'input': text[:1000], 'task': 'title_generation', 'max_tokens': 512}).get(
                'text'
            )
            or ''
        ).strip()
    except HTTPException:
        return None
    raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw)
    try:
        title = json.loads(raw).get('title', '')
    except (ValueError, AttributeError):
        m = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
        title = m.group(1) if m else next((l for l in raw.splitlines() if l.strip()), '')
    title = clean_title(re.sub(r'^title:\s*', '', str(title), flags=re.I), 'generated')
    return title if title and len(title.split()) <= 12 else None


def _set_title(did, title, source, only_from=None):
    with db() as c:
        q = 'UPDATE dialogs SET title=?,title_source=? WHERE id=?' + (
            ' AND title_source IN (%s)' % ','.join('?' * len(only_from)) if only_from else ''
        )
        return c.execute(q, (title, source, did, *(only_from or ()))).rowcount > 0


def _background_title(P, did, text):
    with GEN_SEM:
        title = provider_title(P, text)
        if title:
            _set_title(did, title, 'generated', ('auto',))


def mirror_titles(user, rows):
    """Pull native titles for chats still waiting for one; chats Hermes cannot name (the dated placeholder old
    clients sent locks out its titler) get a derived title now and a provider title in the background."""
    want = [r for r in rows if r['title_source'] in ('auto', 'derived')]
    if not want:
        return rows
    try:
        native = _host_admin('session_titles', {'name': user['profile'], 'ids': [r['stored'] for r in want]})
    except HTTPException:
        return rows
    out = {r['id']: r for r in rows}
    for r in want:
        n = native.get(r['stored']) or {}
        t, s = n.get('title'), n.get('source')
        if t and (s in ('derived', 'llm') or (s == 'user' and not PLACEHOLDER_TITLE.match(t))):
            title, source = clean_title(t, s), ('user' if s == 'user' else s)
        elif n.get('first'):
            title, source = derive_title(n['first']), 'auto'
            with GEN_LOCK:
                fresh = r['id'] not in GEN_TRIED
                GEN_TRIED.add(r['id'])
            if fresh and s == 'user':
                try:
                    enforce_limits(user)
                    threading.Thread(target=_background_title, args=(user['profile'], r['id'], n['first']), daemon=True).start()
                except HTTPException:
                    pass
        else:
            continue
        if title and (title, source) != (r['title'], r['title_source']) and _set_title(r['id'], title, source, ('auto', 'derived')):
            out[r['id']] = {**r, 'title': title, 'title_source': source}
    return list(out.values())


def push_title(user, did, title):
    """Keep Hermes' own session list in step with a name chosen in the portal (best effort: titles are unique
    per profile in Hermes, a duplicate is simply not mirrored there)."""
    try:
        rpc(user['profile'], 'session.title', {'session_id': live(did, user), 'title': title})
    except HTTPException:
        pass


@app.get('/api/dialogs')
def list_dialogs(
    limit: int | None = Query(None, ge=0, le=500),
    q: str = Query('', max_length=120),
    include: str = Query('', max_length=64),
    user=Depends(current_user),
):
    """No params: every listed dialog (legacy shape, a list). With limit/q: {'items','archive_total','more','unread'};
    recent chats (last activity < 8 h) always come whole, the archive in pages of `limit` (the sidebar asks for
    more by raising it), `include` keeps the open chat listed even beyond the page, `q` searches every title."""
    # 'last' = last activity (latest turn), so the sidebar can group by recency
    with db() as c:
        rows = [
            dict(r)
            for r in c.execute(
                'SELECT d.id,d.title,d.title_source,d.stored,d.created,d.pinned,d.chat_provider,d.chat_model,d.chat_effort,COALESCE((SELECT MAX(t.created) FROM turns t WHERE t.dialog=d.id),d.created) AS last,d.unread,(SELECT j.job FROM cron_jobs j WHERE j.dialog=d.id LIMIT 1) AS job FROM dialogs d WHERE d.owner=? AND d.profile=? AND EXISTS(SELECT 1 FROM turns t WHERE t.dialog=d.id) ORDER BY last DESC',
                (user['id'], user['profile']),
            )
        ]
    out = [
        {
            'id': r['id'],
            'title': r['title'] or UNTITLED,
            'title_source': r['title_source'],
            'created': r['created'],
            'last': r['last'],
            'pinned': bool(r['pinned']),
            'unread': r['unread'],
            'job': r['job'],
            'runtime': chat_runtime(r),
        }
        for r in mirror_titles(user, rows)
    ]
    if limit is None and not q:
        return out
    unread = sum(d['unread'] or 0 for d in out if d['id'] != include)  # badge must count archived chats too
    if q.strip():
        needle = q.strip().lower()
        found = [d for d in out if needle in d['title'].lower()]
        return {'items': found[: limit or 50], 'total': len(found), 'more': len(found) > (limit or 50), 'unread': unread}
    edge = time.time() - 8 * 3600
    recent = [d for d in out if d['last'] >= edge or d['pinned']]
    archive = [d for d in out if d['last'] < edge and not d['pinned']]
    page = archive[:limit]
    if include and not any(d['id'] == include for d in recent + page):
        page += [d for d in archive if d['id'] == include]
    return {'items': recent + page, 'archive_total': len(archive), 'more': len(archive) > (limit or 0), 'unread': unread}


# ---------------- shared chats ----------------
# A share is a snapshot of the chat's visible messages taken when the link is made (later messages are not exposed
# until the owner refreshes it). Any signed-in portal user with the link can read it and copy it into their own
# profile as a new chat to continue the task, optionally compressed first (native llm.oneshot, task "compression").
with db() as c:
    c.execute(
        'CREATE TABLE IF NOT EXISTS shares(token TEXT PRIMARY KEY,dialog TEXT NOT NULL,owner TEXT NOT NULL,title TEXT,messages TEXT NOT NULL,created REAL NOT NULL,revoked REAL)'
    )
SHARE_FULL_MAX = 200_000  # characters; a bigger chat can only be copied compressed
COMPRESS_PROMPT = (
    'You condense a chat transcript between a user and an AI agent so another user can continue the same task in a new chat. '
    'Write in the language of the transcript. Keep: the goal, decisions and their reasons, facts, names, numbers, file paths, commands, code that matters, '
    'what is finished and what is still open. Drop chit-chat and repetition. Plain Markdown, at most ~1200 words. Output only the summary.'
)


def _share_row(token):
    with db() as c:
        r = c.execute(
            'SELECT s.*,u.username AS owner_name FROM shares s JOIN users u ON u.id=s.owner WHERE s.token=? AND s.revoked IS NULL', (token,)
        ).fetchone()
    if not r:
        raise HTTPException(404, 'Посилання недійсне або доступ закрито')
    return dict(r)


def _snapshot(did, user):
    msgs = rpc(user['profile'], 'session.history', {'session_id': live(did, user)}).get('messages', [])
    out = []
    for m in msgs:
        if m.get('role') not in ('user', 'assistant'):
            continue
        t = _visible_text(m).strip()
        if m.get('role') == 'user':
            t = t.split('\n--- Attached Context ---')[0].strip()
        if t:
            out.append({'role': m['role'], 'text': redact(t, user), 'timestamp': m.get('timestamp')})
    return out


@app.post('/api/dialogs/{did}/share')
def share_dialog(did: str, user=Depends(current_user)):
    """Create (or refresh the snapshot of) this chat's share link. One active link per chat."""
    d = dialog(did, user)
    msgs = _snapshot(did, user)
    if not msgs:
        raise HTTPException(400, 'У чаті ще немає повідомлень')
    with db() as c:
        r = c.execute('SELECT token FROM shares WHERE dialog=? AND revoked IS NULL', (did,)).fetchone()
        token = r['token'] if r else secrets.token_urlsafe(18)
        c.execute(
            'INSERT INTO shares(token,dialog,owner,title,messages,created) VALUES(?,?,?,?,?,?) ON CONFLICT(token) DO UPDATE SET messages=excluded.messages,title=excluded.title,created=excluded.created',
            (token, did, user['id'], d['title'] or UNTITLED, json.dumps(msgs, ensure_ascii=False), time.time()),
        )
    audit(user, 'chat.share', d['title'] or UNTITLED, {'messages': len(msgs)})
    return {'token': token, 'path': '/s/' + token, 'messages': len(msgs), 'created': time.time()}


@app.get('/api/dialogs/{did}/share')
def share_state(did: str, user=Depends(current_user)):
    dialog(did, user)
    with db() as c:
        r = c.execute('SELECT token,created,messages FROM shares WHERE dialog=? AND revoked IS NULL', (did,)).fetchone()
    return (
        {'token': r['token'], 'path': '/s/' + r['token'], 'created': r['created'], 'messages': len(json.loads(r['messages']))}
        if r
        else {'token': None}
    )


@app.delete('/api/dialogs/{did}/share')
def unshare_dialog(did: str, user=Depends(current_user)):
    d = dialog(did, user)
    with db() as c:
        n = c.execute('UPDATE shares SET revoked=? WHERE dialog=? AND revoked IS NULL', (time.time(), did)).rowcount
    if n:
        audit(user, 'chat.unshare', d['title'] or UNTITLED)
    return {'revoked': bool(n)}


@app.get('/api/shares/{token}')
def read_share(token: str = FPath(..., pattern=r'^[A-Za-z0-9_-]{16,40}$'), user=Depends(current_user)):
    r = _share_row(token)
    msgs = json.loads(r['messages'])
    chars = sum(len(m['text']) for m in msgs)
    return {
        'title': r['title'],
        'owner': r['owner_name'],
        'own': r['owner'] == user['id'],
        'created': r['created'],
        'messages': msgs,
        'chars': chars,
        'approx_tokens': chars // 3,
        'full_allowed': chars <= SHARE_FULL_MAX,
        'suggest_compress': chars > 40_000,
    }


class ShareCopy(BaseModel):
    model_config = {'extra': 'forbid'}
    compress: StrictBool = False


@app.post('/api/shares/{token}/copy')
def copy_share(body: ShareCopy, token: str = FPath(..., pattern=r'^[A-Za-z0-9_-]{16,40}$'), user=Depends(current_user)):
    """New chat in the reader's own profile seeded (native session.create `messages`) with the shared transcript or,
    with compress, with a summary made by the reader's own model."""
    r = _share_row(token)
    msgs = json.loads(r['messages'])
    P = user['profile']
    chars = sum(len(m['text']) for m in msgs)
    if not body.compress and chars > SHARE_FULL_MAX:
        raise HTTPException(413, 'Розмова завелика для повної копії: оберіть стиснення')
    enforce_limits(user)
    if body.compress:
        transcript = '\n\n'.join(('USER' if m['role'] == 'user' else 'AGENT') + ': ' + m['text'] for m in msgs)[-400_000:]
        try:
            summary = (
                rpc(
                    P,
                    'llm.oneshot',
                    {'instructions': COMPRESS_PROMPT, 'input': transcript, 'task': 'compression', 'max_tokens': 3000, 'temperature': 0.2},
                ).get('text')
                or ''
            ).strip()
        except HTTPException as exc:
            raise HTTPException(502, 'Не вдалося стиснути розмову: ' + str(exc.detail)[:200])
        if not summary:
            raise HTTPException(502, 'Модель повернула порожнє стиснення')
        seed = [
            {
                'role': 'user',
                'content': f'Ось стислий зміст розмови «{r["title"]}» (від {r["owner_name"]}). Продовжимо цю задачу.\n\n{summary}',
            },
            {'role': 'assistant', 'content': 'Зрозумів контекст. Що робимо далі?'},
        ]
    else:
        seed = [{'role': m['role'], 'content': m['text']} for m in msgs]
    did = uuid.uuid4().hex
    title = ('Копія: ' + (r['title'] or UNTITLED))[:120]
    cwd = '/srv/hermes-web' if P == 'default' else f'/root/.hermes/profiles/{P}/workspace'
    res = rpc(P, 'session.create', {'cwd': cwd, 'idempotency_key': did, 'title': title, 'messages': seed})
    with db() as c:
        c.execute(
            'INSERT INTO dialogs(id,live,stored,title,title_source,created,owner,profile) VALUES(?,?,?,?,?,?,?,?)',
            (did, res['session_id'], res['stored_session_id'], title, 'user', time.time(), user['id'], P),
        )
        # the copy has no turn yet; a settled marker turn lists it in the sidebar right away
        c.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?)', (uuid.uuid4().hex, did, 'share:copy', '', 0, 'complete', time.time()))
        c.execute("UPDATE dialogs SET seen_turn=(SELECT id FROM turns WHERE dialog=? ORDER BY created DESC LIMIT 1) WHERE id=?", (did, did))
    audit(user, 'chat.copy_shared', r['title'], {'compressed': body.compress, 'messages': len(seed)})
    return {'id': did, 'title': title, 'compressed': body.compress}


@app.get('/api/dialogs/search')
def search_dialogs(q: str = Query(..., min_length=2, max_length=120), user=Depends(current_user)):
    """Chat search: title matches (portal) + message matches from Hermes' own FTS5 index (user and agent messages,
    words, "phrases", prefix*), mapped back to this user's dialogs through the session parent chain."""
    titles = list_dialogs(limit=50, q=q, include='', user=user)['items']
    with db() as c:
        rows = [
            dict(r)
            for r in c.execute(
                'SELECT id,title,stored FROM dialogs WHERE owner=? AND profile=? AND EXISTS(SELECT 1 FROM turns t WHERE t.dialog=dialogs.id)',
                (user['id'], user['profile']),
            )
        ]
    by_stored = {r['stored']: r for r in rows if r['stored']}
    hits = []
    try:
        found = _host_admin('search', {'name': user['profile'], 'q': q, 'limit': 80}, readonly=True).get('hits', [])
    except HTTPException:
        found = []
    per = {}
    for h in found:
        d = next((by_stored[s] for s in h.get('chain', []) if s in by_stored), None)
        if not d or per.get(d['id'], 0) >= 3:
            continue
        per[d['id']] = per.get(d['id'], 0) + 1
        text = re.sub(r'\s+', ' ', h.get('snippet') or '').strip()
        if text.startswith('[cron-'):
            text = re.sub(r'^\[cron-[^\]]*\]\s*', '', text)
        hits.append(
            {'id': d['id'], 'title': d['title'] or UNTITLED, 'role': h.get('role'), 'snippet': redact(text, user)[:300], 'ts': h.get('ts')}
        )
    return {'titles': titles, 'messages': hits[:40]}


@app.get('/api/dialogs/activity')
def dialogs_activity(exclude: str = Query('', max_length=64), turns: bool = False, user=Depends(current_user)):
    """Sidebar marks for chats other than the open one: running, approval / question (agent waits for the user),
    done / error (finished since the owner last opened the chat). Live state is asked from Hermes (sync) only for
    chats whose latest turn is still running or waiting; everything else is one SQL query."""
    with db() as c:
        rows = c.execute(
            "SELECT d.id,d.seen_turn,t.id AS tid,t.state FROM dialogs d JOIN turns t ON t.id=(SELECT id FROM turns WHERE dialog=d.id ORDER BY created DESC LIMIT 1) WHERE d.owner=? AND d.profile=? AND d.id<>? AND (t.state IN ('running','waiting') OR d.seen_turn IS NULL OR d.seen_turn<>t.id) AND t.created>?",
            (user['id'], user['profile'], exclude, time.time() - 7 * 86400),
        ).fetchall()
    out = {}
    for r in rows:
        state = r['state']
        if state in ('running', 'waiting'):
            try:
                s = sync(r['id'], user=user)
                state = s['state']
            except HTTPException:
                continue
            if state == 'waiting':
                reqs = s.get('open_requests') or []
                out[r['id']] = 'approval' if reqs and reqs[0].get('method') == 'approval' else 'question'
                continue
            if state == 'running':
                out[r['id']] = 'running'
                continue
        if r['seen_turn'] != r['tid']:
            out[r['id']] = 'error' if state == 'error' else 'done' if state == 'complete' else 'stopped'
    if turns:  # `turns=1`: also the latest turn id, so a client polling slowly still sees done -> (new turn) -> done
        tid = {r['id']: r['tid'] for r in rows}
        return {k: {'status': v, 'turn': tid[k]} for k, v in out.items()}
    return out


class DialogPatch(BaseModel):
    model_config = {'extra': 'forbid'}
    title: str | None = Field(None, min_length=1, max_length=120)
    pinned: StrictBool | None = None


PIN_MAX = 20


@app.patch('/api/dialogs/{did}')
def rename_dialog(did: str, body: DialogPatch, user=Depends(current_user)):
    """Rename and/or pin. Pinned chats sit on top of the sidebar regardless of age (at most PIN_MAX per user)."""
    d = dialog(did, user)
    if body.title is None and body.pinned is None:
        raise HTTPException(400, 'Nothing to change')
    out = {'id': did}
    if body.pinned is not None:
        with db() as c:
            if (
                body.pinned
                and not d.get('pinned')
                and c.execute(
                    'SELECT COUNT(*) FROM dialogs WHERE owner=? AND profile=? AND pinned IS NOT NULL', (user['id'], user['profile'])
                ).fetchone()[0]
                >= PIN_MAX
            ):
                raise HTTPException(409, f'Можна закріпити не більше {PIN_MAX} чатів')
            c.execute('UPDATE dialogs SET pinned=? WHERE id=?', (time.time() if body.pinned else None, did))
        out['pinned'] = body.pinned
    if body.title is not None:
        title = ' '.join(body.title.split())
        if not title:
            raise HTTPException(400, 'Title is empty')
        _set_title(did, title, 'user')
        push_title(user, did, title)
        out.update(title=title, title_source='user')
    return out


@app.post('/api/dialogs/{did}/title')
def generate_dialog_title(did: str, user=Depends(current_user)):
    """Name the chat from what was asked so far, with the profile's title provider."""
    dialog(did, user)
    enforce_limits(user)
    msgs = [
        m for m in rpc(user['profile'], 'session.history', {'session_id': live(did, user)}).get('messages', []) if m.get('role') == 'user'
    ]
    texts = []
    for m in msgs:
        c = m.get('text') if isinstance(m.get('text'), str) else m.get('content')
        if isinstance(c, list):
            c = '\n'.join(x.get('text', '') for x in c if isinstance(x, dict))
        c = str(c or '').split('\n--- Attached Context ---')[0].strip()
        if c and not c.startswith(('[CONTEXT COMPACTION', '[System')):
            texts.append(c)
    if not texts:
        raise HTTPException(409, 'У чаті ще немає запитів, з яких можна скласти назву.')
    text = texts[0][:600] + ('\n\nLatest request:\n' + texts[-1][:400] if len(texts) > 1 else '')
    title = provider_title(user['profile'], text)
    if not title:
        raise HTTPException(502, 'Провайдер не зміг запропонувати назву. Спробуйте ще раз або перейменуйте вручну.')
    _set_title(did, title, 'generated')
    push_title(user, did, title)
    return {'id': did, 'title': title, 'title_source': 'generated'}


@app.delete('/api/dialogs/{did}')
def delete_dialog(did: str, user=Depends(current_user)):
    d = dialog(did, user)
    with db() as c:
        if c.execute(
            "SELECT 1 FROM turns WHERE dialog=? AND state IN ('running','waiting') AND created>?", (did, time.time() - 900)
        ).fetchone():
            raise HTTPException(409, 'The agent is still answering in this chat; stop it first')
    if d['profile'] in available_profiles():  # drop the Hermes session too; usage records stay for accounting
        for m, sid in (('session.close', d['live']), ('session.delete', d['stored'])):
            try:
                bridge(d['profile'], '/rpc', {'method': m, 'params': {'session_id': sid}})
            except HTTPException:
                pass
    folder = DATA / 'files' / did
    if folder.is_dir():
        for f in folder.iterdir():
            f.unlink()
        folder.rmdir()
    with db() as c:
        c.execute('DELETE FROM files WHERE dialog=?', (did,))
        c.execute('DELETE FROM turns WHERE dialog=?', (did,))
        c.execute('DELETE FROM usage_snap WHERE dialog=?', (did,))
        c.execute('UPDATE cron_jobs SET dialog=NULL WHERE dialog=?', (did,))  # the job stays; its next report opens a new chat
        c.execute('DELETE FROM dialogs WHERE id=?', (did,))
    audit(user, 'chat.delete', d['title'], None)
    return {'deleted': did}


class NewDialog(BaseModel):
    title: str = Field(default='', max_length=120)
    provider: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=120)
    effort: str | None = Field(default=None, max_length=10)


@app.post('/api/dialogs')
def create_dialog(body: NewDialog, user=Depends(current_user)):
    did = uuid.uuid4().hex
    P = user['profile']
    title = ' '.join(body.title.split())
    over = {}
    if body.model:
        check_chat_model(user, body.provider or '', body.model)
        over.update(model=body.model, provider=body.provider)
    if body.effort:
        check_chat_effort(user, body.effort)
        over['reasoning_effort'] = body.effort
    cwd = '/srv/hermes-web' if P == 'default' else f'/root/.hermes/profiles/{P}/workspace'
    # Only a name the user chose goes to Hermes: any title passed here is stored as the user's and would
    # lock out Hermes' own titler for this session.
    # A model/reasoning switch restarts the bridge; the first message right after it must wait, not fail.
    result = {}
    for attempt in range(16):
        try:
            result = rpc(P, 'session.create', {'cwd': cwd, 'idempotency_key': did, **over, **({'title': title} if title else {})})
            break
        except HTTPException as exc:  # only "bridge unavailable" is transient; a Hermes error (dict detail) is final
            if exc.status_code != 502 or isinstance(exc.detail, dict) or attempt == 15:
                raise
            time.sleep(2)
    rt = {'chat_provider': body.provider if body.model else None, 'chat_model': body.model or None, 'chat_effort': body.effort or None}
    with db() as c:
        c.execute(
            'INSERT INTO dialogs(id,live,stored,title,title_source,created,owner,profile,chat_provider,chat_model,chat_effort) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (
                did,
                result['session_id'],
                result['stored_session_id'],
                title or UNTITLED,
                'user' if title else 'auto',
                time.time(),
                user['id'],
                P,
                rt['chat_provider'],
                rt['chat_model'],
                rt['chat_effort'],
            ),
        )
    return {'id': did, 'title': title or UNTITLED, 'title_source': 'user' if title else 'auto', 'runtime': chat_runtime(rt)}


def _visible_text(m):
    c = m.get('text') if isinstance(m.get('text'), str) else m.get('content')
    if isinstance(c, list):
        c = '\n'.join(x.get('text', '') for x in c if isinstance(x, dict))
    return c if isinstance(c, str) else ''


_ATTACH_REF = re.compile(r'^@(file|image):(`[^`\n]+`|"[^"\n]+"|\'[^\'\n]+\'|\S+)[ \t]*$', re.M)


def _unquote_ref(v: str) -> str:
    return v[1:-1] if len(v) > 1 and v[0] == v[-1] and v[0] in '`"\'' else v


def _with_files(did: str, messages: list) -> list:
    """Give each user message the portal files it was sent with (`files`: id, name, mime, size, text preview + line
    count), so the chat shows attachment cards instead of raw `@file:` / `@image:` refs. A file is recorded at submit
    (`files.ref` = Hermes' ref, `files.sent` = time) and belongs to the user message persisted right after it; Hermes
    does not always keep an `@image:` line, so the time is the main key and the ref an exact tie-breaker. Turns from
    before `sent` existed fall back to the file name (texts) or the upload time (images). A ref whose file was deleted
    stays as a card with `missing`."""
    users = [m for m in messages if m.get('role') == 'user']
    if not users:
        return messages
    with db() as c:
        rows = [
            dict(r) for r in c.execute('SELECT id,name,mime,size,path,ref,sent,created FROM files WHERE dialog=? ORDER BY created', (did,))
        ]
    if not rows and not any('@file:' in _visible_text(m) or '@image:' in _visible_text(m) for m in users):
        return messages
    by_ref = {r['ref']: r for r in rows if r['ref']}
    used = set()
    out = {}
    for m in users:
        refs = _ATTACH_REF.findall(_visible_text(m).split('\n--- Attached Context ---')[0])
        ts = float(m.get('timestamp') or 0)
        found, missing = [], []
        for kind, raw in refs:
            r = by_ref.get(_unquote_ref(raw))
            if r is not None and r['id'] not in used:
                used.add(r['id'])
                found.append({**r, '_twin': True})
            elif r is None:
                missing.append((kind, _unquote_ref(raw)))
        if ts:  # sent with this message: recorded up to 30 s before Hermes stored it
            for x in rows:
                if x['id'] not in used and x['sent'] and ts - 30 <= x['sent'] <= ts + 5:
                    used.add(x['id'])
                    found.append(x)
        rest = []
        for kind, v in missing:
            twin = next((x for x in found if x['mime'].startswith('image/') == (kind == 'image') and not x.get('_twin')), None)
            if twin is not None:  # the ref of a file already matched by time (Hermes may format the path differently)
                twin['_twin'] = True
                continue
            r = None
            legacy = [x for x in rows if x['id'] not in used and not x['sent']]
            if kind == 'file':
                base = Path(v).name
                r = next((x for x in legacy if x['name'] == base), None) or next(
                    (
                        x
                        for x in legacy
                        if re.fullmatch(re.escape(Path(x['name']).stem) + r'-\d+' + re.escape(Path(x['name']).suffix), base)
                    ),
                    None,
                )
            else:
                older = [x for x in legacy if x['mime'].startswith('image/') and (not ts or (x['created'] or 0) <= ts + 5)]
                r = older[-1] if older else None
            if r is None:
                rest.append({'name': Path(v).name, 'mime': 'image/png' if kind == 'image' else 'text/plain', 'missing': True})
            else:
                used.add(r['id'])
                found.append(r)
        if not found and not rest:
            continue
        cards = []
        for r in sorted(found, key=lambda x: x['created'] or 0):
            card = {k: r[k] for k in ('id', 'name', 'mime', 'size')}
            if r['mime'] == 'text/plain':
                try:
                    raw = Path(r['path']).read_bytes()
                    card['preview'] = raw[:400].decode('utf-8', 'replace')
                    card['lines'] = raw.count(b'\n') + (0 if raw.endswith(b'\n') else 1)
                except OSError:
                    card['missing'] = True
            elif not Path(r['path']).exists():
                card['missing'] = True
            cards.append(card)
        out[id(m)] = cards + rest
    return [_short_user(m, out[id(m)]) if id(m) in out else m for m in messages]


def _short_user(m: dict, cards: list) -> dict:
    """User message with its attachment cards, minus the inlined `--- Attached Context ---` copy of the files (the
    cards carry a preview, so polls stop re-sending whole pasted texts)."""
    m = {**m, 'files': cards}
    for k in ('text', 'content'):
        if isinstance(m.get(k), str):
            m[k] = m[k].split('\n--- Attached Context ---')[0]
    return m


@app.get('/api/dialogs/{did}/history')
def history(did: str, request: Request, tail: int | None = Query(None, ge=1, le=5000), user=Depends(current_user)):
    """`tail`: only the last N chat-visible messages (user/assistant with text), widened back to a user message so a
    turn is never cut in half; the client loads older ones by asking for a larger tail. No tail: everything."""
    result = rpc(user['profile'], 'session.history', {'session_id': live(did, user)})
    with db() as c:
        c.execute('UPDATE dialogs SET unread=0 WHERE id=? AND unread>0', (did,))  # reading the chat reads its reports
        c.execute(
            "UPDATE dialogs SET seen_turn=(SELECT t.id FROM turns t WHERE t.dialog=dialogs.id ORDER BY t.created DESC LIMIT 1) WHERE id=? AND EXISTS(SELECT 1 FROM turns t WHERE t.dialog=dialogs.id AND t.state NOT IN ('running','waiting') AND t.created=(SELECT MAX(created) FROM turns WHERE dialog=dialogs.id))",
            (did,),
        )
    if tail is None:
        return {**result, 'hermes_row_count': result['count'], 'count': len(result.get('messages', []))}
    visible = [m for m in result.get('messages', []) if m.get('role') in ('user', 'assistant') and _visible_text(m).strip()]
    start = max(0, len(visible) - tail)
    while start > 0 and visible[start].get('role') != 'user':
        start -= 1
    return _etagged(
        request,
        {
            'messages': _with_files(did, visible[start:]),
            'total': len(visible),
            'start': start,
            'more': start > 0,
            'hermes_row_count': result['count'],
            'count': len(visible) - start,
        },
    )


def _etagged(request: Request, body: dict):
    """Polling mostly gets the same history: answer 304 to a matching If-None-Match (the browser cache revalidates
    on its own because of no-cache) so only changed histories cross the wire. nginx gzip weakens the tag (W/)."""
    raw = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
    tag = '"' + hashlib.sha1(raw).hexdigest()[:20] + '"'
    sent = [t.strip().removeprefix('W/') for t in request.headers.get('if-none-match', '').split(',')]
    headers = {'ETag': tag, 'Cache-Control': 'private, no-cache'}
    if tag in sent:
        return Response(status_code=304, headers=headers)
    return Response(content=raw, media_type='application/json', headers=headers)


@app.get('/api/dialogs/{did}/status')
def status(did: str, user=Depends(current_user)):
    return rpc(user['profile'], 'session.status', {'session_id': live(did, user)})


@app.post('/api/dialogs/{did}/stop')
def stop(did: str, user=Depends(current_user)):
    return rpc(user['profile'], 'session.interrupt', {'session_id': live(did, user)})


@app.post('/api/dialogs/{did}/files')
async def upload(did: str, file: UploadFile = File(...), user=Depends(current_user)):
    dialog(did, user)
    raw = await file.read(10 * 1024 * 1024 + 1)
    await file.close()
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, 'File must be 1 byte–10 MiB')
    original = file.filename or 'attachment.txt'
    if '/' in original or '\\' in original or '..' in original or len(original) > 160:
        raise HTTPException(400, 'Unsafe filename')
    name = re.sub(r'[^A-Za-z0-9._-]', '_', original)
    ext = Path(name).suffix.lower()
    mime = file.content_type or ''
    if ext in ('.txt', '.md', '.csv', '.json', '.log'):
        if mime not in ('text/plain', 'text/markdown', 'text/csv', 'application/json', 'application/octet-stream'):
            raise HTTPException(415, 'Text MIME mismatch')
        if len(raw) > 2 * 1024 * 1024:
            raise HTTPException(413, 'Text limit: 2 MiB')
        try:
            raw.decode('utf-8')
        except UnicodeDecodeError:
            raise HTTPException(415, 'Text must be UTF-8')
        if b'\0' in raw:
            raise HTTPException(415, 'Binary content rejected')
        mime = 'text/plain'
    elif ext in ('.png', '.jpg', '.jpeg', '.webp'):
        expected = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}[ext]
        if mime != expected:
            raise HTTPException(415, 'Image MIME mismatch')
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('PNG', 'JPEG', 'WEBP') or image.width * image.height > 20_000_000:
                    raise ValueError()
                actual = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}[image.format]
                if actual != mime:
                    raise ValueError()
                image.verify()
        except Exception:
            raise HTTPException(415, 'Invalid image or >20 megapixels')
    else:
        raise HTTPException(415, 'Allowed: UTF-8 text, PNG, JPEG, WebP')
    fid = uuid.uuid4().hex
    folder = DATA / 'files' / did
    folder.mkdir(parents=True, exist_ok=True)
    quota = 512 * 1024 * 1024 if user['role'] == 'admin' else 256 * 1024 * 1024
    with db() as c:
        used = c.execute(
            'SELECT COALESCE(SUM(f.size),0) FROM files f JOIN dialogs d ON d.id=f.dialog WHERE d.owner=?', (user['id'],)
        ).fetchone()[0]
        if used + len(raw) > quota:
            raise HTTPException(413, 'Storage quota reached')
        path = folder / (fid + ext)
        path.write_bytes(raw)
        c.execute(
            'INSERT INTO files(id,dialog,name,mime,path,size,created) VALUES(?,?,?,?,?,?,?)',
            (fid, did, name, mime, str(path), len(raw), time.time()),
        )
    return {'id': fid, 'name': name, 'mime': mime, 'size': len(raw)}


# ---- artifacts: every file a user attached (clipboard image, pasted long text, upload), across dialogs ----
with db() as c:
    if 'created' not in [r[1] for r in c.execute('PRAGMA table_info(files)')]:
        c.execute('ALTER TABLE files ADD COLUMN created REAL')
    if 'ref' not in [r[1] for r in c.execute('PRAGMA table_info(files)')]:
        c.execute('ALTER TABLE files ADD COLUMN ref TEXT')  # Hermes' @file:/@image: value, maps history refs back to the file
    if 'sent' not in [r[1] for r in c.execute('PRAGMA table_info(files)')]:
        c.execute('ALTER TABLE files ADD COLUMN sent REAL')  # when it went out with a turn: ties it to that user message


def own_file(fid, user):
    with db() as c:
        row = c.execute(
            'SELECT f.*,d.title,d.id AS did FROM files f JOIN dialogs d ON d.id=f.dialog WHERE f.id=? AND d.owner=? AND d.profile=?',
            (fid, user['id'], user['profile']),
        ).fetchone()
    if row is None:
        raise HTTPException(404, 'File not found')
    return dict(row)


@app.get('/api/me/files')
def my_files(user=Depends(current_user)):
    with db() as c:
        rows = c.execute(
            'SELECT f.id,f.name,f.mime,f.size,f.created,f.path,d.id AS dialog,d.title FROM files f JOIN dialogs d ON d.id=f.dialog WHERE d.owner=? AND d.profile=? ORDER BY COALESCE(f.created,d.created) DESC',
            (user['id'], user['profile']),
        ).fetchall()
    out = []
    for r in rows:
        x = {k: r[k] for k in ('id', 'name', 'mime', 'size', 'created', 'dialog', 'title')}
        if r['mime'] == 'text/plain':
            try:
                x['preview'] = Path(r['path']).read_bytes()[:600].decode('utf-8', 'replace')
            except OSError:
                x['preview'] = ''
        out.append(x)
    return out


@app.get('/api/me/files/{fid}')
def my_file(fid: str, download: int = 0, user=Depends(current_user)):
    f = own_file(fid, user)
    try:
        data = Path(f['path']).read_bytes()
    except OSError:
        raise HTTPException(404, 'File missing on disk')
    mime = f['mime'] if f['mime'] in ('image/png', 'image/jpeg', 'image/webp') else 'text/plain; charset=utf-8'
    disp = ('attachment' if download or not f['mime'].startswith('image/') else 'inline') + '; filename="' + f['name'] + '"'
    return Response(
        data,
        media_type=mime,
        headers={'Content-Disposition': disp, 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'private, max-age=3600'},
    )


@app.delete('/api/me/files/{fid}')
def my_file_delete(fid: str, user=Depends(current_user)):
    f = own_file(fid, user)
    try:
        Path(f['path']).unlink()
    except OSError:
        pass
    with db() as c:
        c.execute('DELETE FROM files WHERE id=?', (fid,))
    return {'deleted': fid}


class Prompt(BaseModel):
    text: str = Field(max_length=32000)
    files: list[str] = Field(default_factory=list, max_length=5)
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r'^[A-Za-z0-9_-]{16,80}$')
    # Edit / regenerate = native Hermes rewind: drop the history from this user row on and submit `text` in its place.
    rewind_row_id: int | None = Field(None, ge=1)
    rewind: str | None = Field(None, pattern=r'^(edit|retry)$')


@app.post('/api/dialogs/{did}/chat')
def chat(did: str, body: Prompt, user=Depends(current_user)):
    dialog(did, user)
    P = user['profile']
    if not body.text.strip() and not body.files:
        raise HTTPException(400, 'Empty prompt')
    if (body.rewind is None) != (body.rewind_row_id is None):
        raise HTTPException(400, 'rewind and rewind_row_id go together')
    if body.rewind and not allowed(user, 'cmd:' + ('retry' if body.rewind == 'retry' else 'undo')):
        audit(user, 'command.denied', '/' + body.rewind)
        raise HTTPException(403, 'Немає дозволу змінювати історію чату')
    enforce_limits(user)
    fingerprint = hashlib.sha256(
        json.dumps({'text': body.text, 'files': body.files, 'rewind': body.rewind_row_id}, sort_keys=True).encode()
    ).hexdigest()
    with LOCK:
        with db() as c:
            prior = c.execute('SELECT * FROM turns WHERE id=?', (body.request_id,)).fetchone()
        if prior:
            if prior['dialog'] != did or prior['fingerprint'] != fingerprint:
                raise HTTPException(409, 'Request ID reused with different input')
            return {'dialog': did, 'request_id': body.request_id, 'duplicate': True, 'state': prior['state']}
        if P in BUSY:
            raise HTTPException(409, 'One running turn at a time per profile')
        BUSY.add(P)
    try:
        with db() as c:
            others = [
                r[0]
                for r in c.execute(
                    "SELECT DISTINCT t.dialog FROM turns t JOIN dialogs d ON d.id=t.dialog WHERE t.state IN ('running','waiting') AND t.dialog<>? AND d.owner=? AND d.profile=?",
                    (did, user['id'], P),
                )
            ]
        for other in others:
            if sync(other, user=user)['state'] in ('running', 'waiting'):
                busy_title = dialog(other, user)['title'] or UNTITLED
                raise HTTPException(
                    409, f'Агент зараз працює в чаті «{busy_title}». Дочекайтеся завершення або зупиніть його там, тоді надсилайте тут.'
                )
        sid = ''
        for attempt in range(16):  # bridge may be restarting after a model/reasoning switch
            try:
                sid = live(did, user)
                break
            except HTTPException as exc:
                if exc.status_code != 502 or isinstance(exc.detail, dict) or attempt == 15:
                    raise
                time.sleep(2)
        state = rpc(P, 'session.status', {'session_id': sid})
        if 'Agent Running: Yes' in state.get('output', ''):
            raise HTTPException(409, 'Hermes session already running; reconnect or stop it')
        with db() as c:
            files = []
            for fid in dict.fromkeys(body.files):
                f = c.execute('SELECT * FROM files WHERE id=? AND dialog=?', (fid, did)).fetchone()
                if not f:
                    raise HTTPException(404, 'Attachment not in this dialog')
                files.append(dict(f))
        snapshot = bridge(P, '/events', {'session_id': sid})
        cursor = snapshot['cursor']
        with db() as c:
            c.execute(
                'INSERT INTO turns VALUES(?,?,?,?,?,?,?)',
                (body.request_id, did, fingerprint, snapshot['epoch'], cursor, 'running', time.time()),
            )
        refs = []
        for f in files:
            encoded = base64.b64encode(Path(f['path']).read_bytes()).decode()
            if f['mime'].startswith('image/'):
                result = rpc(P, 'image.attach_bytes', {'session_id': sid, 'filename': f['name'], 'content_base64': encoded})
                ref = result.get('path') or ''
            else:
                result = rpc(P, 'file.attach', {'session_id': sid, 'name': f['name'], 'data_url': 'data:text/plain;base64,' + encoded})
                refs.append(result['ref_text'])
                ref = _unquote_ref(result['ref_text'].removeprefix('@file:'))
            with db() as c:
                c.execute('UPDATE files SET ref=?, sent=? WHERE id=?', (ref or None, time.time(), f['id']))
        params = {'session_id': sid, 'text': body.text + '\n' + '\n'.join(refs)}
        if body.rewind_row_id:
            params.update(
                truncate_before_row_id=body.rewind_row_id, confirm_truncate=True, confirm_empty_truncate=True
            )  # editing the first message empties the transcript on purpose
        try:
            rpc(P, 'prompt.submit', params)
        except HTTPException as exc:
            if body.rewind_row_id:  # the rewind never started: drop the turn row so the chat is not left 'running'
                with db() as c:
                    c.execute('DELETE FROM turns WHERE id=?', (body.request_id,))
                if isinstance(exc.detail, dict) and exc.detail.get('hermes', {}).get('code') in (4018, 4030, 4004, 4029, 4028):
                    raise HTTPException(409, 'Це повідомлення вже змінилося або стиснуте в памʼяті агента. Оновіть чат і спробуйте ще раз.')
            raise
        audit(user, 'chat.turn', P, {'attachments': len(files), **({'rewind': body.rewind} if body.rewind else {})})
    finally:
        with LOCK:
            BUSY.discard(P)
    return {'dialog': did, 'request_id': body.request_id, 'duplicate': False, 'cursor': cursor, 'epoch': snapshot['epoch']}


@app.get('/api/dialogs/{did}/sync')
def sync(did: str, after: int = 0, epoch: str = '', user=Depends(current_user)):
    P = user['profile']
    sid = live(did, user)
    native = rpc(P, 'session.status', {'session_id': sid})
    snapshot = bridge(P, '/events', {'session_id': sid, 'after': after})
    reset = bool(epoch and epoch != snapshot['epoch']) or snapshot['truncated']
    if reset:
        snapshot = bridge(P, '/events', {'session_id': sid, 'after': 0})
    running = 'Agent Running: Yes' in native.get('output', '')
    with db() as c:
        turn = c.execute('SELECT * FROM turns WHERE dialog=? ORDER BY created DESC LIMIT 1', (did,)).fetchone()
    state = 'waiting' if snapshot['open_requests'] else 'running' if running else 'complete'
    if not running and turn:
        if turn['epoch'] != snapshot['epoch'] and turn['state'] in ('running', 'waiting'):
            state = 'interrupted'
        elif snapshot['outcome'] in ('interrupted', 'error'):
            state = snapshot['outcome']
        elif snapshot['outcome']:
            state = 'complete'
        elif turn['state'] in ('interrupted', 'error'):
            state = turn['state']
        elif turn['state'] in ('running', 'waiting'):
            state = 'interrupted'
    if turn:
        settled = turn['state'] in ('running', 'waiting') and state in ('complete', 'interrupted', 'error')
        with db() as c:
            c.execute('UPDATE turns SET state=? WHERE id=?', (state, turn['id']))
        if settled:
            record_usage(dialog(did, user))
    # Hermes renames the session live (instant title at turn start, provider title a moment later).
    named = [
        e['payload']['title']
        for e in snapshot['events']
        if e.get('type') == 'session.title' and isinstance(e.get('payload'), dict) and e['payload'].get('title')
    ]
    if named:
        _set_title(did, clean_title(named[-1], 'derived'), 'derived', ('auto', 'derived', 'llm'))
    title = dialog(did, user)['title'] or UNTITLED
    safe_types = {
        'message.start',
        'message.delta',
        'message.complete',
        'tool.start',
        'tool.complete',
        'status.update',
        'request.cancel',
        'btw.complete',
        'background.complete',
    }
    return {
        **snapshot,
        'events': [e for e in snapshot['events'] if e.get('type') in safe_types],
        'state': state,
        'reset': reset,
        'title': title,
        'request_id': turn['id'] if turn else None,
        'activity_since': turn['cursor'] if turn and turn['epoch'] == snapshot['epoch'] else 0,
        'started_at': turn['created'] if turn else None,
    }


class Side(BaseModel):
    model_config = {'extra': 'forbid'}
    mode: str = Field(pattern=r'^(steer|bg|btw)$')
    text: str = Field(min_length=1, max_length=4000)


@app.post('/api/dialogs/{did}/side')
def side(did: str, body: Side, user=Depends(current_user)):
    """Composer actions while a turn runs, all native Hermes: steer = session.steer (lands after the next tool
    call, no interrupt), bg = prompt.background (separate side session, answer as background.complete),
    btw = prompt.btw (side question over a snapshot, answer as btw.complete). Queueing is client-side."""
    dialog(did, user)
    P = user['profile']
    if not allowed(user, 'cmd:' + body.mode):
        audit(user, 'command.denied', '/' + body.mode)
        raise HTTPException(403, f'No permission for /{body.mode}')
    text = body.text.strip()
    if not text:
        raise HTTPException(400, 'Empty text')
    if body.mode != 'steer':
        enforce_limits(user)
    sid = live(did, user)
    audit(user, 'command.run', '/' + body.mode)
    if body.mode == 'steer':
        r = rpc(P, 'session.steer', {'session_id': sid, 'text': text})
        return {'status': r.get('status', 'rejected')}  # 'rejected' = agent idle: the client queues it instead
    r = rpc(P, 'prompt.background' if body.mode == 'bg' else 'prompt.btw', {'session_id': sid, 'text': text})
    return {'status': 'started', 'task_id': r.get('task_id', '')}


class Answer(BaseModel):
    model_config = {'extra': 'forbid'}
    result: dict


@app.post('/api/dialogs/{did}/requests/{request_id}/respond')
def respond(did: str, request_id: str, body: Answer, user=Depends(current_user)):
    P = user['profile']
    sid = live(did, user)
    native = rpc(P, 'session.events.since', {'session_id': sid, 'last_seen': 0})
    if not any(r['id'] == request_id and r.get('params', {}).get('session_id') == sid for r in native.get('open_requests', [])):
        raise HTTPException(409, 'Request expired or already settled')
    return bridge(P, '/respond', {'session_id': sid, 'request_id': request_id, 'result': body.result})


# ---------------- scheduled jobs (native Hermes cron) ----------------
# Hermes owns scheduling and execution (the host gateway's ticker fires every profile's jobs). The portal lists and
# manages each user's jobs, enforces the owner's policy for user profiles, accounts the runs' cost and delivers each
# report into the job's own chat as a mirrored transcript row, so the user can reply and the agent sees the report.
CRON_MAX_JOBS = 5
CRON_MIN_MINUTES = 60
CRON_FORBIDDEN = ('script', 'no_agent', 'monitor_script', 'monitor_url', 'workdir')  # host-side code/paths, not for user profiles
CRON_LOCK = threading.Lock()
CRON_GAPS = {}
CRON_TOOL = {}
REPORT_RE = re.compile(r'^\[cron-(report|notice) job=([a-f0-9]{6,40})[^\]\n]*\]')
with db() as c:
    if not c.execute("SELECT 1 FROM settings WHERE key='cron_since'").fetchone():
        c.execute("INSERT INTO settings(key,value) VALUES('cron_since',?)", (str(time.time()),))
CRON_SINCE = float(setting('cron_since', '0'))


def _iso(ts):
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(ts).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return 0.0


def profile_users(P):
    with db() as c:
        return [dict(r) for r in c.execute('SELECT * FROM users WHERE profile=? AND blocked=0', (P,))]


def cron_restricted(P):
    """Owner policy applies to profiles used only by role:user accounts; admins' profiles are unrestricted."""
    us = profile_users(P)
    return bool(us) and all(u['role'] == 'user' for u in us)


def cron_allowed_for(P):
    us = profile_users(P)
    return bool(us) and all(allowed(u, 'feature:cron') for u in us)


def require_cron(user):
    if not allowed(user, 'feature:cron'):
        raise HTTPException(403, 'Заплановані завдання вимкнені для вашого облікового запису')
    return user


def cron_gap(P, schedule):
    key = json.dumps(schedule, sort_keys=True)
    if key not in CRON_GAPS:
        try:
            CRON_GAPS[key] = _host_admin('cron_gap', {'name': P, 'schedule': schedule}).get('minutes')
        except HTTPException as exc:
            raise HTTPException(400, 'Не вдалося розібрати розклад: ' + str(exc.detail)[:200])
    return CRON_GAPS[key]


def cron_over_limit(P):
    since = month_start()
    for u in profile_users(P):
        for subject, field, value in (('user:' + u['id'], 'user', u['id']), ('profile:' + P, 'profile', P)):
            lim = limit_of(subject)
            if lim is not None and spent(field, value, since) >= lim:
                return True
    return False


def cron_violation(P, job, cli_tools=None):
    """Why a user-profile job may not run under the owner's policy (None = fine). Count is checked separately."""
    if not cron_allowed_for(P):
        return 'Заплановані завдання вимкнені адміністратором'
    if any(job.get(k) for k in CRON_FORBIDDEN):
        return 'Завдання використовує скрипт, монітор або робочу теку; це недоступно у вашому профілі'
    if cli_tools is not None and job.get('enabled_toolsets') and not set(job['enabled_toolsets']) <= set(cli_tools):
        return 'Завдання просить інструменти, яких немає у вашому профілі'
    g = cron_gap(P, job['schedule']) if job.get('schedule') else None
    if g is not None and g < CRON_MIN_MINUTES:
        return f'Розклад частіший, ніж раз на годину ({job.get("schedule_display") or ""})'
    if cron_over_limit(P):
        return 'Місячний ліміт витрат вичерпано'
    return None


def cron_tool_sync(P, force=False):
    """Agent's cronjob toolset follows feature:cron. Toolsets load at bridge start, so a change restarts the bridge
    (only while the profile is idle; otherwise the next reconcile retries)."""
    if P == 'default' or P not in available_profiles():
        return None
    want = cron_allowed_for(P)
    if not force and CRON_TOOL.get(P) == want:
        return want
    if busy_profile(P):
        return CRON_TOOL.get(P)
    r = _host_admin('cron_tool', {'name': P, 'enabled': want})
    if r['changed']:
        _host_admin('bridge', {'name': P, 'action': 'restart'})
        wait_bridge(P)
        audit(None, 'cron.tool', P, {'enabled': want})
    CRON_TOOL[P] = want
    CRON_TOOL[P + ':tools'] = r['cli_enabled']
    return want


def cron_notice_owner(P):
    us = profile_users(P)
    if P == 'default':
        us = [u for u in us if u['role'] == 'admin']
    return us[0] if us else None


def cron_new_dialog(P, owner, name):
    """A chat for a job that has none (created outside the portal, or its chat was deleted)."""
    cwd = '/srv/hermes-web' if P == 'default' else f'/root/.hermes/profiles/{P}/workspace'
    did = uuid.uuid4().hex
    title = ('Завдання: ' + name)[:120]
    r = rpc(P, 'session.create', {'cwd': cwd, 'idempotency_key': did, 'title': title})
    with db() as c:
        c.execute(
            'INSERT INTO dialogs(id,live,stored,title,title_source,created,owner,profile) VALUES(?,?,?,?,?,?,?,?)',
            (did, r['session_id'], r['stored_session_id'], title, 'user', time.time(), owner['id'], P),
        )
    return did


def cron_deliver(P, did, text):
    """Append to the chat's Hermes transcript (native mirror) and mark it as activity + unread."""
    with db() as c:
        d = c.execute('SELECT * FROM dialogs WHERE id=?', (did,)).fetchone()
        if not d:
            return False
        if c.execute(
            "SELECT 1 FROM turns WHERE dialog=? AND state IN ('running','waiting') AND created>?", (did, time.time() - 900)
        ).fetchone():
            return False  # never write under a running turn; retry later
    _host_admin('cron_mirror', {'name': P, 'stored': d['stored'], 'text': text})
    snap = bridge(P, '/events', {'session_id': '-', 'after': 10**12})  # cursor/epoch only: the report itself has no live events
    with db() as c:
        c.execute(
            'INSERT INTO turns VALUES(?,?,?,?,?,?,?)',
            ('cron-' + uuid.uuid4().hex, did, '', snap['epoch'], snap['cursor'], 'complete', time.time()),
        )
        c.execute('UPDATE dialogs SET unread=unread+1 WHERE id=?', (did,))
    return True


def cron_record_usage(P, jid, did):
    try:
        rows = _host_admin('cron_sessions', {'name': P, 'job': jid})
    except HTTPException:
        return
    owner = cron_notice_owner(P)
    own = None
    for t in rows:
        key = 'cron:' + t['id']
        with USAGE_LOCK, db() as c:
            prev = c.execute('SELECT * FROM usage_snap WHERE dialog=?', (key,)).fetchone()
            delta = {k: t[k] - (prev[k] if prev else 0) for k in ('input', 'output', 'cache_read', 'cache_write', 'cost')}
            if any(v > 0 for v in delta.values()):
                if own is None:
                    own = own_providers(P)
                is_own = int(bool(t.get('providers')) and all(p in own for p in t['providers'].split(',')))
                c.execute(
                    'INSERT INTO usage(ts,user,profile,dialog,input,output,cache_read,cache_write,cost,models,own) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (
                        time.time(),
                        owner['id'] if owner else None,
                        P,
                        did or key,
                        delta['input'],
                        delta['output'],
                        delta['cache_read'],
                        delta['cache_write'],
                        round(delta['cost'], 6),
                        t['models'],
                        is_own,
                    ),
                )
            c.execute(
                'INSERT INTO usage_snap VALUES(?,?,?,?,?,?) ON CONFLICT(dialog) DO UPDATE SET input=excluded.input,output=excluded.output,cache_read=excluded.cache_read,cache_write=excluded.cache_write,cost=excluded.cost',
                (key, t['input'], t['output'], t['cache_read'], t['cache_write'], t['cost']),
            )


def _link_dialog(P, job):
    """The chat a job was created from: the latest turn in this profile that started before the job (agent tool call)."""
    created = _iso(job.get('created_at'))
    if created < CRON_SINCE:
        return None
    with db() as c:
        r = c.execute(
            'SELECT t.dialog FROM turns t JOIN dialogs d ON d.id=t.dialog WHERE d.profile=? AND t.created<=? AND t.created>? ORDER BY t.created DESC LIMIT 1',
            (P, created + 1, created - 3600),
        ).fetchone()
    return r['dialog'] if r else None


def cron_reconcile(P, tool_sync=True):
    with CRON_LOCK:
        listing = _host_admin('cron_list', {'name': P})
        jobs = listing['jobs']
        restricted = cron_restricted(P)
        if restricted and tool_sync:
            cron_tool_sync(P)
        with db() as c:
            known = {r['job']: dict(r) for r in c.execute('SELECT * FROM cron_jobs WHERE profile=?', (P,))}
        for j in jobs:
            if j['id'] not in known:
                fresh = _iso(j.get('created_at')) >= CRON_SINCE
                row = {
                    'profile': P,
                    'job': j['id'],
                    'dialog': _link_dialog(P, j),
                    'seen': '' if fresh else (j['runs'][0] if j['runs'] else ''),
                    'note': None,
                    'created': time.time(),
                }
                with db() as c:
                    c.execute('INSERT OR IGNORE INTO cron_jobs VALUES(?,?,?,?,?,?)', tuple(row.values()))
                known[j['id']] = row
        ids = {j['id'] for j in jobs}
        with db() as c:
            for gone in [k for k in known if k not in ids]:
                c.execute('DELETE FROM cron_jobs WHERE profile=? AND job=?', (P, gone))
                known.pop(gone)
        if restricted:
            tools = CRON_TOOL.get(P + ':tools')
            active = [j for j in jobs if j.get('enabled')]
            for j in sorted(active, key=lambda x: x.get('created_at') or ''):
                reason = cron_violation(P, j, tools)
                if (
                    not reason
                    and sum(1 for x in active if x.get('enabled') and (x.get('created_at') or '') < (j.get('created_at') or ''))
                    >= CRON_MAX_JOBS
                ):
                    reason = f'Більше ніж {CRON_MAX_JOBS} активних завдань'
                if reason:
                    _host_admin('cron_action', {'name': P, 'job': j['id'], 'action': 'pause'})
                    j['enabled'] = False
                    with db() as c:
                        c.execute('UPDATE cron_jobs SET note=? WHERE profile=? AND job=?', (reason, P, j['id']))
                    audit(None, 'cron.policy_pause', P, {'job': j['id'], 'reason': reason})
                    if known[j['id']]['dialog']:
                        cron_deliver(
                            P, known[j['id']]['dialog'], f'[cron-notice job={j["id"]}] Завдання «{j.get("name")}» призупинено: {reason}.'
                        )
                elif (j.get('deliver') or 'local') != 'local':
                    _host_admin(
                        'cron_edit', {'name': P, 'job': j['id'], 'fields': {'deliver': 'local'}}
                    )  # reports go to the portal, never a home channel
        for j in jobs:
            k = known[j['id']]
            new = [f for f in j['runs'] if f > k['seen']]
            if not new:
                continue
            cron_record_usage(P, j['id'], k['dialog'])
            did = k['dialog']
            for f in sorted(new):
                rep = _host_admin('cron_report', {'name': P, 'job': j['id'], 'file': f})
                if rep.get('answer') or rep.get('failed'):
                    if not did:
                        owner = cron_notice_owner(P)
                        if not owner or (j.get('deliver') or 'local') != 'local':  # jobs delivered to other platforms are not mirrored
                            with db() as c:
                                c.execute('UPDATE cron_jobs SET seen=? WHERE profile=? AND job=?', (f, P, j['id']))
                            continue
                        did = cron_new_dialog(P, owner, j.get('name') or j['id'])
                        with db() as c:
                            c.execute('UPDATE cron_jobs SET dialog=? WHERE profile=? AND job=?', (did, P, j['id']))
                    stamp = f[:10] + ' ' + f[11:16].replace('-', ':')
                    body = (
                        rep['answer']
                        if rep.get('answer')
                        else 'Запуск завершився помилкою. Деталі у списку завдань; спробуйте «Запустити зараз» або змініть текст завдання.'
                    )
                    head = f'[cron-report job={j["id"]} at={stamp} UTC{" failed" if rep.get("failed") and not rep.get("answer") else ""}] Звіт запланованого завдання «{j.get("name")}» (автоматичне повідомлення, не від користувача).'
                    if not cron_deliver(P, did, head + '\n\n' + body):
                        break  # chat busy: keep the rest for the next pass
                with db() as c:
                    c.execute('UPDATE cron_jobs SET seen=? WHERE profile=? AND job=?', (f, P, j['id']))
        return listing


def cron_reconciler():
    time.sleep(20)
    while True:
        try:
            with db() as c:
                profiles = sorted({r['profile'] for r in c.execute('SELECT profile FROM users WHERE blocked=0')})
            live = set(available_profiles())
            for P in profiles:
                if P in live:
                    try:
                        cron_reconcile(P)
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(30)


threading.Thread(target=cron_reconciler, daemon=True).start()


def cron_view(P, listing):
    with db() as c:
        known = {r['job']: dict(r) for r in c.execute('SELECT * FROM cron_jobs WHERE profile=?', (P,))}
    with db() as c:
        unread = {r['id']: r['unread'] for r in c.execute('SELECT id,unread FROM dialogs WHERE profile=?', (P,))}
    out = []
    for j in listing['jobs']:
        k = known.get(j['id'], {})
        out.append(
            {
                'id': j['id'],
                'name': j.get('name') or j['id'],
                'prompt': j.get('prompt') or '',
                'schedule': j.get('schedule_display') or '',
                'enabled': bool(j.get('enabled')),
                'state': j.get('state'),
                'next_run_at': j.get('next_run_at'),
                'last_run_at': j.get('last_run_at'),
                'last_status': j.get('last_status'),
                'last_error': bool(j.get('last_error')),
                'created_at': j.get('created_at'),
                'repeat': j.get('repeat'),
                'dialog': k.get('dialog'),
                'unread': unread.get(k.get('dialog'), 0),
                'note': k.get('note') if not j.get('enabled') else None,
                'runs': j['runs'][:10],
            }
        )
    return out


def cron_limits(user):
    return {'max_jobs': CRON_MAX_JOBS, 'min_minutes': CRON_MIN_MINUTES} if cron_restricted(user['profile']) else None


@app.get('/api/cron')
def cron_list_api(user=Depends(current_user)):
    require_cron(user)
    P = user['profile']
    try:
        listing = cron_reconcile(P, tool_sync=False)
    except HTTPException:
        listing = _host_admin('cron_list', {'name': P})
    age = listing.get('ticker_age')
    return {
        'jobs': cron_view(P, listing),
        'limits': cron_limits(user),
        'scheduler_ok': age is not None and age < 300,
        'agent_ready': P == 'default' or CRON_TOOL.get(P) is True,
    }


@app.post('/api/cron/prepare')
def cron_prepare(user=Depends(current_user)):
    """Before asking Hermes to schedule something: make sure the agent has its cronjob tool and the user has room."""
    require_cron(user)
    P = user['profile']
    if cron_restricted(P):
        listing = _host_admin('cron_list', {'name': P})
        if sum(1 for j in listing['jobs'] if j.get('enabled')) >= CRON_MAX_JOBS:
            raise HTTPException(409, f'Уже {CRON_MAX_JOBS} активних завдань. Призупиніть або видаліть одне з них.')
        if cron_over_limit(P):
            raise HTTPException(429, 'Місячний ліміт витрат вичерпано')
        if cron_tool_sync(P, force=CRON_TOOL.get(P) is not True) is not True:
            raise HTTPException(409, 'Агент зараз відповідає в іншому чаті. Спробуйте за хвилину.')
    return {'ready': True}


def _cron_job(user, jid):
    if not re.fullmatch(r'[a-f0-9]{6,40}', jid):
        raise HTTPException(404, 'No such job')
    for j in _host_admin('cron_list', {'name': user['profile']})['jobs']:
        if j['id'] == jid:
            return j
    raise HTTPException(404, 'No such job')


class CronEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    schedule: str | None = Field(default=None, min_length=1, max_length=120)
    prompt: str | None = Field(default=None, min_length=1, max_length=8000)


@app.patch('/api/cron/{jid}')
def cron_edit_api(jid: str, body: CronEdit, user=Depends(current_user)):
    require_cron(user)
    P = user['profile']
    _cron_job(user, jid)
    fields = {k: (' '.join(v.split()) if k != 'prompt' else v.strip()) for k, v in body.model_dump().items() if v is not None}
    if 'schedule' in fields:
        g = cron_gap(P, fields['schedule'])
        if cron_restricted(P) and g is not None and g < CRON_MIN_MINUTES:
            raise HTTPException(400, 'Розклад не може бути частішим, ніж раз на годину')
    try:
        r = _host_admin('cron_edit', {'name': P, 'job': jid, 'fields': fields})
    except HTTPException as exc:
        raise HTTPException(400, 'Hermes не прийняв зміну: ' + str(exc.detail)[:300])
    audit(user, 'cron.edit', P, {'job': jid, 'fields': sorted(fields)})
    return {'job': r}


class CronAction(BaseModel):
    action: str = Field(pattern=r'^(pause|resume|run)$')


@app.post('/api/cron/{jid}/action')
def cron_action_api(jid: str, body: CronAction, user=Depends(current_user)):
    require_cron(user)
    P = user['profile']
    j = _cron_job(user, jid)
    if body.action in ('resume', 'run') and cron_restricted(P):
        reason = cron_violation(P, j, CRON_TOOL.get(P + ':tools'))
        if reason:
            raise HTTPException(409, reason)
        if (
            body.action == 'resume'
            and sum(1 for x in _host_admin('cron_list', {'name': P})['jobs'] if x.get('enabled') and x['id'] != jid) >= CRON_MAX_JOBS
        ):
            raise HTTPException(409, f'Уже {CRON_MAX_JOBS} активних завдань')
    _host_admin('cron_action', {'name': P, 'job': jid, 'action': body.action})
    if body.action == 'resume':
        with db() as c:
            c.execute('UPDATE cron_jobs SET note=NULL WHERE profile=? AND job=?', (P, jid))
    audit(user, 'cron.' + body.action, P, {'job': jid, 'name': j.get('name')})
    return {'ok': True}


@app.delete('/api/cron/{jid}')
def cron_delete_api(jid: str, user=Depends(current_user)):
    require_cron(user)
    P = user['profile']
    j = _cron_job(user, jid)
    _host_admin('cron_action', {'name': P, 'job': jid, 'action': 'remove'})
    with db() as c:
        c.execute('DELETE FROM cron_jobs WHERE profile=? AND job=?', (P, jid))
    audit(user, 'cron.delete', P, {'job': jid, 'name': j.get('name')})
    return {'deleted': jid}


@app.get('/api/cron/{jid}/runs/{run}')
def cron_run_api(jid: str, run: str, user=Depends(current_user)):
    require_cron(user)
    _cron_job(user, jid)
    try:
        r = _host_admin('cron_report', {'name': user['profile'], 'job': jid, 'file': run})
    except HTTPException:
        raise HTTPException(404, 'No such run')
    return {'file': run, 'answer': r.get('answer'), 'failed': bool(r.get('failed')), 'silent': not r.get('answer') and not r.get('failed')}


# ---------------- CLI: python app.py create-user NAME ROLE PROFILE ----------------
if __name__ == '__main__' and len(sys.argv) == 5 and sys.argv[1] == 'create-user':
    uid, pw = create_user(sys.argv[2], sys.argv[3], sys.argv[4])
    if sys.argv[3] == 'admin':
        with db() as c:
            c.execute("UPDATE dialogs SET owner=? WHERE owner IS NULL AND profile='default'", (uid,))
    print(json.dumps({'id': uid, 'username': sys.argv[2], 'password': pw}))
