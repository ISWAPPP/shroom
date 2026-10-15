"""OAuth device-code start/status/cancel for own subscriptions. The sign-in itself is NOT completed
(that needs a real person); the one-time pairing code is checked for shape only and never printed."""
import json, sys, time, re, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:160] if extra else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); c.headers['X-CSRF-Token']=r.json()['csrf']; return c,r.json()['user']
adm,_=login('admin'); usr,uu=login('tester'); S='user:'+uu['id']
import atexit
_SNAP=adm.get(f'/api/admin/permissions/{S}').json(); _KEYS=[k for k in _SNAP if k.startswith(('feature:','provider:'))]
if _KEYS: adm.put(f'/api/admin/permissions/{S}',json={'changes':{k:None for k in _KEYS}})
atexit.register(lambda: _KEYS and adm.put(f'/api/admin/permissions/{S}',json={'changes':{k:_SNAP[k] for k in _KEYS}}))
check('oauth needs permission', usr.post('/api/me/oauth/openai-codex').status_code==403)
adm.put(f'/api/admin/permissions/{S}',json={'changes':{'feature:own_subscriptions':True,'provider:openai-codex':True}})
try:
    p=usr.get('/api/me/providers').json()
    check('oauth provider listed', [x['slug'] for x in p['oauth']]==['openai-codex'], [x['slug'] for x in p['oauth']])
    check('not allowed oauth provider 403', usr.post('/api/me/oauth/nous').status_code==403)
    st=usr.post('/api/me/oauth/openai-codex').json()
    check('device flow started', st['state']=='running' and st['url'].startswith('https://auth.openai.com/'), st['url'])
    check('pairing code shape', bool(re.fullmatch(r'[A-Z0-9]{3,6}(-[A-Z0-9]{3,6})+',st['code'])))
    check('status running', usr.get('/api/me/oauth/'+st['job']).json()['state']=='running')
    adm2=adm.get('/api/me/oauth/'+st['job']); check('other user cannot see job', adm2.status_code in (403,404))
    check('cancel', usr.delete('/api/me/oauth/'+st['job']).json()['state']=='cancelled')
    time.sleep(2)
    check('job gone after cancel', usr.get('/api/me/oauth/'+st['job']).status_code==404)
    check('not marked as own', not usr.get('/api/me/providers').json()['oauth'][0]['own'])
finally:
    adm.put(f'/api/admin/permissions/{S}',json={'changes':{'feature:own_subscriptions':None,'provider:openai-codex':None}})
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
