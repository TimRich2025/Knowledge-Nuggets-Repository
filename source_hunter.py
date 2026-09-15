import os,json,re,subprocess,requests,html
from pathlib import Path
from urllib.parse import quote
from PIL import Image,ImageStat,ImageFilter

SCENES=json.loads(os.environ["KN_SCENE_BRIEF"])
OUT=Path("output"); OUT.mkdir(exist_ok=True)
BAD=("live video","official stream","live stream","livestream","live event","event starts","news conference","press conference","countdown","webinar","presentation","title card","broadcast","briefing","coverage","podcast","audio only","weather balloon","simulation","simulator","animation","interview")
SPACE=("astronaut","space station","iss","microgravity","spaceflight","crew","nasa","orbit","cosmonaut")
EXTRA={
1:["astronaut anthropometry body measurement NASA","astronaut medical examination spaceflight","astronaut height measurement ISS"],
2:["astronaut floating microgravity inside ISS","astronaut weightless ISS interior","crew floating space station"],
3:["astronaut ultrasound human research ISS","spinal ultrasound astronaut ISS","astronaut physiology research microgravity","astronaut bone muscle medical research ISS"],
4:["astronaut height body measurement ISS","astronaut anthropometry spaceflight","astronaut medical body measurement NASA"],
5:["astronaut postflight recovery after landing NASA","astronaut crew landing recovery","astronaut rehabilitation after spaceflight"]}
REQ={
1:(("astronaut","crew"),("measure","measurement","medical","body","height","anthropometry","exam")),
2:(("astronaut","crew"),("float","floating","weightless","microgravity","iss","space station")),
3:(("astronaut","crew"),("ultrasound","spine","spinal","physiology","human research","medical","bone","muscle","vertebra")),
4:(("astronaut","crew"),("height","measure","measurement","body","anthropometry","medical")),
5:(("astronaut","crew"),("landing","landed","return","recovery","postflight","rehabilitation","earth"))}

def run(cmd,timeout=65):
 p=subprocess.run(cmd,text=True,capture_output=True,timeout=timeout); return p.stdout if p.returncode==0 else None

def clean(s): return re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",html.unescape(s or ""))).strip()
def words(s): return set(re.findall(r"[a-z0-9]+",(s or "").lower()))
def metadata_text(title="",desc="",keywords=None,q=""): return clean(" ".join([title,desc or ""," ".join(keywords or []),q])).lower()

def semantic_score(scene,text):
 sn=int(scene.get("scene") or 0); groups=REQ.get(sn)
 if not groups:return 0
 if any(x in text for x in BAD):return 0
 if not any(x in text for x in groups[0]):return 0
 hits=sum(1 for x in groups[1] if x in text)
 if hits==0:return 0
 score=55+min(35,hits*10)
 ideal=(scene.get("ideal_footage") or "").lower(); fallback=(scene.get("fallback_footage") or "").lower()
 overlap=len((words(ideal)|words(fallback)) & words(text)); score+=min(10,overlap*2)
 return min(100,score)

def probe(url):
 o=run(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=width,height,codec_name","-show_entries","format=duration","-of","json",url],55)
 if not o:return None
 try:
  d=json.loads(o); s=(d.get("streams") or [{}])[0]; return {"width":int(s.get("width") or 0),"height":int(s.get("height") or 0),"duration":float((d.get("format") or {}).get("duration") or 0),"codec":s.get("codec_name") or ""}
 except:return None

def classify(w,h):
 if h>w:return (True,98,"CROP_FILL") if w>=1080 and h>=1920 else (False,0,None)
 if w>=3000 and h>=1680:return True,98,"CROP_FILL"
 if w>=1920 and h>=1080:return True,92,"FIT_BLUR"
 return False,0,None

def crop_filter(cp):
 x="0" if cp=="LEFT" else "iw-ow" if cp=="RIGHT" else "(iw-ow)/2"; return f"scale=360:640:force_original_aspect_ratio=increase,crop=360:640:{x}:(ih-oh)/2"
def sample(url,dur,stem,layout,cp="CENTER"):
 p=OUT/f"{stem}_{cp.lower()}.jpg"; t=max(.2,min((dur or 3)*.35,max(.2,(dur or 3)-.5))); vf=crop_filter(cp) if layout=="CROP_FILL" else "scale=480:-2"; run(["ffmpeg","-hide_banner","-loglevel","error","-y","-ss",f"{t:.3f}","-i",url,"-frames:v","1","-vf",vf,str(p)],75); return p if p.exists() else None

def frame_qc(path):
 if not path:return {"pass":False,"score":0,"ocr":"","reason":"extract_failed"}
 with Image.open(path) as im:
  g=im.convert("L"); st=ImageStat.Stat(g); edge=ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]; ent=g.entropy(); std=st.stddev[0]; mean=st.mean[0]
 try:txt=re.sub(r"\s+"," ",subprocess.run(["tesseract",str(path),"stdout","--psm","11"],text=True,capture_output=True,timeout=20).stdout).strip()
 except:txt=""
 low=txt.lower(); risk=any(x in low for x in BAD) or len(re.findall(r"[A-Za-z]{3,}",txt))>=11; blank=(std<10 and ent<3.8) or (edge<3.5 and (mean>238 or mean<15)); soft=edge<4.2 and ent<4.6; score=std*.45+ent*7+edge*2; ok=not(risk or blank or soft); return {"pass":ok,"score":round(score,2),"ocr":txt[:160],"reason":"pass" if ok else "text_or_blank_or_soft"}
