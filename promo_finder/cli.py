"""Command line entry point: python -m promo_finder <command>."""

from __future__ import annotations

import json
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
from .parse import load_corpus

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


if __name__ == "__main__":
    app()
