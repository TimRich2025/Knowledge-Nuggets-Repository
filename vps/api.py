from __future__ import annotations
import hashlib, hmac, json, re, time, uuid
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from redis import Redis
from .config import API_TOKEN, REDIS_URL, OUTPUTS, ALLOWED_CALLBACK_URL

app=FastAPI(title="Knowledge Nuggets Render Worker",version="1.1")

class Job(BaseModel):
    content_id: str = Field(min_length=1,max_length=120)
    production_status: str
    core_question_lines: list[str]
    audio_url: str | None = None
    audio_base64: str | None = None
    scenes: list[dict]
    callback_url: str | None = None

def db():
    if not REDIS_URL: raise HTTPException(503,"REDIS_URL is not configured")
    return Redis.from_url(REDIS_URL,decode_responses=True,socket_connect_timeout=5,socket_timeout=5)

def auth(authorization: str | None):
    if not API_TOKEN: raise HTTPException(503,"KN_API_TOKEN is not configured")
    if authorization != f"Bearer {API_TOKEN}": raise HTTPException(401,"unauthorized")

def safe_id(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+","-",v).strip("-")[:80] or "job"

@app.get("/health")
def health():
    try: db().ping(); queue="ok"
    except Exception as e: raise HTTPException(503,f"queue unavailable: {e}")
    return {"ok":True,"service":"kn-render-api","queue":queue,"layout":"KN_LAYOUT_V1"}

@app.post("/jobs",status_code=202)
def submit(job: Job, authorization: str | None = Header(default=None)):
    make_callback_ok = bool(ALLOWED_CALLBACK_URL and job.callback_url == ALLOWED_CALLBACK_URL)
    if not make_callback_ok:
        auth(authorization)
    if job.production_status != "READY": raise HTTPException(422,"production_status must be READY")
    if len(job.core_question_lines)!=2: raise HTTPException(422,"exactly two core question lines required")
    if not job.scenes: raise HTTPException(422,"at least one scene required")
    if not job.audio_url and not job.audio_base64: raise HTTPException(422,"audio_url or audio_base64 required")
    jid=f"{safe_id(job.content_id)}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    r=db(); payload=job.model_dump(); payload["_job_id"]=jid
    r.hset(f"kn:job:{jid}",mapping={"state":"PENDING","payload":json.dumps(payload),"updated_at":str(time.time())})
    r.rpush("kn:queue",jid)
    return {"accepted":True,"job_id":jid,"state":"PENDING"}

@app.get("/jobs/{job_id}")
def status(job_id: str, authorization: str | None = Header(default=None)):
    auth(authorization); r=db(); data=r.hgetall(f"kn:job:{safe_id(job_id)}")
    if not data: raise HTTPException(404,"job not found")
    return {"job_id":job_id,"state":data.get("state"),"result":json.loads(data["result"]) if data.get("result") else None,"error":json.loads(data["error"]) if data.get("error") else None}


@app.get("/jobs/{job_id}/preview")
def preview(job_id: str, authorization: str | None = Header(default=None)):
    auth(authorization); r=db(); data=r.hgetall(f"kn:job:{safe_id(job_id)}")
    if not data: raise HTTPException(404,"job not found")
    if data.get("state") != "COMPLETED" or not data.get("result"):
        raise HTTPException(409,"preview is not ready")
    result=json.loads(data["result"]); p=Path(result.get("preview_path") or "").resolve()
    root=OUTPUTS.resolve()
    if root not in p.parents or not p.is_file():
        raise HTTPException(404,"preview artifact unavailable")
    return FileResponse(p,media_type="video/mp4",filename=f"{safe_id(job_id)}.mp4")


@app.get("/preview/{content_id}")
def public_preview(content_id: str, token: str):
    cid=safe_id(content_id)
    expected=hashlib.sha256(f"{API_TOKEN}:{cid}".encode()).hexdigest()
    if not API_TOKEN or not hmac.compare_digest(token,expected):
        raise HTTPException(401,"invalid preview token")
    p=(OUTPUTS/cid/"preview.mp4").resolve(); root=OUTPUTS.resolve()
    if root not in p.parents or not p.is_file():
        raise HTTPException(404,"preview artifact unavailable")
    return FileResponse(p,media_type="video/mp4",filename=f"{cid}.mp4")
