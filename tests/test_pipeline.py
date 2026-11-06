"""End-to-end pipeline with a fake LLM: propose -> judge -> blind -> rank -> editor -> reports."""

import json
import re

import yaml

from promo_finder.pipeline import run_pipeline
from tests.test_validate import EP, EPS, ID


def fake_llm(model, messages):
    system, user = messages[0]["content"], messages[-1]["content"]
    ids = re.findall(r"### CLIP (\S+)", user)
    if "strict growth analyst" in system:
        return json.dumps({"scores": [
            {"candidate_id": i, "hook_strength": 5 - k, "cliffhanger_strength": 4,
             "standalone_clarity": 4, "emotional_intensity": 4, "shareability": 3,
             "spoiler_risk": 0, "reason": "test"} for k, i in enumerate(ids)]})
    if "NEVER seen this show" in system:
        return json.dumps({"results": [{"candidate_id": i, "understood": True,
                                        "keep_watching": True} for i in ids]})
    if "social media lead" in system:
        return json.dumps({"order": re.findall(r"### (E\S+) \(rank", user), "notes": {}})
    if "Reply with: ok" in user:
        return "ok"
    return json.dumps({"candidates": [
        {"segments": [{"start_event_id": ID(2), "end_event_id": ID(16)}],
         "hook_event_id": ID(2), "cliffhanger_event_id": ID(16), "why_it_works": "a"},
        {"segments": [{"start_event_id": ID(20), "end_event_id": ID(34)}],
         "hook_event_id": ID(20), "cliffhanger_event_id": ID(34), "why_it_works": "b"}]})


def test_full_pipeline_with_fake_llm(tmp_path, monkeypatch):
    cfg = yaml.safe_load(open("config.yaml"))
    cfg["llm"]["cache_dir"] = None
    import promo_finder.pipeline as pl
    real = pl.LLMClient
    monkeypatch.setattr(pl, "LLMClient", lambda c, log_dir=None: real(c, log_dir, fake=fake_llm))
    ranked = run_pipeline(EPS, [], [EP.number], cfg, tmp_path)
    assert [c.rank for c in ranked] == [1, 2]
    assert ranked[0].scores["hook_strength"] == 5           # higher hook ranks first
    assert ranked[0].blind_test["understood"] is True
    for name in ("promos_ranked.csv", "promos_ranked.json", "ranking_report.md",
                 "candidates_all.json", "run_stats.json"):
        assert (tmp_path / name).exists(), name
    assert "Suggested posting order" in (tmp_path / "ranking_report.md").read_text()
    # resume: second run reads checkpoints and makes no new proposer calls
    again = run_pipeline(EPS, [], [EP.number], cfg, tmp_path)
    assert [c.id for c in again] == [c.id for c in ranked]


def test_baseline_runs_without_llm(tmp_path):
    cfg = yaml.safe_load(open("config.yaml"))
    ranked = run_pipeline(EPS, [], [EP.number], cfg, tmp_path, no_llm=True)
    assert all(c.validation.passed for c in ranked)
