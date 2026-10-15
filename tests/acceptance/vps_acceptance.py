"""VPS resources for the admin dashboard: /api/admin/vps (latest reading + history series), admin-only."""
import json, sys, time, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:200] if extra else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); c.headers['X-CSRF-Token']=r.json()['csrf']; return c
usr=login('tester'); adm=login('admin')
check('user cannot read', usr.get('/api/admin/vps').status_code==403)
check('bad range rejected', adm.get('/api/admin/vps?range=1y').status_code==422)
d={}
for _ in range(8):   # the sampler runs every 15 s; after a backend restart the first reading may still be pending
    r=adm.get('/api/admin/vps?range=1h'); d=r.json()
    if d.get('now') and d['now'].get('cpu'): break
    time.sleep(6)
n=d.get('now') or {}
check('reading present', bool(n) and not d.get('stale'), {k:d.get(k) for k in ('stale','step')})
check('cpu/mem/disk sane', n and 0<=n['cpu']['total']<=1 and 0<n['mem']['used']<n['mem']['total'] and n['disks'] and all(0<x['used']<x['total'] for x in n['disks']))
check('rates and load', n and n['rates'] and all(v>=0 for v in n['rates'].values()) and len(n['load'])==3)
check('units grouped', n and any(u['group']=='bridges' and u['name']=='default' for u in n['units']) and len({(u['group'],u['name']) for u in n['units']})==len(n['units']))
for rg in ('6h','24h','7d'):
    s=adm.get('/api/admin/vps?range='+rg).json()
    check('series '+rg, isinstance(s['series'],list) and s['step']>=15 and len(s['series'])<=130 and all(0<=p['cpu']<=1 for p in s['series']), len(s['series']))
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
