import json
from pathlib import Path

OUT=Path('output'); OUT.mkdir(exist_ok=True)
manifest=json.loads((OUT/'source_manifest.json').read_text(encoding='utf-8'))
selected={int(x['scene']):x for x in manifest if x.get('status')=='SELECTED'}

beats=[
 {"scene":1,"duration":3.2,"voice":"Why do astronauts grow taller in space?","caption_beats":["WHY DO","ASTRONAUTS","GROW TALLER?"],"focus":"astronaut/full body"},
 {"scene":2,"duration":3.6,"voice":"On Earth, gravity constantly compresses your spine.","caption_beats":["ON EARTH","GRAVITY","COMPRESSES","YOUR SPINE"],"focus":"human body / gravity context"},
 {"scene":2,"duration":3.3,"voice":"In microgravity, that pressure disappears.","caption_beats":["IN MICROGRAVITY","PRESSURE","DISAPPEARS"],"focus":"astronaut visibly floating"},
 {"scene":3,"duration":4.2,"voice":"Your spine stretches, and the discs between your vertebrae expand.","caption_beats":["YOUR SPINE","STRETCHES","DISCS EXPAND"],"focus":"astronaut human research / physiology"},
 {"scene":4,"duration":3.4,"voice":"Astronauts can grow up to three percent taller.","caption_beats":["UP TO","3%","TALLER"],"focus":"astronaut body / measurement context"},
 {"scene":5,"duration":4.2,"voice":"But back on Earth, gravity compresses the spine again, and the extra height disappears.","caption_beats":["BACK ON EARTH","GRAVITY RETURNS","HEIGHT DISAPPEARS"],"focus":"return / landing / recovery"}
]

for b in beats:
    src=selected.get(b['scene'])
    b['source']=None if not src else {k:src.get(k) for k in ('asset_identity','title','direct_download_url','width','height','duration','source_family')}
    b['render']={
      "canvas":"1080x1920","layout":"KN_LAYOUT_V1_LOCKED","header_height":429,
      "video_y":429,"video_height":1491,"source_mode":"moving_video_only",
      "caption_style":"centered_white_black_outline","caption_words_per_card":"1-4",
      "graphics":"none_by_default","generic_space_fallback":False
    }

plan={
 "version":"KN_LAYOUT_V1",
 "content_id":"KN-ASTRONAUT-V4",
 "core_question_lines":["WHY DO ASTRONAUTS","GROW TALLER?"],
 "layout_lock":{
   "immutable":True,
   "fixed_elements":["header_geometry","background","official_logo","brand_name","orange_line","question_typography","question_positions","white_divider","video_start","subtitle_style"],
   "variable_elements":["core_question_text","video_footage","subtitle_text"],
   "overflow_policy":"FAIL_AND_REWRITE_QUESTION_NEVER_RESIZE_LAYOUT"
 },
 "principle":"FIXED KNOWLEDGE NUGGETS SHELL + MATCHED MOVING FOOTAGE + SIMPLE CENTER SUBTITLES",
 "audio":{"voice":"warm_clear_natural","music":"later","semantic_sfx":"later"},
 "style":{"extra_decorative_vectors":False,"random_graphics":False,"subtitle_color":"white","subtitle_outline":"black","subtitle_position":"video_center"},
 "beats":beats
}
(OUT/'fullscreen_plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
print(json.dumps({'fullscreen_plan_created':True,'layout':'KN_LAYOUT_V1','beats':len(beats),'sources_attached':sum(bool(b['source']) for b in beats)}))
