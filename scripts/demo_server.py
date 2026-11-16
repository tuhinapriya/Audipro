"""Local simulator bridge: run with .venv/bin/python scripts/demo_server.py."""
import json
import mimetypes
import math
import os
import sys
import threading
import traceback
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from fablet.models import Brief
from fablet.pipeline import Pipeline
from fablet.providers import EditorialProvider, ElevenLabs

load_dotenv(ROOT / '.env')
OUT = ROOT / 'outputs' / 'local-demo'
OUT.mkdir(parents=True, exist_ok=True)
STORE = OUT / 'productions.json'
records = {}
lock = threading.RLock()

def save():
    temporary = STORE.with_suffix('.tmp')
    temporary.write_text(json.dumps(list(records.values())))
    temporary.replace(STORE)

def load_records():
    try:
        records.update({job['id']: job for job in json.loads(STORE.read_text())})
    except FileNotFoundError:
        return
    for job in records.values():
        if job['status'] not in ('completed', 'failed'):
            job.update(status='failed', stage_message='Production interrupted', error_message='The local generator restarted before this production finished.')
    if records:
        save()

def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

def update(job, **values):
    with lock:
        job.update(values, updated_at=now())
        save()

def generate(job):
    try:
        audio = ElevenLabs(os.environ['ELEVENLABS_API_KEY'], os.environ['ELEVENLABS_VOICE_ID'], os.getenv('ELEVENLABS_TTS_MODEL', 'eleven_multilingual_v2'), os.getenv('ELEVENLABS_MUSIC_MODEL', 'music_v1'), os.getenv('ELEVENLABS_SFX_MODEL', 'eleven_text_to_sound_v2'))
        editor = EditorialProvider(os.environ['OPENAI_MODEL'])
        progress = lambda status, percent, message: update(job, status=status, progress_percent=percent, stage_message=message)
        if job['style'] == 'cinematic_scene':
            from fablet.demo_scene import run_scene
            result = run_scene(job['prompt'], job['duration_minutes_requested'], OUT / job['id'], editor, audio, progress)
        else:
            pipeline = Pipeline(editor, audio, os.environ['OPENAI_IMAGE_MODEL'])
            brief = Brief(prompt=job['prompt'], duration_minutes=job['duration_minutes_requested'], style=job['style'])
            result = pipeline.run(brief, OUT / job['id'], progress)
        update(job, status='completed', progress_percent=100, stage_message='Ready to listen', title=result['title'], description=result['description'], duration_seconds=result['duration_seconds'], assets_available=True)
    except Exception:
        traceback.print_exc()
        update(job, status='failed', stage_message='Production failed', error_message='Generation failed. Check the local server terminal for details.')

class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        data = json.dumps(value).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        parts = self.path.strip('/').split('/')
        with lock:
            job = records.get(parts[1]) if len(parts) > 1 else None
            if parts == ['productions']:
                return self.send_json(list(reversed(list(records.values()))))
            if len(parts) == 2 and parts[0] == 'productions':
                return self.send_json(job, 200 if job else 404)
            if len(parts) == 3 and parts[0] == 'productions' and job and job['assets_available']:
                if parts[2] == 'playback':
                    base = f'http://127.0.0.1:8766/productions/{job["id"]}'
                    return self.send_json({'audio_url': base+'/master.mp3', 'cover_url': base+'/cover.webp', 'expires_at': '2099-01-01T00:00:00Z'})
                if parts[2] in ('master.mp3', 'cover.webp'):
                    path = OUT / job['id'] / parts[2]
                    data = path.read_bytes(); start = 0; end = len(data)-1
                    range_header = self.headers.get('Range', '')
                    if range_header.startswith('bytes='):
                        bounds = range_header[6:].split('-', 1)
                        if bounds[0]: start = int(bounds[0])
                        if bounds[1]: end = min(int(bounds[1]), end)
                        if start > end: self.send_error(416); return
                        self.send_response(206); self.send_header('Content-Range', f'bytes {start}-{end}/{len(data)}')
                    else: self.send_response(200)
                    self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream'); self.send_header('Accept-Ranges', 'bytes'); self.send_header('Content-Length', str(end-start+1)); self.end_headers(); self.wfile.write(data[start:end+1]); return
        self.send_error(404)
    def do_POST(self):
        parts = self.path.strip('/').split('/')
        if len(parts) == 3 and parts[0] == 'productions' and parts[2] == 'retry':
            with lock:
                job = records.get(parts[1])
                if not job or job['status'] != 'failed': return self.send_json({'error': 'Cannot retry'}, 409)
                update(job, status='queued', progress_percent=0, stage_message='Retrying', error_message=None)
            threading.Thread(target=generate, args=(job,), daemon=True).start()
            return self.send_json({'id': job['id']})
        if self.path != '/productions': return self.send_error(404)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 10000: raise ValueError()
            body = json.loads(self.rfile.read(size)); prompt = body['prompt'].strip(); duration = body['duration']; style = body['style']
            if not 10 <= len(prompt.encode('utf-16-le')) // 2 <= 2000 or (not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration) or duration < 1 / 6) or style not in ('cinematic_scene', 'cinematic_documentary', 'calm_explainer'): raise ValueError()
        except (ValueError, KeyError, TypeError): return self.send_json({'error': 'Invalid request'}, 400)
        date = now(); job = dict(id=str(uuid.uuid4()), status='queued', progress_percent=0, stage_message='Queued for local generation', created_at=date, updated_at=date, prompt=prompt, duration_minutes_requested=duration, style=style, title=None, description=None, duration_seconds=None, assets_available=False, error_message=None)
        with lock:
            records[job['id']] = job
            save()
        threading.Thread(target=generate, args=(job,), daemon=True).start()
        self.send_json({'id': job['id']}, 201)

if __name__ == '__main__':
    load_records()
    print('Local demo bridge listening on http://127.0.0.1:8766 (generation uses paid APIs)', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8766), Handler).serve_forever()
