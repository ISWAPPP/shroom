"""Real profile-management acceptance test (inside backend container; no secrets printed)."""
import json, sys, time, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra) if extra else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=400,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); r.raise_for_status()
    c.headers['X-CSRF-Token']=r.json()['csrf']; return c
adm=login('admin'); usr=login('tester')
check('user cannot list host profiles 403', usr.get('/api/admin/host/profiles').status_code==403)
check('user cannot create profile 403', usr.post('/api/admin/host/profiles',json={'name':'x','provider':'anthropic','model':'m'}).status_code==403)
ps=adm.get('/api/admin/host/profiles').json(); check('list profiles', {'default','webtest'}<={p['name'] for p in ps}, [(p['name'],p['bridge'],p['users']) for p in ps])
check('bad name rejected', adm.post('/api/admin/host/profiles',json={'name':'Bad Name','provider':'anthropic','model':'claude-haiku-4-5'}).status_code==400)
check('cannot recreate default', adm.post('/api/admin/host/profiles',json={'name':'default','provider':'anthropic','model':'claude-haiku-4-5'}).status_code==400)
r=adm.post('/api/admin/host/profiles',json={'name':'settingstest','provider':'anthropic','model':'claude-haiku-4-5','description':'portal settings acceptance'})
check('create profile', r.status_code==200 and r.json()['bridge']=='active', r.text[:200])
time.sleep(10)
check('new profile in bridge list', 'settingstest' in adm.get('/api/admin/profiles').json())
tools=adm.get('/api/admin/host/profiles/settingstest/tools').json()
en={t['name'] for t in tools if t['enabled']}
check('safe default toolsets', not ({'terminal','file','code_execution','browser'} & en), sorted(en))
m=adm.get('/api/admin/host/profiles/settingstest/models').json()
check('model catalog', any(p['slug']=='anthropic' and 'claude-haiku-4-5' in p['models'] for p in m['providers']))
r=adm.put('/api/admin/host/profiles/settingstest/tools',json={'enable':[],'disable':['web']})
check('disable web tool', r.status_code==200 and not any(t['name']=='web' and t['enabled'] for t in r.json()))
time.sleep(10)
r=adm.put('/api/admin/host/profiles/settingstest/model',json={'provider':'anthropic','model':'claude-haiku-4-5-20251001'})
check('change model', r.status_code==200 and r.json()['model']=='claude-haiku-4-5-20251001')
time.sleep(10)
r=adm.post('/api/admin/users',json={'username':'settings-user','role':'user','profile':'settingstest'}); check('create user on new profile', r.status_code==200); uid=r.json()['id']
c2=httpx.Client(base_url=B,verify=False,timeout=200,headers=O); lr=c2.post('/api/auth/login',json={'username':'settings-user','password':r.json()['password']}); c2.headers['X-CSRF-Token']=lr.json()['csrf']
d=c2.post('/api/dialogs',json={'title':'settings test'}).json()['id']
c2.post(f'/api/dialogs/{d}/chat',json={'text':'Reply with exactly SETTINGS_PROFILE_OK','request_id':'settings-'+str(int(time.time()))+'xyz'})
for _ in range(60):
    time.sleep(2)
    if c2.get(f'/api/dialogs/{d}/sync').json()['state'] in ('complete','error','interrupted'): break
txt=json.dumps(c2.get(f'/api/dialogs/{d}/history').json()['messages'][-1:],ensure_ascii=False)
check('real answer from new profile', 'SETTINGS_PROFILE_OK' in txt, txt[:120])
check('delete blocked while user assigned', adm.post('/api/admin/host/profiles/settingstest/delete',json={'confirm':'settingstest'}).status_code==400)
adm.patch(f'/api/admin/users/{uid}',json={'blocked':True,'profile':'webtest'})
check('delete wrong confirm 400', adm.post('/api/admin/host/profiles/settingstest/delete',json={'confirm':'nope'}).status_code==400)
r=adm.post('/api/admin/host/profiles/settingstest/delete',json={'confirm':'settingstest'}); check('delete profile', r.status_code==200, r.text[:150])
check('profile gone', 'settingstest' not in {p['name'] for p in adm.get('/api/admin/host/profiles').json()})
check('owner bridge cannot be stopped', adm.post('/api/admin/host/profiles/default/bridge',json={'action':'stop'}).status_code==400)
check('cleanup test user', adm.delete(f'/api/admin/users/{uid}').status_code==200)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
