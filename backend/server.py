#!/usr/bin/env python3
"""Read-only KSC Open API bridge for Virtual Office. Requires KlAkOAPI on THIS server only."""
import ipaddress, json, os, re, struct, threading, time, urllib.parse, urllib.request, urllib.error, sqlite3, secrets, hmac, ssl, hashlib, getpass, sys
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT=Path(__file__).resolve().parent.parent
PRIVATE=Path(os.environ.get('VO_PRIVATE_DIR',str(Path.home()/'.virtual-office-monitor'))).expanduser().resolve()
CONFIG=PRIVATE/'ksc.json'
DB_PATH=Path(os.environ.get('VO_DB_PATH','/var/lib/virtual-office/config.db')).expanduser()
TOKEN_PATH=Path(os.environ.get('VO_ADMIN_TOKEN_FILE','/var/lib/virtual-office/admin-token')).expanduser()
HA_CONFIG=Path(os.environ.get('VO_HA_CONFIG','/var/lib/virtual-office/ha.json'))
AUTH_PATH=Path(os.environ.get('VO_ADMIN_AUTH_FILE','/var/lib/virtual-office/admin-auth.json')).expanduser()
VIEWER_AUTH_PATH=Path(os.environ.get('VO_VIEWER_AUTH_FILE','/var/lib/virtual-office/viewer-auth.json')).expanduser()
SESSION_MAX_AGE=12*3600
SESSIONS={}
SESSIONS_LOCK=threading.Lock()
LOGIN_ATTEMPTS={}

def hash_password(password,salt=None):
    if not isinstance(password,str) or len(password)<10 or len(password)>128:
        raise ValueError('Password minimal 10 dan maksimal 128 karakter')
    salt=salt or secrets.token_bytes(16)
    return {'salt':salt.hex(),'hash':hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,350000).hex(),'iterations':350000}

def read_auth():
    try:return json.loads(AUTH_PATH.read_text(encoding='utf-8'))
    except (FileNotFoundError,ValueError):return None

def read_viewer_auth():
    try:return json.loads(VIEWER_AUTH_PATH.read_text(encoding='utf-8'))
    except (FileNotFoundError,ValueError):return None

def save_viewer_auth(auth):
    VIEWER_AUTH_PATH.parent.mkdir(parents=True,exist_ok=True)
    temp=VIEWER_AUTH_PATH.with_name(VIEWER_AUTH_PATH.name+'.tmp-'+secrets.token_hex(4))
    fd=os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as f:json.dump(auth,f)
        os.replace(temp,VIEWER_AUTH_PATH)
    finally:
        if temp.exists():temp.unlink()

def set_viewer_password_interactive():
    print('Pengaturan password Virtual Office (username: viewer)')
    password=getpass.getpass('Password baru (minimal 10 karakter): ')
    verify=getpass.getpass('Ulangi password: ')
    if password!=verify:raise SystemExit('Password tidak sama; tidak ada perubahan.')
    save_viewer_auth(hash_password(password))
    print('Password Viewer berhasil disimpan di '+str(VIEWER_AUTH_PATH))
    print('Restart virtual-office agar sesi lama tidak berlaku.')

def save_auth(auth):
    AUTH_PATH.parent.mkdir(parents=True,exist_ok=True)
    temp=AUTH_PATH.with_name(AUTH_PATH.name+'.tmp-'+secrets.token_hex(4))
    fd=os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as f:json.dump(auth,f)
        os.replace(temp,AUTH_PATH)
    finally:
        if temp.exists():temp.unlink()

def password_matches(auth,password):
    if not auth:return False
    try:
        salt=bytes.fromhex(auth['salt'])
        test=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,int(auth['iterations']))
        return hmac.compare_digest(test.hex(),auth['hash'])
    except (KeyError,ValueError,TypeError):return False

def set_admin_password_interactive():
    print('Pengaturan password Virtual Office (username: admin)')
    password=getpass.getpass('Password baru (minimal 10 karakter): ')
    verify=getpass.getpass('Ulangi password: ')
    if password!=verify:raise SystemExit('Password tidak sama; tidak ada perubahan.')
    credentials=hash_password(password)
    save_auth(credentials)
    print('Password admin berhasil disimpan di '+str(AUTH_PATH))
    print('Restart virtual-office agar sesi lama tidak berlaku.')

def invalidate_sessions():
    with SESSIONS_LOCK:SESSIONS.clear()

