from __future__ import annotations
import json, tempfile, time, traceback
from pathlib import Path
from redis import Redis
from .config import REDIS_URL, TMP
from .pipeline import process, callback

def main():
    if not REDIS_URL: raise SystemExit("REDIS_URL missing")
    r=Redis.from_url(REDIS_URL,decode_responses=True,socket_connect_timeout=10,socket_timeout=15)
    r.ping(); print("KN worker ready; Redis queue connected",flush=True)
    while True:
        item=r.blpop("kn:queue",timeout=5)
        if not item: continue
        jid=item[1]; key=f"kn:job:{jid}"; row=r.hgetall(key)
        if not row: continue
        job=json.loads(row["payload"]); r.hset(key,mapping={"state":"WORKING","updated_at":str(time.time())})
        work=TMP/jid; work.mkdir(parents=True,exist_ok=True)
        try:
            result=process(job,work)
            r.hset(key,mapping={"state":"COMPLETED","result":json.dumps(result),"updated_at":str(time.time())})
        except Exception as e:
            err={"message":str(e),"traceback":traceback.format_exc()[-5000:]}
            r.hset(key,mapping={"state":"FAILED","error":json.dumps(err),"updated_at":str(time.time())})
            try: callback(job,{"event":"render.failed","content_id":job.get("content_id"),"error":str(e)})
            except Exception: pass

if __name__=="__main__": main()
