from __future__ import annotations
import base64, hashlib, json, os, subprocess, tempfile, time
from pathlib import Path
from urllib.parse import urlparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .config import CACHE, MAX_CACHE_GB
from .visual_contract import validate_visual_contract

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

def _audio_meta(probe: dict, min_seconds: float = 5.0, max_seconds: float = 60.0) -> dict:
    a = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), None)
    if not a: raise IngestError("download contains no audio stream")
    duration = float(a.get("duration") or probe.get("format", {}).get("duration") or 0)
    if not min_seconds <= duration <= max_seconds:
        raise IngestError(f"unexpected narration duration: {duration:.2f}s")
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

def ingest_scene_audio(encoded_segments: list[dict | str]) -> tuple[dict, list[dict]]:
    """Join independently synthesized beat audio and measure its real boundaries.

    Each visual beat is synthesized separately.  Decoding each part to PCM before
    concatenation makes its start/end timestamps evidence from the generated
    audio, rather than a timing estimate supplied by an upstream automation.
    """
    if not isinstance(encoded_segments, list) or not encoded_segments:
        raise IngestError("scene_audio_base64 must be a non-empty segment list")
    normalized: list[str] = []
    for index, item in enumerate(encoded_segments, 1):
        if isinstance(item, dict):
            supplied_number = item.get("scene_number")
            if supplied_number is not None:
                try:
                    if int(supplied_number) != index:
                        raise IngestError(f"scene audio {index}: scene_number is out of order")
                except (TypeError, ValueError) as exc:
                    raise IngestError(f"scene audio {index}: invalid scene_number") from exc
            item = item.get("audio_base64")
        if not isinstance(item, str) or not item:
            raise IngestError(f"scene audio {index}: audio_base64 is required")
        normalized.append(item)
    material = "|".join(normalized).encode()
    key = hashlib.sha256(material).hexdigest()
    dest = CACHE / f"{key}.wav"
    meta_path = CACHE / f"{key}.json"
    timings: list[dict] = []
    if dest.exists() and meta_path.is_file():
        try:
            cached = json.loads(meta_path.read_text(encoding="utf-8"))
            cached_timings = cached.get("speech_timings") or []
            if len(cached_timings) == len(normalized):
                os.utime(dest, None)
                return ({key: value for key, value in cached.items() if key != "speech_timings"}, cached_timings)
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        dest.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
    if not dest.exists():
        with tempfile.TemporaryDirectory(prefix="scene-audio-", dir=CACHE) as tmp_name:
            tmp = Path(tmp_name)
            wavs: list[Path] = []
            for index, encoded in enumerate(normalized, 1):
                try:
                    raw = base64.b64decode(str(encoded), validate=True)
                except Exception as exc:
                    raise IngestError(f"scene audio {index}: invalid base64: {exc}") from exc
                if len(raw) < 1_000:
                    raise IngestError(f"scene audio {index}: implausibly small")
                source = tmp / f"part-{index:02d}.mp3"
                source.write_bytes(raw)
                wav = tmp / f"part-{index:02d}.wav"
                command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                           "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)]
                result = subprocess.run(command, capture_output=True, text=True, timeout=90)
                if result.returncode or not wav.is_file():
                    raise IngestError(f"scene audio {index}: PCM decode failed: {result.stderr[-500:]}")
                wavs.append(wav)
            cursor = 0.0
            for index, wav in enumerate(wavs, 1):
                duration = _audio_meta(ffprobe(wav), min_seconds=0.6, max_seconds=60.0)["duration"]
                if duration < 0.6:
                    raise IngestError(f"scene audio {index}: shorter than the minimum visual beat")
                timings.append({"speech_start_seconds": round(cursor, 6), "speech_end_seconds": round(cursor + duration, 6)})
                cursor += duration
            listing = tmp / "concat.txt"
            listing.write_text("\n".join(f"file '{wav.as_posix()}'" for wav in wavs) + "\n", encoding="utf-8")
            joined = tmp / "joined.wav"
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                       "-i", str(listing), "-c:a", "pcm_s16le", str(joined)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            if result.returncode or not joined.is_file():
                raise IngestError(f"scene audio join failed: {result.stderr[-500:]}")
            os.replace(joined, dest)
    media = _audio_meta(ffprobe(dest))
    meta = {"key": key, "url": "inline://scene-tts", "kind": "scene_audio", "path": str(dest),
            "bytes": dest.stat().st_size, "speech_timings": timings, **media}
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.utime(dest, None)
    return meta, timings

def ingest_job(job: dict) -> dict:
    prune_cache()
    scene_audio = job.get("scene_audio_base64")
    speech_timings: list[dict] | None = None
    if scene_audio:
        audio, speech_timings = ingest_scene_audio(scene_audio)
    elif job.get("audio_base64"):
        audio=ingest_inline_audio(job["audio_base64"])
    else:
        audio_url=job.get("audio_url")
        if not audio_url: raise IngestError("audio_url or audio_base64 missing")
        audio=ingest([audio_url],"audio")
    scenes = []
    for index, s in enumerate(job.get("scenes") or []):
        if speech_timings:
            s = {**s, **speech_timings[index]}
        try: validate_visual_contract(s, s.get("scene_number") or s.get("scene") or "?")
        except ValueError as e: raise IngestError(str(e))
        primary = s.get("source_url") or s.get("direct_download_url")
        backups = s.get("backup_download_urls") or []
        if s.get("semantic_match") != "EXACT" or s.get("temporal_match") != "VERIFIED":
            raise IngestError(f"scene {s.get('scene_number') or s.get('scene')}: exact verified visual match required")
        shot_start=float(s.get("shot_start_seconds"))
        shot_end=float(s.get("shot_end_seconds"))
        if str(s.get("media_type") or "").upper() != "VIDEO":
            raise IngestError(f"scene {s.get('scene_number') or s.get('scene')}: real video source required")
        portrait=int(s.get("source_height") or s.get("height") or 0) > int(s.get("source_width") or s.get("width") or 0)
        media=ingest_video_segment([primary,*backups],shot_start,shot_end,portrait)
        scenes.append({**s, "validated_frame_time": 0.75, "source_start_offset": 0,
                       "local_path":media["path"],"ingested_from":media["url"],"ingest_meta":media})
    if not scenes: raise IngestError("job has no scenes")
    return {"audio": audio, "scenes": scenes}