def session_role(token):
    if not token:return None
    with SESSIONS_LOCK:
        record=SESSIONS.get(token)
        if not record:return None
        role,expiry=record
        if expiry<time.time():
            SESSIONS.pop(token,None)
            return None
        return role

def session_is_valid(token):
    return session_role(token) is not None

HA_CACHE={'time':0.0,'connected':False,'error':'Home Assistant belum dikonfigurasi','entities':{}}
HA_LOCK=threading.Lock()
HA_ENTITY_ID_RE=re.compile(r'^[a-z_]+\.[a-z0-9_]+$')

def ha_status_to_online(state,domain):
    value=str(state or '').lower()
    if value in ('unavailable','unknown','none',''):return 'unknown'
    if domain=='binary_sensor':return 'online' if value=='on' else 'offline' if value=='off' else 'unknown'
    if value in ('connected','online','on','home','idle','printing','ready','standby','active','available','ok','sleeping','paused'):return 'online'
    if value in ('disconnected','offline','off','not_home','unreachable'):return 'offline'
    return 'unknown'

def assigned_ha_entities():
    result=set()
    with sqlite3.connect(str(DB_PATH),timeout=5) as conn:
        for (raw,) in conn.execute('SELECT content FROM floor_config'):
            for obj in json.loads(raw).get('objects',[]):
                if obj.get('type') not in ('ap','printer','server'):continue
                entity=str(obj.get('haEntityId','')).strip().lower()
                if HA_ENTITY_ID_RE.fullmatch(entity):result.add(entity)
    return result

