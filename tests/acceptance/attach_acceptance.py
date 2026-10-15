"""Attachment cards in chat history: a user message that carried a pasted text and a clipboard image gets `files`
(id, name, mime, size, text preview + line count) resolved through files.ref, the inlined `--- Attached Context ---`
copy is cut from the reply, edit/regenerate keep the text attachment, and a deleted artifact stays as a `missing`
card. Real LLM calls on webtest (Haiku)."""
import io, json, sys, time, atexit, uuid, httpx, os
from PIL import Image

creds = json.loads(sys.stdin.read())
B = 'https://proxy'
O = {'Origin': os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res = {}


def check(n, c):
    res[n] = bool(c)
    print(('PASS ' if c else 'FAIL ') + n, flush=True)


def login(u):
    c = httpx.Client(base_url=B, verify=False, timeout=120, headers=O)
    r = c.post('/api/auth/login', json={'username': u, 'password': creds[u]})
    r.raise_for_status()
    c.headers['X-CSRF-Token'] = r.json()['csrf']
    return c


usr = login('tester')
did = usr.post('/api/dialogs', json={'title': 'attach test'}).json()['id']
atexit.register(lambda: usr.delete(f'/api/dialogs/{did}'))


def settle(limit=150):
    t = time.time()
    while time.time() - t < limit:
        s = usr.get(f'/api/dialogs/{did}/sync').json()
        if s['state'] not in ('running', 'waiting'):
            return s['state']
        time.sleep(1)
    return 'timeout'


def hist():
    return usr.get(f'/api/dialogs/{did}/history', params={'tail': 50}).json()['messages']


body = '\n'.join(f'line {i}: the secret word is CHANTERELLE' for i in range(60))
stamp = time.strftime('%Y%m%d-%H%M%S')
txt = usr.post(f'/api/dialogs/{did}/files', files={'file': (f'pasted-text-{stamp}.txt', body.encode(), 'text/plain')}).json()
buf = io.BytesIO()
Image.new('RGB', (40, 30), (200, 80, 40)).save(buf, 'PNG')
img = usr.post(f'/api/dialogs/{did}/files', files={'file': (f'clipboard-{stamp}.png', buf.getvalue(), 'image/png')}).json()
check('uploads accepted', txt.get('id') and img.get('id'))
r = usr.post(
    f'/api/dialogs/{did}/chat',
    json={'text': 'What is the secret word in the attached text? One word.', 'files': [txt['id'], img['id']], 'request_id': uuid.uuid4().hex},
)
check('turn with attachments accepted', r.status_code == 200 and settle() == 'complete')
u = [m for m in hist() if m['role'] == 'user']
files = (u[0].get('files') if u else None) or []
by = {f.get('id'): f for f in files}
check('user message carries both files', set(by) == {txt['id'], img['id']})
t = by.get(txt['id'], {})
check('text card has preview and line count', t.get('preview', '').startswith('line 0:') and t.get('lines') == 60 and t.get('mime') == 'text/plain')
check('image card has mime and size', by.get(img['id'], {}).get('mime') == 'image/png' and by.get(img['id'], {}).get('size', 0) > 0)
raw = u[0].get('text') or u[0].get('content') or '' if u else ''
check('attached context not re-sent', '--- Attached Context ---' not in raw and '@file:' in raw)
a = ' '.join(m.get('text') or '' for m in hist() if m['role'] == 'assistant')
check('agent read the text', 'chanterelle' in a.lower())
# regenerate the way the UI does: visible text + the message's file ids, attached again
r = usr.post(
    f'/api/dialogs/{did}/chat',
    json={
        'text': 'What is the secret word in the attached text? One word.',
        'files': [f['id'] for f in files],
        'request_id': uuid.uuid4().hex,
        'rewind': 'retry',
        'rewind_row_id': u[0]['row_id'],
    },
)
check('regenerate accepted', r.status_code == 200 and settle() == 'complete')
h = hist()
u2 = [m for m in h if m['role'] == 'user']
check('regenerated message keeps both cards', len(u2) == 1 and {f.get('id') for f in u2[0].get('files') or []} == {txt['id'], img['id']})
check('regenerated answer still knows the word', 'chanterelle' in ' '.join(m.get('text') or '' for m in h if m['role'] == 'assistant').lower())
usr.delete(f'/api/me/files/{txt["id"]}')
u3 = [m for m in hist() if m['role'] == 'user']
fs = u3[0].get('files') or [] if u3 else []
check('deleted artifact becomes a missing card', any(f.get('missing') and not f.get('id') for f in fs) and any(f.get('id') == img['id'] for f in fs))
print(json.dumps({'passed': sum(res.values()), 'total': len(res)}))
if not all(res.values()):
    sys.exit(1)
