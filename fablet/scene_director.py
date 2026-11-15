"""Blueprint-driven cinematic scripting and ordered audio production."""
import hashlib
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, model_validator
from .artifacts import atomic_write
from .audio import duration, quality, render
from .director import active_level, loudness
from .models import Timeline, TimelineItem
from .usage import UsageLog

class VoiceProfile(BaseModel):
    character: str
    identity: str
    age_range: str
    accent: str
    vocal_register: str
    texture: str
    rhythm: str
    personality: str
    emotional_range: str
    pronunciation: str
    voice_id: str = ''
    casting_evidence: str = ''
    human_review: Literal['pending', 'approved', 'rejected'] = 'pending'

class RequiredBeat(BaseModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]+$')
    description: str
    allowed_types: list[Literal['narration','dialogue','reaction','action','music_start','music_stop','ambience_start','ambience_stop','silence']]
    required_text: str = ''
    required_speaker: str = ''
    acoustic_expectation: str = ''

class SceneBlueprint(BaseModel):
    title: str
    premise: str
    setting: str
    character_goals: list[str]
    emotional_states: list[str]
    escalation: str
    audience_emotion: str
    climax: str
    resolution: str
    profiles: list[VoiceProfile]
    required_beats: list[RequiredBeat]
    optional_details: list[str] = []

    @model_validator(mode='after')
    def distinct(self):
        if len({x.id for x in self.required_beats})!=len(self.required_beats):raise ValueError('Duplicate required beat ID')
        if len({x.character for x in self.profiles})!=len(self.profiles):raise ValueError('Duplicate character')
        return self

class DramaticEvent(BaseModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]+$')
    beat_id: str = ''
    kind: Literal['narration','dialogue','reaction','action','music_start','music_stop','ambience_start','ambience_stop','silence']
    speaker: str = ''
    text: str = ''
    emotional_objective: str = ''
    delivery: str = ''
    intensity: str = ''
    pace: str = ''
    intimacy: str = ''
    intended_reaction: str = ''
    interruption: str = ''
    physical_action: str = ''
    acoustic_expectation: str = ''
    consequence: str = ''
    sound_prompt: str = ''
    duration_seconds: float = Field(default=0,ge=0,le=30)
    source_asset: str = ''
    after_event_id: str = ''

class SceneScreenplay(BaseModel):
    events: list[DramaticEvent] = Field(min_length=1)


def validate_screenplay(blueprint: SceneBlueprint, screenplay: SceneScreenplay) -> list[str]:
    errors=[];events=screenplay.events;ids=[x.id for x in events]
    if len(ids)!=len(set(ids)):errors.append('Duplicate event ID')
    profiles={p.character for p in blueprint.profiles}
    for i,e in enumerate(events):
        if e.after_event_id and e.after_event_id not in ids[:i]:errors.append(f'{e.id}: invalid or future anchor')
        if e.kind in ('dialogue','reaction','narration') and (e.speaker not in profiles or not e.text.strip()):errors.append(f'{e.id}: unknown speaker or empty speech')
        if e.kind=='action' and (not e.physical_action or not e.acoustic_expectation or not e.consequence or not e.sound_prompt):errors.append(f'{e.id}: physical action missing acoustic or consequence detail')
        if e.kind=='silence' and e.duration_seconds <= 0:errors.append(f'{e.id}: silence must have positive duration')
    active=set()
    for e in events:
        if e.kind in ('music_start','ambience_start'):
            track=e.kind.split('_')[0]
            if track in active: errors.append(f'{e.id}: duplicate background start')
            active.add(track)
        elif e.kind in ('music_stop','ambience_stop'):
            track=e.kind.split('_')[0]
            if track not in active: errors.append(f'{e.id}: background not active')
            active.discard(track)
        elif e.kind=='silence' and active:
            errors.append(f'{e.id}: silence overlaps active background')
    positions=[]
    for beat in blueprint.required_beats:
        matches=[(i,e) for i,e in enumerate(events) if e.beat_id==beat.id]
        if not matches:errors.append(f'Missing beat: {beat.id}');continue
        if len(matches)!=1:errors.append(f'{beat.id}: expected exactly one occurrence')
        position,event=matches[0];positions.append(position)
        if event.kind not in beat.allowed_types:errors.append(f'{beat.id}: incorrect event type')
        if beat.required_text and beat.required_text.casefold() not in (event.text+' '+event.physical_action+' '+event.acoustic_expectation+' '+event.consequence).casefold():errors.append(f'{beat.id}: missing required text')
        if beat.required_speaker and event.speaker.casefold()!=beat.required_speaker.casefold():errors.append(f'{beat.id}: incorrect speaker')
        if beat.acoustic_expectation and event.kind=='action' and beat.acoustic_expectation.casefold() not in (event.acoustic_expectation+' '+event.sound_prompt).casefold():errors.append(f'{beat.id}: required acoustic expectation missing')
    if positions!=sorted(positions):errors.append('Required beats are out of order')
    return errors


