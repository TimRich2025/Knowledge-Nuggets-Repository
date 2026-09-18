from __future__ import annotations
import multiprocessing as mp
import os, signal, sys
import uvicorn
from .worker import main as worker_main

def main():
    worker=mp.Process(target=worker_main,name="kn-worker",daemon=True)
    worker.start()
    try:
        port=int(os.environ.get("PORT","8080"))
        uvicorn.run("vps.api:app",host="0.0.0.0",port=port,log_level="info")
    finally:
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=10)

if __name__=="__main__":
    main()
