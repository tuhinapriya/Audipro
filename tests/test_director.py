from fablet.director import Anchor, AudioDirectionPlan, DirectionCue, compile_plan, resolve
from fablet.models import GainPoint, TimelineItem
from fablet.audio import volume_filter
import pytest


def test_phrase_anchors_require_alignment_and_never_guess():
    segments = {'s': {'start_seconds': 4, 'duration_seconds': 10}}
    anchor = Anchor(segment_id='s', point='phrase', phrase='the end')
    assert resolve(anchor, segments, {}) is None
    assert resolve(anchor, segments, {'s':[{'word':'the','start':1}, {'word':'end','start':1.2}]}) == 5


def test_unresolved_cue_is_reported_not_placed():
    cue = DirectionCue(id='x',kind='sfx',asset='sfx/x.mp3',start=Anchor(segment_id='s',point='phrase',phrase='missing'),end=Anchor(segment_id='s',point='end'),purpose='test')
    plan = AudioDirectionPlan(scene_objectives=[],emotional_intensity=[],narration_pacing=[],motifs=[],cues=[cue],mixing_priorities=[])
    cues, errors = compile_plan(plan,[{'path':'narration/s.mp3','start_seconds':1,'duration_seconds':3}])
    assert not cues and errors[0]['cue']=='x'


def test_envelope_rejects_non_monotonic_points():
    item = TimelineItem(path='x', start_seconds=0,duration_seconds=2,kind='music',gain_envelope=[GainPoint(time_seconds=1,gain_db=0),GainPoint(time_seconds=1,gain_db=-3)])
    with pytest.raises(ValueError): volume_filter(item)
