"""Deterministic timeline rendering and objective audio checks."""
import json
import re
import subprocess
from pathlib import Path
from PIL import Image
from .models import Timeline

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


def render(timeline: Timeline, root: Path, output: Path, *, ducking: bool = True, target_lufs: float = -16, true_peak: float = -2):
    validate_timeline(timeline, root)
    args = ['ffmpeg', '-y', '-v', 'error']
    filters, groups = [], {'narration': [], 'music': [], 'sfx': []}
    for i, item in enumerate(timeline.items):
        args += ['-i', str(root/item.path)]
        fade = min(1.0 if item.kind == 'music' else .03, item.duration_seconds / 4)
        fade_in = fade if item.fade_in_seconds is None else min(item.fade_in_seconds,item.duration_seconds)
        fade_out = fade if item.fade_out_seconds is None else min(item.fade_out_seconds,item.duration_seconds)
        fades = (f',afade=t=in:st=0:d={fade_in}:curve=qsin' if fade_in else '') + (f',afade=t=out:st={max(0,item.duration_seconds-fade_out)}:d={fade_out}:curve=qsin' if fade_out else '')
        delay = round(item.start_seconds * 1000)
        filters.append(f'[{i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=duration={item.duration_seconds},asetpts=PTS-STARTPTS,{volume_filter(item)}{fades},adelay={delay}|{delay}[a{i}]')
        groups[item.kind].append(f'[a{i}]')
    def mix(kind):
        labels = groups[kind]
        if labels:
            filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=longest:normalize=0[{kind}]')
    for kind in groups: mix(kind)
    tracks = []
    if groups['music'] and ducking:
        filters.append('[narration]asplit=2[voice][side]')
        filters.append('[music][side]sidechaincompress=threshold=0.01:ratio=8:attack=20:release=300[ducked]')
        tracks += ['[voice]', '[ducked]']
    else:
        tracks.append('[narration]')
        if groups['music']: tracks.append('[music]')
    if groups['sfx']: tracks.append('[sfx]')
    filters.append(''.join(tracks)+f'amix=inputs={len(tracks)}:duration=longest:normalize=0,apad,atrim=duration={timeline.duration_seconds},loudnorm=I={target_lufs}:TP={true_peak}:LRA=11[out]')
    args += ['-filter_complex', ';'.join(filters), '-map', '[out]', '-c:a', 'libmp3lame', '-b:a', '192k', str(output)]
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
