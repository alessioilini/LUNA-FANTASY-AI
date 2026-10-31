"""Project skills (.claude/skills) are well-formed and only cite real `luna` CLI commands."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import validate_skills as V  # noqa: E402

LUNA_SKILLS = {
    "luna-data-collector", "luna-region-translator", "luna-hero-database", "luna-build-analyzer",
    "luna-combat-engine", "luna-battle-simulator", "luna-matchup-analyzer", "luna-team-optimizer",
    "luna-meta-tracker", "luna-resource-planner", "luna-battle-validator", "luna-dashboard",
}


def test_validator_passes_on_project_skills():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "validate_skills.py")], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
    assert " 0 failed" in r.stdout


def test_all_luna_skills_present():
    present = {p.parent.name for p in (ROOT / ".claude" / "skills").glob("luna-*/SKILL.md")}
    assert LUNA_SKILLS <= present, LUNA_SKILLS - present


def _write(d: Path, name: str, text: str):
    (d / name).mkdir(parents=True)
    (d / name / "SKILL.md").write_text(text, encoding="utf-8")


def test_validator_detects_broken_skills(tmp_path):
    body = "\n".join(f"{h}\n- пункт\n" for h in V.REQUIRED_SECTIONS)
    _write(tmp_path, "luna-good", "---\nname: luna-good\ndescription: Does X. Триггер: проверь.\n---\n"
           + body.replace("## Примеры запросов\n- пункт", "## Примеры запросов\n- а\n- б\n- в")
           + "\n`luna kb status` `luna sim a.json b.json -n 10`\n")
    _write(tmp_path, "luna-bad", "---\nname: luna-other\ndescription: English only\n---\n## Назначение\n"
           "`luna dashbord` `luna kb statuz` `luna sim a b --bogus`\n")
    _write(tmp_path, "plain", "no frontmatter")
    res = {r.skill: r for r in V.validate(tmp_path)}
    assert res["luna-good"].errors == []
    errs = " ".join(res["luna-bad"].errors)
    for needle in ("!= directory", "Russian", "missing section", "unknown subcommand `luna dashbord`",
                   "action must be one of", "unknown option --bogus", "Примеры запросов"):
        assert needle in errs, needle
    assert res["plain"].errors


def test_description_length_and_duplicates(tmp_path):
    _write(tmp_path, "a", "---\nname: a\ndescription: " + "x" * 1100 + "\n---\n")
    _write(tmp_path, "b", "---\nname: a\ndescription: ok\n---\n")
    res = {r.skill: r for r in V.validate(tmp_path)}
    assert any("chars" in e for e in res["a"].errors)
    assert any("duplicate" in e for e in res["b"].errors)
