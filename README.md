# promo-finder

Finds and ranks 20-60 second promo clips (hook in the first 3 s, cliffhanger ending, makes sense alone)
in microdrama screenplays. Built for the Kuku AI Generalist assignment, Problem 1.

> The Kuku episode files are confidential. They live in `data/episodes/`, which is git-ignored.

## Setup (macOS / Linux)

```bash
python3 --version            # needs 3.11+
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env         # then put your real API key(s) in .env
pytest                       # smoke test
```

## Configure the model

Edit `config.yaml` -> `models:`. Any LiteLLM model string works, so swapping to a stronger model or a
provided API endpoint needs no code change (`api_base` for OpenAI-compatible endpoints).

## Run

Commands are added phase by phase (see `docs/MASTER_BUILD_PROMPT.md`), for example:

```bash
python -m promo_finder run --input data/episodes --out outputs/
```

## Status

Setup done. Next: Phase 1 (corpus profiler).
