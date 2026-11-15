"""Local-only, in-memory implementation of the worker contract."""
import argparse
import json
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from .models import Brief, Manifest
from .storage import asset_keys

class MockService:
    def __init__(self, api_key='local-test-key', lease_seconds=600, max_attempts=2):
        self.api_key, self.lease_seconds, self.max_attempts = api_key, lease_seconds, max_attempts
        self.jobs = {}
        self.lock = threading.RLock()

    def create(self, payload):
        brief = Brief.model_validate(payload)
        job_id = uuid.uuid4().hex
        self.jobs[job_id] = {'id': job_id, 'prompt': brief.prompt, 'duration_minutes': brief.duration_minutes, 'style': brief.style, 'status': 'queued', 'attempts': 0, 'progress_percent': 0}
        return {'id': job_id}

    def expire(self):
        for job in self.jobs.values():
            if job.get('lease_expires', float('inf')) <= time.monotonic() and job['status'] not in ('completed', 'failed', 'queued'):
                job['status'] = 'queued' if job['attempts'] < self.max_attempts else 'failed'
                job.pop('lease_token', None)
                job.pop('lease_expires', None)
                job['progress_percent'] = 0

    def handle(self, path, body):
        with self.lock:
            self.expire()
            if path == 'create':
                return 200, self.create(body)
            if path == 'get':
                job = self.jobs.get(body.get('job_id'))
                if not job:
                    return 404, {'error': 'unknown job'}
                return 200, {k: v for k, v in job.items() if k not in ('lease_token', 'lease_expires', 'completion_token')}
            if path == 'retry':
                job = self.jobs.get(body.get('job_id'))
                if not job: return 404, {'error': 'unknown job'}
                if job['status'] != 'failed': return 409, {'error': 'not failed'}
                job.update(status='queued', progress_percent=0, attempts=0)
                return 200, {'status': 'queued'}
            if path == 'claim':
                if not body.get('worker_id'): return 400, {'error': 'worker_id required'}
                job = next((j for j in self.jobs.values() if j['status'] == 'queued'), None)
                if job is None: return 204, None
                job.update(status='researching', progress_percent=10, attempts=job['attempts']+1, attempt_id=uuid.uuid4().hex, lease_token=secrets.token_urlsafe(32), lease_expires=time.monotonic()+self.lease_seconds)
                return 200, {'job': {k: job[k] for k in ('id', 'prompt', 'duration_minutes', 'style')}, 'attempt_id': job['attempt_id'], 'lease_token': job['lease_token'], 'lease_expires_at': (datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)).isoformat().replace('+00:00', 'Z')}
            job = self.jobs.get(body.get('job_id'))
            if not job: return 404, {'error': 'unknown job'}
            if path == 'complete' and job['status'] == 'completed':
                if body.get('lease_token') == job.get('completion_token') and body.get('manifest') == job.get('manifest'):
                    return 200, {'status': 'completed'}
                return 409, {'error': 'already completed'}
            if job.get('lease_token') != body.get('lease_token') or job['status'] in ('queued', 'failed', 'completed'):
                return 409, {'error': 'stale lease'}
            if path == 'heartbeat':
                job['lease_expires'] = time.monotonic()+self.lease_seconds
            elif path == 'progress':
                status, percent = body.get('status'), body.get('progress_percent')
                if status not in ('researching', 'writing', 'narrating', 'scoring', 'mixing', 'quality_check') or not isinstance(percent, int) or not job['progress_percent'] <= percent < 100:
                    return 400, {'error': 'invalid progress'}
                job.update(status=status, progress_percent=percent, stage_message=body.get('stage_message'))
            elif path == 'complete':
                try:
                    manifest = Manifest.model_validate(body.get('manifest'))
                    keys = asset_keys(job['id'], job['attempt_id'])
                    if manifest.attempt_id != job['attempt_id'] or (manifest.audio_object_key, manifest.cover_object_key) != keys:
                        return 409, {'error': 'wrong attempt or keys'}
                except ValueError:
                    return 400, {'error': 'invalid manifest'}
                job.update(status='completed', progress_percent=100, manifest=manifest.model_dump(), completion_token=body['lease_token'])
            elif path == 'fail':
                job.update(status='failed', error_message=body.get('error_message'), error_code=body.get('error_code'))
            else:
                return 404, {'error': 'unknown endpoint'}
            return 200, {'status': job['status']}


def server(service, host='127.0.0.1', port=8765):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.headers.get('Authorization') != 'Bearer '+service.api_key:
                self.send_response(401); self.end_headers(); return
            try:
                body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))))
                path = self.path.removeprefix('/worker/')
                code, result = service.handle(path, body)
            except (ValueError, TypeError, KeyError):
                code, result = 400, {'error': 'invalid request'}
            data = json.dumps(result).encode() if result is not None else b''
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        def log_message(self, format, *args):
            pass
    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--api-key', default='local-test-key')
    args = parser.parse_args()
    server(MockService(args.api_key), port=args.port).serve_forever()

if __name__ == '__main__': main()
