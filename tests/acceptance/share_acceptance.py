"""Shared chats: snapshot link, read by another signed-in user, copy-and-continue (full and compressed) into the
reader's own profile, revoke. Real LLM calls on webtest (one short turn + one compression)."""
import json,sys,time,uuid,atexit,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=180,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
usr=login('tester');adm=login('admin');cleanup=[]
atexit.register(lambda: [c.delete(f'/api/dialogs/{i}') for c,i in cleanup])
d=usr.post('/api/dialogs',json={'title':'share test'}).json();did=d['id'];cleanup.append((usr,did))
usr.post(f'/api/dialogs/{did}/chat',json={'text':'Remember the code word: MAPLE-42. Reply with one short sentence.','files':[],'request_id':uuid.uuid4().hex})
for _ in range(90):
    if usr.get(f'/api/dialogs/{did}/sync').json()['state'] not in ('running','waiting'): break
    time.sleep(1)
check('no link yet',usr.get(f'/api/dialogs/{did}/share').json()['token'] is None)
s=usr.post(f'/api/dialogs/{did}/share').json();tok=s['token']
check('link created',bool(tok) and s['path']=='/s/'+tok and s['messages']>=2)
check('same link on refresh',usr.post(f'/api/dialogs/{did}/share').json()['token']==tok)
check('others cannot manage it',adm.post(f'/api/dialogs/{did}/share').status_code==404)
r=adm.get('/api/shares/'+tok).json()
check('another user reads the snapshot',r['own'] is False and r['owner']=='tester' and any('MAPLE-42' in m['text'] for m in r['messages']))
check('anonymous cannot read',httpx.get(B+'/api/shares/'+tok,verify=False,headers=O).status_code==401)
c=adm.post(f'/api/shares/{tok}/copy',json={'compress':False}).json();cleanup.append((adm,c['id']))
h=adm.get(f"/api/dialogs/{c['id']}/history",params={'tail':50}).json()['messages']
check('full copy lands in the reader profile with the transcript',any('MAPLE-42' in (m.get('text') or '') for m in h))
check('copy listed for the reader',any(x['id']==c['id'] for x in adm.get('/api/dialogs').json()))
c2=usr.post(f'/api/shares/{tok}/copy',json={'compress':True}).json();cleanup.append((usr,c2['id']))
h2=usr.get(f"/api/dialogs/{c2['id']}/history",params={'tail':50}).json()['messages']
check('compressed copy keeps the key fact',any('MAPLE-42' in (m.get('text') or '') for m in h2) and len(h2)==2)
usr.post(f"/api/dialogs/{c2['id']}/chat",json={'text':'What is the code word? Answer with the word only.','files':[],'request_id':uuid.uuid4().hex})
for _ in range(90):
    if usr.get(f"/api/dialogs/{c2['id']}/sync").json()['state'] not in ('running','waiting'): break
    time.sleep(1)
a=[m for m in usr.get(f"/api/dialogs/{c2['id']}/history",params={'tail':50}).json()['messages'] if m['role']=='assistant']
check('agent continues with the copied context',bool(a) and 'MAPLE-42' in (a[-1].get('text') or ''))
check('revoke',usr.delete(f'/api/dialogs/{did}/share').json()['revoked'] is True)
check('revoked link is gone',adm.get('/api/shares/'+tok).status_code==404)
check('bad token rejected',adm.get('/api/shares/x').status_code==422)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
