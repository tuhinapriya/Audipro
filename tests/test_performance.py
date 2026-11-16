import json
import pytest
from fablet.casting import CastEntry, CastRegistry
from fablet.performance import group_events, align_block
from fablet.scene_director import DramaticEvent
from fablet.speech_qa import compare


def event(id,kind,speaker='',text=''):
    return DramaticEvent(id=id,kind=kind,speaker=speaker,text=text)


def test_narrator_lock_persists_and_prevents_recasting(tmp_path):
    registry=CastRegistry(entries={'narrator':CastEntry(character_id='narrator',voice_id='george',status='locked',selection='user_approved')})
    p=tmp_path/'cast.json';registry.save(p);loaded=CastRegistry.load(p)
    with pytest.raises(ValueError,match='Locked voice'):loaded.choose('narrator',CastEntry(character_id='narrator',voice_id='other',selection='automatically_selected'))
    assert loaded.entries['narrator'].voice_id=='george'
    with pytest.raises(ValueError,match='unavailable'):loaded.assert_available({'other'})


def test_dialogue_blocks_break_on_action_and_narration():
    events=[event('a','dialogue','A','Hello'),event('b','reaction','B','Yes'),event('c','action'),event('d','dialogue','A','Again'),event('e','narration','Narrator','Then')]
    assert [[e.id for e in b] for b in group_events(events)]==[['a','b'],['c'],['d'],['e']]


def test_alignment_uses_provider_times_and_flags_missing():
    block=[event('a','dialogue','A','Hello'),event('b','dialogue','B','Hi')]
    aligned,issues=align_block(block,[{'dialogue_input_index':0,'start_time_seconds':.2,'end_time_seconds':1,'voice_id':'v1'}],3)
    assert aligned[0]['start_seconds']==.2 and aligned[0]['voice_ids']==['v1']
    assert any('b: missing alignment' in x for x in issues)


def test_repetition_and_missing_words_and_intentional_repetition():
    times=[{'start':i,'end':i+.5} for i in range(4)]
    result=compare('avada kedavra','avada kedavra avada kedavra',times)
    assert result['repeated_phrases'][0]['start_seconds']==2
    assert compare('please stay here','please here')['uncertain']
    assert not compare('no no no no','no no no no')['repeated_phrases']


def test_retry_reuses_unaffected_performance(tmp_path, monkeypatch):
    import subprocess
    from fablet.performance import _perform
    from fablet.usage import UsageLog
    class FakeProvider:
        tts_model='eleven_v4'
        calls=0
        def dialogue(self,inputs,path,meta):
            self.calls+=1
            path.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=1','-c:a','libmp3lame',str(path)],check=True)
            meta.write_text(json.dumps({'voice_segments':[{'dialogue_input_index':0,'start_time_seconds':0,'end_time_seconds':.9,'voice_id':inputs[0]['voice_id']}]}))
    seen=[]
    def fake_asr(path,log):
        seen.append(path)
        return ('hello there hello there',[]) if 'attempt1' in path.name else ('hello there',[])
    monkeypatch.setattr('fablet.performance.transcribe',fake_asr)
    monkeypatch.setattr('fablet.performance.transcribe_secondary',lambda path,log:'hello there')
    registry=CastRegistry(entries={'scene:A':CastEntry(character_id='scene:A',voice_id='v',status='locked',selection='automatically_selected')})
    provider=FakeProvider();block=[event('a','dialogue','A','hello there')]
    _,review,alignment,issues=_perform(block,tmp_path,provider,registry,'scene',UsageLog(tmp_path/'usage'))
    assert review['attempt']==2 and provider.calls==2 and not issues and alignment[0]['speaker']=='A'
    _perform(block,tmp_path,provider,registry,'scene',UsageLog(tmp_path/'usage'))
    assert provider.calls==2 and len(seen)==2


def test_nonadjacent_repeated_phrase_is_flagged_without_banning_scripted_repeats():
    result=compare('the gate will open soon','the gate will open then the gate will open soon')
    assert result['repeated_phrases']
    assert not compare('the gate the gate','the gate the gate')['repeated_phrases']


