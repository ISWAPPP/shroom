"""TOTP 2FA acceptance on a temporary account (its secret exists only inside this test run)."""
import json, sys, time, hmac, struct, base64, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:160] if extra else ''),flush=True)
def code(secret,offset=0):
    key=base64.b32decode(secret+'='*(-len(secret)%8)); st=int(time.time()//30)+offset
    h=hmac.new(key,struct.pack('>Q',st),'sha1').digest(); o=h[-1]&15
    return '%06d'%((struct.unpack('>I',h[o:o+4])[0]&0x7fffffff)%1000000)
def cl(): return httpx.Client(base_url=B,verify=False,timeout=60,headers=O)
adm=cl(); r=adm.post('/api/auth/login',json={'username':'admin','password':creds['admin']}); adm.headers['X-CSRF-Token']=r.json()['csrf']
r=adm.post('/api/admin/users',json={'username':'totp-tmp','role':'user','profile':'webtest'}); uid=r.json()['id']; pw=r.json()['password']
u=cl(); r=u.post('/api/auth/login',json={'username':'totp-tmp','password':pw}); u.headers['X-CSRF-Token']=r.json()['csrf']
check('totp off initially', r.json()['user']['totp'] is False)
st=u.post('/api/auth/totp/setup').json(); secret=st['secret']
check('setup returns otpauth uri', st['uri'].startswith('otpauth://totp/') and secret in st['uri'])
check('wrong code rejected on enable', u.post('/api/auth/totp/enable',json={'code':'000000' if code(secret)!='000000' else '111111'}).status_code==400)
check('enable with valid code', u.post('/api/auth/totp/enable',json={'code':code(secret)}).json()=={'totp':True})
r=cl().post('/api/auth/login',json={'username':'totp-tmp','password':pw}); check('password alone not enough', r.status_code==401 and r.json()['detail']['totp_required'])
r=cl().post('/api/auth/login',json={'username':'totp-tmp','password':pw,'code':'123456' if code(secret)!='123456' else '654321'}); check('bad code refused', r.status_code==401)
time.sleep(31)
c2=cl(); r=c2.post('/api/auth/login',json={'username':'totp-tmp','password':pw,'code':code(secret)}); check('login with password+code', r.status_code==200, r.text)
used=code(secret)
r=cl().post('/api/auth/login',json={'username':'totp-tmp','password':pw,'code':used}); check('code replay refused', r.status_code==401)
check('admin list shows 2FA', any(x['username']=='totp-tmp' and x['totp'] for x in adm.get('/api/admin/users').json()))
check('admin reset 2FA', adm.post(f'/api/admin/users/{uid}/totp/reset').json()=={'totp':False})
r=cl().post('/api/auth/login',json={'username':'totp-tmp','password':pw}); check('after reset password alone works', r.status_code==200)
check('events audited', {'auth.totp_enabled','auth.totp_failed','user.totp_reset'}<={x['action'] for x in adm.get('/api/admin/audit',params={'actor':'totp-tmp'}).json()})
check('cleanup', adm.delete(f'/api/admin/users/{uid}').status_code==200)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
