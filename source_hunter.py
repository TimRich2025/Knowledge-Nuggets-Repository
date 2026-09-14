import os, json, re, subprocess, requests, time, html
from pathlib import Path
from urllib.parse import quote
from PIL import Image, ImageStat, ImageFilter

SCENES = json.loads(os.environ["KN_SCENE_BRIEF"])
OUT = Path("output")
OUT.mkdir(exist_ok=True)

BAD_TITLE = (
    "live video","official stream","live stream","livestream","live event","event starts",
    "news conference","press conference","countdown","webinar","presentation","title card",
    "broadcast","briefing","coverage","podcast","audio only"
)
SPACE_TERMS = ("astronaut","space station","iss","microgravity","spaceflight","crew","nasa","orbit")
NASA_EXTRA = {
    1: ["astronaut body measurement", "astronaut medical examination", "postflight medical astronaut", "human research astronaut measurement"],
    2: ["astronaut floating ISS", "astronaut microgravity ISS", "astronaut weightless space station", "ISS interior crew floating"],
    3: ["astronaut human research physiology", "astronaut ultrasound ISS", "astronaut bone muscle research ISS", "astronaut medical assessment ISS"],
    4: ["astronaut landing recovery", "astronaut postflight recovery", "crew return recovery", "astronaut medical after landing"],
    5: ["astronaut treadmill ISS", "astronaut exercise space station", "astronaut resistance exercise ISS", "astronaut rehabilitation after landing"],
}
COMMONS_EXTRA = {
    1: ["astronaut medical examination video", "astronaut body measurement video", "astronaut postflight recovery video"],
    2: ["astronaut floating ISS video", "astronaut microgravity space station video", "ISS interior astronaut video"],
    3: ["astronaut medical research video", "astronaut ultrasound ISS video", "astronaut physiology ISS video"],
    4: ["astronaut landing recovery video", "astronaut postflight recovery video", "Soyuz astronaut recovery video"],
    5: ["astronaut exercise ISS video", "astronaut treadmill ISS video", "astronaut resistance exercise space station video"],
}

def run(cmd, timeout=60):
    p = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    return p.stdout if p.returncode == 0 else None

def strip_html(s):
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def probe(url):
    o = run([
        "ffprobe","-v","error","-select_streams","v:0",
        "-show_entries","stream=width,height,codec_name",
        "-show_entries","format=duration","-of","json",url
    ], 55)
    if not o:
        return None
    try:
        d = json.loads(o)
        s = (d.get("streams") or [{}])[0]
        return {
            "width": int(s.get("width") or 0),
            "height": int(s.get("height") or 0),
            "duration": float((d.get("format") or {}).get("duration") or 0),
            "codec": s.get("codec_name") or "",
        }
    except Exception:
        return None

def quality_ok(w, h):
    if h > w:
        return (w >= 1080 and h >= 1920, 98 if w >= 1080 and h >= 1920 else 0)
    # hard rule: landscape must be UHD-class enough for a true 9:16 crop without destructive upscaling
    if h >= 1920 and w >= 3000:
        return True, 98
    return False, 0

def crop_filter(cp):
    x = "0" if cp == "LEFT" else "iw-ow" if cp == "RIGHT" else "(iw-ow)/2"
    return f"scale=360:640:force_original_aspect_ratio=increase,crop=360:640:{x}:(ih-oh)/2"

def sample_frame(url, duration, stem, cp):
    p = OUT / f"{stem}_{cp.lower()}.jpg"
    t = max(.2, min((duration or 3) * .35, max(.2, (duration or 3) - .5)))
    out = run([
        "ffmpeg","-hide_banner","-loglevel","error","-y","-ss",f"{t:.3f}",
        "-i",url,"-frames:v","1","-vf",crop_filter(cp),str(p)
    ], 70)
    return p if p.exists() else None

