"""Contextual performances compiled into the blueprint's ordered timeline."""
import hashlib
import json
import shutil
from pathlib import Path
from .artifacts import atomic_write
from .audio import duration, quality, render
from .casting import CastRegistry
from .director import active_level, loudness
from .models import Timeline, TimelineItem
from .scene_director import validate_screenplay
from .speech_qa import compare, transcribe, transcribe_secondary
from .usage import UsageLog

SPEECH={'dialogue','reaction'}

def group_events(events):
    """Only adjacent conversational turns share context; physical beats split blocks."""
    blocks=[]
    for event in events:
        if event.kind in SPEECH and blocks and all(e.kind in SPEECH for e in blocks[-1]):
            blocks[-1].append(event)
        else:
            blocks.append([event])
    return blocks


def align_block(events, segments, length):
    result=[];problems=[]
    for i,event in enumerate(events):
        matches=[x for x in segments if x.get('dialogue_input_index')==i]
        if not matches:
            problems.append(f'{event.id}: missing alignment');continue
        begin=min(x['start_time_seconds'] for x in matches);end=max(x['end_time_seconds'] for x in matches)
        if not (0<=begin<end<=length+.15):
            problems.append(f'{event.id}: invalid alignment');continue
        result.append({'event_id':event.id,'speaker':event.speaker,'start_seconds':begin,'end_seconds':end,'voice_ids':list({x.get('voice_id') for x in matches})})
    if any(a['end_seconds']>b['start_seconds']+.05 for a,b in zip(result,result[1:])):
        problems.append('speaker alignment overlaps or is out of order')
    return result,problems


def _perform(block, root, provider, registry, scope, log, max_attempts=3):
    is_narration=block[0].kind=='narration'
    keys=[('narrator' if e.kind=='narration' else f'{scope}:{e.speaker}') for e in block]
    try:voices=[registry.entries[key].voice_id for key in keys]
    except KeyError as e:raise ValueError(f'Missing cast registry entry: {e.args[0]}') from e
    expected=' '.join(e.text for e in block)
    inputs=[{'text':(f'[{e.delivery}] ' if e.delivery else '')+e.text,'voice_id':voice} for e,voice in zip(block,voices)]
    digest=hashlib.sha256(json.dumps({'inputs':inputs,'narration':is_narration,'model':provider.tts_model},sort_keys=True).encode()).hexdigest()[:16]
    block_id='__'.join(e.id for e in block)
    folder=root/'performances';folder.mkdir(parents=True,exist_ok=True)
    for attempt in range(1,max_attempts+1):
        stem=folder/f'{block_id}_{digest}_attempt{attempt}.mp3';meta=stem.with_suffix('.json');asr=stem.with_suffix('.asr.json')
        if not stem.exists() or not stem.stat().st_size or (not is_narration and not meta.exists()):
            if is_narration:
                previous=provider.voice;provider.voice=voices[0]
                try:provider.narrate(inputs[0]['text'],'','',stem)
                finally:provider.voice=previous
                atomic_write(meta,json.dumps({'type':'narration','voice_id':voices[0]}).encode())
            else:
                provider.dialogue(inputs,stem,meta)
        if not asr.exists():
            transcript,word_times=transcribe(stem,log)
            atomic_write(asr,json.dumps({'transcript':transcript,'word_times':word_times},indent=2).encode())
        evidence=json.loads(asr.read_text());review=compare(expected,evidence['transcript'],evidence['word_times'])
        review['attempt']=attempt;review['asset']=str(stem.relative_to(root));review['model']='whisper-1'
        if review['uncertain']:
            secondary=stem.with_suffix('.secondary.json')
            if not secondary.exists():
                atomic_write(secondary,json.dumps({'transcript':transcribe_secondary(stem,log)}).encode())
            second=compare(expected,json.loads(secondary.read_text())['transcript'])
            review['secondary_asr']={'model':'gpt-4o-transcribe',**second}
            review['interpretation']='ASR is uncertain; disagreement requires human review.'
        if review['repeated_phrases']:
            review['status']='rejected_suspected_repetition'
            atomic_write(stem.with_suffix('.review.json'),json.dumps(review,indent=2).encode())
            continue
        review['status']='uncertain' if review['differences'] else 'passed_automatic_checks'
        atomic_write(stem.with_suffix('.review.json'),json.dumps(review,indent=2).encode())
        alignment,issues=([],[]) if is_narration else align_block(block,json.loads(meta.read_text()).get('voice_segments') or [],duration(stem))
        if not is_narration:
            for item in alignment:
                expected_voice=registry.entries[f"{scope}:{item['speaker']}"].voice_id
                if item['voice_ids'] != [expected_voice]:issues.append(item['event_id']+': speaker metadata mismatch')
        return stem,review,alignment,issues
    raise RuntimeError(f'Performance {block_id} repeatedly failed speech verification; retained attempts for review')


