import json, os, re, subprocess, time
from pathlib import Path
from urllib.parse import urlparse, quote
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

BOT_UA = "KnowledgeNuggetsBot/1.3 (https://github.com/TimRich2025/Knowledge-Nuggets-Repository) python-requests/2.32.5"

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
    allowed = {".mp4", ".webm", ".mov", ".m4v", ".jpg", ".jpeg", ".png", ".mp3"}
    if ext in allowed:
        return ext
    ct = (ctype or "").lower().split(";")[0].strip()
    return {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "audio/mpeg": ".mp3",
    }.get(ct, ".bin")

def candidate_urls(url):
    out = [url]
    p = urlparse(url)
    if p.netloc == "upload.wikimedia.org":
        filename = Path(p.path).name
        if filename:
            out.append(
                "https://commons.wikimedia.org/wiki/Special:Redirect/file/" + quote(filename)
            )
    return out

def download(url, stem, expected=None):
    last = None
    headers = {
        "User-Agent": BOT_UA,
        "Api-User-Agent": BOT_UA,
        "Accept": "*/*",
    }
    for candidate in candidate_urls(url):
        for attempt in range(1, 4):
            try:
                log(f"download attempt {attempt}: {candidate}")
                r = requests.get(
                    candidate,
                    timeout=(15, 120),
                    allow_redirects=True,
                    headers=headers,
                )
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    wait = int(retry_after) if retry_after and retry_after.isdigit() else min(3 * attempt, 9)
                    raise RuntimeError(f"HTTP 429; retry-after={wait}s")
                r.raise_for_status()
                ct = r.headers.get("content-type", "")
                low = ct.lower()
                if "text/html" in low or "text/plain" in low:
                    raise RuntimeError(f"unexpected content-type {ct} final_url={r.url}")
                if len(r.content) < 128:
                    raise RuntimeError(f"download too small ({len(r.content)} bytes)")

                ext = suffix_for(r.url, ct)
                if expected == "video":
                    if not (low.startswith("video/") or ext in {".mp4", ".webm", ".mov", ".m4v"}):
                        raise RuntimeError(f"STATIC_MEDIA_REJECTED content-type={ct} ext={ext}")
                elif expected == "audio":
                    if not (low.startswith("audio/") or ext == ".mp3"):
                        raise RuntimeError(f"unexpected audio media content-type={ct} ext={ext}")
                elif expected == "image":
                    if not (low.startswith("image/") or ext in {".jpg", ".jpeg", ".png"}):
                        raise RuntimeError(f"unexpected watermark media content-type={ct} ext={ext}")

                path = W / f"{stem}{ext}"
                path.write_bytes(r.content)
                log(f"downloaded {len(r.content)} bytes, type={ct}, final={r.url}, file={path}")
                return path, ct
            except Exception as e:
                last = e
                log(f"download failed: {e}")
                if attempt < 3:
                    time.sleep(min(3 * attempt, 9))
        log(f"candidate exhausted: {candidate}")
    raise RuntimeError(f"download exhausted for {url}: {last}")

def duration(path):
    s = run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        f"ffprobe duration {path.name}",
    ).strip()
    return float(s)

def has_video_stream(path):
    out = run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        f"ffprobe video {path.name}",
    ).strip()
    return out == "video"

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
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: KN,DejaVu Sans,66,&H00FFFFFF,&H00008AFF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,80,80,255,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for i, (word, st, en) in enumerate(words):
        lo = max(0, i - 2)
        hi = min(len(words), lo + 5)
        lo = max(0, hi - 5)
        out = []
        for j in range(lo, hi):
            t = words[j][0].replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
            if j == i:
                t = r"{\c&H00008AFF&}" + t + r"{\c&H00FFFFFF&}"
            out.append(t)
        lines.append(
            f"Dialogue: 0,{ts(st)},{ts(max(en, st + .12))},KN,,0,0,0,,{' '.join(out)}"
        )
    path.write_text(header + "\n".join(lines), encoding="utf-8")
    log(f"word timestamps: {len(words)}")
    return len(words)

def scene_durations(scenes, total):
    weights = []
    for scene in scenes:
        phrase = str(scene.get("spoken_phrase") or "").strip()
        weights.append(max(1, len(phrase.split())))
    sw = sum(weights)
    raw = [total * w / sw for w in weights]
    # Keep every visual long enough to register, then renormalize.
    raw = [max(1.2, x) for x in raw]
    scale = total / sum(raw)
    return [x * scale for x in raw]

if PKG.get("production_status") != "READY":
    raise RuntimeError("Render package not READY")

