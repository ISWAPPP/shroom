"""Scheduled jobs: agent creates a native Hermes cron from a portal chat, the portal links it to that chat, enforces policy,
delivers a real run's report into the chat transcript, accounts usage; isolation and permission checks. Cleans up."""
import json,sys,time,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
 c=httpx.Client(base_url=B,verify=False,timeout=200,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
usr=login('tester');adm=login('admin')
uid=usr.get('/api/auth/me').json()['user']['id'];perms_before=adm.get(f'/api/admin/permissions/user:{uid}').json()
def wait_turn(did,limit=180):
 end=time.time()+limit
 while time.time()<end:
  s=usr.get(f'/api/dialogs/{did}/sync').json()
  if s['state'] not in ('running','waiting'):return s['state']
  time.sleep(2)
 return 'timeout'
def jobs():return usr.get('/api/cron').json()['jobs']
did=None;jid=None
try:
 r=usr.get('/api/cron');check('list 200',r.status_code==200);d=r.json()
 check('user limits shown',d['limits']=={'max_jobs':5,'min_minutes':60})
 check('scheduler alive',d['scheduler_ok'])
 before={j['id'] for j in d['jobs']}
 r=usr.post('/api/cron/prepare');check('prepare 200',r.status_code==200)
 check('agent ready (cronjob tool on)',usr.get('/api/cron').json()['agent_ready'])
 did=usr.post('/api/dialogs',json={}).json()['id']
 usr.post(f'/api/dialogs/{did}/chat',json={'text':'Створи заплановане завдання інструментом cronjob одразу, без уточнень: розклад "0 9 * * *", назва «Acceptance cron», завдання: відповісти рівно CRON_ACCEPT_OK.'}).raise_for_status()
 check('turn completed',wait_turn(did)=='complete')
 end=time.time()+60;job=None
 while time.time()<end and not job:
  job=next((j for j in jobs() if j['id'] not in before),None);time.sleep(0 if job else 5)
 check('job listed',job is not None);jid=job['id']
 check('job linked to its chat',job['dialog']==did)
 check('schedule kept',job['schedule']=='0 9 * * *' and job['enabled'])
 r=usr.patch(f'/api/cron/{jid}',json={'schedule':'every 30m'});check('too frequent schedule rejected',r.status_code==400)
 r=usr.patch(f'/api/cron/{jid}',json={'name':'Acceptance cron 2'});check('rename ok',r.status_code==200 and r.json()['job']['name']=='Acceptance cron 2')
 r=usr.patch(f'/api/cron/{jid}',json={'schedule':'garbage x'});check('bad schedule rejected',r.status_code==400)
 spent0=usr.get('/api/me/usage').json()['turns']
 check('run now',usr.post(f'/api/cron/{jid}/action',json={'action':'run'}).status_code==200)
 end=time.time()+240;report=None
 while time.time()<end and not report:
  time.sleep(8)
  if [x for x in usr.get('/api/dialogs').json() if x['id']==did and x.get('unread')]:
   report=[m for m in usr.get(f'/api/dialogs/{did}/history').json()['messages'] if str(m.get('text') or m.get('content') or '').startswith('[cron-report job='+jid)]
 check('report delivered into the job chat',bool(report) and 'CRON_ACCEPT_OK' in str(report[-1].get('text') or report[-1].get('content')))
 check('unread cleared after reading',not [x for x in usr.get('/api/dialogs').json() if x['id']==did and x.get('unread')])
 j=next(j for j in jobs() if j['id']==jid);check('run in history',len(j['runs'])>=1)
 r=usr.get(f'/api/cron/{jid}/runs/{j["runs"][0]}');check('run report readable',r.status_code==200 and 'CRON_ACCEPT_OK' in (r.json()['answer'] or ''))
 check('run usage accounted',usr.get('/api/me/usage').json()['turns']>spent0)
 check('path traversal refused',usr.get(f'/api/cron/{jid}/runs/..%2f..%2fconfig.yaml').status_code in (404,422))
 check('admin does not see the user job',all(x['id']!=jid for x in adm.get('/api/cron').json()['jobs']))
 check('pause',usr.post(f'/api/cron/{jid}/action',json={'action':'pause'}).status_code==200 and not next(j for j in jobs() if j['id']==jid)['enabled'])
 check('resume',usr.post(f'/api/cron/{jid}/action',json={'action':'resume'}).status_code==200 and next(j for j in jobs() if j['id']==jid)['enabled'])
 check('bad action rejected',usr.post(f'/api/cron/{jid}/action',json={'action':'remove'}).status_code==422)
 adm.put(f'/api/admin/permissions/user:{uid}',json={'changes':{'feature:cron':False}}).raise_for_status()
 check('denied user gets 403',usr.get('/api/cron').status_code==403 and usr.post('/api/cron/prepare').status_code==403)
 check('feature hidden in permissions',usr.get('/api/me/permissions').json()['feature:cron'] is False)
finally:
 changes={k:None for k in ['feature:cron']};changes.update({k:v for k,v in perms_before.items() if k=='feature:cron'})
 adm.put(f'/api/admin/permissions/user:{uid}',json={'changes':changes})
 if jid:check('delete job',usr.delete(f'/api/cron/{jid}').status_code==200 and all(j['id']!=jid for j in jobs()))
 if did:usr.delete(f'/api/dialogs/{did}')
 end=time.time()+120   # the reconciler may restart the tester bridge when the permission flips; leave it answering
 while time.time()<end:
  try:
   if usr.get('/api/commands').status_code==200 and usr.get('/api/cron').json()['agent_ready']:break
  except Exception:pass
  time.sleep(3)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
