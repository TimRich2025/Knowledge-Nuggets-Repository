import json,re,subprocess,requests
from pathlib import Path
from urllib.parse import quote

OUT=Path('output')
manifest=json.loads((OUT/'source_manifest.json').read_text(encoding='utf-8'))

def family(s):
    s=(s or '').lower()
    s=re.sub(r'(~orig|[-_ ]clean|[-_ ]4k|[-_ ]8k|ultra[-_ ]?hd|uhd|vp9|h264|hevc)',' ',s)
    s=re.sub(r'[^a-z0-9]+',' ',s)
    return ' '.join(s.split())

def source_family(x):
    # Asset IDs are stable across display-title changes and expose Clean/4K variants reliably.
    return family(x.get('asset_identity') or x.get('title') or '')

def probe(url):
    p=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height','-show_entries','format=duration','-of','json',url],text=True,capture_output=True,timeout=55)
    if p.returncode:return None
    try:
        d=json.loads(p.stdout); s=(d.get('streams') or [{}])[0]
        return int(s.get('width') or 0),int(s.get('height') or 0),float((d.get('format') or {}).get('duration') or 0)
    except:return None

def native4k(w,h): return (w>=3840 and h>=2160) or (h>=3840 and w>=2160)
def nasa_search(q): return requests.get('https://images-api.nasa.gov/search',params={'q':q,'media_type':'video','page_size':70},timeout=30).json()['collection'].get('items',[])
def nasa_assets(nid): return [x.get('href','') for x in requests.get('https://images-api.nasa.gov/asset/'+quote(nid,safe=''),timeout=30).json()['collection'].get('items',[])]
def best_video(urls):
    vids=[u for u in urls if re.search(r'\.(mp4|mov|m4v)(?:$|\?)',u,re.I)]
    vids.sort(key=lambda u:(5 if '~orig' in u.lower() else 4 if '~large' in u.lower() else 2),reverse=True)
    return vids[:4]

used=set(); dup=[]
for i,x in enumerate(manifest):
    if x.get('status')!='SELECTED': continue
    f=source_family(x); x['source_family']=f
    if f in used: dup.append(i)
    else: used.add(f)

replacement_queries={3:['astronaut ultrasound human research ISS','astronaut physiology experiment ISS','astronaut medical research space station'],4:['astronaut human research body ISS','astronaut medical assessment spaceflight','astronaut exercise human physiology ISS','astronaut health experiment ISS']}
keywords={3:('ultrasound','human research','physiology','medical','health','experiment','science'),4:('human research','physiology','medical','health','body','exercise','experiment','science')}
context=('astronaut','crew','iss','space station','spaceflight')

for idx in dup:
    old=manifest[idx]; scene=int(old['scene']); found=None
    for q in replacement_queries.get(scene,[]):
        try: items=nasa_search(q)
        except: continue
        for it in items:
            d=(it.get('data') or [{}])[0]; nid=d.get('nasa_id'); title=d.get('title') or ''; desc=d.get('description') or ''; kws=' '.join(d.get('keywords') or [])
            text=(' '.join([title,desc,kws])).lower(); fam=family(nid or title)
            if not nid or fam in used or not any(k in text for k in keywords.get(scene,())) or not any(k in text for k in context): continue
            try: urls=best_video(nasa_assets(nid))
            except: continue
            for url in urls:
                pr=probe(url)
                if not pr or pr[2]<1 or not native4k(pr[0],pr[1]): continue
                found=dict(old); found.update({'source_type':'NASA','asset_identity':nid,'title':title,'description_excerpt':re.sub(r'\s+',' ',desc)[:300],'direct_download_url':url,'source':'NASA Image and Video Library','license':'NASA U.S. Government media','width':pr[0],'height':pr[1],'duration':round(pr[2],2),'native_4k':True,'source_family':fam,'dedupe_replacement':True})
                break
            if found: break
        if found: break
    if found: manifest[idx]=found; used.add(found['source_family'])
    else: old['status']='DUPLICATE_SOURCE_FAMILY_NO_REPLACEMENT'

selected=[x for x in manifest if x.get('status')=='SELECTED']; families={source_family(x) for x in selected}
gate=json.loads((OUT/'source_gate.json').read_text(encoding='utf-8')); gate['unique_source_families']=len(families); gate['minimum_unique_source_families']=4; gate['duplicate_variant_policy']='CLEAN_CODEC_RESOLUTION_VARIANTS_COUNT_AS_ONE_SOURCE'; gate['ready']=len(selected)==len(manifest) and len(families)>=4 and all(x.get('native_4k') for x in selected)
(OUT/'source_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8'); (OUT/'source_gate.json').write_text(json.dumps(gate,indent=2),encoding='utf-8')
print(json.dumps({'ready':gate['ready'],'selected':len(selected),'unique_source_families':len(families),'families':sorted(families)}))
if not gate['ready']: raise SystemExit('Distinct-source-family gate failed')
