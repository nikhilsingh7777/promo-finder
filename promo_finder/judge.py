"""Stage S7: score candidates (judge) and test them on a 'cold' viewer (blind test).

Both are LLM calls, batched per episode to stay inside free-tier rate limits.
Neither call ever sees or writes timestamps: they read clip text and answer with IDs.
"""

from __future__ import annotations

from rich.console import Console

from .llm import LLMClient, LLMError
from .models import BlindResponse, Candidate, Episode, EventType, JudgeResponse
from .normalize import render_event
from .propose import load_prompt, rule_vars

console = Console()


def clip_events(c: Candidate, episodes: dict[int, Episode]):
    """Events that fall inside the candidate's segments, in order."""
    out = []
    for s in c.segments:
        for e in episodes[s.ep].events:
            if e.start >= s.start - 0.01 and e.end <= s.end + 0.01:
                out.append(e)
    return out


def clip_text(c: Candidate, episodes: dict[int, Episode], with_camera: bool = True) -> str:
    lines = []
    for i, s in enumerate(c.segments, 1):
        if len(c.segments) > 1:
            lines.append(f"--- segment {i} ---")
        for e in episodes[s.ep].events:
            if e.start >= s.start - 0.01 and e.end <= s.end + 0.01:
                if with_camera or e.type != EventType.CAMERA:
                    lines.append(render_event(e))
    return "\n".join(lines)


def series_notes(episodes: dict[int, Episode], ep_no: int, ahead: int = 3) -> str:
    rows = [f"- Ep {k}: {episodes[k].logline}" for k in range(ep_no, ep_no + ahead + 1)
            if k in episodes]
    return "\n".join(rows)


def judge_episode(cands: list[Candidate], episodes: dict[int, Episode], llm: LLMClient,
                  ep_no: int, cfg: dict | None = None) -> None:
    valid = [c for c in cands if c.validation and c.validation.passed]
    if not valid:
        return
    blocks = []
    for c in valid:
        after = "\n".join(c.after_cut) or "(the episode ends here)"
        blocks.append(f"### CLIP {c.id} ({c.validation.duration:.0f} s)\n"
                      f"{clip_text(c, episodes)}\nRIGHT AFTER THE CUT (not in clip):\n{after}")
    cfg = cfg or {}
    ahead = cfg.get("generation", {}).get("spoiler_lookahead_episodes", 3)
    user = (f"SERIES NOTES (this episode and the next few, for spoiler checks):\n"
            f"{series_notes(episodes, ep_no, ahead)}\n\n" + "\n\n".join(blocks))
    try:
        judge_sys = load_prompt("judge_v1.md", **rule_vars(cfg["promo_rules"])) if cfg \
            else load_prompt("judge_v1.md")
        resp = llm.json_call("judge", judge_sys, user, JudgeResponse,
                             tag=f"judge:ep{ep_no}")
        by_id = {s.candidate_id: s for s in resp.scores}
        for c in valid:
            if c.id in by_id:
                c.scores = by_id[c.id].model_dump(exclude={"candidate_id"})
            else:
                c.scores = {"missing": True}
    except LLMError as e:
        console.print(f"[red]ep {ep_no}: judge failed: {e}[/red]")

    # Blind viewer: no series notes, no roster, no 'after the cut': only the clip itself.
    blocks = [f"### CLIP {c.id}\n{clip_text(c, episodes, with_camera=True)}" for c in valid]
    try:
        resp = llm.json_call("blind_viewer", load_prompt("blind_v1.md"), "\n\n".join(blocks),
                             BlindResponse, tag=f"blind:ep{ep_no}")
        by_id = {r.candidate_id: r for r in resp.results}
        for c in valid:
            if c.id in by_id:
                c.blind_test = by_id[c.id].model_dump(exclude={"candidate_id"})
    except LLMError as e:
        console.print(f"[red]ep {ep_no}: blind test failed: {e}[/red]")
