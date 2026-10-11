"""Diagnose KSC authentication and read-only inventory using same v17 backend."""
import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from server import CONFIG, fetch_ksc

def main():
    try:
        cfg=json.loads(CONFIG.read_text(encoding='utf-8'))
        hosts,total=fetch_ksc(cfg)
        print('[OK] Connected to KSC. Total records:',total)
        print('[OK] Unique hostname count:',len(hosts))
        for name,info in list(sorted(hosts.items()))[:10]:
            print(name,info['status'],'agent:',info.get('agent_version'))
    except Exception as err:
        print('[ERROR]',type(err).__name__,str(err))
        raise SystemExit(1)
if __name__=='__main__':main()
