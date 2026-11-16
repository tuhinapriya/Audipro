import array
import math
import subprocess
import wave

import pytest

from fablet.audio import duration, render
from fablet.models import (
    ExpressiveItemMix, ExpressiveMix, GainPoint, SpatialMix, Timeline, TimelineItem,
)


def tone(path, frequency, seconds=6, volume=1):
    subprocess.run([
        'ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i',
        f'sine=frequency={frequency}:sample_rate=48000:duration={seconds}',
        '-af', f'volume={volume}', '-c:a', 'pcm_s16le', str(path),
    ], check=True)


def item(path, kind, start=0, length=6, **kwargs):
    return TimelineItem(path=path, kind=kind, start_seconds=start,
                        duration_seconds=length, fade_in_seconds=0,
                        fade_out_seconds=0, **kwargs)


def samples(path):
    result = subprocess.run([
        'ffmpeg', '-v', 'error', '-i', str(path), '-f', 'f32le',
        '-acodec', 'pcm_f32le', '-ac', '2', '-ar', '48000', '-',
    ], check=True, capture_output=True)
    data = array.array('f')
    data.frombytes(result.stdout)
    return data


def amplitude(data, frequency, start, length=0.5, channel=0):
    begin, count = round(start * 48000), round(length * 48000)
    real = imag = 0.0
    for n in range(begin, begin + count):
        phase = 2 * math.pi * frequency * n / 48000
        value = data[2 * n + channel]
        real += value * math.cos(phase)
        imag += value * math.sin(phase)
    return 2 * math.hypot(real, imag) / count


def test_default_path_and_timeline_serialization_unchanged(tmp_path, monkeypatch):
    import fablet.audio as audio
    timeline = Timeline(duration_seconds=2, items=[
        item('voice.wav', 'narration', length=2), item('music.wav', 'music', length=2),
        item('ambience.wav', 'sfx', length=2),
    ])
    assert set(timeline.model_dump()['items'][0]) == {
        'path', 'start_seconds', 'duration_seconds', 'gain_db', 'kind',
        'gain_envelope', 'fade_in_seconds', 'fade_out_seconds',
    }
    commands = []
    monkeypatch.setattr(audio, 'validate_timeline', lambda *args: None)
    monkeypatch.setattr(audio, 'run', lambda *args: commands.append(args))
    render(timeline, tmp_path, tmp_path/'default.mp3')
    graph = commands[-1][commands[-1].index('-filter_complex') + 1]
    assert 'sidechaincompress=threshold=0.01:ratio=8:attack=20:release=300' in graph
    assert 'aecho=' not in graph and 'pan=stereo' not in graph
    assert 'apad=whole_len=96000,atrim=end_sample=96000' in graph
    render(timeline, tmp_path, tmp_path/'default.mp3', ducking=False)
    graph = commands[-1][commands[-1].index('-filter_complex') + 1]
    assert 'sidechaincompress' not in graph


def test_quiet_speech_ducks_music_and_explicit_ambience_not_foreground(tmp_path):
    for name, frequency in [('voice', 900), ('music', 300), ('ambience', 500), ('effect', 700)]:
        tone(tmp_path/f'{name}.wav', frequency)
    timeline = Timeline(duration_seconds=6, items=[
        item('voice.wav', 'narration', start=2, length=2, gain_db=-50),
        item('music.wav', 'music'),
        item('ambience.wav', 'sfx', start=0.5, length=5),
        item('effect.wav', 'sfx'),
    ])
    config = ExpressiveMix(items={2: ExpressiveItemMix(ambience=True)}, duck_gain_db=-12)
    output = tmp_path/'ducked.mp3'
    render(timeline, tmp_path, output, expressive_mix=config)
    data = samples(output)
    for frequency in (300, 500):
        before = amplitude(data, frequency, 1) / amplitude(data, 700, 1)
        during = amplitude(data, frequency, 3) / amplitude(data, 700, 3)
        after = amplitude(data, frequency, 4.7) / amplitude(data, 700, 4.7)
        assert 20 * math.log10(during / before) == pytest.approx(-12, abs=0.8)
        assert after / before == pytest.approx(1, abs=0.06)
    assert abs(duration(output) - 6) < 0.1

    render(timeline, tmp_path, output, expressive_mix=config, ducking=False)
    data = samples(output)
    for frequency in (300, 500):
        before = amplitude(data, frequency, 1) / amplitude(data, 700, 1)
        during = amplitude(data, frequency, 3) / amplitude(data, 700, 3)
        assert during / before == pytest.approx(1, abs=0.06)


