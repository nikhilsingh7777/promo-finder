# promo-finder

Reads microdrama screenplays and finds the best **20-60 second promo clips** for TikTok / Reels /
Shorts: each one opens on a hook in the first 3 seconds, ends on a cliffhanger, and makes sense
to a stranger. Output: ranked promos with the episode, start/end timestamps of every segment,
the hook, the cliffhanger, one line on why it works, and a suggested posting order.

Built for the Kuku AI Generalist assignment (Problem 1). The Kuku episode files are
confidential and are **not** in this repo.

## How it works

```
screenplays ─► parse (code) ─► propose clips (LLM picks line IDs, never timestamps)
           ─► validate + snap (code: 20-60 s, hook ≤3 s, ends on cliffhanger, no cut lines)
           ─► repair loop (LLM, given the exact measured errors, max 2 tries)
           ─► judge (2nd model, 1-5 rubric) + blind viewer (reads only the clip)
           ─► rank (code: weighted score, dedupe, episode diversity) ─► editor posting order (LLM)
```

**The rule that matters:** the LLM chooses *which lines*; code computes every time and duration
and enforces every hard rule. A clip that breaks a rule never reaches the ranking.

| Step | Who does it | Why |
|---|---|---|
| Parsing, timestamps, durations, rule checks, ranking maths | Code | Deterministic, testable, free |
| Choosing moments, judging hook/cliffhanger quality, cold-viewer test | LLM | Needs taste |
| Final pick and posting | Human editor | Reviews ~30 ranked promos instead of watching 50 episodes |

## Setup

Needs Python 3.11+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add GEMINI_API_KEY (free key from aistudio.google.com)
pytest                        # 30+ tests, no API key needed
```

Put episode `.txt` files in `data/episodes/` (any folder works with `--input`).

## Run

```bash
python -m promo_finder run --run-id full                     # all episodes, resumable
python -m promo_finder run --input path/to/new_show --run-id new_show
python -m promo_finder run --episodes 1-10 --run-id test       # a subset
python -m promo_finder run --no-llm --run-id baseline          # heuristic, no API key
python -m promo_finder evaluate --run outputs/full             # gold set, baseline, failures
python -m promo_finder ping                                    # which models answer right now
python -m promo_finder models                                  # models your key can use
python -m promo_finder parse                                   # parsed JSON + transcripts only
```

An interrupted run resumes: re-run the same command with the same `--run-id`.

## Swap the model (no code change)

Models live in `config.yaml` (`models:` per role, plus per-role fallback chains). Any
[LiteLLM](https://docs.litellm.ai/docs/providers) model string works. Override without editing:

```bash
export PROMO_MODEL=<provider>/<model>                 # every role, e.g. a stronger model
export PROMO_MODEL_PROPOSER=<provider>/<model>        # one role only
export PROMO_API_BASE=https://your-endpoint/v1 PROMO_API_KEY=...   # OpenAI-compatible API
```

## Outputs (`outputs/<run-id>/`)

| File | Contents |
|---|---|
| `promos_ranked.csv` / `.json` | Final ranked promos: segments with timestamps, hook, cliffhanger, why, scores, blind test, proposer model |
| `ranking_report.md` | Human-readable ranking + suggested posting order with reasons |
| `candidates_all.json` | Every candidate, including rejected ones and their errors and repair history |
| `episodes/ep_XX.json` | Per-episode checkpoints (resume) |
| `llm_raw/calls.jsonl`, `errors.jsonl` | Every prompt and raw response, token usage, provider errors |
| `run_stats.json` | Counts, models, tokens, timing, config hash, git commit |

## Quality checks

- 30+ unit tests: parser, every hard rule, repair loop, fallback, full pipeline with a fake LLM.
- `evaluate`: tool vs hand-picked gold promos (overlap, hook-line match, boundary error),
  compared with the no-LLM baseline; rule audit of the final list; `failures.md`.
- `docs/model_comparison.md`: same episodes, strong vs lite proposer model.

## Known limits

- Script only: there is no video, so a visual hook exists only if the script describes it.
- Promos joined **across episodes** are not generated yet (multi-segment within one episode is).
- On the free tier the strong models allow ~20 requests/day each; when they run out the run
  falls back to a lite model and records which model proposed each episode.
- The judge and blind viewer are LLMs, not real viewers; their scores are a proxy to be
  checked against real post performance.

## Repo map

`promo_finder/` code · `prompts/` versioned prompts · `config.yaml` all tunables ·
`tests/` · `eval/` gold labels + results · `docs/` assumptions, AI mistakes, model comparison,
facts · `scripts/profile_corpus.py` corpus profiler
