"""Contextual performances compiled into the blueprint's ordered timeline."""
import hashlib
import json
import math
import shutil
from pathlib import Path
from .artifacts import atomic_write
from .audio import duration, quality, render
from .casting import CastRegistry
from .director import active_level, loudness
from .models import ExpressiveItemMix, ExpressiveMix, GainPoint, SpatialMix, Timeline, TimelineItem
from .providers import DIALOGUE_MODEL
from .scene_director import emphasis_matches, validate_screenplay
from .speech_qa import compare, transcribe, transcribe_secondary
from .usage import UsageLog

SPEECH={'dialogue','reaction'}
EMOTION_TAGS={'fearful','sad','angry','excited','curious','happy'}
DELIVERY_TAGS={'whispering','shouting','softly','laughing','crying'}
EMOTION_ALIASES={'restrained':'restrained','frightened':'fearful','pleading':'pleading','furious':'angry'}
EFFORT_TAGS={'whisper':'whispering','soft':'softly','projected':'projecting','shout':'shouting'}

def performance_text(event, model: str) -> str:
    """Keep script text intact; only render a small allowlist of v4 tags.

    An explicit (even empty) typed direction wins over legacy delivery. Legacy
    free text is accepted only when it is exactly one known delivery label.
    Objectives, reactions, pace, and surrounding scene prose are not voice cues.
    """
    if model != 'eleven_v4':
        return event.text
    direction=event.vocal_performance
    if direction is None:
        legacy=event.delivery.strip().casefold()
        tags=[legacy] if legacy in DELIVERY_TAGS else []
    else:
        emotion=(direction.emotion or '').strip().casefold()
        emotion_tag=EMOTION_ALIASES.get(emotion,emotion if emotion in EMOTION_TAGS else None)
        delivery_tag=EFFORT_TAGS.get(direction.vocal_effort) if direction.vocal_effort is not None else direction.delivery
        tags=[tag for tag in (emotion_tag,delivery_tag) if tag and (tag in DELIVERY_TAGS or tag in EMOTION_TAGS or tag in EMOTION_ALIASES.values() or tag in EFFORT_TAGS.values())]
    text=event.text
    if direction is not None:
        spans=[]
        for phrase in direction.emphasis:
            matches=emphasis_matches(text,phrase)
            if not matches:raise ValueError(f'{event.id}: emphasis phrase not found in speech: {phrase!r}')
            spans.extend((m.start(),m.end()) for m in matches)
        spans.sort()
        if any(a[1]>b[0] for a,b in zip(spans,spans[1:])):raise ValueError(f'{event.id}: overlapping emphasis phrases')
        for start,end in reversed(spans):text=text[:start]+text[start:end].upper()+text[end:]
    return (' '.join(f'[{tag}]' for tag in tags)+' ' if tags else '')+text

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
    if not isinstance(segments,list):return [],['invalid alignment segments']
    if any(not isinstance(x,dict) or type(x.get('dialogue_input_index')) is not int or not 0<=x['dialogue_input_index']<len(events) for x in segments):
        return [],['invalid alignment segment index']
    for i,event in enumerate(events):
        matches=[x for x in segments if x.get('dialogue_input_index')==i]
        if not matches:
            problems.append(f'{event.id}: missing alignment');continue
        if any(not isinstance(x.get(key),(int,float)) or isinstance(x.get(key),bool) or not math.isfinite(x[key]) for x in matches for key in ('start_time_seconds','end_time_seconds')) or any(not 0<=x['start_time_seconds']<x['end_time_seconds']<=length for x in matches):
            problems.append(f'{event.id}: invalid alignment');continue
        begin=min(x['start_time_seconds'] for x in matches);end=max(x['end_time_seconds'] for x in matches)
        result.append({'event_id':event.id,'speaker':event.speaker,'start_seconds':begin,'end_seconds':end,'voice_ids':list(dict.fromkeys(x.get('voice_id') for x in matches))})
    if any(a['end_seconds']>b['start_seconds'] for a,b in zip(result,result[1:])):
        problems.append('speaker alignment overlaps or is out of order')
    return result,problems


