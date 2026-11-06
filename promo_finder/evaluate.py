"""Quality checks on a finished run (no LLM calls).

1. Gold set: compare the tool's picks with hand-picked promos (eval/gold.yaml).
2. Baseline: the same metrics for the no-LLM heuristic run, to show what the LLM adds.
3. Rule audit: every final promo re-checked against the hard rules.
4. Failure log: the weakest picks and every disagreement, for a human to read.
5. facts.md: every number the solution doc needs, generated (never typed by hand).
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import yaml

from .models import Candidate
from .parse import fmt_time, to_seconds


def load_run(run_dir: Path) -> list[Candidate]:
    f = run_dir / "candidates_all.json"
    if f.exists():
        return [Candidate.model_validate(d) for d in json.loads(f.read_text())]
    out = []
    for p in sorted((run_dir / "episodes").glob("ep_*.json")):
        out += [Candidate.model_validate(d) for d in json.loads(p.read_text())]
    return out


def load_ranked(run_dir: Path) -> list[dict]:
    f = run_dir / "promos_ranked.json"
    return json.loads(f.read_text()) if f.exists() else []


def overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union > 0 else 0.0


def span(c: Candidate, ep: int) -> tuple[float, float] | None:
    segs = [s for s in c.segments if s.ep == ep]
    return (min(s.start for s in segs), max(s.end for s in segs)) if segs else None


def gold_metrics(cands: list[Candidate], gold: list[dict]) -> dict:
    """Per gold promo: best match among the tool's valid picks in that episode."""
    valid = [c for c in cands if c.validation and c.validation.passed]
    rows = []
    for g in gold:
        ep = int(g["episode"])
        gs = (to_seconds(str(g["start"])), to_seconds(str(g["end"])))
        mine = [c for c in valid if ep in c.episodes]
        # rank inside the episode by composite (or proposal order when unscored)
        mine.sort(key=lambda c: (c.composite is None, -(c.composite or 0)))
        best, best_iou, best_pos = None, 0.0, None
        for pos, c in enumerate(mine, 1):
            sp = span(c, ep)
            iou = overlap(sp, gs) if sp else 0.0
            if iou > best_iou:
                best, best_iou, best_pos = c, iou, pos
        hook = str(g.get("hook_line", "")).strip().strip('"').lower()
        hook_hit = bool(hook) and any(hook[:25] in (c.hook_text or "").lower() for c in mine)
        sp = span(best, ep) if best else None
        rows.append({
            "episode": ep, "gold": f"{fmt_time(gs[0])}-{fmt_time(gs[1])}",
            "tool_candidates": len(mine),
            "best_match": best.id if best else None,
            "best_match_span": f"{fmt_time(sp[0])}-{fmt_time(sp[1])}" if sp else None,
            "best_iou": round(best_iou, 2), "best_match_rank_in_episode": best_pos,
            "top1_iou": round(overlap(span(mine[0], ep), gs), 2) if mine else 0.0,
            "start_error_s": round(abs(sp[0] - gs[0]), 1) if sp else None,
            "end_error_s": round(abs(sp[1] - gs[1]), 1) if sp else None,
            "same_hook_line": hook_hit,
        })
    n = len(rows) or 1
    summary = {
        "gold_promos": len(rows),
        "hit_any_iou>=0.5": sum(r["best_iou"] >= 0.5 for r in rows),
        "hit_any_iou>=0.3": sum(r["best_iou"] >= 0.3 for r in rows),
        "hit_top1_iou>=0.5": sum(r["top1_iou"] >= 0.5 for r in rows),
        "same_hook_line": sum(r["same_hook_line"] for r in rows),
        "mean_best_iou": round(sum(r["best_iou"] for r in rows) / n, 2),
        "mean_start_error_s": _mean([r["start_error_s"] for r in rows]),
        "mean_end_error_s": _mean([r["end_error_s"] for r in rows]),
    }
    return {"summary": summary, "rows": rows}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def rule_audit(ranked: list[dict], rules: dict) -> dict:
    bad = []
    for r in ranked:
        d = r.get("duration_s") or 0
        if not rules["min_duration_s"] <= d <= rules["max_duration_s"]:
            bad.append((r["promo_id"], f"duration {d}"))
        segs = r.get("segments_detail", [])
        for a, b in zip(segs, segs[1:], strict=False):
            if (b["episode"], b["start_s"]) < (a["episode"], a["end_s"]):
                bad.append((r["promo_id"], "segment order/overlap"))
    return {"final_promos": len(ranked), "rule_violations": bad}


