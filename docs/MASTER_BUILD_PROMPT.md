# MASTER BUILD PROMPT: Kuku "Find the Promos" (Problem 1)

> Paste this whole file into Claude Code (Plan Mode first) inside an EMPTY project folder.
> Put the 50 episode .txt files in `data/episodes/` (git-ignored; confidential Kuku content).
> Work in the PHASES in section 15. STOP at each checkpoint and wait for my "go".

---

## 0. ROLE AND WORKING STYLE

You are a senior engineer pair-programming with me. I am a full-stack SDE doing my first AI/LLM-pipeline project, and I must be able to **explain every design decision in an interview and re-run the tool live on a new, unseen episode file**. So:

- Prefer simple, readable code over clever code. Small modules, type hints, short docstrings explaining *why*.
- Before each phase, state the plan in 5-10 lines. After each phase, list what you built, what you tested, what is still weak.
- Never silently guess. If something in the data surprises you, report it, make a sensible assumption, and record it in `docs/ASSUMPTIONS.md`.
- Keep a running `docs/AI_MISTAKES.md`: every time generated code or an LLM output was wrong and had to be fixed (bug, hallucinated timestamp, bad parse, wrong assumption), log what happened and how it was caught. The assignment requires "one place where AI tools got it wrong", so be honest and specific.
- Do not add frameworks I do not need (no LangChain/CrewAI/LangGraph). Plain Python + a thin LLM wrapper.

---

## 1. THE ASSIGNMENT (what is being judged)

Company: Kuku (microdrama studio). Shows are vertical, 1-2 minute episodes. I chose **Problem 1: Find the Promos**.

**Task:** Build a tool that reads microdrama screenplays and finds the best promos.

**What a promo is:** a **20-60 second** clip taken from the show, posted to Instagram/TikTok/YouTube to pull in new viewers. Usually one continuous stretch, but it may **join several moments** from one episode or across several. A good promo:
1. **Opens on a hook** within the first **3 seconds** (slap, reveal, shocking line) that stops a scrolling viewer.
2. **Ends on a cliffhanger**: cuts at an unresolved moment, so the viewer needs to know what happens next.
3. **Makes sense on its own** to someone who has never seen the show.

Only FIND promos: the right moments and exact start/end points. No editing, music, or overlays.

**Required output per promo:** episode number; start and end timestamp of **every segment, in order**; the hook; the cliffhanger; one line on why it works.
**Plus:** a **ranking** (which to post first and why), and a **quality check** ("where does your tool pick badly?").

**Judging lenses:** (1) problem framing and assumptions; (2) approach and scale: what goes to AI vs plain code/rules, where a human stays in the loop, cost at real volume; (3) quality checking with real runs and honest failures; (4) prototype runs on real inputs and gives usable output; (5) clear, short communication.

**Practical constraints:**
- Free tiers only. If a paid model would be better, document how I'd use it and make the model swappable.
- Interviewers will run my tool on a **new input** and may plug in **stronger models via an API they provide**, so the model/provider must be swappable by config only.
- Confidential input pack: never commit episodes, never embed them in the deployed app, never publish them.
- Deliverables: 2-page PDF solution doc (I write it), prototype link (repo and/or hosted app), a folder of **unedited raw outputs** from running on the **full 50 episodes**, optional 3-minute walkthrough video.
- The brief gives no spec and answers no questions: make assumptions and document them.

---

## 2. INPUT FORMAT (observed in Episode 1; the other 49 may vary, so PROFILE FIRST)

Episodes are ~2 minutes (Episode 1 runs 00:00.00 to 02:18.00). Structure:

```
EPISODE NUMBER: Episode 1
EPISODE LOGLINE: <one sentence summary>
CONTINUITY NOTES: <what this episode establishes>

--- SCRIPT START ---

SCENE 01
Scene heading: INT. CATHEDRAL – DAY
Scene start: 00:00.00
Scene end: 02:18.00

Actions and dialogue:

**CAMERA:**
Start: (00:00.00) | End: (00:04.80)
<shot description>

**ACTION:**
Start: (00:01.00) | End: (00:04.80)
<what happens>

**LADY JULIANA (Confused, Breathless):**
Start: (00:13.50) | End: (00:14.30)
"Why?"

**MATRIARCH (O.S.) (Firm):**
...
**SOUND FX:**
...
--- SCRIPT END ---
```

