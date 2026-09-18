from __future__ import annotations
import json, os, subprocess, sys, time
from pathlib import Path
from .config import ROOT

MARKER = ROOT / "stress-50-passed.json"

def main():
    requested = int(os.environ.get("KN_STRESS_ONCE", "0") or 0)
    if requested > 0 and not MARKER.exists():
        print(f"KN preflight: running {requested} deterministic renders before worker activation", flush=True)
        started=time.time()
        p=subprocess.run([sys.executable,"-m","vps.stress_test","--iterations",str(requested)])
        if p.returncode != 0:
            raise SystemExit(p.returncode)
        MARKER.write_text(json.dumps({"iterations":requested,"passed":True,"finished_at":time.time(),"elapsed_seconds":round(time.time()-started,1)},indent=2),encoding="utf-8")
        print(f"KN preflight passed: {requested}/{requested}; activating worker", flush=True)
    os.execv(sys.executable,[sys.executable,"-m","vps.worker"])

if __name__=="__main__":
    main()
