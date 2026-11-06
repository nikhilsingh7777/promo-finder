"""Builds the 'story so far' context for an episode from headers alone (no extra LLM calls)."""

from __future__ import annotations

from .models import Episode


def roster_text(roster: list[dict], top: int = 15) -> str:
    rows = []
    for c in roster[:top]:
        other = [lab for lab in c["labels"] if lab != c["name"]]
        alias = f" (also labelled: {', '.join(other)})" if other else ""
        rows.append(f"- {c['name']}{alias}: {c['lines']} lines, first seen ep {c['first_episode']}")
    return "\n".join(rows)


def story_so_far(episodes: dict[int, Episode], number: int, n_prev: int) -> str:
    rows = []
    for k in range(max(1, number - n_prev), number):
        ep = episodes.get(k)
        if ep:
            rows.append(f"- Ep {k}: {ep.logline}")
    return "\n".join(rows) or "- (this is the first episode)"


def episode_header(ep: Episode) -> str:
    return (f"Episode {ep.number} ({ep.duration:.0f} s)\nLogline: {ep.logline}\n"
            f"Continuity: {ep.continuity}")
