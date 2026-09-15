import os,json,re,subprocess,requests,html
from pathlib import Path
from urllib.parse import quote
from PIL import Image,ImageStat,ImageFilter

SCENES=json.loads(os.environ["KN_SCENE_BRIEF"])
OUT=Path("output"); OUT.mkdir(exist_ok=True)
BAD=("live video","official stream","live stream","livestream","live event","news conference","press conference","countdown","webinar","presentation","broadcast","briefing","podcast","audio only","weather balloon","simulation","simulator","interview")
# Every scene gets its own visual concept. Broad 'space' relevance is explicitly insufficient.
CONCEPTS={
1:{"must_any":["height","taller","measure","measurement","anthropometry","medical examination","body measurement"],"context_any":["astronaut","spaceflight","crew"],"queries":["astronaut height measurement video","astronaut body measurement spaceflight video","astronaut anthropometry NASA video"]},
2:{"must_any":["microgravity","weightless","floating","zero gravity"],"context_any":["astronaut","crew","iss","space station"],"queries":["astronaut floating microgravity ISS video","astronaut weightless inside space station video"]},
3:{"must_any":["spine","spinal","vertebra","intervertebral","disc","ultrasound"],"context_any":["astronaut","microgravity","spaceflight","human body","medical","anatomy"],"queries":["astronaut spinal ultrasound ISS video","spine microgravity intervertebral disc video","astronaut spine medical research video","spinal ultrasound spaceflight video"]},
4:{"must_any":["height","taller","three percent","3 percent","measure","measurement","anthropometry"],"context_any":["astronaut","spaceflight","crew"],"queries":["astronaut grows taller space height measurement video","astronaut height measurement ISS video","spaceflight anthropometry height video"]},
5:{"must_any":["landing","landed","return to earth","postflight","post-flight","recovery","rehabilitation"],"context_any":["astronaut","crew","spaceflight"],"queries":["astronaut postflight recovery after landing video","astronaut return Earth medical recovery video","crew landing recovery astronaut video"]}}

def run(cmd,timeout=65):
 p=subprocess.run(cmd,text=True,capture_output=True,timeout=timeout); return p.stdout if p.returncode==0 else None

def clean(s):return re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",html.unescape(s or ""))).strip()
def text_blob(title="",desc="",keywords=None):return clean(" ".join([title,desc or ""," ".join(keywords or [])])).lower()

def semantic_score(scene,text):
 c=CONCEPTS.get(int(scene.get("scene") or 0),{})
 if not c or any(x in text for x in BAD):return 0
 concept_hits=sum(1 for x in c["must_any"] if x in text)
 context_hits=sum(1 for x in c["context_any"] if x in text)
 # Search-query words NEVER count as evidence: only source metadata is scored.
 if concept_hits<1 or context_hits<1:return 0
 return min(100,70+min(20,(concept_hits-1)*8)+min(10,(context_hits-1)*4))

