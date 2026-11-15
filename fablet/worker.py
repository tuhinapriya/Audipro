"""HTTP client and lease monitoring for the shared Convex worker contract."""
import threading
from typing import Any
import httpx

class LeaseLost(RuntimeError):
    pass

class WorkerClient:
    def __init__(self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(base_url=base_url.rstrip('/') + '/', headers={'Authorization': f'Bearer {api_key}'}, timeout=30, transport=transport)

    def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        response = self.client.post(endpoint, json=payload)
        if response.status_code == 204:
            return None
        if response.status_code == 409:
            raise LeaseLost('Lease expired, replaced, or job state is invalid')
        response.raise_for_status()
        return response.json() if response.content else {}

    def claim(self, worker_id: str):
        return self.post('claim', {'worker_id': worker_id})

    def heartbeat(self, job_id: str, lease_token: str):
        return self.post('heartbeat', {'job_id': job_id, 'lease_token': lease_token})

    def progress(self, job_id: str, lease_token: str, status: str, progress_percent: int, stage_message: str):
        return self.post('progress', locals_payload(job_id, lease_token, status=status, progress_percent=progress_percent, stage_message=stage_message))

    def complete(self, job_id: str, lease_token: str, manifest: dict):
        return self.post('complete', locals_payload(job_id, lease_token, manifest=manifest))

    def fail(self, job_id: str, lease_token: str, error_code: str, error_message: str):
        return self.post('fail', locals_payload(job_id, lease_token, error_code=error_code, error_message=error_message))

def locals_payload(job_id: str, lease_token: str, **kwargs):
    return {'job_id': job_id, 'lease_token': lease_token, **kwargs}

class Lease:
    def __init__(self, client: WorkerClient, job_id: str, token: str, interval: float = 60):
        self.client, self.job_id, self.token, self.interval = client, job_id, token, interval
        self.stop_event = threading.Event()
        self.lost = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop_event.wait(self.interval):
            try:
                self.client.heartbeat(self.job_id, self.token)
            except Exception:
                # A network failure makes ownership uncertain; fail closed.
                self.lost.set()
                return

    def check(self):
        if self.lost.is_set():
            raise LeaseLost('Lease lost or heartbeat could not be verified')

    def __enter__(self):
        self.client.heartbeat(self.job_id, self.token)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop_event.set()
        self.thread.join()

class Worker:
    def __init__(self, client, pipeline, storage, root, worker_id, poll_seconds=5, heartbeat_seconds=60):
        from pathlib import Path
        self.client, self.pipeline, self.storage = client, pipeline, storage
        self.root, self.worker_id = Path(root), worker_id
        self.poll_seconds, self.heartbeat_seconds = poll_seconds, heartbeat_seconds
        self.stopping = threading.Event()

    def stop(self, *_):
        self.stopping.set()

    def run(self):
        import logging
        while not self.stopping.is_set():
            try:
                if not self.run_once():
                    self.stopping.wait(self.poll_seconds)
            except Exception:
                logging.exception('Worker polling error')
                self.stopping.wait(self.poll_seconds)

    def run_once(self):
        import logging
        from .models import Brief, Manifest
        from .storage import asset_keys
        claim = self.client.claim(self.worker_id)
        if not claim:
            return False
        job, token, attempt = claim['job'], claim['lease_token'], claim['attempt_id']
        job_id = job['id']
        audio_key, cover_key = asset_keys(job_id, attempt)
        root = self.root / job_id / attempt
        # Reuse only snapshots marked closed by a finished local attempt.
        import shutil
        previous = sorted((p for p in root.parent.glob('*') if p.is_dir() and (p / '.closed').exists()), key=lambda p: p.stat().st_mtime, reverse=True)
        if previous:
            shutil.copytree(previous[0], root, ignore=shutil.ignore_patterns('.closed', 'master.mp3', 'cover.webp', 'cover.webp.sha256', 'manifest.json', 'qa_report.json', 'timeline.json'))
        try:
            with Lease(self.client, job_id, token, self.heartbeat_seconds) as lease:
                def progress(status, percent, message):
                    lease.check()
                    if self.stopping.is_set():
                        raise InterruptedError('Worker stopping')
                    self.client.progress(job_id, token, status, percent, message)
                brief = Brief(prompt=job['prompt'], duration_minutes=job['duration_minutes'], style=job['style'])
                result = self.pipeline.run(brief, root, progress)
                lease.check()
                if self.stopping.is_set():
                    raise InterruptedError('Worker stopping')
                self.storage.upload(audio_key, root/'master.mp3', 'audio/mpeg')
                lease.check()
                self.storage.upload(cover_key, root/'cover.webp', 'image/webp')
                lease.check()
                manifest = Manifest(title=result['title'], description=result['description'], duration_seconds=result['duration_seconds'], audio_object_key=audio_key, cover_object_key=cover_key, attempt_id=attempt)
                self.client.complete(job_id, token, manifest.model_dump())
        except LeaseLost:
            logging.warning('Lease lost for job %s; abandoning attempt', job_id)
        except Exception:
            logging.exception('Production failed for job %s', job_id)
            try:
                self.client.fail(job_id, token, 'PRODUCTION_FAILED', 'Production could not be completed.')
            except Exception:
                logging.warning('Could not report failure; job will expire or may already be complete')
        finally:
            root.mkdir(parents=True, exist_ok=True)
            (root / '.closed').touch()
        return True