def test_offsets_preserve_relative_dynamics_and_combine_with_envelope(tmp_path):
    tone(tmp_path/'loud.wav', 400, 2)
    tone(tmp_path/'quiet.wav', 400, 2, volume=0.25)
    tone(tmp_path/'reference.wav', 800)
    timeline = Timeline(duration_seconds=6, items=[
        item('loud.wav', 'narration', start=1, length=2, gain_db=-3,
             gain_envelope=[GainPoint(time_seconds=0, gain_db=-3)]),
        item('quiet.wav', 'narration', start=3, length=2, gain_db=-3,
             gain_envelope=[GainPoint(time_seconds=0, gain_db=-3)]),
        item('reference.wav', 'sfx'),
    ])
    config = ExpressiveMix(items={0: ExpressiveItemMix(gain_offset_db=6),
                                  1: ExpressiveItemMix(gain_offset_db=6)})
    output = tmp_path/'levels.mp3'
    render(timeline, tmp_path, output, expressive_mix=config)
    data = samples(output)
    loud = amplitude(data, 400, 1.5) / amplitude(data, 800, 1.5)
    quiet = amplitude(data, 400, 3.5) / amplitude(data, 800, 3.5)
    assert 20 * math.log10(loud) == pytest.approx(0, abs=0.7)
    assert 20 * math.log10(quiet / loud) == pytest.approx(20 * math.log10(.25), abs=0.7)


def test_duck_ramps_overlap_without_stacking_and_recover(tmp_path):
    tone(tmp_path/'voice.wav', 900, 1)
    tone(tmp_path/'music.wav', 300, 5)
    tone(tmp_path/'effect.wav', 700, 5)
    timeline = Timeline(duration_seconds=5, items=[
        item('voice.wav', 'narration', start=1, length=1, gain_db=-50),
        item('voice.wav', 'narration', start=2.2, length=1, gain_db=-50),
        item('music.wav', 'music', length=5), item('effect.wav', 'sfx', length=5),
    ])
    output = tmp_path/'ramps.mp3'
    config = ExpressiveMix(duck_gain_db=-12, attack_seconds=.5, release_seconds=.5)
    render(timeline, tmp_path, output, expressive_mix=config)
    data = samples(output)
    def relative(start, length=.1):
        return amplitude(data, 300, start, length) / amplitude(data, 700, start, length)
    base = relative(.2)
    assert 20 * math.log10(relative(1.3) / base) == pytest.approx(-12, abs=1)
    assert 20 * math.log10(relative(2.05) / base) == pytest.approx(-9.6, abs=1.5)
    assert relative(4) / base == pytest.approx(1, abs=.06)


def test_spatial_balance_and_distance_apply_per_item(tmp_path):
    tone(tmp_path/'voice.wav', 400, 3)
    tone(tmp_path/'reference.wav', 800, 3)
    timeline = Timeline(duration_seconds=3, items=[item('voice.wav', 'narration', length=3),
                                                  item('reference.wav', 'sfx', length=3)])
    config = ExpressiveMix(items={0: ExpressiveItemMix(spatial=SpatialMix(pan=-1, distance=2))})
    output = tmp_path/'spatial.mp3'
    render(timeline, tmp_path, output, expressive_mix=config)
    data = samples(output)
    left = amplitude(data, 400, 1, channel=0) / amplitude(data, 800, 1, channel=0)
    right = amplitude(data, 400, 1, channel=1) / amplitude(data, 800, 1, channel=1)
    assert left == pytest.approx(math.sqrt(2) / 2, abs=0.05)
    assert right < 0.02


