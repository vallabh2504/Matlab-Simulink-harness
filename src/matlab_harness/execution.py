"""Bounded native execution and explicit recovery of interrupted evidence intents."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import time
import uuid
from .decoding import file_source
from .project import ProjectError, atomic_json, digest, inside, now, read_json


def execute(argv, cwd, directory, timeout, max_bytes=16_777_216):
    from .runtime import _contain, _release, _stop_owned_process
    directory=Path(directory)
    status_path=directory/'process.json'
    record={'argv':argv,'cwd':str(cwd),'started_at':now(),'status':'STARTED','pid':None,'exit_code':None}
    atomic_json(status_path,record)
    process=job=None
    began=time.monotonic();deadline=began+timeout
    with (directory/'stdout.bin').open('wb') as out,(directory/'stderr.bin').open('wb') as err:
        try:
            process=subprocess.Popen(argv,cwd=cwd,stdin=subprocess.DEVNULL,stdout=out,stderr=err,shell=False,
                                     start_new_session=os.name!='nt',env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            record['pid']=process.pid;atomic_json(status_path,record)
            job=_contain(process)
            while True:
                if sum((directory/name).stat().st_size for name in ('stdout.bin','stderr.bin'))>max_bytes:
                    record['status']='OUTPUT_LIMIT';break
                left=deadline-time.monotonic()
                if left<=0:
                    record['status']='TIMED_OUT';break
                try:
                    process.wait(timeout=min(1,left))
                    record['status']='PASSED' if process.returncode==0 else 'FAILED'
                    if sum((directory/name).stat().st_size for name in ('stdout.bin','stderr.bin'))>max_bytes:
                        record['status']='OUTPUT_LIMIT'
                    break
                except subprocess.TimeoutExpired:pass
        except OSError as exc:
            record.update(status='LAUNCH_FAILED' if process is None else 'FAILED',error=str(exc))
        except KeyboardInterrupt:
            record['status']='INTERRUPTED'
        finally:
            if process is not None:
                if process.poll() is None:record['cleanup']=_stop_owned_process(process)
                record.setdefault('cleanup',{}).update(_release(process,job))
                record['exit_code']=process.poll()
    record.update(finished_at=now(),wall_seconds=round(time.monotonic()-began,6),
                  stdout=file_source(directory/'stdout.bin'),stderr=file_source(directory/'stderr.bin'))
    atomic_json(status_path,record)
    return record


def recover(project,owner,kind,identifier,stopped_process_attestation,reason):
    if kind not in {'probe','semantic'} or not all(isinstance(v,str) and v.strip() for v in (identifier,stopped_process_attestation,reason)):
        raise ProjectError("Recovery requires execution kind/id, stopped-process attestation and inspection reason")
    field='probe_receipts' if kind=='probe' else 'semantic_results'
    with project.transaction(owner) as data:
        entry=data.get(field,{}).get(identifier)
        if not entry or entry.get('status')!='STARTED':raise ProjectError("Only a retained interrupted STARTED intent can be recovered")
        path=inside(project.root,entry['path']);record=read_json(path)
        archive=project.control/'history'/('interrupted-'+uuid.uuid4().hex+'.json')
        atomic_json(archive,record)
        record.update(status='INTERRUPTED',recovery={'actor':owner,'at':now(),'stopped_process_attestation':stopped_process_attestation,
                      'reason':reason,'assurance':'operator-attested','original_record':archive.relative_to(project.root).as_posix()})
        atomic_json(path,record)
        entry.update(status='INTERRUPTED',sha256=digest(path))
    return {'status':'INTERRUPTED','accepted':False,'id':identifier,'kind':kind,'recovery':record['recovery']}
