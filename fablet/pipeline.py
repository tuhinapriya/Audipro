import hashlib
import json
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from .artifacts import atomic_write, cached_model
from .audio import duration, quality, render
from .models import Brief, Research, Outline, Script, Direction, Timeline, TimelineItem
from .providers import EditorialProvider, ElevenLabs

def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if not (key.startswith('utm_') or key == 'trk')]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), ''))


class Pipeline:
    def __init__(self, editor: EditorialProvider, audio: ElevenLabs, image_model: str):
        self.editor, self.audio, self.image_model = editor, audio, image_model

    def run(self, brief: Brief, root: Path, progress: Callable[[str, int, str], None] = lambda *args: None):
        root.mkdir(parents=True, exist_ok=True)
        from .usage import UsageLog
        for provider in (self.editor, self.audio):
            if hasattr(provider, 'set_usage_log'):
                provider.set_usage_log(UsageLog(root / 'provider_usage.jsonl'))
        atomic_write(root / 'brief.json', brief.model_dump_json(indent=2).encode())
        progress('researching', 10, 'Researching sources')
        research_raw = root / 'research_response.json'
        brief_hash = hashlib.sha256(brief.model_dump_json().encode()).hexdigest()
        if not research_raw.exists() or not (root / 'research_response.sha256').exists() or (root / 'research_response.sha256').read_text() != brief_hash:
            response = self.editor.research(f'Research this audiobook topic using reliable sources. Cite URLs, distinguish uncertainty, do not invent facts: {brief.prompt}')
            atomic_write(research_raw, response.encode())
            atomic_write(root / 'research_response.sha256', brief_hash.encode())
        raw = research_raw.read_text()
        response_data = json.loads(raw)
        retrieved_urls = {source.get('url') for item in response_data.get('output', []) if item.get('type') == 'web_search_call' for source in ((item.get('action') or {}).get('sources') or []) if isinstance(source, dict)}
        cited_urls = {annotation.get('url') for item in response_data.get('output', []) if item.get('type') == 'message' for content in item.get('content', []) for annotation in (content.get('annotations') or []) if annotation.get('type') == 'url_citation'}
        source_urls = {canonical_url(url) for url in retrieved_urls | cited_urls if url}
        if not source_urls:
            raise ValueError('Research response has no web-search sources or citations')
        source_prompt = 'Extract source references with stable IDs, findings and caveats from this web research response. Every source URL must be copied exactly from the allowed URL list; omit any source not in that list.\nAllowed URLs:\n' + '\n'.join(sorted(source_urls)) + '\nResponse:\n' + raw
        research = cached_model(root/'research.json', Research, source_prompt, lambda: self.editor.structured(source_prompt, Research))
        if not source_urls or any(canonical_url(source.url) not in source_urls for source in research.sources):
            raise ValueError('Research sources must be present in web-search results or citations')
        progress('writing', 25, 'Planning and revising the story')
        context = f'Brief: {brief.model_dump_json()}\nResearch: {research.model_dump_json()}'
        outline = cached_model(root/'outline.json', Outline, context, lambda: self.editor.structured('Create a compelling factual audio documentary outline. Link factual scenes to source IDs.\n'+context, Outline))
        context += '\nOutline: '+outline.model_dump_json()
        target = round(brief.duration_minutes * 130)
        draft = cached_model(root/'script_draft.json', Script, context, lambda: self.editor.structured(f'Write roughly {target} spoken words in ordered short narration segments for this documentary. Cite source IDs per segment, avoid invented quotations and events, distinguish uncertainty and dramatic reconstruction.\n'+context, Script))
        script = cached_model(root/'script.json', Script, [context, draft.model_dump()], lambda: self.editor.structured('Revise for accurate sourced claims, listenability, transitions, pacing and no repetition. Preserve length and source IDs. Remove unsupported claims.\n'+context+'\nDraft: '+draft.model_dump_json(), Script))
        source_ids = {s.id for s in research.sources}
        scene_ids = {s.id for s in outline.scenes}
        if any(set(seg.source_ids) - source_ids or seg.scene_id not in scene_ids for seg in script.segments):
            raise ValueError('Script references unknown source or scene IDs')
        direction = cached_model(root/'direction.json', Direction, script.model_dump(), lambda: self.editor.structured('Create restrained audio direction for this script: one reusable instrumental music cue and select music_segment_ids by narrative significance; leave some segments unscored for contrast and natural silence. Add one or two selective sound effects tied to segment IDs, and a cover prompt.\n'+script.model_dump_json(), Direction))
        segment_ids = {s.id for s in script.segments}
        if any(c.segment_id not in segment_ids for c in direction.effects) or any(i not in segment_ids for i in direction.music_segment_ids):
            raise ValueError('Audio direction references unknown segment')
        progress('narrating', 45, 'Recording narration')
        items = []
        positions = {}
        # Allow an opening effect and a beat of silence before the first word.
        position = 1.7 if any(c.segment_id == script.segments[0].id for c in direction.effects) else 0.0
        for i, seg in enumerate(script.segments):
            path = root/'narration'/f'{seg.id}.mp3'
            previous = script.segments[i-1].text if i else ''
            following = script.segments[i+1].text if i+1 < len(script.segments) else ''
            self._cached_audio(path, [seg.model_dump(), previous, following, self.audio.voice, self.audio.tts_model], lambda: self.audio.narrate(seg.text, previous, following, path))
            length = duration(path)
            positions[seg.id] = position
            items.append(TimelineItem(path=str(path.relative_to(root)), start_seconds=position, duration_seconds=length, kind='narration'))
            position += length + seg.pause_after_seconds
        progress('scoring', 65, 'Producing music and sound effects')
        music = root/'music'/'theme.mp3'
        self._cached_audio(music, [{'prompt': direction.music.prompt, 'duration_seconds': direction.music.duration_seconds}, self.audio.music_model], lambda: self.audio.music(direction.music.prompt, direction.music.duration_seconds, music))
        music_duration = duration(music)
        # Place the theme only beneath editorially selected segments, with short
        # lead-in/out gaps. Repetitions overlap to crossfade; no continuous bed.
        chosen = set(direction.music_segment_ids)
        for item, segment in zip(items.copy(), script.segments):
            if segment.id not in chosen:
                continue
            start = item.start_seconds + min(.5, item.duration_seconds / 8)
            end = item.start_seconds + item.duration_seconds - min(.5, item.duration_seconds / 8)
            cursor = start
            while cursor < end:
                length = min(music_duration, end - cursor)
                if length <= 0:
                    break
                items.append(TimelineItem(path=str(music.relative_to(root)), start_seconds=cursor, duration_seconds=length, gain_db=direction.music.gain_db, kind='music'))
                cursor += max(.1, length - min(.5, length / 4)) if cursor + length < end else length
        for cue in direction.effects:
            path = root/'sfx'/f'{cue.id}.mp3'
            self._cached_audio(path, [{'prompt': cue.prompt, 'duration_seconds': cue.duration_seconds}, getattr(self.audio, 'sfx_model', None)], lambda: self.audio.effect(cue.prompt, cue.duration_seconds, path))
            target_index = next(i for i, segment in enumerate(script.segments) if segment.id == cue.segment_id)
            target_start = positions[cue.segment_id]
            gap_start = (items[target_index - 1].start_seconds + items[target_index - 1].duration_seconds) if target_index else 0.0
            available = max(0.0, target_start - gap_start)
            length = min(duration(path), available)
            if length > .05:
                items.append(TimelineItem(path=str(path.relative_to(root)), start_seconds=gap_start, duration_seconds=length, gain_db=cue.gain_db, kind='sfx'))
        timeline = Timeline(items=items, duration_seconds=position)
        atomic_write(root/'timeline.json', timeline.model_dump_json(indent=2).encode())
        progress('mixing', 80, 'Mixing audio')
        render(timeline, root, root/'master.mp3')
        cover = root/'cover.webp'
        self._cached_audio(cover, [direction.cover_prompt, self.image_model], lambda: self.editor.cover(direction.cover_prompt, self.image_model, cover))
        progress('quality_check', 92, 'Checking production')
        report = quality(root/'master.mp3', cover, position)
        report['script_word_count'] = sum(len(x.text.split()) for x in script.segments)
        report['requested_seconds'] = brief.duration_minutes * 60
        report['duration_review_required'] = not (0.8 * report['requested_seconds'] <= report['duration_seconds'] <= 1.2 * report['requested_seconds'])
        atomic_write(root/'qa_report.json', json.dumps(report, indent=2).encode())
        manifest = {'title': outline.title, 'description': outline.description, 'duration_seconds': round(duration(root/'master.mp3')), 'mime_type': 'audio/mpeg', 'audio_file': 'master.mp3', 'cover_file': 'cover.webp'}
        atomic_write(root/'manifest.json', json.dumps(manifest, indent=2).encode())
        return manifest

    @staticmethod
    def _cached_audio(path: Path, inputs: object, generate: Callable):
        digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        meta = path.with_suffix(path.suffix+'.sha256')
        if path.exists() and path.stat().st_size and meta.exists() and meta.read_text() == digest:
            return
        generate()
        atomic_write(meta, digest.encode())
