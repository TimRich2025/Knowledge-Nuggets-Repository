import json, subprocess
from pathlib import Path
from PIL import ImageFont
from layout_lock import (
    build_header, BRAND_FONT, QUESTION_FONT, LOGO_PATH,
    CANVAS_W, CANVAS_H, VIDEO_Y, VIDEO_H, QUESTION_SIZE, QUESTION_MAX_W
)

OUT=Path("output"); OUT.mkdir(exist_ok=True)
MEDIA=Path("media"); MEDIA.mkdir(exist_ok=True)
for p,label in ((LOGO_PATH,"official logo"),(Path(BRAND_FONT),"brand font"),(Path(QUESTION_FONT),"question font")):
    if not Path(p).is_file():
        raise SystemExit(f"Preflight FAIL: missing {label}: {p}")

# Validate the exact approved master question with the exact locked font.
font=ImageFont.truetype(QUESTION_FONT,QUESTION_SIZE)
for text in ("WHY DO ASTRONAUTS","GROW TALLER?"):
    width=font.getbbox(text)[2]-font.getbbox(text)[0]
    if width>QUESTION_MAX_W:
        raise SystemExit(f"Preflight FAIL: locked question width {width}>{QUESTION_MAX_W}: {text}")

header=MEDIA/"preflight_header.png"
build_header(["WHY DO ASTRONAUTS","GROW TALLER?"],header)
video=MEDIA/"preflight_video.mp4"
vf=(
    f"[0:v]pad={CANVAS_W}:{CANVAS_H}:0:{VIDEO_Y}:color=black[base];"
    f"[base][1:v]overlay=0:0[locked];"
    f"[locked]drawtext=fontfile={QUESTION_FONT}:text='PREFLIGHT':fontcolor=white:fontsize=68:"
    f"borderw=6:bordercolor=black@0.95:x=(w-text_w)/2:y={VIDEO_Y}+(VIDEO_H-text_h)/2[v]"
)
subprocess.run([
    "ffmpeg","-hide_banner","-loglevel","error","-y",
    "-f","lavfi","-i",f"testsrc2=size={CANVAS_W}x{VIDEO_H}:rate=30:duration=0.5",
    "-loop","1","-i",str(header),"-t","0.5","-filter_complex",vf,
    "-map","[v]","-an","-r","30","-c:v","libx264","-preset","ultrafast","-crf","28",
    "-pix_fmt","yuv420p",str(video)
],check=True)

probe=subprocess.run([
    "ffprobe","-v","error","-select_streams","v:0",
    "-show_entries","stream=codec_name,width,height,pix_fmt","-of","json",str(video)
],check=True,text=True,capture_output=True)
stream=(json.loads(probe.stdout).get("streams") or [{}])[0]
expected={"codec_name":"h264","width":CANVAS_W,"height":CANVAS_H,"pix_fmt":"yuv420p"}
for k,v in expected.items():
    if stream.get(k)!=v:
        raise SystemExit(f"Preflight FAIL: {k}={stream.get(k)!r}, expected {v!r}")

voice=MEDIA/"preflight_voice.wav"
subprocess.run(["espeak-ng","-v","en-us","-s","158","-p","42","-w",str(voice),"Knowledge Nuggets preflight"],check=True)
if not voice.is_file() or voice.stat().st_size<1000:
    raise SystemExit("Preflight FAIL: espeak did not create usable audio")

print(json.dumps({
    "preflight":True,"header":True,"drawtext":True,"h264":True,"yuv420p":True,
    "espeak":True,"brand_font":BRAND_FONT,"question_font":QUESTION_FONT
}))
