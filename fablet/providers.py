"""Provider adapters. Calls use paid external APIs and can incur charges."""
import base64
from pathlib import Path
import httpx
from openai import OpenAI
from .artifacts import atomic_write

class EditorialProvider:
    def __init__(self, model: str):
        self.client = OpenAI()
        self.model = model

    def research(self, prompt: str) -> str:
        result = self.client.responses.create(model=self.model, tools=[{'type': 'web_search'}], input=prompt, include=['web_search_call.action.sources'])
        # Persist the full response, including citations and source metadata.
        return result.model_dump_json()

    def structured(self, prompt: str, schema: type):
        result = self.client.responses.parse(model=self.model, input=prompt, text_format=schema)
        if result.output_parsed is None:
            raise RuntimeError('Provider returned no structured output')
        return result.output_parsed

    def cover(self, prompt: str, model: str, destination: Path):
        result = self.client.images.generate(model=model, prompt=prompt, size='1024x1024', n=1)
        if not result.data or not result.data[0].b64_json:
            raise RuntimeError('Image provider did not return image bytes')
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(base64.b64decode(result.data[0].b64_json)))
        out = io.BytesIO()
        im.convert('RGB').save(out, format='WEBP', quality=90)
        atomic_write(destination, out.getvalue())

class ElevenLabs:
    def __init__(self, key: str, voice: str, tts_model: str, music_model: str):
        self.http = httpx.Client(base_url='https://api.elevenlabs.io/v1/', headers={'xi-api-key': key}, timeout=httpx.Timeout(600, connect=30))
        self.voice, self.tts_model, self.music_model = voice, tts_model, music_model

    def _audio(self, endpoint: str, body: dict, dest: Path):
        response = self.http.post(endpoint, json=body)
        response.raise_for_status()
        if not response.content:
            raise RuntimeError('Provider returned empty audio')
        atomic_write(dest, response.content)

    def narrate(self, text: str, previous: str, following: str, dest: Path):
        self._audio(f'text-to-speech/{self.voice}', {'text': text, 'model_id': self.tts_model, 'previous_text': previous, 'next_text': following}, dest)

    def music(self, prompt: str, seconds: int, dest: Path):
        self._audio('music', {'prompt': prompt, 'music_length_ms': seconds * 1000, 'model_id': self.music_model, 'force_instrumental': True}, dest)

    def effect(self, prompt: str, seconds: float, dest: Path):
        self._audio('sound-generation', {'text': prompt, 'duration_seconds': seconds}, dest)
