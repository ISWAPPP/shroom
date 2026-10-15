"""Audit log + user deletion acceptance (inside backend container; no secrets printed)."""
import json, sys, time, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra) if extra else ''),flush=True)
def client(): return httpx.Client(base_url=B,verify=False,timeout=300,headers=O)
def login(u,pw):
    c=client(); r=c.post('/api/auth/login',json={'username':u,'password':pw}); r.raise_for_status()
    c.headers['X-CSRF-Token']=r.json()['csrf']; return c
adm=login('admin',creds['admin']); usr=login('tester',creds['tester'])
check('user cannot read audit 403', usr.get('/api/admin/audit').status_code==403)
users=adm.get('/api/admin/users').json()
check('last_login exposed', any(u['username']=='admin' and u.get('last_login') for u in users))
# create temp user, act as them
r=adm.post('/api/admin/users',json={'username':'audit-tmp','role':'user','profile':'webtest'}); uid=r.json()['id']; pw=r.json()['password']
client().post('/api/auth/login',json={'username':'audit-tmp','password':'wrong-password-x'})
tmp=login('audit-tmp',pw)
did=tmp.post('/api/dialogs',json={'title':'audit tmp'}).json()['id']
tmp.post(f'/api/dialogs/{did}/chat',json={'text':'Reply with exactly AUDIT_OK','request_id':'audit-'+str(int(time.time()))+'abcdef'})
for _ in range(40):
    time.sleep(2)
    if tmp.get(f'/api/dialogs/{did}/sync').json()['state'] in ('complete','error','interrupted'): break
tmp.post(f'/api/dialogs/{did}/command',json={'command':'/version'})
tmp.post(f'/api/dialogs/{did}/command',json={'command':'/yolo'})
adm.patch(f'/api/admin/users/{uid}',json={'blocked':True})
adm.patch(f'/api/admin/users/{uid}',json={'blocked':False})
adm.post(f'/api/admin/users/{uid}/password')
adm.put(f'/api/admin/permissions/user:{uid}',json={'changes':{'cmd:usage':False}})
rows=adm.get('/api/admin/audit',params={'actor':'audit-tmp','limit':100}).json()
acts={r['action'] for r in rows}
need={'user.create','auth.login_failed','auth.login','chat.turn','command.run','command.denied','user.update','user.password_reset','perms.update'}
check('audit captured all actions', need<=acts, sorted(need-acts))
check('audit has ip', all(r['ip'] for r in rows))
check('audit filter by group', all(r['action'].startswith('auth.') for r in adm.get('/api/admin/audit',params={'action':'auth.'}).json()))
check('user cannot delete users 403', usr.delete(f'/api/admin/users/{uid}').status_code==403)
me=[u for u in users if u['username']=='admin'][0]
check('admin cannot delete self 400', adm.delete(f"/api/admin/users/{me['id']}").status_code==400)
r=adm.delete(f'/api/admin/users/{uid}',params={'purge_history':'true'})
check('delete user', r.status_code==200 and r.json()['dialogs']==1, r.text[:200])
check('hermes session purged', r.json().get('hermes_sessions_deleted')==1, r.json())
check('deleted user cannot login', client().post('/api/auth/login',json={'username':'audit-tmp','password':pw}).status_code==401)
check('deleted user session dead', tmp.get('/api/dialogs').status_code==401)
check('user gone from list', 'audit-tmp' not in [u['username'] for u in adm.get('/api/admin/users').json()])
check('delete audited', any(r['action']=='user.delete' and r['target']=='audit-tmp' for r in adm.get('/api/admin/audit',params={'action':'user.'}).json()))
leftover=[u for u in adm.get('/api/admin/users').json() if u['username']=='settings-user']
if leftover:
    r=adm.delete(f"/api/admin/users/{leftover[0]['id']}"); check('removed leftover settings-user', r.status_code==200, r.text[:120])
now=time.time();rows=adm.get('/api/admin/audit',params={'since':now-3600,'until':now+60,'limit':500}).json()
check('date range: only rows inside it',bool(rows) and all(now-3600<=r['ts']<now+60 for r in rows),str(len(rows)))
check('date range in the future is empty',adm.get('/api/admin/audit',params={'since':now+86400}).json()==[],'')
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
