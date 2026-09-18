from __future__ import annotations
import base64, hashlib, json, os, subprocess, time
from pathlib import Path
from urllib.parse import urlparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .config import CACHE, MAX_CACHE_GB

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "KnowledgeNuggetsSourceIngest/1.0"})
SESSION.mount("https://", HTTPAdapter(max_retries=Retry(
    total=4, connect=4, read=4, status=4, backoff_factor=1.5,
    status_forcelist=[500, 502, 503, 504], allowed_methods=frozenset(["GET"])
)))
SESSION.mount("http://", HTTPAdapter(max_retries=Retry(
    total=4, connect=4, read=4, status=4, backoff_factor=1.5,
    status_forcelist=[500, 502, 503, 504], allowed_methods=frozenset(["GET"])
)))

class IngestError(RuntimeError): pass

def prune_cache() -> None:
    limit=max(0.05,float(MAX_CACHE_GB))*1024**3
    files=[p for p in CACHE.iterdir() if p.is_file() and p.suffix != ".json"]
    total=sum(p.stat().st_size for p in files)
    if total <= limit:
        return
    for p in sorted(files,key=lambda x:x.stat().st_atime):
        if total <= limit:
            break
        size=p.stat().st_size
        key=p.stem
        p.unlink(missing_ok=True)
        (CACHE/f"{key}.json").unlink(missing_ok=True)
        total-=size


def _key(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()

def _suffix(url: str, fallback: str) -> str:
    s = Path(urlparse(url).path).suffix.lower()
    return s if 1 < len(s) <= 6 else fallback

def ffprobe(path: Path) -> dict:
    p = subprocess.run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ], capture_output=True, text=True, timeout=45)
    if p.returncode:
        raise IngestError(f"ffprobe failed for {path.name}: {p.stderr[-500:]}")
    return json.loads(p.stdout)

def _video_meta(probe: dict) -> dict:
    v = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v: raise IngestError("download contains no video stream")
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    duration = float(v.get("duration") or probe.get("format", {}).get("duration") or 0)
    if duration < 1: raise IngestError("video is shorter than one second")
    if not ((w >= 1920 and h >= 1080) or (h >= 1920 and w >= 1080)):
        raise IngestError(f"video below Full HD gate: {w}x{h}")
    return {"width": w, "height": h, "duration": duration, "codec": v.get("codec_name")}

def _audio_meta(probe: dict) -> dict:
    a = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not a: raise IngestError("download contains no audio stream")
    duration = float(a.get("duration") or probe.get("format", {}).get("duration") or 0)
    if not 5 <= duration <= 60: raise IngestError(f"unexpected narration duration: {duration:.2f}s")
    return {"duration": duration, "codec": a.get("codec_name")}