def frame_qc(path):
    if not path:
        return {"pass": False, "score": 0, "ocr": "", "reason": "frame_extract_failed"}
    with Image.open(path) as im:
        g = im.convert("L")
        st = ImageStat.Stat(g)
        edge = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]
        entropy = g.entropy()
        std = st.stddev[0]
        mean = st.mean[0]
    try:
        r = subprocess.run(["tesseract",str(path),"stdout","--psm","11"], text=True, capture_output=True, timeout=20)
        txt = re.sub(r"\s+"," ",r.stdout).strip()
    except Exception:
        txt = ""
    low = txt.lower()
    text_risk = any(x in low for x in (
        "live event","starts soon","live stream","news conference","press conference",
        "breaking news","countdown","presentation"
    )) or len(re.findall(r"[A-Za-z]{3,}", txt)) >= 10
    blank = (std < 11 and entropy < 4.0) or (edge < 4.0 and (mean > 235 or mean < 18))
    soft = edge < 4.7 and entropy < 4.8
    score = std*.45 + entropy*7 + edge*2
    ok = not (text_risk or blank or soft)
    return {
        "pass": ok, "score": round(score,2), "ocr": txt[:160], "std": round(std,2),
        "entropy": round(entropy,2), "edge": round(edge,2),
        "reason": "pass" if ok else "text_or_blank_or_soft"
    }

def best_crop(url, duration, stem):
    good = []
    for cp in ("LEFT","CENTER","RIGHT"):
        q = frame_qc(sample_frame(url,duration,stem,cp))
        if q["pass"]:
            good.append((q["score"], cp, q))
    if not good:
        return None, {"pass":False,"score":0,"ocr":"","reason":"all_vertical_crops_failed"}
    _, cp, q = max(good, key=lambda x:x[0])
    return cp, q

def nasa_search(q):
    r = requests.get("https://images-api.nasa.gov/search", params={"q":q,"media_type":"video","page_size":20}, timeout=30)
    r.raise_for_status()
    return r.json()["collection"].get("items", [])

def nasa_assets(nasa_id):
    r = requests.get("https://images-api.nasa.gov/asset/" + quote(nasa_id, safe=""), timeout=30)
    r.raise_for_status()
    return [x.get("href","") for x in r.json()["collection"].get("items", [])]

def nasa_videos(urls):
    vs = [u for u in urls if re.search(r"\.(mp4|mov|m4v)(?:$|\?)",u,re.I)]
    return sorted(vs, key=lambda u: 5 if "~orig" in u.lower() else 4 if "~large" in u.lower() else 2, reverse=True)

def commons_search(q):
    params = {
        "action":"query","generator":"search","gsrsearch":q,"gsrnamespace":6,"gsrlimit":20,
        "prop":"imageinfo","iiprop":"url|mime|size|extmetadata","format":"json","formatversion":2
    }
    r = requests.get("https://commons.wikimedia.org/w/api.php", params=params,
                     headers={"User-Agent":"KnowledgeNuggetsBot/3.0"}, timeout=35)
    r.raise_for_status()
    return (r.json().get("query") or {}).get("pages", [])

def commons_license_ok(meta):
    lic = ((meta.get("LicenseShortName") or {}).get("value") or "")
    terms = ((meta.get("UsageTerms") or {}).get("value") or "")
    txt = (lic + " " + terms).lower()
    allowed = ("public domain" in txt or "cc0" in txt or "pd-usgov" in txt or "pd-nasa" in txt)
    return allowed, lic or terms or "Public domain"

def candidate_key(c):
    return c.get("direct_download_url")

def collect_commons(scene, queries, limit=6):
    out, seen = [], set()
    sn = scene.get("scene")
    for q in queries:
        try:
            pages = commons_search(q)
        except Exception:
            continue
        for rank, page in enumerate(pages,1):
            title = page.get("title") or ""
            if any(x in title.lower() for x in BAD_TITLE):
                continue
            ii = ((page.get("imageinfo") or [{}])[0])
            mime = (ii.get("mime") or "").lower()
            url = ii.get("url") or ""
            if not mime.startswith("video/") or not re.search(r"\.(webm|mp4)(?:$|\?)",url,re.I):
                continue
            if url in seen:
                continue
            seen.add(url)
            meta = ii.get("extmetadata") or {}
            oklic, lic = commons_license_ok(meta)
            if not oklic:
                continue
            w, h = int(ii.get("width") or 0), int(ii.get("height") or 0)
            okq, qscore = quality_ok(w,h)
            if not okq:
                continue
            pr = probe(url)
            if not pr or pr["duration"] < 1:
                continue
            cp, fqc = best_crop(url,pr["duration"],f"c{sn}_{len(out)}")
            if not cp:
                continue
            desc = strip_html(((meta.get("ImageDescription") or {}).get("value") or ""))
            c = {
                "scene":sn, "spoken_phrase":scene.get("spoken_phrase",""),
                "source_type":"WIKIMEDIA_COMMONS", "title":title.replace("File:","",1),
                "selected_asset_page_url":"https://commons.wikimedia.org/wiki/" + quote(title.replace(" ","_")),
                "direct_download_url":url, "source":"Wikimedia Commons",
                "license":lic, "rights_status":"PASS", "attribution_required":False,
                "media_type":"VIDEO","width":pr["width"],"height":pr["height"],
                "duration":round(pr["duration"],2),"visual_quality_score":qscore,
                "cleanliness_status":"PASS","crop_status":"PASS","crop_preference":cp,
                "frame_qc":fqc,"matched_query":q,"search_rank":rank,
                "metadata_excerpt":desc[:500]
            }
            out.append(c)
            if len(out) >= limit:
                return out
    return out

