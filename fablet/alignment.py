"""Word timestamp evidence from the documented Whisper transcription API."""
import argparse
import hashlib
import json
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from .artifacts import atomic_write
from .models import Script
from .usage import UsageLog


def align(root: Path):
    client=OpenAI(); log=UsageLog(root/'provider_usage.jsonl')
    script=Script.model_validate_json((root/'script.json').read_text())
    result={}
    for segment in script.segments:
        audio=root/'narration'/f'{segment.id}.mp3'
        digest=hashlib.sha256(audio.read_bytes()).hexdigest()
        saved=root/'alignment'/f'{segment.id}.json'
        prior=json.loads(saved.read_text()) if saved.exists() else {}
        if prior.get('audio_hash') != digest:
            with audio.open('rb') as f:
                response=client.audio.transcriptions.create(model='whisper-1',file=f,response_format='verbose_json',timestamp_granularities=['word'])
            words=[{'word':w.word,'start':w.start,'end':w.end} for w in (response.words or [])]
            prior={'audio_hash':digest,'model':'whisper-1','words':words,'text':response.text}
            log.record('openai','word_alignment_transcription',model='whisper-1',input_bytes=audio.stat().st_size,usage=None)
            atomic_write(saved,json.dumps(prior,indent=2).encode())
        result[segment.id]=prior['words']
    atomic_write(root/'word_alignment.json',json.dumps(result,indent=2).encode())
    print('Alignment saved; check recognition accuracy before timing critical cues.')

if __name__=='__main__':
    load_dotenv();p=argparse.ArgumentParser();p.add_argument('output',type=Path);align(p.parse_args().output)
