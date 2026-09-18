import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from PIL import Image, ImageChops, ImageStat
from layout_lock import build_header, VIDEO_H, VIDEO_Y, CANVAS_W, CANVAS_H, HEADER_H

OUT = Path("output")
OUT.mkdir(exist_ok=True)
CONTENT_ID = os.environ.get("KN_CONTENT_ID", "kn-render")
SCRIPT = os.environ.get("KN_SCRIPT", "").strip()
RENDER_PACKAGE_RAW = os.environ.get("KN_RENDER_PACKAGE", "{}")
AUDIO_URL = os.environ.get("KN_AUDIO_URL", "")
WATERMARK_URL = os.environ.get("KN_WATERMARK_URL", "")
SAFE_ID = re.sub(r"[^A-Za-z0-9_-]+", "_", CONTENT_ID)
VIDEO_OUT = OUT / f"{SAFE_ID}.mp4"
AUDIO_PATH = OUT / "narration.mp3"
HEADER_PATH = OUT / "kn_locked_header.png"
ASS_PATH = OUT / "subtitles.ass"
QC_PATH = OUT / "qc.json"

SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"KnowledgeNuggetsRenderer/7.0"})
SESSION.mount("https://",HTTPAdapter(max_retries=Retry(total=4,connect=4,read=4,status=4,backoff_factor=1.2,status_forcelist=[429,500,502,503,504],allowed_methods=frozenset(["GET"]))))
SESSION.mount("http://",HTTPAdapter(max_retries=Retry(total=4,connect=4,read=4,status=4,backoff_factor=1.2,status_forcelist=[429,500,502,503,504],allowed_methods=frozenset(["GET"]))))

def run(cmd, timeout=480):
    print("RUN:", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True, timeout=timeout)

def ffprobe_duration(path):
    p=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],capture_output=True,text=True,check=True,timeout=60)
    return float(p.stdout.strip())

def download(url,dest,timeout=(20,240)):
    if not url: raise RuntimeError(f"Missing URL for {dest}")
    with SESSION.get(url,headers={"User-Agent":"KnowledgeNuggetsRenderer/1.0"},stream=True,timeout=timeout,allow_redirects=True) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk: f.write(chunk)
    if not dest.exists() or dest.stat().st_size<1024: raise RuntimeError(f"Downloaded file is unexpectedly small: {dest}")

def nasa_asset_id(url):
    parts=[p for p in urlparse(url).path.split("/") if p]
    for marker in ("video","image","audio"):
        if marker in parts:
            idx=parts.index(marker)
            if idx+1<len(parts): return parts[idx+1]
    base=Path(urlparse(url).path).name
    return base.split("~",1)[0].split("_",1)[0]

def resolve_nasa_candidates(url):
    url=str(url).replace("http://images-assets.nasa.gov","https://images-assets.nasa.gov")
    if "images-assets.nasa.gov" not in url:
        return [url]
    asset_id=nasa_asset_id(url)
    headers={"User-Agent":"KnowledgeNuggetsRenderer/1.0"}
    api=f"https://images-api.nasa.gov/asset/{asset_id}"
    r=SESSION.get(api,headers=headers,timeout=(15,30))
    if r.status_code==404:
        q=asset_id.split("_",1)[0] if asset_id.startswith("jsc") else asset_id
        sr=SESSION.get("https://images-api.nasa.gov/search",params={"q":q,"media_type":"video"},headers=headers,timeout=(15,30))
        sr.raise_for_status()
        hits=sr.json().get("collection",{}).get("items",[])
        nasa_ids=[]
        for hit in hits:
            data=hit.get("data") or []
            if data and data[0].get("nasa_id"):
                nasa_ids.append(str(data[0]["nasa_id"]))
        exact=[x for x in nasa_ids if x.lower().startswith(q.lower())]
        if exact:
            asset_id=exact[0]
        elif nasa_ids:
            asset_id=nasa_ids[0]
        else:
            raise RuntimeError(f"NASA asset search returned no result for {q}")
        r=SESSION.get(f"https://images-api.nasa.gov/asset/{asset_id}",headers=headers,timeout=(15,30))
    r.raise_for_status()
    items=r.json().get("collection",{}).get("items",[])
    hrefs=[str(x.get("href","")).replace("http://","https://") for x in items if x.get("href")]
    videos=[h for h in hrefs if re.search(r"\.(mp4|mov|m4v)$",h,re.I)]
    large=[h for h in videos if re.search(r"~large\.(mp4|mov|m4v)$",h,re.I)]
    medium=[h for h in videos if re.search(r"~medium\.(mp4|mov|m4v)$",h,re.I)]
    small=[h for h in videos if re.search(r"~small\.(mp4|mov|m4v)$",h,re.I)]
    original=[h for h in videos if "~orig." in h.lower()]
    candidates=[]
    for group in (large,medium,small,original):
        for h in group:
            if h not in candidates:
                candidates.append(h)
    if not candidates:
        raise RuntimeError(f"No practical NASA rendition found for {asset_id}")
    print(f"NASA candidates {asset_id}: {candidates}")
    return candidates

