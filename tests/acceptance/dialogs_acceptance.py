"""Chat list: last-activity field, rename, delete (with files), owner isolation."""
import json, sys, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:200] if extra else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); c.headers['X-CSRF-Token']=r.json()['csrf']; return c
usr=login('tester'); adm=login('admin')
did=usr.post('/api/dialogs',json={'title':'dlg-test'}).json()['id']
check('empty chat hidden from list', did not in {d['id'] for d in usr.get('/api/dialogs').json()})
check('listed chats have last', all(d.get('last') and d['last']>=d['created'] for d in usr.get('/api/dialogs').json()))
r=usr.patch(f'/api/dialogs/{did}',json={'title':'  Нова   назва '}); check('rename', r.status_code==200 and r.json()['title']=='Нова назва')

check('empty title rejected', usr.patch(f'/api/dialogs/{did}',json={'title':'   '}).status_code in (400,422))
check('other user cannot rename', adm.patch(f'/api/dialogs/{did}',json={'title':'x'}).status_code==404)
check('other user cannot delete', adm.delete(f'/api/dialogs/{did}').status_code==404)
f=usr.post(f'/api/dialogs/{did}/files',files={'file':('a.txt',b'hello','text/plain')}).json()
r=usr.delete(f'/api/dialogs/{did}'); check('delete', r.status_code==200, r.text)
check('gone from list', did not in {d['id'] for d in usr.get('/api/dialogs').json()})
check('files gone', usr.get('/api/me/files/'+f['id']).status_code==404)
check('audit', any(a['action']=='chat.delete' for a in adm.get('/api/admin/audit?limit=20').json()))
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