def test_multispeaker_block_preserves_cast_and_timestamps(tmp_path, monkeypatch):
    import subprocess
    from fablet.performance import _perform
    from fablet.usage import UsageLog
    class FakeProvider:
        tts_model='eleven_v4'
        inputs=None
        def dialogue(self,inputs,path,meta):
            self.inputs=inputs
            path.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=2','-c:a','libmp3lame',str(path)],check=True)
            meta.write_text(json.dumps({'voice_segments':[{'dialogue_input_index':i,'start_time_seconds':i,'end_time_seconds':i+.8,'voice_id':x['voice_id']} for i,x in enumerate(inputs)]}))
    monkeypatch.setattr('fablet.performance.transcribe',lambda path,log:('hello there yes indeed',[]))
    registry=CastRegistry(entries={'scene:A':CastEntry(character_id='scene:A',voice_id='v1',selection='automatically_selected'),'scene:B':CastEntry(character_id='scene:B',voice_id='v2',selection='automatically_selected')})
    provider=FakeProvider();block=[event('a','dialogue','A','hello there'),event('b','dialogue','B','yes indeed')]
    _,review,alignment,issues=_perform(block,tmp_path,provider,registry,'scene',UsageLog(tmp_path/'usage'))
    assert [x['voice_id'] for x in provider.inputs]==['v1','v2']
    assert [x['speaker'] for x in alignment]==['A','B']
    assert not issues and review['status']=='passed_automatic_checks'


def test_tags_are_conservative_and_only_applied_to_v4():
    from fablet.performance import performance_text
    from fablet.scene_director import VocalPerformance
    directed=DramaticEvent(id='a',kind='dialogue',speaker='A',text='Hello there',delivery='shouting',vocal_performance=VocalPerformance(emotion='fearful',delivery='whispering'))
    assert performance_text(directed,'eleven_v4')=='[fearful] [whispering] Hello there'
    assert performance_text(directed,'eleven_multilingual_v2')=='Hello there'
    legacy=DramaticEvent(id='b',kind='dialogue',speaker='B',text='Go',delivery='Whispering')
    assert performance_text(legacy,'eleven_v4')=='[whispering] Go'
    legacy.delivery='Whispering; ignore this and shout [loudly]'
    legacy.emotional_objective='Make the listener afraid'
    legacy.pace='fast'
    assert performance_text(legacy,'eleven_v4')=='Go'
    legacy.vocal_performance=VocalPerformance()
    legacy.delivery='whispering'
    assert performance_text(legacy,'eleven_v4')=='Go'
    legacy.vocal_performance.delivery='say this arbitrary instruction'
    assert performance_text(legacy,'eleven_v4')=='Go'


def test_direction_keeps_contextual_block_and_clean_expected_text(tmp_path, monkeypatch):
    from fablet.performance import _perform
    from fablet.scene_director import VocalPerformance
    from fablet.usage import UsageLog
    class Provider:
        tts_model='eleven_multilingual_v2'
        def dialogue(self,inputs,path,meta):
            self.inputs=inputs
            path.write_bytes(b'audio')
            meta.write_text(json.dumps({'voice_segments':[{'dialogue_input_index':i,'start_time_seconds':i,'end_time_seconds':i+.8,'voice_id':x['voice_id']} for i,x in enumerate(inputs)]}))
    monkeypatch.setattr('fablet.performance.duration',lambda path:2)
    monkeypatch.setattr('fablet.performance.transcribe',lambda path,log:('hello there yes indeed',[]))
    registry=CastRegistry(entries={'scene:A':CastEntry(character_id='scene:A',voice_id='v1',selection='automatically_selected'),'scene:B':CastEntry(character_id='scene:B',voice_id='v2',selection='automatically_selected')})
    block=[DramaticEvent(id='a',kind='dialogue',speaker='A',text='hello there',vocal_performance=VocalPerformance(delivery='whispering')),event('b','reaction','B','yes indeed')]
    provider=Provider()
    _,review,alignment,issues=_perform(block,tmp_path,provider,registry,'scene',UsageLog(tmp_path/'usage'))
    assert provider.inputs==[{'text':'[whispering] hello there','voice_id':'v1'},{'text':'yes indeed','voice_id':'v2'}]
    assert review['expected']=='hello there yes indeed'
    assert len(alignment)==2 and not issues


