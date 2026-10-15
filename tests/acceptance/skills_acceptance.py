"""Shared library + personal skills acceptance (real Haiku calls; no secrets printed)."""
import json, sys, time, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:220] if extra else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=300,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); r.raise_for_status()
    c.headers['X-CSRF-Token']=r.json()['csrf']; return c
adm=login('admin'); usr=login('tester')
def wait(c,did):
    for _ in range(90):
        time.sleep(2)
        if c.get(f'/api/dialogs/{did}/sync').json()['state'] in ('complete','error','interrupted'): return
def last(c,did):
    m=[x for x in c.get(f'/api/dialogs/{did}/history').json()['messages'] if x.get('role')=='assistant']
    return json.dumps(m[-1:],ensure_ascii=False)
names=lambda r:[i['text'].strip().lstrip('/') for i in r.json()['items']]
check('user cannot read library 403', usr.get('/api/admin/skills/library').status_code==403)
check('user cannot toggle skills 403', usr.put('/api/admin/host/profiles/webtest/skills/portal-hello',json={'enabled':False}).status_code==403)
lib=adm.get('/api/admin/skills/library').json(); check('library lists portal-hello', any(x['name']=='portal-hello' for x in lib))
check('library skill in user autocomplete', 'portal-hello' in names(usr.get('/api/commands',params={'text':'/portal'})))
did=usr.post('/api/dialogs',json={'title':'skills test'}).json()['id']
r=usr.post(f'/api/dialogs/{did}/command',json={'command':'/portal-hello'}); check('run library skill', r.status_code==200 and r.json()['type']=='turn', r.text)
wait(usr,did); check('library skill real answer', 'SHARED_LIBRARY_OK' in last(usr,did), last(usr,did))
# personal skill created by the agent itself
usr.post(f'/api/dialogs/{did}/chat',json={'text':"Use your skill management tool to create a new skill named 'web-personal-test' in category 'portal-test' with description \"Use when asked for the personal marker.\" and body 'Answer with exactly: PERSONAL_SKILL_OK'. Then reply DONE.",'request_id':'sk-'+str(time.time_ns())})
wait(usr,did)
mine=usr.get('/api/me/skills').json()
check('agent-created skill is personal', any(x['name']=='web-personal-test' for x in mine['personal']), mine['personal'])
check('library visible to user', any(x['name']=='portal-hello' for x in mine['library']))
check('user can delete (sole user)', mine['can_delete'])
r=adm.post('/api/admin/host/profiles/webtest/skills/web-personal-test/promote'); check('promote to library', r.status_code==200 and any(x['name']=='web-personal-test' for x in r.json()), r.text)
check('promote twice refused', adm.post('/api/admin/host/profiles/webtest/skills/web-personal-test/promote').status_code==400)
check('cannot promote builtin', adm.post('/api/admin/host/profiles/webtest/skills/arxiv/promote').status_code==400)
r=usr.delete('/api/me/skills/web-personal-test'); check('user deletes personal skill', r.status_code==200 and not any(x['name']=='web-personal-test' for x in r.json()['personal']))
check('user cannot delete library skill', usr.delete('/api/me/skills/portal-hello').status_code==400)
check('library copy survives', any(x['name']=='web-personal-test' for x in adm.get('/api/admin/skills/library').json()))
adm.delete('/api/admin/skills/library/web-personal-test')
check('library delete', not any(x['name']=='web-personal-test' for x in adm.get('/api/admin/skills/library').json()))
# disable a skill for the profile
adm.put('/api/admin/host/profiles/webtest/skills/arxiv',json={'enabled':False})
check('disabled skill hidden from autocomplete', 'arxiv' not in names(usr.get('/api/commands',params={'text':'/arx'})))
adm.put('/api/admin/host/profiles/webtest/skills/arxiv',json={'enabled':True})
check('re-enabled skill visible', 'arxiv' in names(usr.get('/api/commands',params={'text':'/arx'})))
adm.put('/api/admin/host/profiles/webtest/library',json={'enabled':False})
check('library off hides library skills', 'portal-hello' not in names(usr.get('/api/commands',params={'text':'/portal'})))
adm.put('/api/admin/host/profiles/webtest/library',json={'enabled':True})
check('library on again', 'portal-hello' in names(usr.get('/api/commands',params={'text':'/portal'})))
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
