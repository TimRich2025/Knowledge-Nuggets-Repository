from __future__ import annotations
import json, re, time, uuid
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from redis import Redis
from .config import API_TOKEN, REDIS_URL

app=FastAPI(title="Knowledge Nuggets Render Worker",version="1.1")

class Job(BaseModel):
    content_id: str = Field(min_length=1,max_length=120)
    production_status: str
    core_question_lines: list[str]
    audio_url: str
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
    auth(authorization)
    if job.production_status != "READY": raise HTTPException(422,"production_status must be READY")
    if len(job.core_question_lines)!=2: raise HTTPException(422,"exactly two core question lines required")
    if not job.scenes: raise HTTPException(422,"at least one scene required")
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
