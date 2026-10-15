"""Idle session reaping: a chat whose live Hermes session was closed (dialogs.live='' as the reaper leaves it) is
resumed transparently on the next open, with its history intact. Also checks the admin host answers health.
Needs DB access: runs inside the backend container (tests/run.sh)."""
import json,sys,time,uuid,atexit,sqlite3,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=180,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
h=httpx.Client(transport=httpx.HTTPTransport(uds='/run/bridge/admin.sock')).get('http://x/health').json()
check('admin host healthy',h.get('ok') and h.get('ops',0)>30)
usr=login('tester')
d=usr.post('/api/dialogs',json={'title':'reap test'}).json();did=d['id']
atexit.register(lambda: usr.delete(f'/api/dialogs/{did}'))
usr.post(f'/api/dialogs/{did}/chat',json={'text':'Reply with one word: kiwi','files':[],'request_id':uuid.uuid4().hex})
for _ in range(90):
    if usr.get(f'/api/dialogs/{did}/sync').json()['state'] not in ('running','waiting'): break
    time.sleep(1)
before=usr.get(f'/api/dialogs/{did}/history',params={'tail':50}).json()['messages']
c=sqlite3.connect('/data/portal.db');old=c.execute('SELECT live,profile FROM dialogs WHERE id=?',(did,)).fetchone()
c.execute("UPDATE dialogs SET live='' WHERE id=?",(did,));c.commit()
after=usr.get(f'/api/dialogs/{did}/history',params={'tail':50}).json()['messages']
new=c.execute('SELECT live FROM dialogs WHERE id=?',(did,)).fetchone()[0]
check('closed session resumed on open',bool(new) and new!='')
check('history intact after resume',[m.get('text') for m in after]==[m.get('text') for m in before] and len(after)>=2)
usr.post(f'/api/dialogs/{did}/chat',json={'text':'Which fruit did you name? One word.','files':[],'request_id':uuid.uuid4().hex})
for _ in range(90):
    if usr.get(f'/api/dialogs/{did}/sync').json()['state'] not in ('running','waiting'): break
    time.sleep(1)
a=[m for m in usr.get(f'/api/dialogs/{did}/history',params={'tail':50}).json()['messages'] if m['role']=='assistant']
check('agent keeps the context after resume','kiwi' in (a[-1].get('text') or '').lower())
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
