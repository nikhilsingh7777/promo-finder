# Assumptions

Record each assumption where the brief is silent: what you assumed, why, and how it affects output.

| # | Assumption | Why | Effect |
|---|---|---|---|
| 1 | Timestamps are episode-absolute (they do not restart per scene) | Later scenes start at e.g. 00:13.80 in the profile | A promo can span scenes as one time range |
| 2 | `LADY X` and `X` are the same person only when both labels exist | JULIANA/LADY JULIANA, CLARISSA/LADY CLARISSA; but LADY vs LORD ASHCROFT differ | Automatic merge is safe; descriptive aliases go to config/roster_overrides.yaml |
| 3 | LADY IN GOLD GOWN = CLARISSA, THE FORMER GROOM = GERALD, NOBLE MATRIARCH = MATRIARCH | Checked by reading Episodes 1 and 3 | Same character keeps one name across episodes |
| 4 | Events slightly outside their scene's bounds are kept, with a warning | Only 1 case (Ep 22, 0.3 s over); likely an authoring slip | No data lost |
| 5 | Episodes can be 70-200 s, not only 60-120 s | Measured in corpus profile | Promo length limits stay 20-60 s regardless |
| 6 | A promo may end exactly at the episode's end | The episode's own ending is written as a cliffhanger | Flagged as a warning, not rejected; the judge decides if it lands |
| 7 | Gold promos for evaluation were drafted by Claude from transcripts only (blind to the tool's picks) and reviewed by me | Time limit; an independent model avoids grading Gemini with Gemini | Gold is one editor's taste, 8 episodes: a small, subjective sample; treat metrics as indicative |
