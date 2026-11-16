"""Controlled Tower mix/acting experiment; never writes to saved production.

The opt-in dialogue redo uses one paid contextual generation, no narrator
generation, and no automatic generation retries. ASR reviews are also paid.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import math
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

from fablet.audio import _expressive_filters, duration, quality, render, volume_filter
from fablet.casting import CastRegistry
from fablet.director import loudness
from fablet.models import ExpressiveItemMix, ExpressiveMix, GainPoint, Timeline, TimelineItem
from fablet.performance import _perform, align_block, performance_text
from fablet.providers import ElevenLabs
from fablet.scene_director import SceneBlueprint, SceneScreenplay, VocalPerformance, validate_screenplay
from fablet.speech_qa import compare, transcribe, transcribe_secondary
from fablet.usage import UsageLog

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'outputs/tower_revised'
COVER = ROOT / 'outputs/rome/cover.webp'


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe_access(registry):
    results = {}
    with httpx.Client(timeout=30) as client:
        eleven = os.getenv('ELEVENLABS_API_KEY')
        openai = os.getenv('OPENAI_API_KEY')
        if not eleven or not openai:
            return {'credentials': 'missing ElevenLabs or OpenAI key'}
        requests = [
            ('eleven_models', 'https://api.elevenlabs.io/v1/models', {'xi-api-key': eleven}),
            ('openai_models', 'https://api.openai.com/v1/models', {'Authorization': 'Bearer ' + openai}),
        ]
        for key in ('narrator', 'tower:Dumbledore', 'tower:Snape'):
            requests.append((key, 'https://api.elevenlabs.io/v1/voices/' + registry.entries[key].voice_id,
                             {'xi-api-key': eleven}))
        for label, url, headers in requests:
            try:
                results[label] = client.get(url, headers=headers).status_code
            except httpx.HTTPError as exc:
                results[label] = type(exc).__name__
    return results


def words_anchor(evidence, clip_length):
    """Use ASR word boundaries, not invalid or padded provider segments."""
    words = evidence['word_times']
    for index, word in enumerate(words[:-1]):
        if re.sub(r'[^a-z]', '', word['word'].lower()) == 'avada' and re.sub(r'[^a-z]', '', words[index + 1]['word'].lower()) == 'kedavra':
            start, end = float(word['start']), float(words[index + 1]['end'])
            if 0 <= start < end <= clip_length:
                return {'start': start, 'end': end, 'source': 'whisper-1 word timestamps; approximate, human review required'}
    raise ValueError('ASR lacks usable Avada Kedavra word timestamps; cannot anchor impact')


def background_envelope(start, length, snape):
    # Same authored -3 dB dip in both music and wind around the incoming turn.
    times = [(snape - .65, 0), (snape - .18, -3), (snape + .25, -3), (snape + .65, 0)]
    def level(t):
        if t <= times[0][0] or t >= times[-1][0]:
            return 0.0
        for (a, x), (b, y) in zip(times, times[1:]):
            if a <= t <= b:
                return x + (y - x) * (t - a) / (b - a)
        raise AssertionError('unreachable')
    points = [start] + [t for t, _ in times if start < t < start + length] + [start + length]
    return [GainPoint(time_seconds=t-start, gain_db=level(t)) for t in points]


def build_timeline(paths, anchors, common_end):
    intro = duration(paths['e03'])
    block_length = duration(paths['block'])
    snape = intro + anchors['start']
    impact = intro + anchors['end'] - .10
    if impact < intro or impact + 4 > common_end:
        raise ValueError('Invalid impact anchor')
    e08_start = paths['e08_start']
    items = [
        TimelineItem(path=paths['e03'].name, kind='narration', start_seconds=0, duration_seconds=intro),
        TimelineItem(path=paths['block'].name, kind='narration', start_seconds=intro, duration_seconds=block_length),
        TimelineItem(path='e06.mp3', kind='sfx', start_seconds=impact, duration_seconds=duration(paths['e06']), gain_db=4),
        TimelineItem(path='e07.mp3', kind='sfx', start_seconds=impact + duration(paths['e06']), duration_seconds=duration(paths['e07']), gain_db=4),
        TimelineItem(path=paths['e08'].name, kind='narration', start_seconds=e08_start, duration_seconds=duration(paths['e08'])),
        TimelineItem(path='music.mp3', kind='music', start_seconds=0, duration_seconds=common_end, gain_db=5.3,
                     fade_out_seconds=0, gain_envelope=background_envelope(0, common_end, snape)),
    ]
    pos = 0.0
    while pos < common_end:
        length = min(duration(paths['ambience']), common_end-pos)
        items.append(TimelineItem(path='ambience.mp3', kind='sfx', start_seconds=pos, duration_seconds=length,
                                  gain_db=10.6, gain_envelope=background_envelope(pos, length, snape)))
        if pos + length >= common_end:
            break
        pos += length - .1
    mix = ExpressiveMix(duck_gain_db=-9, attack_seconds=.15, release_seconds=.3,
                        items={4: ExpressiveItemMix(gain_offset_db=-2),
                               **{i: ExpressiveItemMix(ambience=True) for i in range(6, len(items))}})
    return Timeline(items=items, duration_seconds=common_end+4), mix, {
        'intro_end': intro, 'snape_start_asr': snape, 'spell_end_asr': intro+anchors['end'],
        'impact_start': impact, 'fall_start': impact+duration(paths['e06']),
        'e08_start': e08_start, 'background_end': common_end, 'silence_end': common_end+4,
        'alignment_source': anchors['source'],
    }


def premaster_bus(timeline, mix, root, output, voice):
    """Export isolated linear buses with the renderer's exact per-item filters.

    These do not include the final nonlinear master loudnorm/MP3 encoding.
    """
    args = ['ffmpeg', '-y', '-v', 'error']
    filters, labels = [], []
    for i, item in enumerate(timeline.items):
        if (item.kind == 'narration') != voice:
            continue
        index = len(labels)
        args += ['-i', str(root / item.path)]
        fade = min(1.0 if item.kind == 'music' else .03, item.duration_seconds / 4)
        fi = fade if item.fade_in_seconds is None else min(item.fade_in_seconds, item.duration_seconds)
        fo = fade if item.fade_out_seconds is None else min(item.fade_out_seconds, item.duration_seconds)
        fades = (f',afade=t=in:st=0:d={fi}:curve=qsin' if fi else '') + (f',afade=t=out:st={max(0,item.duration_seconds-fo)}:d={fo}:curve=qsin' if fo else '')
        delay = round(item.start_seconds * 1000)
        extra = _expressive_filters(item, i, timeline, mix, True)
        filters.append(f'[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=duration={item.duration_seconds},asetpts=PTS-STARTPTS,{volume_filter(item)}{extra}{fades},adelay={delay}|{delay}[a{index}]')
        labels.append(f'[a{index}]')
    # No apad: the measurement windows end with the sources, and padded audio
    # is unnecessary. Bound by both sample count and wall time as a safeguard.
    samples = math.ceil(timeline.duration_seconds * 48000)
    filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=longest:normalize=0,atrim=end_sample={samples}[out]')
    subprocess.run(args+['-filter_complex', ';'.join(filters), '-map', '[out]', '-t', str(timeline.duration_seconds),
                         '-c:a', 'pcm_f32le', str(output)], check=True, capture_output=True, timeout=60)


def rms(path, start, end):
    result = subprocess.run(['ffmpeg', '-hide_banner', '-ss', str(start), '-t', str(end-start), '-i', str(path),
                             '-af', 'volumedetect', '-f', 'null', '-'], check=True, capture_output=True, text=True)
    match = re.search(r'mean_volume:\s*(-?[\d.]+) dB', result.stderr)
    return float(match.group(1)) if match else None


def measurements(master, cue, voice=None, background=None):
    windows = {'dumbledore': (cue['intro_end'], cue['snape_start_asr']),
               'snape': (cue['snape_start_asr'], cue['spell_end_asr']),
               'reaction': (cue['e08_start'], cue['background_end'])}
    if 'impact_start' in cue and cue['impact_start'] - .05 > cue['snape_start_asr']:
        windows['snape_before_impact'] = (cue['snape_start_asr'], cue['impact_start'] - .05)
    result = {'loudnorm_measurement': loudness(master), 'windows': {}}
    for label, (start, end) in windows.items():
        row = {'start_seconds': start, 'end_seconds': end, 'master_rms_dbfs': rms(master, start, end)}
        if voice and background:
            row['premaster_voice_rms_dbfs'] = rms(voice, start, end)
            row['premaster_background_rms_dbfs'] = rms(background, start, end)
            row['premaster_voice_minus_background_db'] = round(row['premaster_voice_rms_dbfs']-row['premaster_background_rms_dbfs'], 2)
        result['windows'][label] = row
    return result


def master_review(path, expected, log):
    text, words = transcribe(path, log)
    result = compare(expected, text, words)
    result.update({'model': 'whisper-1', 'word_times': words, 'audio_sha256': sha(path)})
    if result['uncertain']:
        result['secondary_asr'] = {'model': 'gpt-4o-transcribe', **compare(expected, transcribe_secondary(path, log))}
        result['interpretation'] = 'ASR disagreement requires human review.'
    return result


def recover(previous):
    """Finish measurement from retained evidence without any speech generation."""
    previous = previous.resolve()
    if not previous.is_relative_to((ROOT/'outputs').resolve()) or not previous.name.startswith('tower_expressive_experiment_'):
        raise ValueError('Recovery source must be an experiment output directory')
    output = ROOT/'outputs'/('tower_expressive_experiment_recovered_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    output.mkdir(parents=True, exist_ok=False)
    for item in previous.iterdir():
        if item.is_dir():
            shutil.copytree(item, output/item.name)
        elif item.name != 'performance_and_mix_background_premaster.wav':
            shutil.copy2(item, output/item.name)
    load_dotenv(ROOT/'.env')
    registry = CastRegistry.load(ROOT/'config/cast_registry.json')
    screenplay = SceneScreenplay.model_validate_json((output/'directed_screenplay.json').read_text())
    events = {event.id: event for event in screenplay.events}
    blueprint = SceneBlueprint.model_validate_json((SOURCE/'blueprint.json').read_text())
    cue = json.loads((output/'baseline_cue_sheet.json').read_text())
    base_asr = json.loads((output/'baseline_dialogue_refreshed_asr.json').read_text())
    base_anchor = words_anchor(base_asr, duration(output/'assets/block.mp3'))
    old_meta = json.loads((output/'assets/block.json').read_text())
    old_align, old_issues = align_block([events['e04'], events['e05']], old_meta.get('voice_segments'), duration(output/'assets/block.mp3'))
    stems = list((output/'performances').glob('e04__e05_*_attempt1.mp3'))
    reactions = list((output/'performances').glob('e08_*_attempt1.mp3'))
    if len(stems) != 1 or len(reactions) != 1:
        raise ValueError('Recovery requires exactly one retained dialogue and narration attempt')
    block, reaction = stems[0], reactions[0]
    new_meta = json.loads(block.with_suffix('.json').read_text())
    new_align, new_issues = align_block([events['e04'], events['e05']], new_meta.get('voice_segments'), duration(block))
    for alignment, issues in ((old_align, old_issues), (new_align, new_issues)):
        for item in alignment:
            if item['voice_ids'] != [registry.entries['tower:'+item['speaker']].voice_id]:
                issues.append(item['event_id']+': speaker metadata mismatch')
    timeline = Timeline.model_validate_json((output/'performance_and_mix_timeline.json').read_text())
    mix = ExpressiveMix.model_validate_json((output/'performance_and_mix_mix.json').read_text())
    premaster_bus(timeline, mix, output/'assets', output/'performance_and_mix_background_premaster.wav', False)
    baseline_cue = {'intro_end': cue['events'][3]['start_seconds'],
                    'snape_start_asr': duration(output/'assets/e03.mp3')+base_anchor['start'],
                    'spell_end_asr': duration(output/'assets/e03.mp3')+base_anchor['end'],
                    'e08_start': cue['events'][7]['start_seconds'], 'background_end': cue['events'][8]['start_seconds']}
    results = {'baseline_unchanged': {'measurement': measurements(output/'baseline_unchanged.mp3', baseline_cue),
                                      'qa_evidence': 'baseline_qa_report.json'}}
    blockers = [{'stage': 'initial measurement export', 'error_type': 'unbounded FFmpeg apad output',
                 'note': 'Stopped and removed temporary file; recovered without regenerating speech.'}]
    expected = ' '.join(events[e].text for e in ('e03', 'e04', 'e05', 'e08'))
    for name in ('mix_only', 'performance_and_mix'):
        master = output/(name+'.mp3')
        cues = json.loads((output/(name+'_cues.json')).read_text())
        if name == 'performance_and_mix':
            qa = quality(master, COVER, timeline.duration_seconds, allowed_silence=[(cues['background_end'], cues['silence_end'])])
            qa['human_listening_completed'] = False
            try:
                qa['master_asr'] = master_review(master, expected, UsageLog(output/'provider_usage.jsonl'))
            except Exception as exc:
                code = exc.response.status_code if hasattr(exc, 'response') and exc.response is not None else None
                blockers.append({'stage': name+' master ASR', 'error_type': type(exc).__name__, 'http_status': code})
            save(output/(name+'_qa.json'), qa)
        results[name] = {'cues': cues, 'measurement': measurements(master, cues, output/(name+'_voice_premaster.wav'),
                                                                   output/(name+'_background_premaster.wav')),
                         'qa': name+'_qa.json'}
    baseline_hash = sha(SOURCE/'master_performance_fixed.mp3')
    status = {'baseline_sha256': baseline_hash, 'baseline_copy_sha256': sha(output/'baseline_unchanged.mp3'),
              'baseline_unchanged_verified': baseline_hash == sha(output/'baseline_unchanged.mp3'),
              'baseline_actual_provider_alignment': old_align, 'baseline_alignment_issues': old_issues,
              'new_dialogue_alignment': new_align, 'new_dialogue_alignment_issues': new_issues,
              'new_dialogue_review': json.loads(block.with_suffix('.review.json').read_text()),
              'new_reaction_review': json.loads(reaction.with_suffix('.review.json').read_text()),
              'cast_voice_ids': {key: registry.entries[key].voice_id for key in ('narrator','tower:Dumbledore','tower:Snape')},
              'blueprint_narrator_voice_id': next(p.voice_id for p in blueprint.profiles if p.character == 'Narrator'),
              'narrator_cast_note': 'Baseline narration metadata matches locked registry, not stale blueprint narrator.',
              'human_listening_completed': False, 'blockers': blockers, 'conditions': list(results),
              'method': ['Same mix settings; word-timestamp-dependent cue placement; shared reaction start and final cut.',
                         'No invented human breath or other new sound; existing action and bed assets reused.',
                         'Premaster voice/background buses include speech and all non-speech respectively; master loudnorm is nonlinear.',
                         'ASR and provider timing are evidence, not a substitute for human listening.']}
    save(output/'results.json', {'status': status, 'results': results})
    print(json.dumps({'output': str(output), 'conditions': list(results), 'blockers': blockers}, indent=2))


def legacy_main():
    load_dotenv(ROOT / '.env')
    output = ROOT / 'outputs' / ('tower_expressive_experiment_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    output.mkdir(parents=True, exist_ok=False)
    assets = output / 'assets'
    assets.mkdir()
    baseline = SOURCE / 'master_performance_fixed.mp3'
    baseline_hash = sha(baseline)
    shutil.copy2(baseline, output / 'baseline_unchanged.mp3')
    for name in ('cue_sheet.json', 'qa_report.json', 'timeline.json'):
        shutil.copy2(SOURCE / 'performance_fixed' / name, output / ('baseline_' + name))
    cue = json.loads((SOURCE / 'performance_fixed/cue_sheet.json').read_text())
    script = SceneScreenplay.model_validate_json((SOURCE / 'screenplay.json').read_text())
    blueprint = SceneBlueprint.model_validate_json((SOURCE / 'blueprint.json').read_text())
    errors = validate_screenplay(blueprint, script)
    if errors:
        raise ValueError('; '.join(errors))
    events = {e.id: e for e in script.events}
    registry = CastRegistry.load(ROOT / 'config/cast_registry.json')
    for char, key in [('Dumbledore', 'tower:Dumbledore'), ('Snape', 'tower:Snape')]:
        if next(p for p in blueprint.profiles if p.character == char).voice_id != registry.entries[key].voice_id:
            raise ValueError(f'Locked cast mismatch for {char}')
    asset_events = {e['event_id']: e['asset'] for e in cue['events'] if e['event_id'] in ('e03', 'e04', 'e08')}
    copies = {'e03': SOURCE / asset_events['e03'], 'block': SOURCE / asset_events['e04'],
              'e08': SOURCE / asset_events['e08'], 'e06': SOURCE / 'sfx/e06.mp3',
              'e07': SOURCE / 'sfx/e07.mp3', 'music': SOURCE / 'music.mp3', 'ambience': SOURCE / 'ambience.mp3'}
    base = {}
    for label, source in copies.items():
        dest = assets / (label + '.mp3')
        shutil.copy2(source, dest)
        base[label] = dest
        for extension in ('.json', '.asr.json', '.review.json', '.secondary.json'):
            evidence = source.with_suffix(extension)
            if evidence.exists():
                shutil.copy2(evidence, assets / (label + extension))
    baseline_asr = json.loads((assets / 'block.asr.json').read_text())
    for label in ('e03', 'e08'):
        if json.loads((assets / (label+'.json')).read_text()).get('voice_id') != registry.entries['narrator'].voice_id:
            raise ValueError(f'{label}: saved narration voice differs from locked cast')
    if baseline_asr.get('audio_sha256') and baseline_asr['audio_sha256'] != sha(base['block']):
        raise ValueError('Baseline ASR does not match dialogue audio')
    base_anchor = words_anchor(baseline_asr, duration(base['block']))
    metadata = json.loads((assets / 'block.json').read_text())
    alignment, issues = align_block([events['e04'], events['e05']], metadata.get('voice_segments'), duration(base['block']))
    for item in alignment:
        if item['voice_ids'] != [registry.entries['tower:'+item['speaker']].voice_id]:
            issues.append(item['event_id'] + ': speaker metadata mismatch')
    status = {'baseline_sha256': baseline_hash, 'baseline_actual_provider_alignment': alignment,
              'baseline_alignment_issues': issues, 'baseline_anchor': base_anchor,
              'legacy_baseline_asr_hash_present': bool(baseline_asr.get('audio_sha256')),
              'blueprint_narrator_voice_id': next(p.voice_id for p in blueprint.profiles if p.character == 'Narrator'),
              'narrator_cast_note': 'Saved e03/e08 narration metadata matches the locked registry; the blueprint narrator profile may be stale.',
              'baseline_cue_sheet_alignment_claim': 'historical provider label; independently revalidated above',
              'cast_voice_ids': {key: registry.entries[key].voice_id for key in ('narrator', 'tower:Dumbledore', 'tower:Snape')},
              'human_listening_completed': False, 'blockers': []}
    direction = {
        'e04': VocalPerformance(emotion='restrained', vocal_effort='soft', delivery_note='Weak but composed; private and protective.'),
        'e05': VocalPerformance(emotion='furious', vocal_effort='projected', delivery_note='Forceful and resolute, with conviction; no actor imitation.'),
        'e08': VocalPerformance(emotion='sad', vocal_effort='soft', delivery_note='Close and plain, without sentimentality.'),
    }
    for key, value in direction.items():
        events[key].vocal_performance = value
    save(output / 'directed_screenplay.json', script.model_dump())
    status['actual_v4_inputs'] = {key: performance_text(events[key], 'eleven_v4') for key in direction}
    access = probe_access(registry)
    status['access_checks'] = access
    variant = None
    log = UsageLog(output / 'provider_usage.jsonl')
    if not baseline_asr.get('audio_sha256') and access.get('openai_models') == 200:
        try:
            text, word_times = transcribe(base['block'], log)
            refreshed = {'transcript': text, 'word_times': word_times, 'audio_sha256': sha(base['block']),
                         'review': compare(events['e04'].text+' '+events['e05'].text, text, word_times)}
            save(output / 'baseline_dialogue_refreshed_asr.json', refreshed)
            base_anchor = words_anchor(refreshed, duration(base['block']))
            status['baseline_anchor'] = base_anchor
        except Exception as exc:
            status['blockers'].append({'stage': 'baseline ASR refresh', 'error_type': type(exc).__name__,
                                       'note': 'Using legacy unbound ASR timestamps; human verification required.'})
    elif not baseline_asr.get('audio_sha256'):
        status['blockers'].append({'stage': 'baseline ASR refresh', 'error_type': 'OpenAI access unavailable',
                                   'note': 'Using legacy unbound ASR timestamps; human verification required.'})
    if access and all(value == 200 for value in access.values()):
        provider = ElevenLabs(os.environ['ELEVENLABS_API_KEY'], registry.entries['narrator'].voice_id, 'eleven_v4', 'music_v1')
        provider.set_usage_log(log)
        try:
            block, block_review, alignment, issues = _perform([events['e04'], events['e05']], output, provider, registry, 'tower', log, max_attempts=1)
            block_asr = json.loads(block.with_suffix('.asr.json').read_text())
            block_anchor = words_anchor(block_asr, duration(block))
            status['new_dialogue_alignment'] = alignment
            status['new_dialogue_alignment_issues'] = issues
            status['new_dialogue_review'] = block_review
            reaction, reaction_review, _, _ = _perform([events['e08']], output, provider, registry, 'tower', log, max_attempts=1)
            status['new_reaction_review'] = reaction_review
            variant = dict(base)
            for label, source in [('block', block), ('e08', reaction)]:
                dest = assets / ('new_' + label + '.mp3')
                shutil.copy2(source, dest)
                variant[label] = dest
            status['new_anchor'] = block_anchor
        except Exception as exc:
            # API bodies and credentials are deliberately not recorded.
            code = exc.response.status_code if hasattr(exc, 'response') and exc.response is not None else None
            status['blockers'].append({'stage': 'selective performance or ASR', 'error_type': type(exc).__name__, 'http_status': code})
        finally:
            provider.http.close()
    else:
        status['blockers'].append({'stage': 'provider access preflight', 'checks': access})

    variants = [('mix_only', base, base_anchor)]
    if variant is not None:
        variants.append(('performance_and_mix', variant, block_anchor))
    intro = duration(base['e03'])
    impact_ends = [intro + anchor['end'] - .10 + duration(paths['e06']) + duration(paths['e07']) for _, paths, anchor in variants]
    e08_start = max(impact_ends)
    common_end = e08_start + max(duration(paths['e08']) for _, paths, _ in variants)
    baseline_cue = {'intro_end': cue['events'][3]['start_seconds'],
                    'snape_start_asr': intro+base_anchor['start'], 'spell_end_asr': intro+base_anchor['end'],
                    'e08_start': cue['events'][7]['start_seconds'], 'background_end': cue['events'][8]['start_seconds']}
    results = {'baseline_unchanged': {'measurement': measurements(output/'baseline_unchanged.mp3', baseline_cue),
                                      'qa_evidence': 'baseline_qa_report.json'}}
    expected = ' '.join(events[e].text for e in ('e03', 'e04', 'e05', 'e08'))
    for name, paths, anchor in variants:
        paths['e08_start'] = e08_start
        timeline, mix, cues = build_timeline(paths, anchor, common_end)
        save(output / (name+'_timeline.json'), timeline.model_dump())
        save(output / (name+'_mix.json'), mix.model_dump())
        save(output / (name+'_cues.json'), cues)
        master = output / (name+'.mp3')
        render(timeline, assets, master, expressive_mix=mix)
        voice, background = output / (name+'_voice_premaster.wav'), output / (name+'_background_premaster.wav')
        premaster_bus(timeline, mix, assets, voice, True)
        premaster_bus(timeline, mix, assets, background, False)
        qa = quality(master, COVER, timeline.duration_seconds, allowed_silence=[(common_end, common_end+4)])
        qa['human_listening_completed'] = False
        if access.get('openai_models') == 200:
            try:
                qa['master_asr'] = master_review(master, expected, log)
            except Exception as exc:
                code = exc.response.status_code if hasattr(exc, 'response') and exc.response is not None else None
                status['blockers'].append({'stage': name+' master ASR', 'error_type': type(exc).__name__, 'http_status': code})
        else:
            status['blockers'].append({'stage': name+' master ASR', 'error_type': 'OpenAI access unavailable'})
        save(output / (name+'_qa.json'), qa)
        results[name] = {'cues': cues, 'measurement': measurements(master, cues, voice, background), 'qa': name+'_qa.json'}
    status['baseline_sha256_after'] = sha(baseline)
    status['baseline_copy_sha256'] = sha(output/'baseline_unchanged.mp3')
    status['baseline_unchanged_verified'] = status['baseline_sha256'] == status['baseline_sha256_after'] == status['baseline_copy_sha256']
    status['conditions'] = list(results)
    status['method'] = ['Both experimental conditions use identical authored mix settings, shared narration start and final cut; impact is anchored individually to ASR word timing.',
                        'The fall and original action assets are reused; no breath, scream or other absent human sound was added.',
                        'The matched common background cut pads a shorter reaction or fall-to-reaction gap, rather than trimming speech; four seconds of silence follow.',
                        'Voice/background RMS values are separate pre-master linear buses; nonlinear master loudnorm prevents direct attribution on the final master.',
                        'ASR timestamps and automatic reviews are fallible; acting, sound content and listening quality are not evaluated.']
    save(output / 'results.json', {'status': status, 'results': results})
    print(json.dumps({'output': str(output), 'conditions': list(results), 'blockers': status['blockers'], 'baseline_unchanged_verified': status['baseline_unchanged_verified']}, indent=2))


PREVIOUS = ROOT / 'outputs/tower_expressive_experiment_recovered_20261116T003930247029Z'


def technical_report(output, status, results):
    lines = [
        '# Tower selective-dialogue experiment', '',
        f"Completion: {status.get('completion', 'in progress')}. Human listening: not completed.", '',
        '## Controls and provenance', '',
        f"- Baseline SHA-256 before: {status.get('baseline_sha256', 'unavailable')}; after: {status.get('baseline_sha256_after', 'unavailable')}; copy: {status.get('baseline_copy_sha256', 'unavailable')}; unchanged: {status.get('baseline_unchanged_verified', False)}.",
        f"- Previous output: {status['previous_output']}; its original assets and all prior performance stems/evidence are copied into this output.",
        f"- Dialogue generation calls attempted: {status['dialogue_generation_calls_attempted']}; narration generation calls: 0; automatic generation retries: 0.",
        f"- Dialogue source: {status.get('dialogue_source', 'unavailable')}; regenerated e08 source: {status.get('reaction_source', 'unavailable')}.",
        '- Mix-only uses the original e03, dialogue and e08 audio; performance uses the original e03, selected dialogue and the previously regenerated e08.',
        f"- Speech asset hashes: {json.dumps(status.get('speech_hashes', {}), ensure_ascii=False)}.",
        f"- Exact v4 inputs: {json.dumps(status.get('actual_v4_inputs', {}), ensure_ascii=False)}. The bracketed tags are cues; all words and punctuation remain unchanged. Delivery notes are not sent to the provider.",
        '- Locked registry voices are used; no actor or speaker imitation is requested. A cue is not evidence that the generated acting meets the requested direction.', '',
        '## Spatial and breath evidence', '',
        '- The screenplay describes an exposed stone tower and Harry out of sight, but does not establish reliable left/right positions or a usable spatial separation of the two dialogue turns. No invented pan, distance or reflection is applied; the contextual block cannot represent separate turn positions.',
        '- Existing impact and fall prompts explicitly exclude voices or screams; the reaction mentions breath as narration, not a verified standalone human-breath asset. No suitable human breath was verified by listening. No breath was generated or added; an existing sound or a spoken word is not claimed as actual breath.', '',
        '## Measurements and QA', '',
        '- Identical authored mix settings in both variants: -9 dB speech ducking, a -3 dB bed dip near the spell, and -2 dB e08. Timing follows each dialogue ASR; e08 start and the ending cut are shared. This does not imply identical sample-by-sample envelopes.',
        '- Integrated LUFS and true peak are FFmpeg loudnorm input measurements. RMS is mean volume over each ASR-derived window, including pauses. Premaster voice/background buses include all speech/non-speech and cannot be directly attributed after nonlinear master processing.', '',
        '| Condition | LUFS | True peak dBTP | Dumbledore RMS dBFS | Snape RMS dBFS | Reaction RMS dBFS |',
        '|---|---:|---:|---:|---:|---:|',
    ]
    for name, result in results.items():
        measurement = result['measurement']
        loud = measurement['loudnorm_measurement']
        windows = measurement['windows']
        lines.append(f"| {name} | {loud['input_i']} | {loud['input_tp']} | {windows['dumbledore']['master_rms_dbfs']} | {windows['snape']['master_rms_dbfs']} | {windows['reaction']['master_rms_dbfs']} |")
    lines += ['', f"- Mix settings match: {status.get('mix_settings_identical', 'not evaluated')}.",
              f"- New dialogue alignment issues: {json.dumps(status.get('dialogue_alignment_issues', 'not evaluated'))}.",
              f"- Dialogue automatic review: {json.dumps(status.get('dialogue_review', 'not available'), ensure_ascii=False)}.",
              f"- Master review summary: {json.dumps(status.get('master_review_summary', {}), ensure_ascii=False)}.",
              '- ASR and provider segment times are approximate; actor delivery, breath, spatial impression, intelligibility and final suitability require human listening. Review the full QA and bus-window measurements in results.json.',
              f"- Blockers: {json.dumps(status.get('blockers', []), ensure_ascii=False)}.", '']
    (output / 'TECHNICAL_REPORT.md').write_text('\n'.join(lines))


def revised_experiment(previous, redo_dialogue):
    """Reuse prior evidence; optionally request only a single dialogue block."""
    previous = previous.resolve()
    if not previous.is_relative_to((ROOT / 'outputs').resolve()) or not previous.name.startswith('tower_expressive_experiment_'):
        raise ValueError('Previous output must be a Tower experiment output directory')
    output = ROOT / 'outputs' / ('tower_expressive_experiment_revision_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    output.mkdir(parents=True, exist_ok=False)
    status = {'previous_output': str(previous), 'dialogue_generation_calls_attempted': 0,
              'narrator_generation_calls': 0, 'automatic_generation_retries': 0,
              'human_listening_completed': False, 'blockers': [], 'completion': 'in progress'}
    results = {}
    failed = False
    stage = 'setup'
    baseline = SOURCE / 'master_performance_fixed.mp3'
    try:
        load_dotenv(ROOT / '.env')
        status['baseline_sha256'] = sha(baseline)
        shutil.copy2(baseline, output / 'baseline_unchanged.mp3')
        shutil.copytree(previous / 'assets', output / 'assets')
        shutil.copytree(previous / 'performances', output / 'prior_performances')
        for filename in ('baseline_cue_sheet.json', 'baseline_qa_report.json', 'baseline_timeline.json',
                         'baseline_dialogue_refreshed_asr.json', 'results.json', 'directed_screenplay.json', 'TECHNICAL_REPORT.md'):
            if (previous / filename).is_file():
                shutil.copy2(previous / filename, output / ('prior_' + filename))
        assets = output / 'assets'
        script = SceneScreenplay.model_validate_json((SOURCE / 'screenplay.json').read_text())
        blueprint = SceneBlueprint.model_validate_json((SOURCE / 'blueprint.json').read_text())
        errors = validate_screenplay(blueprint, script)
        if errors:
            raise ValueError('; '.join(errors))
        events = {e.id: e for e in script.events}
        registry = CastRegistry.load(ROOT / 'config/cast_registry.json')
        for char in ('Dumbledore', 'Snape'):
            if next(p for p in blueprint.profiles if p.character == char).voice_id != registry.entries['tower:' + char].voice_id:
                raise ValueError(f'Locked cast mismatch for {char}')
        for label in ('e03', 'e08'):
            if json.loads((assets / (label + '.json')).read_text()).get('voice_id') != registry.entries['narrator'].voice_id:
                raise ValueError(f'Original {label} narrator differs from locked cast')
        events['e04'].vocal_performance = VocalPerformance(emotion='pleading', vocal_effort='soft',
            delivery_note='Soft, vulnerable, pleading to protect the boy; original voice, no actor imitation.')
        events['e05'].vocal_performance = VocalPerformance(emotion='furious', vocal_effort='projected',
            delivery_note='Projected and forceful, resolute with conviction; original voice, no actor imitation.')
        if not redo_dialogue:
            # Reused audio must retain the direction that produced it, not the
            # proposed direction for an optional new generation.
            prior_script = SceneScreenplay.model_validate_json((previous / 'directed_screenplay.json').read_text())
            prior_events = {event.id: event for event in prior_script.events}
            for key in ('e04', 'e05'):
                if prior_events[key].text != events[key].text or prior_events[key].speaker != events[key].speaker:
                    raise ValueError(f'{key}: prior screenplay does not match selected dialogue')
                events[key].vocal_performance = prior_events[key].vocal_performance
        status['actual_v4_inputs'] = {key: performance_text(events[key], 'eleven_v4') for key in ('e04', 'e05')}
        for key in ('e04', 'e05'):
            if not status['actual_v4_inputs'][key].endswith(events[key].text):
                raise ValueError(f'{key}: generated input changed original line text')
        save(output / 'directed_screenplay.json', script.model_dump())
        base = {key: assets / (key + '.mp3') for key in ('e03', 'block', 'e08', 'e06', 'e07', 'music', 'ambience')}
        baseline_asr = json.loads((previous / 'baseline_dialogue_refreshed_asr.json').read_text())
        if baseline_asr.get('audio_sha256') != sha(base['block']):
            raise ValueError('Baseline dialogue ASR is not bound to the original audio')
        base_anchor = words_anchor(baseline_asr, duration(base['block']))
        reaction_candidates = list((output / 'prior_performances').glob('e08_*_attempt1.mp3'))
        if len(reaction_candidates) != 1:
            raise ValueError('Expected exactly one previously regenerated e08 stem')
        reaction = reaction_candidates[0]
        reaction_meta = json.loads(reaction.with_suffix('.json').read_text())
        reaction_asr = json.loads(reaction.with_suffix('.asr.json').read_text())
        if reaction_meta.get('voice_id') != registry.entries['narrator'].voice_id or reaction_asr.get('audio_sha256') != sha(reaction):
            raise ValueError('Prior regenerated e08 voice or ASR evidence does not match')
        status['reaction_source'] = str(reaction.relative_to(output))
        shutil.copy2(reaction, assets / 'selected_reaction.mp3')
        prior_dialogue = list((output / 'prior_performances').glob('e04__e05_*_attempt1.mp3'))
        if len(prior_dialogue) != 1:
            raise ValueError('Expected exactly one prior contextual dialogue stem')
        log = UsageLog(output / 'provider_usage.jsonl')
        access = probe_access(registry) if redo_dialogue else {}
        status['access_checks'] = access
        if redo_dialogue:
            stage = 'dialogue provider preflight'
            if not access or any(value != 200 for value in access.values()):
                raise RuntimeError('Provider preflight failed; no dialogue generated')
            provider = ElevenLabs(os.environ['ELEVENLABS_API_KEY'], registry.entries['narrator'].voice_id, 'eleven_v4', 'music_v1')
            provider.set_usage_log(log)
            try:
                stage = 'one contextual dialogue generation and review'
                status['dialogue_generation_calls_attempted'] = 1
                block, review, alignment, issues = _perform([events['e04'], events['e05']], output, provider, registry, 'tower', log, max_attempts=1)
            finally:
                provider.http.close()
        else:
            block = prior_dialogue[0]
            inputs = [{'text': status['actual_v4_inputs'][key], 'voice_id': registry.entries['tower:' + events[key].speaker].voice_id} for key in ('e04', 'e05')]
            digest = hashlib.sha256(json.dumps({'inputs': inputs, 'narration': False, 'model': 'eleven_v4'}, sort_keys=True).encode()).hexdigest()[:16]
            if block.name != f'e04__e05_{digest}_attempt1.mp3':
                raise ValueError('Prior screenplay and cast do not match the selected dialogue cache key')
            review = json.loads(block.with_suffix('.review.json').read_text())
            alignment, issues = align_block([events['e04'], events['e05']], json.loads(block.with_suffix('.json').read_text()).get('voice_segments'), duration(block))
            for item in alignment:
                if item['voice_ids'] != [registry.entries['tower:' + item['speaker']].voice_id]:
                    issues.append(item['event_id'] + ': speaker metadata mismatch')
        status['dialogue_source'] = str(block.relative_to(output))
        status['dialogue_review'] = review
        status['dialogue_alignment'] = alignment
        status['dialogue_alignment_issues'] = issues
        block_asr = json.loads(block.with_suffix('.asr.json').read_text())
        if block_asr.get('audio_sha256') != sha(block):
            raise ValueError('Selected dialogue ASR does not match audio')
        anchor = words_anchor(block_asr, duration(block))
        shutil.copy2(block, assets / 'selected_dialogue.mp3')
        variant = dict(base, block=assets / 'selected_dialogue.mp3', e08=assets / 'selected_reaction.mp3')
        status['speech_hashes'] = {name: sha(path) for name, path in {
            'original_e03': base['e03'], 'original_dialogue': base['block'], 'original_e08': base['e08'],
            'selected_dialogue': variant['block'], 'reused_regenerated_e08': variant['e08']}.items()}
        variants = [('mix_only', base, base_anchor), ('performance_and_mix', variant, anchor)]
        intro = duration(base['e03'])
        ends = [intro + a['end'] - .10 + duration(p['e06']) + duration(p['e07']) for _, p, a in variants]
        e08_start = max(ends)
        common_end = e08_start + max(duration(p['e08']) for _, p, _ in variants)
        cue = json.loads((previous / 'baseline_cue_sheet.json').read_text())
        baseline_cue = {'intro_end': cue['events'][3]['start_seconds'], 'snape_start_asr': intro + base_anchor['start'],
                        'spell_end_asr': intro + base_anchor['end'], 'e08_start': cue['events'][7]['start_seconds'],
                        'background_end': cue['events'][8]['start_seconds']}
        stage = 'baseline measurement'
        results['baseline_unchanged'] = {'measurement': measurements(output / 'baseline_unchanged.mp3', baseline_cue)}
        expected = ' '.join(events[e].text for e in ('e03', 'e04', 'e05', 'e08'))
        mixes = []
        status['master_review_summary'] = {}
        for name, paths, a in variants:
            stage = name + ' rendering and measurement'
            paths['e08_start'] = e08_start
            timeline, mix, cues = build_timeline(paths, a, common_end)
            mixes.append(mix.model_dump())
            save(output / (name + '_timeline.json'), timeline.model_dump())
            save(output / (name + '_mix.json'), mix.model_dump())
            save(output / (name + '_cues.json'), cues)
            master = output / (name + '.mp3')
            render(timeline, assets, master, expressive_mix=mix)
            voice, background = output / (name + '_voice_premaster.wav'), output / (name + '_background_premaster.wav')
            premaster_bus(timeline, mix, assets, voice, True)
            premaster_bus(timeline, mix, assets, background, False)
            qa = quality(master, COVER, timeline.duration_seconds, allowed_silence=[(common_end, common_end + 4)])
            qa['human_listening_completed'] = False
            if access.get('openai_models') == 200:
                try:
                    qa['master_asr'] = master_review(master, expected, log)
                    status['master_review_summary'][name] = {'uncertain': qa['master_asr']['uncertain'], 'differences': qa['master_asr']['differences'], 'secondary_asr': qa['master_asr'].get('secondary_asr')}
                except Exception as exc:
                    code = exc.response.status_code if hasattr(exc, 'response') and exc.response is not None else None
                    status['blockers'].append({'stage': name + ' master ASR', 'error_type': type(exc).__name__, 'http_status': code})
            else:
                status['blockers'].append({'stage': name + ' master ASR', 'error_type': 'not requested or unavailable'})
            save(output / (name + '_qa.json'), qa)
            results[name] = {'cues': cues, 'measurement': measurements(master, cues, voice, background), 'qa': name + '_qa.json'}
        status['mix_settings_identical'] = mixes[0] == mixes[1]
        if not status['mix_settings_identical']:
            raise ValueError('Comparison mix settings differ')
        status['completion'] = 'rendered and measured; human review pending'
    except Exception as exc:
        failed = True
        code = exc.response.status_code if hasattr(exc, 'response') and exc.response is not None else None
        status['blockers'].append({'stage': stage, 'error_type': type(exc).__name__, 'http_status': code, 'detail': str(exc) if code is None else 'Provider request failed; response omitted.'})
        status['completion'] = 'incomplete; no automatic retry'
    finally:
        if baseline.is_file() and (output / 'baseline_unchanged.mp3').is_file():
            status['baseline_sha256_after'] = sha(baseline)
            status['baseline_copy_sha256'] = sha(output / 'baseline_unchanged.mp3')
            status['baseline_unchanged_verified'] = status.get('baseline_sha256') == status['baseline_sha256_after'] == status['baseline_copy_sha256']
        save(output / 'results.json', {'status': status, 'results': results})
        technical_report(output, status, results)
        print(json.dumps({'output': str(output), 'completion': status['completion'], 'blockers': status['blockers'], 'baseline_unchanged_verified': status.get('baseline_unchanged_verified')}, indent=2))
    return 1 if failed else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--recover', type=Path, help='Recover completed performances without another generation')
    parser.add_argument('--previous', type=Path, default=PREVIOUS, help='Prior experiment with retained stems and evidence')
    parser.add_argument('--redo-dialogue', action='store_true', help='Request exactly one new contextual dialogue; no narration generation')
    args = parser.parse_args()
    if args.recover:
        recover(args.recover)
    else:
        raise SystemExit(revised_experiment(args.previous, args.redo_dialogue))