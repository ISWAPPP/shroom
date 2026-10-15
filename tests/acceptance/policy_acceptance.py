"""Mandatory admin 2FA policy. Uses temporary admins; always restores the policy to off."""
import json, sys, time, hmac, struct, base64, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:160] if extra else ''),flush=True)
def code(secret):
    key=base64.b32decode(secret+'='*(-len(secret)%8)); h=hmac.new(key,struct.pack('>Q',int(time.time()//30)),'sha1').digest(); o=h[-1]&15
    return '%06d'%((struct.unpack('>I',h[o:o+4])[0]&0x7fffffff)%1000000)
def cl(): return httpx.Client(base_url=B,verify=False,timeout=60,headers=O)
def login(u,pw,c=''):
    x=cl(); r=x.post('/api/auth/login',json={'username':u,'password':pw,'code':c}); x.headers['X-CSRF-Token']=r.json().get('csrf',''); return x,r
adm,_=login('admin',creds['admin'])
a1=adm.post('/api/admin/users',json={'username':'pol-a1','role':'admin','profile':'default'}).json()
a2=adm.post('/api/admin/users',json={'username':'pol-a2','role':'admin','profile':'default'}).json()
try:
    c1,_=login('pol-a1',a1['password'])
    check('cannot enable policy without own 2FA', c1.put('/api/admin/policy',json={'require_admin_totp':True}).status_code==400)
    sec=c1.post('/api/auth/totp/setup').json()['secret']; c1.post('/api/auth/totp/enable',json={'code':code(sec)})
    check('enable policy', c1.put('/api/admin/policy',json={'require_admin_totp':True}).json()=={'require_admin_totp':True})
    c2,r=login('pol-a2',a2['password'])
    check('admin without 2FA can log in', r.status_code==200)
    me=c2.get('/api/auth/me').json()['user']; check('flagged must_enroll', me['must_enroll'] is True)
    check('admin APIs blocked until enrolled', c2.get('/api/admin/users').status_code==403)
    check('chat blocked until enrolled', c2.get('/api/dialogs').status_code==403)
    s2=c2.post('/api/auth/totp/setup'); check('can start setup', s2.status_code==200)
    c2.post('/api/auth/totp/enable',json={'code':code(s2.json()['secret'])})
    check('after enrolment admin APIs work', c2.get('/api/admin/users').status_code==200)
    time.sleep(31)
    check('cannot disable 2FA under policy', c2.post('/api/auth/totp/disable',json={'code':code(s2.json()['secret']),'password':a2['password']}).status_code==403)
    usr,r=login('tester',creds['tester']); check('ordinary users unaffected', usr.get('/api/dialogs').status_code==200)
finally:
    # main admin has no 2FA, so while policy is on it is restricted; switch off via the 2FA admin
    c1.put('/api/admin/policy',json={'require_admin_totp':False})
    check('policy restored off', adm.get('/api/admin/policy').json()=={'require_admin_totp':False})
    for x in (a1,a2): adm.delete(f"/api/admin/users/{x['id']}")
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