def collect_nasa(scene, queries, limit=6):
    out, ids = [], set()
    sn = scene.get("scene")
    for q in queries:
        try:
            items = nasa_search(q)
        except Exception:
            continue
        for rank, it in enumerate(items[:12],1):
            d = (it.get("data") or [{}])[0]
            nid = d.get("nasa_id")
            title = d.get("title") or ""
            if not nid or nid in ids or any(x in title.lower() for x in BAD_TITLE):
                continue
            ids.add(nid)
            text = " ".join([title, d.get("description") or "", " ".join(d.get("keywords") or [])]).lower()
            if not any(t in text for t in SPACE_TERMS):
                continue
            try:
                urls = nasa_videos(nasa_assets(nid))
            except Exception:
                continue
            for url in urls[:2]:
                pr = probe(url)
                if not pr or pr["duration"] < 1:
                    continue
                okq, qscore = quality_ok(pr["width"],pr["height"])
                if not okq:
                    continue
                cp, fqc = best_crop(url,pr["duration"],f"n{sn}_{len(out)}")
                if not cp:
                    continue
                c = {
                    "scene":sn,"spoken_phrase":scene.get("spoken_phrase",""),
                    "source_type":"NASA","nasa_id":nid,"title":title,
                    "selected_asset_page_url":"https://images.nasa.gov/details/" + quote(nid),
                    "direct_download_url":url,"source":"NASA Image and Video Library",
                    "license":"NASA U.S. Government media","rights_status":"PASS","attribution_required":False,
                    "media_type":"VIDEO","width":pr["width"],"height":pr["height"],
                    "duration":round(pr["duration"],2),"visual_quality_score":qscore,
                    "cleanliness_status":"PASS","crop_status":"PASS","crop_preference":cp,
                    "frame_qc":fqc,"matched_query":q,"search_rank":rank,
                    "metadata_excerpt":strip_html(d.get("description") or "")[:500]
                }
                out.append(c)
                break
            if len(out) >= limit:
                return out
    return out

POOLS = []
for scene in SCENES:
    sn = int(scene.get("scene") or 0)
    base = list(scene.get("search_queries") or [])
    cq = base + COMMONS_EXTRA.get(sn,[])
    nq = base + NASA_EXTRA.get(sn,[])
    candidates = collect_commons(scene,cq,6)
    if len(candidates) < 6:
        candidates += collect_nasa(scene,nq,6-len(candidates))
    # deterministic de-dupe and quality sort; semantic choice is deliberately deferred to the Make LLM gate
    dedup = {}
    for c in candidates:
        dedup[candidate_key(c)] = c
    candidates = list(dedup.values())
    candidates.sort(key=lambda c:(-c["visual_quality_score"], c["search_rank"]))
    POOLS.append({
        "scene":sn,
        "spoken_phrase":scene.get("spoken_phrase",""),
        "ideal_footage":scene.get("ideal_footage",""),
        "fallback_footage":scene.get("fallback_footage",""),
        "candidates":candidates[:6],
        "candidate_count":len(candidates[:6]),
        "status":"CANDIDATES_READY" if candidates else "NO_CANDIDATES"
    })

(OUT/"source_manifest.json").write_text(json.dumps(POOLS,indent=2),encoding="utf-8")
print(json.dumps(POOLS))