def _directed_mix(block, length, alignment, issues):
    """Return block-local gain points and one representable item position.

    Renderer spatial settings apply to the entire contextual item, never to
    individual turns. Gain ramps are inside validated turn boundaries; effort
    and distance are modest authored offsets, not measured normalization.
    """
    unresolved=[]
    for event in block:
        direction=event.vocal_performance
        if direction and direction.acoustic_environment:
            unresolved.append(f'{event.id}: acoustic environment reference not rendered: {direction.acoustic_environment}')
        if direction and direction.delivery_note:
            unresolved.append(f'{event.id}: delivery note retained for human review')
        if direction and direction.emotion and direction.emotion.strip().casefold() not in EMOTION_TAGS | EMOTION_ALIASES.keys():
            unresolved.append(f'{event.id}: natural-language emotion retained for human review')
    if block[0].kind=='narration':
        bounds=[(0.0,length)]
    elif issues or len(alignment)!=len(block):
        if any(e.vocal_performance and (e.vocal_performance.vocal_effort or e.vocal_performance.distance or e.vocal_performance.spatial_position) for e in block):
            unresolved.append('Block '+', '.join(e.id for e in block)+': expressive mix skipped because provider alignment is invalid')
        return [],None,unresolved
    else:
        bounds=[(item['start_seconds'],item['end_seconds']) for item in alignment]
    points=[]
    effort_gain={'whisper':-3,'soft':-2,'normal':0,'projected':2,'shout':3}
    distance_gain={'intimate':0,'close':-1,'conversational':-2,'distant':-6}
    for event,(start,end) in zip(block,bounds):
        direction=event.vocal_performance
        gain=(effort_gain.get(direction.vocal_effort,0)+distance_gain.get(direction.distance,0)) if direction else 0
        ramp=min(.025,(end-start)/3)
        for time,value in ((start,0),(start+ramp,gain),(end-ramp,gain),(end,0)):
            if points and time==points[-1].time_seconds:
                continue
            points.append(GainPoint(time_seconds=time,gain_db=value))
    if not any(point.gain_db for point in points):points=[]
    positions=[e.vocal_performance.spatial_position.horizontal if e.vocal_performance and e.vocal_performance.spatial_position else ('center' if e.kind=='narration' else None) for e in block]
    spatial=None
    if len(set(positions))==1 and positions[0] is not None:
        spatial=SpatialMix(pan={'left':-.6,'center':0,'right':.6}[positions[0]])
    elif any(p is not None for p in positions):
        unresolved.append('Block '+', '.join(e.id for e in block)+': per-turn or partially specified positions cannot be rendered on one contextual item')
    return points,spatial,unresolved


def _perform(block, root, provider, registry, scope, log, max_attempts=3):
    is_narration=block[0].kind=='narration'
    keys=[('narrator' if e.kind=='narration' else f'{scope}:{e.speaker}') for e in block]
    try:voices=[registry.entries[key].voice_id for key in keys]
    except KeyError as e:raise ValueError(f'Missing cast registry entry: {e.args[0]}') from e
    expected=' '.join(e.text for e in block)
    model=provider.tts_model if is_narration else DIALOGUE_MODEL
    inputs=[{'text':performance_text(e,model),'voice_id':voice} for e,voice in zip(block,voices)]
    digest=hashlib.sha256(json.dumps({'inputs':inputs,'narration':is_narration,'model':model},sort_keys=True).encode()).hexdigest()[:16]
    block_id='__'.join(e.id for e in block)
    folder=root/'performances';folder.mkdir(parents=True,exist_ok=True)
    for attempt in range(1,max_attempts+1):
        stem=folder/f'{block_id}_{digest}_attempt{attempt}.mp3';meta=stem.with_suffix('.json');asr=stem.with_suffix('.asr.json')
        if not stem.exists() or not stem.stat().st_size or not meta.exists():
            # Invalidate evidence before a possibly failing paid regeneration.
            for stale in (stem,meta,asr,stem.with_suffix('.secondary.json'),stem.with_suffix('.review.json')):
                stale.unlink(missing_ok=True)
            if is_narration:
                previous=provider.voice;provider.voice=voices[0]
                try:provider.narrate(inputs[0]['text'],'','',stem)
                finally:provider.voice=previous
                atomic_write(meta,json.dumps({'type':'narration','voice_id':voices[0]}).encode())
            else:
                provider.dialogue(inputs,stem,meta)
        audio_hash=hashlib.sha256(stem.read_bytes()).hexdigest()
        evidence=json.loads(asr.read_text()) if asr.exists() else {}
        if evidence.get('audio_sha256') != audio_hash:
            transcript,word_times=transcribe(stem,log)
            evidence={'transcript':transcript,'word_times':word_times,'audio_sha256':audio_hash}
            atomic_write(asr,json.dumps(evidence,indent=2).encode())
        review=compare(expected,evidence['transcript'],evidence['word_times'])
        review['attempt']=attempt;review['asset']=str(stem.relative_to(root));review['model']='whisper-1'
        if review['uncertain']:
            secondary=stem.with_suffix('.secondary.json')
            secondary_evidence=json.loads(secondary.read_text()) if secondary.exists() else {}
            if secondary_evidence.get('audio_sha256') != audio_hash:
                secondary_evidence={'transcript':transcribe_secondary(stem,log),'audio_sha256':audio_hash}
                atomic_write(secondary,json.dumps(secondary_evidence).encode())
            second=compare(expected,secondary_evidence['transcript'])
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


