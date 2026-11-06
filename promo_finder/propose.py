"""Stage S4-S6: propose candidates per episode (LLM), validate (code), repair (LLM)."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from .context import episode_header, roster_text, story_so_far
from .llm import LLMClient, LLMError
from .models import Candidate, Episode, ProposalResponse, ProposedCandidate
from .normalize import render_transcript
from .validate import validate

console = Console()
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"


def rule_vars(rules: dict) -> dict:
    """Rule numbers shown to the LLM come from config.yaml, same as the ones code enforces."""
    fmt = lambda x: f"{x:g}"  # noqa: E731
    return {"target_min": fmt(rules["target_min_s"]), "target_max": fmt(rules["target_max_s"]),
            "min_dur": fmt(rules["min_duration_s"]), "max_dur": fmt(rules["max_duration_s"]),
            "hook_window": fmt(rules["hook_window_s"]),
            "cliff_tail": fmt(rules["cliff_tail_max_s"])}


def load_prompt(name: str, **vars) -> str:
    text = (PROMPTS / name).read_text(encoding="utf-8")
    for k, v in vars.items():
        text = text.replace("{{" + k + "}}", str(v))
    return text


def propose_episode(ep: Episode, episodes: dict[int, Episode], roster: list[dict],
                    llm: LLMClient, cfg: dict) -> list[Candidate]:
    rules, gen = cfg["promo_rules"], cfg["generation"]
    system = load_prompt("proposer_v1.md", max_candidates=gen["max_candidates_per_episode"],
                         **rule_vars(rules))
    transcript = render_transcript(ep)
    user = (f"CHARACTERS (canonical name and other labels used for them):\n"
            f"{roster_text(roster)}\n\nSTORY SO FAR:\n"
            f"{story_so_far(episodes, ep.number, gen['context_prev_episodes'])}\n\n"
            f"THIS EPISODE:\n{episode_header(ep)}\n\nTRANSCRIPT:\n{transcript}")
    try:
        resp = llm.json_call("proposer", system, user, ProposalResponse,
                             tag=f"propose:ep{ep.number}")
    except LLMError as e:
        console.print(f"[red]ep {ep.number}: proposer failed: {e}[/red]")
        return []
    used = llm.last_model
    out = []
    for i, pc in enumerate(resp.candidates[: gen["max_candidates_per_episode"]], 1):
        cand = Candidate(id=f"E{ep.number:02d}-C{i}", episodes=[ep.number], proposal=pc,
                         proposer_model=used)
        validate(cand, episodes, rules)
        cand = repair_loop(cand, ep, episodes, transcript, llm, cfg)
        out.append(cand)
    return out


def repair_loop(cand: Candidate, ep: Episode, episodes: dict[int, Episode], transcript: str,
                llm: LLMClient, cfg: dict) -> Candidate:
    rules = cfg["promo_rules"]
    system = load_prompt("repair_v1.md", **rule_vars(rules))
    for attempt in range(1, cfg["generation"]["repair_attempts"] + 1):
        if cand.validation and cand.validation.passed:
            break
        errs = cand.validation.errors if cand.validation else ["not validated"]
        cand.history.append({"attempt": attempt - 1, "proposal": cand.proposal.model_dump(),
                             "duration": cand.validation.duration if cand.validation else None,
                             "errors": errs})
        user = ("CANDIDATE:\n" + cand.proposal.model_dump_json(indent=1) +
                f"\n\nMEASURED BY CODE: total duration {cand.validation.duration:.1f} s"
                "\nERRORS:\n- " + "\n- ".join(errs) + f"\n\nTRANSCRIPT:\n{transcript}")
        try:
            fixed = llm.json_call("proposer", system, user, ProposedCandidate,
                                  temperature=0.0, tag=f"repair:{cand.id}#{attempt}")
        except LLMError as e:
            cand.history.append({"attempt": attempt, "llm_error": str(e)})
            break
        cand.proposal = fixed
        cand.repair_attempts = attempt
        validate(cand, episodes, rules)
    return cand
