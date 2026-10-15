"""Host file safety tests in a temporary isolated profile; no real memories are edited."""
import importlib.util, tempfile, pathlib, os, concurrent.futures
spec=importlib.util.spec_from_file_location('portal_profile_admin',pathlib.Path(__file__).resolve().parents[2]/'profile_admin.py')
assert spec is not None and spec.loader is not None
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
scratch=pathlib.Path(os.environ.get('TMPDIR','/tmp'));scratch.mkdir(parents=True,exist_ok=True)
def refuses(fn):
 try:fn()
 except ValueError:return
 raise AssertionError('Unsafe operation was not rejected')
with tempfile.TemporaryDirectory(dir=scratch) as temp:
 root=pathlib.Path(temp)/'root';profile=root/'profiles'/'unit';profile.mkdir(parents=True);(profile/'config.yaml').write_text('memory: {}\n');setattr(module,'ROOT',root)
 original=module.profile_document('unit','soul');saved=module.set_profile_document('unit','soul','Ідентичність',original['revision']);assert module.profile_document('unit','soul')['content']=='Ідентичність'
 refuses(lambda:module.set_profile_document('unit','soul','stale',original['revision']))
 refuses(lambda:module.profile_document('unit','../../.env'))
 refuses(lambda:module.set_profile_document('unit','soul','x'*20001,saved['revision']))
 assert len(list((profile/'backups'/'profile-documents'/'soul').glob('*.bak')))==1
 assert (profile/'SOUL.md').stat().st_mode&0o777==0o600
 outside=pathlib.Path(temp)/'outside';outside.write_text('Do not modify')
 (profile/'SOUL.md').unlink();(profile/'SOUL.md').symlink_to(outside)
 refuses(lambda:module.profile_document('unit','soul'));assert outside.read_text()=='Do not modify'
 (profile/'SOUL.md').unlink();os.link(outside,profile/'SOUL.md');refuses(lambda:module.profile_document('unit','soul'));(profile/'SOUL.md').unlink()
 (profile/'memories').symlink_to(pathlib.Path(temp));refuses(lambda:module.profile_document('unit','memory'));(profile/'memories').unlink()
 snapshot=module.profile_document('unit','memory')
 def write(value):
  try:module.set_profile_document('unit','memory',value,snapshot['revision']);return True
  except ValueError:return False
 with concurrent.futures.ThreadPoolExecutor(2) as executor:results=list(executor.map(write,['One','Two']))
 assert sum(results)==1
 for _ in range(12):
  snap=module.profile_document('unit','soul');module.set_profile_document('unit','soul',str(_),snap['revision'])
 assert len(list((profile/'backups'/'profile-documents'/'soul').glob('*.bak')))==10
 refuses(lambda:module.set_profile_memory_config('unit',{'terminal.backend':'local'}))
 refuses(lambda:module.set_profile_memory_config('unit',{'memory_char_limit':False}))
print('PASS: isolated documents, revisions, symlink/hardlink/traversal refusal, concurrent writes, restrictive permissions, backup rotation, config allowlist')
