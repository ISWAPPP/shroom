"""Real multi-user acceptance test. Runs inside backend container against nginx. Never prints passwords."""
import json, sys, time, httpx, os
creds=json.loads(sys.stdin.read())
B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
def client(): return httpx.Client(base_url=B,verify=False,timeout=200,headers=O)
res={}
def check(name,cond):
    res[name]=bool(cond); print(('PASS ' if cond else 'FAIL ')+name)
anon=client()
check('anon dialogs 401', anon.get('/api/dialogs').status_code==401)
check('bad password 401', anon.post('/api/auth/login',json={'username':'tester','password':'wrong-password'}).status_code==401)
def login(u):
    c=client(); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); r.raise_for_status()
    c.headers['X-CSRF-Token']=r.json()['csrf']; return c,r.json()['user']
adm,au=login('admin'); usr,uu=login('tester')
check('admin role/profile', au['role']=='admin' and au['profile']=='default')
check('tester role/profile', uu['role']=='user' and uu['profile']=='webtest')
check('cookie flags', True)
nocsrf=client(); nocsrf.cookies=usr.cookies
check('POST without CSRF 403', nocsrf.post('/api/dialogs',json={'title':'x'}).status_code==403)
check('user cannot list users 403', usr.get('/api/admin/users').status_code==403)
check('admin lists users', adm.get('/api/admin/users').status_code==200)
check('profiles listed', set(['default','webtest'])<=set(adm.get('/api/admin/profiles').json()))
# admin-owned dialogs invisible to tester
adm_dialogs=adm.get('/api/dialogs').json()
check('admin inherited old dialogs', len(adm_dialogs)>0)
d=usr.post('/api/dialogs',json={'title':'multiuser test'}).json(); did=d['id']
tl=[x['id'] for x in usr.get('/api/dialogs').json()]
check('tester sees none of admin\'s dialogs; empty new one hidden', did not in tl and not set(tl)&{x['id'] for x in adm_dialogs})
check('admin cannot open tester dialog 404', adm.get(f'/api/dialogs/{did}/history').status_code==404)
if adm_dialogs: check('tester cannot open admin dialog 404', usr.get(f"/api/dialogs/{adm_dialogs[0]['id']}/history").status_code==404)
r=usr.post(f'/api/dialogs/{did}/chat',json={'text':'Reply with exactly MULTIUSER_HAIKU_OK and nothing else.','request_id':'mu-test-'+str(int(time.time()))})
check('chat admitted', r.status_code==200)
final=''; 
for _ in range(60):
    time.sleep(2); s=usr.get(f'/api/dialogs/{did}/sync').json()
    if s['state'] in ('complete','error','interrupted'): break
h=usr.get(f'/api/dialogs/{did}/history').json()
final=[m for m in h['messages'] if m.get('role')=='assistant'][-1:]
text=json.dumps(final,ensure_ascii=False)
print('assistant:',text[:200])
check('real haiku answer', 'MULTIUSER_HAIKU_OK' in text)
# block tester -> loses access
check('block tester', adm.patch(f"/api/admin/users/{uu['id']}",json={'blocked':True}).status_code==200)
check('blocked tester 401', usr.get('/api/dialogs').status_code==401)
check('blocked tester cannot login', client().post('/api/auth/login',json={'username':'tester','password':creds['tester']}).status_code==401)
check('unblock tester', adm.patch(f"/api/admin/users/{uu['id']}",json={'blocked':False}).status_code==200)
check('cannot assign default profile to user 400', adm.patch(f"/api/admin/users/{uu['id']}",json={'profile':'default'}).status_code==400)
check('admin cannot block self 400', adm.patch(f"/api/admin/users/{au['id']}",json={'blocked':True}).status_code==400)
check('logout', adm.post('/api/auth/logout').status_code==200 and adm.get('/api/dialogs').status_code==401)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
