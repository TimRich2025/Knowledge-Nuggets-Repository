from __future__ import annotations
import json, re, subprocess
from pathlib import Path
from PIL import Image, ImageChops, ImageStat
from layout_lock import build_header, VIDEO_H, VIDEO_Y, CANVAS_W, CANVAS_H, HEADER_H
from .production_contract import validate_measured_render_contract, validate_submission_contract

class RenderError(RuntimeError): pass

ENCODE_H = VIDEO_H + (VIDEO_H % 2)  # H.264 yuv420p requires even dimensions.
DEFAULT_VISUAL_SPEED = 1.15

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

def _spoken_tokens(text: str) -> list[tuple[str, float]]:
    """Return ordered words with a small punctuation-aware speech weight.

    Caption cards used to receive equal screen time.  That visibly drifted when
    one card contained short words and the next contained longer words or a
    sentence pause.  These weights keep caption boundaries tied to the words
    Google TTS is actually pronouncing without inventing timestamps.
    """
    tokens=[]
    for match in re.finditer(r"[A-Za-z0-9']+|[,;:.!?]", text):
        token=match.group(0)
        if token in ",;:":
            if tokens: tokens[-1]=(tokens[-1][0],tokens[-1][1]+0.32)
            continue
        if token in ".!?":
            if tokens: tokens[-1]=(tokens[-1][0],tokens[-1][1]+0.44)
            continue
        vowel_groups=len(re.findall(r"[aeiouy]+",token.lower()))
        weight=max(1.0,0.72+0.62*vowel_groups+0.035*len(token))
        tokens.append((token.lower(),weight))
    return tokens

def caption_intervals(scene: dict, duration: float) -> list[tuple[str, float, float]]:
    beats=[str(x).strip().upper() for x in (scene.get("caption_beats") or []) if str(x).strip()]
    if not beats:
        beats=[str(scene.get("spoken_phrase") or "").strip().upper()]
    spoken=_spoken_tokens(str(scene.get("spoken_phrase") or ""))
    cursor=0
    weights=[]
    for beat in beats:
        beat_words=[word for word,_ in _spoken_tokens(beat)]
        weight=0.0
        for word in beat_words:
            while cursor < len(spoken) and spoken[cursor][0] != word:
                cursor += 1
            if cursor < len(spoken):
                weight += spoken[cursor][1]
                cursor += 1
            else:
                weight += max(1.0,len(word)/4.5)
        weights.append(max(0.6,weight))
    total=sum(weights) or float(len(beats))
    intervals=[]; elapsed=0.0
    for index,(beat,weight) in enumerate(zip(beats,weights)):
        start=elapsed
        elapsed=duration if index == len(beats)-1 else elapsed+duration*(weight/total)
        intervals.append((beat,start,elapsed))
    return intervals

def phrase_intervals(scene: dict, intervals: list[tuple[str, float, float]], duration: float) -> list[tuple[str, float, float, list[tuple[str, float, float]]]]:
    """Keep caption phrases and retain the spoken time of every word."""
    beats=[str(x).strip().upper() for x in (scene.get("caption_beats") or []) if str(x).strip()]
    if not beats:
        beats=[str(scene.get("spoken_phrase") or "").strip().upper()]
    if [word for beat in beats for word,_ in _spoken_tokens(beat)] != [word for word,_ in _spoken_tokens(str(scene.get("spoken_phrase") or ""))]:
        raise RenderError("caption text differs from the spoken script")
    words=[]
    for phrase,start,end in intervals:
        tokens=_spoken_tokens(phrase)
        total=sum(weight for _,weight in tokens) or 1.0
        cursor=start
        for index,(word,weight) in enumerate(tokens):
            next_time=end if index==len(tokens)-1 else cursor+(end-start)*weight/total
            words.append((word,cursor,next_time)); cursor=next_time
    grouped=[]; cursor=0
    for beat in beats:
        targets=[word for word,_ in _spoken_tokens(beat)]
        matched=words[cursor:cursor+len(targets)]
        if len(matched)!=len(targets) or [word for word,_,_ in matched]!=targets:
            raise RenderError("caption timing words differ from the spoken script")
        grouped.append((beat,matched[0][1],matched[-1][2],matched))
        cursor+=len(targets)
    if cursor!=len(words):
        raise RenderError("caption timing contains words absent from the spoken script")
    return grouped

