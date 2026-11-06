# promo-finder

**Finds the best 20–60 second promo clips in microdrama screenplays.** Each promo opens on a
hook inside the first 3 seconds, ends on a cliffhanger, and makes sense to someone who has never
seen the show. For every promo the tool returns the episode, the start and end of every segment
in order, the hook, the cliffhanger, one line on why it works, a score, and a suggested posting order.

Built for the Kuku AI Generalist assignment, Problem 1 (*Find the Promos*).
The episode screenplays are confidential and are **not** in this repo.

> **Links:** Solution doc (PDF) · Raw outputs of the full 50-episode run (Drive) · Walkthrough video
> *(filled in on the submission form)*

---

## Results on the full input pack (50 episodes)

| Candidates proposed | Passed every rule | Ranked after dedupe | Episodes covered | Rule violations | AI calls / tokens |
|:--:|:--:|:--:|:--:|:--:|:--:|
| 102 | 95 | **90** | 49 / 50 | **0** | 168 / 0.86 M |

Against 8 hand-marked gold promos (episodes 5, 9, 12, 20, 28, 35, 42, 49), scored by temporal IoU:

| | AI tool | No-AI keyword baseline |
|---|:--:|:--:|
| Found the gold moment (IoU ≥ 0.5) | **6 / 8** | 4 / 8 |
| …as its #1 pick for that episode | **4 / 8** | 0 / 8 |
| Mean IoU | **0.68** | 0.43 |
| Mean error at the clip's end | **4.8 s** | 19.3 s |

Top of the ranked list (`samples/promos_ranked_top10.csv` has the first 10 rows; the full
90-row output is in the Drive folder):

| # | Episode · segments | Hook (first 3 s) | Cliffhanger |
|---|---|---|---|
| 1 | Ep 3 · 00:58.2–01:36.5 (38 s) | "Guards! Remove her!" | Stranger: "Then don't touch her again." |
| 2 | Ep 11 · 01:07.5–01:52.8 (45 s) | "A perfect hiding hole for a thief." | The planted pocket watch is pulled out |
| 3 | Ep 23 · 01:18.2–02:11.5 (53 s) | "Someone is poisoning her." | The door latch turns: an intruder |
| 4 | Ep 15 · 00:47.3–01:26.0 (39 s) | A thug shoves Juliana | Cut on the swell as rescue nears |
| 5 | Ep 34 · 01:07.9–01:27.6 + 02:43.5–03:10.0 (46 s) | "She placed herbs around my brother's bed." | The judge raises his hand to sentence her |

---

## Quick start (3 commands)

