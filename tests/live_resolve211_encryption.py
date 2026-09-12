"""Encrypt a synthetic identity shader through both wrappers, without installation.
Usage: python tests/live_resolve211_encryption.py SOURCE_DCTL OUTPUT_DIR
Requires task-owned synthetic source; creates new .dctle files and refuses repeats.
"""
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    import src.server as s
    from src.granular import resolve_211 as g
    source=Path(sys.argv[1]).resolve();output=Path(sys.argv[2]).resolve()
    before=hashlib.sha256(source.read_bytes()).hexdigest()
    rows=[]
    for layer in ['compound','granular']:
        target=output/(layer+'-encrypted.dctle')
        assert not target.exists(),'Choose a fresh fixture output directory'
        params={'input_path':str(source),'output_path':str(target),'expiry':''}
        result=s.dctl('encrypt_native',params) if layer=='compound' else g.encrypt_dctl_native(**params)
        assert result.get('success') and target.is_file(),result
        data=target.read_bytes();digest=hashlib.sha256(data).hexdigest()
        assert data and result['bytes']==len(data) and result['sha256']==digest
        assert hashlib.sha256(source.read_bytes()).hexdigest()==before
        refused=s.dctl('encrypt_native',params) if layer=='compound' else g.encrypt_dctl_native(**params)
        assert not refused.get('success') and 'error' in refused,refused
        assert hashlib.sha256(target.read_bytes()).hexdigest()==digest
        rows.append({'layer':layer,'bytes':len(data),'source_unchanged':True,'repeat_refused':True,'mode':oct(target.stat().st_mode & 0o777)})
    (output/'receipt.json').write_text(json.dumps({'version':s.get_resolve().GetVersionString(),'results':rows},indent=2),encoding='utf-8')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':main()
