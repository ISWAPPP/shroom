"""Header model switch: own vs shared groups, admin allowlist for shared models, reasoning effort gated by cmd:reasoning."""
import json, sys, time, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:300] if extra else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=200,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); c.headers['X-CSRF-Token']=r.json()['csrf']; return c,r.json()['user']
usr,uu=login('tester'); adm,_=login('admin'); S='user:'+uu['id']; U=uu['id']
def wait():
    for _ in range(60):
        try:
            if usr.get('/api/me/models').status_code==200: return
        except Exception: pass
        time.sleep(2)
before_allow=adm.get(f'/api/admin/users/{U}/models').json()['allowed']
adm.put(f'/api/admin/users/{U}/models',json={'allowed':[]})
d=usr.get('/api/me/models').json(); cur=d['current']; kinds={p['slug']:p['kind'] for p in d['providers']}
check('kinds present', set(kinds.values())<= {'own','shared'} and kinds, kinds)
sh=next((p for p in d['providers'] if p['kind']=='shared'),None)
check('shared limited to assigned', sh and len(sh['models'])==1, sh and sh['models'])
full=next(p for p in adm.get(f'/api/admin/users/{U}/models').json()['shared'] if p['slug']==sh['slug'])['models']
extra=next(m for m in full if m not in sh['models'])
check('non-allowed shared model refused', usr.put('/api/me/models',json={'provider':sh['slug'],'model':extra}).status_code==403)
adm.put(f'/api/admin/users/{U}/models',json={'allowed':[f"{sh['slug']}/{extra}"]})
check('allowlist widens choice', extra in next(p for p in usr.get('/api/me/models').json()['providers'] if p['slug']==sh['slug'])['models'])
own=next((p for p in d['providers'] if p['kind']=='own'),None)
if own:
    t=next(m for m in own['models'] if m!=cur['model'])
    try:
        r=usr.put('/api/me/models',json={'provider':own['slug'],'model':t}); time.sleep(3); wait()
        check('own switch', r.status_code==200 and usr.get('/api/me/models').json()['current']=={'provider':own['slug'],'model':t})
    finally: usr.put('/api/me/models',json=cur); time.sleep(3); wait()
check('restored', usr.get('/api/me/models').json()['current']==cur)
check('reasoning hidden without perm', usr.get('/api/me/models').json()['can_reason'] is False and usr.put('/api/me/reasoning',json={'effort':'low'}).status_code==403)
adm.put(f'/api/admin/permissions/{S}',json={'changes':{'cmd:reasoning':True}})
try:
    r=usr.put('/api/me/reasoning',json={'effort':'low'}); time.sleep(3); wait()
    check('reasoning set', r.status_code==200 and usr.get('/api/me/models').json()['effort']=='low', r.text)
    check('bad effort refused', usr.put('/api/me/reasoning',json={'effort':'turbo'}).status_code>=400)
finally:
    usr.put('/api/me/reasoning',json={'effort':''}); time.sleep(3); wait()
    adm.put(f'/api/admin/permissions/{S}',json={'changes':{'cmd:reasoning':None}})
    adm.put(f'/api/admin/users/{U}/models',json={'allowed':before_allow})
check('user cannot edit allowlist', usr.put(f'/api/admin/users/{U}/models',json={'allowed':[]}).status_code==403)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
