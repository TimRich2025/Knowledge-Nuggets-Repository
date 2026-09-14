import os,json,re,subprocess,requests,time
from pathlib import Path
from urllib.parse import urlparse,unquote
from faster_whisper import WhisperModel
CID=os.environ["KN_CONTENT_ID"]; SCRIPT=os.environ["KN_SCRIPT"]; PKG=json.loads(os.environ["KN_RENDER_PACKAGE"]); AUDIO=os.environ["KN_AUDIO_URL"]; WM=os.environ["KN_WATERMARK_URL"]
W=Path("work"); O=Path("output"); W.mkdir(exist_ok=True); O.mkdir(exist_ok=True)
def sh(cmd):
 p=subprocess.run(cmd,text=True,capture_output=True)
 if p.returncode: raise RuntimeError((p.stderr or p.stdout)[-5000:])
 return p.stdout
def get(url,name):
 h={"User-Agent":"KnowledgeNuggetsBot/2.0"}
 for n in range(3):
  try:
   r=requests.get(url,timeout=(15,180),allow_redirects=True,headers=h); r.raise_for_status()
   ct=r.headers.get("content-type","")
   if ct.startswith("text/"): raise RuntimeError(ct)
   ext=Path(urlparse(r.url).path).suffix.lower() or ".bin"
   p=W/(name+ext); p.write_bytes(r.content); return p
  except Exception:
   if n==2: raise
   time.sleep(2+n)
