import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests

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
WM_PATH = OUT / "watermark.png"
ASS_PATH = OUT / "subtitles.ass"
QC_PATH = OUT / "qc.json"

def run(cmd, timeout=480):
    print("RUN:", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True, timeout=timeout)

def ffprobe_duration(path):
    p = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],capture_output=True,text=True,check=True,timeout=60)
    return float(p.stdout.strip())

def download(url, dest, timeout=(20,240)):
    if not url: raise RuntimeError(f"Missing URL for {dest}")
    with requests.get(url,headers={"User-Agent":"KnowledgeNuggetsRenderer/1.0"},stream=True,timeout=timeout,allow_redirects=True) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024*1024):
                if chunk: f.write(chunk)
    if not dest.exists() or dest.stat().st_size < 1024: raise RuntimeError(f"Downloaded file is unexpectedly small: {dest}")

def nasa_asset_id(url):
    parts=[p for p in urlparse(url).path.split("/") if p]
    for marker in ("video","image","audio"):
        if marker in parts:
            idx=parts.index(marker)
            if idx+1 < len(parts): return parts[idx+1]
    base=Path(urlparse(url).path).name
    return base.split("~",1)[0].split("_",1)[0]

def resolve_nasa_large(url):
    url=str(url).replace("http://images-assets.nasa.gov","https://images-assets.nasa.gov")
    if "images-assets.nasa.gov" not in url: return url
    asset_id=nasa_asset_id(url)
    r=requests.get(f"https://images-api.nasa.gov/asset/{asset_id}",headers={"User-Agent":"KnowledgeNuggetsRenderer/1.0"},timeout=(15,30)); r.raise_for_status()
    items=r.json().get("collection",{}).get("items",[])
    hrefs=[str(x.get("href","")).replace("http://","https://") for x in items if x.get("href")]
    videos=[h for h in hrefs if re.search(r"\.(mp4|mov|m4v)$",h,re.I)]
    preferred=[h for h in videos if re.search(r"~large\.(mp4|mov|m4v)$",h,re.I)]
    if not preferred: preferred=[h for h in videos if "large" in h.lower() and "orig" not in h.lower()]
    if not preferred: preferred=[h for h in videos if re.search(r"~medium\.(mp4|mov|m4v)$",h,re.I)]
    if not preferred: raise RuntimeError(f"No practical NASA rendition found for {asset_id}")
    print(f"NASA rendition {asset_id}: {preferred[0]}"); return preferred[0]

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
def build_word_times(words,total_duration):
    weights=[weight(w) for w in words]; usable=max(0.5,total_duration-0.10); unit=usable/max(sum(weights),1.0); out=[]; t=0.03
    for i,(w,wt) in enumerate(zip(words,weights)):
        start=t; end=min(total_duration-0.02,start+wt*unit)
        if i==len(words)-1: end=max(end,total_duration-0.02)
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
Style: Main,DejaVu Sans,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,110,110,390,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events=[]; n=len(words_timed)
    for i,(_,start,end) in enumerate(words_timed):
        gs=(i//4)*4; ge=min(gs+4,n); parts=[]
        for j in range(gs,ge):
            txt=ass_escape(words_timed[j][0]); parts.append((r"{\c&H00008AFF&}"+txt+r"{\c&H00FFFFFF&}") if j==i else txt)
        events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Main,,0,0,0,,{' '.join(parts)}")
    ASS_PATH.write_text(header+"\n".join(events)+"\n",encoding="utf-8")
def crop_x(pref):
    pref=str(pref or "CENTER").upper()
    if pref=="LEFT": return "0"
    if pref=="RIGHT": return "iw-1080"
    return "(iw-1080)/2"

pkg=json.loads(RENDER_PACKAGE_RAW); scenes=pkg.get("scenes") or []
if not scenes: raise RuntimeError("Render package has no scenes")
if any(float(s.get("semantic_score",0))<90 for s in scenes): raise RuntimeError("Semantic scene gate failed")
download(AUDIO_URL,AUDIO_PATH); audio_duration=ffprobe_duration(AUDIO_PATH)
if not (5.0<=audio_duration<=60.0): raise RuntimeError(f"Unexpected narration duration: {audio_duration}")
download(WATERMARK_URL,WM_PATH)
words=tokenize(SCRIPT); word_times=build_word_times(words,audio_duration); build_ass(word_times)
scene_weights=[max(1,len(tokenize(s.get("spoken_phrase","")))) for s in scenes]; weight_sum=sum(scene_weights)
durations=[audio_duration*w/weight_sum for w in scene_weights]
if durations: durations[-1]+=audio_duration-sum(durations)
resolved=[resolve_nasa_large(s["source_url"]) for s in scenes]
local_sources=[]
for i,url in enumerate(resolved):
    suffix=Path(urlparse(url).path).suffix.lower(); suffix=suffix if suffix in (".mp4",".mov",".m4v") else ".mp4"
    dest=OUT/f"source_{i}{suffix}"; print(f"Downloading source {i+1}/{len(resolved)}"); download(url,dest,timeout=(20,300)); local_sources.append(dest)
cmd=["ffmpeg","-hide_banner","-loglevel","warning","-y"]
for path,dur in zip(local_sources,durations): cmd += ["-ss","8","-t",f"{dur+0.35:.3f}","-i",str(path)]
wm_idx=len(scenes); audio_idx=wm_idx+1; cmd += ["-loop","1","-i",str(WM_PATH),"-i",str(AUDIO_PATH)]
filters=[]; labels=[]
for i,(scene,dur) in enumerate(zip(scenes,durations)):
    layout=str(scene.get("layout_mode","FIT_BLUR")).upper()
    if layout=="CROP_FILL":
        x=crop_x(scene.get("crop_preference")); filters.append(f"[{i}:v]scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920:{x}:(ih-1920)/2,setsar=1,fps=30,trim=duration={dur:.3f},setpts=PTS-STARTPTS[v{i}]")
    else:
        filters.append(f"[{i}:v]split=2[s{i}bg][s{i}fg];[s{i}bg]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,gblur=sigma=8,scale=1080:1920:flags=bilinear,eq=brightness=-0.05:saturation=0.82,setsar=1,fps=30,trim=duration={dur:.3f},setpts=PTS-STARTPTS[s{i}b];[s{i}fg]scale=1080:1920:force_original_aspect_ratio=decrease:flags=lanczos,setsar=1,fps=30,trim=duration={dur:.3f},setpts=PTS-STARTPTS[s{i}f];[s{i}b][s{i}f]overlay=(W-w)/2:(H-h)/2:shortest=1[v{i}]")
    labels.append(f"[v{i}]")
filters.append("".join(labels)+f"concat=n={len(scenes)}:v=1:a=0[base]"); filters.append(f"[{wm_idx}:v]scale=48:-1[wm]"); filters.append("[base][wm]overlay=W-w-52:H-h-78:shortest=1[branded]"); filters.append(f"[branded]ass={ASS_PATH.as_posix()}[finalv]")
cmd += ["-filter_complex",";".join(filters),"-map","[finalv]","-map",f"{audio_idx}:a:0","-t",f"{audio_duration:.3f}","-c:v","libx264","-preset","veryfast","-crf","18","-pix_fmt","yuv420p","-profile:v","high","-level","4.2","-c:a","aac","-b:a","192k","-movflags","+faststart",str(VIDEO_OUT)]
run(cmd,timeout=420)
render_duration=ffprobe_duration(VIDEO_OUT); issues=[]
if abs(render_duration-audio_duration)>0.35: issues.append("duration_mismatch")
if VIDEO_OUT.stat().st_size<500000: issues.append("render_file_too_small")
qc={"content_id":CONTENT_ID,"status":"RENDER_READY" if not issues else "RENDER_QC_WARNING","duration_seconds":round(render_duration,3),"technical_qc_score":100 if not issues else 85,"content_qc_score":round(sum(float(s.get("semantic_score",0)) for s in scenes)/len(scenes),1),"motion_scenes":len(scenes),"unique_motion_sources":len(set(resolved)),"watermark":"BRAIN_NUGGET_TRANSPARENT_BOTTOM_RIGHT_4PCT","subtitle_layout":"KN_SAFE_V2_4WORD_ACTIVE_ORANGE","issues":issues,"render_strategy":"LOCAL_SOURCE_DOWNLOAD_LAYOUT_AWARE_ONE_PASS","resolved_sources":resolved}
QC_PATH.write_text(json.dumps(qc,ensure_ascii=False,indent=2),encoding="utf-8"); print(json.dumps(qc,ensure_ascii=False))