def typewriter_text(text: str, words: list[tuple[str, float, float]], phrase_start: float) -> str:
    """Reveal each word only while that exact word is being spoken."""
    result=[]
    for index,match in enumerate(re.finditer(r"[A-Za-z0-9']+",text)):
        word=match.group()
        measured,start,end=words[index]
        if word.lower()!=measured:
            raise RenderError("typed caption does not match word timing")
        if index:
            result.append("\u00a0\u00a0")
        word_start=round(1000*(start-phrase_start))
        # Every letter uses the same step. Natural pauses between spoken words
        # remain pauses; they must not accelerate or stretch the typing itself.
        letter_ms=26
        for letter,char in enumerate(word):
            at=max(0,word_start+letter_ms*letter)
            result.append(r"{\alpha&HFF&\t("+f"{at},{at+1}"+r",\alpha&H00&)}"+ass_escape(char))
    return "".join(result)

def build_ass(scenes: list[dict], durations: list[float], out: Path):
    header="""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Main,Noto Sans,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,1,5,90,90,0,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    events=[]; t=0.0; cy=VIDEO_Y+VIDEO_H//2
    for scene,dur in zip(scenes,durations):
        measured=scene.get("caption_timings") or []
        intervals=[]
        for item in measured:
            try:
                txt=str(item["text"]).strip().upper()
                start=max(0.0,min(dur,float(item["start_seconds"])))
                end=min(dur,max(start+0.05,float(item["end_seconds"])))
                if start >= dur or end <= start:
                    raise ValueError("caption timing outside scene")
            except (KeyError,TypeError,ValueError):
                intervals=[]
                break
            if txt: intervals.append((txt,start,end))
        if not intervals:
            raise RenderError("measured word-boundary caption timings are required")
        for txt,start,end,words in phrase_intervals(scene,intervals,dur):
            a=t+start; b=t+end
            placement=rf"\an5\pos(540,{cy})"
            events.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Main,,0,0,0,,{{{placement}}}{typewriter_text(txt,words,start)}")
        t+=dur
    out.write_text(header+"\n".join(events)+"\n",encoding="utf-8")

def scene_filter(scene: dict, scene_index: int = 1, duration: float | None = None) -> str:
    layout=str(scene.get("layout_mode") or "CROP_FILL").upper()
    try:
        speed=float(scene.get("playback_speed") or DEFAULT_VISUAL_SPEED)
    except (TypeError, ValueError) as exc:
        raise RenderError("playback_speed must be numeric") from exc
    if not 1.0 <= speed <= 1.35:
        raise RenderError("playback_speed must be between 1.0 and 1.35")
    exact_tail=(f"fps=30,tpad=stop_mode=clone:stop_duration=0.5,"
                f"trim=duration={float(duration):.6f},setpts=PTS-STARTPTS,setsar=1" if duration else "fps=30,setsar=1")
    if layout == "CROP_FILL":
        return (f"setpts=(PTS-STARTPTS)/{speed:.5f},"
                f"scale={CANVAS_W}:{ENCODE_H}:force_original_aspect_ratio=increase:flags=lanczos,"
                f"crop={CANVAS_W}:{ENCODE_H}:(iw-{CANVAS_W})/2:(ih-{ENCODE_H})/2,"
                f"{exact_tail}")
    if layout == "FIT_BLUR":
        bh=max(2,(ENCODE_H//4)//2*2)
        return (f"setpts=(PTS-STARTPTS)/{speed:.5f},split=2[bg][fg];[bg]scale=270:{bh}:force_original_aspect_ratio=increase,crop=270:{bh},"
                f"gblur=sigma=8,scale={CANVAS_W}:{ENCODE_H},eq=brightness=-0.05:saturation=0.82,setsar=1,fps=30[bg2];"
                f"[fg]scale={CANVAS_W}:{ENCODE_H}:force_original_aspect_ratio=decrease:flags=lanczos,setsar=1,fps=30[fg2];"
                f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2:shortest=1,{exact_tail}")
    raise RenderError(f"unsupported layout_mode: {layout}")

def render_job(job: dict, ingested: dict, job_dir: Path) -> dict:
    if job.get("production_status") != "READY": raise RenderError("production_status must be READY")
    try:
        validate_submission_contract(job)
        validate_measured_render_contract(ingested["scenes"])
    except ValueError as exc:
        raise RenderError(str(exc)) from exc
    q=job.get("core_question_lines")
    if not isinstance(q,list) or len(q)!=2: raise RenderError("core_question_lines must contain exactly two lines")
    scenes=ingested["scenes"]
    audio=Path(ingested["audio"]["path"])
    audio_dur=probe_duration(audio)
    if not 15 <= audio_dur <= 60: raise RenderError(f"narration outside 15-60s target: {audio_dur:.2f}s")
    speech_intervals=[]
    previous_end=0.0
    for idx, scene in enumerate(scenes, 1):
        try:
            start=float(scene["speech_start_seconds"])
            end=float(scene["speech_end_seconds"])
        except Exception as exc:
            raise RenderError(f"scene {idx}: verified speech interval required") from exc
        if start < 0 or end-start < .6 or start + .05 < previous_end or (idx > 1 and abs(start-previous_end) > .10):
            raise RenderError(f"scene {idx}: invalid verified speech interval")
        if end > audio_dur + .10:
            raise RenderError(f"scene {idx}: verified speech interval exceeds narration")
        speech_intervals.append((start,end))
        previous_end=end
    if speech_intervals[0][0] > .15:
        raise RenderError("narration begins before the first verified visual beat")
    if audio_dur-speech_intervals[-1][1] > .35:
        raise RenderError("narration continues after the last verified visual beat")
    durations=[end-start for start,end in speech_intervals]

    header=job_dir/"header.png"; build_header(q,header)
    ass=job_dir/"captions.ass"; build_ass(scenes,durations,ass)
    segments=[]; segment_commands=[]
    for idx,(s,dur) in enumerate(zip(scenes,durations),1):
        src=Path(s["local_path"])
        src_dur=probe_duration(src)
        try:
            requested_speed=float(s.get("playback_speed") or DEFAULT_VISUAL_SPEED)
            verified_duration=float(s["shot_end_seconds"])-float(s["shot_start_seconds"])
        except (TypeError, ValueError) as exc:
            raise RenderError(f"scene {idx}: playback_speed must be numeric") from exc
        usable_duration=min(src_dur,verified_duration)
        if usable_duration + 0.12 < dur:
            raise RenderError(f"scene {idx}: verified visual interval {src_dur:.2f}s shorter than required narration beat {dur:.2f}s")
        # A requested speed-up is only applied when the approved source window
        # contains enough real frames to cover the complete spoken beat.  This
        # prevents timestamp holes or frozen tails between scenes.
        safe_speed=max(1.0,(usable_duration-0.08)/dur)
        effective_speed=min(requested_speed,safe_speed)
        effective_scene={**s,"playback_speed":effective_speed}
        # `local_path` is exactly the source interval approved by visual review.
        # A renderer may shorten its tail for narration timing but must never seek
        # to another moment inside or outside that approved interval.
        start=0.0
        seg=job_dir/f"seg_{idx:02d}.mp4"; vf=scene_filter(effective_scene,idx,dur)
        if ";" in vf:
            fc=f"[0:v]{vf}[v]"
            cmd=["ffmpeg","-hide_banner","-loglevel","error","-y","-ss",f"{start:.3f}","-i",str(src),"-an","-filter_complex_threads","1","-filter_complex",fc,"-map","[v]","-c:v","libx264","-threads","2","-preset","veryfast","-crf","17","-pix_fmt","yuv420p",str(seg)]
        else:
            cmd=["ffmpeg","-hide_banner","-loglevel","error","-y","-ss",f"{start:.3f}","-i",str(src),"-an","-filter_threads","1","-vf",vf,"-c:v","libx264","-threads","2","-preset","veryfast","-crf","17","-pix_fmt","yuv420p",str(seg)]
        run(cmd, 300)
        actual_duration=probe_duration(seg)
        if abs(actual_duration-dur) > 0.08:
            raise RenderError(f"scene {idx}: encoded segment has {actual_duration:.3f}s instead of {dur:.3f}s")
        segments.append(seg); segment_commands.append((cmd,dur))

    concat=job_dir/"concat.txt"
    concat.write_text("\n".join(f"file '{p.resolve().as_posix()}'" for p in segments)+"\n",encoding="utf-8")
    lower=job_dir/"lower.mp4"
    # A damaged intermediate can make FFmpeg concat exit successfully after
    # only the first scene. Verify the full track and retry damaged segments.
    for attempt in range(3):
        for seg,(cmd,dur) in zip(segments,segment_commands):
            try:
                valid=seg.stat().st_size>=32_000 and abs(probe_duration(seg)-dur)<=0.08
            except (OSError,ValueError,RenderError):
                valid=False
            if not valid:
                run(cmd,300)
        try:
            run(["ffmpeg","-hide_banner","-loglevel","error","-xerror","-y","-f","concat","-safe","0","-i",str(concat),"-c","copy",str(lower)],120)
            lower_duration=probe_duration(lower)
            if abs(lower_duration-sum(durations))<=0.12:
                break
        except RenderError:
            pass
    else:
        raise RenderError("concatenated visual track lost scenes after three attempts")
    out=job_dir/"preview.mp4"
    fc=(f"[0:v]crop={CANVAS_W}:{VIDEO_H}:0:0[lower];[lower]pad={CANVAS_W}:{CANVAS_H}:0:{VIDEO_Y}:color=black[base];"
        f"[base][1:v]overlay=0:0:eof_action=repeat:repeatlast=1[locked];[locked]ass={ass.as_posix()}[v]")
    studio_voice=("highpass=f=75,"
                  "equalizer=f=140:t=q:w=0.8:g=2.5,"
                  "equalizer=f=430:t=q:w=1:g=-1.5,"
                  "equalizer=f=3000:t=q:w=0.9:g=2.0,"
                  "acompressor=threshold=0.10:ratio=2.2:attack=18:release=160:makeup=1.35:mix=0.85,"
                  "loudnorm=I=-15:TP=-1.5:LRA=8,volume=2dB,alimiter=limit=0.89")
    run(["ffmpeg","-hide_banner","-loglevel","error","-y","-i",str(lower),"-loop","1","-i",str(header),"-i",str(audio),
         "-filter_complex_threads","1","-filter_complex",fc,"-map","[v]","-map","2:a:0","-t",f"{audio_dur:.3f}","-c:v","libx264","-threads","2","-preset","veryfast","-crf","16",
         "-pix_fmt","yuv420p","-af",studio_voice,"-ac","2","-ar","48000",
         "-c:a","aac","-b:a","192k","-movflags","+faststart",str(out)],360)

    frame=job_dir/"qc_frame.png"
    run(["ffmpeg","-hide_banner","-loglevel","error","-y","-ss","0.3","-i",str(out),"-frames:v","1",str(frame)],60)
    actual=Image.open(frame).convert("RGB"); expected=Image.open(header).convert("RGB")
    if actual.size!=(CANVAS_W,CANVAS_H): raise RenderError(f"wrong output size: {actual.size}")
    diff=ImageChops.difference(actual.crop((0,0,CANVAS_W,HEADER_H)),expected)
    mae=sum(ImageStat.Stat(diff).mean)/3
    if mae>12: raise RenderError(f"layout lock drift: MAE {mae:.3f}")
    return {"status":"RENDER_READY","preview_path":str(out),"duration_seconds":round(probe_duration(out),3),"layout_header_mae":round(mae,3),"layout_lock":"KN_LAYOUT_V1"}
