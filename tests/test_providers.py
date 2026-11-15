import json
from types import SimpleNamespace
import httpx
from fablet.providers import ElevenLabs
from fablet.transcription import words
from fablet.usage import UsageLog


def test_elevenlabs_requests_and_usage(tmp_path):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=b'audio', headers={'request-id': 'abc'})
    provider = ElevenLabs('secret', 'voice123', 'eleven_multilingual_v2', 'music_v1', 'eleven_text_to_sound_v2')
    provider.http.close()
    provider.http = httpx.Client(base_url='https://api.elevenlabs.io/v1/', transport=httpx.MockTransport(handler), headers={'xi-api-key': 'secret'})
    provider.set_usage_log(UsageLog(tmp_path/'usage.jsonl'))
    provider.narrate('Hello', 'before', 'after', tmp_path/'voice.mp3')
    provider.music('instrumental', 10, tmp_path/'music.mp3')
    provider.effect('quiet wind', 2, tmp_path/'sfx.mp3')
    assert [r.url.path for r in requests] == ['/v1/text-to-speech/voice123', '/v1/music', '/v1/sound-generation']
    assert json.loads(requests[0].content)['previous_text'] == 'before'
    assert json.loads(requests[1].content)['force_instrumental'] is True
    assert json.loads(requests[2].content)['model_id'] == 'eleven_text_to_sound_v2'
    assert 'secret' not in (tmp_path/'usage.jsonl').read_text()
    assert len((tmp_path/'usage.jsonl').read_text().splitlines()) == 3


def test_transcription_token_normalization():
    assert words("Hello, WORLD!") == ['hello', 'world']


def test_elevenlabs_preflight_surfaces_invalid_key_without_leaking():
    import pytest
    from fablet.providers import check_elevenlabs_access
    def handler(request):
        return httpx.Response(400, json={'detail': {'code': 'invalid_api_key', 'message': 'secret'}})
    with pytest.raises(RuntimeError, match='API key ID provided') as error:
        check_elevenlabs_access('secret', 'voice', transport=httpx.MockTransport(handler))
    assert 'secret' not in str(error.value)
