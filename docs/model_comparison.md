# Model comparison: same episodes, two proposer models (2026-11-06)

Both runs use the same prompts, validator and rules. Rule checks are done by code, so the
validity numbers are objective. Judge scores are NOT comparable across the two runs
(run `ten` was judged by gemini-3.5-flash, run `ten2` by gemini-3.1-flash-lite).

| | gemini-3.5-flash (run `ten`, eps 1-6) | gemini-3.1-flash-lite (run `ten2`, eps 1-10) |
|---|---|---|
| Candidates proposed | 15 | 21 |
| Valid after repair | 15 (100%) | 14 (67%) |
| Valid on first try | 14 (93%) | 8 (38%) |
| Avg valid duration | 41.3 s | 31.6 s |
| Output tokens per propose call | ~3,400-8,800 (reasoning) | ~300-700 |
| Seconds per propose call | 25-68 | 2-20 |

Most common lite failures: overlapping segments (4), clip far too long (80 s, 2),
hook not in the first 3 s, camera shot used as the hook.

Takeaway: the lite model is ~3x faster and cheaper but breaks the hard rules far more often;
the validator + repair loop catches every violation, so bad clips never reach the ranking,
but fewer good candidates survive. Use the stronger model to propose; the lite model is
fine for the blind-viewer test.