def produce_performance(blueprint, screenplay, root: Path, provider, cover: Path, registry: CastRegistry, scope: str, *, generate_missing_actions: bool = False, expressive_mix: ExpressiveMix | None = None):
    """Render contextual blocks; pass ExpressiveMix() to opt into direction mixing.

    Item indices in an explicitly supplied mix refer to the final timeline order.
    The renderer has one spatial setting per block, not per dialogue turn.
    Acoustic environment references remain metadata for human review.
    """
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
    cursor=0.0;background={};completed=[];tracks=[];timeline_events=[];reviews=[];unresolved=[];unresolved_direction=[]
    mix=expressive_mix.model_copy(deep=True) if expressive_mix is not None else None
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
            track=TimelineItem(path=asset,start_seconds=cursor,duration_seconds=length,kind='narration')
            if mix is not None:
                points,spatial,direction_issues=_directed_mix(block,length,alignment,issues)
                unresolved_direction.extend(direction_issues)
                track.gain_envelope=points
                if spatial is not None:
                    settings=mix.items.setdefault(len(tracks),ExpressiveItemMix())
                    if settings.spatial is not None and settings.spatial != spatial:
                        unresolved_direction.append('Block '+', '.join(e.id for e in block)+': explicit mix spatial setting overrides performance position')
                    else:settings.spatial=spatial
            tracks.append(track)
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
            if mix is not None and kind=='ambience':
                mix.items.setdefault(len(tracks),ExpressiveItemMix()).ambience=True
            tracks.append(TimelineItem(path=path.name,start_seconds=pos,duration_seconds=length,gain_db=gain,kind='music' if kind=='music' else 'sfx',fade_out_seconds=0 if kind=='music' and pos+length>=end else None))
            if pos+length>=end:break
            pos+=max(.1,length-.1)
    timeline=Timeline(items=tracks,duration_seconds=cursor)
    expected_ids=[b.id for b in blueprint.required_beats]
    actual_ids=[e['beat_id'] for e in timeline_events if e['beat_id'] in expected_ids]
    if actual_ids!=expected_ids:raise ValueError('Required timeline beats missing or out of order')
    atomic_write(work/'timeline.json',timeline.model_dump_json(indent=2).encode())
    cue_sheet={'events':timeline_events,'timeline':timeline.model_dump(),'unresolved':unresolved}
    if mix is not None:cue_sheet.update({'expressive_mix':mix.model_dump(),'unresolved_performance':unresolved_direction})
    atomic_write(work/'cue_sheet.json',json.dumps(cue_sheet,indent=2).encode())
    target=root/'master_performance_fixed.mp3'
    if mix is None:render(timeline,root,target,ducking=True)
    else:render(timeline,root,target,ducking=True,expressive_mix=mix)
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
    if mix is not None:
        q['unresolved_performance']=unresolved_direction
        q['limitations'].append('Spatial mix applies to whole performance blocks; per-turn spatial changes and acoustic environment references are not rendered.')
    atomic_write(work/'qa_report.json',json.dumps(q,indent=2).encode())
    if mix_review['repeated_phrases']:
        raise RuntimeError('Final mix contains suspected repeated speech; review retained QA evidence before delivery')
    return q
