"""Chat search over message text (Hermes FTS5 via host op `search`): a unique word written by the user and repeated
by the agent is found in both roles and mapped to the right dialog; titles still match; another user's chats never
show up. Needs the owner bridge to run the current profile_admin."""
import json,sys,time,uuid,atexit,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
usr=login('tester');adm=login('admin')
word='zorbix'+uuid.uuid4().hex[:6]
d=usr.post('/api/dialogs',json={'title':'search test'}).json();did=d['id']
atexit.register(lambda: usr.delete(f'/api/dialogs/{did}'))
usr.post(f'/api/dialogs/{did}/chat',json={'text':f'Repeat exactly this one word and nothing else: {word}','files':[],'request_id':uuid.uuid4().hex})
for _ in range(90):
    if usr.get(f'/api/dialogs/{did}/sync').json()['state'] not in ('running','waiting'): break
    time.sleep(1)
r=usr.get('/api/dialogs/search',params={'q':word});j=r.json()
hits=[m for m in j['messages'] if m['id']==did]
check('search answers',r.status_code==200 and 'titles' in j)
check('user message found in its dialog',any(m['role']=='user' for m in hits))
check('agent reply found too',any(m['role']=='assistant' for m in hits))
check('snippet marks the match',any('>>>' in m['snippet'] for m in hits))
check('title search still works',any(x['id']==did for x in usr.get('/api/dialogs/search',params={'q':'search test'}).json()['titles']))
check("other users never see it",not any(m['id']==did for m in adm.get('/api/dialogs/search',params={'q':word}).json()['messages']))
check('too short query rejected',usr.get('/api/dialogs/search',params={'q':'a'}).status_code==422)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
