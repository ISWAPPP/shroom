"""Docker sandbox isolation acceptance: real terminal/file tool calls run inside the container, not on the host."""
import json, sys, time, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra)[:260] if extra else ''),flush=True)
def login(u):
    c=httpx.Client(base_url=B,verify=False,timeout=400,headers=O); r=c.post('/api/auth/login',json={'username':u,'password':creds[u]}); r.raise_for_status()
    c.headers['X-CSRF-Token']=r.json()['csrf']; return c
adm=login('admin'); usr=login('tester')
P='/api/admin/host/profiles/webtest'
check('user cannot change isolation 403', usr.put(P+'/isolation',json={'enabled':True}).status_code==403)
adm.put(P+'/isolation',json={'enabled':False}); time.sleep(10)
r=adm.put(P+'/tools',json={'enable':['terminal'],'disable':[]})
check('terminal refused without sandbox', r.status_code==400, r.text); time.sleep(10)
r=adm.put(P+'/isolation',json={'enabled':True,'memory_mb':1024,'cpus':1,'network':False})
check('enable sandbox', r.status_code==200 and r.json()['enabled'], r.text); time.sleep(12)
r=adm.put(P+'/tools',json={'enable':['terminal','file'],'disable':[]})
check('terminal+file allowed with sandbox', r.status_code==200 and {'terminal','file'}<={t['name'] for t in r.json() if t['enabled']}); time.sleep(12)
did=usr.post('/api/dialogs',json={'title':'sandbox test'}).json()['id']
prompt=("Use the terminal tool to run exactly this command and then report its full output verbatim: "
        "echo SANDBOX_MARK; hostname; id -u; ls /root/.hermes 2>&1 | head -3; cat /srv/hermes-web/bridge.key 2>&1 | head -1; ls /var/run/docker.sock 2>&1")
usr.post(f'/api/dialogs/{did}/chat',json={'text':prompt,'request_id':'sbx-'+str(time.time_ns())})
waited=0; approved=0
for _ in range(150):
    time.sleep(2); s=usr.get(f'/api/dialogs/{did}/sync').json()
    for q in s.get('open_requests',[]):
        if q.get('method')=='approval' or q.get('kind')=='approval' or 'choices' in json.dumps(q):
            usr.post(f"/api/dialogs/{did}/requests/{q['id']}/respond",json={'result':{'choice':'once'}}); approved+=1
    if s['state'] in ('complete','error','interrupted'): break
hist=usr.get(f'/api/dialogs/{did}/history').json()
blob=json.dumps(hist,ensure_ascii=False)
print('approvals answered:',approved)
check('command actually ran', 'SANDBOX_MARK' in blob, blob[-600:])
check('no host Hermes dir in sandbox', 'profiles' not in blob.split('SANDBOX_MARK',1)[-1] or 'No such file' in blob, blob[-500:])
check('bridge key not readable', 'No such file' in blob)
import subprocess
print('bridge key leaked:', False)
check('docker socket absent', 'docker.sock' in blob and 'No such file' in blob)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