def probe(p):
 d=json.loads(sh(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=width,height,codec_name","-show_entries","format=duration","-of","json",str(p)]))
 if not d.get("streams"): raise RuntimeError("NO_VIDEO_STREAM")
 s=d["streams"][0]; return int(s["width"]),int(s["height"]),float(d["format"]["duration"])
def dur(p):
 return float(sh(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(p)]).strip())
def blocked(u):
 t=unquote(u).lower().replace("_"," ").replace("-"," ")
 for x in ("live video","official stream","live stream","livestream","live event","event starts","news conference","press conference","countdown","webinar","presentation","title card","broadcast slate"):
  if x in t:return x
def tm(x):return f"{int(x//3600)}:{int((x%3600)//60):02d}:{x%60:05.2f}"
def subs(audio,path):
 m=WhisperModel("base.en",device="cpu",compute_type="int8")
 seg,_=m.transcribe(str(audio),language="en",word_timestamps=True,beam_size=3,initial_prompt=SCRIPT[:1000])
 words=[]
 for s in seg:
  for q in s.words or []:
   if q.start is not None and q.end is not None and (q.word or "").strip(): words.append(((q.word or "").strip(),float(q.start),float(q.end)))
 if not words: raise RuntimeError("NO_WORD_TIMESTAMPS")
 groups=[]; cur=[]
 for i,(w,_,_) in enumerate(words):
  cand=cur+[i]; chars=sum(len(words[j][0]) for j in cand)+len(cand)-1
  if cur and (len(cand)>4 or chars>25): groups.append(cur); cur=[i]
  else: cur=cand
 if cur: groups.append(cur)
 gm={j:g for g in groups for j in g}
 head="""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: KN,DejaVu Sans,60,&H00FFFFFF,&H00008AFF,&H00101010,&H00000000,-1,0,0,0,100,100,0,0,1,2.3,0,2,120,120,405,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
 out=[]
 for i,(w,st,en) in enumerate(words):
  txt=[]
  for j in gm[i]:
   z=words[j][0].replace("\\","\\\\").replace("{","\\{").replace("}","\\}")
   if j==i:z=r"{\c&H00008AFF&}"+z+r"{\c&H00FFFFFF&}"
   txt.append(z)
  out.append(f"Dialogue: 0,{tm(st)},{tm(max(en,st+.12))},KN,,0,0,0,,{' '.join(txt)}")
 path.write_text(head+"\n".join(out),encoding="utf-8"); return len(words)
if PKG.get("production_status")!="READY": raise RuntimeError("PACKAGE_NOT_READY")
sc=PKG.get("scenes") or []
if not sc or not WM: raise RuntimeError("MISSING_SCENES_OR_WATERMARK")
urls=[x.get("source_url","") for x in sc]
if any(not x for x in urls): raise RuntimeError("MISSING_SOURCE")
if len(sc)>=4 and len(set(urls))/len(urls)<.75: raise RuntimeError("INSUFFICIENT_VARIETY")
audio=get(AUDIO,"narration"); ad=dur(audio)
weights=[max(1,len(str(x.get("spoken_phrase","")).split())) for x in sc]; sw=sum(weights); ds=[ad*w/sw for w in weights]
cache={}; sources=[]; qc=[]
for i,(s,sd) in enumerate(zip(sc,ds),1):
 u=s["source_url"]; b=blocked(u)
 if b: raise RuntimeError(f"SOURCE_TITLE_REJECTED_{i}_{b}")
 if u not in cache:
  p=get(u,f"src{len(cache)+1}"); cache[u]=(p,*probe(p))
 p,w,h,ln=cache[u]
 if w>=h and h<1920: raise RuntimeError(f"LOW_RES_LANDSCAPE_{i}_{w}x{h}")
 if h>w and (w<1080 or h<1920): raise RuntimeError(f"LOW_RES_PORTRAIT_{i}_{w}x{h}")
 cp=str(s.get("crop_preference") or "CENTER").upper()
 if cp not in ("LEFT","CENTER","RIGHT"):cp="CENTER"
 sources.append((p,w,h,ln,cp)); qc.append({"scene":i,"source_width":w,"source_height":h,"crop_preference":cp})
ass=W/"subs.ass"; wc=subs(audio,ass); wm=get(WM,"watermark")
cmd=["ffmpeg","-hide_banner","-y"]; uses={}
for (p,w,h,ln,cp),sd in zip(sources,ds):
 k=str(p); n=uses.get(k,0); uses[k]=n+1; off=min(8*n,max(0,ln-sd-.25))
 cmd+=["-stream_loop","-1","-ss",f"{off:.3f}","-i",str(p)]
wi=len(sources); ai=wi+1; cmd+=["-loop","1","-i",str(wm),"-i",str(audio)]
f=[]; labs=[]
for i,((p,w,h,ln,cp),sd) in enumerate(zip(sources,ds)):
 x="0" if cp=="LEFT" else "iw-ow" if cp=="RIGHT" else "(iw-ow)/2"; lab=f"v{i}"
 f.append(f"[{i}:v]trim=duration={sd:.3f},setpts=PTS-STARTPTS,scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:{x}:(ih-oh)/2,setsar=1,fps=30[{lab}]"); labs.append(f"[{lab}]")
f.append("".join(labs)+f"concat=n={len(labs)}:v=1:a=0[vcat]")
aa=str(ass.resolve()).replace(":","\\:")
f.append(f"[vcat]ass='{aa}'[vs]"); f.append(f"[{wi}:v]scale=72:-1,format=rgba,colorchannelmixer=aa=.72[wm]"); f.append("[vs][wm]overlay=(W-w)/2:H-h-54[v]")
safe=re.sub(r"[^A-Za-z0-9_-]+","_",CID)[:80] or "kn"; out=O/f"{safe}.mp4"
cmd+=["-filter_complex",";".join(f),"-map","[v]","-map",f"{ai}:a:0","-c:v","libx264","-preset","medium","-crf","17","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-shortest","-movflags","+faststart",str(out)]
sh(cmd)
fd=dur(out); p=json.loads(sh(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=width,height,codec_name","-of","json",str(out)]))["streams"][0]
issues=[]
if p.get("width")!=1080 or p.get("height")!=1920:issues.append("wrong_dimensions")
if p.get("codec_name")!="h264":isssues.append("codec")
if abs(fd-ad)>1:issues.append("duration")
q={"content_id":CID,"status":"RENDER_READY" if not issues else "RENDER_QC_FAILED","duration_seconds":round(fd,3),"technical_qc_score":100 if not issues else 70,"content_qc_score":100 if wc>=max(3,int(len(SERIPT.split())*.7)) else 80,"word_timestamps":wc,"motion_scenes":len(sc),"unique_motion_sources":len(cache),"watermark":"BRAIN_NUGGET_APPLIED","watermark_width_px":72,"subtitle_layout":"KN_FIXED_V2_3TO4_WORDS_SAFE","subtitle_margin_v":405,"source_qc":qc,"render_mode":"SINGLE_PASS_FINAL_ENCODE","issues":issues}
(O/"qc.json").write_text(json.dumps(q),encoding="utf-8"); print(json.dumps(q)
