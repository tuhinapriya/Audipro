import json
import time
import httpx
import pytest
from fablet.models import Brief, Segment, Script
from fablet.artifacts import cached_model
from fablet.worker import WorkerClient, Lease, LeaseLost


def test_brief_and_unique_segments():
    with pytest.raises(ValueError):
        Brief(prompt='tiny', duration_minutes=5)
    segment = Segment(id='a', scene_id='scene', text='Hello', source_ids=[])
    with pytest.raises(ValueError):
        Script(segments=[segment, segment], editorial_notes=[])


def test_artifact_cache_invalidation(tmp_path):
    calls = []
    def make():
        calls.append(1)
        return Brief(prompt='A sufficiently long prompt', duration_minutes=5)
    path = tmp_path/'brief.json'
    cached_model(path, Brief, {'x': 1}, make)
    cached_model(path, Brief, {'x': 1}, make)
    cached_model(path, Brief, {'x': 2}, make)
    assert len(calls) == 2


def test_worker_contract_and_stale_lease():
    requests = []
    def handler(request):
        requests.append((request.url.path, json.loads(request.content), request.headers['authorization']))
        if request.url.path.endswith('/claim'):
            return httpx.Response(204)
        return httpx.Response(409, json={'error': 'expired'})
    worker = WorkerClient('https://example.com/worker', 'secret', httpx.MockTransport(handler))
    assert worker.claim('w1') is None
    with pytest.raises(LeaseLost):
        worker.heartbeat('job', 'token')
    assert requests[0] == ('/worker/claim', {'worker_id': 'w1'}, 'Bearer secret')
    assert requests[1][1] == {'job_id': 'job', 'lease_token': 'token'}


def test_heartbeat_runs_and_fails_closed():
    class Client:
        calls = 0
        def heartbeat(self, job_id, token):
            self.calls += 1
            if self.calls > 1:
                raise httpx.ConnectError('unavailable')
    client = Client()
    with Lease(client, 'job', 'token', interval=.01) as lease:
        assert lease.lost.wait(timeout=1)
        with pytest.raises(LeaseLost):
            lease.check()
