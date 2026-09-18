from __future__ import annotations
import json, os, time, traceback
from pathlib import Path
from .config import PENDING, WORKING, COMPLETED, FAILED, TMP, POLL_SECONDS
from .pipeline import process, callback

def claim() -> Path | None:
    for p in sorted(PENDING.glob("*.json")):
        dst=WORKING/p.name
        try:
            os.replace(p,dst); return dst
        except FileNotFoundError:
            continue
    return None

def main():
    print("KN worker ready",flush=True)
    while True:
        p=claim()
        if not p:
            time.sleep(POLL_SECONDS); continue
        job=json.loads(p.read_text(encoding="utf-8")); work=TMP/p.stem
        work.mkdir(parents=True,exist_ok=True)
        try:
            result=process(job,work); job["_result"]=result
            p.write_text(json.dumps(job,indent=2),encoding="utf-8")
            os.replace(p,COMPLETED/p.name)
        except Exception as e:
            job["_error"]={"message":str(e),"traceback":traceback.format_exc()[-5000:]}
            p.write_text(json.dumps(job,indent=2),encoding="utf-8")
            os.replace(p,FAILED/p.name)
            try: callback(job,{"event":"render.failed","content_id":job.get("content_id"),"error":str(e)})
            except Exception: pass

if __name__=="__main__": main()
