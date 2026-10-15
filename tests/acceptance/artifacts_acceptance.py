"""Artifacts: files attached to dialogs are listed per user, viewable, downloadable, deletable; isolation between users."""
import json, sys, base64, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:200] if extra else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); c.headers['X-CSRF-Token']=r.json()['csrf']; return c
usr=login('tester'); adm=login('admin')
d=usr.post('/api/dialogs',json={'title':'artifacts-test'}).json(); did=d['id']
png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==')
im=usr.post(f'/api/dialogs/{did}/files',files={'file':('clipboard-test.png',png,'image/png')}).json()
tx=usr.post(f'/api/dialogs/{did}/files',files={'file':('pasted-text-test.txt',('лог '*800).encode(),'text/plain')}).json()
lst=usr.get('/api/me/files').json(); ids={x['id']:x for x in lst}
check('both listed', im['id'] in ids and tx['id'] in ids)
check('text has preview', ids[tx['id']]['preview'].startswith('лог'))
check('has dialog title and time', ids[im['id']]['title']=='artifacts-test' and ids[im['id']]['created'])
r=usr.get('/api/me/files/'+im['id']); check('image inline', r.status_code==200 and r.headers['content-type']=='image/png' and r.content==png and 'inline' in r.headers['content-disposition'])
r=usr.get('/api/me/files/'+tx['id']+'?download=1'); check('text download', r.status_code==200 and 'attachment' in r.headers['content-disposition'] and 'nosniff' in r.headers.get('x-content-type-options',''), dict(r.headers))
check('other user 404', adm.get('/api/me/files/'+im['id']).status_code==404 and im['id'] not in {x['id'] for x in adm.get('/api/me/files').json()})
check('other user cannot delete', adm.delete('/api/me/files/'+im['id']).status_code==404)
check('delete', usr.delete('/api/me/files/'+im['id']).status_code==200 and usr.get('/api/me/files/'+im['id']).status_code==404)
usr.delete('/api/me/files/'+tx['id']); usr.delete(f'/api/dialogs/{did}')
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
