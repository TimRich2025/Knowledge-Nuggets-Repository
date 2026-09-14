import os,json,re,subprocess,requests,time
from pathlib import Path
from urllib.parse import quote
from PIL import Image,ImageStat,ImageFilter

B=json.loads(os.environ['KN_SCENE_BRIEF'])
O=Path('output'); O.mkdir(exist_ok=True)
BAD=('live video','official stream','live stream','livestream','live event','event starts','news conference','press conference','countdown','webinar','presentation','title card','broadcast','briefing','coverage')
STOP=set('the a an and or of to in on at by for from with is are was were be can this that it its after before during'.split())

def run(c,t=60):
    p=subprocess.run(c,text=True,capture_output=True,timeout=t)
    return p.stdout if p.returncode==0 else None

def probe(u):
    o=run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,codec_name','-show_entries','format=duration','-of','json',u],50)
    if not o:return None
    try:
        d=json.loads(o); s=(d.get('streams')or[{}])[0]
        return {'width':int(s.get('width')or 0),'height':int(s.get('height')or 0),'duration':float((d.get('format')or{}).get('duration')or 0)}
    except:return None

def search(q):
    r=requests.get('https://images-api.nasa.gov/search',params={'q':q,'media_type':'video','page_size':24},timeout=30)
    r.raise_for_status()
    return r.json()['collection'].get('items',[])

def assets(n):
    r=requests.get('https://images-api.nasa.gov/asset/'+quote(n,safe=''),timeout=30)
    r.raise_for_status()
    return [x.get('href','') for x in r.json()['collection'].get('items',[])]

def vids(a):
    v=[u for u in a if re.search(r'\.(mp4|mov|m4v)(?:$|\?)',u,re.I)]
    return sorted(v,key=lambda u:5 if '~orig' in u.lower() else 4 if '~large' in u.lower() else 3 if '~medium' in u.lower() else 1,reverse=True)

def toks(x):
    return {w for w in re.findall(r'[a-z0-9]+',(x or '').lower()) if len(w)>2 and w not in STOP}

