"""Produce non-destructive comparisons from saved Fablet stems."""
import argparse
import json
import re
import subprocess
from pathlib import Path
from .audio import render, quality, duration
from .director import active_level, loudness, AudioDirectionPlan, compile_plan
from .models import Timeline, TimelineItem, GainPoint


def compare(root: Path):
    original = Timeline.model_validate_json((root/'timeline.json').read_text())
    music_level = active_level(root/'music/theme.mp3')
    music_gain = min(18.0, -25.0-music_level)
    levels = {'music_active_dbfs': music_level, 'chosen_music_gain_db': music_gain}
    narration = [x for x in original.items if x.kind == 'narration']
    sfx = [x.model_copy(update={'gain_db': min(12, -25-active_level(root/x.path))}) for x in original.items if x.kind == 'sfx']
    music = [x.model_copy(update={'gain_db': music_gain}) for x in original.items if x.kind == 'music']
    for mode in ('basic', 'ducked', 'directed'):
        if mode == 'directed':
            # J-cut into the opening and hand-selected unscored sections; no new assets.
            theme = root/'music/theme.mp3'
            intro_end = narration[0].start_seconds + 3
            intro = TimelineItem(path='music/theme.mp3',start_seconds=.8,duration_seconds=min(duration(theme),intro_end-.8),gain_db=music_gain,kind='music')
            cues = [intro]+music
            # Relative gain envelopes lower the score before the first word;
            # these smooth ramps are independent of reactive compression.
            for cue in cues:
                lead = max(.05, min(.6, cue.duration_seconds / 3))
                cue.gain_envelope = [GainPoint(time_seconds=0, gain_db=0), GainPoint(time_seconds=lead, gain_db=-3)]

        else:
            cues = music
        timeline = Timeline(items=narration+cues+sfx,duration_seconds=original.duration_seconds)
        out = root/f'master_{mode}.mp3'
        render(timeline, root, out, ducking=(mode=='ducked'))
        q = quality(out,root/'cover.webp', timeline.duration_seconds)
        q['loudness'] = loudness(out)
        q['active_region_levels'] = []
        for voice in narration:
            measured = subprocess.run(['ffmpeg','-hide_banner','-ss',str(voice.start_seconds),'-t',str(voice.duration_seconds),'-i',str(out),'-af','volumedetect','-f','null','-'],capture_output=True,text=True,check=True)
            mean = re.search(r'mean_volume:\s*(-?[\d.]+) dB', measured.stderr)
            q['active_region_levels'].append({'segment':voice.path,'mixed_region_mean_dbfs':float(mean.group(1)) if mean else None,'start_seconds':voice.start_seconds,'duration_seconds':voice.duration_seconds})
        q['calibration'] = levels
        q['cue_execution'] = [x.model_dump() for x in cues+sfx]
        q['limitations'] = ['Requires human listening; no water-drop or dedicated ambience asset is available.', 'Music active level is a whole-stem estimate, not a perceptual masking measurement.']
        (root/f'qa_{mode}.json').write_text(json.dumps(q,indent=2))
        if mode == 'directed':
            q['unresolved_cues'] = [{'cue': 'water-drop', 'reason': 'No water-drop asset or word alignment available; omitted.'}]
            (root/f'qa_{mode}.json').write_text(json.dumps(q,indent=2))
        (root/f'cue_sheet_{mode}.json').write_text(json.dumps({'cues': q['cue_execution'], 'unresolved': q.get('unresolved_cues', [])},indent=2))
        print(mode, q['loudness']['input_i'], 'LUFS', q['loudness']['input_tp'], 'dBTP')

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args();compare(args.output)
