"""Reproduce the two blueprint regression scenes with account-available voices."""
import argparse
import json
import os
from pathlib import Path
import httpx
from dotenv import load_dotenv
from fablet.scene_director import VoiceProfile, RequiredBeat, SceneBlueprint, draft, validate_cast, validate_screenplay, review_script, produce, shortlist
from fablet.providers import EditorialProvider, ElevenLabs
from fablet.usage import UsageLog


def profile(name, identity, age, accent, register, texture, personality, voice):
    return VoiceProfile(character=name,identity=identity,age_range=age,accent=accent,vocal_register=register,texture=texture,rhythm='natural and measured',personality=personality,emotional_range='fear, restraint and warmth',pronunciation='English',voice_id=voice['voice_id'],casting_evidence='Provider metadata only; audition and human approval pending.',human_review='pending')

def beat(id,description,kind,required_text='',speaker='',acoustic=''):
    return RequiredBeat(id=id,description=description,allowed_types=[kind],required_text=required_text,required_speaker=speaker,acoustic_expectation=acoustic)

def main():
    load_dotenv();parser=argparse.ArgumentParser();parser.add_argument('scene',choices=['hut','tower']);args=parser.parse_args()
    r=httpx.get('https://api.elevenlabs.io/v2/voices',headers={'xi-api-key':os.environ['ELEVENLABS_API_KEY']},params={'page_size':100},timeout=30);r.raise_for_status();voices=r.json()['voices']
    def select(gender,use_case):
        return next(v for v in voices if (v.get('labels') or {}).get('accent')=='british' and (v.get('labels') or {}).get('gender')==gender and (v.get('labels') or {}).get('use_case')==use_case)
    alice=select('female','informative_educational')
    george=select('male','narrative_story')
    daniel=select('male','informative_educational')
    if args.scene=='hut':
        profiles=[profile('Narrator','British storyteller','middle_aged','british','mid','clear warm','observant',alice),profile('Harry','youthful British boy','young','british','light','clear','startled and curious',daniel),profile('Hagrid','large warm British man','middle_aged','british','deep','rough resonant','gentle and reassuring',george)]
        required=[beat('storm','Storm ambience starts','ambience_start'),beat('music','Tension music starts','music_start'),beat('knocks','Three heavy knocks','action','three heavy knocks',acoustic='three heavy knocks'),beat('intro','Harry hears the knocks','narration',speaker='Narrator'),beat('burst','The door bursts inward with a crash','action','bursts inward',acoustic='door bursts inward and crashes'),beat('fear','Harry is frightened and speaks','dialogue',speaker='Harry'),beat('entrance','Hagrid reveals his identity and enters','dialogue',speaker='Hagrid'),beat('wonder','Hagrid reveals a magical world; fear becomes wonder','dialogue',speaker='Hagrid'),beat('music_end','Music stops','music_stop'),beat('storm_end','Storm stops before silence','ambience_stop'),beat('end','A short pause after the reveal','silence')]
        premise='In a storm-lashed hut, Harry meets Hagrid. An original fictionalized adaptation with new dialogue.';setting='An isolated hut in a violent storm';climax='Door bursts inward';resolution='Hagrid reveals a world of magic and fear shifts to wonder'; music=Path('outputs/hagrid_scene/music/score.mp3');ambience=Path('outputs/hagrid_scene/sfx/ambience.mp3')
    else:
        profiles=[profile('Narrator','British storyteller','middle_aged','british','mid','clear','grave',alice),profile('Dumbledore','elderly wizard','old','british','low','warm resonant','weak, calm and compassionate',george),profile('Snape','adult British man','middle_aged','british','low','controlled dark','conflicted and restrained',daniel)]
        required=[beat('wind','Cold wind begins','ambience_start'),beat('music','Tension music begins','music_start'),beat('intro','Narrator sets the tower','narration',speaker='Narrator'),beat('confrontation','Dumbledore speaks quietly to Snape','dialogue',speaker='Dumbledore'),beat('spell','Snape speaks the decisive spell','dialogue','Avada Kedavra','Snape'),beat('impact','The spell strikes Dumbledore','action','impact',acoustic='a sharp magical impact'),beat('fall','Dumbledore falls from the tower','action','fall',acoustic='a body falls away followed by distant silence'),beat('reaction','Harry reacts separately from physical events','narration',speaker='Narrator'),beat('music_cut','Music cuts off','music_stop'),beat('wind_cut','Wind stops before silence','ambience_stop'),beat('silence','The scene ends with deliberate silence','silence')]
        premise='A fictionalized tower confrontation. Original dialogue except the user-specified two-word spell.';setting='A wind-swept tower';climax='Snape speaks the spell; impact and fall';resolution='Harry reacts, sound cuts to silence';music=Path('outputs/tower_scene/music/score.mp3');ambience=Path('outputs/tower_scene/sfx/ambience.mp3')
    root=Path('outputs')/f'{args.scene}_revised';root.mkdir(parents=True,exist_ok=True)
    bp=SceneBlueprint(title=args.scene.title()+' regression',premise=premise,setting=setting,character_goals=['Convey each character’s immediate goal'],emotional_states=['fear','tension'],escalation='Escalate through the required sequence',audience_emotion='suspense then emotional release',climax=climax,resolution=resolution,profiles=profiles,required_beats=required,optional_details=['Use original language; never impersonate an actor'])
    (root/'blueprint.json').write_text(bp.model_dump_json(indent=2))
    report=[]
    for p in profiles:
        voice=next(v for v in voices if v['voice_id']==p.voice_id)
        report.append({'character':p.character,'selected_name':voice['name'],'metadata':voice.get('labels',{}),'mismatches':validate_cast(p,voice),'review':'pending human audition','shortlist':[{'name':v['name'],'labels':v.get('labels',{})} for v in shortlist(p,voices)[:3]]})
    (root/'casting_report.json').write_text(json.dumps(report,indent=2))
    provider=ElevenLabs(os.environ['ELEVENLABS_API_KEY'],os.environ['ELEVENLABS_VOICE_ID'],'eleven_v4',os.getenv('ELEVENLABS_MUSIC_MODEL','music_v1'),os.getenv('ELEVENLABS_SFX_MODEL','eleven_text_to_sound_v2'))
    provider.set_usage_log(UsageLog(root/'provider_usage.jsonl'))
    editor=EditorialProvider(os.environ['OPENAI_MODEL']);editor.set_usage_log(UsageLog(root/'provider_usage.jsonl'))
    script_path=root/'screenplay.json'
    if script_path.exists():
        from fablet.scene_director import SceneScreenplay
        screenplay=SceneScreenplay.model_validate_json(script_path.read_text())
    else:
        screenplay=draft(bp,editor,max_attempts=3);script_path.write_text(screenplay.model_dump_json(indent=2))
    errors=validate_screenplay(bp,screenplay)
    if errors: raise ValueError('Screenplay validation failed before audio: '+ '; '.join(errors))
    # Short saved samples are evidence for a human reviewer, not an automatic approval.
    for p in profiles:
        path=root/'auditions'/f'{p.character.lower()}.mp3'
        if not path.exists():
            old=provider.voice;provider.voice=p.voice_id
            try:provider.narrate('[quietly] Listen carefully. We have little time.','','',path)
            finally:provider.voice=old
    print(args.scene,'screenplay validated; beginning audio production',flush=True)
    q=produce(bp,screenplay,root,provider,Path('outputs/rome/cover.webp'),music,ambience)
    print(args.scene,'rendered',round(q['duration_seconds'],2),'seconds; listening and casting review pending',flush=True)

if __name__=='__main__':main()
