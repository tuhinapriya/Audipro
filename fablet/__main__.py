import argparse
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv
from .models import Brief
from .pipeline import Pipeline
from .providers import EditorialProvider, ElevenLabs

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog='fablet')
    sub = parser.add_subparsers(dest='command', required=True)
    generate = sub.add_parser('generate')
    generate.add_argument('--prompt', required=True)
    generate.add_argument('--duration', type=int, choices=[5, 10, 15], default=5)
    generate.add_argument('--smoke', action='store_true', help='Target roughly 60–90 seconds, subject to actual narration pace')
    generate.add_argument('--style', choices=['cinematic_documentary', 'calm_explainer'], default='cinematic_documentary')
    generate.add_argument('--output', required=True, type=Path)
    worker = sub.add_parser('worker')
    worker.add_argument('--output', type=Path, default=Path('./outputs/worker'))
    worker.add_argument('--poll-seconds', type=float, default=5)
    args = parser.parse_args()
    names = ['OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_IMAGE_MODEL', 'ELEVENLABS_API_KEY', 'ELEVENLABS_VOICE_ID']
    if args.command == 'worker':
        names += ['WORKER_BASE_URL', 'WORKER_API_KEY', 'R2_ENDPOINT_URL', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET']
    missing = [name for name in names if not os.environ.get(name)]
    missing += [tool for tool in ('ffmpeg', 'ffprobe') if not shutil.which(tool)]
    if missing:
        parser.error('Missing required configuration or executable: '+', '.join(missing))
    editor = EditorialProvider(os.environ['OPENAI_MODEL'])
    audio = ElevenLabs(os.environ['ELEVENLABS_API_KEY'], os.environ['ELEVENLABS_VOICE_ID'], os.getenv('ELEVENLABS_TTS_MODEL', 'eleven_multilingual_v2'), os.getenv('ELEVENLABS_MUSIC_MODEL', 'music_v1'))
    pipeline = Pipeline(editor, audio, os.environ['OPENAI_IMAGE_MODEL'])
    if args.command == 'generate':
        brief = Brief(prompt=args.prompt, duration_minutes=1.25 if args.smoke else args.duration, style=args.style)
        pipeline.run(brief, args.output, lambda stage, percent, msg: print(f'{stage} {percent}%: {msg}', flush=True))
    else:
        import signal
        from .worker import Worker, WorkerClient
        from .storage import Storage
        client = WorkerClient(os.environ['WORKER_BASE_URL'], os.environ['WORKER_API_KEY'])
        storage = Storage(os.environ['R2_ENDPOINT_URL'], os.environ['R2_ACCESS_KEY_ID'], os.environ['R2_SECRET_ACCESS_KEY'], os.environ['R2_BUCKET'])
        runner = Worker(client, pipeline, storage, args.output, os.getenv('WORKER_ID', 'audio-worker-1'), args.poll_seconds)
        signal.signal(signal.SIGINT, runner.stop)
        signal.signal(signal.SIGTERM, runner.stop)
        runner.run()

if __name__ == '__main__':
    main()
