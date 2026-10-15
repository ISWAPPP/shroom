"""Admin "log in as user": session switch, banner data, restrictions, audit, return to own session, admin targets refused."""
import json,sys,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=60,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
adm=login('admin');usr=login('tester')
users=adm.get('/api/admin/users').json();tester=next(u for u in users if u['username']=='tester');admin=next(u for u in users if u['username']=='admin')
check('user cannot impersonate',usr.post(f"/api/admin/users/{admin['id']}/impersonate").status_code==403)
check('admin target refused',adm.post(f"/api/admin/users/{admin['id']}/impersonate").status_code==403)
r=adm.post(f"/api/admin/users/{tester['id']}/impersonate");check('impersonate starts',r.status_code==200 and r.json()['user']['username']=='tester')
adm.headers['X-CSRF-Token']=r.json()['csrf']
me=adm.get('/api/auth/me').json()['user'];check('acting as tester, banner data',me['username']=='tester' and me['role']=='user' and me['impersonated_by']=='admin')
check('admin API closed while impersonating',adm.get('/api/admin/users').status_code==403)
check('sees tester dialogs',adm.get('/api/dialogs').status_code==200)
check('password change refused',adm.post('/api/auth/password',json={'old':'x'*12,'new':'y'*12}).status_code==403)
check('totp setup refused',adm.post('/api/auth/totp/setup').status_code==403)
check('nested impersonation impossible',adm.post(f"/api/admin/users/{tester['id']}/impersonate").status_code==403)
check('real tester session unaffected',usr.get('/api/auth/me').json()['user'].get('impersonated_by') is None)
r=adm.post('/api/auth/impersonate/stop');check('return restores admin session',r.status_code==200 and r.json()['restored'])
me=adm.get('/api/auth/me').json();adm.headers['X-CSRF-Token']=me['csrf']
check('back as admin',me['user']['username']=='admin' and not me['user'].get('impersonated_by'))
log=adm.get('/api/admin/audit').json();items=log.get('items',log) if isinstance(log,dict) else log
acts=[(e.get('action'),e.get('actor_name')) for e in items[:30]]
check('audited start/stop',('auth.impersonate_start','admin') in acts and ('auth.impersonate_stop','admin') in acts)
check('stop without impersonation rejected',adm.post('/api/auth/impersonate/stop').status_code==400)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