def test_regeneration_invalidates_primary_and_secondary_asr(tmp_path, monkeypatch):
    from fablet.performance import _perform
    from fablet.usage import UsageLog
    class Provider:
        tts_model='eleven_v4'
        calls=0
        def dialogue(self,inputs,path,meta):
            self.calls+=1
            path.write_bytes(f'audio{self.calls}'.encode())
            meta.write_text(json.dumps({'voice_segments':[{'dialogue_input_index':0,'start_time_seconds':0,'end_time_seconds':.8,'voice_id':'v'}]}))
    calls=[];secondary=[]
    monkeypatch.setattr('fablet.performance.duration',lambda path:1)
    monkeypatch.setattr('fablet.performance.transcribe',lambda path,log:(calls.append(path.read_bytes()) or 'different',[]))
    monkeypatch.setattr('fablet.performance.transcribe_secondary',lambda path,log:secondary.append(path.read_bytes()) or 'different')
    registry=CastRegistry(entries={'scene:A':CastEntry(character_id='scene:A',voice_id='v',selection='automatically_selected')})
    provider=Provider();block=[event('a','dialogue','A','hello')];log=UsageLog(tmp_path/'usage')
    stem,_,_,_=_perform(block,tmp_path,provider,registry,'scene',log)
    stem.with_suffix('.json').unlink()
    _perform(block,tmp_path,provider,registry,'scene',log)
    assert calls==[b'audio1',b'audio2'] and secondary==[b'audio1',b'audio2']


@pytest.mark.parametrize('model,expected', [('eleven_v4','[softly] A quiet line'),('eleven_multilingual_v2','A quiet line')])
def test_narration_uses_selected_model_and_restores_voice(tmp_path,monkeypatch,model,expected):
    from fablet.performance import _perform
    from fablet.scene_director import VocalPerformance
    from fablet.usage import UsageLog
    class Provider:
        voice='original'
        tts_model=model
        def narrate(self,text,previous,following,path):
            self.request=(self.voice,text,previous,following)
            path.write_bytes(b'audio')
    monkeypatch.setattr('fablet.performance.transcribe',lambda path,log:('A quiet line',[]))
    registry=CastRegistry(entries={'narrator':CastEntry(character_id='narrator',voice_id='n',selection='automatically_selected')})
    block=[DramaticEvent(id='n',kind='narration',speaker='Narrator',text='A quiet line',vocal_performance=VocalPerformance(delivery='softly'))]
    provider=Provider()
    _,review,alignment,issues=_perform(block,tmp_path,provider,registry,'scene',UsageLog(tmp_path/'usage'))
    assert provider.request==('n',expected,'','') and provider.voice=='original'
    assert review['expected']=='A quiet line' and not alignment and not issues


def test_asr_cache_tracks_external_audio_changes_and_old_caches(tmp_path,monkeypatch):
    from fablet.performance import _perform
    from fablet.usage import UsageLog
    class Provider:
        tts_model='eleven_v4'
        calls=0
        def dialogue(self,inputs,path,meta):
            self.calls+=1;path.write_bytes(b'first')
            meta.write_text(json.dumps({'voice_segments':[{'dialogue_input_index':0,'start_time_seconds':0,'end_time_seconds':.8,'voice_id':'v'}]}))
    calls=[];secondary=[]
    monkeypatch.setattr('fablet.performance.duration',lambda path:1)
    monkeypatch.setattr('fablet.performance.transcribe',lambda path,log:(calls.append(path.read_bytes()) or 'different',[]))
    monkeypatch.setattr('fablet.performance.transcribe_secondary',lambda path,log:secondary.append(path.read_bytes()) or 'different')
    registry=CastRegistry(entries={'scene:A':CastEntry(character_id='scene:A',voice_id='v',selection='automatically_selected')})
    provider=Provider();block=[event('a','dialogue','A','hello')];log=UsageLog(tmp_path/'usage')
    stem,_,_,_=_perform(block,tmp_path,provider,registry,'scene',log)
    stem.with_suffix('.asr.json').write_text(json.dumps({'transcript':'old','word_times':[]}))
    _perform(block,tmp_path,provider,registry,'scene',log)
    stem.write_bytes(b'second')
    _perform(block,tmp_path,provider,registry,'scene',log)
    assert provider.calls==1 and calls==[b'first',b'first',b'second'] and secondary==[b'first',b'second']


