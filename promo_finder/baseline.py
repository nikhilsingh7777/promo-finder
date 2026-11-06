"""No-LLM baseline: keyword and punctuation heuristics.

Two jobs: (1) a demo that runs with no API key (--no-llm), (2) the bar the LLM pipeline
must clearly beat in evaluation. It uses the same validator as the LLM path.
"""

from __future__ import annotations

import re

from .models import Candidate, Episode, Event, EventType, ProposedCandidate, ProposedSegment
from .validate import validate

HOOK_WORDS = re.compile(r"\b(slap|strike|struck|grab|drag|scream|gasp|shock|reveal|kneel|"
                        r"punch|throw|shove|tear|guard|remove|never|marry|betray|liar|"
                        r"enough|how dare|knife|blood|arrest|chain)\w*", re.I)
HOT_EMOTION = re.compile(r"cold|cruel|furious|outrag|shock|horrif|scream|desperat|"
                         r"mock|gloat|disgust|venom|threat|deadly|betray|devastat", re.I)


def hook_score(e: Event) -> float:
    if e.type not in (EventType.DIALOGUE, EventType.ACTION, EventType.SOUND):
        return 0.0
    s = 0.0
    s += 1.0 * len(HOOK_WORDS.findall(e.text))
    s += 1.0 if e.emotion and HOT_EMOTION.search(e.emotion) else 0.0
    s += 0.8 if e.text.endswith("!") else 0.0
    s += 0.5 if e.type == EventType.DIALOGUE and len(e.text.split()) <= 8 else 0.0
    return s


def cliff_score(e: Event) -> float:
    if e.type not in (EventType.DIALOGUE, EventType.ACTION):
        return 0.0
    s = 0.0
    s += 1.2 if e.text.endswith("?") else 0.0
    s += 1.0 if e.text.endswith("...") or e.text.endswith("…") else 0.0
    s += 0.8 if e.text.endswith("!") else 0.0
    s += 0.5 * len(HOOK_WORDS.findall(e.text))
    s += 0.8 if e.emotion and HOT_EMOTION.search(e.emotion) else 0.0
    return s


def baseline_episode(ep: Episode, episodes: dict[int, Episode], cfg: dict,
                     n: int = 3) -> list[Candidate]:
    rules = cfg["promo_rules"]
    evs = [e for e in ep.events if e.type != EventType.CAMERA]
    options = []
    for i, h in enumerate(evs):
        hs = hook_score(h)
        if hs < 1.0:
            continue
        best = None
        for e in evs[i + 1:]:
            dur = e.end - h.start
            if dur < rules["target_min_s"]:
                continue
            if dur > rules["target_max_s"]:
                break
            cs = cliff_score(e)
            if best is None or cs > best[0]:
                best = (cs, e)
        if best:
            options.append((hs + best[0], h, best[1]))
    options.sort(key=lambda t: t[0], reverse=True)
    out: list[Candidate] = []
    for score, h, e in options:
        if any(h.start < c.segments[0].end and e.end > c.segments[0].start for c in out):
            continue  # overlaps an already chosen window
        prop = ProposedCandidate(
            segments=[ProposedSegment(start_event_id=h.id, end_event_id=e.id)],
            hook_event_id=h.id, cliffhanger_event_id=e.id,
            hook_description="keyword/punctuation heuristic", cliffhanger_description="",
            why_it_works=f"heuristic score {score:.1f}", confidence=min(1.0, score / 8))
        c = validate(Candidate(id=f"E{ep.number:02d}-B{len(out) + 1}", episodes=[ep.number],
                               proposer_model="baseline-heuristic",
                               proposal=prop), episodes, rules)
        if c.validation.passed:
            c.scores = {"heuristic": round(score, 2)}
            out.append(c)
        if len(out) >= n:
            break
    return out