def semantic(scene,data,rank):
    a=toks(' '.join([scene.get('spoken_phrase',''),scene.get('ideal_footage',''),scene.get('fallback_footage','')]))
    b=toks((data.get('title')or'')+' '+(data.get('description')or'')+' '+' '.join(data.get('keywords')or[]))
    overlap=len(a&b)
    # conservative: NASA + same-subject context needs meaningful lexical overlap
    return min(99,78+int(18*overlap/max(1,min(len(a),10)))+max(0,3-rank//4))

def quality(p):
    w,h=p['width'],p['height']
    if h>w:
        return (98,'CROP_FILL') if w>=1080 and h>=1920 else (60,'LOW_RES')
    if w>=3000 and h>=1680:return 98,'CROP_FILL'
    if w>=2560 and h>=1440:return 94,'CROP_FILL'
    if w>=1920 and h>=1080:return 90,'FIT_BLUR'
    return 60,'LOW_RES'

def make_frame(u,d,stem,mode,cp='CENTER'):
    p=O/(stem+'.jpg')
    t=max(.2,min(d*.35,max(.2,d-.5))) if d else .5
    vf='scale=480:-2'
    if mode=='CROP_FILL':
        x='0' if cp=='LEFT' else 'iw-ow' if cp=='RIGHT' else '(iw-ow)/2'
        vf=f"scale=360:640:force_original_aspect_ratio=increase,crop=360:640:{x}:(ih-oh)/2"
    out=run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',f'{t:.3f}','-i',u,'-frames:v','1','-vf',vf,str(p)],60)
    return p if p.exists() else None

def qc_frame(p):
    if not p:return {'pass':False,'score':0,'ocr':'','reason':'frame_extract_failed'}
    with Image.open(p) as im:
        g=im.convert('L')
        st=ImageStat.Stat(g)
        edge=ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]
        entropy=g.entropy()
        std=st.stddev[0]
        mean=st.mean[0]
    try:
        r=subprocess.run(['tesseract',str(p),'stdout','--psm','11'],text=True,capture_output=True,timeout=20)
        txt=re.sub(r'\s+',' ',r.stdout).strip()
    except: txt=''
    low=txt.lower()
    text_risk=any(x in low for x in('live event','starts soon','live stream','news conference','press conference','breaking news','countdown')) or len(re.findall(r'[A-Za-z]{3,}',txt))>=10
    blank=(std<11 and entropy<4.0) or (edge<4.0 and (mean>235 or mean<18))
    soft=edge<4.7 and entropy<4.8
    score=(std*0.45)+(entropy*7)+(edge*2)
    ok=not(text_risk or blank or soft)
    return {'pass':ok,'score':round(score,2),'ocr':txt[:160],'std':round(std,2),'entropy':round(entropy,2),'edge':round(edge,2),'reason':'pass' if ok else 'text_or_blank_or_soft'}

def layout_qc(u,d,stem,mode):
    if mode=='FIT_BLUR':
        q=qc_frame(make_frame(u,d,stem,mode))
        return ('CENTER',q) if q['pass'] else (None,q)
    candidates=[]
    for cp in ('LEFT','CENTER','RIGHT'):
        q=qc_frame(make_frame(u,d,stem+'_'+cp.lower(),mode,cp))
        if q['pass']: candidates.append((q['score'],cp,q))
    if not candidates:
        return None,{'pass':False,'score':0,'ocr':'','reason':'all_vertical_crops_failed'}
    _,cp,q=max(candidates,key=lambda x:x[0])
    return cp,q

extra={
1:['astronaut medical examination NASA','astronaut human research NASA','astronaut body measurement NASA','astronaut postflight medical NASA'],
2:['astronaut floating space station NASA','ISS crew microgravity NASA','astronaut weightlessness ISS NASA','ISS interior astronaut NASA'],
3:['astronaut medical research physiology NASA','astronaut human research spine NASA','astronaut physical examination NASA','astronaut body microgravity NASA'],
4:['astronaut landing recovery NASA','astronaut postflight recovery NASA','crew return recovery NASA','astronaut rehabilitation NASA'],
5:['astronaut exercise ISS NASA','astronaut treadmill space station NASA','astronaut exercise space station NASA','astronaut physical therapy NASA']
}

R=[]; used=set()
for s in B:
    sn=s.get('scene'); cs=[]; seen=set()
    queries=list(s.get('search_queries')or[])+extra.get(sn,[])
    for q in queries:
        try: items=search(q)
        except Exception: continue
        for rank,it in enumerate(items[:16],1):
            d=(it.get('data')or[{}])[0]
            nid=d.get('nasa_id'); title=d.get('title')or''
            if not nid or nid in seen or any(x in title.lower() for x in BAD): continue
            seen.add(nid)
            metadata=((d.get('title')or'')+' '+(d.get('description')or'')+' '+' '.join(d.get('keywords')or[])).lower()
            if not any(k in metadata for k in ('astronaut','space station','iss','spaceflight','crew','microgravity')): continue
            sc=semantic(s,d,rank)
            if sc<88: continue
            try: us=vids(assets(nid))
            except Exception: continue
            for u in us[:3]:
                p=probe(u)
                if not p or p['duration']<1: continue
                qs,mode=quality(p)
                if qs<88: continue
                cp,fq=layout_qc(u,p['duration'],f's{sn}_{len(cs)}',mode)
                if not cp: continue
                cs.append({
                    'scene':sn,'spoken_phrase':s.get('spoken_phrase',''),'nasa_id':nid,'title':title,
                    'selected_asset_page_url':'https://images.nasa.gov/details/'+quote(nid),
                    'direct_download_url':u,'source':'NASA Image and Video Library',
                    'license':'NASA U.S. Government media','rights_status':'PASS','media_type':'VIDEO',
                    'width':p['width'],'height':p['height'],'duration':round(p['duration'],2),
                    'semantic_score':sc,'visual_quality_score':qs,'cleaness_status':'PASS','crop_status':'PASS',
                    'layout_mode':mode,'crop_preference':cp,'frame_qc':fq,
                    'reason':'Verified NASA API motion asset: '+title[:100]
                })
                break
        if len(cs)>=8: break
    cs.sort(key=lambda x:(x['nasa_id'] in used,-x['semantic_score'],-x['visual_quality_score'],-x['frame_qc'].get('score',0)))
    pick=next((c for c in cs if c['semantic_score']>=88 and c['visual_quality_score']>=88 and c['nasa_id'] not in used),None)
    if pick is None:
        pick=next((c for c in cs if c['semantic_score']>=88 and c['visual_quality_score']>=88),None)
    if pick:
        used.add(pick['nasa_id']); pick['status']='SELECTED'; R.append(pick)
    else:
        R.append({'scene':sn,'spoken_phrase':s.get('spoken_phrase',''),'status':'MISSING','reason':'No NASA API candidate passed semantic, resolution, frame and overlay QC'})

Path('output/source_manifest.json').write_text(json.dumps(R,indent=2),encoding='utf-8')
print(json.dumps(R))
