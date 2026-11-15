import hashlib
import json
from pathlib import Path
from typing import Callable
from .artifacts import atomic_write, cached_model
from .audio import duration, quality, render
from .models import Brief, Research, Outline, Script, Direction, Timeline, TimelineItem
from .providers import EditorialProvider, ElevenLabs

class Pipeline:
    def __init__(self, editor: EditorialProvider, audio: ElevenLabs, image_model: str):
        self.editor, self.audio, self.image_model = editor, audio, image_model

    def run(self, brief: Brief, root: Path, progress: Callable[[str, int, str], None] = lambda *args: None):
        root.mkdir(parents=True, exist_ok=True)
        atomic_write(root / 'brief.json', brief.model_dump_json(indent=2).encode())
        progress('researching', 10, 'Researching sources')
        research_raw = root / 'research_response.json'
        brief_hash = hashlib.sha256(brief.model_dump_json().encode()).hexdigest()
        if not research_raw.exists() or not (root / 'research_response.sha256').exists() or (root / 'research_response.sha256').read_text() != brief_hash:
            response = self.editor.research(f'Research this audiobook topic using reliable sources. Cite URLs, distinguish uncertainty, do not invent facts: {brief.prompt}')
            atomic_write(research_raw, response.encode())
            atomic_write(root / 'research_response.sha256', brief_hash.encode())
        raw = research_raw.read_text()
        research = cached_model(root/'research.json', Research, raw, lambda: self.editor.structured('Extract source references with stable IDs, source URLs, findings and caveats from this web research response. Do not invent sources.\n'+raw, Research))
        if any(source.url not in raw for source in research.sources):
            raise ValueError('Research contains a source URL absent from the provider response')
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
        direction = cached_model(root/'direction.json', Direction, script.model_dump(), lambda: self.editor.structured('Create restrained audio direction for this script: one reusable instrumental music cue, selective sound effects tied to segment IDs, and a cover prompt.\n'+script.model_dump_json(), Direction))
        if any(c.segment_id not in {s.id for s in script.segments} for c in direction.effects):
            raise ValueError('SFX references unknown segment')
        progress('narrating', 45, 'Recording narration')
        items = []
        positions = {}
        position = 0.0
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
        self._cached_audio(music, [direction.music.model_dump(), self.audio.music_model], lambda: self.audio.music(direction.music.prompt, direction.music.duration_seconds, music))
        music_duration = duration(music)
        # Reuse the motif; fade each repetition to avoid hard cuts.
        for start in range(0, int(position)+1, max(1, int(music_duration - 0.5))):
            length = min(music_duration, position-start)
            if length > 0:
                items.append(TimelineItem(path=str(music.relative_to(root)), start_seconds=start, duration_seconds=length, gain_db=direction.music.gain_db, kind='music'))
        for cue in direction.effects:
            path = root/'sfx'/f'{cue.id}.mp3'
            self._cached_audio(path, cue.model_dump(), lambda: self.audio.effect(cue.prompt, cue.duration_seconds, path))
            length = min(duration(path), position - positions[cue.segment_id])
            if length > 0:
                items.append(TimelineItem(path=str(path.relative_to(root)), start_seconds=positions[cue.segment_id], duration_seconds=length, gain_db=cue.gain_db, kind='sfx'))
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
