"""Data models shared by every pipeline stage."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EventType(str, Enum):
    DIALOGUE = "DIALOGUE"
    ACTION = "ACTION"
    CAMERA = "CAMERA"
    SOUND = "SOUND"
    UNKNOWN = "UNKNOWN"


class Event(BaseModel):
    """One timed block of the screenplay (a shot, an action, a line, a sound)."""

    id: str                                  # e.g. E01-S01-014, stable within a run
    ep: int
    scene: int
    type: EventType
    speaker: str | None = None               # label as written, e.g. "LADY IN GOLD GOWN"
    speaker_canonical: str | None = None     # resolved character, e.g. "CLARISSA"
    modifiers: list[str] = Field(default_factory=list)  # O.S., V.O. ...
    emotion: str | None = None               # "Cold, Commanding"
    text: str = ""
    start: float                             # seconds from episode start
    end: float
    source_line: int                         # line number of the block header


class Scene(BaseModel):
    index: int
    heading: str = ""
    start: float | None = None
    end: float | None = None
    events: list[Event] = Field(default_factory=list)


class Episode(BaseModel):
    number: int
    source_file: str
    logline: str = ""
    continuity: str = ""
    duration: float = 0.0
    scenes: list[Scene] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def events(self) -> list[Event]:
        """All events of the episode in time order."""
        return [e for s in self.scenes for e in s.events]

    def event_by_id(self) -> dict[str, Event]:
        return {e.id: e for e in self.events}


# ---------- what the LLM returns (it never writes timestamps) ----------

class ProposedSegment(BaseModel):
    start_event_id: str
    end_event_id: str


class ProposedCandidate(BaseModel):
    segments: list[ProposedSegment]
    hook_event_id: str
    hook_description: str = ""
    cliffhanger_event_id: str
    cliffhanger_description: str = ""
    unresolved_question: str = ""
    why_it_works: str = ""
    confidence: float = 0.5


class ProposalResponse(BaseModel):
    candidates: list[ProposedCandidate] = Field(default_factory=list)


# ---------- what code computes ----------

class Segment(BaseModel):
    ep: int
    start_event_id: str
    end_event_id: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 2)


class Validation(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duration: float = 0.0
    edge: bool = False                       # valid but outside the comfortable target band
    ends_at_episode_end: bool = False


class Candidate(BaseModel):
    id: str
    type: str = "single"                     # single | multi | composed
    episodes: list[int]
    proposal: ProposedCandidate
    segments: list[Segment] = Field(default_factory=list)
    hook_text: str = ""
    cliffhanger_text: str = ""
    after_cut: list[str] = Field(default_factory=list)   # what happens right after the promo
    validation: Validation | None = None
    repair_attempts: int = 0
    proposer_model: str = ""
    history: list[dict] = Field(default_factory=list)    # earlier failed versions + errors
    scores: dict = Field(default_factory=dict)
    blind_test: dict = Field(default_factory=dict)
    composite: float | None = None
    rank: int | None = None


class JudgeScore(BaseModel):
    candidate_id: str
    hook_strength: int = 1
    cliffhanger_strength: int = 1
    standalone_clarity: int = 1
    emotional_intensity: int = 1
    shareability: int = 1
    spoiler_risk: int = 0
    answer_inside_clip: bool = False
    reason: str = ""


class JudgeResponse(BaseModel):
    scores: list[JudgeScore] = Field(default_factory=list)


class BlindResult(BaseModel):
    candidate_id: str
    main_people: str = ""
    conflict: str = ""
    confusions: list[str] = Field(default_factory=list)
    want_next: str = ""
    keep_watching: bool = False
    understood: bool = False


class BlindResponse(BaseModel):
    results: list[BlindResult] = Field(default_factory=list)


class EditorResponse(BaseModel):
    order: list[str] = Field(default_factory=list)
    notes: dict[str, str] = Field(default_factory=dict)
    near_duplicates: list[list[str]] = Field(default_factory=list)
