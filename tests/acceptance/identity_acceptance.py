"""Profile identity/memory management. Isolated temporary profile/users; never writes existing memories."""
import json,sys,uuid,time,httpx,os
creds=json.loads(sys.stdin.read());base='https://proxy';origin={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
a=httpx.Client(base_url=base,verify=False,timeout=400,headers=origin)
r=a.post('/api/auth/login',json={'username':'admin','password':creds['admin']});r.raise_for_status();a.headers['X-CSRF-Token']=r.json()['csrf']
p='identitytest-'+uuid.uuid4().hex[:8];uids=[];checks={};created=False;live_dialog=None;c=None

def check(name,ok):checks[name]=bool(ok);print(('PASS ' if ok else 'FAIL ')+name,flush=True)
def make_user(suffix):
 r=a.post('/api/admin/users',json={'username':p+suffix,'role':'user','profile':p});r.raise_for_status();x=r.json();uids.append(x['id']);c=httpx.Client(base_url=base,verify=False,timeout=400,headers=origin);lr=c.post('/api/auth/login',json={'username':p+suffix,'password':x['password']});lr.raise_for_status();c.headers['X-CSRF-Token']=lr.json()['csrf'];return c,x['id']
try:
 r=a.post('/api/admin/host/profiles',json={'name':p,'provider':'anthropic','model':'claude-haiku-4-5','description':'identity acceptance'});r.raise_for_status();created=True
 for _ in range(45):
  if p in a.get('/api/admin/profiles').json():break
  time.sleep(1)
 else:raise RuntimeError('Temporary profile bridge did not become ready')
 c,uid=make_user('-user');admin=f'/api/admin/host/profiles/{p}'
 features=c.get('/api/me/permissions').json();check('default soul permission',features.get('feature:own_soul') is True);check('default memory permission',features.get('feature:own_memory') is True)
 for key in ('soul','memory','user'):
  path='/api/me/agent/documents/'+key;r=c.get(path);check('read '+key,r.status_code==200);d=r.json();text='Перевірка профілю '+key
  r=c.put(path,json={'content':text,'revision':d['revision']});check('save '+key,r.status_code==200);saved=r.json()
  check('readback '+key,a.get(admin+'/documents/'+key).json()['content']==text)
  r=c.put(path,json={'content':'Стара чернетка','revision':d['revision']});check('conflict '+key,r.status_code==409)
  check('conflict preserves '+key,c.get(path).json()['content']==text)
 check('nonadmin host document refused',c.get(admin+'/documents/soul').status_code==403)
 check('nonadmin config refused',c.get(admin+'/memory-config').status_code==403)
 check('unknown document refused',a.get(admin+'/documents/config').status_code==404)
 check('oversized document refused',c.put('/api/me/agent/documents/soul',json={'content':'x'*40001,'revision':saved['revision']}).status_code==422)
 cfg=a.get(admin+'/memory-config');check('admin config read',cfg.status_code==200 and 'memory_char_limit' in cfg.json()['values'])
 r=a.put(admin+'/memory-config',json={'changes':{'nudge_interval':11,'write_approval':True}});check('admin config write',r.status_code==200)
 check('config readback',a.get(admin+'/memory-config').json()['values']['nudge_interval']==11)
 check('unknown config key refused',a.put(admin+'/memory-config',json={'changes':{'terminal.backend':'local'}}).status_code in (400,422))
 check('bad limit refused',a.put(admin+'/memory-config',json={'changes':{'memory_char_limit':0}}).status_code==400)
 soul_marker='SOUL_SCOPE_'+uuid.uuid4().hex[:8];user_marker='USER_SCOPE_'+uuid.uuid4().hex[:8]
 for key,text in [('soul','Кожну відповідь починай із точного префікса '+soul_marker+'.'),('user','Моє тестове імʼя: '+user_marker+'.')]:
  d=c.get('/api/me/agent/documents/'+key).json();r=c.put('/api/me/agent/documents/'+key,json={'content':text,'revision':d['revision']});r.raise_for_status()
 live_dialog=c.post('/api/dialogs',json={'title':'identity application check'}).json()['id']
 r=c.post('/api/dialogs/'+live_dialog+'/chat',json={'text':'Коротко привітайся та назви моє тестове імʼя з памʼяті профілю.','files':[],'request_id':str(uuid.uuid4())});r.raise_for_status()
 st={}
 for _ in range(90):
  st=c.get('/api/dialogs/'+live_dialog+'/sync').json()
  if st['state'] not in ('running','waiting'):break
  time.sleep(1)
 messages=c.get('/api/dialogs/'+live_dialog+'/history').json()['messages'];reply=json.dumps([m for m in messages if m.get('role')=='assistant'],ensure_ascii=False)
 check('new session applies SOUL',soul_marker in reply);check('new session applies USER memory',user_marker in reply)
 if st['state'] in ('running','waiting'):c.post('/api/dialogs/'+live_dialog+'/stop')
 r=c.delete('/api/dialogs/'+live_dialog);check('cleanup live dialog',r.status_code==200);live_dialog=None
 r=a.put('/api/admin/permissions/user:'+uid,json={'changes':{'feature:own_memory':False}});r.raise_for_status()
 check('memory deny read',c.get('/api/me/agent/documents/memory').status_code==403)
 check('memory deny write',c.put('/api/me/agent/documents/user',json={'content':'denied','revision':saved['revision']}).status_code==403)
 check('soul independent',c.get('/api/me/agent/documents/soul').status_code==200)
 r=a.put('/api/admin/permissions/user:'+uid,json={'changes':{'feature:own_soul':False}});r.raise_for_status();check('soul deny read',c.get('/api/me/agent/documents/soul').status_code==403)
 r=a.put('/api/admin/permissions/user:'+uid,json={'changes':{'feature:own_soul':True,'feature:own_memory':True}});r.raise_for_status()
 c2,uid2=make_user('-shared');check('shared profile refuses self edit',c.get('/api/me/agent/documents/soul').status_code==403)
 check('admin shared edit allowed',a.get(admin+'/documents/soul').status_code==200)
 audit=a.get('/api/admin/audit?limit=100').json();events=[e for e in audit if e.get('action')=='profile.document.edit' and e.get('target')==p];check('audit without document contents',len(events)>=3 and all('Перевірка профілю' not in str(e.get('details')) for e in events))
finally:
 if live_dialog and c is not None:
  c.post('/api/dialogs/'+live_dialog+'/stop')
  for _ in range(30):
   if c.get('/api/dialogs/'+live_dialog+'/sync').json().get('state') not in ('running','waiting'):break
   time.sleep(1)
  c.delete('/api/dialogs/'+live_dialog)
 for uid in uids:
  r=a.delete('/api/admin/users/'+uid);check('cleanup user '+uid[-6:],r.status_code==200)
 if created:
  r=a.post(f'/api/admin/host/profiles/{p}/delete',json={'confirm':p});check('cleanup profile',r.status_code==200)
print(json.dumps({'passed':sum(checks.values()),'total':len(checks)}))
if not all(checks.values()):sys.exit(1)
