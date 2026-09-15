import json, os
from pathlib import Path

OUT=Path('output'); OUT.mkdir(exist_ok=True)

# Visual Director: raw footage must stay semantically relevant. Graphics explain/amplify;
# they are never used to disguise unrelated footage.
PLANS={
  1:{
    'purpose':'HOOK_AND_MEASUREMENT',
    'overlay':[{'type':'vertical_ruler','anchor':'subject_side','animation':'draw_up','accent':'orange'},
               {'type':'height_markers','from':'180 CM','to':'185 CM','animation':'tick_up'},
               {'type':'arrow','direction':'up','animation':'spring_short'}],
    'typography':[{'text':'WHY DO ASTRONAUTS','role':'hook'},{'text':'GROW IN SPACE?','role':'hook_accent'}],
    'sfx':[{'name':'measurement_ticks','at':'ruler_draw','gain_db':-12},{'name':'precision_click','at':'height_lock','gain_db':-9}],
    'camera':[{'type':'slow_push','amount':0.04}],
    'rule':'Footage must show an astronaut/body/measurement context; generic space or Earth imagery is forbidden.'},
  2:{
    'purpose':'GRAVITY_RELEASE',
    'overlay':[{'type':'compression_arrows','direction':'inward_vertical','animation':'press'},
               {'type':'label','text':'GRAVITY','animation':'snap_in'},
               {'type':'compression_arrows','direction':'outward_vertical','animation':'release'}],
    'typography':[{'text':'PRESSURE','role':'keyword'},{'text':'DISAPPEARS','role':'keyword_accent'}],
    'sfx':[{'name':'low_compression','at':'press','gain_db':-15},{'name':'air_release','at':'release','gain_db':-12}],
    'camera':[{'type':'micro_reframe','target':'astronaut'}],
    'rule':'Footage must visibly demonstrate astronaut microgravity/weightlessness.'},
  3:{
    'purpose':'SPINE_MECHANISM',
    'overlay':[{'type':'spine_line_art','animation':'trace','style':'technical_minimal'},
               {'type':'disc_spacing','animation':'expand_subtle'},
               {'type':'callout','text':'INTERVERTEBRAL DISCS','animation':'track_in'},
               {'type':'micro_arrows','direction':'outward','animation':'pulse_once'}],
    'typography':[{'text':'SPINE STRETCHES','role':'keyword'},{'text':'DISCS EXPAND','role':'keyword_accent'}],
    'sfx':[{'name':'technical_trace','at':'spine_trace','gain_db':-17},{'name':'soft_expand','at':'disc_expand','gain_db':-14}],
    'camera':[{'type':'controlled_zoom','amount':0.06}],
    'rule':'Footage must concern spine/ultrasound/physiology/body research; overlay supplies the explanatory mechanism.'},
  4:{
    'purpose':'THREE_PERCENT_PAYOFF',
    'overlay':[{'type':'measurement_bracket','animation':'extend_up'},
               {'type':'counter','text':'+3%','animation':'count_impact','scale':'hero'},
               {'type':'up_arrow','animation':'rise_lock'}],
    'typography':[{'text':'UP TO','role':'support'},{'text':'+3% TALLER','role':'hero_accent'}],
    'sfx':[{'name':'riser_short','at':'counter_start','gain_db':-14},{'name':'clean_impact','at':'counter_lock','gain_db':-8}],
    'camera':[{'type':'hold_subject','duration':'payoff'}],
    'rule':'Footage must show astronaut body/measurement/height context. Do not use generic ISS exterior footage.'},
  5:{
    'purpose':'RETURN_TO_GRAVITY',
    'overlay':[{'type':'gravity_arrow','direction':'down','animation':'drop_in'},
               {'type':'measurement_bracket','animation':'contract'},
               {'type':'counter','text':'+3% → 0%','animation':'return_to_zero'}],
    'typography':[{'text':'BACK ON EARTH','role':'keyword'},{'text':'HEIGHT RETURNS','role':'keyword_accent'}],
    'sfx':[{'name':'gravity_drop','at':'landing_transition','gain_db':-13},{'name':'compression_thump','at':'contract','gain_db':-11}],
    'camera':[{'type':'settle','amount':0.03}],
    'rule':'Footage must show actual astronaut return, landing, recovery or post-flight gravity context.'}
}

manifest_path=OUT/'source_manifest.json'
manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else []
by_scene={int(x['scene']):x for x in manifest if x.get('status')=='SELECTED'}
result=[]
for scene,plan in PLANS.items():
    src=by_scene.get(scene)
    result.append({'scene':scene,'source_ready':bool(src),'source':src,'visual_plan':plan,
                   'render_policy':{'raw_footage_required':True,'allow_still_images':False,'allow_generic_space_fallback':False,
                                    'graphics_are_explanatory_only':True,'caption_words_per_beat':'2-4','ui_safe_zone':'right'}})

(OUT/'visual_plan.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({'visual_plan_created':True,'scenes':len(result),'sources_ready':sum(1 for x in result if x['source_ready'])}))