def best_comp(url,dur,stem,layout):
 if layout=="FIT_BLUR":
  q=frame_qc(sample(url,dur,stem,layout)); return ("CENTER",q) if q["pass"] else (None,q)
 good=[]
 for cp in ("LEFT","CENTER","RIGHT"):
  q=frame_qc(sample(url,dur,stem,layout,cp));
  if q["pass"]:good.append((q["score"],cp,q))
 return (max(good,key=lambda x:x[0])[1],max(good,key=lambda x:x[0])[2]) if good else (None,{"pass":False,"score":0,"reason":"all_vertical_crops_failed"})

def nasa_search(q):return requests.get("https://images-api.nasa.gov/search",params={"q":q,"media_type":"video","page_size":30},timeout=30).json()["collection"].get("items",[])
def nasa_assets(nid):return [x.get("href","") for x in requests.get("https://images-api.nasa.gov/asset/"+quote(nid,safe=""),timeout=30).json()["collection"].get("items",[])]
def nasa_videos(urls):return sorted([u for u in urls if re.search(r"\.(mp4|mov|m4v)(?:$|\?)",u,re.I)],key=lambda u:5 if "~orig" in u.lower() else 4 if "~large" in u.lower() else 2,reverse=True)
def commons_search(q):
 p={"action":"query","generator":"search","gsrsearch":q,"gsrnamespace":6,"gsrlimit":30,"prop":"imageinfo","iiprop":"url|mime|size|extmetadata","format":"json","formatversion":2}; return (requests.get("https://commons.wikimedia.org/w/api.php",params=p,headers={"User-Agent":"KnowledgeNuggetsBot/4.2"},timeout=35).json().get("query") or {}).get("pages",[])
def commons_license(meta):
 lic=((meta.get("LicenseShortName") or {}).get("value") or ""); txt=(lic+" "+((meta.get("UsageTerms") or {}).get("value") or "")).lower(); return ("public domain" in txt or "cc0" in txt or "pd-usgov" in txt or "pd-nasa" in txt),lic or "Public domain"

def common_obj(scene,page,q,rank,index):
 title=page.get("title") or ""; ii=((page.get("imageinfo") or [{}])[0]); meta=ii.get("extmetadata") or {}; desc=clean(((meta.get("ImageDescription") or {}).get("value") or "")); text=metadata_text(title,desc,[],q); sem=semantic_score(scene,text)
 if sem<65:return None
 mime=(ii.get("mime") or "").lower(); url=ii.get("url") or ""; oklic,lic=commons_license(meta)
 if not mime.startswith("video/") or not re.search(r"\.(webm|mp4)(?:$|\?)",url,re.I) or not oklic:return None
 pr=probe(url)
 if not pr or pr["duration"]<1:return None
 ok,qs,layout=classify(pr["width"],pr["height"])
 if not ok:return None
 cp,fq=best_comp(url,pr["duration"],f"c{scene['scene']}_{index}",layout)
 if not cp:return None
 return {"scene":scene["scene"],"spoken_phrase":scene.get("spoken_phrase",""),"source_type":"WIKIMEDIA_COMMONS","title":title.replace("File:","",1),"direct_download_url":url,"source":"Wikimedia Commons","license":lic,"rights_status":"PASS","media_type":"VIDEO","width":pr["width"],"height":pr["height"],"duration":round(pr["duration"],2),"visual_quality_score":qs,"semantic_score":sem,"layout_mode":layout,"crop_preference":cp,"frame_qc":fq,"matched_query":q,"search_rank":rank,"status":"CANDIDATE"}