def get_ha_snapshot():
    # Serve only entity IDs explicitly mapped to office devices; never expose token or full HA state.
    now=time.monotonic()
    with HA_LOCK:
        if now-HA_CACHE['time']<20:return dict(HA_CACHE)
        HA_CACHE['time']=now
        try:
            cfg=json.loads(HA_CONFIG.read_text(encoding='utf-8'))
            url=str(cfg.get('url','')).rstrip('/')
            token=str(cfg.get('token','')).strip()
            parsed=urllib.parse.urlsplit(url)
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
                raise ValueError('HA URL harus http(s)://host:port tanpa path')
            if not token:raise ValueError('Token Home Assistant belum diisi')
            result={}
            for entity in sorted(assigned_ha_entities()):
                req=urllib.request.Request(url+'/api/states/'+urllib.parse.quote(entity,safe='.'),headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
                try:
                    with urllib.request.urlopen(req,timeout=5,context=ssl.create_default_context()) as response:
                        obj=json.load(response)
                    state=str(obj.get('state','unknown'))
                    result[entity]={'status':ha_status_to_online(state,entity.split('.')[0]),'state':state,
                      'name':str(obj.get('attributes',{}).get('friendly_name',entity))[:120]}
                except urllib.error.HTTPError as err:
                    if err.code==404:result[entity]={'status':'unknown','state':'not_found','name':entity}
                    else:raise
            HA_CACHE.update(connected=True,error=None,entities=result)
        except Exception as err:
            HA_CACHE.update(connected=False,error=type(err).__name__+': '+str(err)[:150],entities={})
        return dict(HA_CACHE)

HOST=os.environ.get('VO_HOST','127.0.0.1')
PORT=int(os.environ.get('VO_PORT','8080'))
LOCK=threading.RLock()
STATE={'connected':False,'timestamp':None,'error':'Konfigurasi KSC belum tersedia','devices':{},'hostnames':[],'total_hosts':0}
FIELDS=['KLHST_WKS_WINHOSTNAME','KLHST_WKS_DN','KLHST_WKS_FQDN','KLHST_WKS_STATUS','KLHST_WKS_LAST_NAGENT_CONNECTED','KLHST_WKS_NAG_VERSION','KLHST_WKS_GROUPID','KLHST_WKS_IP_LONG','KLHST_WKS_CONNECT_IP_LONG']

def normalize_host(value):
    return str(value or '').strip().upper().split('.')[0]

def val(obj,key):
    try:
        return obj[key]
    except Exception as exc:
        if not (isinstance(exc,(KeyError,TypeError,AttributeError)) or
                (type(exc).__name__=='KlAkParamTypeError' and 'does not contain' in str(exc))):
            raise
    try:
        return obj.GetValue(key)
    except Exception as exc:
        if isinstance(exc,(KeyError,TypeError,AttributeError)) or (type(exc).__name__=='KlAkParamTypeError' and 'does not contain' in str(exc)):
            return None
        raise

def clean_text(value):
    if value is None:return None
    try:return str(value)
    except Exception:return None

def decode_ksc_ipv4(value):
    """Decode a KSC IP_LONG integer into standard network-order IPv4 octets.

    The observed KSC response encodes 10.66.192.35 as 0x0A42C023.
    Accept signed 32-bit representations and reject invalid addresses.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number=int(value)
        if number < -(1 << 31) or number > 0xffffffff:
            return None
        address=ipaddress.IPv4Address(struct.pack('>I',number & 0xffffffff))
        if address.is_unspecified or address.is_multicast or address.is_reserved or address.is_loopback or address.is_link_local:
            return None
        return str(address)
    except (ValueError, TypeError, OverflowError, struct.error, ipaddress.AddressValueError):
        return None

def ksc_host_ip(row):
    # Primary host address, then KSC connection address if no primary address exists.
    for field in ('KLHST_WKS_IP_LONG','KLHST_WKS_CONNECT_IP_LONG'):
        result=decode_ksc_ipv4(val(row,field))
        if result:
            return result
    return None

def parse_host(row):
    name=normalize_host(val(row,'KLHST_WKS_WINHOSTNAME') or val(row,'KLHST_WKS_FQDN') or val(row,'KLHST_WKS_DN'))
    if not name:return None
    bits=val(row,'KLHST_WKS_STATUS')
    try:bits=int(bits)
    except (TypeError,ValueError):bits=None
    # KSC documented bit 3: Network Agent alive; bit 2: agent installed.
    status='unknown' if bits is None or not bits & (1<<2) else 'online' if bits & (1<<3) else 'offline'
    return {'hostname':name,'status':status,'source':'ksc-network-agent',
            'agent_alive':bool(bits & (1<<3)) if bits is not None else None,
            'last_connected':clean_text(val(row,'KLHST_WKS_LAST_NAGENT_CONNECTED')),
            'agent_version':clean_text(val(row,'KLHST_WKS_NAG_VERSION')),
            'group_id':val(row,'KLHST_WKS_GROUPID'),
            'ip':ksc_host_ip(row)}

def fetch_ksc(cfg):
    from KlAkOAPI.AdmServer import KlAkAdmServer
    from KlAkOAPI.HostGroup import KlAkHostGroup
    from KlAkOAPI.ChunkAccessor import KlAkChunkAccessor
    url=str(cfg['server_url'])
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.port!=13299 or parsed.path not in ('','/') or parsed.username:
        raise ValueError('KSC server_url harus https://HOST:13299')
    username=os.environ.get('KSC_USERNAME','').strip()
    password=os.environ.get('KSC_PASSWORD','')
    if not username or not password:raise ValueError('KSC_USERNAME dan KSC_PASSWORD harus tersedia di environment')
    cert=str(cfg.get('cert_file','')).strip()
    if not cert or not Path(cert).is_file():raise ValueError('cert_file wajib diisi dengan sertifikat KSC yang terpercaya')
    verify=cert
    server=KlAkAdmServer.Create(url,username,password,verify=verify)
    hg=KlAkHostGroup(server); accessor=KlAkChunkAccessor(server)
    # Read-only query; optional KSC filter, e.g. hostname pattern or group condition.
    query=str(cfg.get('filter',''))
    result=hg.FindHosts(query,FIELDS,[],{'KLGRP_FIND_FROM_CUR_VS_ONLY':False},120)
    token=result.OutPar('strAccessor')
    hosts={}
    try:
        total=accessor.GetItemsCount(token).RetVal()
        limit=max(1,min(10000,int(cfg.get('max_hosts',3000))))
        if total>limit:raise ValueError(f'Terlalu banyak hasil KSC ({total}); perketat filter atau naikkan max_hosts')
        for start in range(0,total,100):
            chunk=accessor.GetItemsChunk(token,start,min(100,total-start)).OutPar('pChunk')
            for raw in chunk['KLCSP_ITERATOR_ARRAY']:
                host=parse_host(raw)
                if host:
                    # A single Windows hostname may have stale duplicate records; keep ambiguous as Unknown.
                    key=host.pop('hostname')
                    if key in hosts and hosts[key]!=host:
                        hosts[key]['status']='unknown';hosts[key]['duplicate']=True
                    else:hosts[key]=host
    finally:
        accessor.Release(token)
    return hosts,total

def poll_forever():
    while True:
        interval=60
        try:
            cfg=json.loads(CONFIG.read_text(encoding='utf-8'))
            interval=max(30,min(900,int(cfg.get('poll_seconds',60))))
            hosts,total=fetch_ksc(cfg)
            with LOCK:STATE.update(connected=True,timestamp=int(time.time()),error=None,
                devices=hosts,hostnames=sorted(hosts),total_hosts=total)
        except Exception as exc:
            # Stale data must never masquerade as an online device.
            with LOCK:STATE.update(connected=False,timestamp=int(time.time()),error=type(exc).__name__+': '+str(exc)[:180],devices={},hostnames=[],total_hosts=0)
        time.sleep(interval)


# Persistent configuration is shared between browsers. The KSC API remains read-only.
def init_database():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(str(DB_PATH),timeout=15) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('CREATE TABLE IF NOT EXISTS floor_config (floor TEXT PRIMARY KEY, revision INTEGER NOT NULL, content TEXT NOT NULL, updated_at INTEGER NOT NULL)')
        for floor in ('1','2'):
            template=json.loads((ROOT/f'lantai{floor}.json').read_text(encoding='utf-8'))
            conn.execute('INSERT OR IGNORE INTO floor_config (floor,revision,content,updated_at) VALUES (?,?,?,?)',(floor,1,json.dumps(template,ensure_ascii=False),int(time.time())))
        # Upgrade-only migration: add the two Floor 2 workstations to an existing SQLite
        # configuration without overwriting mappings, names, edits, or other custom objects.
        row=conn.execute('SELECT revision, content FROM floor_config WHERE floor=?',('2',)).fetchone()
        if row:
            current=json.loads(row[1]); objects=current.get('objects',[])
            existing={o.get('id') for o in objects if isinstance(o,dict)}
            template2=json.loads((ROOT/'lantai2.json').read_text(encoding='utf-8'))
            missing=[o for o in template2['objects'] if o.get('id') in ('WS-29','WS-30') and o.get('id') not in existing]
            if missing:
                objects.extend(missing)
                conn.execute('UPDATE floor_config SET revision=?, content=?, updated_at=? WHERE floor=?',
                             (row[0]+1,json.dumps(current,ensure_ascii=False),int(time.time()),'2'))
                print('Virtual Office SQLite migration: added '+', '.join(o['id'] for o in missing),flush=True)
        # Upgrade-only Floor 1 migration: add three desks in the column marked by
        # the user, without replacing any existing names, hostnames, coordinates,
        # device mappings or other SQLite configuration.
        row=conn.execute('SELECT revision, content FROM floor_config WHERE floor=?',('1',)).fetchone()
        if row:
            current=json.loads(row[1]); objects=current.get('objects',[])
            existing={o.get('id') for o in objects if isinstance(o,dict)}
            template1=json.loads((ROOT/'lantai1.json').read_text(encoding='utf-8'))
            requested=('WS-L1-20','WS-L1-21','WS-L1-22')
            missing=[o for o in template1['objects'] if o.get('id') in requested and o.get('id') not in existing]
            if missing:
                objects.extend(missing)
                conn.execute('UPDATE floor_config SET revision=?, content=?, updated_at=? WHERE floor=?',
                             (row[0]+1,json.dumps(current,ensure_ascii=False),int(time.time()),'1'))
                print('Virtual Office SQLite migration: added '+', '.join(o['id'] for o in missing),flush=True)
        conn.commit()
    if not TOKEN_PATH.is_file():
        TOKEN_PATH.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(str(TOKEN_PATH),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as out: out.write(secrets.token_urlsafe(36)+'\n')

def get_floor_config(floor):
    with sqlite3.connect(str(DB_PATH),timeout=15) as conn:
        conn.row_factory=sqlite3.Row
        row=conn.execute('SELECT revision, content, updated_at FROM floor_config WHERE floor=?',(floor,)).fetchone()
    if not row:return None
    return {'floor':floor,'revision':row['revision'],'updated_at':row['updated_at'],'config':json.loads(row['content'])}

def validate_floor_config(floor,config):
    if not isinstance(config,dict) or not isinstance(config.get('objects'),list):raise ValueError('Struktur konfigurasi tidak valid')
    expected=json.loads((ROOT/f'lantai{floor}.json').read_text(encoding='utf-8'))
    if config.get('roomId')!=expected.get('roomId'):raise ValueError('roomId bukan untuk lantai ini')
    standard={(o['id'],o['type']) for o in expected['objects']}
    supplied=[(o.get('id'),o.get('type')) for o in config['objects'] if isinstance(o,dict)]
    if len(config['objects'])>500 or len(supplied)!=len(config['objects']) or len(set(supplied))!=len(supplied):
        raise ValueError('Jumlah atau ID objek tidak valid/duplikat')
    if not standard.issubset(set(supplied)):
        raise ValueError('Objek dasar lantai tidak boleh dihapus atau diubah jenisnya')
    for item in config['objects']:
        if (not isinstance(item,dict) or item.get('type') not in ('user','ap','server','printer')
                or not isinstance(item.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',item['id'])
                or type(item.get('x')) not in (int,float) or type(item.get('y')) not in (int,float)
                or not 0<=item['x']<=100 or not 0<=item['y']<=100):
            raise ValueError('Objek atau koordinat tidak valid')
        for name in ('name','hostname','anydeskId','ip','haEntityId'):
            if len(str(item.get(name,'') or ''))>256:raise ValueError('Field objek terlalu panjang')
    if len(json.dumps(config))>1024*1024:raise ValueError('Data terlalu besar')
    return config

def update_floor_config(floor,config,revision):
    with sqlite3.connect(str(DB_PATH),timeout=15) as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT revision FROM floor_config WHERE floor=?',(floor,)).fetchone()
        if not row:raise KeyError(floor)
        if row[0]!=revision:
            conn.rollback()
            return None
        new_revision=row[0]+1
        conn.execute('UPDATE floor_config SET revision=?,content=?,updated_at=? WHERE floor=?',(new_revision,json.dumps(config,ensure_ascii=False),int(time.time()),floor))
        conn.commit()
    return new_revision

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
    def end_headers(self):
        # Always revalidate the frontend after a release switch.
        # GLB models may still be cached by the browser for performance.
        requested=urllib.parse.urlsplit(self.path).path
        if requested in ('/','/index.html','/lantai1.json','/lantai2.json'):
            self.send_header('Cache-Control','no-store, max-age=0')
            self.send_header('Pragma','no-cache')
            self.send_header('X-Virtual-Office-Build','v16-grid-filters')
        return super().end_headers()
    def json_response(self,data,status=200):
        body=json.dumps(data,ensure_ascii=False,default=str).encode('utf-8')
        self.send_response(status)
        for k,v in {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Length':str(len(body))}.items():self.send_header(k,v)
        self.end_headers();self.wfile.write(body)
    def admin_session(self):
        header=self.headers.get('Authorization','')
        return session_role(header[7:] if header.startswith('Bearer ') else '')=='admin'
    def any_session(self):
        header=self.headers.get('Authorization','')
        return session_role(header[7:] if header.startswith('Bearer ') else '')
    def read_json_body(self,max_size=4096):
        length=int(self.headers.get('Content-Length','0'))
        if length<=0 or length>max_size:raise ValueError('Ukuran permintaan tidak valid')
        return json.loads(self.rfile.read(length).decode('utf-8'))
    def do_GET(self):
        path=urllib.parse.urlsplit(self.path).path
        if path=='/api/auth/status':return self.json_response({'authenticated':bool(self.any_session()),'role':self.any_session(),'configured':bool(read_auth()),'viewerConfigured':bool(read_viewer_auth())})
        if path.startswith('/api/') and not self.any_session():return self.json_response({'error':'Login diperlukan'},401)
        m=re.fullmatch(r'/api/config/([12])',path)
        if m:return self.json_response(get_floor_config(m.group(1)))
        if path.startswith('/api/'):
            with LOCK:state=STATE.copy()
            if path=='/api/ha/status':
                snap=get_ha_snapshot();return self.json_response({'connected':snap['connected'],'error':snap['error'],'entities':snap['entities']})
            if path=='/api/health':return self.json_response({'ok':True,'provider_connected':state['connected'],'error':state['error']})
            if path=='/api/status':return self.json_response({'mode':'ksc','connected':state['connected'],'timestamp':state['timestamp'],'error':state['error'],'total_hosts':state['total_hosts'],'devices':state['devices']})
            if path=='/api/inventory':return self.json_response({'connected':state['connected'],'timestamp':state['timestamp'],'hostnames':state['hostnames']})
            return self.json_response({'error':'Not found'},404)
        if path not in ('/','/index.html','/lantai1.json','/lantai2.json') and not re.fullmatch(r'/assets/[A-Za-z0-9_.-]+\.(png|jpg|jpeg|webp)',path) and not re.fullmatch(r'/assets/models/[A-Za-z0-9_.-]+\.glb',path):
            return self.json_response({'error':'Not found'},404)
        return super().do_GET()
    def do_POST(self):
        path=urllib.parse.urlsplit(self.path).path
        if path=='/api/auth/login':
            try:
                payload=self.read_json_body()
                username=str(payload.get('username','')).strip()
                password=str(payload.get('password',''))
                client=self.client_address[0]
                now=time.time()
                with SESSIONS_LOCK:
                    attempts=[t for t in LOGIN_ATTEMPTS.get(client,[]) if now-t<300]
                    LOGIN_ATTEMPTS[client]=attempts
                    limited=len(attempts)>=8
                if limited:return self.json_response({'error':'Terlalu banyak percobaan. Coba lagi dalam 5 menit.'},429)
                auth=read_auth()
                if username not in ('admin','viewer') or not password_matches(auth if username=='admin' else read_viewer_auth(),password):
                    with SESSIONS_LOCK:LOGIN_ATTEMPTS.setdefault(client,[]).append(now)
                    return self.json_response({'error':'Username atau password salah'},401)
                with SESSIONS_LOCK:
                    LOGIN_ATTEMPTS.pop(client,None)
                    token=secrets.token_urlsafe(36)
                    SESSIONS[token]=(username,time.time()+SESSION_MAX_AGE)
                return self.json_response({'ok':True,'token':token,'role':username,'expiresIn':SESSION_MAX_AGE})
            except (ValueError,TypeError,json.JSONDecodeError) as exc:return self.json_response({'error':str(exc)},400)
        if path=='/api/auth/logout':
            header=self.headers.get('Authorization','')
            with SESSIONS_LOCK:SESSIONS.pop(header[7:] if header.startswith('Bearer ') else '',None)
            return self.json_response({'ok':True})
        if path=='/api/auth/change-password':
            if not self.admin_session():return self.json_response({'error':'Sesi Admin tidak valid'},401)
            try:
                payload=self.read_json_body()
                current=str(payload.get('currentPassword',''))
                new=str(payload.get('newPassword',''))
                if not password_matches(read_auth(),current):return self.json_response({'error':'Password saat ini salah'},403)
                save_auth(hash_password(new))
                invalidate_sessions()
                return self.json_response({'ok':True})
            except (ValueError,TypeError,json.JSONDecodeError) as exc:return self.json_response({'error':str(exc)},400)
        m=re.fullmatch(r'/api/config/([12])',path)
        if not m:return self.json_response({'error':'Not found'},404)
        try:
            if not self.admin_session():return self.json_response({'error':'Sesi Admin tidak valid atau kedaluwarsa'},401)
            length=int(self.headers.get('Content-Length','0'))
            if length<=0 or length>1024*1024:return self.json_response({'error':'Ukuran payload tidak valid'},413)
            payload=json.loads(self.rfile.read(length).decode('utf-8'))
            revision=payload.get('revision')
            if type(revision) is not int or revision<1:return self.json_response({'error':'Revisi konfigurasi tidak valid'},400)
            config=validate_floor_config(m.group(1),payload.get('config'))
            new_revision=update_floor_config(m.group(1),config,revision)
            if new_revision is None:return self.json_response({'error':'Konfigurasi telah berubah di browser lain. Muat ulang sebelum menyimpan.'},409)
            return self.json_response({'ok':True,'revision':new_revision})
        except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:return self.json_response({'error':str(exc)[:200]},400)
        except Exception as exc:
            print('Config write error:',repr(exc),flush=True)
            return self.json_response({'error':'Gagal menyimpan konfigurasi'},500)


if __name__=='__main__':
    if '--set-viewer-password' in sys.argv:
        set_viewer_password_interactive()
        raise SystemExit(0)
    if '--set-admin-password' in sys.argv:
        set_admin_password_interactive()
        raise SystemExit(0)
    init_database()
    print(f'Virtual Office KSC Bridge: http://{HOST}:{PORT}; private config: {CONFIG}; sqlite: {DB_PATH}',flush=True)
    if HOST not in ('127.0.0.1','::1','localhost'):print('WARNING: restrict dashboard to trusted VPN or HTTPS reverse proxy with authentication',flush=True)
    threading.Thread(target=poll_forever,daemon=True).start()
    ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
