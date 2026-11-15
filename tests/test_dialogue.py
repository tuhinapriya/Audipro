import base64
import json
import httpx
import pytest
from fablet.models import NarrativeDirectionPlan
from fablet.providers import ElevenLabs


def test_text_to_dialogue_request_and_alignment(tmp_path):
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json={'audio_base64':base64.b64encode(b'audio').decode(),'voice_segments':[{'dialogue_input_index':0,'start_time_seconds':0,'end_time_seconds':1}]})
    p=ElevenLabs('key','voice','eleven_v4','music_v1')
    p.http.close();p.http=httpx.Client(base_url='https://api.elevenlabs.io/v1/',transport=httpx.MockTransport(handler))
    p.dialogue([{'text':'[whispers] Hello','voice_id':'one'},{'text':'[urgent] Go','voice_id':'two'}],tmp_path/'dialogue.mp3',tmp_path/'alignment.json')
    assert seen[0].url.path=='/v1/text-to-dialogue/with-timestamps'
    assert json.loads(seen[0].content)['model_id']=='eleven_v4'
    assert len(json.loads(seen[0].content)['inputs'])==2
    assert (tmp_path/'dialogue.mp3').read_bytes()==b'audio'
    assert json.loads((tmp_path/'alignment.json').read_text())['voice_segments'][0]['dialogue_input_index']==0


def test_unrecognized_character_rejected():
    with pytest.raises(ValueError):
        NarrativeDirectionPlan.model_validate({'title':'x','context':'x','fictionalized':True,'cast':[{'name':'Narrator','voice_id':'1','role':'narrator'},{'name':'One','voice_id':'2','role':'character'}],'narrator_text':'x','dialogue':[{'speaker':'unknown','text':'Hi'}],'music_prompt':'x','ambience_prompt':'x'})


def test_requested_turn_pause_is_rendered_from_provider_timestamps(tmp_path):
    import subprocess
    from PIL import Image
    from fablet.cinematic import render_scene
    def tone(path, seconds):
        path.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(['ffmpeg','-y','-v','error','-f','lavfi','-i',f'sine=frequency=440:duration={seconds}','-c:a','libmp3lame',str(path)],check=True)
    class FakeProvider:
        voice='n';tts_model='eleven_v4';music_model='music_v1';sfx_model='eleven_text_to_sound_v2'
        def set_usage_log(self, log): pass
        def narrate(self, text, previous, following, dest): tone(dest,1)
        def dialogue(self, turns, dest, metadata):
            tone(dest,2)
            metadata.write_text(json.dumps({'voice_segments':[{'dialogue_input_index':0,'start_time_seconds':0,'end_time_seconds':1},{'dialogue_input_index':1,'start_time_seconds':1,'end_time_seconds':2}]}))
        def music(self, prompt, seconds, dest): tone(dest,seconds)
        def effect(self, prompt, seconds, dest): tone(dest,seconds)
    plan=NarrativeDirectionPlan.model_validate({'title':'test','context':'fiction','fictionalized':True,'cast':[{'name':'Narrator','voice_id':'n','role':'narrator'},{'name':'A','voice_id':'a','role':'character'},{'name':'B','voice_id':'b','role':'character'}],'narrator_text':'A scene.','dialogue':[{'speaker':'A','text':'First','pause_after_seconds':1},{'speaker':'B','text':'Second'}],'music_prompt':'instrumental','ambience_prompt':'wind','ending_silence_seconds':.5})
    cover=tmp_path/'cover.webp';Image.new('RGB',(10,10)).save(cover,'WEBP')
    output=tmp_path/'out';render_scene(plan,output,FakeProvider(),cover)
    cues=json.loads((output/'cue_sheet.json').read_text())
    first,second=cues['dialogue_turns']
    assert second['scene_start']-first['scene_start'] >= 1.9
    assert (output/'master.mp3').stat().st_size > 0