**Known gotchas (design for them):**
1. Time format is `mm:ss.ss` (support `hh:mm:ss.ss` and `ss.s` too). Parse to float seconds.
2. **Parallel tracks overlap in time**: CAMERA blocks run alongside ACTION/dialogue. Do not assume events are sequential or disjoint.
3. Speaker labels are role descriptions, not names, and change meaning over the story: `LADY JULIANA`, `MATRIARCH`, `LADY IN GOLD GOWN` (= sister Clarissa, named only inside another character's line), `THE FORMER GROOM` (= Gerald). Need **alias resolution** (character roster per show) so the model and judges know who is who.
4. Header modifiers can stack: `NAME (O.S.) (Firm)`, `NAME (V.O.)`. Parse speaker, modifiers, emotion tag separately.
5. Multiple scenes per episode, each with its own start/end. Check that event times fall inside scene bounds.
6. Dialogue is quoted text; one speaker may have consecutive lines (continuations).
7. Possible data errors: missing Start/End, end < start, overlaps, text with odd quotes or unicode dashes, missing sections, blank logline. Never crash: emit `warnings` and continue.
8. The header `LOGLINE` and `CONTINUITY NOTES` are free, structured summaries. Use them as the "story so far" memory instead of extra LLM summarisation calls.
9. Scripts only: there is NO video or audio. Visual hooks (a slap) exist only if the ACTION/CAMERA text says so. This is a core limitation to document.

---

## 3. KEY DESIGN PRINCIPLE: LLMs PICK, CODE MEASURES

LLMs hallucinate timestamps and miscount durations. Therefore:

- The LLM never writes raw timestamps. It chooses **event IDs** (`start_event_id`, `end_event_id`, `hook_event_id`) from a transcript where every line carries a stable ID.
- **Code** converts IDs to timestamps, computes durations, snaps boundaries, enforces all hard rules, and rejects/repairs bad candidates.
- The LLM judges *taste* (hook strength, cliffhanger quality, clarity). Code judges *facts* (duration, ordering, boundaries, overlap).
- Any claim in the output ("hook", "cliffhanger") must quote or reference real event IDs, so it can be verified programmatically.

---

## 4. PIPELINE (stages)

```
episodes/*.txt
  -> S1 Parse -> S2 Normalize + event IDs + character roster
  -> S3 Show context (loglines + continuity notes)
  -> S4 Propose candidates (LLM, per episode)
  -> S5 Validate + snap (code) -> S6 Repair loop (LLM, max 2 tries)
  -> S7 Judge: rubric score + blind-viewer standalone test (LLM, different model if possible)
  -> S8 Cross-episode composer (LLM, optional multi-segment promos)
  -> S9 Dedupe + rank (code score + LLM editor note on top-K)
  -> S10 Reports + raw-output folder
```

### S0. Corpus profiler (do this BEFORE writing the parser)
Script `scripts/profile_corpus.py` scans all 50 files and prints: files found; per-file header presence; scene counts; block types and counts; time-format variants; speaker-label vocabulary (top 50, with counts); episode durations; events with end<start; events outside scene bounds; files that fail the strict parser. Show me the report and propose parser rules before building it.

### S1. Parser (`parse.py`), pure Python, no LLM
Regex/state-machine parser to the `Episode` model. Strict-but-tolerant: unknown blocks kept as `UNKNOWN` with a warning. Unit tests on Episode 1 plus synthetic broken fixtures.

### S2. Normalizer (`normalize.py`)
- Event IDs: `E{ep:02d}-S{scene:02d}-{n:03d}`, ordered by (start, original order).
- Types: DIALOGUE, ACTION, CAMERA, SOUND.
- Character roster: collect speaker labels per show; ONE cheap LLM call (cached) proposes `alias -> canonical name + one-line role` using the labels plus loglines/continuity notes of the first ~5 episodes; I can override via `config/roster_overrides.yaml`. Output `show_bible.json`.
- Render LLM-ready transcript, one line per event, with IDs and times, e.g.
  `[E01-S01-014] 00:13.50-00:14.30 DIALOGUE LADY JULIANA (Confused, Breathless): "Why?"`
  `[E01-S01-021] 00:25.60-00:29.80 ACTION: Juliana walks forward ...`
  CAMERA/SOUND lines are included in compact form (`CAM`, `SFX`), because they carry the visual information.
- Fallback format-adapter (optional, flagged in output): if strict parsing fails on a new-format file, ask the LLM to convert it to the canonical schema, then validate with the same code checks.

### S3. Show context
Per episode, pass the proposer: the show bible, loglines + continuity notes of the previous 3-5 episodes, and this episode's header. Cheap, deterministic, no extra summarisation calls.

### S4. Proposer (LLM, one call per episode, structured JSON via Pydantic schema)
Returns up to `max_candidates_per_episode` (default 3) candidates:
```
segments: [{start_event_id, end_event_id}]   # 1-3 segments, in story order
hook_event_id, hook_description
cliffhanger_event_id, cliffhanger_description, unresolved_question
why_it_works (one line)
confidence 0-1
```
Rules in the prompt: see section 9. Candidates may span scenes. Multi-segment candidates are allowed only if the joined cut still makes sense; prefer one continuous stretch.

### S5. Validator + snapper (`validate.py`), code only, deterministic
Hard rules (fail = reject or send to repair):
- R1 total duration = sum of (segment_end - segment_start) within **[20, 60]** s. Configure a safe target band (default 28-56 s) and mark candidates outside it as "edge".
- R2 segments non-overlapping and in story order (episode, then time).
- R3 every segment boundary falls on event boundaries; **never cut a dialogue line mid-way**. Start = start of first event minus lead-in (<=0.3 s, never into the previous event). End = end of last event plus tail (<=0.4 s, never into the next event).
- R4 **hook rule**: the hook event must START within 3.0 s of the promo start. First 3 s must contain dialogue or meaningful ACTION (not a pure establishing shot).
- R5 **cliffhanger rule**: the final event must not be a resolution. Check: the final event is not the last event of the episode, OR it is the episode's own cliffhanger ending (flag which). Also store the 2-3 events that follow the cut so the judge can verify the answer comes AFTER the promo.
- R6 all referenced IDs exist; segment count <=3 (config); no empty segments.
- R7 no cross-promo overlap (see S9).
Soft warnings: first-3-s silence, a segment <3 s, speaker introduced only by role label with no roster alias, heavy reliance on context from earlier episodes.

### S6. Repair loop
For candidates failing a hard rule, send back the candidate plus a precise error list ("duration 71.2 s, must be 20-60"; "hook starts at 5.4 s"), allow <=2 repairs, then drop and log. Record every attempt in the raw logs.

### S7. Judge (LLM, separate prompt, ideally a different model from the proposer)
1. **Rubric scoring**, integers 1-5 with written anchors: `hook_strength`, `cliffhanger_strength`, `standalone_clarity`, `emotional_intensity`, `shareability`, and `spoiler_risk` (0 none / 1 minor / 2 reveals a major twist; judged against the loglines).
2. **Blind-viewer test**: a SECOND call that sees ONLY the promo transcript (no logline, no bible, no other episodes) and answers: who are the 2-3 main people and relationship; what is the conflict; what is confusing; what do you most want to know next. Output `standalone_pass` (bool), `confusions[]`, `fixable_with_context_segment` (bool and which earlier event ids would fix it).
3. Do not let the judge write timestamps. It scores and explains with event IDs.

### S8. Cross-episode composer (stretch, but the brief mentions it)
Input: top moments per episode (candidates that scored high on hook/cliffhanger but low on standalone), plus loglines. Output: 2-3-segment promos that prepend a short "context" segment (2-8 s) from an earlier moment/episode to a strong hook/cliffhanger. Same validator and judge apply. Flag clearly as `type: composed`.

### S9. Dedupe + ranking
- Dedupe: temporal IoU > 0.3 within an episode -> keep the higher score.
- Composite score in code (weights in `config.yaml`): hook 0.30, cliffhanger 0.25, standalone 0.20, emotional/shareability 0.15, spoiler-safety 0.10; penalty if validator "edge" or warnings; small diversity penalty so the top 10 are not all from one scene/episode; mild preference for early episodes as the "first-impression" promos (document this as an assumption, not a fact).
- Final list: keep top `final_n` (default 30) plus the full candidate pool in a separate file.
- **LLM editor note** for the top 10 only: one listwise call that sees the top-K candidates' transcripts + scores and writes "why this should be posted first" and a recommended posting order. Keep numeric ranking from code authoritative; show where the editor note disagrees.

### S10. Reports (see section 13).

---

## 5. DATA MODELS (Pydantic v2)

`Event(id, ep, scene, type, speaker, speaker_canonical, modifiers[], emotion, text, start, end, source_line)`
`Scene(index, heading, start, end, events[])`
`Episode(number, logline, continuity, duration, scenes[], warnings[])`
`Segment(ep, start_event_id, end_event_id, start, end)`
`Candidate(id, type[single|multi|composed], segments[], hook{event_id,text,description}, cliffhanger{event_id,text,description,unresolved_question}, why, proposer_confidence, validator{passed,errors[],warnings[],duration,edge}, scores{...}, blind_test{...}, composite, rank)`
`RunManifest(run_id, timestamp, config_hash, models, prompt_versions, git_commit, token_counts, cost_estimate, wall_time, episodes_parsed, episodes_failed)`

---

## 6. LLM LAYER (`llm.py`), SWAPPABLE BY CONFIG

- Use **LiteLLM** (OpenAI-compatible interface across providers) so the interviewer can set a different `model` and `api_base`/key through env vars or the UI with **zero code changes**.
- All model names live in `config.yaml` (roles: `proposer`, `judge`, `blind_viewer`, `roster`, `editor`) and can be overridden by CLI `--model` and env. NO model names hard-coded. Verify current free-tier model IDs from provider docs; do not assume.
- Structured output: request JSON matching the Pydantic schema; on parse failure retry once with the error message; log both.
- temperature=0 (judge) and low (proposer). Seed where supported.
- Disk cache keyed by hash(provider, model, prompt_version, input) so re-runs are free and reproducible.
- Retries with exponential backoff, a token-bucket rate limiter (free tiers are rate-limited), concurrency limit, resumable runs (skip episodes already done).
- Log every raw request/response and token usage to `outputs/<run>/llm_raw/`. Compute a cost estimate from a small price table in config (free tier = 0, but also show the "what it would cost on paid pricing" number).
- `--no-llm` mode: a heuristic baseline (high-emotion tags, short punchy lines, reveals/questions/exclamations, action verbs like slap/gasp/reveal, ends before the episode's resolution). It serves as (a) a demo when no key is available and (b) a **baseline to beat** in the evaluation.

---

## 7. HUMAN IN THE LOOP

Streamlit "Review" tab: for each promo an editor can Approve / Reject / Nudge start-end to neighbouring events / add a note. Save to `feedback/feedback.jsonl`. Feedback is used (a) as gold labels for evaluation and (b) as few-shot examples for the proposer prompt (`prompts/fewshot.jsonl`). Document this loop in the doc as the scale story: the editor reviews a ranked shortlist of ~30 per show rather than watching 50 episodes.

---

## 8. SCALE AND COST (must be measured, not guessed)

Instrument and report: tokens per episode, calls per episode, seconds per episode, estimated cost per show at paid pricing, projection for N shows/week. Design for scale: stateless per-episode workers, cache, async concurrency, tiered models (cheap model for proposing; stronger model only for judging top-K), resumable runs, batch APIs where available. State honestly what the free tier limits you to.

---

## 9. RUNTIME LLM PROMPTS (draft; store as versioned files in `prompts/`, e.g. `proposer_v1.md`)

### 9.1 Proposer system prompt
```
You are a short-form video editor for vertical microdramas (ReelShort / DramaBox style).
You receive a time-coded screenplay where every line has an ID like [E05-S02-014].
Find up to {N} promo candidates: 20-60 seconds total, posted to TikTok/Reels/Shorts to win NEW viewers.

A promo must:
1. HOOK: its first event is a striking moment (a slap, a reveal, a threat, a shocking or cruel line, a sudden reversal). Not an establishing shot, greeting, or exposition.
2. CLIFFHANGER: it ends right BEFORE the answer or consequence, leaving a question the viewer must see answered. Never end after a resolution.
3. STAND ALONE: a stranger who knows nothing else can tell who the main people are, the relationship, and the conflict from the promo alone. Prefer one continuous stretch. Use a 2nd/3rd segment only to add essential context.

Hard constraints: choose segments only by event IDs. Do NOT write timestamps. Estimate total length from the times shown and stay within 25-55 s. Start at the first event of the hook; end at the last event before the unresolved question gets answered. Never start or end mid-line. Do not reveal the show's biggest twists (check the loglines).

Return ONLY JSON matching the schema. For each candidate give: segments[{start_event_id,end_event_id}], hook_event_id, hook_description, cliffhanger_event_id, cliffhanger_description, unresolved_question, why_it_works (one sentence), confidence 0-1. If the episode has no good promo, return fewer or none; do not pad.
```
User message: show bible (roster), previous episodes' loglines/continuity, this episode header, the ID'd transcript.

### 9.2 Repair prompt
Gives the failing candidate + exact validator errors + the transcript; asks for a corrected candidate only (same schema), changing as little as possible.

### 9.3 Judge prompt
```
You are a strict social-video growth analyst. Score each promo candidate from the transcript excerpt shown.
Anchors (integers):
hook_strength: 1 = nothing happens in the first 3 s; 3 = interesting but expected; 5 = unmistakable stop-the-scroll shock/reveal/slap/line.
cliffhanger_strength: 1 = resolved or fizzles; 3 = open question but low stakes; 5 = cut at peak tension, the viewer NEEDS the answer.
standalone_clarity: 1 = needs prior episodes; 5 = anyone gets who/what/why immediately.
emotional_intensity, shareability: 1-5 with the same style of anchors.
spoiler_risk: 0 none, 1 minor, 2 gives away a major twist (use loglines).
You are shown the 2-3 events AFTER the cut: confirm the answer is not inside the promo.
Be harsh: most clips deserve 2-3. Output JSON with scores and one-sentence reasons that cite event IDs.
```

### 9.4 Blind-viewer prompt
```
You have NEVER seen this show. Below is a short clip transcript. Answer in JSON:
who are the 2-3 main people and how are they related; what is the conflict;
what, if anything, confused you; what do you most want to see next;
would you keep watching (yes/no) and why in one line.
```
(No logline, no roster, no other episodes are given to this call. That is the point.)

### 9.5 Editor-note prompt (top-K only)
Listwise: given K promos with scores and transcripts, recommend posting order and one sentence each on why it should go first/later; call out near-duplicates and spoiler risks.

---

## 10. EVALUATION HARNESS (`eval/`): this is a main scoring area

1. **Deterministic checks (must be 100%)**: all final promos pass R1-R6; zero mid-line cuts; every cited event ID exists. Report the pass rate BEFORE and AFTER the repair loop.
2. **Gold set**: I will hand-label promos for ~8-10 episodes spread across the series in `eval/gold.yaml` (episode, start, end, hook line). Build the metrics script: hit@k (candidate overlaps a gold promo with temporal IoU >= 0.5), hook-line agreement, mean boundary error in seconds. Compare **LLM pipeline vs heuristic baseline**.
3. **Judge sanity**: score 30 random 20-60 s windows with the same judge and show that selected promos score clearly higher than random windows (negative control). Also compare judge scores to my own scores on ~20 promos (correlation, biggest disagreements).
4. **Stability**: run twice (and with a second model if possible); report overlap of final picks (Jaccard) and rank correlation.
5. **Blind-viewer**: % of final promos passing standalone; list the common confusions.
6. **Failure log** (`eval/failures.md`, auto-seeded then I annotate): the 10 worst picks among the top 30, lowest-scored candidates that still survived, validator vs judge disagreements, model-vs-model disagreements, episodes with zero promos. For each: what went wrong and the likely reason (e.g. script-only so the hook is not visually visible; context-dependent reveal; repeated pattern across similar episodes; wrong cliffhanger because resolution is in the next episode).
7. Never tune on the gold episodes and then report them as clean evaluation. Keep a held-out split.

---

## 11. INTERFACES

**CLI** (`python -m promo_finder ...`):
`profile`, `run --input <dir|file> --out outputs/ [--model ...] [--no-llm] [--episodes 1-10] [--resume]`, `evaluate --gold eval/gold.yaml`, `report`.
A single new episode file must run end to end in about two minutes.

**Streamlit app** (`app.py`), simple and clean:
- Sidebar: provider / model / API key (session only, never stored, BYO key so my free key is not burnt), thresholds, run button.
- Input: upload episode .txt files (hosted) or folder path (local).
- Tabs: **Ranked promos** (table with episode, segments, duration, scores, badges); **Promo detail** (transcript with highlighted segments, hook/cliffhanger/why, blind-viewer result, validator result); **Review** (approve/reject/nudge); **Run stats** (tokens, cost, time, warnings); **Failures**.
- Export CSV / JSON / Markdown.
- Must deploy on Streamlit Community Cloud or HF Spaces WITHOUT any Kuku episodes in the repo. Include one tiny self-written fake episode in `samples/` for demo.

---

## 12. REPO STRUCTURE

```
promo-finder/
  README.md            # 5-line quickstart, exact run steps, model swap, known limits
  config.yaml  config/roster_overrides.yaml
  prompts/             # versioned prompt files + fewshot.jsonl
  promo_finder/        # parse.py normalize.py context.py propose.py validate.py repair.py
                       # judge.py compose.py rank.py report.py llm.py models.py cli.py
  app.py
  scripts/profile_corpus.py
  eval/                # gold.yaml, run_eval.py, failures.md
  tests/               # parse, validate, snapping, hook/cliffhanger rules, ranking
  samples/             # fake episode only
  data/episodes/       # gitignored (real episodes)
  outputs/             # gitignored; the raw-output folder is delivered separately
  docs/                # ASSUMPTIONS.md AI_MISTAKES.md facts.md
  .gitignore           # data/, outputs/, .env, cache/, feedback/
```

---

## 13. OUTPUTS (the "raw outputs" folder: UNEDITED, produced by one command)

`outputs/<run_id>/`
- `promos_ranked.csv` and `promos_ranked.json`: rank, promo_id, type, episode(s), **segments with start-end for each (mm:ss.s)**, total duration, hook (quote + event id), cliffhanger (quote + event id), why it works, scores, composite, validator status, blind-test result.
- `ranking_report.md`: top 10 with editor-note rationale, then the remaining list.
- `candidates_all.json`: the full pool including rejected ones with reasons.
- `parsed/ep_XX.json`, `validation_report.json` (all parse warnings).
- `llm_raw/`: every raw prompt/response.
- `run_manifest.json`, `cost.json`.
Do not hand-edit anything in this folder. If something is wrong, fix the code and re-run.

---

## 14. FACTS FILE FOR MY 2-PAGE DOC

Auto-generate `docs/facts.md` containing ONLY facts and numbers (no prose I might copy blindly): episodes parsed, anomalies found, calls and tokens per episode, cost/time per show, validator pass rate before/after repair, eval metrics vs baseline, stability numbers, blind-test pass rate, top 5 failures with episode and event IDs, list of assumptions, list of AI mistakes. I will write the PDF myself from this.

---

## 15. PHASES AND CHECKPOINTS (stop after each; wait for my approval)

1. **Scaffold + profile**: repo, config, `.gitignore`, `profile_corpus.py`; show me the corpus report and your proposed parser rules. CHECKPOINT.
2. **Parser + normalizer + tests**: all 50 files parse with warnings listed; Episode 1 golden test. CHECKPOINT.
3. **LLM layer + proposer + validator + repair**, on 3 episodes first; show raw candidates and validator results. CHECKPOINT.
4. **Judge + blind-viewer + ranking + `--no-llm` baseline**; run on 10 episodes; I review picks by eye. CHECKPOINT.
5. **Full 50-episode run**, cost/time measured, reports generated. CHECKPOINT.
6. **Evaluation harness** + failure log (I provide gold labels). CHECKPOINT.
7. **Streamlit app + review loop + CLI polish + README**, deploy-ready, model-swap demo. CHECKPOINT.
8. **Composer (cross-episode)** only if time remains. Then `docs/facts.md`.

---

## 16. QUALITY BAR AND DON'TS

- Every hard rule is enforced by code and covered by a unit test. No LLM output is trusted for time or duration.
- Do not invent episode content in tests; use Episode 1 and synthetic fixtures.
- Do not claim accuracy you did not measure. If a number is from a small sample, say so in the report.
- Do not overfit prompts to Episode 1. Keep prompts generic for any microdrama, any language style.
- Never print or commit API keys. Provide `.env.example`.
- If the run hits free-tier rate limits, degrade gracefully (queue, resume), never fail silently.
- Prefer a smaller thing that works end to end over a bigger one that half works.

## 17. ACCEPTANCE CHECKLIST (final)

- [ ] `python -m promo_finder run --input data/episodes --out outputs/` runs all 50 episodes, resumable.
- [ ] A brand-new single episode file runs in about 2 minutes with a different `--model` and no code change.
- [ ] 100% of final promos satisfy duration 20-60 s, valid ordering, hook within 3 s, no mid-line cuts.
- [ ] Ranked CSV/JSON/MD present; each promo has per-segment timestamps, hook, cliffhanger, one-line why.
- [ ] Evaluation vs baseline, stability, blind-viewer results and honest failure log exist.
- [ ] Streamlit app works with BYO key; no episodes in the repo.
- [ ] `docs/ASSUMPTIONS.md`, `docs/AI_MISTAKES.md`, `docs/facts.md` filled.

BEGIN with Phase 1. First, read `data/episodes/`, confirm the file count, and give me the plan for Phase 1 before writing code.
