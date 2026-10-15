import unittest
from interactions import Interactions
class Tests(unittest.TestCase):
 def test_approval_exact_once(self):
  sent=[]; s=Interactions(sent.append)
  s.receive({'id':'srq-a','method':'approval','params':{'session_id':'one','choices':['once','deny'],'command':'true'}})
  with self.assertRaises(ValueError):s.respond('two','srq-a',{'choice':'once'})
  with self.assertRaises(ValueError):s.respond('one','srq-a',{'choice':'always'})
  s.respond('one','srq-a',{'choice':'once'})
  with self.assertRaises(ValueError):s.respond('one','srq-a',{'choice':'once'})
  self.assertEqual(sent,[{'jsonrpc':'2.0','id':'srq-a','result':{'choice':'once'}}])
 def test_cancel_and_secret_fail_closed(self):
  sent=[]; s=Interactions(sent.append)
  s.receive({'id':'srq-x','method':'secret','params':{'session_id':'one','prompt':'SENSITIVE_METADATA','env_var':'EXAMPLE'}})
  self.assertEqual(s.snapshot('one')['open_requests'],[])
  self.assertNotIn('SENSITIVE_METADATA',str(s.snapshot('one')))
  self.assertIn('error',sent[0]); self.assertNotIn('result',sent[0])
  s.receive({'id':'srq-c','method':'clarify','params':{'session_id':'one','questions':[{'qid':'q1','question':'Color?'}]}})
  s.cancel('srq-c')
  with self.assertRaises(ValueError):s.respond('one','srq-c',{'answers':{'q1':'blue'}})
 def test_clarification_complete_set(self):
  sent=[]; s=Interactions(sent.append)
  s.receive({'id':'srq-c','method':'clarify','params':{'session_id':'one','questions':[{'qid':'q1','question':'Color?'}]}})
  with self.assertRaises(ValueError):s.respond('one','srq-c',{'answers':{'wrong':'blue'}})
  s.respond('one','srq-c',{'answers':{'q1':'blue'}})
  self.assertEqual(sent[0]['result'],{'answers':{'q1':'blue'}})
 def test_all_secret_methods_decline_without_metadata(self):
  for method in ('secret','sudo','vault.unlock_prompt','vault.save_login','vault.code','preview.act','setup_choose'):
   sent=[]; s=Interactions(sent.append)
   s.receive({'id':'srq-s','method':method,'params':{'session_id':'one','prompt':'PRIVATE_METADATA'}})
   self.assertEqual(s.snapshot('one')['open_requests'],[])
   self.assertNotIn('PRIVATE_METADATA',str(s.snapshot('one')))
   self.assertEqual(sent[0]['error']['code'],-32601)
 def test_sensitive_clarify_has_no_form(self):
  sent=[];s=Interactions(sent.append)
  s.receive({'id':'srq-c','method':'clarify','params':{'session_id':'one','questions':[{'qid':'q','question':'Enter your API key'}]}})
  self.assertEqual(s.snapshot('one')['open_requests'],[])
  self.assertIn('error',sent[0])
 def test_concurrent_responses_send_only_once(self):
  import threading
  sent=[];s=Interactions(sent.append)
  s.receive({'id':'srq-a','method':'approval','params':{'session_id':'one','choices':['once','deny']}})
  errors=[]
  def respond():
   try:s.respond('one','srq-a',{'choice':'once'})
   except ValueError:errors.append('stale')
  threads=[threading.Thread(target=respond) for _ in range(10)]
  for t in threads:t.start()
  for t in threads:t.join()
  self.assertEqual(len(sent),1);self.assertEqual(len(errors),9)
if __name__=='__main__':unittest.main()
