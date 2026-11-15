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
