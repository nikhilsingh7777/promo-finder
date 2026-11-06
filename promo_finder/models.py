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
