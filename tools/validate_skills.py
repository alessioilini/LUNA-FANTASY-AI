#!/usr/bin/env python3
"""Validate project Claude Code skills in .claude/skills/*/SKILL.md.

Checks for every skill:
  * YAML frontmatter exists, `name` == directory name, `description` non-empty and < 1024 chars;
  * skill names are unique.
Extra checks for project skills named `luna-*`:
  * the 8 required section headings exist, in order;
  * the description contains Russian trigger words (Cyrillic);
  * "## Примеры запросов" has at least 3 list items;
  * every `luna <subcommand>` mentioned in code (inline or fenced) exists in the real argparse
    parser of luna.cli, its action argument (e.g. `luna kb status`) is a valid choice, and every
    `--flag` used is accepted by that subcommand.

Usage: python tools/validate_skills.py [--skills-dir PATH]   (exit code 1 on any failure)
"""
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / ".claude" / "skills"
MAX_DESC = 1024
REQUIRED_SECTIONS = [
    "## Назначение",
    "## Когда использовать",
    "## Требуемые входные данные",
    "## Алгоритм работы",
    "## Ограничения",
    "## Формат результата",
    "## Проверки качества",
    "## Примеры запросов",
]
MIN_EXAMPLES = 3
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
# `luna <sub>` or `python -m luna <sub>` at the start of a command segment
CMD_RE = re.compile(r"(?:^|(?<=[\s(`$]))(?:python3?\s+-m\s+)?luna\s+([a-z][a-z0-9-]*)((?:[^\n]*)?)")
SEGMENT_END = re.compile(r"\s(?:\||&&|;|>|2>)\s|\s#\s")


# ----------------------------------------------------------------------------- parser introspection
class _Captured(Exception):
    def __init__(self, parser):
        self.parser = parser


def luna_cli_spec() -> dict[str, dict]:
    """{subcommand: {"options": set(option strings), "choices": list|None}} from luna.cli's argparse parser."""
    sys.path.insert(0, str(ROOT))
    try:
        import luna.cli as cli

        orig = argparse.ArgumentParser.parse_args

        def grab(self, *a, **k):
            raise _Captured(self)

        argparse.ArgumentParser.parse_args = grab
        try:
            cli.main([])
        except _Captured as c:
            parser = c.parser
        finally:
            argparse.ArgumentParser.parse_args = orig
        spec = {}
        for act in parser._actions:
            if isinstance(act, argparse._SubParsersAction):
                for name, sp in act.choices.items():
                    opts, choices = {"-h", "--help"}, None
                    for a in sp._actions:
                        opts.update(a.option_strings)
                        if not a.option_strings and a.choices and choices is None:
                            choices = list(a.choices)
                    spec[name] = {"options": opts, "choices": choices}
        if spec:
            return spec
    except Exception as e:  # pragma: no cover - fallback path
        print(f"note: argparse introspection failed ({e}); falling back to `python -m luna --help`", file=sys.stderr)
    out = subprocess.run([sys.executable, "-m", "luna", "--help"], capture_output=True, text=True, cwd=ROOT).stdout
    m = re.search(r"\{([a-z0-9,-]+)\}", out)
    spec = {}
    for name in (m.group(1).split(",") if m else []):
        h = subprocess.run([sys.executable, "-m", "luna", name, "--help"], capture_output=True, text=True, cwd=ROOT).stdout
        opts = set(re.findall(r"(?<![\w-])(--?[a-zA-Z][\w-]*)", h))
        cm = re.search(r"usage: .*?\{([^}]+)\}", h, re.S)
        spec[name] = {"options": opts | {"-h", "--help"}, "choices": cm.group(1).split(",") if cm else None}
    return spec