scenes = PKG.get("scenes") or []
if not scenes:
    raise RuntimeError("No scenes")
if not WM:
    raise RuntimeError("WATERMARK_REQUIRED")

urls = [str(s.get("source_url") or "") for s in scenes]
if any(not u for u in urls):
    raise RuntimeError("One or more scenes have no source_url")
if len(scenes) >= 4:
    unique_ratio = len(set(urls)) / len(urls)
    if unique_ratio < 0.60:
        raise RuntimeError(f"INSUFFICIENT_VISUAL_VARIETY unique_ratio={unique_ratio:.2f}")
    if max(urls.count(u) for u in set(urls)) > 2:
        raise RuntimeError(F"SOURCE_REUSED_MORE_THAN_TWICE")

log(f"content={CID}; scenes={len(scenes)}; unique_sources={len(set(urls))}")
audio, _ = download(AUDIO, "narration", expected="audio")
ad = duration(audio)
durations = scene_durations(scenes, ad)
log("scene durations=" + ",".join(f"{x:.3f}" for x in durations))

cache = {}
source_use_count = {}
clips = []
vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30"

for i, (scene, scene_len) in enumerate(zip(scenes, durations), 1):
    url = scene["source_url"]

    if url in cache:
        src, ct, src_dur = cache[url]
        log(f"scene {i}: reusing cached motion source {src}")
    else:
        src, ct = download(url, f"source_{len(cache)+1}", expected="video")
        if not has_video_stream(src):
            raise RuntimeError(f"STATIC_OR_INVALID_SCENE_SOURCE scene={i}")
        src_dur = duration(src)
        cache[url] = (src, ct, src_dur)

    use_index = source_use_count.get(url, 0)
    source_use_count[url] = use_index + 1

    offset = 0.0
    if use_index > 0 and src_dur > scene_len + 1:
        offset = min(max(0.0, src_dur * 0.45), max(0.0, src_dur - scene_len - 0.25))

    clip = W / f"scene_{i:02d}.mp4"
    run(
        [
            "ffmpeg", "-hide_banner", "-y",
            "-stream_loop", "-1",
            "-ss", f"{offset:.3f}",
            "-i", str(src),
            "-t", f"{scene_len:.3f}",
            "-vf", vf,
            "-an",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-r", "30",
            str(clip),
        ],
        f"normalize motion scene {i}",
    )
    clips.append(clip)

lst = W / "concat.txt"
lst.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in clips), encoding="utf-8")
video = W / "visuals.mp4"
run(
    [
        "ffmpeg", "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-r", "30", str(video),
    ],
    "concat motion scenes",
)

ass = W / "subs.ass"
wc = build_subs(audio, ass)

wm, _ = download(WM, "watermark", expected="image")
safe = re.sub(r"[^A-Za-z0-9_-]+", "_", CID)[:80] or "kn"
out = O / f"{safe}.mp4"
aa = str(ass.resolve()).replace(":", r"\:")

fc = (
    f"[0:v]ass='{aa}'[v0];"
    f"[1:v]scale=84:-1,format=rgba,colorchannelmixer=aa=0.68[wm];"
    f"[v0][wm]overlay=(W-w)/2:H-h-38[v]"
)
cmd = [
    "ffmpeg", "-hide_banner", "-y",
    "-i", str(video),
    "-loop", "1", "-i", str(wm),
    "-i", str(audio),
    "-filter_complex", fc,
    "-map", "[v]", "-map", "2:a:0",
]

run(
    cmd + [
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(out),
    ],
    "final Knowledge Nuggets layout render",
)

fd = duration(out)
probe = json.loads(run(
    [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name",
        "-of", "json", str(out),
    ],
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
if len(cache) < max(1, int(len(scenes) * 0.60)):
    score -= 25
    issues.append("insufficient_motion_variety")

q = {
    "content_id": CID,
    "status": "RENDER_READY" if score >= 90 else "RENDER_QC_FAILED",
    "duration_seconds": round(fd, 3),
    "technical_qc_score": max(score, 0),
    "content_qc_score": 100 if wc >= max(3, int(len(SCRIPT.split()) * .7)) else 80,
    "word_timestamps": wc,
    "motion_scenes": len(scenes),
    "unique_motion_sources": len(cache),
    "watermark": "REQUIRED_AND_APPLIED",
    "subtitle_layout": "KN_FIXED_V1",
    "issues": issues,
}
(O / "qc.json").write_text(json.dumps(q), encoding="utf-8")
log("QC " + json.dumps(q))
print(json.dumps(q))
