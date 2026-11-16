"""Deterministic timeline rendering and objective audio checks."""
import json
import math
import re
import subprocess
from pathlib import Path
from PIL import Image
from .models import ExpressiveMix, Timeline, TimelineItem

def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, text=True, capture_output=True)

def probe(path: Path) -> dict:
    return json.loads(run('ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)).stdout)

def duration(path: Path) -> float:
    value = float(probe(path)['format']['duration'])
    if value <= 0 or path.stat().st_size == 0:
        raise ValueError(f'Empty audio: {path}')
    return value

def validate_timeline(timeline: Timeline, root: Path):
    if not timeline.items or not any(i.kind == 'narration' for i in timeline.items):
        raise ValueError('Timeline requires narration')
    narration = sorted((i for i in timeline.items if i.kind == 'narration'), key=lambda x: x.start_seconds)
    for a, b in zip(narration, narration[1:]):
        if a.start_seconds + a.duration_seconds > b.start_seconds + .01:
            raise ValueError('Narration segments overlap')
    for item in timeline.items:
        path = (root/item.path).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError(f'Missing or unsafe timeline asset: {item.path}')
        if item.start_seconds + item.duration_seconds > timeline.duration_seconds + .01:
            raise ValueError('Timeline item extends past output')
        if duration(path) + .05 < item.duration_seconds:
            raise ValueError(f'Timeline item exceeds source duration: {item.path}')

def volume_filter(item):
    points = item.gain_envelope
    if not points:
        return f'volume={item.gain_db}dB'
    if any(a.time_seconds >= b.time_seconds for a, b in zip(points, points[1:])):
        raise ValueError('Gain envelope points must be strictly increasing')
    expression = str(points[-1].gain_db)
    for a, b in reversed(list(zip(points, points[1:]))):
        delta = b.time_seconds-a.time_seconds
        value = f'({a.gain_db}+({b.gain_db-a.gain_db})*(t-{a.time_seconds})/{delta})'
        expression = f'if(lt(t,{b.time_seconds}),{value},{expression})'
    expression = f'if(lt(t,{points[0].time_seconds}),{points[0].gain_db},{expression})'
    return f"volume='pow(10,({item.gain_db}+({expression}))/20)':eval=frame"


def _duck_filter(item: TimelineItem, timeline: Timeline, mix: ExpressiveMix) -> str:
    """Apply the strongest scheduled duck, with times relative to this item."""
    amounts = []
    for voice in timeline.items:
        if voice.kind != 'narration':
            continue
        start = voice.start_seconds - item.start_seconds
        end = start + voice.duration_seconds
        if end + mix.release_seconds <= 0 or start - mix.attack_seconds >= item.duration_seconds:
            continue
        amounts.append(
            f'max(0,min(1,min((t-({start-mix.attack_seconds}))/{mix.attack_seconds},'
            f'(({end+mix.release_seconds})-t)/{mix.release_seconds})))'
        )
    if not amounts or mix.duck_gain_db == 0:
        return ''
    while len(amounts) > 1:
        amounts = [f'max({amounts[i]},{amounts[i+1]})' if i+1 < len(amounts) else amounts[i]
                   for i in range(0, len(amounts), 2)]
    return f",volume='pow(10,({mix.duck_gain_db})*({amounts[0]})/20)':eval=frame"


def _expressive_filters(item: TimelineItem, index: int, timeline: Timeline, mix: ExpressiveMix, ducking: bool) -> str:
    settings = mix.items.get(index)
    result = ''
    if settings:
        if settings.gain_offset_db:
            result += f',volume={settings.gain_offset_db}dB'
        if settings.spatial:
            spatial = settings.spatial
            # Crossfeed the opposite channel as the source moves away from centre;
            # simple balance would discard speech present only in that channel.
            left, right = math.sqrt(1 - spatial.pan), math.sqrt(1 + spatial.pan)
            cross_left, cross_right = max(0, -spatial.pan) / 2, max(0, spatial.pan) / 2
            result += (f',pan=stereo|c0={left*(1-cross_left)}*c0+{left*cross_left}*c1'
                       f'|c1={right*cross_right}*c0+{right*(1-cross_right)}*c1,volume={1/spatial.distance}')
            if spatial.reflection:
                result += f',aecho=1:1:{spatial.reflection_delay_ms}:{spatial.reflection},atrim=duration={item.duration_seconds}'
    if ducking and (item.kind == 'music' or (settings and settings.ambience)):
        result += _duck_filter(item, timeline, mix)
    return result


def render(timeline: Timeline, root: Path, output: Path, *, ducking: bool = True, target_lufs: float = -16, true_peak: float = -2, expressive_mix: ExpressiveMix | None = None):
    """Render normally, or opt into per-index settings and scheduled background ducking.

    Expressive offsets add to authored item gain/envelopes; no source is measured
    or normalized. The existing final master loudness processing remains in place.
    When enabled, ducking covers narration item intervals (including quiet speech),
    music, and explicitly marked ambience, rather than the legacy sidechain.

    Construct ExpressiveMix(items={index: ExpressiveItemMix(...)}) using indices
    from the final Timeline.items order and pass it as expressive_mix. Mark an SFX
    bed with ambience=True; other SFX remain foreground. A SpatialMix on an item
    sets stereo placement, relative-distance attenuation and optional early echo.
    Ducking=False disables both kinds of ducking, not the other expressive effects.
    Automation is frame-evaluated and follows entire narration clips, not words.
    """
    validate_timeline(timeline, root)
    if expressive_mix is not None:
        for index, settings in expressive_mix.items.items():
            if index < 0 or index >= len(timeline.items):
                raise ValueError(f'Expressive mix item index out of range: {index}')
            if settings.ambience and timeline.items[index].kind != 'sfx':
                raise ValueError('Only SFX items can be marked as ambience')
    args = ['ffmpeg', '-y', '-v', 'error']
    filters, groups = [], {'narration': [], 'music': [], 'sfx': []}
    for i, item in enumerate(timeline.items):
        args += ['-i', str(root/item.path)]
        fade = min(1.0 if item.kind == 'music' else .03, item.duration_seconds / 4)
        fade_in = fade if item.fade_in_seconds is None else min(item.fade_in_seconds,item.duration_seconds)
        fade_out = fade if item.fade_out_seconds is None else min(item.fade_out_seconds,item.duration_seconds)
        fades = (f',afade=t=in:st=0:d={fade_in}:curve=qsin' if fade_in else '') + (f',afade=t=out:st={max(0,item.duration_seconds-fade_out)}:d={fade_out}:curve=qsin' if fade_out else '')
        delay = round(item.start_seconds * 1000)
        expressive = _expressive_filters(item, i, timeline, expressive_mix, ducking) if expressive_mix is not None else ''
        filters.append(f'[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=duration={item.duration_seconds},asetpts=PTS-STARTPTS,{volume_filter(item)}{expressive}{fades},adelay={delay}|{delay}[a{i}]')
        groups[item.kind].append(f'[a{i}]')
    def mix(kind):
        labels = groups[kind]
        if labels:
            filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=longest:normalize=0[{kind}]')
    for kind in groups: mix(kind)
    tracks = []
    if groups['music'] and ducking and expressive_mix is None:
        filters.append('[narration]asplit=2[voice][side]')
        filters.append('[music][side]sidechaincompress=threshold=0.01:ratio=8:attack=20:release=300[ducked]')
        tracks += ['[voice]', '[ducked]']
    else:
        tracks.append('[narration]')
        if groups['music']: tracks.append('[music]')
    if groups['sfx']: tracks.append('[sfx]')
    # Bound the padding itself: an unbounded apad before time-based atrim can
    # keep FFmpeg processing forever on some filter graph/timestamp combinations.
    samples = math.ceil(timeline.duration_seconds * 48000)
    filters.append(''.join(tracks)+f'amix=inputs={len(tracks)}:duration=longest:normalize=0,apad=whole_len={samples},atrim=end_sample={samples},loudnorm=I={target_lufs}:TP={true_peak}:LRA=11[out]')
    args += ['-filter_complex', ';'.join(filters), '-map', '[out]', '-t', str(timeline.duration_seconds), '-c:a', 'libmp3lame', '-b:a', '192k', str(output)]
    run(*args)

def quality(audio: Path, cover: Path, expected_duration: float, *, allowed_silence: list[tuple[float, float]] | None = None) -> dict:
    metadata = probe(audio)
    actual = float(metadata['format']['duration'])
    with Image.open(cover) as image: image.verify()
    if not any(s.get('codec_type') == 'audio' for s in metadata['streams']): raise ValueError('No audio stream')
    if abs(actual - expected_duration) > .25: raise ValueError('Unexpected render duration')
    result = run('ffmpeg', '-hide_banner', '-i', str(audio), '-af', 'volumedetect,silencedetect=noise=-50dB:d=3', '-f', 'null', '-')
    peak = re.search(r'max_volume:\s*(-?[\d.]+) dB', result.stderr)
    if not peak: raise ValueError('Unable to measure peak')
    if float(peak.group(1)) >= -0.1: raise ValueError('Audio peak indicates clipping')
    silence_starts = [float(v) for v in re.findall(r'silence_start:\s*([\d.]+)', result.stderr)]
    silence_ends = [float(v) for v in re.findall(r'silence_end:\s*([\d.]+)', result.stderr)]
    silences = list(zip(silence_starts, silence_ends))
    for start, end in silences:
        if not any(start >= a-.3 and end <= b+.3 for a,b in (allowed_silence or [])):
            raise ValueError('Audio contains unplanned silence longer than 3 seconds')
    return {'basic_format_checks_passed': True, 'publication_ready': False, 'duration_seconds': actual, 'peak_dbfs': float(peak.group(1)), 'analysis_log': result.stderr, 'measured_silences': silences, 'limitations': ['No speech alignment or factual verification is performed.', 'Artistic quality requires a full human listen.']}
