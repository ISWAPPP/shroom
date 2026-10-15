"""Usage accounting + monthly limits acceptance (real Haiku calls; no secrets printed)."""
import json, sys, time, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra) if extra else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=300,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); r.raise_for_status()
    c.headers['X-CSRF-Token']=r.json()['csrf']; return c,r.json()['user']
adm,_=login('admin'); usr,uu=login('tester')
def turn(c,did,text):
    r=c.post(f'/api/dialogs/{did}/chat',json={'text':text,'request_id':'usage-'+str(time.time_ns())})
    if r.status_code!=200: return r
    for _ in range(60):
        time.sleep(2)
        if c.get(f'/api/dialogs/{did}/sync').json()['state'] in ('complete','error','interrupted'): break
    return r
before=usr.get('/api/me/usage').json()
did=usr.post('/api/dialogs',json={'title':'usage test'}).json()['id']
r=turn(usr,did,'Reply with exactly USAGE_ONE'); check('turn ok', r.status_code==200)
after=usr.get('/api/me/usage').json()
check('usage recorded', after['turns']==before['turns']+1 and after['cost']>before['cost'] and after['tokens']>before['tokens'], (before,after))
a=adm.get('/api/admin/usage').json()
row=[u for u in a['users'] if u['id']==uu['id']][0]; prow=[p for p in a['profiles'] if p['name']=='webtest'][0]
check('admin sees user usage', row['cost']==after['cost'], row)
check('profile usage >= user usage', prow['cost']>=row['cost'])
check('daily series', len(a['daily'])>=1)
check('user cannot set limits 403', usr.put(f"/api/admin/limits/user:{uu['id']}",json={'usd_month':100}).status_code==403)
check('bad subject 400', adm.put('/api/admin/limits/foo',json={'usd_month':1}).status_code==400)
check('negative limit 422', adm.put(f"/api/admin/limits/user:{uu['id']}",json={'usd_month':-1}).status_code==422)
adm.put(f"/api/admin/limits/user:{uu['id']}",json={'usd_month':0.0001})
r=turn(usr,did,'Reply with exactly SHOULD_NOT_RUN'); check('user limit blocks chat 429', r.status_code==429, r.text[:120])
r=usr.post(f'/api/dialogs/{did}/command',json={'command':'/retry'}); check('user limit blocks /retry 429', r.status_code==429)
r=usr.post(f'/api/dialogs/{did}/command',json={'command':'/status'}); check('info command still works', r.status_code==200)
adm.put(f"/api/admin/limits/user:{uu['id']}",json={'usd_month':None})
adm.put('/api/admin/limits/profile:webtest',json={'usd_month':0.0001})
r=turn(usr,did,'Reply with exactly SHOULD_NOT_RUN'); check('profile limit blocks chat 429', r.status_code==429, r.text[:120])
adm.put('/api/admin/limits/profile:webtest',json={'usd_month':None})
r=turn(usr,did,'Reply with exactly USAGE_TWO'); check('limits cleared, chat works', r.status_code==200)
au=adm.get('/api/admin/audit',params={'action':'limit.'}).json()
check('limits audited', {'limit.update','limit.blocked'}<={x['action'] for x in au})
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