# ----------------------------------------------------------------------------- skill parsing
def parse_frontmatter(text: str) -> tuple[dict | None, str, str]:
    """Returns (frontmatter dict or None, body, error)."""
    if not text.startswith("---"):
        return None, text, "no frontmatter (file must start with ---)"
    m = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not m:
        return None, text, "frontmatter not closed with ---"
    raw, body = m.group(1), text[m.end():]
    try:
        import yaml
        data = yaml.safe_load(raw)
    except ImportError:  # pragma: no cover
        data = _lenient_frontmatter(raw)
    except Exception as e:
        # Claude Code reads `key: value` lines leniently (e.g. unquoted colons inside a description);
        # accept that, but report that the frontmatter is not strict YAML.
        data = _lenient_frontmatter(raw)
        if not data:
            return None, body, f"invalid YAML frontmatter: {e}"
        return data, body, "LENIENT: frontmatter is not strict YAML (unquoted ': ' in a value); parsed leniently"
    if not isinstance(data, dict):
        return None, body, "frontmatter is not a mapping"
    return data, body, ""


def _lenient_frontmatter(raw: str) -> dict:
    """Top-level `key: rest of line` pairs plus folded/literal block scalars (indented continuation lines)."""
    data, key = {}, None
    for line in raw.splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):(?:\s+(.*))?$", line)
        if km:
            key, val = km.group(1), (km.group(2) or "").strip()
            data[key] = "" if val in ("", ">", ">-", "|", "|-") else val.strip("'\"")
        elif key and line.startswith((" ", "\t")):
            data[key] = (data[key] + " " + line.strip()).strip()
    return data


def code_snippets(body: str) -> list[str]:
    """Command-bearing text: lines of fenced blocks (with `\\` continuations joined) + inline code spans."""
    out = []
    fence = re.compile(r"^[ \t]*```[^\n]*\n(.*?)^[ \t]*```", re.S | re.M)
    for m in fence.finditer(body):
        block = re.sub(r"\\\n\s*", " ", m.group(1))
        out.extend(block.splitlines())
    rest = fence.sub("", body)
    for m in re.finditer(r"`([^`]+)`", rest, re.S):
        out.append(" ".join(m.group(1).split()))
    return out


def luna_commands(body: str) -> list[tuple[str, list[str], str]]:
    """[(subcommand, argument tokens, original text)] for every `luna <sub> ...` in code."""
    found = []
    for snip in code_snippets(body):
        for m in CMD_RE.finditer(snip):
            sub, tail = m.group(1), m.group(2) or ""
            tail = SEGMENT_END.split(" " + tail, maxsplit=1)[0]
            try:
                toks = shlex.split(tail)
            except ValueError:
                toks = tail.split()
            found.append((sub, toks, f"luna {sub}{(' ' + tail.strip()) if tail.strip() else ''}"))
    return found


def check_command(sub: str, toks: list[str], spec: dict) -> list[str]:
    if sub not in spec:
        return [f"unknown subcommand `luna {sub}`"]
    errs = []
    s = spec[sub]
    if s["choices"] and toks and not toks[0].startswith("-") and toks[0] not in ("...", "…"):
        if toks[0] not in s["choices"]:
            errs.append(f"`luna {sub} {toks[0]}`: action must be one of {s['choices']}")
    for t in toks:
        if re.fullmatch(r"--?[a-zA-Z][\w-]*(=.*)?", t):
            flag = t.split("=", 1)[0]
            if flag not in s["options"]:
                errs.append(f"`luna {sub}`: unknown option {flag}")
    return errs


def section_items(body: str, heading: str) -> list[str]:
    m = re.search(rf"^{re.escape(heading)}\s*$(.*?)(?=^## |\Z)", body, re.S | re.M)
    if not m:
        return []
    return [l for l in m.group(1).splitlines() if re.match(r"^\s*(?:[-*]|\d+[.)])\s+\S", l)]


# ----------------------------------------------------------------------------- main check
@dataclass
class Result:
    skill: str
    desc_len: int = 0
    lines: int = 0
    sections: str = "-"
    cli_refs: int = 0
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def status(self) -> str:
        return "FAIL" if self.errors else ("WARN" if self.warnings else "OK")


