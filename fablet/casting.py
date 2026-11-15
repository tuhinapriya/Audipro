"""Persistent casting decisions. Metadata suggestions never overwrite a lock."""
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field
from .artifacts import atomic_write

class CastEntry(BaseModel):
    character_id: str
    voice_id: str = Field(min_length=1)
    characteristics: str = ''
    status: Literal['locked', 'provisional'] = 'provisional'
    selection: Literal['user_approved', 'automatically_selected']
    audition_reference: str = ''

class CastRegistry(BaseModel):
    entries: dict[str, CastEntry]

    def choose(self, key: str, proposed: CastEntry, *, explicit_change: bool = False):
        existing = self.entries.get(key)
        if existing and existing.status == 'locked' and existing.voice_id != proposed.voice_id and not explicit_change:
            raise ValueError(f'Locked voice cannot be changed without explicit authorization: {key}')
        self.entries[key] = proposed

    def save(self, path: Path):
        atomic_write(path, self.model_dump_json(indent=2).encode())

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate_json(path.read_text())

    def assert_available(self, available_voice_ids: set[str]):
        missing = [key for key, entry in self.entries.items() if entry.voice_id not in available_voice_ids]
        if missing:
            raise ValueError('Selected voices unavailable; no substitutions made: '+', '.join(missing))
