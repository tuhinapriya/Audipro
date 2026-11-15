"""Independent speech-to-text comparison; flags are evidence, not proof."""
import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from openai import OpenAI
from .artifacts import atomic_write
from .models import Script
from .usage import UsageLog


def words(text):
    return re.findall(r"[\w']+", text.casefold())


def verify(root: Path, model: str):
    script = Script.model_validate_json((root / 'script.json').read_text())
    client = OpenAI()
    log = UsageLog(root / 'provider_usage.jsonl')
    entries = []
    for segment in script.segments:
        audio = root / 'narration' / f'{segment.id}.mp3'
        digest = hashlib.sha256(audio.read_bytes() + model.encode()).hexdigest()
        target = root / 'transcripts' / f'{segment.id}.json'
        saved = json.loads(target.read_text()) if target.exists() else None
        if not saved or saved.get('audio_hash') != digest:
            with audio.open('rb') as source:
                response = client.audio.transcriptions.create(model=model, file=source)
            usage = getattr(response, 'usage', None)
            log.record('openai', 'transcription', model=model, usage=usage.model_dump() if usage else None, input_bytes=audio.stat().st_size)
            saved = {'audio_hash': digest, 'model': model, 'text': response.text}
            atomic_write(target, json.dumps(saved, indent=2).encode())
        expected, actual = words(segment.text), words(saved['text'])
        match = SequenceMatcher(None, expected, actual, autojunk=False)
        differences = [{'type': op, 'expected': ' '.join(expected[i:j]), 'heard': ' '.join(actual[k:l])} for op, i, j, k, l in match.get_opcodes() if op != 'equal']
        entries.append({'segment_id': segment.id, 'similarity': round(match.ratio(), 3), 'review_required': bool(differences), 'differences': differences})
    report_path = root / 'qa_report.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    report['transcription_review'] = {'model': model, 'segments': entries, 'note': 'ASR is imperfect; listen to flagged passages and review pronunciation manually.'}
    atomic_write(report_path, json.dumps(report, indent=2).encode())
    print(f'Transcription comparison saved to {report_path}; review flagged segments and listen to the full production.')
