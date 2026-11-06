"""Character alias resolution and LLM-ready transcript rendering."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

from .models import Episode, Event, EventType
from .parse import fmt_time

HONORIFICS = ("LADY ", "LORD ", "SIR ")
TYPE_TAG = {EventType.CAMERA: "CAM", EventType.ACTION: "ACT", EventType.SOUND: "SFX",
            EventType.UNKNOWN: "UNK"}


def load_overrides(path: str | Path = "config/roster_overrides.yaml") -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {k.upper(): v.upper() for k, v in (data.get("aliases") or {}).items()}


def build_alias_map(episodes: list[Episode], overrides: dict[str, str] | None = None
                    ) -> dict[str, str]:
    """Map every speaker label to one canonical name.

    Rule 1 (automatic): 'LADY JULIANA' -> 'JULIANA' only when 'JULIANA' is itself a label,
    so 'LADY ASHCROFT' and 'LORD ASHCROFT' stay two different people.
    Rule 2 (manual): overrides from config/roster_overrides.yaml win.
    """
    labels = {e.speaker.upper() for ep in episodes for e in ep.events if e.speaker}
    alias: dict[str, str] = {}
    for lab in labels:
        target = lab
        for h in HONORIFICS:
            if lab.startswith(h) and lab[len(h):] in labels:
                target = lab[len(h):]
        alias[lab] = target
    for k, v in (overrides or {}).items():
        alias[k] = v
    # resolve chains (A -> B -> C)
    for k in list(alias):
        seen = {k}
        while alias[k] in alias and alias[alias[k]] != alias[k] and alias[k] not in seen:
            seen.add(alias[k])
            alias[k] = alias[alias[k]]
    return alias


def apply_aliases(episodes: list[Episode], alias: dict[str, str]) -> None:
    for ep in episodes:
        for e in ep.events:
            if e.speaker:
                e.speaker_canonical = alias.get(e.speaker.upper(), e.speaker.upper())


def roster_summary(episodes: list[Episode]) -> list[dict]:
    """Canonical characters with their labels, line counts and first episode."""
    lines: Counter[str] = Counter()
    labels: dict[str, set[str]] = {}
    first: dict[str, int] = {}
    for ep in episodes:
        for e in ep.events:
            if e.speaker_canonical:
                c = e.speaker_canonical
                lines[c] += 1
                labels.setdefault(c, set()).add(e.speaker.upper())
                first.setdefault(c, ep.number)
    return [{"name": c, "lines": n, "labels": sorted(labels[c]), "first_episode": first[c]}
            for c, n in lines.most_common()]


def render_event(e: Event) -> str:
    t = f"{fmt_time(e.start)}-{fmt_time(e.end)}"
    if e.type == EventType.DIALOGUE:
        who = e.speaker or "?"
        if e.speaker_canonical and e.speaker_canonical != (e.speaker or "").upper():
            who = f"{who} [= {e.speaker_canonical}]"
        extra = ", ".join(e.modifiers + ([e.emotion] if e.emotion else []))
        who = f"{who} ({extra})" if extra else who
        return f'[{e.id}] {t} SAY {who}: "{e.text}"'
    return f"[{e.id}] {t} {TYPE_TAG.get(e.type, e.type.value)}: {e.text}"


def render_transcript(ep: Episode, events: list[Event] | None = None,
                      include_camera: bool = True) -> str:
    """One line per event, with IDs and times, ready to paste into an LLM prompt."""
    evs = events if events is not None else ep.events
    out = []
    current_scene = None
    for e in sorted(evs, key=lambda x: (x.start, x.source_line)):
        if not include_camera and e.type == EventType.CAMERA:
            continue
        if events is None and e.scene != current_scene:
            sc = next(s for s in ep.scenes if s.index == e.scene)
            out.append(f"## SCENE {sc.index}: {sc.heading}")
            current_scene = e.scene
        out.append(render_event(e))
    return "\n".join(out)
