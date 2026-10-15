"""Per-chat model and reasoning: session-scoped switch (no restart, other chats and the profile default untouched),
draft pick sent with dialog creation, allowlist/permission enforcement. Real LLM turns on webtest (cheap)."""
import json, sqlite3, sys, time, uuid, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}; res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:300] if extra and not c else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=200,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); r.raise_for_status()
    c.headers['X-CSRF-Token']=r.json()['csrf']; return c,r.json()['user']
usr,uu=login('tester'); adm,_=login('admin'); U=uu['id']; S='user:'+U
db=sqlite3.connect('/data/portal.db')
def models_used(did):
    rows=db.execute('SELECT models FROM usage WHERE dialog=? ORDER BY ts',(did,)).fetchall(); return [r[0] or '' for r in rows]
def turn(did,text):
    r=usr.post(f'/api/dialogs/{did}/chat',json={'text':text,'files':[],'request_id':uuid.uuid4().hex,'stream':False}); r.raise_for_status()
    for _ in range(90):
        time.sleep(2); s=usr.get(f'/api/dialogs/{did}/sync').json()
        if s['state'] not in ('running','waiting'): return s['state']
    return 'timeout'
perm_before=adm.get(f'/api/admin/permissions/{S}').json()
allow_before=adm.get(f'/api/admin/users/{U}/models').json()['allowed']
made=[]
try:
    adm.put(f'/api/admin/permissions/{S}',json={'changes':{'cmd:reasoning':None,'feature:switch_model':None}})
    d=usr.get('/api/me/models').json(); default=d['current']
    check('chat switch allowed for user', d['chat_switch'] is True)
    sh=next(p for p in adm.get(f'/api/admin/users/{U}/models').json()['shared'] if p['slug']==default['provider'])
    other=next((m for m in sh['models'] if 'sonnet' in m and m!=default['model']),None) or next(m for m in sh['models'] if m!=default['model'])
    r=usr.post('/api/dialogs',json={'provider':default['provider'],'model':other})
    check('non-allowed shared model refused at creation', r.status_code==403, r.text)
    adm.put(f'/api/admin/users/{U}/models',json={'allowed':[f"{default['provider']}/{other}"]})
    r=usr.post('/api/dialogs',json={'provider':default['provider'],'model':other,'effort':'low'})
    check('reasoning pick needs cmd:reasoning', r.status_code==403, r.text)
    adm.put(f'/api/admin/permissions/{S}',json={'changes':{'cmd:reasoning':True}})
    check('chat reasoning flag', usr.get('/api/me/models').json()['chat_reason'] is True)
    r=usr.post('/api/dialogs',json={'provider':default['provider'],'model':other,'effort':'low'}); a=r.json(); made.append(a['id'])
    check('draft pick stored on creation', r.status_code==200 and a['runtime']=={'provider':default['provider'],'model':other,'effort':'low'}, r.text)
    b=usr.post('/api/dialogs',json={}).json(); made.append(b['id'])
    check('plain chat follows default', b['runtime']=={'provider':None,'model':None,'effort':None})
    check('chat A turn', turn(a['id'],'Reply with exactly: A')=='complete')
    check('chat B turn', turn(b['id'],'Reply with exactly: B')=='complete')
    ua,ub=models_used(a['id']),models_used(b['id'])
    check('chat A ran on its own model', ua and other in ua[-1] and default['model'] not in ua[-1], ua)
    check('chat B ran on the default', ub and default['model'] in ub[-1], ub)
    check('profile default untouched', usr.get('/api/me/models').json()['current']==default)
    r=usr.put(f"/api/dialogs/{a['id']}/model",json={'provider':default['provider'],'model':default['model']})
    check('switch existing chat', r.status_code==200 and r.json()['model']==default['model'], r.text)
    check('chat A turn after switch', turn(a['id'],'Reply with exactly: A2')=='complete')
    ua=models_used(a['id'])
    check('switch applied to next turn', len(ua)>=2 and default['model'] in ua[-1], ua)
    r=usr.put(f"/api/dialogs/{a['id']}/reasoning",json={'effort':'high'})
    check('switch chat reasoning', r.status_code==200 and r.json()['effort']=='high', r.text)
    check('bad effort refused', usr.put(f"/api/dialogs/{a['id']}/reasoning",json={'effort':'turbo'}).status_code==400)
    bad=next((m for m in sh['models'] if m not in (other,default['model'])),None)
    if bad: check('non-allowed model refused on switch', usr.put(f"/api/dialogs/{a['id']}/model",json={'provider':default['provider'],'model':bad}).status_code==403)
    lst=usr.get('/api/dialogs',params={'limit':5,'include':a['id']}).json()['items']
    row=next((x for x in lst if x['id']==a['id']),None)
    check('dialog list carries runtime', row and row['runtime']=={'provider':default['provider'],'model':default['model'],'effort':'high'}, row)
    ad=adm.get('/api/dialogs').json()
    if ad: check("other user's chat is 404", usr.put(f"/api/dialogs/{ad[0]['id']}/model",json={'provider':default['provider'],'model':default['model']}).status_code==404)
    check('limits per provider', usr.get('/api/me/limits',params={'provider':default['provider']}).status_code==200)
finally:
    for did in made: usr.delete(f'/api/dialogs/{did}')
    adm.put(f'/api/admin/users/{U}/models',json={'allowed':allow_before})
    keys={k:perm_before.get(k) for k in ('cmd:reasoning','feature:switch_model')} if isinstance(perm_before,dict) else {}
    adm.put(f'/api/admin/permissions/{S}',json={'changes':{k:(v if isinstance(v,bool) else None) for k,v in keys.items()}})
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()): sys.exit(1)
