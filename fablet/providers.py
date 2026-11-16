"""Provider adapters. Calls use paid external APIs and can incur charges."""
import base64
from pathlib import Path
import httpx
from openai import OpenAI
from .artifacts import atomic_write

DIALOGUE_MODEL = 'eleven_v4'

class EditorialProvider:
    def __init__(self, model: str):
        self.client = OpenAI()
        self.model = model

    def set_usage_log(self, log):
        self.usage_log = log

    def _record(self, operation, result, **extra):
        log = getattr(self, 'usage_log', None)
        if log:
            usage = getattr(result, 'usage', None)
            log.record('openai', operation, model=extra.pop('model', self.model), usage=usage.model_dump() if usage else None, **extra)

    def research(self, prompt: str) -> str:
        result = self.client.responses.create(model=self.model, tools=[{'type': 'web_search'}], tool_choice='required', input=prompt, include=['web_search_call.action.sources'])
        self._record("web_research", result)
        # Persist the full response, including citations and source metadata.
        return result.model_dump_json()

    def structured(self, prompt: str, schema: type):
        result = self.client.responses.parse(model=self.model, input=prompt, text_format=schema)
        self._record("structured_" + schema.__name__, result)
        if result.output_parsed is None:
            raise RuntimeError('Provider returned no structured output')
        return result.output_parsed

    def cover(self, prompt: str, model: str, destination: Path):
        result = self.client.images.generate(model=model, prompt=prompt, size='1024x1024', n=1)
        self._record("image_generation", result, model=model)
        if not result.data or not result.data[0].b64_json:
            raise RuntimeError('Image provider did not return image bytes')
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(base64.b64decode(result.data[0].b64_json)))
        out = io.BytesIO()
        im.convert('RGB').save(out, format='WEBP', quality=90)
        atomic_write(destination, out.getvalue())

class ElevenLabs:
    def __init__(self, key: str, voice: str, tts_model: str, music_model: str, sfx_model: str = 'eleven_text_to_sound_v2'):
        self.http = httpx.Client(base_url='https://api.elevenlabs.io/v1/', headers={'xi-api-key': key}, timeout=httpx.Timeout(600, connect=30))
        self.voice, self.tts_model, self.music_model, self.sfx_model = voice, tts_model, music_model, sfx_model

    def set_usage_log(self, log):
        self.usage_log = log

    def _audio(self, endpoint: str, body: dict, dest: Path):
        response = self.http.post(endpoint, json=body)
        response.raise_for_status()
        log = getattr(self, 'usage_log', None)
        if log:
            log.record('elevenlabs', endpoint.split('/')[0], model=body.get('model_id'), input_characters=len(body.get('text', '')), requested_seconds=body.get('duration_seconds') or (body.get('music_length_ms', 0) / 1000 or None), response_bytes=len(response.content), request_id=response.headers.get('request-id'))
        if not response.content:
            raise RuntimeError('Provider returned empty audio')
        atomic_write(dest, response.content)

    def narrate(self, text: str, previous: str, following: str, dest: Path):
        self._audio(f'text-to-speech/{self.voice}', {'text': text, 'model_id': self.tts_model, 'previous_text': previous, 'next_text': following}, dest)

    def dialogue(self, turns: list[dict], dest: Path, metadata_path: Path):
        """Generate a multi-speaker performance and preserve alignment metadata."""
        import json
        if not turns or len({t['voice_id'] for t in turns}) > 10 or sum(len(t['text']) for t in turns) > 2000:
            raise ValueError('Dialogue requires inputs, at most ten voices and at most 2000 characters')
        response = self.http.post('text-to-dialogue/with-timestamps', json={'inputs': turns, 'model_id': DIALOGUE_MODEL})
        response.raise_for_status()
        data = response.json()
        audio = base64.b64decode(data.pop('audio_base64'), validate=True)
        if not audio:
            raise RuntimeError('Provider returned empty dialogue')
        atomic_write(dest, audio)
        atomic_write(metadata_path, json.dumps(data, indent=2).encode())
        log = getattr(self, 'usage_log', None)
        if log:
            log.record('elevenlabs', 'text-to-dialogue', model=DIALOGUE_MODEL, input_characters=sum(len(t['text']) for t in turns), response_bytes=len(audio), request_id=response.headers.get('request-id'))

    def music(self, prompt: str, seconds: int, dest: Path):
        self._audio('music', {'prompt': prompt, 'music_length_ms': seconds * 1000, 'model_id': self.music_model, 'force_instrumental': True}, dest)

    def effect(self, prompt: str, seconds: float, dest: Path):
        self._audio('sound-generation', {'text': prompt, 'duration_seconds': seconds, 'model_id': self.sfx_model}, dest)


def check_elevenlabs_access(key: str, voice: str, *, transport=None):
    """Check authentication and voice availability before incurring generation costs."""
    with httpx.Client(base_url='https://api.elevenlabs.io/v1/', headers={'xi-api-key': key}, timeout=30, transport=transport) as client:
        for endpoint, label in [('models', 'authentication'), (f'voices/{voice}', 'selected voice')]:
            response = client.get(endpoint)
            if response.is_error:
                try:
                    detail = response.json().get('detail', {})
                    code = detail.get('code') if isinstance(detail, dict) else None
                except ValueError:
                    code = None
                # Do not print provider response bodies or credentials.
                hint = ' API key ID provided; use the actual ElevenLabs API key.' if code == 'invalid_api_key' else ''
                raise RuntimeError(f'ElevenLabs {label} check failed (HTTP {response.status_code}).{hint}')
