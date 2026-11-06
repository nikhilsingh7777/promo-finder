"""Deterministic promo checks. Code, not the LLM, owns every time and duration.

Hard rules (any failure -> candidate rejected or sent to repair):
  R1 total duration in [min_duration_s, max_duration_s]
  R2 segments in story order, not overlapping, at most max_segments
  R3 boundaries never cut a dialogue line (boundaries are widened to whole lines)
  R4 hook event starts within hook_window_s of the promo start, and the first
     hook_window_s seconds contain dialogue or action, not only camera shots
  R5 cliffhanger event is in the last segment and the promo ends soon after it
  R6 every referenced event ID exists
"""

from __future__ import annotations

from .models import Candidate, Episode, Event, EventType, Segment, Validation
from .parse import fmt_time

CLIFF_TAIL_MAX_S = 4.0       # promo may continue at most this long after the cliffhanger ends


def _ep_of(event_id: str) -> int | None:
    try:
        return int(event_id.split("-")[0][1:])
    except (ValueError, IndexError):
        return None


def build_segments(cand: Candidate, episodes: dict[int, Episode], rules: dict
                   ) -> tuple[list[Segment], list[str], list[str]]:
    """Turn event-ID segments into timed segments, widened to whole dialogue lines."""
    errors: list[str] = []
    warnings: list[str] = []
    segs: list[Segment] = []
    for i, ps in enumerate(cand.proposal.segments, 1):
        ep_no = _ep_of(ps.start_event_id)
        ep = episodes.get(ep_no) if ep_no is not None else None
        if ep is None or _ep_of(ps.end_event_id) != ep_no:
            errors.append(f"segment {i}: start and end must be valid IDs from one episode "
                          f"({ps.start_event_id}, {ps.end_event_id})")
            continue
        by_id = ep.event_by_id()
        a, b = by_id.get(ps.start_event_id), by_id.get(ps.end_event_id)
        if a is None or b is None:
            missing = [x for x, ev in ((ps.start_event_id, a), (ps.end_event_id, b)) if ev is None]
            errors.append(f"segment {i}: unknown event ID(s) {missing}")
            continue
        start, end = min(a.start, b.start), max(a.end, b.end)
        if b.start < a.start:
            warnings.append(f"segment {i}: end event is before start event; order swapped")
        # R3: widen to whole dialogue lines that straddle a boundary.
        for e in ep.events:
            if e.type != EventType.DIALOGUE:
                continue
            if e.start < start < e.end:
                start = e.start
            if e.start < end < e.end:
                end = e.end
        # Small lead-in / tail so the cut breathes, never reaching another dialogue line.
        prev_line_end = max((e.end for e in ep.events
                             if e.type == EventType.DIALOGUE and e.end <= start), default=0.0)
        next_line_start = min((e.start for e in ep.events
                               if e.type == EventType.DIALOGUE and e.start >= end),
                              default=ep.duration)
        start = max(start - rules["lead_in_s"], prev_line_end, 0.0)
        end = min(end + rules["tail_s"], next_line_start, ep.duration)
        segs.append(Segment(ep=ep_no, start_event_id=ps.start_event_id,
                            end_event_id=ps.end_event_id,
                            start=round(start, 2), end=round(end, 2)))
    return segs, errors, warnings


