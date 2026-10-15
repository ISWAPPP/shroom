"""Subscription limit gauges: /api/me/limits per user, /api/admin/limits shared + per-user, admin-only."""
import json, sys, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:200] if extra else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); c.headers['X-CSRF-Token']=r.json()['csrf']; return c
usr=login('tester'); adm=login('admin')
m=usr.get('/api/me/limits'); d=m.json()
check('user limits', m.status_code==200 and 'windows' in d and 'own' in d, m.text)
check('windows have percent', all(0<=w['used']<=100 for w in d['windows']) and (d['windows'] or d['unavailable']))
check('user cannot read admin', usr.get('/api/admin/limits').status_code==403)
a=adm.get('/api/admin/limits').json()
check('shared claude+gpt', {s['provider'] for s in a['shared']}>={'anthropic','openai-codex'}, [s['provider'] for s in a['shared']])
check('per-user rows', any(u['username']=='tester' and 'limits' in u for u in a['users']))
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