def failure_log(cands: list[Candidate], ranked: list[dict]) -> list[str]:
    out = []
    valid = [c for c in cands if c.validation and c.validation.passed]
    rejected = [c for c in cands if c.validation and not c.validation.passed]
    errs = Counter(e.split(";")[0].split("(")[0].strip()[:70]
                   for c in rejected for e in c.validation.errors)
    out.append(f"## Rejected by the validator after repair: {len(rejected)} of {len(cands)}")
    out += [f"- {n} x {e}" for e, n in errs.most_common(8)]
    eps_all = {e for c in cands for e in c.episodes}
    eps_ok = {e for c in valid for e in c.episodes}
    if eps_all - eps_ok:
        out.append(f"\n## Episodes with no valid promo: {sorted(eps_all - eps_ok)}")
    blind_fail = [c for c in valid if c.blind_test and not c.blind_test.get("understood", True)]
    out.append(f"\n## Cold viewer could not follow: {len(blind_fail)} of {len(valid)}")
    for c in blind_fail[:10]:
        out.append(f"- {c.id}: {'; '.join(c.blind_test.get('confusions', []))[:200]}")
    inside = [c for c in valid if (c.scores or {}).get("answer_inside_clip")]
    out.append(f"\n## Judge says the clip already answers its own question: {len(inside)}")
    out += [f"- {c.id}: {(c.scores or {}).get('reason', '')[:200]}" for c in inside[:10]]
    spoil = [c for c in valid if (c.scores or {}).get("spoiler_risk", 0) >= 2]
    out.append(f"\n## Major spoiler risk: {len(spoil)}")
    out += [f"- {c.id}: {(c.scores or {}).get('reason', '')[:200]}" for c in spoil[:10]]
    weak_hook = [c for c in valid if (c.scores or {}).get("hook_strength", 5) <= 2]
    out.append(f"\n## Weak hooks (judge <= 2/5): {len(weak_hook)}")
    out += [f"- {c.id}: hook {c.hook_text[:120]}" for c in weak_hook[:10]]
    out.append("\n## Bottom 5 of the final ranked list (lowest score that still made it)")
    for r in ranked[-5:]:
        out.append(f"- #{r['rank']} {r['promo_id']} score {r['composite']}: "
                   f"{r.get('judge_reason', '')[:200]}")
    return out


def evaluate(run_dir: Path, baseline_dir: Path | None, gold_file: Path, rules: dict,
             out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cands, ranked = load_run(run_dir), load_ranked(run_dir)
    gold = (yaml.safe_load(gold_file.read_text()) or {}).get("promos", []) \
        if gold_file.exists() else []
    res = {"run": str(run_dir), "rule_audit": rule_audit(ranked, rules)}
    if gold:
        res["gold_llm"] = gold_metrics(cands, gold)
        if baseline_dir and baseline_dir.exists():
            res["gold_baseline"] = gold_metrics(load_run(baseline_dir), gold)
    valid = [c for c in cands if c.validation and c.validation.passed]
    scored = [c for c in valid if "hook_strength" in (c.scores or {})]
    res["counts"] = {
        "candidates": len(cands), "valid": len(valid),
        "valid_first_try": sum(c.repair_attempts == 0 for c in valid),
        "repaired_ok": sum(c.repair_attempts > 0 for c in valid),
        "blind_understood": sum(bool((c.blind_test or {}).get("understood")) for c in valid),
        "blind_would_watch": sum(bool((c.blind_test or {}).get("keep_watching")) for c in valid),
        "by_proposer_model": dict(Counter(c.proposer_model or "unknown" for c in cands)),
        "avg_scores": {k: round(sum(c.scores[k] for c in scored) / len(scored), 2)
                       for k in ("hook_strength", "cliffhanger_strength",
                                 "standalone_clarity", "spoiler_risk")} if scored else {},
    }
    (out_dir / "eval_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    (out_dir / "failures.md").write_text(
        "# Where the tool picks badly (auto-generated, then annotated by hand)\n\n"
        + "\n".join(failure_log(cands, ranked)) + "\n", encoding="utf-8")
    return res


def write_facts(run_dir: Path, res: dict, path: Path) -> None:
    """Numbers only, so the solution doc is written from measured facts."""
    stats = json.loads((run_dir / "run_stats.json").read_text()) \
        if (run_dir / "run_stats.json").exists() else {}
    calls = [json.loads(x) for x in (run_dir / "llm_raw" / "calls.jsonl").read_text()
             .splitlines()] if (run_dir / "llm_raw" / "calls.jsonl").exists() else []
    by_stage = Counter(c["tag"].split(":")[0] for c in calls)
    tok_in = sum((c.get("usage") or {}).get("prompt_tokens", 0) or 0 for c in calls)
    tok_out = sum((c.get("usage") or {}).get("completion_tokens", 0) or 0 for c in calls)
    eps = stats.get("episodes") or 1
    L = ["# Facts for the solution doc (generated by `promo_finder evaluate`)", ""]
    L.append(f"- Run: `{run_dir}` at {stats.get('timestamp')} (git {stats.get('git_commit')})")
    L.append(f"- Episodes: {stats.get('episodes')}; candidates {stats.get('candidates')}; "
             f"valid {stats.get('valid')} ({stats.get('valid_first_try')} first try, "
             f"{stats.get('repaired')} needed repair); ranked after dedupe "
             f"{stats.get('ranked_after_dedupe')}")
    L.append(f"- Episodes per proposer model: {stats.get('episodes_by_proposer_model')}")
    L.append(f"- Models: {stats.get('models')}")
    L.append(f"- LLM calls logged (not counting cached): {len(calls)} -> {dict(by_stage)}")
    L.append(f"- Tokens: {tok_in:,} in / {tok_out:,} out; per episode ~{tok_in // eps:,} in / "
             f"~{tok_out // eps:,} out")
    L.append("- Cost on free tier: $0. Paid-price estimate: multiply the token totals by the "
             "provider's current per-token price (check the pricing page; not hard-coded).")
    L.append(f"- Rule audit of final list: {res['rule_audit']['final_promos']} promos, "
             f"{len(res['rule_audit']['rule_violations'])} violations")
    L.append(f"- Counts: {res['counts']}")
    for key, label in (("gold_llm", "LLM pipeline vs gold"),
                       ("gold_baseline", "No-LLM baseline vs gold")):
        if key in res:
            L.append(f"- {label}: {res[key]['summary']}")
    L.append("- Model comparison (same episodes): see docs/model_comparison.md")
    L.append("- AI mistakes log: docs/AI_MISTAKES.md; assumptions: docs/ASSUMPTIONS.md")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