def ass_escape(s): return s.replace("\\",r"\\").replace("{",r"\{").replace("}",r"\}")
def ass_time(sec):
    sec=max(0.0,float(sec)); h=int(sec//3600); m=int((sec%3600)//60); s=sec%60
    return f"{h}:{m:02d}:{s:05.2f}"
def tokenize(text): return re.findall(r"\S+",text)
def weight(word):
    base=max(1.0,len(re.sub(r"[^A-Za-z0-9]","",word))**0.38)
    if re.search(r"[.!?]$",word): base+=0.35
    elif re.search(r"[,;:]$",word): base+=0.18
    return base
def build_word_times(words,total):
    weights=[weight(w) for w in words]; usable=max(0.5,total-0.10); unit=usable/max(sum(weights),1.0); out=[]; t=0.03
    for i,(w,wt) in enumerate(zip(words,weights)):
        start=t; end=min(total-0.02,start+wt*unit)
        if i==len(words)-1: end=max(end,total-0.02)
        out.append((w,start,max(start+0.04,end))); t=end
    return out
def build_ass(words_timed):
    header="""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Main,DejaVu Sans,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,1,5,90,90,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    # Deterministic short phrase cards: white only, black outline, centered in video region.
    chunks=[]; cur=[]
    for i,(word,start,end) in enumerate(words_timed):
        candidate=cur+[(word,start,end)]
        text=" ".join(x[0] for x in candidate)
        if cur and (len(candidate)>3 or len(text)>22):
            chunks.append(cur); cur=[(word,start,end)]
        else:
            cur=candidate
    if cur: chunks.append(cur)
    cy=VIDEO_Y + VIDEO_H//2
    events=[]
    for chunk in chunks:
        start=chunk[0][1]; end=chunk[-1][2]
        text=ass_escape(" ".join(x[0] for x in chunk).upper())
        events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Main,,0,0,0,,{{\\an5\\pos(540,{cy})}}{text}")
    ASS_PATH.write_text(header+"\n".join(events)+"\n",encoding="utf-8")

def crop_x(pref):
    pref=str(pref or "CENTER").upper()
    if pref=="LEFT": return "0"
    if pref=="RIGHT": return "iw-1080"
    return "(iw-1080)/2"

pkg=json.loads(RENDER_PACKAGE_RAW); scenes=pkg.get("scenes") or []
if pkg.get("production_status")!="READY": raise RuntimeError("Production package is not READY")
if not scenes: raise RuntimeError("Render package has no scenes")
if any(float(s.get("semantic_score",0))<88 for s in scenes): raise RuntimeError("Semantic scene gate failed")
question_lines=pkg.get("core_question_lines")
if not isinstance(question_lines,list) or len(question_lines)!=2:
    raise RuntimeError("Locked layout requires exactly two core_question_lines")
build_header(question_lines,HEADER_PATH)
download(AUDIO_URL,AUDIO_PATH); audio_duration=ffprobe_duration(AUDIO_PATH)
if not (15.0<=audio_duration<=30.5): raise RuntimeError(f"Narration outside 15-30s target: {audio_duration}")
words=tokenize(SCRIPT); build_ass(build_word_times(words,audio_duration))
scene_weights=[max(1,len(tokenize(s.get("spoken_phrase","")))) for s in scenes]; weight_sum=sum(scene_weights); durations=[audio_duration*w/weight_sum for w in scene_weights]
if durations: durations[-1]+=audio_duration-sum(durations)
candidate_sets=[resolve_nasa_candidates(s["source_url"]) for s in scenes]
resolved=[]
vertical_clips=[]

def scene_filter(scene):
    layout=str(scene.get("layout_mode","FIT_BLUR")).upper()
    if layout=="CROP_FILL":
        x=crop_x(scene.get("crop_preference"))
        return f"scale=1080:{VIDEO_H}:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:{VIDEO_H}:{x}:(ih-{VIDEO_H})/2,setsar=1,fps=30"
    return (
        f"split=2[bg][fg];"
        f"[bg]scale=270:{max(1,VIDEO_H//4)}:force_original_aspect_ratio=increase,"
        f"crop=270:{max(1,VIDEO_H//4)},gblur=sigma=8,scale=1080:{VIDEO_H}:flags=bilinear,"
        f"eq=brightness=-0.05:saturation=0.82,setsar=1,fps=30[bg2];"
        f"[fg]scale=1080:{VIDEO_H}:force_original_aspect_ratio=decrease:flags=lanczos,setsar=1,fps=30[fg2];"
        f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2:shortest=1"
    )

for i,(scene,dur,candidates) in enumerate(zip(scenes,durations,candidate_sets)):
    last_error=None
    clip=OUT/f"vertical_{i}.mp4"
    for attempt,url in enumerate(candidates[:3], start=1):
        suffix=Path(urlparse(url).path).suffix.lower()
        suffix=suffix if suffix in (".mp4",".mov",".m4v") else ".mp4"
        source=OUT/f"source_{i}_{attempt}{suffix}"
        try:
            print(f"Scene {i+1}: trying candidate {attempt}/{min(3,len(candidates))}: {url}", flush=True)
            download(url,source,timeout=(20,180))
            vf=scene_filter(scene)
            source_duration=ffprobe_duration(source)
            requested_start=scene.get("source_start")
            if requested_start is not None:
                seek=max(0.0,min(max(0.0,source_duration-dur-.25),float(requested_start)))
            else:
                seek=max(0.0,min(max(0.0,source_duration-dur-.25),source_duration*.35-dur/2))
            if ";" in vf:
                filter_complex=f"[0:v]{vf}[vout]"
                scene_cmd=[
                    "ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-ss",f"{seek:.3f}","-i",str(source),"-t",f"{dur:.3f}","-an",
                    "-filter_complex",filter_complex,"-map","[vout]",
                    "-c:v","libx264","-preset","ultrafast","-crf","10",
                    "-pix_fmt","yuv420p","-movflags","+faststart",str(clip)
                ]
            else:
                scene_cmd=[
                    "ffmpeg","-hide_banner","-loglevel","error","-y",
                    "-ss",f"{seek:.3f}","-i",str(source),"-t",f"{dur:.3f}","-an",
                    "-vf",vf,
                    "-c:v","libx264","-preset","ultrafast","-crf","10",
                    "-pix_fmt","yuv420p","-movflags","+faststart",str(clip)
                ]
            run(scene_cmd,timeout=90)
            if not clip.exists() or clip.stat().st_size < 200000:
                raise RuntimeError("Vertical clip output missing or too small")
            resolved.append(url)
            vertical_clips.append(clip)
            print(f"Scene {i+1}: prepared successfully from {url}", flush=True)
            break
        except Exception as exc:
            last_error=exc
            print(f"Scene {i+1}: candidate failed: {type(exc).__name__}: {exc}", flush=True)
            if clip.exists():
                clip.unlink()
        finally:
            if source.exists():
                source.unlink()
    else:
        raise RuntimeError(f"Scene {i+1} could not be prepared from any candidate: {last_error}")

concat_path=OUT/"concat.txt"
joined_path=OUT/"joined.mp4"
concat_path.write_text("\n".join("file " + repr(str(p.resolve())) for p in vertical_clips) + "\n",encoding="utf-8")
run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","concat","-safe","0","-i",str(concat_path),"-c","copy","-movflags","+faststart",str(joined_path)],timeout=60)
final_filter=(
    f"[0:v]pad={CANVAS_W}:{CANVAS_H}:0:{VIDEO_Y}:color=black[base];"
    f"[base][1:v]overlay=0:0:eof_action=repeat:repeatlast=1[locked];"
    f"[locked]ass={ASS_PATH.as_posix()}[finalv]"
)
run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i",str(joined_path),"-loop","1","-i",str(HEADER_PATH),"-i",str(AUDIO_PATH),"-filter_complex",final_filter,"-map","[finalv]","-map","2:a:0","-t",f"{audio_duration:.3f}","-c:v","libx264","-preset","superfast","-crf","16","-pix_fmt","yuv420p","-profile:v","high","-level","4.2","-c:a","aac","-b:a","192k","-movflags","+faststart",str(VIDEO_OUT)],timeout=180)

render_duration=ffprobe_duration(VIDEO_OUT); issues=[]
if abs(render_duration-audio_duration)>0.35: issues.append("duration_mismatch")
if VIDEO_OUT.stat().st_size<500000: issues.append("render_file_too_small")

# Real layout-lock check against the rendered frame, not a metadata flag.
qc_frame=OUT/"layout_qc_frame.png"
run(["ffmpeg","-hide_banner","-loglevel","error","-y","-ss","0.30","-i",str(VIDEO_OUT),"-frames:v","1",str(qc_frame)],timeout=60)
actual=Image.open(qc_frame).convert("RGB")
expected=Image.open(HEADER_PATH).convert("RGB")
if actual.size!=(CANVAS_W,CANVAS_H):
    issues.append("wrong_canvas_size"); header_mae=999.0
else:
    diff=ImageChops.difference(actual.crop((0,0,CANVAS_W,HEADER_H)),expected)
    header_mae=sum(ImageStat.Stat(diff).mean)/3
    if header_mae>12.0: issues.append("layout_lock_changed")

technical=100 if not issues else 85
qc={
    "content_id":CONTENT_ID,
    "status":"RENDER_READY" if not issues else "RENDER_QC_WARNING",
    "duration_seconds":round(render_duration,3),
    "technical_qc_score":technical,
    "content_qc_score":round(sum(float(s.get("semantic_score",0)) for s in scenes)/len(scenes),1),
    "motion_scenes":len(scenes),
    "unique_motion_sources":len(set(resolved)),
    "layout_lock":"KN_LAYOUT_V1",
    "layout_header_mae":round(header_mae,3),
    "subtitle_layout":"CENTERED_WHITE_BLACK_OUTLINE_NO_BOX",
    "watermark":"NONE_HEADER_LOGO_ONLY",
    "issues":issues,
    "render_strategy":"MAKE_ORCHESTRATES_GITHUB_RENDERS_LOCKED_LAYOUT",
    "resolved_sources":resolved
}
QC_PATH.write_text(json.dumps(qc,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(qc,ensure_ascii=False))
