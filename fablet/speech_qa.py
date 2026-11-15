"""Word-timed speech comparison. ASR is evidence, not ground truth."""
import re
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from openai import OpenAI
from .usage import UsageLog


def tokens(text: str):
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?",text.casefold().replace('’',"'"))


def compare(expected: str, observed: str, word_times: list[dict] | None = None):
    exp,got=tokens(expected),tokens(observed)
    matches=SequenceMatcher(None,exp,got,autojunk=False)
    discrepancies=[]
    for op,i,j,k,l in matches.get_opcodes():
        if op=='equal':continue
        discrepancies.append({'type':op,'expected':' '.join(exp[i:j]),'heard':' '.join(got[k:l]),'start_seconds':word_times[k]['start'] if word_times and k<len(word_times) else None,'end_seconds':word_times[l-1]['end'] if word_times and l and l<=len(word_times) else None})
    repeats=[]
    # Compare occurrence counts with the script, so explicitly scripted repeats
    # remain valid. Timestamps are approximate ASR evidence, not ground truth.
    minimum=1 if len(exp)==1 else 2
    for n in range(min(8,len(got)//2),minimum-1,-1):
        expected_counts=Counter(tuple(exp[i:i+n]) for i in range(len(exp)-n+1))
        observed_counts=Counter(tuple(got[i:i+n]) for i in range(len(got)-n+1))
        for seq,count in observed_counts.items():
            permitted=expected_counts[seq]
            if permitted and count>permitted:
                occurrences=[i for i in range(len(got)-n+1) if tuple(got[i:i+n])==seq]
                i=occurrences[permitted]
                repeats.append({'phrase':' '.join(seq),'start_seconds':word_times[i]['start'] if word_times and i<len(word_times) else None,'end_seconds':word_times[i+n-1]['end'] if word_times and i+n-1<len(word_times) else None})
        if repeats:break
    return {'expected':expected,'observed':observed,'differences':discrepancies,'repeated_phrases':repeats,'uncertain':bool(discrepancies or repeats)}


def transcribe(path: Path, log: UsageLog, client=None):
    client=client or OpenAI()
    with path.open('rb') as source:
        result=client.audio.transcriptions.create(model='whisper-1',file=source,response_format='verbose_json',timestamp_granularities=['word'])
    log.record('openai','speech_verification',model='whisper-1',input_bytes=path.stat().st_size,usage=None)
    return result.text,[{'word':w.word,'start':w.start,'end':w.end} for w in (result.words or [])]


def transcribe_secondary(path: Path, log: UsageLog, client=None):
    """Second ASR opinion for anomalous clips; disagreements stay uncertain."""
    client=client or OpenAI()
    with path.open('rb') as source:
        result=client.audio.transcriptions.create(model='gpt-4o-transcribe',file=source)
    log.record('openai','speech_verification_secondary',model='gpt-4o-transcribe',input_bytes=path.stat().st_size,usage=None)
    return result.text
