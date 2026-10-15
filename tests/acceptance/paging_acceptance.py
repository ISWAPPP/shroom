"""Gradual loading: paged chat archive (/api/dialogs?limit=&include=&q=) and message tail (/history?tail=). Read-only on admin."""
import json,sys,time,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=120,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
adm=login('admin')
full=adm.get('/api/dialogs').json()
check('legacy shape still a list',isinstance(full,list))
edge=time.time()-8*3600
recent=[d for d in full if d['last']>=edge];old=[d for d in full if d['last']<edge]
p=adm.get('/api/dialogs',params={'limit':1}).json()
check('page: all recent + 1 archived',len(p['items'])==len(recent)+min(1,len(old)) and p['archive_total']==len(old))
check('more flag',p['more']==(len(old)>1))
p0=adm.get('/api/dialogs',params={'limit':0}).json()
check('limit 0: only recent',[d['id'] for d in p0['items']]==[d['id'] for d in recent])
if old:
    tgt=old[-1]['id'];pi=adm.get('/api/dialogs',params={'limit':0,'include':tgt}).json()
    check('include keeps open chat listed',tgt in {d['id'] for d in pi['items']})
    word=old[-1]['title'].split()[0]
    ps=adm.get('/api/dialogs',params={'q':word,'limit':50}).json()
    check('search covers the archive',tgt in {d['id'] for d in ps['items']} or ps['total']>50)
check('unread counts every chat',p['unread']==sum(d['unread'] or 0 for d in full))
cand=[d for d in full if not d['unread']]
best=None
for d in cand[:8]:
    h=adm.get(f"/api/dialogs/{d['id']}/history",params={'tail':5000}).json()
    if h['total']>=6: best=(d['id'],h);break
if best:
    did,allh=best;t=adm.get(f'/api/dialogs/{did}/history',params={'tail':2}).json()
    check('tail returns last messages only',0<len(t['messages'])<allh['total'] and t['more'] and t['start']+len(t['messages'])==allh['total'])
    check('tail starts at a user message',t['messages'][0]['role']=='user')
    check('tail is the end of the full list',t['messages']==allh['messages'][t['start']:])
    t2=adm.get(f'/api/dialogs/{did}/history',params={'tail':t['total']}).json()
    check('large tail = everything',t2['start']==0 and not t2['more'])
    r=adm.get(f'/api/dialogs/{did}/history',params={'tail':2});tag=r.headers.get('etag','')
    check('tail history carries an ETag',bool(tag) and 'no-cache' in r.headers.get('cache-control',''))
    check('unchanged history answers 304',adm.get(f'/api/dialogs/{did}/history',params={'tail':2},headers={'If-None-Match':tag}).status_code==304)
    check('other tail is not 304',adm.get(f'/api/dialogs/{did}/history',params={'tail':t['total']},headers={'If-None-Match':tag}).status_code==200)
else: check('found a dialog with 6+ messages',False)
check('bad tail rejected',adm.get(f"/api/dialogs/{full[0]['id']}/history",params={'tail':0}).status_code==422)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
