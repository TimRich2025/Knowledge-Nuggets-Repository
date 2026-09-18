from __future__ import annotations
import json, re, time, uuid
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from .config import API_TOKEN, PENDING, WORKING, COMPLETED, FAILED

app=FastAPI(title="Knowledge Nuggets Render Worker",version="1.0")

class Job(BaseModel):
    content_id: str = Field(min_length=1,max_length=120)
    production_status: str
    core_question_lines: list[str]
    audio_url: str
    scenes: list[dict]
    callback_url: str | None = None

def auth(authorization: str | None):
    if not API_TOKEN: raise HTTPException(503,"KN_API_TOKEN is not configured")
    if authorization != f"Bearer {API_TOKEN}": raise HTTPException(401,"unauthorized")

def safe_id(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+","-",v).strip("-")[:80] or "job"

@app.get("/health")
def health():
    return {"ok":True,"service":"kn-render-worker","layout":"KN_LAYOUT_V1"}

@app.post("/jobs",status_code=202)
def submit(job: Job, authorization: str | None = Header(default=None)):
    auth(authorization)
    if job.production_status != "READY": raise HTTPException(422,"production_status must be READY")
    if len(job.core_question_lines)!=2: raise HTTPException(422,"exactly two core question lines required")
    if not job.scenes: raise HTTPException(422,"at least one scene required")
    jid=f"{safe_id(job.content_id)}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    path=PENDING/f"{jid}.json"
    path.write_text(job.model_dump_json(indent=2),encoding="utf-8")
    return {"accepted":True,"job_id":jid,"state":"PENDING"}

@app.get("/jobs/{job_id}")
def status(job_id: str, authorization: str | None = Header(default=None)):
    auth(authorization); name=f"{safe_id(job_id)}.json"
    for state,folder in [("PENDING",PENDING),("WORKING",WORKING),("COMPLETED",COMPLETED),("FAILED",FAILED)]:
        p=folder/name
        if p.exists():
            data=json.loads(p.read_text(encoding="utf-8"))
            return {"job_id":job_id,"state":state,"result":data.get("_result"),"error":data.get("_error")}
    raise HTTPException(404,"job not found")
