"""Real permission acceptance test (runs inside backend container; never prints passwords)."""
import json, sys, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+extra if extra else ''))
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=200,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); r.raise_for_status()
    c.headers['X-CSRF-Token']=r.json()['csrf']; return c,r.json()['user']
adm,au=login('admin'); usr,uu=login('tester')
import atexit
S='user:'+uu['id']; _SNAP=adm.get(f'/api/admin/permissions/{S}').json()
_KEYS=[k for k in _SNAP if k.startswith(('feature:','provider:'))]
if _KEYS: adm.put(f'/api/admin/permissions/{S}',json={'changes':{k:None for k in _KEYS}})
atexit.register(lambda: _KEYS and adm.put(f'/api/admin/permissions/{S}',json={'changes':{k:_SNAP[k] for k in _KEYS}}))
names=lambda r:[i['text'].lstrip('/') for i in r.json()['items']]
t_all=names(usr.get('/api/commands',params={'text':'/'}))
check('tester list has no yolo', 'yolo' not in t_all, str(len(t_all))+' items')
check('tester list has help', 'help' in t_all)
check('tester /y has no yolo', 'yolo' not in names(usr.get('/api/commands',params={'text':'/y'})))
check('tester /plu has no plugins', 'plugins' not in names(usr.get('/api/commands',params={'text':'/plu'})))
check('tester sees skills', any(i['kind']=='skill' for i in usr.get('/api/commands',params={'text':'/a'}).json()['items']))
check('admin /y has yolo', 'yolo' in names(adm.get('/api/commands',params={'text':'/y'})))
did=[d for d in usr.get('/api/dialogs').json() if d['title']=='multiuser test'][0]['id']
r=usr.post(f'/api/dialogs/{did}/command',json={'command':'/yolo'}); check('tester /yolo direct API 403', r.status_code==403, r.text[:80])
r=usr.post(f'/api/dialogs/{did}/command',json={'command':'/plugins'}); check('tester /plugins 403', r.status_code==403)
r=usr.post(f'/api/dialogs/{did}/command',json={'command':'/version'}); check('tester /version runs', r.status_code==200 and r.json().get('type')=='output', r.text[:120])
check('user cannot read perms 403', usr.get('/api/admin/permissions/role:user').status_code==403)
check('user cannot write perms 403', usr.put('/api/admin/permissions/user:'+uu['id'],json={'changes':{'cmd:yolo':True}}).status_code==403)
cat=adm.get('/api/admin/catalog',params={'profile':'webtest'}).json()
check('admin catalog', len(cat['items'])>100 and any(f['key']=='feature:own_subscriptions' for f in cat['features']), str(len(cat['items']))+' items')
adm.put('/api/admin/permissions/user:'+uu['id'],json={'changes':{'cmd:version':False}})
r=usr.post(f'/api/dialogs/{did}/command',json={'command':'/version'}); check('per-user deny overrides role allow', r.status_code==403)
adm.put('/api/admin/permissions/user:'+uu['id'],json={'changes':{'cmd:version':None,'cmd:plugins':True}})
check('per-user allow shows /plugins', 'plugins' in names(usr.get('/api/commands',params={'text':'/plu'})))
adm.put('/api/admin/permissions/user:'+uu['id'],json={'changes':{'cmd:plugins':None}})
check('reverted', 'plugins' not in names(usr.get('/api/commands',params={'text':'/plu'})))
check('bad key rejected 400', adm.put('/api/admin/permissions/role:user',json={'changes':{'rm -rf':True}}).status_code==400)
check('feature defaults', usr.get('/api/me/permissions').json()=={'feature:own_subscriptions':False,'feature:own_skills':True,'feature:own_plugins':True,'feature:switch_model':True,'feature:own_soul':True,'feature:own_memory':True})
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
