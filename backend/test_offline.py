import importlib.util,sys,types,tempfile,os,json,urllib.request,threading,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('vo_ksc_server',Path(__file__).with_name('server.py'))
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
assert s.parse_host({'KLHST_WKS_WINHOSTNAME':'IDSRBJMPC01','KLHST_WKS_STATUS':12})['status']=='online'
assert s.parse_host({'KLHST_WKS_WINHOSTNAME':'IDSRBJMPC02','KLHST_WKS_STATUS':4})['status']=='offline'
assert s.parse_host({'KLHST_WKS_WINHOSTNAME':'IDSRBJMPC03','KLHST_WKS_STATUS':0})['status']=='unknown'
assert s.normalize_host('idsrbjmpc01.corp.local')=='IDSRBJMPC01'
assert s.parse_host({'KLHST_WKS_DN':'PC-SAMPLE','KLHST_WKS_STATUS':None})['status']=='unknown'
# Mock the official KlAkOAPI module interface end to end without connecting to a real KSC.
class R:
 def __init__(self,**kw):self.kw=kw
 def OutPar(self,key):return self.kw[key]
 def RetVal(self):return self.kw['retval']
class Server:
 @staticmethod
 def Create(url,user,password,verify):
  assert password=='secret' and verify.endswith('.cer');return object()
class HG:
 def __init__(self,sv):pass
 def FindHosts(self,*args):assert len(args[1])>3;return R(strAccessor='tok')
class CA:
 def __init__(self,sv):self.released=False
 def GetItemsCount(self,token):return R(retval=2)
 def GetItemsChunk(self,token,start,n):return R(pChunk={'KLCSP_ITERATOR_ARRAY':[
  {'KLHST_WKS_WINHOSTNAME':'PC-ONE','KLHST_WKS_STATUS':12},
  {'KLHST_WKS_WINHOSTNAME':'PC-TWO','KLHST_WKS_STATUS':4}]})
 def Release(self,token):assert token=='tok'
for key,obj in [('KlAkOAPI',types.ModuleType('KlAkOAPI')),('KlAkOAPI.AdmServer',types.ModuleType('KlAkOAPI.AdmServer')),('KlAkOAPI.HostGroup',types.ModuleType('KlAkOAPI.HostGroup')),('KlAkOAPI.ChunkAccessor',types.ModuleType('KlAkOAPI.ChunkAccessor'))]:sys.modules[key]=obj
sys.modules['KlAkOAPI.AdmServer'].KlAkAdmServer=Server
sys.modules['KlAkOAPI.HostGroup'].KlAkHostGroup=HG
sys.modules['KlAkOAPI.ChunkAccessor'].KlAkChunkAccessor=CA
with tempfile.TemporaryDirectory() as t:
 cert=Path(t)/'server.cer';cert.write_text('stub')
 os.environ['KSC_USERNAME']='user';os.environ['KSC_PASSWORD']='secret'
 hosts,total=s.fetch_ksc({'server_url':'https://ksc.example:13299','cert_file':str(cert)})
 assert total==2 and hosts['PC-ONE']['status']=='online' and hosts['PC-TWO']['status']=='offline'
 print('PASS: KSC SDK mocked query, bit-3 status and hostname mapping')
# Server API smoke test. Expose only ephemeral local port.
from http.server import ThreadingHTTPServer
s.STATE.update(connected=True,timestamp=123,error=None,devices={'PC-ONE':{'status':'online'}},hostnames=['PC-ONE'],total_hosts=1)
server=ThreadingHTTPServer(('127.0.0.1',0),s.Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
base=f'http://127.0.0.1:{server.server_port}'
try:
 for path in ['/api/health','/api/status','/api/inventory','/','/index.html']:
  with urllib.request.urlopen(base+path,timeout=3) as res:
   assert res.status==200;data=res.read()
   if path=='/api/status':assert json.loads(data)['devices']['PC-ONE']['status']=='online'
 try:urllib.request.urlopen(base+'/backend/server.py',timeout=3);raise AssertionError('backend exposed')
 except urllib.error.HTTPError as err:assert err.code==404
 print('PASS: HTTP health/status/inventory/index; protected backend returns 404')
finally:server.shutdown();server.server_close()
