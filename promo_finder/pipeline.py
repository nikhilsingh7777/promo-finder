"""End-to-end run: propose -> validate/repair -> judge + blind test -> rank -> editor -> reports.

Each episode's result is checkpointed, so an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path

from rich.console import Console

from .baseline import baseline_episode
from .judge import clip_text
from .llm import LLMClient, LLMError
from .models import Candidate, EditorResponse, Episode
from .propose import load_prompt, propose_episode
from .rank import rank
from .report import write_reports

console = Console()


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def run_pipeline(episodes: dict[int, Episode], roster: list[dict], todo: list[int],
                 cfg: dict, run_dir: Path, no_llm: bool = False) -> list[Candidate]:
    from .judge import judge_episode

    ckpt = run_dir / "episodes"
    ckpt.mkdir(parents=True, exist_ok=True)
    llm = None if no_llm else LLMClient(cfg, log_dir=run_dir / "llm_raw")
    if llm:
        used = llm.preflight("proposer")
        console.print(f"Model check: {used}")
    t0 = time.time()
    all_cands: list[Candidate] = []
    for n in todo:
        f = ckpt / f"ep_{n:02d}.json"
        if f.exists():
            cands = [Candidate.model_validate(d) for d in json.loads(f.read_text())]
            console.print(f"ep {n:02d}: resumed ({len(cands)} candidates)")
        else:
            if no_llm:
                cands = baseline_episode(episodes[n], episodes, cfg)
            else:
                cands = propose_episode(episodes[n], episodes, roster, llm, cfg)
                judge_episode(cands, episodes, llm, n, cfg)
            f.write_text(json.dumps([c.model_dump() for c in cands], ensure_ascii=False),
                         encoding="utf-8")
            ok = sum(1 for c in cands if c.validation and c.validation.passed)
            console.print(f"ep {n:02d}: {len(cands)} candidates, {ok} valid")
        all_cands.extend(cands)

    ranked = rank(all_cands, cfg)
    editor = None
    if llm and ranked:
        editor = editor_note(ranked[: cfg["ranking"]["editor_note_top_k"]], episodes, llm)

    stats = {
        "run_dir": str(run_dir), "mode": "baseline (no LLM)" if no_llm else "llm",
        "episodes": len(todo),
        "candidates": len(all_cands),
        "valid": sum(1 for c in all_cands if c.validation and c.validation.passed),
        "valid_first_try": sum(1 for c in all_cands if c.validation and c.validation.passed
                               and c.repair_attempts == 0),
        "repaired": sum(1 for c in all_cands if c.repair_attempts > 0),
        "ranked_after_dedupe": len(ranked),
        "episodes_by_proposer_model": _count_models(all_cands),
        "seconds_this_session": round(time.time() - t0, 1),
        "llm_usage_this_session": llm.usage if llm else {},
        "models": {} if no_llm else {r: llm.model_for(r) for r in
                                     ("proposer", "judge", "blind_viewer", "editor")},
        "config_hash": hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:12],
        "git_commit": _git_commit(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_reports(run_dir, ranked, all_cands, editor, stats, cfg["ranking"]["final_n"])
    return ranked


def _count_models(cands: list[Candidate]) -> dict:
    eps: dict[str, set] = {}
    for c in cands:
        eps.setdefault(c.proposer_model or "unknown", set()).update(c.episodes)
    return {m: len(v) for m, v in eps.items()}


def editor_note(top: list[Candidate], episodes: dict[int, Episode], llm: LLMClient
                ) -> dict | None:
    blocks = []
    for c in top:
        s = c.scores or {}
        blocks.append(f"### {c.id} (rank {c.rank}, score {c.composite}, "
                      f"{c.validation.duration:.0f} s)\nHook: {c.hook_text}\n"
                      f"Cliffhanger: {c.cliffhanger_text}\nJudge: {s.get('reason', '')}\n"
                      f"{clip_text(c, episodes, with_camera=False)}")
    try:
        resp = llm.json_call("editor", load_prompt("editor_v1.md"), "\n\n".join(blocks),
                             EditorResponse, tag="editor")
        valid_ids = {c.id for c in top}
        resp.order = [i for i in resp.order if i in valid_ids]
        return resp.model_dump()
    except LLMError as e:
        console.print(f"[red]editor note failed: {e}[/red]")
        return None
