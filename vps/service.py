from __future__ import annotations
import os
import threading
import traceback

import uvicorn

from .worker import main as worker_main


def run_worker() -> None:
    """Keep the queue consumer in-process so Puck has enough memory.

    The previous multiprocessing wrapper duplicated the complete Python module
    graph before launching the isolated TTS process.  A thread shares those
    read-only modules with FastAPI and leaves that memory to the FP16 model.
    """
    try:
        worker_main()
    except BaseException:
        traceback.print_exc()
        print("KN worker thread exited; terminating service for Railway restart", flush=True)
        os._exit(1)


def main():
    worker = threading.Thread(target=run_worker, name="kn-worker", daemon=True)
    worker.start()
    try:
        port=int(os.environ.get("PORT","8080"))
        uvicorn.run("vps.api:app",host="0.0.0.0",port=port,log_level="info")
    finally:
        os._exit(0)

if __name__=="__main__":
    main()
