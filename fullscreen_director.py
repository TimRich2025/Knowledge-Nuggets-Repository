import json
from pathlib import Path

OUT=Path('output'); OUT.mkdir(exist_ok=True)
manifest=json.loads((OUT/'source_manifest.json').read_text(encoding='utf-8'))
selected={int(x['scene']):x for x in manifest if x.get('status')=='SELECTED'}

# Fullscreen short grammar derived from the approved direction: footage carries context,
# graphics direct attention, captions emphasize only the current beat, audio supports both.
beats=[
 {"scene":1,"duration":3.2,"voice":"Why do astronauts grow taller in space?","caption_beats":["WHY DO","ASTRONAUTS","GROW TALLER?"],"focus":"astronaut/full body","graphics":["height_bracket","up_arrow","measurement_ticks"],"motion":"fast_push_in","sfx":["soft_whoosh","measurement_click"],"music_energy":"curious_hook"},
 {"scene":2,"duration":3.6,"voice":"On Earth, gravity constantly compresses your spine.","caption_beats":["ON EARTH","GRAVITY","COMPRESSES","YOUR SPINE"],"focus":"human body / gravity context","graphics":["down_arrows","spine_outline","compression_pulse"],"motion":"controlled_punch_in","sfx":["low_hit","compression_tick"],"music_energy":"build"},
 {"scene":2,"duration":3.3,"voice":"In microgravity, that pressure disappears.","caption_beats":["IN MICROGRAVITY","PRESSURE","DISAPPEARS"],"focus":"astronaut visibly floating","graphics":["circle_subject","arrows_release"],"motion":"subject_track","sfx":["air_release","light_whoosh"],"music_energy":"release"},
 {"scene":3,"duration":4.2,"voice":"Your spine stretches, and the discs between your vertebrae expand.","caption_beats":["YOUR SPINE","STRETCHES","DISCS EXPAND"],"focus":"astronaut human research / physiology","graphics":["spine_trace","disc_spacing","expand_arrows"],"motion":"slow_macro_push","sfx":["technical_trace","soft_expand"],"music_energy":"explain"},
 {"scene":4,"duration":3.4,"voice":"Astronauts can grow up to three percent taller.","caption_beats":["UP TO","3%","TALLER"],"focus":"astronaut body / measurement context","graphics":["vertical_ruler","height_line","counter_0_to_3","up_arrow"],"motion":"snap_reframe","sfx":["riser_short","number_pop","impact_clean"],"music_energy":"payoff"},
 {"scene":5,"duration":4.2,"voice":"But back on Earth, gravity compresses the spine again, and the extra height disappears.","caption_beats":["BACK ON EARTH","GRAVITY RETURNS","HEIGHT DISAPPEARS"],"focus":"return / landing / recovery","graphics":["down_arrow","height_bracket_contract","counter_3_to_0"],"motion":"impact_then_settle","sfx":["gravity_drop","compression_thump","soft_resolve"],"music_energy":"resolve"}
]

for b in beats:
    src=selected.get(b['scene'])
    b['source']=None if not src else {k:src.get(k) for k in ('asset_identity','title','direct_download_url','width','height','duration','source_family')}
    b['render']={"canvas":"1080x1920","layout":"FULLSCREEN","source_mode":"moving_video_only","crop":"cover_9x16_subject_aware","caption_words_per_card":"1-4","caption_position":"dynamic_safe_center","shorts_ui_safe_right":True,"white_caption_panel":False,"generic_space_fallback":False,"graphics_role":"attention_and_explanation","watermark":"bottom_center","watermark_scale":"visible_not_dominant"}

plan={"version":"KN_FULLSCREEN_V1","content_id":"KN-ASTRONAUT-V4","principle":"VOICE + MATCHED FOOTAGE + KINETIC TYPE + ATTENTION GRAPHICS + MUSIC + SEMANTIC SFX","audio":{"voice":"warm_clear_natural","voice_priority_db":0,"music_target_db":-21,"music_duck_under_voice_db":-5,"sfx_target_db":-12,"no_constant_sfx":True,"semantic_sync":True},"style":{"fullscreen":True,"fast_semantic_cuts":True,"large_high_contrast_captions":True,"accent":"warm orange","stroke_shadow":"strong readability","attention_tools":["arrow","circle","ruler","bracket","counter","outline","zoom","tracking_marker"],"avoid":["white lower caption panel","gray low-contrast subtitles","decorative effects without meaning","generic space filler"]},"beats":beats}
(OUT/'fullscreen_plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
print(json.dumps({'fullscreen_plan_created':True,'beats':len(beats),'sources_attached':sum(bool(b['source']) for b in beats)}))