Needs Python 3.11+ and a free Gemini key from [aistudio.google.com](https://aistudio.google.com).

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cp .env.example .env            # put GEMINI_API_KEY=... in .env
python -m promo_finder run --input path/to/episodes --run-id myshow
```

Then open `outputs/myshow/ranking_report.md` (ranked list + posting order with reasons) and
`outputs/myshow/promos_ranked.csv` (every promo, every segment, every score).

`pytest` runs 32 tests with no API key. `python -m promo_finder run --no-llm --run-id baseline`
runs the keyword baseline with no API key.

### Input format

A folder of `.txt` screenplays, one per episode, with scene headers and timestamped lines
(`[MM:SS.ss]`). File names are sorted naturally, so `Episode 1.txt … Episode 50.txt` works.
Timestamps are read as running through the whole episode, so a cut may span scenes.

### More commands

```bash
python -m promo_finder run --run-id full                 # default input folder data/episodes/, resumable
python -m promo_finder run --episodes 1-10 --run-id t    # a subset
python -m promo_finder evaluate --run outputs/full       # gold set vs baseline, rule audit, failures.md
python -m promo_finder ping                              # which configured models answer right now
python -m promo_finder models                            # models your key can use
python -m promo_finder parse                             # parsed JSON + transcripts only
```

An interrupted run resumes when you repeat the command with the same `--run-id`; finished
episodes are checkpointed and LLM responses are cached.

---

## How it works

```
screenplays ─► parse (code) ─► propose clips (LLM picks line IDs, never timestamps)
           ─► validate + snap (code: 20–60 s, hook ≤ 3 s, ends on cliffhanger, no cut lines)
           ─► repair loop (LLM, given the exact measured errors, max 2 tries)
           ─► judge (2nd model, 1–5 rubric) + blind viewer (reads only the clip)
           ─► rank (code: weighted score, dedupe, episode diversity) ─► posting order (LLM)
```

**The rule that matters:** the LLM chooses *which lines*; code computes every timestamp and
duration and enforces every hard rule. A clip that breaks a rule never reaches the ranking.

| Step | Who does it | Why |
|---|---|---|
| Parsing, timestamps, durations, rule checks, dedupe, ranking maths | Code | Deterministic, testable, free |
| Choosing moments, judging hook and cliffhanger, cold-viewer test, posting order | LLM | Needs taste |
| Final approval and posting | Human editor | Reviews ~30 ranked clips instead of watching 50 episodes |

### Swap the model (no code change)

Models are set per role in `config.yaml` (`models:` plus per-role fallback chains). Any
[LiteLLM](https://docs.litellm.ai/docs/providers) model string works. Override without editing:

```bash
export PROMO_MODEL=<provider>/<model>                 # every role, e.g. a stronger model
export PROMO_MODEL_PROPOSER=<provider>/<model>        # one role only
export PROMO_API_BASE=https://your-endpoint/v1 PROMO_API_KEY=...   # any OpenAI-compatible API
```

Every rule number (clip length, hook window, cliffhanger tail, candidates per episode, ranking
weights and penalties) lives in `config.yaml` and is fed into the prompts from there.

---

## Outputs (`outputs/<run-id>/`)

| File | Contents |
|---|---|
| `promos_ranked.csv` / `.json` | All ranked promos: segments with timestamps, hook, cliffhanger, why it works, scores, blind-viewer result, which model proposed it |
| `ranking_report.md` | Human-readable ranked list and suggested posting order with reasons |
| `candidates_all.json` | Every candidate including rejected ones, with their errors and repair history |
| `episodes/ep_XX.json` | Per-episode checkpoints (resume) |
| `llm_raw/calls.jsonl`, `errors.jsonl` | Every prompt and raw response, token usage, provider errors |
| `run_stats.json` | Counts, models used, tokens, timing, config hash, git commit |

`samples/` holds the top-10 CSV and the ranking report from the full run, so you can see the
output shape without running anything.

---

## How I know it works, and where it picks badly

- **Gold set:** `eval/gold.yaml` has one hand-marked promo for each of 8 episodes; `evaluate`
  scores every run against it (IoU, hook-line match, start/end error) and against the no-LLM baseline.
- **Rule audit:** the final list is re-checked against every hard rule after ranking (0 violations).
- **Blind viewer:** a model that sees only the clip text reports whether it understood it (90 of 95).
- **Tests:** 32 unit tests cover the parser, every rule, the repair loop, model fallback and the
  whole pipeline with a fake LLM.

Known failure patterns (details and examples in `eval/failure_analysis.md`):

1. **Runs past the cliffhanger.** 22 of 95 clips show the answer to their own question.
2. **Loose starts.** Ends are 4.8 s off on average, starts 9.8 s; weak hook lines can pass.
3. **The cheaper model picks worse.** Free-tier quota meant episodes 26–50 were proposed by
   Flash-Lite: 7 rule breaks out of 48 vs 0 of 54, and IoU 0.52 vs 0.84 (`docs/model_comparison.md`).
4. **Judge bias.** The Flash-Lite judge rated Flash-Lite clips higher than their gold match justifies.
5. **Script only.** A visual hook the script does not describe is invisible to the tool.
6. Promos joined **across episodes** are not generated (multi-segment within an episode is).

---

## Scale and cost

One show (50 episodes, ~103 minutes of drama): 168 LLM calls, 0.86 M tokens, about 35 minutes,
$0 on the free tier. Episodes are independent, so with a paid key they run in parallel and a
show takes minutes. At Kuku's volume: a paid key for the proposer only, a cheap judge, and
editor approvals fed back to tune the ranking weights.

---

## Repo map

```
promo_finder/     parse · normalize · propose · validate · judge · rank · report · pipeline · cli
prompts/          versioned prompt templates (numbers filled from config.yaml)
config.yaml       every tunable: models, fallbacks, rules, ranking weights
config/           roster_overrides.yaml (hand-mapped character aliases)
tests/            32 tests, no API key needed
eval/             gold.yaml, failure_analysis.md, results/
docs/             ASSUMPTIONS.md · AI_MISTAKES.md · model_comparison.md · facts.md · corpus_profile.md
samples/          top-10 CSV and ranking report from the full run
scripts/          profile_corpus.py
```

## AI tools used

Claude Code as a pair programmer (scaffolding, tests, first drafts of docs and the gold set,
reviewed and edited by me) and Gemini 3.5 Flash / 3 Flash / 3.1 Flash-Lite via LiteLLM inside
the tool. Where the AI got it wrong, and what I changed, is logged in `docs/AI_MISTAKES.md`.