def nasa_obj(scene,d,q,rank,index):
 nid=d.get("nasa_id"); title=d.get("title") or ""; desc=d.get("description") or ""; kws=d.get("keywords") or []; text=metadata_text(title,desc,kws,q); sem=semantic_score(scene,text)
 if not nid or sem<65 or not any(x in text for x in SPACE):return None
 try:urls=nasa_videos(nasa_assets(nid))
 except:return None
 for url in urls[:3]:
  pr=probe(url)
  if not pr or pr["duration"]<1:continue
  ok,qs,layout=classify(pr["width"],pr["height"])
  if not ok:continue
  cp,fq=best_comp(url,pr["duration"],f"n{scene['scene']}_{index}",layout)
  if cp:return {"scene":scene["scene"],"spoken_phrase":scene.get("spoken_phrase",""),"source_type":"NASA","nasa_id":nid,"title":title,"direct_download_url":url,"source":"NASA Image and Video Library","license":"NASA U.S. Government media","rights_status":"PASS","media_type":"VIDEO","width":pr["width"],"height":pr["height"],"duration":round(pr["duration"],2),"visual_quality_score":qs,"semantic_score":sem,"layout_mode":layout,"crop_preference":cp,"frame_qc":fq,"matched_query":q,"search_rank":rank,"status":"CANDIDATE"}
 return None

def collect(scene,queries,kind,limit=10):
 out=[];seen=set()
 for q in queries:
  try:items=commons_search(q) if kind=="commons" else nasa_search(q)
  except:continue
  for rank,it in enumerate(items[:20],1):
   key=it.get("title") if kind=="commons" else ((it.get("data") or [{}])[0]).get("nasa_id")
   if not key or key in seen:continue
   seen.add(key); c=common_obj(scene,it,q,rank,len(out)) if kind=="commons" else nasa_obj(scene,(it.get("data") or [{}])[0],q,rank,len(out))
   if c:out.append(c)
   if len(out)>=limit:return out
 return out

pools=[]
for scene in SCENES:
 sn=int(scene.get("scene") or 0); base=list(scene.get("search_queries") or []); queries=base+EXTRA.get(sn,[]); candidates=collect(scene,queries,"commons",10)
 if len(candidates)<10:candidates+=collect(scene,queries,"nasa",10-len(candidates))
 candidates=list({c["direct_download_url"]:c for c in candidates}.values()); candidates.sort(key=lambda c:(-c["semantic_score"],-c["visual_quality_score"],c["search_rank"])); pools.append((scene,candidates))

used_urls=set();used_ids=set();manifest=[]
for scene,candidates in pools:
 selected=None
 for c in candidates:
  identity=c.get("nasa_id") or c.get("title") or c["direct_download_url"]
  if c["direct_download_url"] not in used_urls and identity not in used_ids:
   selected=dict(c);used_urls.add(c["direct_download_url"]);used_ids.add(identity);break
 if selected:selected["status"]="SELECTED";manifest.append(selected)
 else:manifest.append({"scene":scene.get("scene"),"spoken_phrase":scene.get("spoken_phrase",""),"status":"NO_RELEVANT_UNIQUE_SOURCE","candidates_found":len(candidates)})
selected=[x for x in manifest if x.get("status")=="SELECTED"];unique=len({x.get("direct_download_url") for x in selected});ready=len(selected)==len(SCENES) and unique>=4 and all(x.get("semantic_score",0)>=65 for x in selected)
(OUT/"source_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8");(OUT/"source_gate.json").write_text(json.dumps({"ready":ready,"selected":len(selected),"scenes":len(SCENES),"unique_sources":unique,"minimum_unique_sources":4,"minimum_semantic_score":65},indent=2),encoding="utf-8")
print(json.dumps(manifest))
if not ready:raise SystemExit(f"Semantic/multi-source gate failed: {unique} unique relevant assets for {len(SCENES)} scenes.")
