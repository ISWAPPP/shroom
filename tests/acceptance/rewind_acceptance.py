"""Edit / regenerate (native Hermes rewind through POST /chat with rewind + rewind_row_id), message timestamps and
row ids in /history, permission gate (cmd:undo / cmd:retry). Real LLM calls on webtest (Haiku)."""
import json,sys,time,atexit,uuid,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
adm=login('admin');usr=login('tester')
tester=next(u for u in adm.get('/api/admin/users').json() if u['username']=='tester')
S='user:'+tester['id'];KEYS=('cmd:undo','cmd:retry')
snap=adm.get(f'/api/admin/permissions/{S}').json()
atexit.register(lambda: adm.put(f'/api/admin/permissions/{S}',json={'changes':{k:snap.get(k) for k in KEYS}}))
adm.put(f'/api/admin/permissions/{S}',json={'changes':{k:None for k in KEYS}})
p=usr.get('/api/me/permissions').json()
check('permissions expose cmd:undo and cmd:retry',p.get('cmd:undo') is True and p.get('cmd:retry') is True)
d=usr.post('/api/dialogs',json={'title':'rewind test'}).json();did=d['id']
atexit.register(lambda: usr.delete(f'/api/dialogs/{did}'))
def chat(text,**kw): return usr.post(f'/api/dialogs/{did}/chat',json={'text':text,'files':[],'request_id':uuid.uuid4().hex,**kw})
def settle(limit=120):
    t=time.time()
    while time.time()-t<limit:
        s=usr.get(f'/api/dialogs/{did}/sync').json()
        if s['state'] not in ('running','waiting'): return s['state']
        time.sleep(1)
    return 'timeout'
def hist(): return usr.get(f'/api/dialogs/{did}/history',params={'tail':50}).json()['messages']
check('first turn',chat('Reply with exactly one word: mushroom').status_code==200 and settle()=='complete')
h=hist();u=[m for m in h if m['role']=='user']
check('history carries row_id and timestamp',bool(u) and isinstance(u[0].get('row_id'),int) and u[0].get('timestamp',0)>time.time()-600)
row=u[0]['row_id']
check('rewind without row id rejected',chat('x',rewind='edit').status_code==400)
check('unknown rewind kind rejected',chat('x',rewind='drop',rewind_row_id=row).status_code==422)
adm.put(f'/api/admin/permissions/{S}',json={'changes':{'cmd:undo':False}})
check('edit denied without cmd:undo',chat('Reply with exactly one word: sun',rewind='edit',rewind_row_id=row).status_code==403)
adm.put(f'/api/admin/permissions/{S}',json={'changes':{'cmd:undo':None}})
r=chat('Reply with exactly one word: sun',rewind='edit',rewind_row_id=row)
check('edit accepted',r.status_code==200 and settle()=='complete')
h=hist();u=[m for m in h if m['role']=='user'];a=[m for m in h if m['role']=='assistant']
check('edit replaced the user message (one user message, new text)',len(u)==1 and 'sun' in (u[0].get('text') or '') and 'mushroom' not in (u[0].get('text') or ''))
check('edit produced a new answer',bool(a) and 'sun' in ' '.join(x.get('text') or '' for x in a).lower())
r=chat(u[0]['text'],rewind='retry',rewind_row_id=u[0]['row_id'])
check('regenerate accepted',r.status_code==200 and settle()=='complete')
h2=hist();u2=[m for m in h2 if m['role']=='user']
check('regenerate keeps one user message and an answer',len(u2)==1 and any(m['role']=='assistant' for m in h2))
check('stale row id refused with 409',chat('Reply: x',rewind='edit',rewind_row_id=row).status_code==409)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
