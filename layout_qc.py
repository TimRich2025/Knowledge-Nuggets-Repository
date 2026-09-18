import json, subprocess
from pathlib import Path
from PIL import Image, ImageChops, ImageStat
from layout_lock import build_header, HEADER_H, CANVAS_W, CANVAS_H

OUT=Path('output'); MEDIA=Path('media'); MEDIA.mkdir(exist_ok=True)
plan=json.loads((OUT/'fullscreen_plan.json').read_text(encoding='utf-8'))
video=OUT/'KN-ASTRONAUT-V4_LAYOUT_LOCKED_PREVIEW.mp4'
if not video.exists():
    raise SystemExit('Preview missing')
question_lines=plan.get('core_question_lines') or ['WHY DO ASTRONAUTS','GROW TALLER?']
expected=MEDIA/'kn_locked_header_qc.png'
build_header(question_lines,expected)
frame=MEDIA/'layout_qc_frame.png'
subprocess.run(['ffmpeg','-y','-ss','0.50','-i',str(video),'-frames:v','1',str(frame)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
actual=Image.open(frame).convert('RGB')
if actual.size!=(CANVAS_W,CANVAS_H):
    raise SystemExit(f'Layout FAIL: resolution {actual.size}')
actual_header=actual.crop((0,0,CANVAS_W,HEADER_H))
exp=Image.open(expected).convert('RGB')
diff=ImageChops.difference(actual_header,exp)
stat=ImageStat.Stat(diff)
mae=sum(stat.mean)/3
report={'layout':'KN_LAYOUT_V1','resolution':list(actual.size),'header_mae':round(mae,3),'threshold':12.0,'pass':mae<=12.0}
(OUT/'layout_qc.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
if not report['pass']:
    raise SystemExit('Layout FAIL: fixed header changed')
