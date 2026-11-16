from typing import Literal
from pydantic import BaseModel, Field, model_validator

Style = Literal['cinematic_documentary', 'calm_explainer']

class Brief(BaseModel):
    prompt: str = Field(min_length=10, max_length=2000)
    duration_minutes: float = Field(gt=0, allow_inf_nan=False)
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

class GainPoint(BaseModel):
    time_seconds: float = Field(ge=0)
    gain_db: float = Field(ge=-60, le=30)

class TimelineItem(BaseModel):
    path: str
    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    gain_db: float = 0
    kind: Literal['narration', 'music', 'sfx']
    gain_envelope: list[GainPoint] = []
    fade_in_seconds: float | None = Field(default=None, ge=0)
    fade_out_seconds: float | None = Field(default=None, ge=0)

class Timeline(BaseModel):
    items: list[TimelineItem]
    duration_seconds: float = Field(gt=0)

class SpatialMix(BaseModel):
    """Stereo placement and restrained early reflection for an individual item.

    Pan is -1 (left) to 1 (right); distance is a relative linear distance,
    with 1 as the reference. Reflection is a single, item-bounded echo.
    """
    pan: float = Field(default=0, ge=-1, le=1, allow_inf_nan=False)
    distance: float = Field(default=1, ge=1, le=10, allow_inf_nan=False)
    reflection: float = Field(default=0, ge=0, le=0.2, allow_inf_nan=False)
    reflection_delay_ms: int = Field(default=60, ge=20, le=100)

class ExpressiveItemMix(BaseModel):
    """Additional settings relative to the item's authored gain and envelope."""
    gain_offset_db: float = Field(default=0, ge=-30, le=12, allow_inf_nan=False)
    ambience: bool = False
    spatial: SpatialMix | None = None

class ExpressiveMix(BaseModel):
    """Opt-in render settings, keyed by zero-based index in Timeline.items.

    Mark SFX beds as ambience explicitly; unmarked SFX remain foreground.
    Ducking uses whole narration item intervals, not a loudness threshold.
    """
    items: dict[int, ExpressiveItemMix] = Field(default_factory=dict)
    duck_gain_db: float = Field(default=-9, ge=-30, le=0, allow_inf_nan=False)
    attack_seconds: float = Field(default=0.15, ge=0.01, le=5, allow_inf_nan=False)
    release_seconds: float = Field(default=0.3, ge=0.01, le=5, allow_inf_nan=False)

class Manifest(BaseModel):
    attempt_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    title: str
    description: str
    duration_seconds: int = Field(gt=0)
    audio_object_key: str
    cover_object_key: str
    mime_type: Literal['audio/mpeg'] = 'audio/mpeg'

class CharacterCasting(BaseModel):
    name: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)
    role: Literal['narrator', 'character']
    description: str = ''

class DialogueTurn(BaseModel):
    speaker: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=2000)
    delivery: str = ''
    emotion: str = ''
    pause_after_seconds: float = Field(default=0, ge=0, le=10)

class SceneAction(BaseModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]+$')
    description: str
    sound_prompt: str
    anchor: Literal['scene_start', 'narrator_end', 'dialogue_start', 'dialogue_end', 'dialogue_turn_start']
    offset_seconds: float = 0
    turn_index: int | None = Field(default=None, ge=0)
    duration_seconds: float = Field(gt=0, le=30)

class NarrativeDirectionPlan(BaseModel):
    title: str
    context: str
    fictionalized: bool
    cast: list[CharacterCasting] = Field(min_length=2)
    narrator_text: str = Field(min_length=1)
    dialogue: list[DialogueTurn] = Field(min_length=1)
    actions: list[SceneAction] = []
    music_prompt: str = Field(min_length=1)
    ambience_prompt: str = Field(min_length=1)
    pause_before_dialogue_seconds: float = Field(default=1, ge=0, le=10)
    ending_silence_seconds: float = Field(default=1, ge=0, le=10)

    @model_validator(mode='after')
    def valid_cast(self):
        names = [c.name for c in self.cast]
        if len(names) != len(set(names)):
            raise ValueError('Cast names must be unique')
        if sum(c.role == 'narrator' for c in self.cast) != 1:
            raise ValueError('Exactly one narrator is required')
        characters = {c.name for c in self.cast if c.role == 'character'}
        if any(turn.speaker not in characters for turn in self.dialogue):
            raise ValueError('Every dialogue turn must refer to a cast character')
        if len({c.voice_id for c in self.cast if c.role == 'character'}) > 10:
            raise ValueError('Dialogue supports at most 10 distinct voices')
        if sum(len(t.text) + len(t.delivery) + 3 for t in self.dialogue) > 2000:
            raise ValueError('Keep a dialogue request within 2000 characters')
        return self
