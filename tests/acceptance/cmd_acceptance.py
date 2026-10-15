"""Exercise every default user command through the portal (inside backend container)."""
import json, sys, time, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
c=httpx.Client(base_url=B,verify=False,timeout=200,headers=O); r=c.post('/api/auth/login',json={'username':'tester','password':creds['tester']}); c.headers['X-CSRF-Token']=r.json()['csrf']
did=c.post('/api/dialogs',json={'title':'cmd test'}).json()['id']
def wait():
    for _ in range(60):
        time.sleep(2)
        if c.get(f'/api/dialogs/{did}/sync').json()['state'] in ('complete','error','interrupted'): return
def run(cmd):
    t=time.time(); r=c.post(f'/api/dialogs/{did}/command',json={'command':cmd}); dt=time.time()-t
    body=r.json(); txt=(body.get('output') or body.get('notice') or body.get('detail') or body.get('type') or '')
    print(f'{cmd:22} {r.status_code} {dt:5.1f}s {body.get("type","-"):16} {str(txt)[:90]!r}',flush=True); return r,body
c.post(f'/api/dialogs/{did}/chat',json={'text':'Reply with exactly: FIRST','request_id':'cmdt-'+str(int(time.time()))+'aaaaaa'}); wait()
for cmd in ['/help','/whoami','/version','/status','/usage','/context','/history','/title Мій тест','/title','/personality','/compress','/btw what did I ask?']:
    run(cmd)
r,b=run('/retry'); wait()
h=c.get(f'/api/dialogs/{did}/history').json()['messages']; print('after retry roles:',[m['role'] for m in h])
r,b=run('/undo'); h=c.get(f'/api/dialogs/{did}/history').json()['messages']; print('after undo roles:',[m['role'] for m in h])
r,b=run('/new Новий з команди'); print('new dialog listed:', any(d['id']==b.get('id') and d['title']=='Новий з команди' for d in c.get('/api/dialogs').json()))
titles=[d['title'] for d in c.get('/api/dialogs').json()]; print('retitled listed:', 'Мій тест' in titles)
ok='Мій тест' in titles
print(('PASS' if ok else 'FAIL')+' commands smoke')