def test_changing_direction_invalidates_only_that_block_cache(tmp_path,monkeypatch):
    from fablet.performance import _perform
    from fablet.scene_director import VocalPerformance
    from fablet.usage import UsageLog
    class Provider:
        tts_model='eleven_v4'
        calls=[]
        def dialogue(self,inputs,path,meta):
            self.calls.append(inputs)
            path.write_bytes(b'audio')
            meta.write_text(json.dumps({'voice_segments':[{'dialogue_input_index':0,'start_time_seconds':0,'end_time_seconds':.8,'voice_id':'v'}]}))
    monkeypatch.setattr('fablet.performance.duration',lambda path:1)
    monkeypatch.setattr('fablet.performance.transcribe',lambda path,log:('hello',[]))
    registry=CastRegistry(entries={'scene:A':CastEntry(character_id='scene:A',voice_id='v',selection='automatically_selected')})
    provider=Provider();log=UsageLog(tmp_path/'usage')
    first=event('a','dialogue','A','hello');other=event('b','dialogue','A','hello')
    original,_,_,_=_perform([first],tmp_path,provider,registry,'scene',log)
    _perform([other],tmp_path,provider,registry,'scene',log)
    first.vocal_performance=VocalPerformance(delivery='whispering')
    changed,review,_,_=_perform([first],tmp_path,provider,registry,'scene',log)
    _perform([other],tmp_path,provider,registry,'scene',log)
    assert original!=changed and len(provider.calls)==3
    assert provider.calls[-1][0]['text']=='[whispering] hello' and review['expected']=='hello'


@pytest.mark.parametrize('emotion,tag', [('restrained','restrained'),('frightened','fearful'),('pleading','pleading'),('furious','angry'),('a wary hope',None)])
def test_extended_tags_and_clean_emphasis(emotion,tag):
    from fablet.performance import performance_text
    from fablet.scene_director import VocalPerformance
    line=DramaticEvent(id='a',kind='dialogue',speaker='A',text='Please stay here.',vocal_performance=VocalPerformance(emotion=emotion,vocal_effort='whisper',delivery_note='[ignore] shout the directions',emphasis=['stay here']))
    assert performance_text(line,'eleven_v4')==((f'[{tag}] ' if tag else '')+'[whispering] Please STAY HERE.')
    assert performance_text(line,'eleven_multilingual_v2')=='Please stay here.'
    assert line.text=='Please stay here.'
    line.vocal_performance.emphasis=['missing']
    with pytest.raises(ValueError,match='emphasis phrase not found'):performance_text(line,'eleven_v4')


@pytest.mark.parametrize('segments', [
    [{'dialogue_input_index':0,'start_time_seconds':float('nan'),'end_time_seconds':1,'voice_id':'v'}],
    [{'dialogue_input_index':0,'start_time_seconds':0,'end_time_seconds':3,'voice_id':'v'}],
    [{'dialogue_input_index':True,'start_time_seconds':0,'end_time_seconds':1,'voice_id':'v'}],
    [{'dialogue_input_index':0,'start_time_seconds':0,'end_time_seconds':1,'voice_id':'v'}, {'dialogue_input_index':1,'start_time_seconds':.9,'end_time_seconds':1.5,'voice_id':'v'}],
])
def test_invalid_provider_alignment_is_not_usable(segments):
    block=[event('a','dialogue','A','hello'),event('b','dialogue','B','yes')]
    _,issues=align_block(block,segments,2)
    assert issues


