"""Stage S9: composite score (code), dedupe, diversity-aware ranking.

The judge gives taste scores; this file turns them into one number with weights from
config.yaml, so the ranking is transparent and can be re-weighted without new LLM calls.
"""

from __future__ import annotations

from .models import Candidate


def _n(x, lo=1, hi=5) -> float:
    try:
        return max(0.0, min(1.0, (float(x) - lo) / (hi - lo)))
    except (TypeError, ValueError):
        return 0.0


def composite(c: Candidate, cfg: dict) -> float | None:
    s = c.scores
    if s and "heuristic" in s and c.validation and c.validation.passed:
        return round(min(1.0, s["heuristic"] / 10), 4)      # --no-llm baseline
    if not s or s.get("missing") or not c.validation or not c.validation.passed:
        return None
    w = cfg["ranking"]["weights"]
    score = (w["hook"] * _n(s.get("hook_strength"))
             + w["cliffhanger"] * _n(s.get("cliffhanger_strength"))
             + w["standalone"] * _n(s.get("standalone_clarity"))
             + w["emotion_share"] * (_n(s.get("emotional_intensity"))
                                     + _n(s.get("shareability"))) / 2
             + w["spoiler_safety"] * (1 - min(2, s.get("spoiler_risk", 0)) / 2))
    pen = cfg["ranking"].get("penalties", {})
    if s.get("answer_inside_clip"):
        score -= pen.get("answer_inside_clip", 0.10)
    bt = c.blind_test
    if bt and not bt.get("understood", True):
        score -= pen.get("blind_not_understood", 0.08)
    if bt and not bt.get("keep_watching", True):
        score -= pen.get("blind_not_hooked", 0.05)
    if c.validation.edge:
        score -= pen.get("edge_duration", 0.03)
    if min(c.episodes) <= cfg["ranking"].get("early_episode_max", 5):
        score += cfg["ranking"].get("early_episode_bonus", 0.03)
    return round(score, 4)


def iou(a: Candidate, b: Candidate) -> float:
    """Temporal overlap of two candidates (same-episode parts only)."""
    inter = 0.0
    for x in a.segments:
        for y in b.segments:
            if x.ep == y.ep:
                inter += max(0.0, min(x.end, y.end) - max(x.start, y.start))
    da = sum(s.duration for s in a.segments)
    db = sum(s.duration for s in b.segments)
    union = da + db - inter
    return inter / union if union > 0 else 0.0


def rank(cands: list[Candidate], cfg: dict) -> list[Candidate]:
    """Score, drop near-duplicates, then greedy re-rank with a same-episode diversity penalty."""
    for c in cands:
        c.composite = composite(c, cfg)
    pool = sorted([c for c in cands if c.composite is not None],
                  key=lambda c: c.composite, reverse=True)
    kept: list[Candidate] = []
    thr = cfg["promo_rules"]["dedupe_iou"]
    for c in pool:
        if all(iou(c, k) <= thr for k in kept):
            kept.append(c)
    div = cfg["ranking"].get("same_episode_penalty", 0.04)
    ordered: list[Candidate] = []
    remaining = kept[:]
    while remaining:
        def adj(c: Candidate) -> float:
            same = sum(1 for o in ordered if set(o.episodes) & set(c.episodes))
            return c.composite - div * same
        best = max(remaining, key=adj)
        ordered.append(best)
        remaining.remove(best)
    for i, c in enumerate(ordered, 1):
        c.rank = i
    return ordered
