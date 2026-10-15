"""Own AI subscriptions acceptance. Uses an obviously fake key string (not a real secret) to test storage/permissions;
model switching is verified via config, then reset to the admin-assigned model and a real Haiku answer."""
import json, sys, time, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
FAKE='portal-acceptance-not-a-real-key-000'
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:200] if extra else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=300,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); r.raise_for_status()
    c.headers['X-CSRF-Token']=r.json()['csrf']; return c,r.json()['user']
adm,_=login('admin'); usr,uu=login('tester'); S='user:'+uu['id']

import atexit
_SNAP=adm.get(f'/api/admin/permissions/{S}').json()
_KEYS=[k for k in _SNAP if k.startswith(('feature:','provider:'))]
if _KEYS: adm.put(f'/api/admin/permissions/{S}',json={'changes':{k:None for k in _KEYS}})
atexit.register(lambda: _KEYS and adm.put(f'/api/admin/permissions/{S}',json={'changes':{k:_SNAP[k] for k in _KEYS}}))
check('feature off by default 403', usr.get('/api/me/providers').status_code==403)
cat=adm.get('/api/admin/catalog',params={'profile':'webtest'}).json()
check('catalog lists providers', any(p['slug']=='deepseek' for p in cat['providers']), len(cat['providers']))
adm.put(f'/api/admin/permissions/{S}',json={'changes':{'feature:own_subscriptions':True,'provider:deepseek':True}})
p=usr.get('/api/me/providers').json()
check('only allowed providers listed', [x['slug'] for x in p['providers']]==['deepseek'], [x['slug'] for x in p['providers']])
check('assigned model known', p['assigned'] and p['assigned']['model'].startswith('claude-haiku'), p['assigned'])
check('disallowed provider refused 403', usr.put('/api/me/providers/gemini',json={'api_key':FAKE}).status_code==403)
r=usr.put('/api/me/providers/deepseek',json={'api_key':FAKE}); check('save own key', r.status_code==200 and r.json()['providers'][0]['own'], r.text)
check('key never echoed', FAKE not in r.text and FAKE not in usr.get('/api/me/providers').text)
check('cannot switch to non-own provider', usr.put('/api/me/model',json={'provider':'anthropic','model':'claude-opus-5-5'}).status_code==403)
r=usr.put('/api/me/model',json={'provider':'deepseek','model':'deepseek-chat'}); check('switch to own provider', r.status_code==200, r.text)
time.sleep(12)
check('profile now on own provider', usr.get('/api/me/providers').json()['current']['provider']=='deepseek')
r=usr.put('/api/me/model',json={'reset':True}); check('reset to admin model', r.status_code==200, r.text); time.sleep(12)
cur=usr.get('/api/me/providers').json()['current']; check('back on admin model', cur['provider']=='anthropic' and cur['model'].startswith('claude-haiku'), cur)
did=usr.post('/api/dialogs',json={'title':'own subs'}).json()['id']
usr.post(f'/api/dialogs/{did}/chat',json={'text':'Reply with exactly OWN_SUBS_RESET_OK','request_id':'own-'+str(time.time_ns())})
for _ in range(60):
    time.sleep(2)
    if usr.get(f'/api/dialogs/{did}/sync').json()['state'] in ('complete','error','interrupted'): break
m=[x for x in usr.get(f'/api/dialogs/{did}/history').json()['messages'] if x.get('role')=='assistant']
check('real answer after reset', 'OWN_SUBS_RESET_OK' in json.dumps(m[-1:]), m[-1:])
check('cannot remove admin-provided provider', usr.delete('/api/me/providers/anthropic').status_code==404)
r=usr.delete('/api/me/providers/deepseek'); check('remove own key', r.status_code==200 and not r.json()['providers'][0]['own'])
check('subscription audited', {'subscription.add','subscription.remove'}<={x['action'] for x in adm.get('/api/admin/audit',params={'actor':'tester'}).json()})
adm.put(f'/api/admin/permissions/{S}',json={'changes':{'feature:own_subscriptions':None,'provider:deepseek':None}})
check('feature revoked 403', usr.get('/api/me/providers').status_code==403)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