def test_spatial_placement_retains_opposite_stereo_channel(tmp_path):
    pcm = array.array('h')
    for n in range(2 * 48000):
        pcm.extend((0, round(10000 * math.sin(2 * math.pi * 400 * n / 48000))))
    with wave.open(str(tmp_path/'stereo.wav'), 'wb') as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(pcm.tobytes())
    timeline = Timeline(duration_seconds=2, items=[item('stereo.wav', 'narration', length=2)])
    output = tmp_path/'placed.mp3'
    render(timeline, tmp_path, output, expressive_mix=ExpressiveMix(
        items={0: ExpressiveItemMix(spatial=SpatialMix(pan=-1))}))
    data = samples(output)
    assert amplitude(data, 400, .5, channel=0) > .02
    assert amplitude(data, 400, .5, channel=1) < .002


def test_reflections_are_opt_in_bounded_and_renderable(tmp_path, monkeypatch):
    import fablet.audio as audio
    pcm = array.array('h', [0] * (2 * 48000))
    for n in range(round(.5 * 48000), round(.52 * 48000)):
        pcm[n] = round(10000 * math.sin(2 * math.pi * 1000 * n / 48000))
    for n in range(round(1.98 * 48000), 2 * 48000):
        pcm[n] = round(10000 * math.sin(2 * math.pi * 1000 * n / 48000))
    with wave.open(str(tmp_path/'voice.wav'), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(pcm.tobytes())
    timeline = Timeline(duration_seconds=2.5, items=[item('voice.wav', 'narration', length=2)])
    commands = []
    original_run = audio.run
    def capture(*args):
        commands.append(args)
        return original_run(*args)
    monkeypatch.setattr(audio, 'run', capture)
    config = ExpressiveMix(items={0: ExpressiveItemMix(spatial=SpatialMix(reflection=.2, reflection_delay_ms=80))})
    output = tmp_path/'reflected.mp3'
    render(timeline, tmp_path, output, expressive_mix=config)
    command = next(c for c in commands if c[0] == 'ffmpeg')
    graph = command[command.index('-filter_complex') + 1]
    assert 'aecho=1:1:80:0.2,atrim=duration=2.0' in graph
    assert abs(duration(output) - 2.5) < .1
    data = samples(output)
    direct = amplitude(data, 1000, .5, length=.02)
    echo = amplitude(data, 1000, .58, length=.02)
    assert echo / direct == pytest.approx(.2, abs=.04)
    assert amplitude(data, 1000, 2.06, length=.02) < direct * .03
    assert max(abs(data[i]) for i in range(2 * 105600, 2 * 110400)) < 0.001


def test_config_validation_and_invalid_item_bindings(tmp_path, monkeypatch):
    import fablet.audio as audio
    for kwargs in ({'pan': float('nan')}, {'distance': 0.5}, {'reflection': 0.21},
                   {'reflection_delay_ms': 101}):
        with pytest.raises(ValueError):
            SpatialMix(**kwargs)
    with pytest.raises(ValueError):
        ExpressiveMix(duck_gain_db=float('inf'))
    timeline = Timeline(duration_seconds=1, items=[item('x', 'narration', length=1)])
    monkeypatch.setattr(audio, 'validate_timeline', lambda *args: None)
    for index in (-1, 1):
        with pytest.raises(ValueError, match='index out of range'):
            render(timeline, tmp_path, tmp_path/'out.mp3', expressive_mix=ExpressiveMix(items={index: ExpressiveItemMix()}))
    with pytest.raises(ValueError, match='Only SFX'):
        render(timeline, tmp_path, tmp_path/'out.mp3', expressive_mix=ExpressiveMix(items={0: ExpressiveItemMix(ambience=True)}))