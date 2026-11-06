"""Phase 1: profile the screenplay corpus before writing the parser.

Scans every episode file with deliberately loose regexes and reports
structure, time formats, speaker labels, durations and anomalies.
Usage: python scripts/profile_corpus.py [episodes_dir] [report_path]
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

TIME = r"(\d{1,2}:\d{2}(?:\.\d+)?|\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)"
RE_HEADER = re.compile(r"^(EPISODE NUMBER|EPISODE LOGLINE|CONTINUITY NOTES):\s*(.*)$")
RE_SCENE = re.compile(r"^SCENE\s+(\d+)\s*$", re.I)
RE_SCENE_START = re.compile(rf"^Scene start:\s*{TIME}", re.I)
RE_SCENE_END = re.compile(rf"^Scene end:\s*{TIME}", re.I)
RE_BLOCK = re.compile(r"^\*\*(.+?):?\*\*\s*$")
RE_TIMING = re.compile(rf"^Start:\s*\(\s*{TIME}\s*\)\s*\|\s*End:\s*\(\s*{TIME}\s*\)\s*$")
RE_ANY_TIME = re.compile(r"\d+:\d+(?:\.\d+)?")
TECH = {"CAMERA", "ACTION", "SOUND FX", "SOUND", "SFX", "MUSIC"}


def to_sec(t: str) -> float:
    parts = [float(p) for p in t.split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def speaker_of(label: str) -> tuple[str, list[str]]:
    """'MATRIARCH (O.S.) (Firm)' -> ('MATRIARCH', ['O.S.', 'Firm'])."""
    label = label.rstrip(":").strip()
    mods = re.findall(r"\(([^)]*)\)", label)
    name = re.sub(r"\([^)]*\)", "", label).strip()
    return name, mods


def profile(path: Path) -> dict:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    info = {"file": path.name, "headers": {}, "scenes": [], "blocks": Counter(),
            "speakers": Counter(), "issues": [], "time_formats": Counter(),
            "events": 0, "max_end": 0.0}
    scene = None
    pending_block = None
    for i, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        for t in RE_ANY_TIME.findall(line):
            fmt = re.sub(r"\d", "9", t)
            info["time_formats"][fmt] += 1
        if m := RE_HEADER.match(line):
            info["headers"][m.group(1)] = m.group(2).strip()
        elif m := RE_SCENE.match(line):
            scene = {"n": int(m.group(1)), "start": None, "end": None, "heading": ""}
            info["scenes"].append(scene)
        elif line.lower().startswith("scene heading:") and scene:
            scene["heading"] = line.split(":", 1)[1].strip()
        elif (m := RE_SCENE_START.match(line)) and scene:
            scene["start"] = to_sec(m.group(1))
        elif (m := RE_SCENE_END.match(line)) and scene:
            scene["end"] = to_sec(m.group(1))
        elif m := RE_BLOCK.match(line):
            name, mods = speaker_of(m.group(1))
            if pending_block:
                info["issues"].append(f"L{i}: block '{pending_block}' had no timing line")
            pending_block = name
            if name.upper() in TECH:
                info["blocks"][name.upper()] += 1
            else:
                info["blocks"]["DIALOGUE"] += 1
                info["speakers"][name] += 1
        elif m := RE_TIMING.match(line):
            s, e = to_sec(m.group(1)), to_sec(m.group(2))
            info["events"] += 1
            info["max_end"] = max(info["max_end"], e)
            if pending_block is None:
                info["issues"].append(f"L{i}: timing line with no block header")
            if e < s:
                info["issues"].append(f"L{i}: end < start ({m.group(1)} > {m.group(2)})")
            if scene and scene["start"] is not None and scene["end"] is not None:
                if s < scene["start"] - 0.01 or e > scene["end"] + 0.01:
                    info["issues"].append(
                        f"L{i}: event {m.group(1)}-{m.group(2)} outside scene "
                        f"{scene['n']} bounds")
            pending_block = None
        elif line.lower().startswith("start:"):
            info["issues"].append(f"L{i}: unparsed timing line: {line[:70]}")
    for key in ("EPISODE NUMBER", "EPISODE LOGLINE", "CONTINUITY NOTES"):
        if not info["headers"].get(key):
            info["issues"].append(f"missing header {key}")
    if not info["scenes"]:
        info["issues"].append("no SCENE markers found")
    return info


def main() -> None:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "data/episodes")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "docs/corpus_profile.md")
    files = sorted(src.glob("*.txt"))
    infos = [profile(f) for f in files]
    speakers = Counter()
    first_seen: dict[str, int] = {}
    blocks = Counter()
    fmts = Counter()
    for n, inf in enumerate(infos, 1):
        speakers.update(inf["speakers"])
        blocks.update(inf["blocks"])
        fmts.update(inf["time_formats"])
        for s in inf["speakers"]:
            first_seen.setdefault(s, n)
    durs = [inf["max_end"] for inf in infos]
    r = ["# Corpus profile", ""]
    r.append(f"- Files: **{len(files)}**")
    r.append(f"- Events (timed blocks): **{sum(i['events'] for i in infos)}**")
    r.append(f"- Episode duration (s): min {min(durs):.1f}, max {max(durs):.1f}, "
             f"mean {sum(durs) / len(durs):.1f}, total {sum(durs) / 60:.1f} min")
    sc = [len(i["scenes"]) for i in infos]
    r.append(f"- Scenes per episode: min {min(sc)}, max {max(sc)}")
    r.append(f"- Block types: {dict(blocks.most_common())}")
    r.append(f"- Time formats seen: {dict(fmts.most_common())}")
    r += ["", "## Per episode", "",
          "| File | Ep header | Scenes | Events | Dur (s) | Issues |",
          "|---|---|---|---|---|---|"]
    for inf in infos:
        r.append(f"| {inf['file']} | {inf['headers'].get('EPISODE NUMBER', '-')} | "
                 f"{len(inf['scenes'])} | {inf['events']} | {inf['max_end']:.1f} | "
                 f"{len(inf['issues'])} |")
    r += ["", "## Speaker labels (count, first episode index)", ""]
    for s, c in speakers.most_common():
        r.append(f"- {s}: {c} (ep #{first_seen[s]})")
    r += ["", "## Issues", ""]
    any_issue = False
    for inf in infos:
        for iss in inf["issues"]:
            any_issue = True
            r.append(f"- {inf['file']}: {iss}")
    if not any_issue:
        r.append("- none")
    out.write_text("\n".join(r) + "\n", encoding="utf-8")
    print("\n".join(r[:9]))
    print(f"Issues: {sum(len(i['issues']) for i in infos)}. Full report: {out}")


if __name__ == "__main__":
    main()
