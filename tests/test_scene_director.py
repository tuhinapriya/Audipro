import pytest
from fablet.scene_director import VoiceProfile, RequiredBeat, SceneBlueprint, SceneScreenplay, DramaticEvent, validate_screenplay, validate_cast


def sample():
    profile=VoiceProfile(character='Harry',identity='child',age_range='young',accent='british',vocal_register='light',texture='clear',rhythm='quick',personality='curious',emotional_range='fear',pronunciation='english',voice_id='v')
    blueprint=SceneBlueprint(title='test',premise='test',setting='test',character_goals=[],emotional_states=[],escalation='rising',audience_emotion='surprise',climax='door',resolution='wonder',profiles=[profile],required_beats=[RequiredBeat(id='knock',description='knocks',allowed_types=['action']),RequiredBeat(id='line',description='line',allowed_types=['dialogue'],required_speaker='Harry',required_text='hello')])
    knock=DramaticEvent(id='e1',beat_id='knock',kind='action',physical_action='knocks',acoustic_expectation='three heavy knocks',consequence='door shakes',sound_prompt='three knocks')
    line=DramaticEvent(id='e2',beat_id='line',kind='dialogue',speaker='Harry',text='hello there')
    return blueprint,knock,line


def test_missing_and_reordered_required_beats():
    bp,a,b=sample();assert not validate_screenplay(bp,SceneScreenplay(events=[a,b]))
    assert any('Missing beat' in e for e in validate_screenplay(bp,SceneScreenplay(events=[a])))
    assert any('out of order' in e for e in validate_screenplay(bp,SceneScreenplay(events=[b,a])))


def test_wrong_speaker_and_omitted_action_detail():
    bp,a,b=sample();a.consequence='';b.speaker='Other'
    errors=validate_screenplay(bp,SceneScreenplay(events=[a,b]));assert any('physical action' in e for e in errors);assert any('incorrect speaker' in e for e in errors)


def test_casting_metadata_mismatch_is_reported():
    bp,_,_=sample();errors=validate_cast(bp.profiles[0],{'voice_id':'v','labels':{'accent':'american','age':'middle_aged'}})
    assert any('accent mismatch' in e for e in errors) and any('age mismatch' in e for e in errors)


def test_missing_required_acoustic_action_is_rejected():
    bp,a,b=sample();bp.required_beats[0].acoustic_expectation='three heavy knocks';a.acoustic_expectation='gentle creak';a.sound_prompt='quiet hinge'
    assert any('required acoustic expectation missing' in x for x in validate_screenplay(bp,SceneScreenplay(events=[a,b])))


def test_planned_silence_cannot_overlap_active_music():
    bp,_,_=sample();bp.required_beats=[]
    script=SceneScreenplay(events=[DramaticEvent(id='music',kind='music_start'),DramaticEvent(id='silence',kind='silence',duration_seconds=2)])
    assert any('silence overlaps' in x for x in validate_screenplay(bp,script))


def test_missing_beat_stops_before_provider_access(tmp_path):
    from fablet.scene_director import produce
    bp,a,_=sample()
    class NeverCall:
        def __getattribute__(self, name): raise AssertionError('Provider must not be called')
    with pytest.raises(ValueError,match='Creative checks failed'):
        produce(bp,SceneScreenplay(events=[a]),tmp_path,NeverCall(),tmp_path/'cover',tmp_path/'music',tmp_path/'ambience')
