"""Sidebar chat states (/api/dialogs/activity): running while a turn works in a chat that is not open, done until the
chat is opened, approval/question while the agent waits; a second chat cannot start while one runs (clear message)."""
import json,sys,time,atexit,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
usr=login('tester')
a=usr.post('/api/dialogs',json={'title':'status test A'}).json()['id'];b=usr.post('/api/dialogs',json={'title':'status test B'}).json()['id']
atexit.register(lambda:[usr.delete(f'/api/dialogs/{x}') for x in (a,b)])
check('nothing to mark at start',a not in usr.get('/api/dialogs/activity').json())
r=usr.post(f'/api/dialogs/{a}/chat',json={'text':'Use the terminal tool to run exactly: sleep 15 && echo ok. Then reply with one word: done.','files':[]})
check('turn started in A',r.status_code==200)
seen=set()
for _ in range(20):
    st=usr.get('/api/dialogs/activity',params={'exclude':b}).json().get(a)
    if st: seen.add(st)
    if st=='running': break
    time.sleep(1)
check('A marked running while another chat is open','running' in seen)
check('open chat excluded',a not in usr.get('/api/dialogs/activity',params={'exclude':a}).json())
r=usr.post(f'/api/dialogs/{b}/chat',json={'text':'hi','files':[]})
check('second chat refused with the busy chat named',r.status_code==409 and 'status test A' in r.text)
final=None
for _ in range(120):
    final=usr.get('/api/dialogs/activity',params={'exclude':b}).json().get(a)
    if final and final!='running': break
    time.sleep(2)
check('A marked done after finishing, not yet opened',final=='done')
check('still done on the next poll',usr.get('/api/dialogs/activity').json().get(a)=='done')
usr.get(f'/api/dialogs/{a}/history',params={'tail':30})
check('opening the chat clears the mark',a not in usr.get('/api/dialogs/activity').json())
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
