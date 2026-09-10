"""Stage native DCTL encryption, then publish without replacing an existing file."""
import errno
import hashlib
import os
from pathlib import Path
import shutil
import tempfile


def encrypt_dctl(r, input_path, output_path, expiry, safe_dir):
    if not isinstance(input_path,str) or not input_path or not isinstance(output_path,str) or not output_path:
        return {'error':'input_path and output_path must be non-empty strings'}
    if expiry is not None and not isinstance(expiry,str):
        return {'error':'expiry must be an ISO 8601 string or null'}
    source=Path(input_path).expanduser().absolute()
    target=Path(output_path).expanduser().absolute()
    if source.suffix.lower()!='.dctl' or not source.is_file():
        return {'error':'input_path must name an existing .dctl file'}
    if target.suffix.lower()!='.dctle':
        return {'error':'output_path must end in .dctle'}
    if os.path.lexists(target):
        return {'error':'Output already exists; refusing to overwrite','success':False}
    try:
        target.parent.mkdir(parents=True,exist_ok=True)
        staging_root=Path(safe_dir(str(target.parent.resolve())))
        staging_root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='resolve-mcp-dctl-',dir=staging_root) as stage:
            # Native Name is a stem: Resolve appends .dctle itself. Use a fixed
            # staging name, so user filename characters never become native paths.
            options={'Name':'encrypted','OutputFolder':stage,'Expiry':None if expiry=='' else expiry}
            if not r.EncryptDCTL(str(source),options):
                return {'success':False}
            encrypted=Path(stage)/'encrypted.dctle'
            if encrypted.is_symlink() or not encrypted.is_file() or encrypted.stat().st_size==0:
                return {'success':False,'error':'Resolve reported success without a non-empty encrypted file'}
            os.chmod(encrypted,0o600)
            digest=hashlib.sha256(encrypted.read_bytes()).hexdigest()
            size=encrypted.stat().st_size
            try:
                os.link(encrypted,target)
            except OSError as exc:
                if exc.errno not in (errno.EXDEV,errno.EPERM,errno.EOPNOTSUPP,errno.ENOSYS):
                    raise
                # Cross-volume/no-hardlink filesystem: exclusive creation still
                # prevents overwriting an existing target, including a symlink.
                fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                try:
                    with os.fdopen(fd,'wb') as out, encrypted.open('rb') as src:
                        shutil.copyfileobj(src,out)
                        out.flush()
                        os.fsync(out.fileno())
                except BaseException:
                    target.unlink(missing_ok=True)
                    raise
            return {'success':True,'path':str(target),'bytes':size,'sha256':digest}
    except FileExistsError:
        return {'success':False,'error':'Output appeared during encryption; refusing to overwrite'}
    except Exception as exc:
        return {'success':False,'error':'Encryption/export failed: '+(str(exc) or type(exc).__name__)}
