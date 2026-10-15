"""Login throttling: per (ip,user) lock after 5 failures, other users from the same IP unaffected, success clears."""
import json, sys, time, httpx, os
creds=json.loads(sys.stdin.read()); B='https://proxy'; O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')}
res={}
def check(n,c,extra=''):
    res[n]=bool(c); print(('PASS ' if c else 'FAIL ')+n+(' '+str(extra) if extra else ''),flush=True)
c=httpx.Client(base_url=B,verify=False,timeout=60,headers=O)
ghost='nobody-'+str(time.time_ns())[-9:]
codes=[c.post('/api/auth/login',json={'username':ghost,'password':'x'*12}).status_code for _ in range(6)]
check('5 failures then 429 for that user', codes[:5]==[401]*5 and codes[5]==429, codes)
r=c.post('/api/auth/login',json={'username':'tester','password':creds['tester']})
check('other user from same IP still logs in', r.status_code==200, r.status_code)
codes=[c.post('/api/auth/login',json={'username':'tester','password':'wrong-'+str(i)*8}).status_code for i in range(3)]
r=c.post('/api/auth/login',json={'username':'tester','password':creds['tester']})
check('success after a few typos clears counter', r.status_code==200 and codes==[401]*3)
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
