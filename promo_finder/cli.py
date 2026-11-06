"""Command line entry point: python -m promo_finder <command>."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import typer
from rich.console import Console

from .normalize import (
    apply_aliases,
    build_alias_map,
    load_overrides,
    render_transcript,
    roster_summary,
)
from .parse import fmt_time, load_corpus

app = typer.Typer(add_completion=False, help="Find ranked promo clips in microdrama screenplays.")
console = Console()


@app.callback()
def main() -> None:
    """promo-finder CLI."""


@app.command()
def parse(
    input: Path = typer.Option(Path("data/episodes"), help="Folder of episode .txt files"),
    out: Path = typer.Option(Path("outputs/parsed"), help="Where to write parsed output"),
    overrides: Path = typer.Option(Path("config/roster_overrides.yaml")),
) -> None:
    """Parse all episodes, resolve speaker aliases, write JSON + transcripts."""
    episodes = load_corpus(input)
    if not episodes:
        console.print(f"[red]No .txt files found in {input}[/red]")
        raise typer.Exit(1)
    alias = build_alias_map(episodes, load_overrides(overrides))
    apply_aliases(episodes, alias)
    out.mkdir(parents=True, exist_ok=True)
    total_warn = 0
    for ep in episodes:
        stem = f"ep_{ep.number:02d}"
        (out / f"{stem}.json").write_text(ep.model_dump_json(indent=2), encoding="utf-8")
        (out / f"{stem}.transcript.txt").write_text(render_transcript(ep), encoding="utf-8")
        total_warn += len(ep.warnings)
        for w in ep.warnings:
            console.print(f"[yellow]ep {ep.number}: {w}[/yellow]")
    roster = roster_summary(episodes)
    (out / "roster.json").write_text(
        json.dumps({"aliases": alias, "characters": roster}, indent=2), encoding="utf-8")
    n_events = sum(len(ep.events) for ep in episodes)
    console.print(f"[green]Parsed {len(episodes)} episodes, {n_events} events, "
                  f"{len(roster)} characters, {total_warn} warnings -> {out}[/green]")


def _range(spec: str | None, available: list[int]) -> list[int]:
    if not spec:
        return available
    out: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return [n for n in available if n in out]


def load_show(input: Path, overrides: Path):
    episodes = load_corpus(input)
    if not episodes:
        console.print(f"[red]No .txt files found in {input}[/red]")
        raise typer.Exit(1)
    alias = build_alias_map(episodes, load_overrides(overrides))
    apply_aliases(episodes, alias)
    return {ep.number: ep for ep in episodes}, roster_summary(episodes)


@app.command()
def propose(
    input: Path = typer.Option(Path("data/episodes"), help="Folder of episode .txt files"),
    episodes: str = typer.Option(None, help="Episodes to run, e.g. '1-3' or '1,5,9'"),
    out: Path = typer.Option(Path("outputs"), help="Parent folder for run output"),
    run_id: str = typer.Option(None, help="Run folder name (default: timestamp)"),
    config: Path = typer.Option(Path("config.yaml")),
    overrides: Path = typer.Option(Path("config/roster_overrides.yaml")),
) -> None:
    """Propose, validate and repair promo candidates (Phase 3 stages)."""
    from dotenv import load_dotenv

    from .config import load_config
    from .llm import LLMClient, LLMError
    from .propose import propose_episode

    load_dotenv()
    cfg = load_config(str(config))
    eps, roster = load_show(input, overrides)
    todo = _range(episodes, sorted(eps))
    run_dir = out / (run_id or time.strftime("run_%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    llm = LLMClient(cfg, log_dir=run_dir / "llm_raw")
    try:
        used = llm.preflight("proposer")
        console.print(f"Model check: {used}")
    except LLMError as e:
        console.print(f"[red]Model check failed: {e}[/red]\n"
                      "Fix: run `python -m promo_finder models`, pick a listed model, and set it "
                      "in config.yaml (or export PROMO_MODEL=gemini/<name>). Check .env too.")
        raise typer.Exit(1) from None
    console.print(f"Model (proposer): [bold]{llm.model_for('proposer')}[/bold]; "
                  f"episodes {todo[0]}-{todo[-1]} ({len(todo)}); output {run_dir}")
    t0 = time.time()
    all_cands = []
    for n in todo:
        cands = propose_episode(eps[n], eps, roster, llm, cfg)
        all_cands.extend(cands)
        ok = sum(c.validation.passed for c in cands if c.validation)
        console.print(f"ep {n:02d}: {len(cands)} candidates, {ok} valid")
    (run_dir / "candidates_all.json").write_text(
        json.dumps([c.model_dump() for c in all_cands], indent=2, ensure_ascii=False),
        encoding="utf-8")
    _write_summary(run_dir / "candidates_summary.md", all_cands)
    stats = {"episodes": len(todo), "candidates": len(all_cands),
             "valid": sum(c.validation.passed for c in all_cands if c.validation),
             "valid_first_try": sum(c.validation.passed and c.repair_attempts == 0
                                    for c in all_cands if c.validation),
             "seconds": round(time.time() - t0, 1), "usage": llm.usage,
             "model_proposer": llm.model_for("proposer")}
    (run_dir / "run_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    console.print(f"[green]{stats['valid']}/{stats['candidates']} valid "
                  f"({stats['valid_first_try']} on first try), {stats['seconds']} s, "
                  f"usage {llm.usage}[/green]")


def _write_summary(path: Path, cands) -> None:
    rows = ["# Candidates", ""]
    for c in cands:
        v = c.validation
        segs = "; ".join(f"ep{s.ep} {fmt_time(s.start)}-{fmt_time(s.end)}" for s in c.segments)
        status = "VALID" if v and v.passed else "REJECTED"
        rows += [f"## {c.id}  [{status}]  {v.duration if v else 0:.1f} s  "
                 f"(repairs: {c.repair_attempts})",
                 f"- Segments: {segs or '-'}",
                 f"- Hook: {c.hook_text or c.proposal.hook_event_id} - "
                 f"{c.proposal.hook_description}",
                 f"- Cliffhanger: {c.cliffhanger_text or c.proposal.cliffhanger_event_id} - "
                 f"{c.proposal.cliffhanger_description}",
                 f"- Leaves viewer asking: {c.proposal.unresolved_question}",
                 f"- Why: {c.proposal.why_it_works}",
                 f"- Right after the cut: {' | '.join(c.after_cut) or '(episode ends)'}"]
        if v and (v.errors or v.warnings):
            rows.append(f"- Errors: {v.errors}  Warnings: {v.warnings}")
        rows.append("")
    path.write_text("\n".join(rows), encoding="utf-8")


@app.command()
def run(
    input: Path = typer.Option(Path("data/episodes"), help="Folder of episode .txt files"),
    episodes: str = typer.Option(None, help="Episodes to run, e.g. '1-10' (default: all)"),
    out: Path = typer.Option(Path("outputs"), help="Parent folder for run output"),
    run_id: str = typer.Option(None, help="Run folder name; reuse it to resume a run"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Heuristic baseline, no API needed"),
    config: Path = typer.Option(Path("config.yaml")),
    overrides: Path = typer.Option(Path("config/roster_overrides.yaml")),
    verbose: bool = typer.Option(False, "--verbose", help="Also print provider quota/retry warnings"),
) -> None:
    """Full pipeline: find, check, score and rank promos; write reports."""
    import os

    from dotenv import load_dotenv

    if verbose:
        os.environ["PROMO_VERBOSE"] = "1"

    from .config import load_config
    from .llm import LLMError
    from .pipeline import run_pipeline

    load_dotenv()
    cfg = load_config(str(config))
    eps, roster = load_show(input, overrides)
    todo = _range(episodes, sorted(eps))
    default = ("baseline_" if no_llm else "run_") + time.strftime("%Y%m%d_%H%M%S")
    run_dir = out / (run_id or default)
    run_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"Episodes {todo[0]}-{todo[-1]} ({len(todo)}), output {run_dir}")
    try:
        ranked = run_pipeline(eps, roster, todo, cfg, run_dir, no_llm=no_llm)
    except LLMError as e:
        console.print(f"[red]{e}[/red]\nRe-run the same command with --run-id "
                      f"{run_dir.name} to resume.")
        raise typer.Exit(1) from None
    console.print(f"[green]{len(ranked)} ranked promos. Open {run_dir}/ranking_report.md[/green]")
    for c in ranked[:5]:
        segs = " + ".join(f"ep{s.ep} {fmt_time(s.start)}-{fmt_time(s.end)}" for s in c.segments)
        console.print(f"  #{c.rank} {c.id} {segs} ({c.validation.duration:.0f} s) "
                      f"score {c.composite}")


@app.command()
def evaluate(
    run: Path = typer.Option(Path("outputs/full"), help="Run folder to evaluate"),
    baseline: Path = typer.Option(Path("outputs/baseline"), help="No-LLM run to compare"),
    gold: Path = typer.Option(Path("eval/gold.yaml"), help="Hand-picked promos"),
    out: Path = typer.Option(Path("eval/results")),
    config: Path = typer.Option(Path("config.yaml")),
) -> None:
    """Score a run against gold labels and the baseline; write failures.md (no LLM)."""
    from .config import load_config
    from .evaluate import evaluate as do_eval
    from .evaluate import write_facts

    res = do_eval(run, baseline, gold, load_config(str(config))["promo_rules"], out)
    write_facts(run, res, Path("docs/facts.md"))
    console.print_json(json.dumps({k: v for k, v in res.items() if k != "gold_llm"
                                   and k != "gold_baseline"}))
    for key in ("gold_llm", "gold_baseline"):
        if key in res:
            console.print(f"[bold]{key}[/bold]: {res[key]['summary']}")
    console.print(f"[green]Written: {out}/eval_results.json, {out}/failures.md, "
                  f"docs/facts.md[/green]")


@app.command()
def ping(config: Path = typer.Option(Path("config.yaml")),
         timeout: int = typer.Option(30, help="Seconds to wait per model")) -> None:
    """Test each configured model with a tiny call; shows which ones answer and how fast."""
    from dotenv import load_dotenv

    from .config import load_config
    from .llm import LLMClient, LLMError

    load_dotenv()
    cfg = load_config(str(config))
    llm = LLMClient(cfg)
    fb = cfg["models"].get("fallbacks") or []
    fb = [m for v in fb.values() for m in v] if isinstance(fb, dict) else fb
    models_ = list(dict.fromkeys([cfg["models"][r] for r in
                                  ("proposer", "judge", "blind_viewer")] + fb))
    for m in models_:
        t0 = time.time()
        try:
            llm._call_provider(m, [{"role": "user", "content": "Reply with: ok"}], 0.0,
                               timeout=timeout, retries=0)
            console.print(f"[green]OK  [/green] {m}  ({time.time() - t0:.1f} s)")
        except LLMError as e:
            console.print(f"[red]FAIL[/red] {m}  ({time.time() - t0:.1f} s): {str(e)[:120]}")


@app.command()
def models(provider: str = typer.Option("gemini", help="Only 'gemini' is supported")) -> None:
    """List the Gemini models your API key can use (model names change often)."""
    import urllib.request

    from dotenv import load_dotenv

    load_dotenv()
    key = os.getenv("GEMINI_API_KEY", "")
    if not key or key == "your_key_here":
        console.print("[red]Set GEMINI_API_KEY in .env first[/red]")
        raise typer.Exit(1)
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
        headers={"x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    for m in data.get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            console.print(f"gemini/{m['name'].split('/', 1)[1]}")


if __name__ == "__main__":
    app()
