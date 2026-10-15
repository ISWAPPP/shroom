"""Real tool progress exposed by portal sync; cleans up its own dialog."""
import json, sys, time, uuid, httpx, os
creds=json.loads(sys.stdin.read())
c=httpx.Client(base_url='https://proxy',verify=False,timeout=120,headers={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')})
r=c.post('/api/auth/login',json={'username':'tester','password':creds['tester']});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf']
did=c.post('/api/dialogs',json={'title':'activity-acceptance'}).json()['id']
snapshot={}
try:
    r=c.post(f'/api/dialogs/{did}/chat',json={'text':'Використай інструмент terminal для команди printf portal_activity_test. Після цього коротко повідом результат. Обов’язково виконай інструмент, не відповідай без виконання.','request_id':str(uuid.uuid4()),'files':[]});r.raise_for_status()
    cursor=0;epoch='';events=[];snapshot={}
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        r=c.get(f'/api/dialogs/{did}/sync',params={'after':cursor,'epoch':epoch});r.raise_for_status();snapshot=r.json();events.extend(snapshot['events']);cursor=snapshot['cursor'];epoch=snapshot['epoch']
        if snapshot['state'] not in ('running','waiting'):break
        time.sleep(.5)
    starts=[e for e in events if e['type']=='tool.start'];ends=[e for e in events if e['type']=='tool.complete']
    checks={'start event':bool(starts),'complete event':bool(ends),'stable tool ids':bool(starts and ends and set(e['payload']['tool_id'] for e in starts)&set(e['payload']['tool_id'] for e in ends)),'turn boundary':isinstance(snapshot.get('activity_since'),int),'settled':snapshot.get('state')=='complete'}
    for name,ok in checks.items():print(('PASS ' if ok else 'FAIL ')+name)
    print(json.dumps({'passed':sum(checks.values()),'total':len(checks)}))
    if not all(checks.values()):sys.exit(1)
finally:
    if snapshot.get('state') in ('running','waiting'):
        c.post(f'/api/dialogs/{did}/stop')
        for _ in range(30):
            if c.get(f'/api/dialogs/{did}/sync').json().get('state') not in ('running','waiting'):break
            time.sleep(1)
    c.delete(f'/api/dialogs/{did}')
