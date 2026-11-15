import argparse
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv
from .models import Brief
from .pipeline import Pipeline
from .providers import EditorialProvider, ElevenLabs, check_elevenlabs_access

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(prog='fablet')
    sub = parser.add_subparsers(dest='command', required=True)
    generate = sub.add_parser('generate')
    generate.add_argument('--prompt', required=True)
    generate.add_argument('--duration', type=float, choices=[2, 2.5, 3, 5, 10, 15], default=5)
    generate.add_argument('--smoke', action='store_true', help='Target roughly 60–90 seconds, subject to actual narration pace')
    generate.add_argument('--style', choices=['cinematic_documentary', 'calm_explainer'], default='cinematic_documentary')
    generate.add_argument('--output', required=True, type=Path)
    sub.add_parser('voices', help='List voices available to your ElevenLabs account')
    transcribe = sub.add_parser('transcribe', help='Compare generated narration with an independent transcription')
    transcribe.add_argument('--output', required=True, type=Path)
    worker = sub.add_parser('worker')
    worker.add_argument('--output', type=Path, default=Path('./outputs/worker'))
    worker.add_argument('--poll-seconds', type=float, default=5)
    args = parser.parse_args()
    if args.command == 'voices':
        import httpx
        if not os.getenv('ELEVENLABS_API_KEY'):
            parser.error('Missing ELEVENLABS_API_KEY')
        response = httpx.get('https://api.elevenlabs.io/v2/voices', headers={'xi-api-key': os.environ['ELEVENLABS_API_KEY']}, timeout=30)
        response.raise_for_status()
        for voice in response.json().get('voices', []):
            print(f"{voice['voice_id']}  {voice['name']}")
        if response.json().get('has_more'):
            print('Additional voices exist; inspect the ElevenLabs dashboard for the full list.')
        return
    if args.command == 'transcribe':
        from .transcription import verify
        if not os.getenv('OPENAI_API_KEY'):
            parser.error('Missing OPENAI_API_KEY')
        verify(args.output, os.getenv('OPENAI_TRANSCRIPTION_MODEL', 'whisper-1'))
        return
    names = ['OPENAI_API_KEY', 'OPENAI_MODEL', 'OPENAI_IMAGE_MODEL', 'ELEVENLABS_API_KEY', 'ELEVENLABS_VOICE_ID']
    if args.command == 'worker':
        names += ['WORKER_BASE_URL', 'WORKER_API_KEY', 'R2_ENDPOINT_URL', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET']
    missing = [name for name in names if not os.environ.get(name)]
    missing += [tool for tool in ('ffmpeg', 'ffprobe') if not shutil.which(tool)]
    if missing:
        parser.error('Missing required configuration or executable: '+', '.join(missing))
    if args.command == 'generate':
        try:
            check_elevenlabs_access(os.environ['ELEVENLABS_API_KEY'], os.environ['ELEVENLABS_VOICE_ID'])
        except Exception as error:
            # Never emit remote response bodies or the request URL with a voice ID.
            if isinstance(error, RuntimeError):
                parser.error(str(error))
            parser.error('ElevenLabs preflight could not connect; check network access.')
    editor = EditorialProvider(os.environ['OPENAI_MODEL'])
    audio = ElevenLabs(os.environ['ELEVENLABS_API_KEY'], os.environ['ELEVENLABS_VOICE_ID'], os.getenv('ELEVENLABS_TTS_MODEL', 'eleven_multilingual_v2'), os.getenv('ELEVENLABS_MUSIC_MODEL', 'music_v1'), os.getenv('ELEVENLABS_SFX_MODEL', 'eleven_text_to_sound_v2'))
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
