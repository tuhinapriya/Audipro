"""Render a narrated dialogue scene with independent music and sound effects."""
import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from .artifacts import atomic_write
from .audio import duration, quality, render
from .director import active_level, loudness
from .models import NarrativeDirectionPlan, Timeline, TimelineItem, GainPoint
from .providers import ElevenLabs
from .usage import UsageLog


def cached(path, inputs, callback):
    key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    meta = path.with_suffix(path.suffix+'.sha256')
    if path.exists() and path.stat().st_size and meta.exists() and meta.read_text()==key:
        return
    callback()
    atomic_write(meta,key.encode())


def render_scene(plan: NarrativeDirectionPlan, root: Path, provider: ElevenLabs, cover: Path):
    root.mkdir(parents=True,exist_ok=True)
    atomic_write(root/'narrative_plan.json',plan.model_dump_json(indent=2).encode())
    provider.set_usage_log(UsageLog(root/'provider_usage.jsonl'))
    cast={c.name:c for c in plan.cast}
    narrator=next(c for c in plan.cast if c.role=='narrator')
    voice = root/'narration'/'intro.mp3'
    original_voice = provider.voice
    provider.voice = narrator.voice_id
    try:
        cached(voice,[plan.narrator_text,narrator.voice_id,provider.tts_model],lambda: provider.narrate(plan.narrator_text,'','',voice))
    finally:
        provider.voice = original_voice
    inputs=[{'text':f'[{t.delivery}] {t.text}' if t.delivery else t.text,'voice_id':cast[t.speaker].voice_id} for t in plan.dialogue]
    dialogue=root/'dialogue'/'conversation.mp3'
    metadata=root/'dialogue'/'alignment.json'
    # A missing alignment sidecar invalidates the cached dialogue.
    if not metadata.exists() and dialogue.exists():
        dialogue.with_suffix('.mp3.sha256').unlink(missing_ok=True)
    cached(dialogue,inputs,lambda:provider.dialogue(inputs,dialogue,metadata))
    narrator_start=2.5
    narrator_length=duration(voice)
    dialogue_start=narrator_start+narrator_length+plan.pause_before_dialogue_seconds
    dialogue_length=duration(dialogue)
    voice_segments=json.loads(metadata.read_text()).get('voice_segments',[])
    cuts=[]
    for index,turn in enumerate(plan.dialogue):
        parts=[x for x in voice_segments if x.get('dialogue_input_index')==index]
        if not parts:
            continue
        start=min(x['start_time_seconds'] for x in parts);end=max(x['end_time_seconds'] for x in parts)
        if not (0<=start<end<=dialogue_length+.1):
            continue
        clip=root/'dialogue'/f'turn_{index+1:02d}.wav'
        subprocess.run(['ffmpeg','-y','-v','error','-ss',str(start),'-i',str(dialogue),'-t',str(end-start),'-c:a','pcm_s16le',str(clip)],check=True)
        cuts.append({'turn':index+1,'speaker':turn.speaker,'clip':str(clip.relative_to(root)),'original_start':start,'original_end':end,'scene_start':dialogue_start+start})
    split=any(t.pause_after_seconds for t in plan.dialogue)
    if split and len(cuts)!=len(plan.dialogue):
        raise ValueError('Per-turn pauses require valid timing for every dialogue turn')
    if split:
        cursor=dialogue_start
        for cut,turn in zip(cuts,plan.dialogue):
            cut['scene_start']=cursor
            cursor+=duration(root/cut['clip'])+turn.pause_after_seconds
        dialogue_end=cursor
    else:
        dialogue_end=dialogue_start+dialogue_length
    total=dialogue_end+plan.ending_silence_seconds
    anchors={'scene_start':0,'narrator_end':narrator_start+narrator_length,'dialogue_start':dialogue_start,'dialogue_end':dialogue_end}
    music=root/'music'/'score.mp3'
    length=max(3,min(300,round(total)))
    cached(music,[plan.music_prompt,length,provider.music_model],lambda:provider.music(plan.music_prompt,length,music))
    ambiance=root/'sfx'/'ambience.mp3'
    cached(ambiance,[plan.ambience_prompt,15,provider.sfx_model],lambda:provider.effect(plan.ambience_prompt,15,ambiance))
    for action in plan.actions:
        path=root/'sfx'/f'{action.id}.mp3'
        cached(path,[action.sound_prompt,action.duration_seconds,provider.sfx_model],lambda action=action,path=path:provider.effect(action.sound_prompt,action.duration_seconds,path))
    items=[TimelineItem(path=str(voice.relative_to(root)),start_seconds=narrator_start,duration_seconds=narrator_length,kind='narration')]
    if split:
        items.extend(TimelineItem(path=cut['clip'],start_seconds=cut['scene_start'],duration_seconds=duration(root/cut['clip']),kind='narration') for cut in cuts)
    else:
        items.append(TimelineItem(path=str(dialogue.relative_to(root)),start_seconds=dialogue_start,duration_seconds=dialogue_length,kind='narration'))
    def gain(path,target,limit=20):
        try:return max(-18,min(limit,target-active_level(path)))
        except ValueError:return 0
    musical_length=min(duration(music),total-plan.ending_silence_seconds-.2)
    musical_gain=gain(music,-25)
    # A gentle swell before dialogue, a smooth reduction ahead of speech, and
    # a return toward the end; boundaries use measured narration duration.
    t=max(.2,dialogue_start-.8)
    points=[GainPoint(time_seconds=0,gain_db=-3),GainPoint(time_seconds=min(2,t/2),gain_db=0),GainPoint(time_seconds=t,gain_db=-4)]
    if split:
        for cut, turn in zip(cuts, plan.dialogue):
            if turn.pause_after_seconds < .5:
                continue
            gap_start=cut['scene_start']+duration(root/cut['clip'])
            gap_end=min(gap_start+turn.pause_after_seconds,musical_length)
            if gap_end-gap_start >= .5:
                points.extend([GainPoint(time_seconds=gap_start,gain_db=-4),GainPoint(time_seconds=(gap_start+gap_end)/2,gain_db=0),GainPoint(time_seconds=gap_end-.1,gain_db=-4)])
    points=sorted({p.time_seconds:p for p in points}.values(),key=lambda p:p.time_seconds)
    items.append(TimelineItem(path=str(music.relative_to(root)),start_seconds=0,duration_seconds=musical_length,gain_db=musical_gain,kind='music',gain_envelope=points))
    ambience_length=duration(ambiance)
    cursor=0.0
    while cursor < total-plan.ending_silence_seconds:
        a_len=min(ambience_length,total-plan.ending_silence_seconds-cursor)
        items.append(TimelineItem(path=str(ambiance.relative_to(root)),start_seconds=cursor,duration_seconds=a_len,gain_db=gain(ambiance,-30),kind='sfx'))
        if cursor+a_len >= total-plan.ending_silence_seconds: break
        cursor += max(.1,a_len-.1)
    omitted=[]
    for action in plan.actions:
        path=root/'sfx'/f'{action.id}.mp3'
        if action.anchor == 'dialogue_turn_start':
            match=next((cut for cut in cuts if cut['turn']==(action.turn_index if action.turn_index is not None else -1)+1),None)
            if not match:
                omitted.append({'id':action.id,'reason':'dialogue turn has no provider timestamp'}); continue
            start=match['scene_start']+action.offset_seconds
        else:
            start=anchors[action.anchor]+action.offset_seconds
        if start<0 or start>=total-plan.ending_silence_seconds:
            omitted.append({'id':action.id,'reason':'anchor outside scene'});continue
        actual=min(duration(path),total-plan.ending_silence_seconds-start)
        items.append(TimelineItem(path=str(path.relative_to(root)),start_seconds=start,duration_seconds=actual,gain_db=gain(path,-26),kind='sfx'))
    timeline=Timeline(items=items,duration_seconds=total)
    atomic_write(root/'timeline.json',timeline.model_dump_json(indent=2).encode())
    if len(cuts)!=len(plan.dialogue):
        omitted.append({'id':'turn_clips','reason':'some provider turn timestamps were missing or invalid'})
    cues={'anchors':anchors,'layers':[x.model_dump() for x in items],'dialogue_turns':cuts,'unresolved':omitted,'music_gain_db':musical_gain}
    atomic_write(root/'cue_sheet.json',json.dumps(cues,indent=2).encode())
    render(timeline,root,root/'master.mp3',ducking=False)
    report=quality(root/'master.mp3',cover,total)
    report.update({'loudness':loudness(root/'master.mp3'),'duration_target_seconds':[30,45],'within_target':30<=total<=45,'dialogue_alignment_segments':len(cuts),'unresolved_cues':omitted,'manual_listening_completed':False,'limitations':['Intelligibility, emotional delivery, distinct voices and music balance require human listening.','Per-turn extracts depend on provider alignment; the full conversation is retained.','Fictionalized character dialogue is not a historical quotation.']})
    atomic_write(root/'qa_report.json',json.dumps(report,indent=2).encode())
    atomic_write(root/'manifest.json',json.dumps({'title':plan.title,'fictionalized':plan.fictionalized,'duration_seconds':round(total,2),'audio_file':'master.mp3','mime_type':'audio/mpeg'},indent=2).encode())
    return report


def main():
    load_dotenv();parser=argparse.ArgumentParser();parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--cover',type=Path,required=True);args=parser.parse_args()
    plan=NarrativeDirectionPlan.model_validate_json(args.plan.read_text())
    required=['ELEVENLABS_API_KEY','ELEVENLABS_VOICE_ID']
    missing=[x for x in required if not os.getenv(x)]
    if missing:parser.error('Missing '+', '.join(missing))
    provider=ElevenLabs(os.environ['ELEVENLABS_API_KEY'],os.environ['ELEVENLABS_VOICE_ID'],'eleven_v4',os.getenv('ELEVENLABS_MUSIC_MODEL','music_v1'),os.getenv('ELEVENLABS_SFX_MODEL','eleven_text_to_sound_v2'))
    result=render_scene(plan,args.output,provider,args.cover)
    print('Rendered duration:',result['duration_seconds'],'seconds; human listening required')

if __name__=='__main__': main()
