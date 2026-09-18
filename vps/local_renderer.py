from __future__ import annotations
import json, subprocess
from pathlib import Path
from PIL import Image, ImageChops, ImageStat
from layout_lock import build_header, VIDEO_H, VIDEO_Y, CANVAS_W, CANVAS_H, HEADER_H

class RenderError(RuntimeError): pass

ENCODE_H = VIDEO_H + (VIDEO_H % 2)  # H.264 yuv420p requires even dimensions.

def run(cmd, timeout=240):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        detail = (p.stderr or p.stdout or "<no ffmpeg output>")[-1800:]
        raise RenderError(f"command failed rc={p.returncode}: {detail}")
    return p

def probe_duration(path: Path) -> float:
    p = run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)], 45)
    return float(p.stdout.strip())

def ass_time(sec: float) -> str:
    h=int(sec//3600); sec-=h*3600; m=int(sec//60); sec-=m*60
    return f"{h}:{m:02d}:{sec:05.2f}"

def ass_escape(s: str) -> str:
    return s.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")

def build_ass(scenes: list[dict], durations: list[float], out: Path):
    header="""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Main,Noto Sans,68,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,5,1,5,90,90,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events=[]; t=0.0; cy=VIDEO_Y+VIDEO_H//2
    for scene,dur in zip(scenes,durations):
        beats=[str(x).strip().upper() for x in (scene.get("caption_beats") or []) if str(x).strip()]
        if not beats:
            beats=[str(scene.get("spoken_phrase") or "").strip().upper()]
        step=dur/max(1,len(beats))
        for i,txt in enumerate(beats):
            a=t+i*step; b=t+(i+1)*step
            events.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Main,,0,0,0,,{{\\an5\\pos(540,{cy})}}{ass_escape(txt)}")
        t+=dur
    out.write_text(header+"\n".join(events)+"\n",encoding="utf-8")

def scene_filter(scene: dict) -> str:
    layout=str(scene.get("layout_mode") or "CROP_FILL").upper()
    if layout == "CROP_FILL":
        return f"scale={CANVAS_W}:{ENCODE_H}:force_original_aspect_ratio=increase:flags=lanczos,crop={CANVAS_W}:{ENCODE_H}:(iw-{CANVAS_W})/2:(ih-{ENCODE_H})/2,setsar=1,fps=30"
    if layout == "FIT_BLUR":
        bh=max(2,(ENCODE_H//4)//2*2)
        return (f"split=2[bg][fg];[bg]scale=270:{bh}:force_original_aspect_ratio=increase,crop=270:{bh},"
                f"gblur=sigma=8,scale={CANVAS_W}:{ENCODE_H},eq=brightness=-0.05:saturation=0.82,setsar=1,fps=30[bg2];"
                f"[fg]scale={CANVAS_W}:{ENCODE_H}:force_original_aspect_ratio=decrease:flags=lanczos,setsar=1,fps=30[fg2];"
                f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2:shortest=1")
    raise RenderError(f"unsupported layout_mode: {layout}")

def render_job(job: dict, ingested: dict, job_dir: Path) -> dict:
    if job.get("production_status") != "READY": raise RenderError("production_status must be READY")
    q=job.get("core_question_lines")
    if not isinstance(q,list) or len(q)!=2: raise RenderError("core_question_lines must contain exactly two lines")
    scenes=ingested["scenes"]
    audio=Path(ingested["audio"]["path"])
    audio_dur=probe_duration(audio)
    if not 15 <= audio_dur <= 30.5: raise RenderError(f"narration outside 15-30s target: {audio_dur:.2f}s")
    requested=[max(.8,float(s.get("duration") or 3.0)) for s in scenes]
    scale=audio_dur/sum(requested); durations=[d*scale for d in requested]

    header=job_dir/"header.png"; build_header(q,header)
    ass=job_dir/"captions.ass"; build_ass(scenes,durations,ass)
    segments=[]
    for idx,(s,dur) in enumerate(zip(scenes,durations),1):
        src=Path(s["local_path"])
        src_dur=probe_duration(src)
        primary=s.get("source_url") or s.get("direct_download_url")
        if primary and s.get("ingested_from") == primary:
            anchor=float(s.get("validated_frame_time") or src_dur*.35)
            offset=float(s.get("source_start_offset") or 0)
        elif not s.get("ingested_from"):
            anchor=float(s.get("validated_frame_time") or src_dur*.35)
            offset=float(s.get("source_start_offset") or 0)
        else:
            anchor=src_dur*.35
            offset=0.0
        start=max(0.0,min(max(0.0,src_dur-dur-.25),anchor-dur/2+offset))
        seg=job_dir/f"seg_{idx:02d}.mp4"; vf=scene_filter(s)
        if ";" in vf:
            fc=f"[0:v]{vf}[v]"
            cmd=["ffmpeg","-hide_banner","-loglevel","error","-y","-ss",f"{start:.3f}","-i",str(src),"-t",f"{dur:.3f}","-an","-filter_complex_threads","1","-filter_complex",fc,"-map","[v]","-c:v","libx264","-threads","2","-preset","veryfast","-crf","17","-pix_fmt","yuv420p",str(seg)]
        else:
            cmd=["ffmpeg","-hide_banner","-loglevel","error","-y","-ss",f"{start:.3f}","-i",str(src),"-t",f"{dur:.3f}","-an","-filter_threads","1","-vf",vf,"-c:v","libx264","-threads","2","-preset","veryfast","-crf","17","-pix_fmt","yuv420p",str(seg)]
        run(cmd, 300); segments.append(seg)

    concat=job_dir/"concat.txt"
    concat.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in segments)+"\n",encoding="utf-8")
    lower=job_dir/"lower.mp4"
    run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy",str(lower)],120)
    out=job_dir/"preview.mp4"
    fc=(f"[0:v]crop={CANVAS_W}:{VIDEO_H}:0:0[lower];[lower]pad={CANVAS_W}:{CANVAS_H}:0:{VIDEO_Y}:color=black[base];"
        f"[base][1:v]overlay=0:0:eof_action=repeat:repeatlast=1[locked];[locked]ass={ass.as_posix()}[v]")
    run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i",str(lower),"-loop","1","-i",str(header),"-i",str(audio),
         "-filter_complex_threads","1","-filter_complex",fc,"-map","[v]","-map","2:a:0","-t",f"{audio_dur:.3f}","-c:v","libx264","-threads","2","-preset","veryfast","-crf","16",
         "-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-movflags","+faststart",str(out)],360)

    frame=job_dir/"qc_frame.png"
    run(["ffmpeg","-hide_banner","-loglevel","error","-y","-ss","0.3","-i",str(out),"-frames:v","1",str(frame)],60)
    actual=Image.open(frame).convert("RGB"); expected=Image.open(header).convert("RGB")
    if actual.size!=(CANVAS_W,CANVAS_H): raise RenderError(f"wrong output size: {actual.size}")
    diff=ImageChops.difference(actual.crop((0,0,CANVAS_W,HEADER_H)),expected)
    mae=sum(ImageStat.Stat(diff).mean)/3
    if mae>12: raise RenderError(f"layout lock drift: MAE {mae:.3f}")
    return {"status":"RENDER_READY","preview_path":str(out),"duration_seconds":round(probe_duration(out),3),"layout_header_mae":round(mae,3),"layout_lock":"KN_LAYOUT_V1"}
