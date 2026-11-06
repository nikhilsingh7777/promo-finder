# Project rules for Claude

- Spec: `docs/MASTER_BUILD_PROMPT.md`. Follow its phases and stop at each checkpoint.
- `data/`, `outputs/`, `cache/`, `feedback/` and `.env` must never be committed. Check `git status` before every commit.
- Never print, log or commit API keys.
- LLMs choose event IDs; code computes every timestamp and duration.
- No hard-coded model names in code: everything comes from `config.yaml`.
- Keep code simple and explainable. Add tests for every hard rule.
- Log every AI mistake in `docs/AI_MISTAKES.md` and every assumption in `docs/ASSUMPTIONS.md`.
