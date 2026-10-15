"""Sliding session expiry: an open tab (any authenticated request, polls included) keeps the login alive, so a user is
not logged out while the agent sleeps; the absolute cap from login still applies. Uses tester; edits only its own
fresh session row in /data/portal.db and logs it out afterwards."""
import json, sqlite3, sys, time, httpx, os

creds = json.loads(sys.stdin.read())
B = 'https://proxy'
O = {'Origin': os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res = {}


def check(n, c):
    res[n] = bool(c)
    print(('PASS ' if c else 'FAIL ') + n, flush=True)


c = httpx.Client(base_url=B, verify=False, timeout=60, headers=O)
r = c.post('/api/auth/login', json={'username': 'tester', 'password': creds['tester']})
r.raise_for_status()
c.headers['X-CSRF-Token'] = r.json()['csrf']
db = sqlite3.connect('/data/portal.db', timeout=10)
uid = c.get('/api/auth/me').json()['user']['id']
token = db.execute('SELECT token FROM sessions WHERE user=? AND impersonator IS NULL ORDER BY created DESC LIMIT 1', (uid,)).fetchone()[0]


def exp():
    return db.execute('SELECT expires FROM sessions WHERE token=?', (token,)).fetchone()[0]


try:
    db.execute('UPDATE sessions SET expires=? WHERE token=?', (time.time() + 120, token))
    db.commit()
    check('GET poll still authenticated near expiry', c.get('/api/auth/me').status_code == 200)
    check('expiry slid forward to ~12 h', exp() > time.time() + 11 * 3600)
    before = exp()
    c.get('/api/auth/me')
    check('no rewrite within 5 minutes', exp() == before)
    db.execute('UPDATE sessions SET created=?, expires=? WHERE token=?', (time.time() - 7 * 24 * 3600 + 600, time.time() + 60, token))
    db.commit()
    c.get('/api/auth/me')
    created = db.execute('SELECT created FROM sessions WHERE token=?', (token,)).fetchone()[0]
    check('capped at 7 days from login', abs(exp() - (created + 7 * 24 * 3600)) < 2)
    db.execute('UPDATE sessions SET expires=? WHERE token=?', (time.time() - 1, token))
    db.commit()
    check('expired session is refused', c.get('/api/auth/me').status_code == 401)
finally:
    db.execute('DELETE FROM sessions WHERE token=?', (token,))
    db.commit()
print(json.dumps({'passed': sum(res.values()), 'total': len(res)}))
if not all(res.values()):
    sys.exit(1)
