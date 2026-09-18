import json, subprocess, urllib.request, urllib.error, urllib.parse, shlex, time, hashlib
from pathlib import Path
from layout_lock import build_header, VIDEO_H, VIDEO_Y, QUESTION_FONT

OUT=Path('output'); MEDIA=Path('media'); MEDIA.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
plan=json.loads((OUT/'fullscreen_plan.json').read_text(encoding='utf-8')); clips=[]
SUB_FONT=QUESTION_FONT

def run(cmd):
    print('+', ' '.join(shlex.quote(str(x)) for x in cmd), flush=True)
    subprocess.run([str(x) for x in cmd],check=True)

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
            if not tmp.exists() or tmp.stat().st_size < 1024*1024:
                raise RuntimeError('download too small')
            tmp.replace(path); return
        except urllib.error.HTTPError as e:
            last=e
            if e.code not in (429,500,502,503,504): raise
            ra=e.headers.get('Retry-After') if e.headers else None
            delay=min(120,int(ra)) if ra and ra.isdigit() else waits[min(attempt-1,4)]
        except Exception as e:
            last=e; delay=waits[min(attempt-1,4)]
        finally:
            if tmp.exists(): tmp.unlink()
        if attempt < max_attempts: time.sleep(delay)
    raise RuntimeError(f'Download failed: {url}: {last}')

def esc(s):
    return str(s).replace('\\','\\\\').replace("'","’").replace(':','\\:').replace('%','\\%')

def caption_filters(cards,dur):
    fs=[]; n=max(1,len(cards)); slot=dur/n
    for j,card in enumerate(cards):
        text=str(card).strip().upper(); a=j*slot; z=min(dur,(j+1)*slot+0.06)
        size=68 if len(text)<=13 else 58
        fs.append(
            f"drawtext=fontfile={SUB_FONT}:text='{esc(text)}':fontcolor=white:fontsize={size}:"
            f"borderw=6:bordercolor=black@0.95:x=(w-text_w)/2:y={VIDEO_Y + VIDEO_H/2:.1f}-text_h/2:"
            f"enable='between(t,{a:.2f},{z:.2f})'"
        )
    return fs

# Fixed shell. No AI may regenerate, move or restyle the brand elements.
question_lines=plan.get('core_question_lines') or ['WHY DO ASTRONAUTS','GROW TALLER?']
header=MEDIA/'kn_locked_header.png'
build_header(question_lines,header)

for i,b in enumerate(plan['beats'],1):
    src=b.get('source') or {}; url=src.get('direct_download_url')
    if not url: raise SystemExit(f'Beat {i}: no source URL')
    candidates=[url]+[u for u in (src.get('backup_download_urls') or []) if u and u!=url]
    key=hashlib.sha1(safe_url(url).encode()).hexdigest()[:12]
    ext=Path(urllib.parse.urlparse(safe_url(url)).path).suffix.lower()
    raw=MEDIA/f'source_{key}{ext if ext in (".mp4",".mov",".m4v",".webm") else ".mp4"}'
    if not raw.exists():
        errors=[]
        for candidate in candidates:
            try:
                dl(candidate,raw,max_attempts=3)
                break
            except Exception as e:
                errors.append(str(e))
        if not raw.exists():
            raise RuntimeError(f'Beat {i}: all source encodes failed: {errors}')
    dur=float(b['duration']); source_dur=float(src.get('duration') or dur)
    # Temporary fallback only. A later semantic shot-selector can supply source_start.
    start=float(b['source_start']) if b.get('source_start') is not None else max(0.0,min(source_dur-dur-1.0,source_dur*(0.12+0.11*(i-1))))
    out=MEDIA/f'beat_{i}.mp4'
    captions=','.join(caption_filters(b['caption_beats'],dur))
    fc=(f"[0:v]scale=1080:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop=1080:{VIDEO_H},eq=contrast=1.03:saturation=1.03,"
        f"pad=1080:1920:0:{VIDEO_Y}:color=black[base];"
        f"[base][1:v]overlay=0:0[locked];"
        f"[locked]{captions}[v]")
    run(['ffmpeg','-y','-ss',f'{start:.2f}','-i',raw,'-loop','1','-i',header,'-t',f'{dur:.2f}',
         '-filter_complex',fc,'-map','[v]','-an','-r','30','-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p',out])
    clips.append(out)

concat=MEDIA/'concat.txt'
concat.write_text(''.join(f"file '{p.resolve()}'\n" for p in clips),encoding='utf-8')
base=OUT/'KN-ASTRONAUT-V4_LAYOUT_LOCKED_SILENT.mp4'
run(['ffmpeg','-y','-f','concat','-safe','0','-i',concat,'-c','copy',base])
total=sum(float(b['duration']) for b in plan['beats'])
final=OUT/'KN-ASTRONAUT-V4_LAYOUT_LOCKED_PREVIEW.mp4'
script=' '.join(str(b.get('voice') or b.get('narration') or '') for b in plan['beats']).strip()
voice=MEDIA/'temp_voice.wav'
if not script:
    raise RuntimeError('Fullscreen plan contains no narration/voice text; refusing silent preview')
run(['espeak-ng','-v','en-us','-s','158','-p','42','-w',voice,script])
run(['ffmpeg','-y','-i',base,'-i',voice,'-f','lavfi','-i',f'sine=frequency=90:sample_rate=48000:duration={total}',
     '-filter_complex','[1:a]volume=1.25,highpass=f=80,lowpass=f=9000[v];[2:a]volume=0.010,lowpass=f=300[bed];[v][bed]amix=inputs=2:duration=longest:normalize=0[a]',
     '-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k','-shortest',final])
print(json.dumps({'rendered':True,'preview':str(final),'beats':len(clips),'duration':total,'layout_lock':'KN_LAYOUT_V1'}))
