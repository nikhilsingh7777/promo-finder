"""Screenplay parser: plain code, no LLM.

Strict about structure, tolerant about data: anything odd becomes a warning
on the Episode instead of an exception, so one bad file never stops a run.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import Episode, Event, EventType, Scene

_TIME = r"(\d{1,2}(?::\d{2}){1,2}(?:\.\d+)?)"
RE_HEADER = re.compile(r"^(EPISODE NUMBER|EPISODE LOGLINE|CONTINUITY NOTES)\s*:\s*(.*)$", re.I)
RE_SCENE = re.compile(r"^SCENE\s+(\d+)\s*$", re.I)
RE_SCENE_FIELD = re.compile(rf"^Scene (start|end)\s*:\s*{_TIME}", re.I)
RE_BLOCK = re.compile(r"^\*\*(.+?)\*\*\s*$")
RE_TIMING = re.compile(rf"^Start:\s*\(\s*{_TIME}\s*\)\s*\|\s*End:\s*\(\s*{_TIME}\s*\)\s*$", re.I)
RE_SKIP = re.compile(r"^(--- SCRIPT (START|END) ---|ACTIONS AND DIALOGUE:?)$", re.I)

TECH_TYPES = {
    "CAMERA": EventType.CAMERA,
    "ACTION": EventType.ACTION,
    "SOUND FX": EventType.SOUND,
    "SOUND": EventType.SOUND,
    "SFX": EventType.SOUND,
}
# Parenthetical tags that describe delivery position, not emotion.
POSITION_TAGS = {"O.S.", "V.O.", "O.C.", "CONT'D", "CONT’D", "OS", "VO"}


def to_seconds(t: str) -> float:
    """'01:05.60' -> 65.6 ; '1:02:03.5' -> 3723.5."""
    total = 0.0
    for part in t.split(":"):
        total = total * 60 + float(part)
    return round(total, 3)


def fmt_time(sec: float) -> str:
    """65.6 -> '01:05.60' (same style as the screenplays)."""
    m, s = divmod(round(sec, 2), 60)
    return f"{int(m):02d}:{s:05.2f}"


def split_label(label: str) -> tuple[str, list[str], str | None]:
    """'MATRIARCH (O.S.) (Firm)' -> ('MATRIARCH', ['O.S.'], 'Firm')."""
    label = label.strip().rstrip(":").strip()
    tags = [t.strip() for t in re.findall(r"\(([^)]*)\)", label)]
    name = re.sub(r"\([^)]*\)", "", label).strip().rstrip(":").strip()
    modifiers = [t for t in tags if t.upper() in POSITION_TAGS]
    emotions = [t for t in tags if t.upper() not in POSITION_TAGS]
    return name, modifiers, (", ".join(emotions) or None)


def _clean_text(lines: list[str]) -> str:
    text = " ".join(x.strip() for x in lines if x.strip())
    if len(text) >= 2 and text[0] in "\"“" and text[-1] in "\"”":
        text = text[1:-1].strip()
    return text


def parse_text(text: str, source_file: str = "<string>") -> Episode:
    lines = text.splitlines()
    headers: dict[str, str] = {}
    scenes: list[Scene] = []
    warnings: list[str] = []
    raw_events: list[dict] = []     # collected first, IDs assigned after sorting
    current: dict | None = None     # block being read

    def close_block() -> None:
        nonlocal current
        if current is None:
            return
        if current.get("start") is None:
            warnings.append(
                f"L{current['line']}: block '{current['label']}' has no timing; dropped")
        else:
            current["text"] = _clean_text(current["body"])
            raw_events.append(current)
        current = None

    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or RE_SKIP.match(line):
            continue
        if m := RE_HEADER.match(line):
            headers[m.group(1).upper()] = m.group(2).strip()
            continue
        if m := RE_SCENE.match(line):
            close_block()
            scenes.append(Scene(index=int(m.group(1))))
            continue
        if line.lower().startswith("scene heading:"):
            if scenes:
                scenes[-1].heading = line.split(":", 1)[1].strip()
            continue
        if m := RE_SCENE_FIELD.match(line):
            if scenes:
                setattr(scenes[-1], m.group(1).lower(), to_seconds(m.group(2)))
            continue
        if m := RE_BLOCK.match(line):
            close_block()
            if not scenes:
                warnings.append(f"L{i}: block before any SCENE; created scene 1")
                scenes.append(Scene(index=1))
            current = {"label": m.group(1), "line": i, "scene": scenes[-1].index,
                       "start": None, "end": None, "body": []}
            continue
        if m := RE_TIMING.match(line):
            if current is None:
                warnings.append(f"L{i}: timing line with no block; ignored")
            elif current["start"] is not None:
                warnings.append(f"L{i}: second timing line in one block; ignored")
            else:
                current["start"] = to_seconds(m.group(1))
                current["end"] = to_seconds(m.group(2))
            continue
        if current is not None:
            current["body"].append(line)
        else:
            warnings.append(f"L{i}: text outside any block: {line[:60]!r}")
    close_block()

    number = _episode_number(headers.get("EPISODE NUMBER", ""), source_file)
    if number is None:
        warnings.append("no episode number found; using 0")
        number = 0
    for key in ("EPISODE LOGLINE", "CONTINUITY NOTES"):
        if not headers.get(key):
            warnings.append(f"missing header {key}")

    scene_map = {s.index: s for s in scenes}
    for ev in raw_events:
        name, mods, emotion = split_label(ev["label"])
        etype = TECH_TYPES.get(name.upper())
        is_dialogue = etype is None
        start, end = ev["start"], ev["end"]
        if end < start:
            warnings.append(
                f"L{ev['line']}: end < start ({fmt_time(start)} > {fmt_time(end)}); swapped")
            start, end = end, start
        sc = scene_map[ev["scene"]]
        if sc.start is not None and sc.end is not None and (
            start < sc.start - 0.01 or end > sc.end + 0.01
        ):
            warnings.append(
                f"L{ev['line']}: event {fmt_time(start)}-{fmt_time(end)} outside scene "
                f"{sc.index} ({fmt_time(sc.start)}-{fmt_time(sc.end)}); kept"
            )
        sc.events.append(Event(
            id="", ep=number, scene=sc.index,
            type=EventType.DIALOGUE if is_dialogue else etype,
            speaker=name if is_dialogue else None,
            modifiers=mods, emotion=emotion if is_dialogue else None,
            text=ev["text"], start=start, end=end, source_line=ev["line"],
        ))

    # Stable IDs: time order inside each scene, ties keep file order.
    for sc in scenes:
        sc.events.sort(key=lambda e: (e.start, e.source_line))
        for n, e in enumerate(sc.events, 1):
            e.id = f"E{number:02d}-S{sc.index:02d}-{n:03d}"
        if not sc.events:
            warnings.append(f"scene {sc.index} has no events")

    ends = [s.end for s in scenes if s.end is not None]
    ends += [e.end for s in scenes for e in s.events]
    return Episode(
        number=number, source_file=Path(source_file).name,
        logline=headers.get("EPISODE LOGLINE", ""),
        continuity=headers.get("CONTINUITY NOTES", ""),
        duration=max(ends) if ends else 0.0,
        scenes=scenes, warnings=warnings,
    )


def _episode_number(header: str, source_file: str) -> int | None:
    for s in (header, Path(source_file).name):
        if m := re.search(r"(?:episode[\s_-]*)(\d+)", s, re.I):
            return int(m.group(1))
    return None


def parse_file(path: str | Path) -> Episode:
    p = Path(path)
    return parse_text(p.read_text(encoding="utf-8", errors="replace"), str(p))


def load_corpus(folder: str | Path) -> list[Episode]:
    """Parse every .txt in a folder, sorted by episode number."""
    eps = [parse_file(p) for p in sorted(Path(folder).glob("*.txt"))]
    return sorted(eps, key=lambda e: e.number)
