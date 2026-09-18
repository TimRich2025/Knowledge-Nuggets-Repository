from __future__ import annotations
import argparse, json, shutil, subprocess, tempfile
from pathlib import Path
from .local_renderer import render_job

def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--iterations',type=int,default=50); args=ap.parse_args()
    root=Path(tempfile.mkdtemp(prefix='kn-stress-'))
    try:
        a=root/'a.mp4'; b=root/'b.mp4'; voice=root/'voice.m4a'
        run(['ffmpeg','-y','-f','lavfi','-i','testsrc2=size=1920x1080:rate=30','-t','10','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(a)])
        run(['ffmpeg','-y','-f','lavfi','-i','smptebars=size=1920x1080:rate=30','-t','10','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',str(b)])
        run(['ffmpeg','-y','-f','lavfi','-i','sine=frequency=440:sample_rate=44100','-t','18','-c:a','aac',str(voice)])
        job={'content_id':'STRESS','production_status':'READY','core_question_lines':['WHY DO ASTRONAUTS','GROW TALLER?'],'scenes':[
            {'duration':9,'layout_mode':'CROP_FILL','caption_beats':['WHY DO','ASTRONAUTS','GROW TALLER?'],'validated_frame_time':4},
            {'duration':9,'layout_mode':'FIT_BLUR','caption_beats':['GRAVITY','CHANGES','THE SPINE'],'validated_frame_time':4}]}
        ing={'audio':{'path':str(voice)},'scenes':[{**job['scenes'][0],'local_path':str(a)},{**job['scenes'][1],'local_path':str(b)}]}
        results=[]
        for i in range(1,args.iterations+1):
            out=root/f'run-{i:03d}'; out.mkdir()
            result=render_job(job,ing,out); results.append(result)
            print(f'{i}/{args.iterations} OK mae={result["layout_header_mae"]}',flush=True)
        print(json.dumps({'iterations':args.iterations,'successes':len(results),'failures':0,'max_header_mae':max(x['layout_header_mae'] for x in results)},indent=2))
    finally:
        shutil.rmtree(root,ignore_errors=True)

if __name__=='__main__': main()
