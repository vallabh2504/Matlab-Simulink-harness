"""Trusted child wrapper: record the actual uncaught Python exception, not log text."""
from __future__ import annotations
import json
from pathlib import Path
import runpy
import sys
import traceback


def main():
    script=Path(sys.argv[1]).resolve()
    proof=Path(sys.argv[2]).resolve()
    arguments=sys.argv[3:]
    sys.argv=[str(script),*arguments]
    sys.path.insert(0,str(script.parent))
    record={'version':1,'ok':True,'is_assertion':False,'type':None,'message':None}
    code=0
    try:
        runpy.run_path(str(script),run_name='__main__')
    except BaseException as exc:
        if not isinstance(exc,SystemExit) or exc.code not in (None,0):
            record.update(ok=False,is_assertion=type(exc) is AssertionError,
                          type=type(exc).__module__+'.'+type(exc).__qualname__,message=str(exc)[:1_048_576])
            code=1
            traceback.print_exc()
    proof.write_text(json.dumps(record,ensure_ascii=True,allow_nan=False),encoding='utf-8')
    return code


if __name__=='__main__':
    raise SystemExit(main())