def validate(cand: Candidate, episodes: dict[int, Episode], rules: dict) -> Candidate:
    segs, errors, warnings = build_segments(cand, episodes, rules)
    p = cand.proposal
    val = Validation(passed=False)

    if not p.segments:
        errors.append("no segments")
    if len(p.segments) > rules["max_segments"]:
        errors.append(f"{len(p.segments)} segments; max is {rules['max_segments']}")

    # R2 ordering / overlap
    for x, y in zip(segs, segs[1:], strict=False):
        if (y.ep, y.start) < (x.ep, x.start):
            errors.append("segments are not in story order")
        elif y.ep == x.ep and y.start < x.end:
            errors.append(f"segments overlap ({fmt_time(x.start)}-{fmt_time(x.end)} and "
                          f"{fmt_time(y.start)}-{fmt_time(y.end)})")
    for i, s in enumerate(segs, 1):
        if s.duration < 3:
            warnings.append(f"segment {i} is very short ({s.duration:.1f} s)")

    # R1 duration
    total = round(sum(s.duration for s in segs), 2)
    val.duration = total
    if segs and not rules["min_duration_s"] <= total <= rules["max_duration_s"]:
        errors.append(f"total duration {total:.1f} s; must be "
                      f"{rules['min_duration_s']}-{rules['max_duration_s']} s")
    val.edge = bool(segs) and not rules["target_min_s"] <= total <= rules["target_max_s"]
    if val.edge and not errors:
        warnings.append(f"duration {total:.1f} s is outside the target "
                        f"{rules['target_min_s']}-{rules['target_max_s']} s band")

    hook = _find(p.hook_event_id, episodes)
    cliff = _find(p.cliffhanger_event_id, episodes)
    if hook is None:
        errors.append(f"unknown hook_event_id {p.hook_event_id}")
    if cliff is None:
        errors.append(f"unknown cliffhanger_event_id {p.cliffhanger_event_id}")

    if segs and hook is not None:
        first = segs[0]
        # R4 hook must be something the viewer hears or sees happen, not a camera move
        if hook.type == EventType.CAMERA:
            errors.append(f"hook_event_id {hook.id} is a camera shot; pick the line or action "
                          "that grabs the viewer")
        # R4 hook position
        if hook.ep != first.ep or not first.start - 0.01 <= hook.start <= first.end:
            errors.append("hook event is not inside the first segment")
        elif hook.start - first.start > rules["hook_window_s"]:
            errors.append(f"hook starts {hook.start - first.start:.1f} s into the promo; "
                          f"must be within {rules['hook_window_s']} s")
        # R4 first seconds must not be camera-only
        win_end = first.start + rules["hook_window_s"]
        opening = [e for e in episodes[first.ep].events
                   if e.start < win_end and e.end > first.start and e.start >= first.start - 0.5]
        if not any(e.type in (EventType.DIALOGUE, EventType.ACTION, EventType.SOUND)
                   for e in opening):
            errors.append("first seconds contain only camera shots (no line or action)")
        cand.hook_text = _label(hook)

    if segs and cliff is not None:
        last = segs[-1]
        # R5 cliffhanger at the end
        if cliff.ep != last.ep or not last.start <= cliff.start <= last.end + 0.01:
            errors.append("cliffhanger event is not inside the last segment")
        elif last.end - cliff.end > CLIFF_TAIL_MAX_S:
            errors.append(f"promo continues {last.end - cliff.end:.1f} s after the cliffhanger; "
                          f"cut within {CLIFF_TAIL_MAX_S:.0f} s of it")
        ep = episodes[last.ep]
        later = [e for e in ep.events if e.start >= last.end - 0.01 and e.type != EventType.CAMERA]
        val.ends_at_episode_end = not later
        cand.after_cut = [_label(e) for e in later[:3]]
        if val.ends_at_episode_end:
            warnings.append("promo ends at the episode's own ending")
        cand.cliffhanger_text = _label(cliff)

    cand.segments = segs
    cand.episodes = sorted({s.ep for s in segs}) or cand.episodes
    cand.type = "single" if len(segs) <= 1 else ("multi" if len(cand.episodes) == 1
                                                 else "composed")
    val.errors, val.warnings = errors, warnings
    val.passed = not errors
    cand.validation = val
    return cand


def _find(event_id: str, episodes: dict[int, Episode]) -> Event | None:
    ep_no = _ep_of(event_id)
    if ep_no is None or ep_no not in episodes:
        return None
    return episodes[ep_no].event_by_id().get(event_id)


def _label(e: Event) -> str:
    if e.type == EventType.DIALOGUE:
        who = e.speaker_canonical or e.speaker
        return f'[{e.id}] {who}: "{e.text}"'
    return f"[{e.id}] {e.type.value}: {e.text}"
