"""Parser and normalizer tests: synthetic fixtures + Episode 1 golden checks."""

from pathlib import Path

import pytest

from promo_finder.models import EventType
from promo_finder.normalize import build_alias_map, render_transcript
from promo_finder.parse import (
    fmt_time,
    load_corpus,
    parse_file,
    parse_text,
    split_label,
    to_seconds,
)

DATA = Path("data/episodes")
needs_data = pytest.mark.skipif(not DATA.exists(), reason="confidential episodes not present")

SAMPLE = '''EPISODE NUMBER: Episode 7
EPISODE LOGLINE: A test logline.
CONTINUITY NOTES: Test notes.

--- SCRIPT START ---

SCENE 01
Scene heading: INT. HALL – DAY
Scene start: 00:00.00
Scene end: 00:30.00

ACTIONS AND DIALOGUE:

**CAMERA:**
Start: (00:00.00) | End: (00:04.00)
Wide shot of a hall.

**LADY ANNA (O.S.) (Cold, Firm):**
Start: (00:01.00) | End: (00:03.50)
"You should leave."

**ANNA (Angry):**
Start: (00:05.00) | End: (00:04.00)
"Never."

**ACTION:**
Start: (00:06.00) | End: (00:08.00)
She slaps him
across the face.

**SOUND FX:**
"no timing line here"

--- SCRIPT END ---
'''


def test_time_helpers():
    assert to_seconds("01:05.60") == 65.6
    assert to_seconds("1:02:03.5") == 3723.5
    assert fmt_time(65.6) == "01:05.60"


def test_split_label():
    assert split_label("MATRIARCH (O.S.) (Firm)") == ("MATRIARCH", ["O.S."], "Firm")
    assert split_label("CAMERA:") == ("CAMERA", [], None)
    assert split_label("LADY JULIANA (Confused, Breathless):") == (
        "LADY JULIANA", [], "Confused, Breathless")


def test_synthetic_episode():
    ep = parse_text(SAMPLE, "x.txt")
    assert ep.number == 7 and ep.logline == "A test logline."
    types = [e.type for e in ep.events]
    assert types == [EventType.CAMERA, EventType.DIALOGUE, EventType.DIALOGUE, EventType.ACTION]
    line = ep.events[1]
    assert line.speaker == "LADY ANNA" and line.modifiers == ["O.S."]
    assert line.emotion == "Cold, Firm" and line.text == "You should leave."
    assert ep.events[3].text == "She slaps him across the face."     # multi-line body joined
    assert ep.events[2].start == 4.0 and ep.events[2].end == 5.0       # end<start swapped
    assert any("end < start" in w for w in ep.warnings)
    assert any("no timing" in w for w in ep.warnings)                  # bad block dropped
    assert [e.id for e in ep.events][0] == "E07-S01-001"


def test_alias_rule_only_merges_existing_names():
    ep = parse_text(SAMPLE, "x.txt")
    alias = build_alias_map([ep], {})
    assert alias["LADY ANNA"] == "ANNA"
    alias2 = build_alias_map([ep], {"ANNA": "HANNAH"})
    assert alias2["LADY ANNA"] == "HANNAH"      # chains resolve


@needs_data
def test_episode_1_golden():
    ep = parse_file(next(DATA.glob("episode-001-*.txt")))
    assert ep.number == 1 and len(ep.scenes) == 1
    assert ep.duration == pytest.approx(138.0)
    assert not ep.warnings
    lines = [e for e in ep.events if e.type == EventType.DIALOGUE]
    assert lines[0].speaker == "MATRIARCH" and lines[0].text == "You should turn around, Juliana."
    assert lines[0].start == pytest.approx(11.3)
    gold = [e for e in lines if e.speaker == "LADY IN GOLD GOWN"]
    assert gold[0].text == "Because he is marrying me."
    assert "[E01-S01-" in render_transcript(ep)


@needs_data
def test_whole_corpus_parses():
    eps = load_corpus(DATA)
    assert len(eps) == 50
    assert [e.number for e in eps] == list(range(1, 51))
    for ep in eps:
        assert ep.events, f"episode {ep.number} has no events"
        ids = [e.id for e in ep.events]
        assert len(ids) == len(set(ids)), f"duplicate ids in episode {ep.number}"
        for e in ep.events:
            assert e.end >= e.start
    assert sum(len(ep.events) for ep in eps) == 3727
