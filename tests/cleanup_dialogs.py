"""Remove chats that acceptance scripts left in the `tester` account (only tester; never other users).
Usage inside the backend container, creds JSON on stdin:
  snap  -> prints the ids of tester's current dialogs (one per line)
  clean <snapfile-content-on-argv...> -> deletes tester's dialogs that are not in the snapshot
  titles <title> [<title> ...] -> deletes tester's dialogs with exactly these titles (one-off backlog cleanup)
Deletion goes through the API (closes and deletes the Hermes session too); a chat still answering is retried for 60 s."""
import json, sys, time, httpx, os
creds = json.loads(sys.stdin.read())
c = httpx.Client(base_url='https://proxy', verify=False, timeout=60, headers={'Origin': os.environ.get('PORTAL_ORIGIN', 'https://localhost')})
r = c.post('/api/auth/login', json={'username': 'tester', 'password': creds['tester']}); r.raise_for_status()
c.headers['X-CSRF-Token'] = r.json()['csrf']
items = c.get('/api/dialogs').json()   # legacy shape: every dialog with at least one turn
mode, args = sys.argv[1], sys.argv[2:]
if mode == 'snap':
    print('SNAP ' + ' '.join(d['id'] for d in items)); sys.exit(0)
keep = set(args) if mode == 'clean' else set()
doomed = [d for d in items if (d['id'] not in keep if mode == 'clean' else d['title'] in args)]
gone = 0
for d in doomed:
    x = None
    for _ in range(12):
        x = c.delete(f"/api/dialogs/{d['id']}")
        if x.status_code != 409: break
        time.sleep(5)
    gone += bool(x is not None and x.status_code == 200)
print(f'cleanup: deleted {gone}/{len(doomed)} tester chats')
