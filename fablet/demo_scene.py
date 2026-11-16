"""Prepare and render a prompt through the cinematic scene director."""
import json
import math
import os
import shutil
from pathlib import Path

from pydantic import BaseModel
from .casting import CastEntry, CastRegistry
from .models import ExpressiveMix
from .performance import produce_performance
from .scene_director import SceneBlueprint, SceneScreenplay, generate_blueprint, draft, shortlist
from .usage import UsageLog


class SceneAssets(BaseModel):
    music: str
    ambience: str
    cover: str


def run_scene(prompt, duration_minutes, root: Path, editor, audio, progress):
    root.mkdir(parents=True, exist_ok=True)
    editor.set_usage_log(UsageLog(root / 'provider_usage.jsonl'))
    progress('writing', 10, 'Planning your scene')
    brief = f'{prompt}\nTarget a total duration of approximately {round(duration_minutes * 60)} seconds including speech, action and pauses. Write an original cinematic audio scene, not a documentary.'
    blueprint_path = root / 'blueprint.json'
    script_path = root / 'screenplay.json'
    assets_path = root / 'asset_prompts.json'
    if blueprint_path.exists() and script_path.exists():
        blueprint = SceneBlueprint.model_validate_json(blueprint_path.read_text())
        script = SceneScreenplay.model_validate_json(script_path.read_text())
    else:
        blueprint = generate_blueprint(brief, editor)
        blueprint_path.write_text(blueprint.model_dump_json(indent=2))
        script = draft(blueprint, editor, max_attempts=3, direction=f'Target approximately {round(duration_minutes * 60)} seconds total including speech and actions. Use music and ambience start/stop events where appropriate.')
        script_path.write_text(script.model_dump_json(indent=2))
    if assets_path.exists():
        assets = SceneAssets.model_validate_json(assets_path.read_text())
    else:
        assets = editor.structured('Write three concise standalone generation prompts for instrumental cinematic music, environmental ambience, and cover art that suit this audio scene. Each must be under 450 characters. No vocals in the music.\n' + blueprint.model_dump_json(), SceneAssets)
        assets_path.write_text(assets.model_dump_json(indent=2))
    progress('narrating', 30, 'Casting voices and preparing the performance')
    response = audio.http.get('https://api.elevenlabs.io/v2/voices', params={'page_size': 100})
    response.raise_for_status()
    voices = response.json().get('voices', [])
    if not voices: raise ValueError('No available voices returned for casting')
    narrator = os.environ['ELEVENLABS_VOICE_ID']
    registry = CastRegistry(entries={'narrator': CastEntry(character_id='narrator', voice_id=narrator, status='provisional', selection='automatically_selected')})
    used = {narrator}
    speakers = {e.speaker for e in script.events if e.kind in ('dialogue', 'reaction')}
    for profile in blueprint.profiles:
        if profile.character not in speakers: continue
        candidates = shortlist(profile, voices)
        candidate = next((v for v in candidates if v.get('voice_id') and v['voice_id'] not in used), None)
        if candidate is None: candidate = next((v for v in candidates if v.get('voice_id')), None)
        if candidate is None: raise ValueError('No available voice for character')
        voice_id = candidate['voice_id']; used.add(voice_id)
        profile.voice_id = voice_id
        key = f'scene:{profile.character}'
        registry.choose(key, CastEntry(character_id=key, voice_id=voice_id, characteristics=profile.identity, status='provisional', selection='automatically_selected'))
    registry.save(root / 'cast_registry.json')
    (root / 'blueprint.json').write_text(blueprint.model_dump_json(indent=2))
    progress('scoring', 45, 'Creating music and atmosphere')
    if not (root / 'music.mp3').is_file(): audio.music(assets.music, max(10, min(300, math.ceil(duration_minutes * 60))), root / 'music.mp3')
    if not (root / 'ambience.mp3').is_file(): audio.effect(assets.ambience, min(22, max(1, duration_minutes * 60)), root / 'ambience.mp3')
    if not (root / 'cover.webp').is_file(): editor.cover(assets.cover, os.environ['OPENAI_IMAGE_MODEL'], root / 'cover.webp')
    progress('mixing', 65, 'Performing and mixing your scene')
    report = produce_performance(blueprint, script, root, audio, root / 'cover.webp', registry, 'scene', generate_missing_actions=True, expressive_mix=ExpressiveMix())
    shutil.copyfile(root / 'master_performance_fixed.mp3', root / 'master.mp3')
    return {'title': blueprint.title, 'description': blueprint.premise, 'duration_seconds': math.ceil(report['duration_seconds'])}
