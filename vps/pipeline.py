from __future__ import annotations
import hashlib, json, os, time
from pathlib import Path
import requests
from .config import OUTPUTS, CALLBACK_TOKEN, API_TOKEN, PUBLIC_BASE_URL, YOUTUBE_UPLOAD_ENABLED
from .source_cache import ingest_job
from .local_renderer import render_job
from .social_metadata import build_social_metadata
from .youtube_publisher import publish_private_short

def callback(job: dict, payload: dict):
    url=job.get("callback_url")
    if not url: return
    headers={"Content-Type":"application/json"}
    if CALLBACK_TOKEN: headers["Authorization"]=f"Bearer {CALLBACK_TOKEN}"
    requests.post(url,json=payload,headers=headers,timeout=30).raise_for_status()

def process(job: dict, work_dir: Path) -> dict:
    started=time.time()
    # Phase A may use the network. It must finish completely before rendering starts.
    ingested=ingest_job(job)
    (work_dir/"ingested.json").write_text(json.dumps(ingested,indent=2),encoding="utf-8")

    # Phase B is local-only: render_job receives filesystem paths, never remote URLs.
    result=render_job(job,ingested,work_dir)
    content_id=str(job.get("content_id") or work_dir.name)
    final_dir=OUTPUTS/content_id
    final_dir.mkdir(parents=True,exist_ok=True)
    preview=Path(result["preview_path"])
    final_preview=final_dir/"preview.mp4"
    # TMP and OUTPUTS share the persistent /data volume.  Copying briefly
    # doubles the finished video's disk usage and can exhaust the small free
    # volume.  An atomic move preserves the artifact without that duplicate.
    os.replace(preview,final_preview)
    token=hashlib.sha256(f"{API_TOKEN}:{content_id}".encode()).hexdigest() if API_TOKEN else ""
    preview_url=f"{PUBLIC_BASE_URL}/preview/{content_id}?token={token}" if PUBLIC_BASE_URL and token else ""
    result={**result,"content_id":content_id,"preview_path":str(final_preview),"preview_url":preview_url,"elapsed_seconds":round(time.time()-started,2)}
    if YOUTUBE_UPLOAD_ENABLED:
        topic = str(job.get("topic") or " ".join(job.get("core_question_lines") or [])).strip()
        fact_statement = str(job.get("fact_statement") or " ".join(
            str(scene.get("spoken_phrase") or "") for scene in job.get("scenes") or []
        )).strip()
        metadata = build_social_metadata(topic, fact_statement)
        result["youtube"] = publish_private_short(final_preview, metadata["title"], metadata["description"])
    else:
        result["youtube"] = {"status": "DISABLED"}
    (final_dir/"result.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    callback(job,{"event":"publish.completed" if YOUTUBE_UPLOAD_ENABLED else "render.completed",**result})
    return result
