# Failure analysis: where the tool picks badly (full run, 50 episodes)

Numbers come from `eval/results/eval_results.json`, `eval/results/failures.md` (auto-generated)
and `outputs/full/`. Gold = 8 hand-picked promos (eps 5, 9, 12, 20, 28, 35, 42, 49), drafted
blind to the tool's picks; a small, subjective sample, so treat it as indicative.

## Headline

| vs gold (8 episodes) | LLM pipeline | No-LLM baseline |
|---|---|---|
| Found the gold moment (overlap >= 0.5) | **6 / 8** | 4 / 8 |
| Gold moment is the tool's #1 pick in that episode | **4 / 8** | 0 / 8 |
| Mean overlap with gold | **0.68** | 0.43 |
| Mean end-point error | **4.8 s** | 19.3 s |
| Mean start-point error | 9.8 s | 11.5 s |

Every final promo passes the hard rules (30 / 30, 0 violations); 95 of 102 candidates were
valid, 7 rejected after 2 repairs.

## Failure patterns (most important first)

1. **Clip shows its own answer (22 of 95 valid clips, judge flag).** The proposer often runs
   past the cliffhanger into the resolution: E02-C3 includes the end of Juliana's speech,
   E03-C3 shows the proposal itself, E05-C2 shows the husband comforting her. Three of these
   still made the top 30 (#26 E04-C3, #27 E13-C2) because the penalty (0.10) is small.
   Fix: stronger penalty, or let code trim the clip back to the cliffhanger event.
2. **Starts too early (mean start error 9.8 s vs 4.8 s at the end).** The tool opens on
   set-up instead of the shock: E35 (tool starts 30 s late on a different beat, overlap 0.26),
   E42 starts on the 10 s entrance shot instead of "Who are you?", E09's #1 pick opens on a
   door knock. Ends are reliable because the cliffhanger rule anchors them; starts have only
   the "hook within 3 s" rule, which a weak first line still passes.
3. **Weak hooks pass the rules (17 clips judged hook <= 2/5).** E06-C1 opens on "I know this
   is not the life you came from."; E22-C2 on "Prudence." The 3-second rule checks position,
   not strength.
4. **Right moment, wrong rank inside the episode.** E28: the gold moment was found but ranked
   3rd of 3 (tool preferred later beats); E09 and E20 gold matches ranked 2nd.
5. **Lite proposer is weaker (episodes 26-50, free-tier quota).** Ep 26 got no valid promo;
   7 of 48 lite candidates failed the rules vs 0 of 54 strong. On gold, strong-model episodes
   averaged 0.84 overlap (eps 5, 9, 12, 20) vs 0.52 for lite episodes (28, 35, 42, 49); n=4 each.
6. **The judge may favour its own model.** The judge is the lite model. It scored lite
   proposals higher (hook 3.49 vs 3.39, cliffhanger 3.71 vs 3.19) even though they fit the
   gold less well and break rules more. 4 of the final top 10 are lite-proposed. Likely
   self-preference bias; a stronger, different judge is a config change.
7. **Context-heavy late episodes confuse a cold viewer.** 3 of 95 failed the blind test, all
   late-series (E38-C1/C2: wedding + prisoner, E48-C1: "healer's crown"). Late episodes lean
   on plot the stranger does not know.
8. **Spoilers.** E16-C1/C2 reveal the mastermind, E42 reveals the Duke. The judge flags them
   (spoiler 2), the ranking penalises them, the editor note says post them later.

## What the script-only input cannot judge

A slap or a look exists only if the script describes it; we cannot measure acting, pacing or
music. Hooks that are visual in the real cut may be under-rated here.

## What I would change next (in order)

1. Trim-to-cliffhanger in code (fixes pattern 1 without new LLM calls).
2. A "hook strength" pass that moves the start to the strongest line in the first 10 s.
3. Use a strong model as judge (removes the self-preference doubt).
4. Run all episodes on the strong proposer (quota, not code).
5. Calibrate on real post performance (views, 3-s hold rate) once promos are published.
