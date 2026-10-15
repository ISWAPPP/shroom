"""Composer actions while the agent works (POST /api/dialogs/{id}/side): steer reaches the running turn, btw and
background answers arrive as sync events, permissions are enforced server-side. Real LLM calls on webtest."""
import json,sys,time,atexit,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
adm=login('admin');usr=login('tester')
tester=next(u for u in adm.get('/api/admin/users').json() if u['username']=='tester')
S='user:'+tester['id'];KEYS=('cmd:bg','cmd:steer','cmd:btw')
snap=adm.get(f'/api/admin/permissions/{S}').json()
atexit.register(lambda: adm.put(f'/api/admin/permissions/{S}',json={'changes':{k:snap.get(k) for k in KEYS}}))
adm.put(f'/api/admin/permissions/{S}',json={'changes':{'cmd:bg':None,'cmd:steer':None,'cmd:btw':None}})
p=usr.get('/api/me/permissions').json()
check('defaults: steer+btw allowed, bg denied',p.get('cmd:steer') is True and p.get('cmd:btw') is True and p.get('cmd:bg') is False)
d=usr.post('/api/dialogs',json={'title':'busy-actions test'}).json();did=d['id']
atexit.register(lambda: usr.delete(f'/api/dialogs/{did}'))
check('bg denied without permission',usr.post(f'/api/dialogs/{did}/side',json={'mode':'bg','text':'hi'}).status_code==403)
check('unknown mode rejected',usr.post(f'/api/dialogs/{did}/side',json={'mode':'queue','text':'hi'}).status_code==422)
adm.put(f'/api/admin/permissions/{S}',json={'changes':{'cmd:bg':True}})
r=usr.post(f'/api/dialogs/{did}/chat',json={'text':'Use the terminal tool to run exactly: sleep 30 && echo slept. Then reply with one short sentence about what it printed.','files':[]})
check('turn started',r.status_code==200)
events=[];cursor=0;epoch=''
def poll():
    global cursor,epoch
    s=usr.get(f'/api/dialogs/{did}/sync',params={'after':cursor,'epoch':epoch}).json();cursor=s['cursor'];epoch=s['epoch'];events.extend(s['events']);return s
for _ in range(60):
    s=poll()
    if any(e['type']=='tool.start' for e in events): break
    time.sleep(1)
check('agent is running a tool',s['state'] in ('running','waiting') and any(e['type']=='tool.start' for e in events))
r=usr.post(f'/api/dialogs/{did}/side',json={'mode':'steer','text':'Important: end your final reply with the word PELMEN in capitals.'})
check('steer accepted mid-turn',r.status_code==200 and r.json().get('status')=='queued')
r=usr.post(f'/api/dialogs/{did}/side',json={'mode':'btw','text':'Side question: what is 2+2? Answer with just the digit.'})
check('btw started',r.status_code==200 and r.json().get('status')=='started')
r=usr.post(f'/api/dialogs/{did}/side',json={'mode':'bg','text':'Reply with exactly the text BG-OK and nothing else. Do not use tools.'})
check('background started',r.status_code==200 and r.json().get('status')=='started')
for _ in range(180):
    s=poll()
    types={e['type'] for e in events}
    if s['state']=='complete' and 'btw.complete' in types and 'background.complete' in types: break
    time.sleep(1)
btw=[e for e in events if e['type']=='btw.complete'];bg=[e for e in events if e['type']=='background.complete']
check('btw answer delivered','4' in str(btw[-1]['payload'].get('text','')) if btw else False)
check('background answer delivered','BG-OK' in str(bg[-1]['payload'].get('text','')) if bg else False)
check('turn completed',s['state']=='complete')
hist=usr.get(f'/api/dialogs/{did}/history').json()['messages']
reply=' '.join(str(m.get('text') or m.get('content') or '') for m in hist if m.get('role')=='assistant')
check('steer reached the running agent','PELMEN' in reply.upper())
log=adm.get('/api/admin/audit').json();items=log.get('items',log) if isinstance(log,dict) else log
check('side actions audited',{'/steer','/btw','/bg'}<= {e.get('target') for e in items[:40] if e.get('action')=='command.run'})
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
