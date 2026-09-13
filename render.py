import json, os, re, subprocess, time
from pathlib import Path
from urllib.parse import urlparse
import requests
from faster_whisper import WhisperModel

CID = os.environ["KN_CONTENT_ID"]
SCRIPT = os.environ["KN_SCRIPT"]
PKG = json.loads(os.environ["KN_RENDER_PACKAGE"])
AUDIO = os.environ["KN_AUDIO_URL"]
WM = os.environ.get("KN_WATERMARK_URL", "").strip()

W = Path("work")
O = Path("output")
W.mkdir(exist_ok=True)
O.mkdir(exist_ok=True)

def log(msg):
    print(f"[KN] {msg}", flush=True)

def run(cmd, label="command"):
    log(label + ": " + " ".join(map(str, cmd)))
    p = subprocess.run(cmd, text=True, capture_output=True)
    if p.stdout:
        print(p.stdout[-5000:], flush=True)
    if p.stderr:
        print(p.stderr[-7000:], flush=True)
    if p.returncode:
        raise RuntimeError(f"{label} failed with exit {p.returncode}")
    return p.stdout

def suffix_for(url, ctype):
    ext = Path(urlparse(url).path).suffix.lower()
    allowed = {".jpg", ".jpeg", ".png", ".mp4", ".webm", ".mov", ".m4v"}
    if ext in allowed:
        return ext
    ct = (ctype or "").lower().split(";")[0].strip()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "audio/mpeg": ".mp3",
    }.get(ct, ".bin")

def download(url, stem):
    last = None
    for attempt in range(1, 7):
        try:
            log(f"download attempt {attempt}: {url}")
            r = requests.get(
                url,
                timeout=(15, 90),
                allow_redirects=True,
                headers={"User-Agent": "KnowledgeNuggetsRenderer/1.1 (+GitHub Actions)"},
            )
            r.raise_for_status()
            ct = r.headers.get("content-type", "")
            low = ct.lower()
            if "text/html" in low or "text/plain" in low:
                raise RuntimeError(f"unexpected content-type {ct} final_url={r.url}")
            if len(r.content) < 128:
                raise RuntimeError(f"download too small ({len(r.content)} bytes)")
            path = W / f"{stem}{suffix_for(r.url, ct)}"
            path.write_bytes(r.content)
            log(f"downloaded {len(r.content)} bytes, type={ct}, final={r.url}, file={path}")
            return path, ct
        except Exception as e:
            last = e
            log(f"download failed: {e}")
            if attempt < 6:
                time.sleep(min(2 ** attempt, 12))
    raise RuntimeError(f"download exhausted for {url}: {last}")

def duration(path):
    s = run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        f"ffprobe {path.name}",
    ).strip()
    return float(s)

def ts(x):
    return f"{int(x//3600)}:{int((x%3600)//60):02d}:{x%60:05.2f}"

def build_subs(audio, path):
    log("loading faster-whisper")
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segs, _ = model.transcribe(
        str(audio),
        language="en",
        word_timestamps=True,
        beam_size=3,
        initial_prompt=SCRIPT[:1000],
    )
    words = []
    for s in segs:
        for q in (s.words or []):
            word = (q.word or "").strip()
            if q.start is not None and q.end is not None and word:
                words.append((word, float(q.start), float(q.end)))
    if not words:
        raise RuntimeError("No word timestamps")

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: KN,DejaVu Sans,64,&H00FFFFFF,&H00008AFF,&H00111111,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,70,70,275,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for i, (word, st, en) in enumerate(words):
        lo = max(0, i - 2)
        hi = min(len(words), lo + 6)
        lo = max(0, hi - 6)
        out = []
        for j in range(lo, hi):
            t = words[j][0].replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
            if j == i:
                t = r"{\c&H00008AFF&}" + t + r"{\c&H00FFFFFF&}"
            out.append(t)
        lines.append(
            f"Dialogue: 0,{ts(st)},{ts(max(en, st+.12))},KN,,0,0,0,,{' '.join(out)}"
        )
    path.write_text(header + "\n".join(lines), encoding="utf-8")
    log(f"word timestamps: {len(words)}")
    return len(words)