def _download(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.unlink(missing_ok=True)
    with SESSION.get(url, stream=True, timeout=(15, 120), allow_redirects=True) as r:
        if r.status_code == 429:
            raise IngestError(f"origin rate limited source: {url}")
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk: f.write(chunk)
    if tmp.stat().st_size < 32_000:
        tmp.unlink(missing_ok=True)
        raise IngestError("download is implausibly small")
    os.replace(tmp, dest)

def ingest(urls: list[str], kind: str) -> dict:
    errors = []
    fallback_suffix = ".mp4" if kind == "video" else ".audio"
    for url in [u for u in urls if u]:
        key = _key(url)
        dest = CACHE / f"{key}{_suffix(url, fallback_suffix)}"
        meta_path = CACHE / f"{key}.json"
        try:
            if not dest.exists():
                _download(url, dest)
            probe = ffprobe(dest)
            media = _video_meta(probe) if kind == "video" else _audio_meta(probe)
            meta = {"key": key, "url": url, "kind": kind, "path": str(dest), "bytes": dest.stat().st_size, **media}
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            os.utime(dest, None)
            return meta
        except Exception as e:
            errors.append(f"{url}: {e}")
            dest.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            time.sleep(1)
    raise IngestError("all approved sources failed ingest: " + " | ".join(errors))


def ingest_video_segment(urls: list[str], shot_start: float, shot_end: float, portrait: bool = False) -> dict:
    errors=[]
    start=max(0.0,float(shot_start))
    end=float(shot_end)
    length=end-start
    if length < 1.5:
        raise IngestError("verified shot interval must be at least 1.5 seconds")
    for url in [u for u in urls if u]:
        key=hashlib.sha256(f"{url}|{start:.3f}|{end:.3f}|1080".encode()).hexdigest()
        dest=CACHE/f"{key}.mp4"; meta_path=CACHE/f"{key}.json"
        tmp=dest.with_name(dest.stem+".part.mp4")
        try:
            prune_cache()
            if not dest.exists():
                tmp.unlink(missing_ok=True)
                scale="1080:-2" if portrait else "-2:1080"
                cmd=["ffmpeg","-hide_banner","-loglevel","error","-y",
                     "-user_agent","KnowledgeNuggetsSourceIngest/3.0",
                     "-ss",f"{start:.3f}","-i",url,"-t",f"{length:.3f}",
                     "-an","-vf",f"scale={scale}",
                     "-c:v","libx264","-threads","2","-preset","veryfast","-crf","18","-pix_fmt","yuv420p",
                     "-movflags","+faststart",str(tmp)]
                p=subprocess.run(cmd,capture_output=True,text=True,timeout=180)
                if p.returncode:
                    err=p.stderr[-1200:]
                    if "429" in err or "Too Many Requests" in err:
                        raise IngestError(f"origin rate limited source: {url}")
                    raise IngestError(f"verified-shot ingest failed: {err}")
                if not tmp.exists() or tmp.stat().st_size < 32_000:
                    raise IngestError("verified shot is implausibly small")
                os.replace(tmp,dest)
            probe=ffprobe(dest); media=_video_meta(probe)
            meta={"key":key,"url":url,"kind":"verified_shot","path":str(dest),"bytes":dest.stat().st_size,
                  "shot_start_seconds":start,"shot_end_seconds":end,**media}
            meta_path.write_text(json.dumps(meta,indent=2),encoding="utf-8"); os.utime(dest,None)
            return meta
        except Exception as e:
            errors.append(f"{url}: {e}")
            dest.unlink(missing_ok=True); meta_path.unlink(missing_ok=True); tmp.unlink(missing_ok=True)
            time.sleep(1)
    raise IngestError("all approved exact-shot sources failed ingest: "+" | ".join(errors))

def ingest_inline_audio(encoded: str) -> dict:
    try:
        raw=base64.b64decode(encoded,validate=True)
    except Exception as e:
        raise IngestError(f"invalid audio_base64: {e}")
    if len(raw) < 32_000:
        raise IngestError("inline narration is implausibly small")
    key=hashlib.sha256(raw).hexdigest()
    dest=CACHE/f"{key}.mp3"; meta_path=CACHE/f"{key}.json"
    if not dest.exists():
        tmp=dest.with_suffix(".mp3.part"); tmp.write_bytes(raw); os.replace(tmp,dest)
    probe=ffprobe(dest); media=_audio_meta(probe)
    meta={"key":key,"url":"inline://make-tts","kind":"audio","path":str(dest),"bytes":dest.stat().st_size,**media}
    meta_path.write_text(json.dumps(meta,indent=2),encoding="utf-8"); os.utime(dest,None)
    return meta

def ingest_job(job: dict) -> dict:
    prune_cache()
    if job.get("audio_base64"):
        audio=ingest_inline_audio(job["audio_base64"])
    else:
        audio_url=job.get("audio_url")
        if not audio_url: raise IngestError("audio_url or audio_base64 missing")
        audio=ingest([audio_url],"audio")
    scenes = []
    for s in job.get("scenes") or []:
        primary = s.get("source_url") or s.get("direct_download_url")
        backups = s.get("backup_download_urls") or []
        if s.get("semantic_match") != "EXACT" or s.get("temporal_match") != "VERIFIED":
            raise IngestError(f"scene {s.get('scene_number') or s.get('scene')}: exact verified visual match required")
        shot_start=float(s.get("shot_start_seconds"))
        shot_end=float(s.get("shot_end_seconds"))
        portrait=int(s.get("source_height") or s.get("height") or 0) > int(s.get("source_width") or s.get("width") or 0)
        media=ingest_video_segment([primary,*backups],shot_start,shot_end,portrait)
        scenes.append({**s, "validated_frame_time": 0.75, "source_start_offset": 0,
                       "local_path":media["path"],"ingested_from":media["url"],"ingest_meta":media})
    if not scenes: raise IngestError("job has no scenes")
    return {"audio": audio, "scenes": scenes}
