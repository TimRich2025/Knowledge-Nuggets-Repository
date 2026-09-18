from __future__ import annotations
import multiprocessing as mp
import os, threading
import uvicorn
from .worker import main as worker_main

def main():
    worker=mp.Process(target=worker_main,name="kn-worker",daemon=True)
    worker.start()

    def monitor_worker():
        worker.join()
        code=worker.exitcode if worker.exitcode is not None else 1
        print(f"KN worker exited with code {code}; terminating service for Railway restart",flush=True)
        os._exit(code or 1)

    threading.Thread(target=monitor_worker,name="kn-worker-monitor",daemon=True).start()
    try:
        port=int(os.environ.get("PORT","8080"))
        uvicorn.run("vps.api:app",host="0.0.0.0",port=port,log_level="info")
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=10)

if __name__=="__main__":
    main()
