from __future__ import annotations
import json, os, subprocess, sys, time
from .config import ROOT

STRESS_MARKER = ROOT / "stress-50-passed.json"
SOURCE_MARKER = ROOT / "source-ingest-smoke-passed.json"

def main():
    requested=int(os.environ.get("KN_STRESS_ONCE","0") or 0)
    if requested > 0 and not STRESS_MARKER.exists():
        print(f"KN preflight: running {requested} deterministic renders before service activation",flush=True)
        started=time.time()
        p=subprocess.run([sys.executable,"-m","vps.stress_test","--iterations",str(requested)])
        if p.returncode != 0:
            raise SystemExit(p.returncode)
        STRESS_MARKER.write_text(json.dumps({"iterations":requested,"passed":True,"finished_at":time.time(),"elapsed_seconds":round(time.time()-started,1)},indent=2),encoding="utf-8")
        print(f"KN preflight passed: {requested}/{requested}",flush=True)

    if os.environ.get("KN_SOURCE_SMOKE_ONCE","0") == "1" and not SOURCE_MARKER.exists():
        print("KN source-ingest smoke: starting",flush=True)
        p=subprocess.run([sys.executable,"-m","vps.source_ingest_smoke"])
        if p.returncode != 0:
            raise SystemExit(p.returncode)
        SOURCE_MARKER.write_text(json.dumps({"passed":True,"finished_at":time.time()},indent=2),encoding="utf-8")
        print("KN source-ingest smoke: PASS",flush=True)

    print("KN gates passed; activating API + worker",flush=True)
    os.execv(sys.executable,[sys.executable,"-m","vps.service"])

if __name__=="__main__":
    main()
