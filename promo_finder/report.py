"""Stage S10: write the deliverable files. Nothing here is edited by hand."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import Candidate
from .parse import fmt_time

SCORE_KEYS = ["hook_strength", "cliffhanger_strength", "standalone_clarity",
              "emotional_intensity", "shareability", "spoiler_risk"]


def _segs(c: Candidate) -> str:
    return " + ".join(f"Ep{s.ep} {fmt_time(s.start)}-{fmt_time(s.end)}" for s in c.segments)


def row(c: Candidate) -> dict:
    bt = c.blind_test or {}
    r = {"rank": c.rank, "promo_id": c.id, "type": c.type,
         "episodes": ",".join(map(str, c.episodes)), "segments": _segs(c),
         "duration_s": c.validation.duration if c.validation else None,
         "hook": c.hook_text, "hook_note": c.proposal.hook_description,
         "cliffhanger": c.cliffhanger_text, "cliffhanger_note": c.proposal.cliffhanger_description,
         "unresolved_question": c.proposal.unresolved_question,
         "why_it_works": c.proposal.why_it_works, "composite": c.composite}
    for k in SCORE_KEYS:
        r[k] = c.scores.get(k) if c.scores else None
    r["judge_reason"] = (c.scores or {}).get("reason", "")
    r["blind_understood"] = bt.get("understood")
    r["blind_keep_watching"] = bt.get("keep_watching")
    r["blind_confusions"] = "; ".join(bt.get("confusions", []))
    r["warnings"] = "; ".join(c.validation.warnings) if c.validation else ""
    r["repairs"] = c.repair_attempts
    return r


def write_reports(run_dir: Path, ranked: list[Candidate], all_cands: list[Candidate],
                  editor: dict | None, stats: dict, final_n: int) -> None:
    final = ranked[:final_n]
    rows = [row(c) for c in final]
    with open(run_dir / "promos_ranked.csv", "w", newline="", encoding="utf-8") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    full = []
    for c in final:
        d = row(c)
        d["segments_detail"] = [{"episode": s.ep, "start": fmt_time(s.start),
                                 "end": fmt_time(s.end), "start_s": s.start, "end_s": s.end,
                                 "start_event_id": s.start_event_id,
                                 "end_event_id": s.end_event_id} for s in c.segments]
        d["after_cut"] = c.after_cut
        d["blind_test"] = c.blind_test
        full.append(d)
    (run_dir / "promos_ranked.json").write_text(json.dumps(full, indent=2, ensure_ascii=False),
                                                encoding="utf-8")
    (run_dir / "candidates_all.json").write_text(
        json.dumps([c.model_dump() for c in all_cands], indent=2, ensure_ascii=False),
        encoding="utf-8")

    md = ["# Ranked promos", "",
          f"Episodes: {stats.get('episodes')} | candidates: {stats.get('candidates')} | "
          f"valid: {stats.get('valid')} | ranked after dedupe: {len(ranked)} | "
          f"shown: {len(final)}", ""]
    if editor and editor.get("order"):
        md += ["## Suggested posting order (LLM editor, top picks)", ""]
        for i, cid in enumerate(editor["order"], 1):
            md.append(f"{i}. **{cid}**: {editor.get('notes', {}).get(cid, '')}")
        if editor.get("near_duplicates"):
            md.append(f"\nNear-duplicates flagged: {editor['near_duplicates']}")
        md.append("")
    md += ["## All ranked promos (code ranking)", ""]
    for c in final:
        s = c.scores or {}
        bt = c.blind_test or {}
        md += [f"### #{c.rank}  {c.id}  ({c.validation.duration:.0f} s, score {c.composite})",
               f"- **Cut:** {_segs(c)}",
               f"- **Hook:** {c.hook_text}",
               f"- **Cliffhanger:** {c.cliffhanger_text}",
               f"- **Why it works:** {c.proposal.why_it_works}",
               f"- **Judge:** hook {s.get('hook_strength')}, "
               f"cliff {s.get('cliffhanger_strength')}, "
               f"standalone {s.get('standalone_clarity')}, emotion {s.get('emotional_intensity')}, "
               f"share {s.get('shareability')}, spoiler {s.get('spoiler_risk')}. "
               f"{s.get('reason', '')}",
               f"- **Cold viewer:** understood={bt.get('understood')}, "
               f"would watch={bt.get('keep_watching')}. Confused by: "
               f"{'; '.join(bt.get('confusions', [])) or 'nothing'}",
               ""]
    (run_dir / "ranking_report.md").write_text("\n".join(md), encoding="utf-8")
    (run_dir / "run_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
