import json,re
from pathlib import Path

OUT=Path('output')
manifest=json.loads((OUT/'source_manifest.json').read_text(encoding='utf-8'))

def family(s):
    s=(s or '').lower()
    s=re.sub(r'(~orig|[-_ ]clean|[-_ ]4k|[-_ ]8k|ultra[-_ ]?hd|uhd|vp9|h264|hevc)',' ',s)
    s=re.sub(r'[^a-z0-9]+',' ',s)
    return ' '.join(s.split())

def source_family(x):
    return family(x.get('asset_identity') or x.get('title') or '')

def hd_or_better(w,h):
    return (w>=1920 and h>=1080) or (h>=1920 and w>=1080)

# This stage is deliberately deterministic. It never swaps a semantically approved
# clip for a merely different clip. Exact licensed Commons footage is retained.
# Reuse is allowed only while the whole five-scene plan still has >=3 distinct families.
seen=set()
for x in manifest:
    if x.get('status')!='SELECTED':
        continue
    fam=source_family(x)
    x['source_family']=fam
    if fam in seen:
        x['source_reused_for_scene']=True
        x.setdefault('reuse_reason','SEMANTICALLY_APPROVED_REUSE_PREFERRED_OVER_OFF_TOPIC_REPLACEMENT')
    else:
        seen.add(fam)

selected=[x for x in manifest if x.get('status')=='SELECTED']
families={source_family(x) for x in selected if source_family(x)}
gate=json.loads((OUT/'source_gate.json').read_text(encoding='utf-8'))
gate['unique_source_families']=len(families)
gate['minimum_unique_source_families']=3
gate['duplicate_variant_policy']='AT_LEAST_THREE_DISTINCT_FAMILIES;SEMANTIC_SCENE_REUSE_ALLOWED'
gate['render_source_policy']='SEMANTIC_FIRST;LICENSED_COMMONS_RETAINED;4K_PREFERRED;FULL_HD_FALLBACK_ALLOWED'
gate['ready']=(
    len(selected)==len(manifest)
    and len(families)>=3
    and all(
        float(x.get('semantic_score') or 0)>=70
        and hd_or_better(int(x.get('width') or 0),int(x.get('height') or 0))
        for x in selected
    )
)

(OUT/'source_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
(OUT/'source_gate.json').write_text(json.dumps(gate,indent=2),encoding='utf-8')
print(json.dumps({
    'ready':gate['ready'],
    'selected':len(selected),
    'unique_source_families':len(families),
    'families':sorted(families)
}))
if not gate['ready']:
    raise SystemExit('Render-stable distinct-source-family gate failed')
