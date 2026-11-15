from typing import Literal
from pydantic import BaseModel, Field, model_validator

Style = Literal['cinematic_documentary', 'calm_explainer']

class Brief(BaseModel):
    prompt: str = Field(min_length=10, max_length=2000)
    duration_minutes: float = Field(gt=0, le=15)
    style: Style = 'cinematic_documentary'

class Source(BaseModel):
    id: str
    title: str
    url: str
    summary: str

class Research(BaseModel):
    sources: list[Source] = Field(min_length=1)
    findings: list[str] = Field(min_length=1)
    caveats: list[str] = []

class Scene(BaseModel):
    id: str
    purpose: str
    source_ids: list[str]

class Outline(BaseModel):
    title: str
    description: str
    scenes: list[Scene] = Field(min_length=1)

class Segment(BaseModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]+$')
    scene_id: str
    text: str = Field(min_length=1, max_length=4000)
    source_ids: list[str]
    pronunciation: str = ''
    pause_after_seconds: float = Field(default=0.5, ge=0, le=5)

class Script(BaseModel):
    segments: list[Segment] = Field(min_length=1)
    editorial_notes: list[str]

    @model_validator(mode='after')
    def unique_ids(self):
        ids = [s.id for s in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError('segment IDs must be unique')
        return self

class MusicCue(BaseModel):
    prompt: str
    duration_seconds: int = Field(ge=3, le=300)
    gain_db: float = Field(default=-22, ge=-60, le=0)

class SfxCue(BaseModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]+$')
    segment_id: str
    prompt: str
    duration_seconds: float = Field(ge=0.5, le=22)
    gain_db: float = Field(default=-20, ge=-60, le=0)

class Direction(BaseModel):
    music: MusicCue
    music_segment_ids: list[str] = []
    effects: list[SfxCue] = []
    cover_prompt: str

class TimelineItem(BaseModel):
    path: str
    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    gain_db: float = 0
    kind: Literal['narration', 'music', 'sfx']

class Timeline(BaseModel):
    items: list[TimelineItem]
    duration_seconds: float = Field(gt=0)

class Manifest(BaseModel):
    attempt_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    title: str
    description: str
    duration_seconds: int = Field(gt=0)
    audio_object_key: str
    cover_object_key: str
    mime_type: Literal['audio/mpeg'] = 'audio/mpeg'
