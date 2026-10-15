"""Portal-side handling of Hermes approval/clarify requests. No credential fields or general RPC responses accepted."""
import threading, re
class Interactions:
 def __init__(self,send):
  self.send=send; self.lock=threading.RLock(); self.open={}; self.notices={}
 def receive(self,frame):
  rid=frame['id']; method=frame['method']; p=frame.get('params',{}); sid=p.get('session_id')
  with self.lock:
   sensitive_clarify=method=='clarify' and bool(re.search(r'password|passphrase|api[ _-]?key|secret|token|otp|2fa|verification code|парол|токен|секрет|код підтвердж',str(p.get('questions','')),re.I))
   if method not in ('approval','clarify') or not sid or sensitive_clarify:
    self.send({'jsonrpc':'2.0','id':rid,'error':{'code':-32601,'message':'This interaction is unsupported; use a secure native Hermes surface. No value collected.'}})
    if sid:self.notices[sid]='Credential/secret or unsupported interaction declined. Do not enter passwords, tokens or codes in chat; use the native secure Hermes surface.'
    return
   if method=='approval':
    p={k:p[k] for k in ('session_id','command','description','choices','tool_name') if k in p}
    p['choices']=[c for c in p.get('choices',[]) if c in ('once','deny')]
   else:p={k:p[k] for k in ('session_id','questions','answers') if k in p}
   self.open[rid]={'id':rid,'method':method,'params':p}
 def cancel(self,rid):
  with self.lock:self.open.pop(rid,None)
 def snapshot(self,sid):
  with self.lock:return {'open_requests':[r for r in self.open.values() if r['params']['session_id']==sid],'notice':self.notices.get(sid,'')}
 def respond(self,sid,rid,result):
  with self.lock:
   r=self.open.get(rid)
   if not r or r['params']['session_id']!=sid:raise ValueError('Request expired, already answered, or belongs to another session')
   if r['method']=='approval':
    if set(result)!={'choice'} or result['choice'] not in ('once','deny') or result['choice'] not in r['params']['choices']:raise ValueError('Only an offered one-time allow or deny is supported')
   elif r['method']=='clarify':
    if set(result) not in ({'answers'},set()):raise ValueError('Invalid clarification response')
    if 'answers' in result:
     answers=result['answers']; qids={q['qid'] for q in r['params']['questions']}
     if not isinstance(answers,dict) or set(answers)!=qids or any(v is not None and (not isinstance(v,str) or len(v)>4000) for v in answers.values()):raise ValueError('Answer every question or explicitly skip it')
   self.open.pop(rid)
   self.send({'jsonrpc':'2.0','id':rid,'result':result})
   return {'sent':True,'request_id':rid}
