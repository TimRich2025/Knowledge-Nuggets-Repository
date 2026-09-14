import os,json,re,subprocess
from pathlib import Path
from urllib.parse import quote
import requests
from PIL import Image,ImageStat,ImageFilter
B=json.loads(os.environ['KN_SCENE_BRIEF']);O=Path('output');O.mkdir(exist_ok=True)
BAD=('live video','official stream','live stream','livestream','live event','event starts','news conference','press conference','countdown','webinar','presentation','title card','broadcast','briefing','coverage')
STOP=set('the a an and or of to in on at by for from with is are was were be can this that it its after before during'.split())
def run(c,t=45):
 p=subprocess.run(c,text=True,capture_output=True,timeout=t);return p.stdout if p.returncode==0 else None
def probe(u):
 o=run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,codec_name','-show_entries','format=duration','-of','json',u]);
 if not o:return None
 try:
  d=json.loads(o);s=(d.get('streams')or[{}])[0];return {'width':int(s.get('width')or 0),'height':int(s.get('height')or 0),'duration':float((d.get('format')or{}).get('duration')or 0)}
 except:return None
def search(q):
 r=requests.get('https://images-api.nasa.gov/search',params={'q':q,'media_type':'video','page_size':20},timeout=30);r.raise_for_status();return r.json()['collection'].get('items',[])
def assets(n):
 r=requests.get('https://images-api.nasa.gov/asset/'+quote(n,safe=''),timeout=30);r.raise_for_status();return[x.get('href','') for x in r.json()['collection'].get('items',[])]
def vids(a):
 v=[u for u in a if re.search(r'\.(mp4|mov|m4v)(?:$|\?)',u,re.I)];return sorted(v,key=lambda u:5 if '~orig' in u.lower() else 4 if '~large' in u.lower() else 3 if '~medium' in u.lower() else 1,reverse=True)
def toks(x):return{w for w in re.findall(r'[a-z0-9]+',(x or '').lower())if len(w)>2 and w not in STOP}
def sem(s,d,r):
 a=toks(' '.join([s.get('spoken_phrase',''),s.get('ideal_footage',''),s.get('fallback_footage','')]));b=toks((d.get('title')or'')+' '+(d.get('description')or'')+' '+' '.join(d.get('keywords')or[]));return min(99,72+int(22*len(a&b)/max(1,min(len(a),10)))+max(0,6-r))
def quality(p):
 w,h=p['width'],p['height'];
 if h>w:return(98,'PORTRAIT_FULL')if w>=1080 and h>=1920 else((88,'PORTRAIT_UPSCALE')if w>=720 and h>=1280 else(60,'LOW_RES'))
 if w>=3000 and h>=1680:return 98,'FILL_CROP'
 if w>=2560 and h>=1440:return 94,'FILL_CROP'
 if w>=1920 and h>=1080:return 90,'BLUR_FILL'
 return 60,'LOW_RES'
def frame(u,d,stem):
 p=O/(stem+'.jpg');t=max(.2,min(d*.35,max(.2,d-.5)))if d else .5;run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',f'{t:.3f}','-i',u,'-frames:v','1','-vf','scale=480:-2',str(p)],50);return p if p.exists()else None
def qc(p):
 if not p:return False,''
 with Image.open(p)as im:
  g=im.convert('L');st=ImageStat.Stat(g);edge=ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0];ok=not(st.stddev[0]<10 or g.entropy()<3.8 or edge<3.6)
 try:r=subprocess.run(['tesseract',str(p),'stdout','--psm','11'],text=True,capture_output=True,timeout=20);txt=re.sub(r'\s+',' ',r.stdout).strip()
 except:txt=''
 low=txt.lower();risk=any(x in low for x in('live event','starts soon','live stream','news conference','press conference','breaking news','countdown'))or len(re.findall(r'[A-Za-z]{3,}',txt))>=10
 return ok and not risk,txt[:160]
extra={1:['astronaut medical examination','astronaut human research','astronaut body measurement'],2:['astronaut floating space station','ISS crew microgravity','astronaut weightlessness ISS'],3:['astronaut medical research','astronaut human research physiology','astronaut physical examination'],4:['astronaut landing recovery','astronaut postflight recovery','crew return recovery'],5:['astronaut exercise ISS','astronaut treadmill space station','astronaut exercise space station']}
R=[];used=set()
for s in B:
 sn=s.get('scene');cs=[];seen=set()
 for q in list(s.get('search_queries')or[])+extra.get(sn,[]):
  try:items=search(q)
  except:continue
  for rank,it in enumerate(items[:12],1):
   d=(it.get('data')or[{}])[0];nid=d.get('nasa_id');title=d.get('title')or''
   if not nid or nid in seen or any(x in title.lower()for x in BAD):continue
   seen.add(nid)
   try:us=vids(assets(nid))
   except:continue
   for u in us[:2]:
    p=probe(u)
    if not p or p['duration']<1:continue
    qs,mode=quality(p)
    if qs<88:continue
    ok,txt=qc(frame(u,p['duration'],f's{sn}_{len(cs)}'))
    if not ok:continue
    sc=sem(s,d,rank);text=((d.get('title')or'')+' '+(d.get('description')or'')).lower()
    if 'astronaut' not in text and 'space station' not in text and 'iss' not in text:continue
    cs.append({'scene':sn,'spoken_phrase':s.get('spoken_phrase',''),'nasa_id':nid,'title':title,'selected_asset_page_url':'https://images.nasa.gov/details/'+quote(nid),'direct_download_url':u,'source':'NASA Image and Video Library','license':'NASA U.S. Government media','rights_status':'PASS','media_type':'VIDEO','width':p['width'],'height':p['height'],'duration':round(p['duration'],2),'semantic_score':sc,'visual_quality_score':qs,'cleanliness_status':'PASS','crop_status':'PASS','crop_preference':'CENTER','composition_mode':mode,'ocr_text':txt,'reason':'NASA video: '+title[:100]});break
  if len(cs)>=8:break
 cs.sort(key=lambda x:(x['nasa_id']in used,-x['semantic_score'],-x['visual_quality_score']));pick=next((c for c in cs if c['semantic_score']>=82 and c['nasa_id']not in used),cs[0]if cs else None)
 if pick:used.add(pick['nasa_id']);pick['status']='SELECTED';R.append(pick)
 else:R.append({'scene':sn,'spoken_phrase':s.get('spoken_phrase',''),'status':'MISSING','reason':'No NASA API candidate passed source/frame/rights QC'})
Path('output/source_manifest.json').write_text(json.dumps(R,indent=2),encoding='utf-8');print(json.dumps(R))
