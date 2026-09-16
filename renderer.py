import json, subprocess, urllib.request, urllib.error, shlex, time
from pathlib import Path

OUT=Path('output'); MEDIA=Path('media'); MEDIA.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
plan=json.loads((OUT/'fullscreen_plan.json').read_text(encoding='utf-8'))
clips=[]

def run(cmd):
    print('+', ' '.join(shlex.quote(str(x)) for x in cmd)); subprocess.run([str(x) for x in cmd],check=True)

def dl(url,path,max_attempts=5):
    """Download public media with rate-limit aware retries and no poisoned partial files."""
    waits=[8,20,45,75,120]
    last=None
    for attempt in range(1,max_attempts+1):
        tmp=path.with_suffix(path.suffix+'.part')
        if tmp.exists(): tmp.unlink()
        try:
            req=urllib.request.Request(url,headers={
                'User-Agent':'KnowledgeNuggetsBot/1.0 (automated educational video renderer)',
                'Accept':'video/*,application/octet-stream;q=0.9,*/*;q=0.1',
                'Accept-Encoding':'identity',
            })
            with urllib.request.urlopen(req,timeout=120) as r, open(tmp,'wb') as f:
                while True:
                    b=r.read(1024*1024)
                    if not b: break
                    f.write(b)
            if not tmp.exists() or tmp.stat().st_size < 1024*1024:
                raise RuntimeError(f'download too small: {tmp.stat().st_size if tmp.exists() else 0} bytes')
            tmp.replace(path)
            print(f'Downloaded {path.name}: {path.stat().st_size/1024/1024:.1f} MiB',flush=True)
            return
        except urllib.error.HTTPError as e:
            last=e
            retry_after=e.headers.get('Retry-After') if e.headers else None
            if e.code not in (429,500,502,503,504): raise
            delay=int(retry_after) if retry_after and retry_after.isdigit() else waits[min(attempt-1,len(waits)-1)]
            print(f'Download throttled/error HTTP {e.code}; attempt {attempt}/{max_attempts}, waiting {delay}s',flush=True)
        except Exception as e:
            last=e
            delay=waits[min(attempt-1,len(waits)-1)]
            print(f'Download error {type(e).__name__}: {e}; attempt {attempt}/{max_attempts}, waiting {delay}s',flush=True)
        finally:
            if tmp.exists(): tmp.unlink()
        if attempt < max_attempts: time.sleep(delay)
    raise RuntimeError(f'Download failed after {max_attempts} attempts: {url}: {last}')

for i,b in enumerate(plan['beats'],1):
    src=b.get('source') or {}; url=src.get('direct_download_url')
    if not url: raise SystemExit(f'Beat {i}: no source URL')
    ext=Path(urllib.parse.urlparse(url).path).suffix.lower() if hasattr(urllib,'parse') else ''
    raw=MEDIA/f'source_{i}{ext if ext in (".mp4",".mov",".m4v",".webm") else ".mp4"}'
    if not raw.exists(): dl(url,raw)
    dur=float(b['duration']); source_dur=float(src.get('duration') or dur)
    start=max(0.0,min(source_dur-dur-1.0, source_dur*(0.12+0.11*(i-1))))
    cap=' / '.join(b['caption_beats']).replace("'","’").replace(':','\\:')
    out=MEDIA/f'beat_{i}.mp4'
    vf=("scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        "eq=contrast=1.04:saturation=1.04,"
        f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{cap}':"
        "fontcolor=white:fontsize=66:borderw=6:bordercolor=black@0.85:"
        "x=(w-text_w)/2:y=h*0.68")
    run(['ffmpeg','-y','-ss',f'{start:.2f}','-i',raw,'-t',f'{dur:.2f}','-an','-vf',vf,'-r','30','-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p',out])
    clips.append(out)

concat=MEDIA/'concat.txt'; concat.write_text(''.join(f"file '{p.resolve()}'\n" for p in clips),encoding='utf-8')
base=OUT/'KN-ASTRONAUT-V4_FULLSCREEN_SILENT.mp4'
run(['ffmpeg','-y','-f','concat','-safe','0','-i',concat,'-c','copy',base])
total=sum(float(b['duration']) for b in plan['beats'])
final=OUT/'KN-ASTRONAUT-V4_FULLSCREEN_PREVIEW.mp4'
run(['ffmpeg','-y','-i',base,'-f','lavfi','-i',f'sine=frequency=110:sample_rate=48000:duration={total}', '-filter_complex','[1:a]volume=0.018,highpass=f=70,lowpass=f=420[a]','-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','160k','-shortest',final])
print(json.dumps({'rendered':True,'preview':str(final),'beats':len(clips),'duration':total}))
