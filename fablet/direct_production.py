"""Generate a sound direction plan and compile it against actual narration timings."""
import argparse
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from .artifacts import cached_model
from .audio import duration, quality, render
from .director import AudioDirectionPlan, active_level, compile_plan, loudness
from .models import Timeline, TimelineItem, GainPoint
from .providers import EditorialProvider
from .usage import UsageLog


def direct(root: Path):
    script = json.loads((root/'script.json').read_text())
    original = Timeline.model_validate_json((root/'timeline.json').read_text())
    narration = [item.model_dump() for item in original.items if item.kind == 'narration']
    assets = [str(p.relative_to(root)) for folder in ('music', 'sfx') for p in (root/folder).glob('*.mp3')]
    editor = EditorialProvider(os.environ['OPENAI_MODEL'])
    editor.set_usage_log(UsageLog(root/'provider_usage.jsonl'))
    context = json.dumps({'script': script, 'available_assets': assets}, ensure_ascii=False)
    plan = cached_model(root/'audio_direction_plan.json', AudioDirectionPlan, context, lambda: editor.structured('Act as an audio director. Design a coherent cinematic soundscape for this script using only available asset paths. For every cue choose exact script segment IDs and semantic start/end anchors; use start/end anchors, not invented timestamps. Phrase anchors are allowed but will be skipped if no word alignment exists. Space cues for dramatic contrast, J-cuts, L-cuts, and intentional silence. Include scene objectives, emotional intensity, narration pacing, motif, mixing priorities and the reason for every cue. Do not cite nonexistent assets.\n'+context, AudioDirectionPlan))
    alignment_path = root/'word_alignment.json'
    alignment = json.loads(alignment_path.read_text()) if alignment_path.exists() else {}
    cues, unresolved = compile_plan(plan, narration, alignment)
    items = [TimelineItem.model_validate(item) for item in narration]
    report = []
    for cue in cues:
        path = cue['asset']
        if cue['kind'] == 'silence':
            unresolved.append({'cue':cue['id'], 'reason':'Silence requires no asset; verify it does not overlap active stems.'}); continue
        if path not in assets:
            unresolved.append({'cue':cue['id'], 'reason':'Asset not available'}); continue
        start = cue['start_seconds']; length = min(cue['end_seconds']-start,duration(root/path),original.duration_seconds-start)
        if length <= 0:
            unresolved.append({'cue':cue['id'], 'reason':'Empty or out-of-range cue'}); continue
        kind = 'music' if cue['kind'] in ('music','ambience') else 'sfx'
        # Calibrate each asset by measured active level, not its absolute peak.
        target = -25 if kind == 'music' else -23
        try:
            measured_level = active_level(root/path)
        except ValueError:
            unresolved.append({'cue':cue['id'], 'reason':'Asset contains no measurable active audio above the analysis threshold; omitted.'})
            continue
        gain = max(-18,min(18,target-measured_level))
        envelope = []
        if kind == 'music' and length > .3:
            envelope = [GainPoint(time_seconds=0,gain_db=0),GainPoint(time_seconds=min(.6,length/2),gain_db=-3)]
        item = TimelineItem(path=path,start_seconds=start,duration_seconds=length,gain_db=gain,kind=kind,gain_envelope=envelope)
        items.append(item)
        report.append({'id':cue['id'],'purpose':cue['purpose'],'transition_requested':cue['transition'],**item.model_dump()})
    if not any(i.kind=='music' for i in items):
        raise RuntimeError('Direction produced no usable music cues; inspect unresolved cues')
    timeline = Timeline(items=items,duration_seconds=original.duration_seconds)
    (root/'timeline_directed.json').write_text(timeline.model_dump_json(indent=2))
    (root/'cue_sheet.json').write_text(json.dumps({'executed':report,'unresolved':unresolved},indent=2))
    render(timeline,root,root/'master_directed.mp3',ducking=False)
    q=quality(root/'master_directed.mp3',root/'cover.webp',timeline.duration_seconds)
    q.update({'loudness':loudness(root/'master_directed.mp3'),'cue_execution':report,'unresolved_cues':unresolved,'manual_listening_completed':False,'limitations':['Phrase cues require word alignment; unresolved cues were skipped.','Transition types are editorial intentions; this renderer applies equal-power fades rather than dedicated J/L-crossfade scheduling.','Music balance and historical claims require human review.']})
    (root/'qa_directed.json').write_text(json.dumps(q,indent=2))
    print('Directed render saved; unresolved cues:',len(unresolved))

if __name__ == '__main__':
    load_dotenv();p=argparse.ArgumentParser();p.add_argument('output',type=Path);direct(p.parse_args().output)
