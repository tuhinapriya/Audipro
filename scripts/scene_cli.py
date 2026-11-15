"""Blueprint or produce a generic scene using configured real providers."""
import argparse
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from fablet.providers import EditorialProvider, ElevenLabs
from fablet.scene_director import SceneBlueprint, SceneScreenplay, generate_blueprint, draft, validate_screenplay, review_script, produce
from fablet.usage import UsageLog


def main():
    load_dotenv();p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('blueprint');b.add_argument('--brief',required=True);b.add_argument('--output',type=Path,required=True)
    r=sub.add_parser('render');r.add_argument('--blueprint',type=Path,required=True);r.add_argument('--output',type=Path,required=True);r.add_argument('--music',type=Path,required=True);r.add_argument('--ambience',type=Path,required=True);r.add_argument('--cover',type=Path,required=True)
    args=p.parse_args();editor=EditorialProvider(os.environ['OPENAI_MODEL'])
    if args.command=='blueprint':
        blueprint=generate_blueprint(args.brief,editor);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(blueprint.model_dump_json(indent=2));print('Blueprint saved. Set available voice IDs and review required beats before rendering.');return
    root=args.output;root.mkdir(parents=True,exist_ok=True);editor.set_usage_log(UsageLog(root/'provider_usage.jsonl'))
    blueprint=SceneBlueprint.model_validate_json(args.blueprint.read_text());path=root/'screenplay.json'
    if path.exists():
        script=SceneScreenplay.model_validate_json(path.read_text());errors=validate_screenplay(blueprint,script)
        if errors:raise ValueError('Saved screenplay does not satisfy blueprint: '+'; '.join(errors))
        assessment,errors=review_script(blueprint,script,editor);(root/'script_review.json').write_text(assessment.model_dump_json(indent=2))
        if errors:raise ValueError('Independent script review requires revision: '+'; '.join(errors))
    else:
        script=draft(blueprint,editor,max_attempts=3);path.write_text(script.model_dump_json(indent=2))
    provider=ElevenLabs(os.environ['ELEVENLABS_API_KEY'],os.environ['ELEVENLABS_VOICE_ID'],'eleven_v4',os.getenv('ELEVENLABS_MUSIC_MODEL','music_v1'),os.getenv('ELEVENLABS_SFX_MODEL','eleven_text_to_sound_v2'))
    produce(blueprint,script,root,provider,args.cover,args.music,args.ambience)
    print('Rendered; review casting, acting, acoustic actions and mix by ear.')

if __name__=='__main__':main()
