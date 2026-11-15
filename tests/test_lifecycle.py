import json
import subprocess
import threading
import time
from pathlib import Path
import httpx
import pytest
from PIL import Image
from fablet.audio import duration, quality, render
from fablet.mock_api import MockService, server
from fablet.models import Direction, MusicCue, Outline, Research, Scene, Script, Segment, Source, Timeline, TimelineItem
from fablet.pipeline import Pipeline
from fablet.storage import LocalStorage, Storage, asset_keys
from fablet.worker import Worker, WorkerClient, LeaseLost


def tone(path, seconds=2, frequency=440):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', f'sine=frequency={frequency}:duration={seconds}', '-c:a', 'libmp3lame', str(path)], check=True)

class FakeEditor:
    def research(self, prompt): return json.dumps({'source': 'https://example.org/source'})
    def structured(self, prompt, schema):
        if schema == Research: return Research(sources=[Source(id='src', title='Source', url='https://example.org/source', summary='Test')], findings=['Test'])
        if schema == Outline: return Outline(title='Test audiobook', description='A local test', scenes=[Scene(id='scene', purpose='test', source_ids=['src'])])
        if schema == Script: return Script(segments=[Segment(id='s1', scene_id='scene', text='This is a test narration.', source_ids=['src'])], editorial_notes=[])
        if schema == Direction: return Direction(music=MusicCue(prompt='test instrumental', duration_seconds=3), effects=[], cover_prompt='test cover')
        raise AssertionError(schema)
    def cover(self, prompt, model, destination):
        Image.new('RGB', (32, 32), 'navy').save(destination, 'WEBP')

class FakeAudio:
    voice = 'fixture'; tts_model = 'fixture'; music_model = 'fixture'
    def narrate(self, text, previous, following, dest): tone(dest)
    def music(self, prompt, seconds, dest): tone(dest, 3, 220)
    def effect(self, prompt, seconds, dest): tone(dest, seconds, 800)

@pytest.fixture
def api():
    service = MockService(lease_seconds=1)
    http = server(service, port=0)
    thread = threading.Thread(target=http.serve_forever, daemon=True); thread.start()
    client = WorkerClient(f'http://127.0.0.1:{http.server_port}/worker', service.api_key)
    yield service, client
    client.client.close(); http.shutdown(); http.server_close(); thread.join()


def create(client):
    return client.post('create', {'prompt': 'A sufficiently long documentary prompt', 'duration_minutes': 5, 'style': 'cinematic_documentary'})['id']


def test_full_worker_lifecycle(api, tmp_path):
    service, client = api
    job = create(client)
    worker = Worker(client, Pipeline(FakeEditor(), FakeAudio(), 'fake'), LocalStorage(tmp_path/'objects'), tmp_path/'work', 'test', heartbeat_seconds=.1)
    assert worker.run_once()
    result = client.post('get', {'job_id': job})
    assert result['status'] == 'completed'
    path = tmp_path/'objects'/result['manifest']['audio_object_key']
    assert duration(path) > 1
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'], check=True)
    assert (tmp_path/'objects'/result['manifest']['cover_object_key']).exists()
    assert (tmp_path/'work'/job/result['manifest']['attempt_id']/'qa_report.json').exists()


def test_expiry_reclaim_and_stale_completion(api):
    service, client = api
    job = create(client); first = client.claim('first')
    service.jobs[job]['lease_expires'] = time.monotonic()-1
    second = client.claim('second')
    assert first['attempt_id'] != second['attempt_id']
    a, c = asset_keys(job, first['attempt_id'])
    manifest = dict(attempt_id=first['attempt_id'], title='x', description='y', duration_seconds=1, audio_object_key=a, cover_object_key=c, mime_type='audio/mpeg')
    with pytest.raises(LeaseLost): client.complete(job, first['lease_token'], manifest)
    with pytest.raises(LeaseLost): client.complete(job, second['lease_token'], manifest)


