from __future__ import annotations
import json, shutil, time, traceback
from pathlib import Path
from redis import Redis
from .config import REDIS_URL, TMP, YOUTUBE_OAUTH_REDIRECT_URI
from .pipeline import process, callback
from .youtube_publisher import YouTubePublishError, exchange_authorization_code

def clean_work_dir(path: Path) -> None:
    """Remove render intermediates; finished previews live under OUTPUTS."""
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def consume_youtube_oauth_code(r: Redis) -> None:
    """Turn the short-lived browser code into a refresh token inside Railway.

    The refresh token never travels through Make, GitHub or a local terminal.
    It is exposed only once on the same one-time browser session that granted
    consent, then stored as a protected worker variable.
    """
    code = r.getdel("kn:youtube_oauth:code")
    if not code:
        return
    try:
        refresh_token = exchange_authorization_code(code, YOUTUBE_OAUTH_REDIRECT_URI)
        r.setex("kn:youtube_oauth:result", 600, refresh_token)
        r.setex("kn:youtube_oauth:status", 600, "READY")
        print("KN YouTube OAuth refresh token ready", flush=True)
    except YouTubePublishError as exc:
        r.setex("kn:youtube_oauth:error", 600, str(exc))
        r.setex("kn:youtube_oauth:status", 600, "FAILED")
        print(f"KN YouTube OAuth token exchange failed: {exc}", flush=True)

def main():
    if not REDIS_URL: raise SystemExit("REDIS_URL missing")
    r=Redis.from_url(REDIS_URL,decode_responses=True,socket_connect_timeout=10,socket_timeout=15)
    r.ping()
    # A restart must recover space left by interrupted or failed renders.
    for stale in TMP.iterdir():
        clean_work_dir(stale)
    print("KN worker ready; Redis queue connected",flush=True)
    while True:
        consume_youtube_oauth_code(r)
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
        finally:
            clean_work_dir(work)

if __name__=="__main__": main()
