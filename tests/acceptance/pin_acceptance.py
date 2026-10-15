"""Pinned chats: PATCH /api/dialogs/{id} {pinned}, pinned chats listed with the recent ones regardless of age,
rename still works, bad bodies rejected, other users' chats untouchable. Runs one short LLM turn on webtest."""
import json,sys,time,uuid,atexit,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
usr=login('tester');adm=login('admin')
d=usr.post('/api/dialogs',json={'title':'pin test'}).json();did=d['id']
atexit.register(lambda: usr.delete(f'/api/dialogs/{did}'))
usr.post(f'/api/dialogs/{did}/chat',json={'text':'Reply with one word: ok','files':[],'request_id':uuid.uuid4().hex})
for _ in range(90):
    if usr.get(f'/api/dialogs/{did}/sync').json()['state'] not in ('running','waiting'): break
    time.sleep(1)
row=lambda: next((x for x in usr.get('/api/dialogs').json() if x['id']==did),None)
check('listed, not pinned',row() is not None and row()['pinned'] is False)
check('pin',usr.patch(f'/api/dialogs/{did}',json={'pinned':True}).json().get('pinned') is True and row()['pinned'] is True)
p=usr.get('/api/dialogs',params={'limit':0}).json()
check('pinned chat listed even with limit=0 (never paged into the archive)',any(x['id']==did for x in p['items']))
check('rename keeps working',usr.patch(f'/api/dialogs/{did}',json={'title':'pin test renamed'}).json().get('title')=='pin test renamed' and row()['pinned'] is True)
check('empty patch rejected',usr.patch(f'/api/dialogs/{did}',json={}).status_code==400)
check('unknown field rejected',usr.patch(f'/api/dialogs/{did}',json={'pinned':True,'x':1}).status_code==422)
check('non-bool pinned rejected',usr.patch(f'/api/dialogs/{did}',json={'pinned':'yes'}).status_code==422)
check("another user cannot pin it",adm.patch(f'/api/dialogs/{did}',json={'pinned':False}).status_code==404 and row()['pinned'] is True)
check('unpin',usr.patch(f'/api/dialogs/{did}',json={'pinned':False}).json().get('pinned') is False and row()['pinned'] is False)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
