"""Cursor Agent CLI key: permission default, status shape, key validation against Cursor, owner profile refused, no key leaks."""
import json,sys,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
adm=login('admin');usr=login('tester')
check('anonymous refused',httpx.get(B+'/api/me/cursor',verify=False,headers=O).status_code==401)
check('feature on by default for role:user',usr.get('/api/me/permissions').json().get('feature:cursor_agent') is True)
r=usr.get('/api/me/cursor');d=r.json() if r.status_code==200 else {}
check('status shape',r.status_code==200 and {'connected','valid','email','key_name','sandbox','network','terminal'}<=set(d))
before=d.get('connected')
bogus='key_'+'0123456789abcdef'*4
r=usr.put('/api/me/cursor',json={'api_key':'not a key !!!!!!!!'});check('malformed key rejected',r.status_code==400)
r=usr.put('/api/me/cursor',json={'api_key':bogus});check('key unknown to Cursor rejected',r.status_code==400 and 'Cursor' in r.text)
check('too short rejected by schema',usr.put('/api/me/cursor',json={'api_key':'short'}).status_code==422)
d2=usr.get('/api/me/cursor').json();check('state unchanged after rejects',d2.get('connected')==before)
check('no key material in status',bogus not in json.dumps(d2) and 'api_key' not in d2)
check('owner profile refused',adm.get('/api/me/cursor').status_code==400)
log=adm.get('/api/admin/audit').json();items=log.get('items',log) if isinstance(log,dict) else log
check('key never in audit log',bogus not in json.dumps(items[:50],ensure_ascii=False))
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
