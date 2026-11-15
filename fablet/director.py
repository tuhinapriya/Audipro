"""Semantic direction, timing compilation and conservative calibration."""
import json
import re
import subprocess
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field
from .audio import duration

class Anchor(BaseModel):
    segment_id: str
    point: Literal['start', 'end', 'phrase']
    phrase: str = ''
    offset_seconds: float = 0

class DirectionCue(BaseModel):
    id: str
    kind: Literal['music', 'sfx', 'ambience', 'silence']
    asset: str
    start: Anchor
    end: Anchor
    purpose: str
    gain_db: float = 0
    transition: Literal['fade', 'crossfade', 'hard_cut', 'j_cut', 'l_cut'] = 'fade'
    priority: str = 'speech'

class AudioDirectionPlan(BaseModel):
    scene_objectives: list[str]
    emotional_intensity: list[str]
    narration_pacing: list[str]
    motifs: list[str]
    cues: list[DirectionCue]
    mixing_priorities: list[str]


def resolve(anchor: Anchor, segments: dict, alignment: dict):
    """No phrase anchor is guessed: a missing alignment skips the cue."""
    seg = segments.get(anchor.segment_id)
    if not seg: return None
    if anchor.point == 'start': return seg['start_seconds'] + anchor.offset_seconds
    if anchor.point == 'end': return seg['start_seconds'] + seg['duration_seconds'] + anchor.offset_seconds
    words = alignment.get(anchor.segment_id, [])
    target = re.findall(r"[\w']+", anchor.phrase.lower())
    if not target: return None
    for i in range(len(words) - len(target) + 1):
        if [w['word'].strip('.,!?').lower() for w in words[i:i+len(target)]] == target:
            return seg['start_seconds'] + words[i]['start'] + anchor.offset_seconds
    return None


def compile_plan(plan: AudioDirectionPlan, narration: list, alignment: dict | None = None):
    segments = {Path(item['path']).stem: item for item in narration}
    cues, unresolved = [], []
    for cue in plan.cues:
        start = resolve(cue.start, segments, alignment or {})
        end = resolve(cue.end, segments, alignment or {})
        if start is None or end is None or end <= start or start < 0:
            unresolved.append({'cue': cue.id, 'reason': 'anchor missing, invalid or lacks word alignment'})
            continue
        cues.append({**cue.model_dump(), 'start_seconds': start, 'end_seconds': end})
    return cues, unresolved


def active_level(path: Path, seconds: float | None = None):
    args = ['ffmpeg','-hide_banner']
    if seconds: args += ['-t', str(seconds)]
    args += ['-i',str(path),'-af','silenceremove=start_periods=1:start_threshold=-50dB:stop_periods=-1:stop_duration=0.2:stop_threshold=-50dB,volumedetect','-f','null','-']
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    match = re.search(r'mean_volume:\s*(-?[\d.]+) dB', result.stderr)
    if not match: raise ValueError(f'Could not measure active audio in {path.name}')
    return float(match.group(1))


def loudness(path: Path):
    result = subprocess.run(['ffmpeg','-hide_banner','-i',str(path),'-af','loudnorm=I=-16:TP=-2:LRA=11:print_format=json','-f','null','-'],capture_output=True,text=True,check=True)
    match = re.search(r'\{\s*"input_i".*?\}', result.stderr, re.S)
    if not match: raise ValueError('Unable to measure integrated loudness')
    return json.loads(match.group())
