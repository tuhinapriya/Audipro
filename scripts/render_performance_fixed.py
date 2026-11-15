"""Rerender a saved blueprint scene using its locked cast and saved sound assets."""
import argparse,os
from pathlib import Path
from dotenv import load_dotenv
from fablet.casting import CastRegistry
from fablet.performance import produce_performance
from fablet.providers import ElevenLabs
from fablet.scene_director import SceneBlueprint, SceneScreenplay

load_dotenv();p=argparse.ArgumentParser();p.add_argument('scene',choices=['hut','tower']);args=p.parse_args()
root=Path('outputs')/(args.scene+'_revised');registry=CastRegistry.load(Path('config/cast_registry.json'))
blueprint=SceneBlueprint.model_validate_json((root/'blueprint.json').read_text());screenplay=SceneScreenplay.model_validate_json((root/'screenplay.json').read_text())
provider=ElevenLabs(os.environ['ELEVENLABS_API_KEY'],os.environ['ELEVENLABS_VOICE_ID'],'eleven_v4',os.getenv('ELEVENLABS_MUSIC_MODEL','music_v1'),os.getenv('ELEVENLABS_SFX_MODEL','eleven_text_to_sound_v2'))
report=produce_performance(blueprint,screenplay,root,provider,Path('outputs/rome/cover.webp'),registry,args.scene)
print(args.scene,'duration',round(report['duration_seconds'],2),'master flags',len(report['master_transcription']['differences']),'unresolved alignment',len(report['unresolved_alignment']),flush=True)