def produce_performance(blueprint, screenplay, root: Path, provider, cover: Path, registry: CastRegistry, scope: str, *, generate_missing_actions: bool = False):
    errors=validate_screenplay(blueprint,screenplay)
    if errors:raise ValueError('Screenplay validation failed: '+'; '.join(errors))
    required_keys={'narrator' if e.kind=='narration' else f'{scope}:{e.speaker}' for e in screenplay.events if e.kind in SPEECH or e.kind=='narration'}
    missing=required_keys-registry.entries.keys()
    if missing: raise ValueError('Missing cast registry entries: '+', '.join(sorted(missing)))
    profiles={profile.character:profile for profile in blueprint.profiles}
    for event in screenplay.events:
        if event.kind in SPEECH:
            selected=registry.entries[f'{scope}:{event.speaker}'].voice_id
            if profiles[event.speaker].voice_id and profiles[event.speaker].voice_id != selected:
                raise ValueError(f'Locked cast differs from blueprint for {event.speaker}; resolve explicitly before generation')
        if event.kind=='action':
            asset=root/'sfx'/f'{event.id}.mp3'
            if (not asset.is_file() or not asset.stat().st_size) and not generate_missing_actions:
                raise FileNotFoundError(f'Missing existing action asset {asset}; no audio was generated')
    for background in ('music.mp3','ambience.mp3'):
        asset=root/background
        if not asset.is_file() or not asset.stat().st_size:
            raise FileNotFoundError(f'Missing saved background {asset}; no audio was generated')
    for voice_id in {registry.entries[key].voice_id for key in required_keys}:
        response=provider.http.get(f'voices/{voice_id}')
        if response.is_error: raise ValueError('A selected voice is unavailable; no substitutions were made. Check the cast registry and account access.')
    work=root/'performance_fixed';work.mkdir(parents=True,exist_ok=True)
    log=UsageLog(work/'provider_usage.jsonl');provider.set_usage_log(log)
    cursor=0.0;background={};completed=[];tracks=[];timeline_events=[];reviews=[];unresolved=[]
    def close(kind):
        if kind in background:
            start=background.pop(kind)
            if cursor>start:completed.append((kind,start,cursor))
    for block in group_events(screenplay.events):
        event=block[0];start=cursor;asset='';event_data=[]
        if event.kind in ('music_start','ambience_start'):
            background[event.kind.split('_')[0]]=cursor
        elif event.kind in ('music_stop','ambience_stop'):
            close(event.kind.split('_')[0])
        elif event.kind=='silence':
            if background:raise ValueError('Cannot silence while backgrounds are active')
            cursor+=event.duration_seconds
        elif event.kind in SPEECH or event.kind=='narration':
            stem,review,alignment,issues=_perform(block,work,provider,registry,scope,log)
            length=duration(stem);asset=str(stem.relative_to(root));reviews.append(review);unresolved.extend(issues)
            tracks.append(TimelineItem(path=asset,start_seconds=cursor,duration_seconds=length,kind='narration'))
            for member in block:
                match=next((x for x in alignment if x['event_id']==member.id),None)
                # Narration is a single event, so the full block is its anchor.
                begin=cursor+(match['start_seconds'] if match else 0) if len(block)==1 or match else None
                end=cursor+(match['end_seconds'] if match else length) if len(block)==1 or match else None
                event_data.append({'event_id':member.id,'beat_id':member.beat_id,'kind':member.kind,'speaker':member.speaker,'start_seconds':begin,'end_seconds':end,'asset':asset,'alignment': 'provider' if match else ('whole_narration' if member.kind=='narration' else 'unavailable')})
            cursor+=length
        elif event.kind=='action':
            asset=f'sfx/{event.id}.mp3';path=root/asset
            if not path.is_file() or path.stat().st_size==0:
                if not generate_missing_actions:raise FileNotFoundError(f'Missing existing action asset {asset}; refusing to regenerate it implicitly')
                from .cinematic import cached
                requested=event.duration_seconds or 2
                cached(path,[event.sound_prompt,requested,provider.sfx_model],lambda:provider.effect(event.sound_prompt,requested,path))
            length=duration(path);tracks.append(TimelineItem(path=asset,start_seconds=cursor,duration_seconds=length,gain_db=4,kind='sfx'));cursor+=length
        if event_data:timeline_events.extend(event_data)
        else:timeline_events.append({'event_id':event.id,'beat_id':event.beat_id,'kind':event.kind,'start_seconds':start,'end_seconds':cursor,'asset':asset})
    for kind in list(background):close(kind)
    for kind,start,end in completed:
        path=root/('music.mp3' if kind=='music' else 'ambience.mp3')
        if not path.is_file():raise FileNotFoundError(f'Missing saved background {path}')
        gain=max(-12,min(18,(-25 if kind=='music' else -32)-active_level(path)))
        pos=start;span=duration(path)
        while pos<end:
            length=min(span,end-pos)
            tracks.append(TimelineItem(path=path.name,start_seconds=pos,duration_seconds=length,gain_db=gain,kind='music' if kind=='music' else 'sfx',fade_out_seconds=0 if kind=='music' and pos+length>=end else None))
            if pos+length>=end:break
            pos+=max(.1,length-.1)
    timeline=Timeline(items=tracks,duration_seconds=cursor)
    expected_ids=[b.id for b in blueprint.required_beats]
    actual_ids=[e['beat_id'] for e in timeline_events if e['beat_id'] in expected_ids]
    if actual_ids!=expected_ids:raise ValueError('Required timeline beats missing or out of order')
    atomic_write(work/'timeline.json',timeline.model_dump_json(indent=2).encode())
    atomic_write(work/'cue_sheet.json',json.dumps({'events':timeline_events,'timeline':timeline.model_dump(),'unresolved':unresolved},indent=2).encode())
    target=root/'master_performance_fixed.mp3'
    render(timeline,root,target,ducking=True)
    planned=[(e['start_seconds'],e['end_seconds']) for e in timeline_events if e['kind']=='silence']
    q=quality(target,cover,cursor,allowed_silence=planned)
    text,word_times=transcribe(target,log)
    expected=' '.join(e.text for e in screenplay.events if e.kind in SPEECH or e.kind=='narration')
    mix_review=compare(expected,text,word_times)
    if mix_review['uncertain']:
        secondary_text=transcribe_secondary(target,log)
        mix_review['secondary_asr']={'model':'gpt-4o-transcribe',**compare(expected,secondary_text)}
        mix_review['interpretation']='ASR is uncertain; disagreement requires human review.'
    q.update({'loudness':loudness(target),'required_beats_in_order':actual_ids,'planned_silence':planned,'speech_performances':reviews,'master_transcription':mix_review,'unresolved_alignment':unresolved,'human_listening_completed':False,'limitations':['ASR can omit repetitions or mishear words.','Casting, acting, acoustics and the finished mix require human listening.','Speaker timestamps are provider estimates.']})
    atomic_write(work/'qa_report.json',json.dumps(q,indent=2).encode())
    if mix_review['repeated_phrases']:
        raise RuntimeError('Final mix contains suspected repeated speech; review retained QA evidence before delivery')
    return q
