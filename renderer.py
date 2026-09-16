import json, subprocess, urllib.request, urllib.error, urllib.parse, shlex, time
from pathlib import Path

OUT=Path('output'); MEDIA=Path('media'); MEDIA.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
plan=json.loads((OUT/'fullscreen_plan.json').read_text(encoding='utf-8')); clips=[]
FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
ORANGE='0xFF7A18'

def run(cmd):
    print('+', ' '.join(shlex.quote(str(x)) for x in cmd)); subprocess.run([str(x) for x in cmd],check=True)

def safe_url(url):
    p=urllib.parse.urlsplit(str(url).replace('http://images-assets.nasa.gov','https://images-assets.nasa.gov'))
    path=urllib.parse.quote(urllib.parse.unquote(p.path),safe='/%:@~!$&()*+,;=-._')
    query=urllib.parse.quote(urllib.parse.unquote(p.query),safe='=&;%:+,/?@~!$()*-._')
    return urllib.parse.urlunsplit((p.scheme,p.netloc.encode('idna').decode('ascii'),path,query,p.fragment))

def dl(url,path,max_attempts=5):
    url=safe_url(url); waits=[8,20,45,75,120]; last=None
    for attempt in range(1,max_attempts+1):
        tmp=path.with_suffix(path.suffix+'.part')
        if tmp.exists(): tmp.unlink()
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'KnowledgeNuggetsBot/1.0','Accept':'video/*,application/octet-stream;q=0.9,*/*;q=0.1','Accept-Encoding':'identity'})
            with urllib.request.urlopen(req,timeout=120) as r, open(tmp,'wb') as f:
                while True:
                    b=r.read(1024*1024)
                    if not b: break
                    f.write(b)
            if not tmp.exists() or tmp.stat().st_size < 1024*1024: raise RuntimeError('download too small')
            tmp.replace(path); return
        except urllib.error.HTTPError as e:
            last=e
            if e.code not in (429,500,502,503,504): raise
            ra=e.headers.get('Retry-After') if e.headers else None; delay=min(120,int(ra)) if ra and ra.isdigit() else waits[min(attempt-1,4)]
        except Exception as e:
            last=e; delay=waits[min(attempt-1,4)]
        finally:
            if tmp.exists(): tmp.unlink()
        if attempt < max_attempts: time.sleep(delay)
    raise RuntimeError(f'Download failed: {url}: {last}')

def esc(s): return str(s).replace('\\','\\\\').replace("'","’").replace(':','\\:').replace('%','\\%')

def caption_filters(cards,dur,scene):
    fs=[]; n=max(1,len(cards)); slot=dur/n
    for j,card in enumerate(cards):
        a=j*slot; z=min(dur,(j+1)*slot+0.08)
        size=82 if len(card)<=12 else 68
        col=ORANGE if ('3%' in card or card in ('GRAVITY','PRESSURE','STRETCHES','TALLER')) else 'white'
        fs.append(f"drawtext=fontfile={FONT}:text='{esc(card)}':fontcolor={col}:fontsize={size}:borderw=7:bordercolor=black@0.82:x=(w-text_w)/2:y=h*0.70:enable='between(t,{a:.2f},{z:.2f})'")
    # Minimal explanatory graphics, intentionally restrained.
    if scene in (2,3):
        fs += ["drawbox=x=w*0.47:y=h*0.30:w=10:h=h*0.25:color=0xFF7A18@0.85:t=fill",
               "drawbox=x=w*0.40:y=h*0.40:w=w*0.20:h=8:color=white@0.75:t=fill"]
    if scene==5:
        fs += ["drawbox=x=w*0.15:y=h*0.22:w=8:h=h*0.42:color=0xFF7A18@0.9:t=fill",
               "drawbox=x=w*0.13:y=h*0.22:w=50:h=7:color=white@0.9:t=fill",
               "drawbox=x=w*0.13:y=h*0.64:w=50:h=7:color=white@0.9:t=fill"]
    if scene==6:
        fs += ["drawbox=x=w*0.15:y=h*0.28:w=8:h=h*0.30:color=0xFF7A18@0.85:t=fill"]
    return fs

for i,b in enumerate(plan['beats'],1):
    src=b.get('source') or {}; url=src.get('direct_download_url')
    if not url: raise SystemExit(f'Beat {i}: no source URL')
    ext=Path(urllib.parse.urlparse(safe_url(url)).path).suffix.lower(); raw=MEDIA/f'source_{i}{ext if ext in (".mp4",".mov",".m4v",".webm") else ".mp4"}'
    if not raw.exists(): dl(url,raw)
    dur=float(b['duration']); source_dur=float(src.get('duration') or dur)
    start=max(0.0,min(source_dur-dur-1.0, source_dur*(0.12+0.11*(i-1))))
    out=MEDIA/f'beat_{i}.mp4'
    vf=['scale=1080:1920:force_original_aspect_ratio=increase','crop=1080:1920','eq=contrast=1.04:saturation=1.04']
    vf += caption_filters(b['caption_beats'],dur,i)
    run(['ffmpeg','-y','-ss',f'{start:.2f}','-i',raw,'-t',f'{dur:.2f}','-an','-vf',','.join(vf),'-r','30','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',out]); clips.append(out)

concat=MEDIA/'concat.txt'; concat.write_text(''.join(f"file '{p.resolve()}'\n" for p in clips),encoding='utf-8')
base=OUT/'KN-ASTRONAUT-V4_FULLSCREEN_SILENT.mp4'; run(['ffmpeg','-y','-f','concat','-safe','0','-i',concat,'-c','copy',base])
total=sum(float(b['duration']) for b in plan['beats']); final=OUT/'KN-ASTRONAUT-V4_FULLSCREEN_PREVIEW.mp4'
script=' '.join(str(b.get('narration','')) for b in plan['beats']).strip()
voice=MEDIA/'temp_voice.wav'
if script:
    run(['espeak-ng','-v','en-us','-s','158','-p','42','-w',voice,script])
    run(['ffmpeg','-y','-i',base,'-i',voice,'-f','lavfi','-i',f'sine=frequency=90:sample_rate=48000:duration={total}', '-filter_complex','[1:a]volume=1.25,highpass=f=80,lowpass=f=9000[v];[2:a]volume=0.010,lowpass=f=300[bed];[v][bed]amix=inputs=2:duration=longest:normalize=0[a]','-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k','-shortest',final])
else:
    run(['ffmpeg','-y','-i',base,'-c','copy',final])
print(json.dumps({'rendered':True,'preview':str(final),'beats':len(clips),'duration':total,'temp_voice':bool(script)}))
