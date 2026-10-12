from __future__ import annotations
import json, shutil, time, traceback
from pathlib import Path
from redis import Redis
from .config import REDIS_URL, TMP, YOUTUBE_OAUTH_REDIRECT_URI, YOUTUBE_OAUTH_REFRESH_TOKEN
from .pipeline import process, callback
from .source_cache import prune_cache
from .youtube_publisher import YouTubePublishError, exchange_authorization_code

def clean_work_dir(path: Path) -> None:
    """Remove render intermediates; finished previews live under OUTPUTS."""
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def consume_youtube_oauth_code(r: Redis) -> None:
    """Turn the short-lived browser code into a refresh token inside Railway.

    The refresh token never travels through Make, GitHub, a local terminal or
    the browser response. It remains in the protected production Redis store.
    """
    code = r.getdel("kn:youtube_oauth:code")
    if not code:
        return
    try:
        refresh_token = exchange_authorization_code(code, YOUTUBE_OAUTH_REDIRECT_URI)
        r.set("kn:youtube_oauth:refresh_token", refresh_token)
        r.setex("kn:youtube_oauth:status", 600, "READY")
        print("KN YouTube OAuth refresh token ready", flush=True)
    except YouTubePublishError as exc:
        r.setex("kn:youtube_oauth:error", 600, str(exc))
        r.setex("kn:youtube_oauth:status", 600, "FAILED")
        print(f"KN YouTube OAuth token exchange failed: {exc}", flush=True)


def recover_recent_audio_jobs(r: Redis, now: float | None = None) -> int:
    """Requeue the narrowly identified jobs superseded by an audio migration.

    The payload already passed Make and the API contract, so recreating it in
    Make is unnecessary. A per-job marker prevents restart loops and the exact
    backend/mode match prevents unrelated completed videos being duplicated.
    """
    current = float(now if now is not None else time.time())
    recovered = 0
    for key in r.scan_iter("kn:job:*"):
        row = r.hgetall(key)
        try:
            age = current - float(row.get("updated_at") or 0)
            error = json.loads(row.get("error") or "{}")
            result = json.loads(row.get("result") or "{}")
            json.loads(row.get("payload") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not 0 <= age <= 48 * 3600:
            continue
        state = row.get("state")
        old_edge_failure = (state == "FAILED" and
                            "neural TTS failed after retries" in str(error.get("message") or ""))
        old_audio_render = (
            state == "COMPLETED"
            and result.get("narration_backend") == "kokoro-af-bella-continuous"
            and result.get("soundtrack_mode") == "procedural-upbeat"
        )
        if not (old_edge_failure or old_audio_render):
            continue
        jid = str(key).removeprefix("kn:job:")
        migration = "edge-v1" if old_edge_failure else "male-fp16-music-v1"
        marker = f"kn:recovery:{migration}:{jid}"
        if not r.set(marker, "1", nx=True, ex=7 * 24 * 3600):
            continue
        r.hset(key, mapping={"state": "QUEUED", "result": "", "error": "",
                             "updated_at": str(current)})
        r.rpush("kn:queue", jid)
        recovered += 1
        print(f"KN requeued audio migration {migration}: {jid}", flush=True)
    return recovered

def main():
    if not REDIS_URL: raise SystemExit("REDIS_URL missing")
    r=Redis.from_url(REDIS_URL,decode_responses=True,socket_connect_timeout=10,socket_timeout=15)
    r.ping()
    # A restart must recover space left by interrupted or failed renders.
    for stale in TMP.iterdir():
        clean_work_dir(stale)
    cache_cleanup=prune_cache()
    recovered=recover_recent_audio_jobs(r)
    print(f"KN startup cache cleanup: {cache_cleanup}",flush=True)
    print(f"KN worker ready; Redis queue connected; recovered={recovered}",flush=True)
    while True:
        consume_youtube_oauth_code(r)
        item=r.blpop("kn:queue",timeout=5)
        if not item: continue
        jid=item[1]; key=f"kn:job:{jid}"; row=r.hgetall(key)
        if not row: continue
        job=json.loads(row["payload"]); r.hset(key,mapping={"state":"WORKING","updated_at":str(time.time())})
        work=TMP/jid; work.mkdir(parents=True,exist_ok=True)
        try:
            refresh_token = r.get("kn:youtube_oauth:refresh_token") or YOUTUBE_OAUTH_REFRESH_TOKEN
            result=process(job,work,refresh_token)
            r.hset(key,mapping={"state":"COMPLETED","result":json.dumps(result),"updated_at":str(time.time())})
        except Exception as e:
            err={"message":str(e),"traceback":traceback.format_exc()[-5000:]}
            r.hset(key,mapping={"state":"FAILED","error":json.dumps(err),"updated_at":str(time.time())})
            try: callback(job,{"event":"render.failed","content_id":job.get("content_id"),"error":str(e)})
            except Exception: pass
        finally:
            clean_work_dir(work)

if __name__=="__main__": main()