def test_attempt_uploads_are_immutable(tmp_path):
    store = LocalStorage(tmp_path/'objects')
    src = tmp_path/'audio'; src.write_bytes(b'audio')
    first, _ = asset_keys('job', 'attempt1'); second, _ = asset_keys('job', 'attempt2')
    store.upload(first, src, 'audio/mpeg'); store.upload(second, src, 'audio/mpeg')
    with pytest.raises(FileExistsError): store.upload(first, src, 'audio/mpeg')
    assert (tmp_path/'objects'/first).read_bytes() == b'audio'
    assert (tmp_path/'objects'/second).read_bytes() == b'audio'


def test_failed_upload_does_not_complete(api, tmp_path):
    service, client = api; job = create(client)
    class BrokenStorage:
        def upload(self, *args): raise OSError('failure')
    worker = Worker(client, Pipeline(FakeEditor(), FakeAudio(), 'fake'), BrokenStorage(), tmp_path, 'w', heartbeat_seconds=.1)
    worker.run_once()
    assert client.post('get', {'job_id': job})['status'] == 'failed'
    client.post('retry', {'job_id': job})
    assert client.claim('restarted')['job']['id'] == job


def test_storage_checks_incomplete_upload(tmp_path):
    src = tmp_path/'input'; src.write_bytes(b'1234')
    class FakeS3:
        def put_object(self, **kw): assert kw['IfNoneMatch'] == '*'
        def head_object(self, **kw): return {'ContentLength': 1}
    storage = object.__new__(Storage); storage.client = FakeS3(); storage.bucket = 'b'
    with pytest.raises(RuntimeError): storage.upload('x', src, 'audio/mpeg')


def test_invalid_audio_and_timeline(tmp_path):
    bad = tmp_path/'bad.mp3'; bad.write_bytes(b'not audio')
    with pytest.raises(subprocess.CalledProcessError): duration(bad)
    with pytest.raises(ValueError): render(Timeline(duration_seconds=2, items=[TimelineItem(path='missing.mp3', start_seconds=0, duration_seconds=1, kind='narration')]), tmp_path, tmp_path/'out.mp3')
    tone(tmp_path/'tone.mp3')
    with pytest.raises(ValueError): render(Timeline(duration_seconds=2, items=[TimelineItem(path='tone.mp3', start_seconds=1.5, duration_seconds=1, kind='narration')]), tmp_path, tmp_path/'out.mp3')


def test_retry_reuses_closed_attempt_artifacts(api, tmp_path):
    _, client = api; job = create(client)
    class CountingAudio(FakeAudio):
        calls = 0
        def narrate(self, *args):
            self.calls += 1
            super().narrate(*args)
    audio = CountingAudio()
    pipeline = Pipeline(FakeEditor(), audio, 'fake')
    class BrokenStorage:
        def upload(self, *args): raise OSError('offline')
    Worker(client, pipeline, BrokenStorage(), tmp_path/'work', 'first', heartbeat_seconds=.1).run_once()
    assert audio.calls == 1
    client.post('retry', {'job_id': job})
    Worker(client, pipeline, LocalStorage(tmp_path/'objects'), tmp_path/'work', 'second', heartbeat_seconds=.1).run_once()
    assert audio.calls == 1
    assert client.post('get', {'job_id': job})['status'] == 'completed'


def test_quality_rejects_silence_and_clipping(tmp_path):
    cover = tmp_path/'cover.webp'; Image.new('RGB', (32, 32)).save(cover, 'WEBP')
    silent = tmp_path/'silent.wav'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', '4', str(silent)], check=True)
    with pytest.raises(ValueError): quality(silent, cover, 4)
    clipped = tmp_path/'clip.wav'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=frequency=400:duration=4', '-af', 'volume=30dB', str(clipped)], check=True)
    with pytest.raises(ValueError, match='clipping'): quality(clipped, cover, 4)
