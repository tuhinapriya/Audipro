"""Compare each generated speech event to its script; this incurs API usage."""
import argparse,json,os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from dotenv import load_dotenv
from openai import OpenAI
from fablet.usage import UsageLog
from fablet.transcription import words

load_dotenv();p=argparse.ArgumentParser();p.add_argument('output',type=Path);root=p.parse_args().output
client=OpenAI();model=os.getenv('OPENAI_TRANSCRIPTION_MODEL','gpt-4o-transcribe');data=json.loads((root/'screenplay.json').read_text());events=[e for e in data['events'] if e['kind'] in ('narration','dialogue','reaction')]
def transcribe(e):
    path=root/'speech'/f"{e['id']}.mp3"
    with path.open('rb') as f:r=client.audio.transcriptions.create(model=model,file=f)
    a,b=words(e['text']),words(r.text);m=SequenceMatcher(None,a,b,autojunk=False)
    differences=[{'type':op,'expected':' '.join(a[i:j]),'heard':' '.join(b[k:l])} for op,i,j,k,l in m.get_opcodes() if op!='equal']
    return {'event_id':e['id'],'transcript':r.text,'differences':differences,'input_bytes':path.stat().st_size}
with ThreadPoolExecutor(max_workers=4) as ex:results=list(ex.map(transcribe,events))
for item in results:UsageLog(root/'provider_usage.jsonl').record('openai','speech_transcription',model=model,input_bytes=item.pop('input_bytes'),usage=None)
qpath=root/'creative_qa.json';q=json.loads(qpath.read_text());q['transcription_review']={'model':model,'events':results,'note':'ASR is imperfect; human listening is still required.'};q['subjective_review']['independent_script_review']='completed; human story review pending';q['casting_findings']=json.loads((root/'casting_report.json').read_text());qpath.write_text(json.dumps(q,indent=2));print(root, 'events:',len(results),'flags:',sum(bool(r['differences']) for r in results))
for r in results:
    if r['differences']:print(r['event_id'],r['differences'])
