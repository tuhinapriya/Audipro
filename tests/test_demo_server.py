import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("demo_server", Path(__file__).resolve().parents[1] / "scripts" / "demo_server.py")
demo_server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo_server)


def test_local_generation_uses_requested_duration(monkeypatch, tmp_path):
    seen = []

    class FakePipeline:
        def __init__(self, *args):
            pass

        def run(self, brief, root, progress):
            seen.append(brief.duration_minutes)
            return {'title': 'Test', 'description': 'Test', 'duration_seconds': 60}

    monkeypatch.setattr(demo_server, 'OUT', tmp_path)
    monkeypatch.setattr(demo_server, 'STORE', tmp_path / 'productions.json')
    monkeypatch.setattr(demo_server, 'records', {})
    monkeypatch.setattr(demo_server, 'Pipeline', FakePipeline)
    monkeypatch.setattr(demo_server, 'EditorialProvider', lambda *args: None)
    monkeypatch.setattr(demo_server, 'ElevenLabs', lambda *args: None)
    for name in ('OPENAI_MODEL', 'OPENAI_IMAGE_MODEL', 'ELEVENLABS_API_KEY', 'ELEVENLABS_VOICE_ID'):
        monkeypatch.setenv(name, 'test')
    for minutes in (0.5, 1, 3):
        job = {'id': str(minutes), 'prompt': 'A story about the ocean', 'style': 'cinematic_documentary', 'duration_minutes_requested': minutes}
        demo_server.records[job['id']] = job
        demo_server.generate(job)
        assert job['status'] == 'completed'
    assert seen == [0.5, 1, 3]