def validate_cast(profile: VoiceProfile, voice: dict) -> list[str]:
    """Metadata is evidence only: absent data remains unverified, never approved."""
    labels=voice.get('labels') or {};errors=[]
    if profile.voice_id and profile.voice_id!=voice.get('voice_id'):errors.append('voice ID mismatch')
    desired=profile.accent.casefold();actual=str(labels.get('accent','')).casefold()
    if desired and actual and desired not in actual and actual not in desired:errors.append(f'accent mismatch: requested {desired}, metadata {actual}')
    if desired and not actual:errors.append('accent unverified in metadata')
    age=profile.age_range.casefold(); observed=str(labels.get('age','')).casefold()
    if age in ('young','old','middle_aged') and observed and age!=observed:errors.append(f'age mismatch: requested {age}, metadata {observed}')
    if age and not observed:errors.append('age unverified in metadata')
    evidence=' '.join([str(voice.get('description') or ''), *[str(v) for v in labels.values()]]).casefold()
    for label,requested in [('register',profile.vocal_register),('texture',profile.texture)]:
        terms=[x for x in requested.casefold().split() if len(x)>3]
        if terms and not any(term in evidence for term in terms): errors.append(f'{label} unverified in metadata: {requested}')
    return errors


def shortlist(profile: VoiceProfile, voices: list[dict]) -> list[dict]:
    def rank(voice):
        labels=voice.get('labels') or {};accent=str(labels.get('accent','')).casefold();want=profile.accent.casefold()
        evidence=' '.join(str(x) for x in [voice.get('description',''),*labels.values()]).casefold()
        score=(4 if want and want in accent else 0)+sum(1 for word in (profile.vocal_register+' '+profile.texture).casefold().split() if len(word)>3 and word in evidence)
        return score
    return sorted(voices,key=rank,reverse=True)


def generate_blueprint(brief: str, editor):
    return editor.structured('Create a production-ready SceneBlueprint from the brief. Preserve every explicitly required character, action and exact line in required_beats in chronological order, with stable IDs. Separate optional details. Provide detailed voice profiles, leaving voice_id empty unless supplied. Do not impersonate actors.\n'+brief, SceneBlueprint)


class BeatAssessment(BaseModel):
    beat_id: str
    satisfied: bool
    evidence: str
    issue: str

class ScriptAssessment(BaseModel):
    beats: list[BeatAssessment]
    dramatic_order_correct: bool
    issues: list[str]


def review_script(blueprint: SceneBlueprint, screenplay: SceneScreenplay, editor):
    assessment=editor.structured('Review this screenplay against every required beat. Assess actual meaning and physical action, not merely matching labels. Return one assessment per beat with specific event evidence. Flag omitted actions, incorrect consequences, speaker mistakes, and order errors. Distinguish creative interpretation from an actual required event.\nBlueprint: '+blueprint.model_dump_json()+'\nScreenplay: '+screenplay.model_dump_json(),ScriptAssessment)
    ids={beat.id for beat in blueprint.required_beats}
    checked={item.beat_id for item in assessment.beats}
    errors=[]
    if ids!=checked: errors.append('Independent review did not cover every required beat')
    if not assessment.dramatic_order_correct: errors.append('Independent review found incorrect order')
    errors.extend(item.beat_id+': '+item.issue for item in assessment.beats if not item.satisfied)
    errors.extend(assessment.issues)
    return assessment,errors