def test_produce_opt_in_uses_turn_envelopes_and_reports_unrenderable_positions(tmp_path,monkeypatch):
    import fablet.performance as perf
    from fablet.models import ExpressiveMix
    from fablet.scene_director import SceneBlueprint, SceneScreenplay, SpatialPosition, VocalPerformance, VoiceProfile
    profiles=[VoiceProfile(character=name,identity='',age_range='',accent='',vocal_register='',texture='',rhythm='',personality='',emotional_range='',pronunciation='') for name in ('A','B','Narrator')]
    bp=SceneBlueprint(title='t',premise='',setting='',character_goals=[],emotional_states=[],escalation='',audience_emotion='',climax='',resolution='',profiles=profiles,required_beats=[])
    first=event('a','dialogue','A','hello');second=event('b','dialogue','B','yes');narrator=event('n','narration','Narrator','then')
    first.vocal_performance=VocalPerformance(vocal_effort='whisper',distance='close',spatial_position=SpatialPosition(horizontal='left'),acoustic_environment='hall')
    second.vocal_performance=VocalPerformance(vocal_effort='shout',spatial_position=SpatialPosition(horizontal='right'))
    screenplay=SceneScreenplay(events=[first,second,narrator])
    registry=CastRegistry(entries={key:CastEntry(character_id=key,voice_id=key,selection='automatically_selected') for key in ('scene:A','scene:B','narrator')})
    for name in ('music.mp3','ambience.mp3'):(tmp_path/name).write_bytes(b'audio')
    class HTTP:
        def get(self,path):return type('Response',(),{'is_error':False})()
    class Provider:
        http=HTTP()
        def set_usage_log(self,log):pass
    def perform(block,work,*args):
        stem=work/(block[0].id+'.mp3');stem.write_bytes(b'audio')
        alignment=[] if block[0].kind=='narration' else [dict(event_id=e.id,speaker=e.speaker,start_seconds=i,end_seconds=i+.8,voice_ids=[f'scene:{e.speaker}']) for i,e in enumerate(block)]
        return stem,{},alignment,[]
    captured=[]
    monkeypatch.setattr(perf,'_perform',perform)
    monkeypatch.setattr(perf,'duration',lambda path:2)
    monkeypatch.setattr(perf,'render',lambda timeline,root,target,**kwargs:captured.append((timeline,kwargs)))
    monkeypatch.setattr(perf,'quality',lambda *args,**kwargs:{})
    monkeypatch.setattr(perf,'loudness',lambda path:-16)
    monkeypatch.setattr(perf,'transcribe',lambda path,log:('hello yes then',[]))
    original=ExpressiveMix()
    report=perf.produce_performance(bp,screenplay,tmp_path,Provider(),tmp_path/'cover',registry,'scene',expressive_mix=original)
    timeline,kwargs=captured[-1];mix=kwargs['expressive_mix']
    assert len(timeline.items)==2 and timeline.items[0].path.endswith('a.mp3')
    points=timeline.items[0].gain_envelope
    assert any(p.gain_db==-4 and 0<p.time_seconds<.8 for p in points)
    assert any(p.gain_db==3 and 1<p.time_seconds<1.8 for p in points)
    assert all(a.time_seconds<b.time_seconds for a,b in zip(points,points[1:]))
    assert 0 not in mix.items and mix.items[1].spatial.pan==0
    assert not original.items
    assert any('per-turn' in issue for issue in report['unresolved_performance'])
    assert any('acoustic environment' in issue for issue in report['unresolved_performance'])
    cue=json.loads((tmp_path/'performance_fixed'/'cue_sheet.json').read_text())
    assert cue['unresolved_performance']==report['unresolved_performance']
    perf.produce_performance(bp,screenplay,tmp_path,Provider(),tmp_path/'cover',registry,'scene')
    legacy,kwargs=captured[-1]
    assert 'expressive_mix' not in kwargs and not legacy.items[0].gain_envelope
    assert 'unresolved_performance' not in json.loads((tmp_path/'performance_fixed'/'cue_sheet.json').read_text())


