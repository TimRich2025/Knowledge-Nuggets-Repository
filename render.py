import json,os,re,subprocess
from pathlib import Path
import requests
from faster_whisper import WhisperModel
CID=os.environ["KN_CONTENT_ID"]; SCRIPT=os.environ["KN_SCRIPT"]; PKG=json.loads(os.environ["KN_RENDER_PACKAGE"]); AUDIO=os.environ["KN_AUDIO_URL"]; WM=os.environ.get("KN_WATERMARK_URL","").strip()
W=Path("work"); O=Path("output"); W.mkdir(exist_ok=True); O.mkdir(exist_ok=True)
def run(c):
 p=subprocess.run(c,text=True,capture_output=True)
 if p.returncode: raise RuntimeError(p.stderr[-3500:])
 return p.stdout
def dl(u,p):
 r=requests.get(u,timeout=60,allow_redirects=True,headers={"User-Agent":"KN/1"}); r.raise_for_status(); p.write_bytes(r.content); return r.headers.get("content-type","")
def dur(p): return float(run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(p)]).strip())
def ts(x):
 return f"{int(x//3600)}:{int((x%3600)//60):02d}:{x%60:05.2f}"
def subs(a,p):
 m=WhisperModel("base.en",device="cpu",compute_type="int8"); seg,_=m.transcribe(str(a),language="en",word_timestamps=True,beam_size=3,initial_prompt=SCRIPT[:1000]); w=[]
 for s in seg:
  for q in (s.words or []):
   if q.start is not None and q.end is not None and (q.word or "").strip(): w.append((q.word.strip(),float(q.start),float(q.end)))
 if not w: raise RuntimeError("No word timestamps")
 h='''[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: KN,DejaVu Sans,64,&H00FFFFFF,&H00008AFF,&H00111111,&H00000000,-1,0,0,0,100,100,0,0,1,3,0,2,70,70,275,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'''
 L=[]
 for i,(word,st,en) in enumerate(w):
  lo=max(0,i-2); hi=min(len(w),lo+6); lo=max(0,hi-6); z=[]
  for j in range(lo,hi):
   t=w[j][0].replace("\\",r"\\").replace("{",r"\{").replace("}",r"\}")
   z.append((r"{\c&H00008AFF&}"+t+r"{\c&H00FFFFFF&}") if j==i else t)
  L.append(f"Dialogue: 0,{ts(st)},{ts(max(en,st+.12))},KN,,0,0,0,,{' '.join(z)}")
 p.write_text(h+"\n".join(L),encoding="utf-8"); return len(w)
if PKG.get("production_status")!="READY": raise RuntimeError("Render package not READY")
S=PKG.get("scenes") or []
if not S: raise RuntimeError("No scenes")
a=W/"narration.mp3"; dl(AUDIO,a); ad=dur(a); per=max(ad/len(S),.5); clips=[]
for i,s in enumerate(S,1):
 src=W/f"src{i}"; ct=dl(s["source_url"],src); c=W/f"s{i:02d}.mp4"; vf="scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30"; inp=["-loop","1","-i",str(src)] if ct.lower().startswith("image/") else ["-stream_loop","-1","-i",str(src)]
 run(["ffmpeg","-y",*inp,"-t",f"{per:.3f}","-vf",vf,"-an","-c:v","libx264","-preset","veryfast","-crf","20","-pix_fmt","yuv420p",str(c)]); clips.append(c)
lst=W/"c.txt"; lst.write_text("\n".join(f"file '{x.resolve().as_posix()}'" for x in clips)); v=W/"v.mp4"; run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),"-c","copy",str(v)])
ass=W/"s.ass"; wc=subs(a,ass); safe=re.sub(r"[^A-Za-z0-9_-]+","_",CID)[:80] or "kn"; out=O/f"{safe}.mp4"; aa=str(ass.resolve()).replace(":","\\:")
if WM:
 wm=W/"wm.png"; dl(WM,wm); fc=f"[0:v]ass='{aa}'[v0];[1:v]scale=95:-1[wm];[v0][wm]overlay=W-w-44:H-h-44[v]"; cmd=["ffmpeg","-y","-i",str(v),"-i",str(wm),"-i",str(a),"-filter_complex",fc,"-map","[v]","-map","2:a:0"]
else: cmd=["ffmpeg","-y","-i",str(v),"-i",str(a),"-vf",f"ass='{aa}'","-map","0:v:0","-map","1:a:0"]
run(cmd+["-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-shortest","-movflags","+faststart",str(out)])
fd=dur(out); pr=json.loads(run(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=width,height,codec_name","-of","json",str(out)]))["streams"][0]; sc=100; issues=[]
if pr.get("width")!=1080 or pr.get("height")!=1920: sc-=35; issues.append("wrong_dimensions")
if pr.get("codec_name")!="h264": sc-=10; issues.append("codec")
if abs(fd-ad)>1: sc-=20; issues.append("duration")
q={"content_id":CID,"status":"RENDER_READY" if sc>=90 else "RENDER_QC_FAILED","duration_seconds":round(fd,3),"technical_qc_score":max(sc,0),"content_qc_score":100 if wc>=max(3,int(len(SCRIPT.split())*.7)) else 80,"word_timestamps":wc,"issues":issues}; (O/"qc.json").write_text(json.dumps(q)); print(json.dumps(q))
