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


def test_vocal_performance_round_trip_and_legacy_compatibility():
    from fablet.scene_director import VocalPerformance
    old=DramaticEvent.model_validate({'id':'old','kind':'dialogue','speaker':'Harry','text':'Hello','delivery':'whispering'})
    assert old.vocal_performance is None
    directed=old.model_copy(update={'vocal_performance':VocalPerformance(emotion='fearful',delivery='whispering')})
    restored=DramaticEvent.model_validate_json(directed.model_dump_json())
    assert restored.vocal_performance == VocalPerformance(emotion='fearful',delivery='whispering')
    assert VocalPerformance(emotion='a complicated, guarded hope').emotion == 'a complicated, guarded hope'
    with pytest.raises(ValueError):
        VocalPerformance.model_validate({'speed':1.2,'style':0.5})


def test_vocal_performance_rejected_on_non_speech_events():
    from fablet.scene_director import VocalPerformance
    bp,action,line=sample()
    action.vocal_performance=VocalPerformance(delivery='whispering')
    assert any('vocal performance' in error for error in validate_screenplay(bp,SceneScreenplay(events=[action,line])))


def test_extended_direction_round_trip_and_emphasis_validation():
    from fablet.scene_director import SpatialPosition, VocalPerformance
    bp,action,line=sample()
    line.vocal_performance=VocalPerformance(vocal_effort='soft',emotion='frightened',delivery_note='barely steady',distance='close',spatial_position=SpatialPosition(horizontal='left',reference='doorway'),acoustic_environment='stone hall',emphasis=['hello'])
    restored=DramaticEvent.model_validate_json(line.model_dump_json())
    assert restored.vocal_performance==line.vocal_performance
    assert not validate_screenplay(bp,SceneScreenplay(events=[action,restored]))
    restored.vocal_performance.emphasis=['hell']
    assert any('emphasis phrase not found' in error for error in validate_screenplay(bp,SceneScreenplay(events=[action,restored])))
    restored.vocal_performance.emphasis=['hello','hello there']
    assert any('overlapping emphasis' in error for error in validate_screenplay(bp,SceneScreenplay(events=[action,restored])))
    for kwargs in ({'vocal_effort':'loud'}, {'distance':'far'}, {'spatial_position':{'horizontal':'behind'}}):
        with pytest.raises(ValueError):VocalPerformance(**kwargs)