def test_directed_mix_requires_valid_alignment_and_only_applies_shared_positions():
    from fablet.performance import _directed_mix
    from fablet.scene_director import SpatialPosition, VocalPerformance
    first=event('a','dialogue','A','hello');second=event('b','dialogue','B','yes')
    for line in (first,second):line.vocal_performance=VocalPerformance(vocal_effort='soft',spatial_position=SpatialPosition(horizontal='left'))
    alignment=[{'start_seconds':0,'end_seconds':.8},{'start_seconds':1,'end_seconds':1.8}]
    points,spatial,issues=_directed_mix([first,second],2,alignment,[])
    assert points and spatial.pan==-.6 and not issues
    points,spatial,issues=_directed_mix([first,second],2,alignment,['speaker metadata mismatch'])
    assert not points and spatial is None and any('alignment is invalid' in x for x in issues)
    second.vocal_performance.spatial_position=None
    _,spatial,issues=_directed_mix([first,second],2,alignment,[])
    assert spatial is None and any('partially specified' in x for x in issues)


def test_provider_voice_mismatch_disables_turn_automation(tmp_path,monkeypatch):
    import fablet.performance as perf
    from fablet.scene_director import VocalPerformance
    from fablet.usage import UsageLog
    class Provider:
        tts_model='eleven_v4'
        def dialogue(self,inputs,path,meta):
            path.write_bytes(b'audio')
            meta.write_text(json.dumps({'voice_segments':[{'dialogue_input_index':0,'start_time_seconds':0,'end_time_seconds':.8,'voice_id':'wrong'}]}))
    monkeypatch.setattr(perf,'duration',lambda path:1)
    monkeypatch.setattr(perf,'transcribe',lambda path,log:('hello',[]))
    registry=CastRegistry(entries={'scene:A':CastEntry(character_id='scene:A',voice_id='v',selection='automatically_selected')})
    line=event('a','dialogue','A','hello');line.vocal_performance=VocalPerformance(vocal_effort='shout')
    _,_,alignment,issues=perf._perform([line],tmp_path,Provider(),registry,'scene',UsageLog(tmp_path/'usage'))
    assert any('speaker metadata mismatch' in x for x in issues)
    points,spatial,unresolved=perf._directed_mix([line],1,alignment,issues)
    assert not points and spatial is None and unresolved


def test_turn_envelope_render_preserves_source_dynamics(tmp_path):
    import array
    import math
    import subprocess
    import wave
    from fablet.audio import render
    from fablet.models import ExpressiveMix, Timeline, TimelineItem
    from fablet.performance import _directed_mix
    from fablet.scene_director import VocalPerformance
    source=tmp_path/'block.wav'
    signal=array.array('h', (round((8000 if n<96000 else 2000)*math.sin(2*math.pi*440*n/48000)) for n in range(192000)))
    with wave.open(str(source),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(48000);wav.writeframes(signal.tobytes())
    a=event('a','dialogue','A','hello');b=event('b','dialogue','B','yes')
    a.vocal_performance=VocalPerformance(vocal_effort='whisper')
    b.vocal_performance=VocalPerformance(vocal_effort='shout')
    points,_,issues=_directed_mix([a,b],4,[{'start_seconds':0,'end_seconds':2},{'start_seconds':2,'end_seconds':4}],[])
    assert not issues
    timeline=Timeline(duration_seconds=4,items=[TimelineItem(path=source.name,start_seconds=0,duration_seconds=4,kind='narration',gain_envelope=points)])
    output=tmp_path/'render.mp3'
    render(timeline,tmp_path,output,ducking=False,expressive_mix=ExpressiveMix())
    pcm=subprocess.run(['ffmpeg','-v','error','-i',str(output),'-f','f32le','-ac','1','-ar','48000','-'],check=True,capture_output=True).stdout
    samples=array.array('f');samples.frombytes(pcm)
    def rms(start):
        window=samples[round(start*48000):round((start+.5)*48000)]
        return math.sqrt(sum(x*x for x in window)/len(window))
    assert 20*math.log10(rms(2.5)/rms(.5))==pytest.approx(20*math.log10(.25)+6,abs=1)
