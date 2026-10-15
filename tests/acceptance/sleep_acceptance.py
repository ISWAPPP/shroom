"""Idle sleep of user bridges: an asleep bridge answers polls with 503 {asleep} without waking, /api/me/bridge reports
it, ?wake=1 starts it and waits, then chat calls work again. Uses webtest (tester). Needs the owner bridge to run the
current profile_admin (bridge sleep/wake actions)."""
import json,sys,time,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
adm=login('admin');usr=login('tester')
P=usr.get('/api/auth/me').json()['user']['profile']
d=usr.get('/api/dialogs',params={'limit':5}).json()['items'];did=d[0]['id'] if d else None
check('starts ready',usr.get('/api/me/bridge').json()['state']=='ready')
check('owner bridge cannot sleep',adm.post('/api/admin/host/profiles/default/bridge',json={'action':'sleep'}).status_code>=400)
check('admin puts it to sleep',adm.post(f'/api/admin/host/profiles/{P}/bridge',json={'action':'sleep'}).status_code==200)
check('reported asleep',usr.get('/api/me/bridge').json()['state']=='asleep')
if did:
    r=usr.get(f'/api/dialogs/{did}/sync');check('poll gets 503 asleep and does not wake',r.status_code==503 and r.json()['detail'].get('asleep') and usr.get('/api/me/bridge').json()['state']=='asleep')
t=time.time();r=usr.get('/api/me/bridge',params={'wake':1});dt=time.time()-t
check(f'wake=1 brings it back ({dt:.1f}s)',r.json()['state']=='ready')
if did: check('chat calls work again',usr.get(f'/api/dialogs/{did}/sync').status_code==200)
au=adm.get('/api/admin/audit',params={'action':'profile.wake','limit':5}).json()
check('wake audited',any(a['target']==P for a in au))
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