def validate(skills_dir: Path = SKILLS_DIR, spec: dict | None = None) -> list[Result]:
    results: list[Result] = []
    names: dict[str, str] = {}
    dirs = sorted(p for p in Path(skills_dir).iterdir() if p.is_dir()) if Path(skills_dir).exists() else []
    for d in dirs:
        r = Result(skill=d.name)
        results.append(r)
        f = d / "SKILL.md"
        if not f.exists():
            r.errors.append("missing SKILL.md")
            continue
        text = f.read_text(encoding="utf-8")
        r.lines = len(text.splitlines())
        fm, body, err = parse_frontmatter(text)
        if err.startswith("LENIENT: "):
            r.warnings.append(err[len("LENIENT: "):])
        elif err:
            r.errors.append(err)
            continue
        name = str(fm.get("name") or "").strip()
        desc = str(fm.get("description") or "").strip()
        r.desc_len = len(desc)
        if name != d.name:
            r.errors.append(f"frontmatter name {name!r} != directory {d.name!r}")
        if not desc:
            r.errors.append("empty description")
        elif len(desc) >= MAX_DESC:
            r.errors.append(f"description is {len(desc)} chars (must be < {MAX_DESC})")
        if name:
            if name in names:
                r.errors.append(f"duplicate skill name {name!r} (also in {names[name]})")
            names[name] = d.name
        if not d.name.startswith("luna-"):
            continue
        # ---- project (luna-*) skills
        if not CYRILLIC.search(desc):
            r.errors.append("description has no Russian trigger words")
        pos, found = -1, 0
        for h in REQUIRED_SECTIONS:
            m = re.search(rf"^{re.escape(h)}\s*$", body, re.M)
            if not m:
                r.errors.append(f"missing section {h!r}")
                continue
            found += 1
            if m.start() < pos:
                r.errors.append(f"section {h!r} out of order")
            pos = m.start()
        r.sections = f"{found}/{len(REQUIRED_SECTIONS)}"
        n_ex = len(section_items(body, "## Примеры запросов"))
        if n_ex < MIN_EXAMPLES:
            r.errors.append(f"'## Примеры запросов' has {n_ex} items (need >= {MIN_EXAMPLES})")
        if not section_items(body, "## Алгоритм работы"):
            r.errors.append("'## Алгоритм работы' has no steps")
        if not 40 <= r.lines <= 200:
            r.warnings.append(f"{r.lines} lines (target roughly 60-150)")
        if spec is None:
            spec = luna_cli_spec()
        cmds = luna_commands(desc + "\n\n" + body)   # description and body
        r.cli_refs = len(cmds)
        if not cmds:
            r.errors.append("no `luna ...` command referenced")
        for sub, toks, src in cmds:
            for e in check_command(sub, toks, spec):
                r.errors.append(f"{e}  [in: {src[:90]}]")
    return results


def print_table(results: list[Result]) -> None:
    hdr = ("skill", "status", "desc_len", "lines", "sections", "cli_refs")
    rows = [(r.skill, r.status, str(r.desc_len), str(r.lines), r.sections, str(r.cli_refs)) for r in results]
    w = [max(len(h), *(len(row[i]) for row in rows)) if rows else len(h) for i, h in enumerate(hdr)]
    line = "+".join("-" * (x + 2) for x in w)
    print(line)
    print("|".join(f" {h:<{w[i]}} " for i, h in enumerate(hdr)))
    print(line)
    for row in rows:
        print("|".join(f" {c:<{w[i]}} " for i, c in enumerate(row)))
    print(line)
    for r in results:
        for e in r.errors:
            print(f"ERROR {r.skill}: {e}")
        for wmsg in r.warnings:
            print(f"WARN  {r.skill}: {wmsg}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skills-dir", default=str(SKILLS_DIR))
    args = ap.parse_args(argv)
    results = validate(Path(args.skills_dir))
    print_table(results)
    n_fail = sum(1 for r in results if r.errors)
    n_luna = sum(1 for r in results if r.skill.startswith("luna-"))
    print(f"\n{len(results)} skills checked ({n_luna} luna-*), {n_fail} failed, "
          f"{sum(r.cli_refs for r in results)} luna CLI references verified against luna.cli")
    if not results:
        print("no skills found")
        return 1
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
