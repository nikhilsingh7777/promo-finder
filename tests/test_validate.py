"""Hard-rule tests for the validator and the propose->repair loop (fake LLM, no API)."""

import json

import yaml

from promo_finder.llm import LLMClient, extract_json
from promo_finder.models import Candidate, ProposedCandidate
from promo_finder.parse import parse_text
from promo_finder.propose import propose_episode

RULES = yaml.safe_load(open("config.yaml"))["promo_rules"]


def make_episode(n_lines: int = 20, step: float = 5.0):
    """Synthetic episode: alternating CAMERA + dialogue every `step` seconds."""
    parts = ["EPISODE NUMBER: Episode 3", "EPISODE LOGLINE: L.", "CONTINUITY NOTES: C.", "",
             "SCENE 01", "Scene heading: INT. ROOM - DAY", "Scene start: 00:00.00",
             f"Scene end: {int(n_lines * step // 60):02d}:{n_lines * step % 60:05.2f}", ""]
    for i in range(n_lines):
        s = i * step
        mm = lambda t: f"{int(t // 60):02d}:{t % 60:05.2f}"  # noqa: E731
        parts += ["**CAMERA:**", f"Start: ({mm(s)}) | End: ({mm(s + step)})", f"Shot {i}.", "",
                  "**ANNA (Angry):**", f"Start: ({mm(s + 0.5)}) | End: ({mm(s + 3.5)})",
                  f'"Line {i}!"', ""]
    return parse_text("\n".join(parts), "ep3.txt")


EP = make_episode()
EPS = {3: EP}
ID = lambda i: f"E03-S01-{i:03d}"  # noqa: E731   events: cam=2k+1, line=2k+2


def cand(start, end, hook, cliff, segs=None):
    segs = segs or [{"start_event_id": start, "end_event_id": end}]
    return Candidate(id="t", episodes=[3], proposal=ProposedCandidate(
        segments=segs, hook_event_id=hook, cliffhanger_event_id=cliff))


def check(c):
    from promo_finder.validate import validate
    return validate(c, EPS, RULES).validation


def test_valid_promo_passes():
    v = check(cand(ID(2), ID(16), ID(2), ID(16)))      # lines 0..7 -> 0.5 s .. 38.5 s
    assert v.passed, v.errors
    assert 30 <= v.duration <= 40


def test_too_long_is_rejected():
    v = check(cand(ID(2), ID(40), ID(2), ID(40)))
    assert not v.passed and any("total duration" in e for e in v.errors)


def test_too_short_is_rejected():
    v = check(cand(ID(2), ID(4), ID(2), ID(4)))
    assert not v.passed and any("total duration" in e for e in v.errors)


def test_late_hook_is_rejected():
    v = check(cand(ID(2), ID(16), ID(6), ID(16)))      # hook 10 s in
    assert any("hook starts" in e for e in v.errors)


def test_cliffhanger_must_be_at_end():
    v = check(cand(ID(2), ID(16), ID(2), ID(8)))
    assert any("after the cliffhanger" in e for e in v.errors)


def test_unknown_ids_and_overlap():
    v = check(cand(ID(2), "E03-S01-999", ID(2), ID(16)))
    assert any("unknown event" in e for e in v.errors)
    v = check(cand(None, None, ID(2), ID(16), segs=[
        {"start_event_id": ID(2), "end_event_id": ID(10)},
        {"start_event_id": ID(8), "end_event_id": ID(16)}]))
    assert any("overlap" in e for e in v.errors)


def test_boundaries_never_cut_a_line():
    from promo_finder.validate import validate
    c = validate(cand(ID(1), ID(15), ID(2), ID(16)), EPS, RULES)   # ends on a camera mid-line
    seg = c.segments[0]
    for e in EP.events:
        if e.speaker:
            assert not (e.start < seg.start < e.end) and not (e.start < seg.end < e.end)


def test_extract_json_handles_fences():
    assert json.loads(extract_json('sure!\n```json\n{"a": 1}\n```')) == {"a": 1}


def test_repair_loop_fixes_a_too_long_candidate():
    cfg = yaml.safe_load(open("config.yaml"))
    cfg["llm"]["cache_dir"] = None
    bad = {"candidates": [{"segments": [{"start_event_id": ID(2), "end_event_id": ID(40)}],
                           "hook_event_id": ID(2), "cliffhanger_event_id": ID(40)}]}
    good = {"segments": [{"start_event_id": ID(2), "end_event_id": ID(16)}],
            "hook_event_id": ID(2), "cliffhanger_event_id": ID(16), "why_it_works": "x"}
    replies = iter(["not json at all", json.dumps(bad), json.dumps(good)])
    llm = LLMClient(cfg, fake=lambda model, msgs: next(replies))
    cands = propose_episode(EP, EPS, [], llm, cfg)
    assert len(cands) == 1
    c = cands[0]
    assert c.validation.passed and c.repair_attempts == 1
    assert c.history[0]["errors"]                         # failed version kept for the report
    assert llm.usage["errors"] == 1                       # the bad-JSON reply was retried


def test_camera_shot_cannot_be_the_hook():
    v = check(cand(ID(1), ID(16), ID(1), ID(16)))      # ID(1) is a CAMERA event
    assert any("camera shot" in e for e in v.errors)