if PKG.get("production_status") != "READY":
    raise RuntimeError("Render package not READY")

scenes = PKG.get("scenes") or []
if not scenes:
    raise RuntimeError("No scenes")

log(f"content={CID}; scenes={len(scenes)}")
audio, _ = download(AUDIO, "narration")
ad = duration(audio)
per = max(ad / len(scenes), 0.5)
log(f"audio duration={ad:.3f}s; scene duration={per:.3f}s")

cache = {}
clips = []
vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30"

for i, scene in enumerate(scenes, 1):
    url = scene.get("source_url")
    if not url:
        raise RuntimeError(f"scene {i} has no source_url")
    if url in cache:
        src, ct = cache[url]
        log(f"scene {i}: reusing cached source {src}")
    else:
        src, ct = download(url, f"source_{len(cache)+1}")
        cache[url] = (src, ct)

    clip = W / f"scene_{i:02d}.mp4"
    is_image = (ct or "").lower().startswith("image/") or src.suffix.lower() in {".jpg", ".jpeg", ".png"}
    if is_image:
        inp = ["-loop", "1", "-framerate", "30", "-i", str(src)]
    else:
        inp = ["-stream_loop", "-1", "-i", str(src)]

    run(
        ["ffmpeg", "-hide_banner", "-y", *inp,
         "-t", f"{per:.3f}", "-vf", vf, "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-r", "30", str(clip)],
        f"normalize scene {i}",
    )
    clips.append(clip)

lst = W / "concat.txt"
lst.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in clips), encoding="utf-8")
video = W / "visuals.mp4"
run(
    ["ffmpeg", "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
     "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
     "-pix_fmt", "yuv420p", "-r", "30", str(video)],
    "concat scenes",
)

ass = W / "subs.ass"
wc = build_subs(audio, ass)
safe = re.sub(r"[^A-Za-z0-9_-]+", "_", CID)[:80] or "kn"
out = O / f"{safe}.mp4"
aa = str(ass.resolve()).replace(":", r"\:")

if WM:
    wm, _ = download(WM, "watermark")
    fc = f"[0:v]ass='{aa}'[v0];[1:v]scale=95:-1[wm];[v0][wm]overlay=W-w-44:H-h-44[v]"
    cmd = ["ffmpeg", "-hide_banner", "-y", "-i", str(video), "-i", str(wm), "-i", str(audio),
           "-filter_complex", fc, "-map", "[v]", "-map", "2:a:0"]
else:
    cmd = ["ffmpeg", "-hide_banner", "-y", "-i", str(video), "-i", str(audio),
           "-vf", f"ass='{aa}'", "-map", "0:v:0", "-map", "1:a:0"]

run(
    cmd + ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-shortest", "-movflags", "+faststart", str(out)],
    "final render",
)

fd = duration(out)
probe = json.loads(run(
    ["ffprobe", "-v", "error", "-select_streams", "v:0",
     "-show_entries", "stream=width,height,codec_name", "-of", "json", str(out)],
    "final probe",
))["streams"][0]

score = 100
issues = []
if probe.get("width") != 1080 or probe.get("height") != 1920:
    score -= 35
    issues.append("wrong_dimensions")
if probe.get("codec_name") != "h264":
    score -= 10
    issues.append("codec")
if abs(fd - ad) > 1:
    score -= 20
    issues.append("duration")

q = {
    "content_id": CID,
    "status": "RENDER_READY" if score >= 90 else "RENDER_QC_FAILED",
    "duration_seconds": round(fd, 3),
    "technical_qc_score": max(score, 0),
    "content_qc_score": 100 if wc >= max(3, int(len(SCRIPT.split()) * .7)) else 80,
    "word_timestamps": wc,
    "issues": issues,
}
(O / "qc.json").write_text(json.dumps(q), encoding="utf-8")
log("QC " + json.dumps(q))
print(json.dumps(q))