def draft(blueprint: SceneBlueprint, editor, max_attempts=2):
    feedback=''
    for _ in range(max_attempts):
        screenplay=editor.structured('Write a concise original audio screenplay as ordered events based on this blueprint. Use every required beat ID exactly once in order, match required speakers and required text verbatim. Physical actions must have acoustic expectation, physical action, consequence, and a standalone SFX prompt. Music and ambience start/stop are separate events; silence events contain seconds. Speech must be brief and interleaved with actions. Do not imitate actors.\nBlueprint: '+blueprint.model_dump_json()+'\nValidation errors to fix: '+feedback,SceneScreenplay)
        errors=validate_screenplay(blueprint,screenplay)
        if not errors:
            assessment,errors=review_script(blueprint,screenplay,editor)
            if not errors:return screenplay
        feedback='; '.join(errors)
    raise ValueError('Screenplay rejected before audio generation: '+feedback)


def produce_legacy(blueprint: SceneBlueprint, screenplay: SceneScreenplay, root: Path, provider, cover: Path, music_file: Path, ambience_file: Path):
    """Render ordered beats. Human review is required for casting and acoustics."""
    import shutil
    from .cinematic import cached
    errors=validate_screenplay(blueprint,screenplay)
    if errors: raise ValueError('Creative checks failed before paid audio: '+'; '.join(errors))
    profiles={p.character:p for p in blueprint.profiles}
    if any(not p.voice_id for p in profiles.values()):raise ValueError('All speaking profiles need a voice ID')
    root.mkdir(parents=True,exist_ok=True)
    atomic_write(root/'blueprint.json',blueprint.model_dump_json(indent=2).encode())
    atomic_write(root/'screenplay.json',screenplay.model_dump_json(indent=2).encode())
    provider.set_usage_log(UsageLog(root/'provider_usage.jsonl'))
    # Background assets are copied once, leaving the originals untouched.
    for source,name in [(music_file,'music.mp3'),(ambience_file,'ambience.mp3')]:
        target=root/name
        if not target.exists():shutil.copy2(source,target)
    cursor=0.0; background={}; completed=[];tracks=[];events=[]
    def close_background(kind):
        nonlocal cursor
        if kind in background:
            start=background.pop(kind)
            if cursor-start>0:completed.append((kind,start,cursor))
    for event in screenplay.events:
        start=cursor;asset=''
        if event.kind in ('music_start','ambience_start'):
            key=event.kind.split('_')[0]
            if key in background:raise ValueError('Duplicate active background: '+key)
            background[key]=cursor
        elif event.kind in ('music_stop','ambience_stop'):
            key=event.kind.split('_')[0]
            if key not in background:raise ValueError('Background stop without start: '+key)
            close_background(key)
        elif event.kind=='silence':
            if background:raise ValueError('Intentional silence requires stopping backgrounds')
            cursor+=event.duration_seconds
        elif event.kind in ('narration','dialogue','reaction'):
            profile=profiles[event.speaker]; path=root/'speech'/f'{event.id}.mp3';meta=root/'speech'/f'{event.id}.alignment.json'
            # Narrative objectives belong in the plan, not in speech tags: long
            # instructions may be spoken aloud by a TTS model. Use delivery only.
            tag=event.delivery.strip()
            text=(f'[{tag}] ' if tag else '')+event.text
            request=[{'text':text,'voice_id':profile.voice_id}]
            if not meta.exists() and path.exists():path.with_suffix('.mp3.sha256').unlink(missing_ok=True)
            cached(path,request,lambda:provider.dialogue(request,path,meta))
            length=duration(path);tracks.append(TimelineItem(path=str(path.relative_to(root)),start_seconds=cursor,duration_seconds=length,kind='narration'));cursor+=length;asset=str(path.relative_to(root))
        elif event.kind=='action':
            path=root/'sfx'/f'{event.id}.mp3'; length=event.duration_seconds or 2
            cached(path,[event.sound_prompt,length,provider.sfx_model],lambda:provider.effect(event.sound_prompt,length,path))
            length=duration(path);tracks.append(TimelineItem(path=str(path.relative_to(root)),start_seconds=cursor,duration_seconds=length,gain_db=4,kind='sfx'));cursor+=length;asset=str(path.relative_to(root))
        events.append({'event_id':event.id,'beat_id':event.beat_id,'kind':event.kind,'start_seconds':start,'end_seconds':cursor,'asset':asset})
    for key in list(background):close_background(key)
    # The existing renderer handles fades and a sidechain; repeat each available
    # background as needed, using a measured active-level gain with a cap.
    for kind,start,end in completed:
        path=root/('music.mp3' if kind=='music' else 'ambience.mp3')
        try:gain=max(-12,min(18,(-25 if kind=='music' else -32)-active_level(path)))
        except ValueError:raise ValueError('Background has no measurable active audio: '+kind)
        pos=start;span=duration(path)
        while pos<end:
            length=min(span,end-pos)
            tracks.append(TimelineItem(path=path.name,start_seconds=pos,duration_seconds=length,gain_db=gain,kind='music' if kind=='music' else 'sfx',fade_out_seconds=0 if kind=='music' and pos+length>=end else None))
            if pos+length>=end:break
            pos+=max(.1,length-.1)
    timeline=Timeline(items=tracks,duration_seconds=cursor)
    atomic_write(root/'timeline.json',timeline.model_dump_json(indent=2).encode())
    atomic_write(root/'cue_sheet.json',json.dumps({'events':events,'timeline':timeline.model_dump()},indent=2).encode())
    expected=[x.id for x in blueprint.required_beats];actual=[x['beat_id'] for x in events if x['beat_id'] in expected]
    if actual!=expected:raise ValueError('Required beat IDs missing or out of order in timeline')
    render(timeline,root,root/'master.mp3',ducking=True)
    planned_silence=[(e['start_seconds'],e['end_seconds']) for e in events if e['kind']=='silence']
    q=quality(root/'master.mp3',cover,cursor,allowed_silence=planned_silence)
    q['planned_silence']=planned_silence
    speaker_checks=[]
    for event in screenplay.events:
        if event.kind not in ('narration','dialogue','reaction'): continue
        meta=json.loads((root/'speech'/f'{event.id}.alignment.json').read_text())
        parts=meta.get('voice_segments') or []
        speaker_checks.append({'event_id':event.id,'speaker':event.speaker,'provider_voice_id_matches':bool(parts) and all(p.get('voice_id')==profiles[event.speaker].voice_id for p in parts)})
    q.update({'loudness':loudness(root/'master.mp3'),'deterministic':{'required_beats_in_order':True,'required_speakers_and_text':True,'timeline_beat_ids':actual,'speaker_metadata':speaker_checks},'subjective_review':{'casting':'pending human audition','acting':'pending human listening','acoustics':'pending human listening','music':'pending human listening','dramatic_effect':'pending human listening'},'limitations':['Required beat IDs demonstrate planned coverage, not semantic correctness or acoustic success.','Voice metadata and scripted tags cannot establish accent, depth or acting quality.','Individual dialogue turns are generated independently; conversational continuity needs human review.']})
    atomic_write(root/'creative_qa.json',json.dumps(q,indent=2).encode())
    return q


def produce(blueprint: SceneBlueprint, screenplay: SceneScreenplay, root: Path, provider, cover: Path, music_file: Path, ambience_file: Path, *, registry=None, scope: str = ''):
    """Default to contextual performance blocks; never silently recast."""
    errors=validate_screenplay(blueprint,screenplay)
    if errors:raise ValueError('Creative checks failed before paid audio: '+'; '.join(errors))
    if registry is None or not scope:raise ValueError('A persistent cast registry and scene scope are required')
    import shutil
    root.mkdir(parents=True,exist_ok=True)
    for source,name in ((music_file,'music.mp3'),(ambience_file,'ambience.mp3')):
        target=root/name
        if not target.exists():shutil.copy2(source,target)
    from .performance import produce_performance
    return produce_performance(blueprint,screenplay,root,provider,cover,registry,scope,generate_missing_actions=True)
