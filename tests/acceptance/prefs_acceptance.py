"""Per-account colour/mode preferences, legacy updates and validation; restore tester choices."""
import json,sys,httpx,os
creds=json.loads(sys.stdin.read());B='https://proxy';O={'Origin':os.environ.get('PORTAL_ORIGIN', 'https://localhost')};res={}
def check(n,c):res[n]=bool(c);print(('PASS ' if c else 'FAIL ')+n,flush=True)
def login(u):
 c=httpx.Client(base_url=B,verify=False,timeout=60,headers=O);r=c.post('/api/auth/login',json={'username':u,'password':creds[u]});r.raise_for_status();c.headers['X-CSRF-Token']=r.json()['csrf'];return c
usr=login('tester');adm=login('admin');before=usr.get('/api/me/prefs').json();abefore=adm.get('/api/me/prefs').json()
try:
 check('themes listed',set(before['themes'])=={'light','dark','system'})
 check('palettes listed',set(before['palettes'])=={'blue','forest','violet','amber','rose','ocean','mushroom','nord','graphite','coral','plum','matcha','dusk','neon','solarized'})
 for palette in before['palettes']:
  for theme in ('light','dark'):
   r=usr.put('/api/me/prefs',json={'theme':theme,'palette':palette});p=usr.get('/api/me/prefs').json();check(palette+' '+theme,r.status_code==200 and p['theme']==theme and p['palette']==palette)
 check('isolated',adm.get('/api/me/prefs').json()==abefore)
 saved=usr.get('/api/me/prefs').json()
 check('unknown palette rejected',usr.put('/api/me/prefs',json={'theme':'light','palette':'missing'}).status_code==400)
 check('invalid payload leaves preferences unchanged',usr.get('/api/me/prefs').json()==saved)
 check('unknown theme rejected',usr.put('/api/me/prefs',json={'theme':'neon'}).status_code==400)
 check('empty update rejected',usr.put('/api/me/prefs',json={}).status_code==400)
 r=usr.put('/api/me/prefs',json={'theme':'system'});check('legacy theme-only preserves palette',r.status_code==200 and r.json()['palette']==saved['palette'])
 r=usr.put('/api/me/prefs',json={'palette':'forest'});check('palette-only preserves mode',r.status_code==200 and r.json()['theme']=='system')
 check('backgrounds listed, default none',set(before['backgrounds'])=={'none','synapse','constellation','waves','aurora','orbits','spores','mycelium','fireflies','ripples','flow','honeycomb','warp','rain','lissajous'} and before['background'] in before['backgrounds'])
 for bg in before['backgrounds']:
  r=usr.put('/api/me/prefs',json={'background':bg});check('background '+bg,r.status_code==200 and r.json()['background']==bg and r.json()['palette']=='forest')
 check('unknown background rejected',usr.put('/api/me/prefs',json={'background':'disco'}).status_code==400)
finally:
 r=usr.put('/api/me/prefs',json={'theme':before['theme'],'palette':before['palette'],'background':before['background']});r.raise_for_status();p=usr.get('/api/me/prefs').json();check('original preferences restored',p['theme']==before['theme'] and p['palette']==before['palette'] and p['background']==before['background'])
print(json.dumps({'passed':sum(res.values()),'total':len(res)}))
if not all(res.values()):sys.exit(1)
