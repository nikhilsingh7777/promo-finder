# Where AI tools got it wrong

| Date | Tool / model | What went wrong | How it was caught | Fix |
|---|---|---|---|---|
| 2026-11-06 | Claude (writing config.yaml) | Set the default model to `gemini/gemini-2.5-flash` from memory; the API returned 404: no longer available to new users | First real run crashed on the first call | Switched to `gemini-3.8-flash` (named in Google's error); added `models` command + a preflight call so a bad model name fails in 1 s with a clear message |
| 2026-11-06 | Claude (llm.py v1) | No request timeout and silent retries: when gemini-3.8-flash was overloaded the run sat for 7 min with no output | Watched the run; no call ever reached the log | Added 90 s timeout, visible retry messages, a model fallback chain in config.yaml and a `ping` command |
| 2026-11-06 | gemini-3.5-flash (proposer) | In 3 of 7 test candidates the hook_event_id was a CAMERA shot and the hook description described a later line (e.g. E03-C1 mentions a ring that appears seconds later) | Read outputs/test3/candidates_summary.md by hand | New hard rule: hook must be a SAY/ACT/SFX event; prompt now says the description must describe that exact line |
| 2026-11-06 | Claude (llm.py fallback edit) | While shortening the fallback loop it deleted the `continue`, so a failed model fell through to the success path: `UnboundLocalError: usage` crashed the 10-episode run at ep 7 on a 429 | Real run crash on the first rate-limit | Restored `continue`, added a regression test that a failing first model hands over to the next |
