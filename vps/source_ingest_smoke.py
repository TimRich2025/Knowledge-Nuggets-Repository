from __future__ import annotations
import json, time
from .source_cache import ingest

URLS=[
    "https://download.blender.org/durian/trailer/sintel_trailer-1080p.mp4",
]

def main():
    t=time.time()
    first=ingest(URLS,"video")
    t1=time.time()
    second=ingest(URLS,"video")
    print(json.dumps({
        "status":"PASS",
        "source":first["url"],
        "width":first["width"],
        "height":first["height"],
        "duration":first["duration"],
        "bytes":first["bytes"],
        "first_ingest_seconds":round(t1-t,2),
        "cached_reingest_seconds":round(time.time()-t1,2),
        "same_cache_path":first["path"]==second["path"],
    },indent=2),flush=True)

if __name__=="__main__":
    main()