def probe(url):
 o=run(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=width,height,codec_name","-show_entries","format=duration","-of","json",url],55)
 if not o:return None
 try:
  d=json.loads(o);s=(d.get("streams") or [{}])[0];return {"width":int(s.get("width") or 0),"height":int(s.get("height") or 0),"duration":float((d.get("format") or {}).get("duration") or 0),"codec":s.get("codec_name") or ""}
 except:return None

def classify(w,h):
 if h>w:return (True,98,"CROP_FILL") if w>=1080 and h>=1920 else (False,0,None)
 if w>=3000 and h>=1680:return True,98,"CROP_FILL"
 if w>=1920 and h>=1080:return True,92,"FIT_BLUR"
 return False,0,None

def crop_filter(cp):
 x="0" if cp=="LEFT" else "iw-ow" if cp=="RIGHT" else "(iw-ow)/2";return f"scale=360:640:force_original_aspect_ratio=increase,crop=360:640:{x}:(ih-oh)/2"
def sample(url,dur,stem,layout,cp="CENTER"):
 p=OUT/f"{stem}_{cp.lower()}.jpg";t=max(.2,min((dur or 3)*.35,max(.2,(dur or 3)-.5)));vf=crop_filter(cp) if layout=="CROP_FILL" else "scale=480:-2";run(["ffmpeg","-hide_banner","-loglevel","error","-y","-ss",f"{t:.3f}","-i",url,"-frames:v","1","-vf",vf,str(p)],75);return p if p.exists() else None

def frame_qc(path):
 if not path:return {"pass":False,"score":0,"reason":"extract_failed"}
 with Image.open(path) as im:
  g=im.convert("L");st=ImageStat.Stat(g);edge=ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0];ent=g.entropy();std=st.stddev[0];mean=st.mean[0]
 try:txt=re.sub(r"\s+"," ",subprocess.run(["tesseract",str(path),"stdout","--psm","11"],text=True,capture_output=True,timeout=20).stdout).strip()
 except:txt=""
 risk=any(x in txt.lower() for x in BAD) or len(re.findall(r"[A-Za-z]{3,}",txt))>=11;blank=(std<10 and ent<3.8) or (edge<3.5 and (mean>238 or mean<15));soft=edge<4.2 and ent<4.6;score=std*.45+ent*7+edge*2;ok=not(risk or blank or soft);return {"pass":ok,"score":round(score,2),"ocr":txt[:160],"reason":"pass" if ok else "text_or_blank_or_soft"}
def best_comp(url,dur,stem,layout):
 cps=("CENTER",) if layout=="FIT_BLUR" else ("LEFT","CENTER","RIGHT");good=[]
 for cp in cps:
  q=frame_qc(sample(url,dur,stem,layout,cp))
  if q["pass"]:good.append((q["score"],cp,q))
 return (max(good,key=lambda x:x[0])[1],max(good,key=lambda x:x[0])[2]) if good else (None,{"pass":False,"score":0,"reason":"all_crops_failed"})

def nasa_search(q):return requests.get("https://images-api.nasa.gov/search",params={"q":q,"media_type":"video","page_size":40},timeout=30).json()["collection"].get("items",[])
def nasa_assets(nid):return [x.get("href","") for x in requests.get("https://images-api.nasa.gov/asset/"+quote(nid,safe=""),timeout=30).json()["collection"].get("items",[])]
def nasa_videos(urls):return sorted([u for u in urls if re.search(r"\.(mp4|mov|m4v)(?:$|\?)",u,re.I)],key=lambda u:5 if "~orig" in u.lower() else 4 if "~large" in u.lower() else 2,reverse=True)
def commons_search(q):
 p={"action":"query","generator":"search","gsrsearch":q,"gsrnamespace":6,"gsrlimit":40,"prop":"imageinfo","iiprop":"url|mime|size|extmetadata","format":"json","formatversion":2};return (requests.get("https://commons.wikimedia.org/w/api.php",params=p,headers={"User-Agent":"KnowledgeNuggetsBot/5.0"},timeout=35).json().get("query") or {}).get("pages",[])
def commons_license(meta):
 lic=((meta.get("LicenseShortName") or {}).get("value") or "");txt=(lic+" "+((meta.get("UsageTerms") or {}).get("value") or "")).lower();return ("public domain" in txt or "cc0" in txt or "pd-usgov" in txt or "pd-nasa" in txt),lic or "Public domain"

def make_candidate(scene,kind,title,desc,url,lic,identity,rank,index):
 sem=semantic_score(scene,text_blob(title,desc,[]))
 if sem<70:return None
 pr=probe(url)
 if not pr or pr["duration"]<1:return None
 ok,qs,layout=classify(pr["width"],pr["height"])
 if not ok:return None
 cp,fq=best_comp(url,pr["duration"],f"{kind}{scene['scene']}_{index}",layout)
 if not cp:return None
 return {"scene":scene["scene"],"spoken_phrase":scene.get("spoken_phrase",""),"source_type":kind,"asset_identity":identity,"title":title,"description_excerpt":clean(desc)[:300],"direct_download_url":url,"source":"NASA Image and Video Library" if kind=="NASA" else "Wikimedia Commons","license":lic,"rights_status":"PASS","media_type":"VIDEO","width":pr["width"],"height":pr["height"],"duration":round(pr["duration"],2),"visual_quality_score":qs,"semantic_score":sem,"layout_mode":layout,"crop_preference":cp,"frame_qc":fq,"search_rank":rank,"status":"CANDIDATE"}

