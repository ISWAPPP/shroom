"""Own skills/plugins management: defaults allowed, sandbox-only plugin enable, permission and shared-profile gates.
Toggles 'disk-cleanup' plugin on webtest (sandboxed) and restores it."""
import json, sys, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:200] if extra else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=300,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); c.headers['X-CSRF-Token']=r.json()['csrf']; return c,r.json()['user']
adm,_=login('admin'); usr,uu=login('tester'); S='user:'+uu['id']
perm=usr.get('/api/me/permissions').json()
check('own_skills default on', perm.get('feature:own_skills') is True)
check('own_plugins default on', perm.get('feature:own_plugins') is True)
pl=usr.get('/api/me/plugins').json()
check('plugins listed, messengers hidden', len(pl['plugins'])>10 and not any(p['name'].endswith('-platform') for p in pl['plugins']), len(pl['plugins']))
iso=adm.get('/api/admin/host/profiles/webtest/isolation').json()['enabled']
P='disk-cleanup'; before=next(p['enabled'] for p in pl['plugins'] if p['name']==P)
try:
    r=usr.put('/api/me/plugins/'+P,json={'enabled':not before})
    if iso or before: check('toggle plugin (sandbox)', r.status_code==200 and next(p['enabled'] for p in r.json()['plugins'] if p['name']==P)==(not before), r.text)
    else: check('enable refused without sandbox', r.status_code>=400)
finally:
    usr.put('/api/me/plugins/'+P,json={'enabled':before})
check('unknown plugin refused', usr.put('/api/me/plugins/nope-xyz',json={'enabled':True}).status_code>=400)
sk=usr.get('/api/me/skills/manage'); check('own skills list', sk.status_code==200 and len(sk.json()['skills'])>0)
name=next(x['name'] for x in sk.json()['skills'] if x['enabled'])
r=usr.put('/api/me/skills/'+name,json={'enabled':False}); off=next(x['enabled'] for x in r.json()['skills'] if x['name']==name)
usr.put('/api/me/skills/'+name,json={'enabled':True})
check('toggle own skill', off is False)
check('admin cannot change default plugins', adm.put('/api/admin/host/profiles/default/plugins/'+P,json={'enabled':True}).status_code>=400)
adm.put(f'/api/admin/permissions/{S}',json={'changes':{'feature:own_plugins':False,'feature:own_skills':False}})
try:
    check('plugins denied when revoked', usr.get('/api/me/plugins').status_code==403)
    check('skills manage denied when revoked', usr.put('/api/me/skills/'+name,json={'enabled':False}).status_code==403)
finally:
    adm.put(f'/api/admin/permissions/{S}',json={'changes':{'feature:own_plugins':None,'feature:own_skills':None}})
check('audit records plugin change', any(a['action']=='profile.set_plugin' for a in adm.get('/api/admin/audit?limit=50').json()))
import time
for _ in range(60):  # plugin toggles restart the bridge; leave it warm for the next suite
    if usr.get('/api/commands',params={'text':'/'}).status_code==200: break
    time.sleep(2)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