def collect(scene,kind,limit=10):
 out=[];seen=set();queries=list(scene.get("search_queries") or [])+CONCEPTS[int(scene["scene"])]["queries"]
 for q in queries:
  try:items=commons_search(q) if kind=="COMMONS" else nasa_search(q)
  except:continue
  for rank,it in enumerate(items[:30],1):
   if kind=="NASA":
    d=(it.get("data") or [{}])[0];identity=d.get("nasa_id");title=d.get("title") or "";desc=d.get("description") or "";kws=d.get("keywords") or [];semtext=text_blob(title,desc,kws)
    if not identity or identity in seen or semantic_score(scene,semtext)<70:continue
    seen.add(identity)
    try:urls=nasa_videos(nasa_assets(identity))
    except:continue
    for url in urls[:2]:
     c=make_candidate(scene,"NASA",title," ".join([desc," ".join(kws)]),url,"NASA U.S. Government media",identity,rank,len(out))
     if c:out.append(c);break
   else:
    title=it.get("title") or "";identity=title;ii=((it.get("imageinfo") or [{}])[0]);meta=ii.get("extmetadata") or {};desc=clean(((meta.get("ImageDescription") or {}).get("value") or ""));url=ii.get("url") or "";mime=(ii.get("mime") or "").lower();oklic,lic=commons_license(meta)
    if identity in seen or semantic_score(scene,text_blob(title,desc,[]))<70 or not oklic or not mime.startswith("video/") or not re.search(r"\.(webm|mp4)(?:$|\?)",url,re.I):continue
    seen.add(identity);c=make_candidate(scene,"COMMONS",title.replace("File:","",1),desc,url,lic,identity,rank,len(out))
    if c:out.append(c)
   if len(out)>=limit:return out
 return out

pools=[]
for scene in SCENES:
 candidates=collect(scene,"COMMONS",10)
 if len(candidates)<10:candidates+=collect(scene,"NASA",10-len(candidates))
 candidates=list({c["direct_download_url"]:c for c in candidates}.values());candidates.sort(key=lambda c:(-c["semantic_score"],-c["visual_quality_score"],c["search_rank"]));pools.append((scene,candidates))

used_urls=set();used_ids=set();manifest=[]
for scene,candidates in pools:
 selected=None
 for c in candidates:
  if c["direct_download_url"] not in used_urls and c["asset_identity"] not in used_ids:
   selected=dict(c);used_urls.add(c["direct_download_url"]);used_ids.add(c["asset_identity"]);break
 if selected:selected["status"]="SELECTED";manifest.append(selected)
 else:manifest.append({"scene":scene.get("scene"),"spoken_phrase":scene.get("spoken_phrase",""),"status":"NO_EXACT_TOPIC_VIDEO","candidates_found":len(candidates),"required_visual_concept":CONCEPTS.get(int(scene.get("scene") or 0),{})})
selected=[x for x in manifest if x.get("status")=="SELECTED"];unique=len({x.get("direct_download_url") for x in selected});ready=len(selected)==len(SCENES) and unique>=4 and all(x.get("semantic_score",0)>=70 for x in selected)
(OUT/"source_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8");(OUT/"source_gate.json").write_text(json.dumps({"ready":ready,"selected":len(selected),"scenes":len(SCENES),"unique_sources":unique,"minimum_unique_sources":4,"minimum_semantic_score":70,"policy":"TOPIC_FIRST_NO_GENERIC_SPACE_FOOTAGE"},indent=2),encoding="utf-8")
print(json.dumps(manifest))
if not ready:raise SystemExit(f"Topic-first gate failed: {len(selected)}/{len(SCENES)} scenes have exact-topic video; {unique} unique assets.")
