"""`luna` command line. Run `python -m luna --help`."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def _dump(obj, out: str | None = None, fmt: str | None = None):
    from .export import export
    if out:
        files = export(obj if isinstance(obj, dict) else {"rows": obj}, out, fmt)
        print("written:", *files, sep="\n  ")
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def _catalog(path: str | None):
    from .model import Catalog
    return Catalog.load(path or ROOT / "data" / "kb" / "catalog_RU.json")


def _asm(args):
    from .engine.assumptions import AssumptionSet
    a = AssumptionSet.preset(args.preset)
    for kv in getattr(args, "set", None) or []:
        k, v = kv.split("=", 1)
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            pass
        a.values[k] = v
    return a


def _priors(path):
    from .sim.montecarlo import PriorBook
    return PriorBook.from_dict(json.loads(Path(path).read_text(encoding="utf-8"))) if path else None


# --------------------------------------------------------------------------- commands
def cmd_env_check(args):
    rows = {"python": sys.version.split()[0]}
    for tool, flag in (("git", "--version"), ("node", "--version"), ("claude", "--version"), ("ffmpeg", "-version"), ("tesseract", "--version")):
        p = shutil.which(tool)
        rows[tool] = subprocess.run([p, flag], capture_output=True, text=True).stdout.splitlines()[0] if p else "missing"
    for mod in ("openpyxl", "ortools", "bs4", "requests", "pytest"):
        try:
            m = __import__(mod)
            rows[mod] = getattr(m, "__version__", "ok")
        except ImportError:
            rows[mod] = "missing"
    sk = ROOT / ".claude" / "skills"
    rows["project_skills"] = sorted(p.name for p in sk.iterdir() if (p / "SKILL.md").exists()) if sk.exists() else []
    _dump(rows)


def cmd_kb(args):
    from .kb import KnowledgeBase
    kb = KnowledgeBase.load()
    if args.action == "status":
        _dump(kb.coverage_report(), args.out)
    elif args.action == "hero":
        from .localization import resolve_hero
        _dump(kb.hero_card(resolve_hero(args.arg) or args.arg))
    elif args.action == "conflicts":
        _dump(kb.conflicts())
    elif args.action == "import-csv":
        from .collector import import_hero_csv
        from .provenance import Fact
        facts = import_hero_csv(args.arg)
        for f in facts:
            kb.add(Fact.from_dict(f), persist=True)
        print(f"imported {len(facts)} facts")
    elif args.action == "accept":
        from .collector import PENDING
        from .provenance import Fact
        p = PENDING / f"{args.arg or 'RU'}.jsonl"
        rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []
        for r in rows:
            kb.add(Fact.from_dict(r), persist=True)
        if p.exists():
            p.rename(p.with_suffix(".accepted.jsonl"))
        print(f"accepted {len(rows)} reviewed facts into the KB")


def cmd_glossary(args):
    from .localization import lookup, _load
    _dump(lookup(args.term) if args.term else _load()["entries"])


def cmd_assumptions(args):
    from .engine.assumptions import registry_markdown, PRESETS
    print(registry_markdown())
    print("\nPresets:", json.dumps(PRESETS, ensure_ascii=False, indent=1))


def cmd_validate_team(args):
    from .kb import KnowledgeBase
    from .model import Team
    from .rules import GameRules, validate_team
    cat = _catalog(args.catalog)
    t = Team.load(args.team)
    kb = KnowledgeBase.load(args.rules_dir) if args.rules_dir else KnowledgeBase.load()
    rules = GameRules.from_kb(kb, cat.region if not args.rules_dir else "SYNTHETIC")
    inv = json.loads(Path(args.inventory).read_text()) if args.inventory else None
    rep = validate_team(t, cat, rules, inventory=inv)
    for i in rep.issues:
        print(i)
    print("OK" if rep.ok else "INVALID")
    sys.exit(0 if rep.ok else 1)


def cmd_battle(args):
    from .model import Team
    from .sim.montecarlo import run_battle, battle_report
    cat = _catalog(args.catalog)
    res = run_battle(Team.load(args.team_a), Team.load(args.team_b), cat, _asm(args), args.seed, _priors(args.priors))
    rep = battle_report(res)
    if args.log:
        Path(args.log).write_text(json.dumps(res.log, ensure_ascii=False), encoding="utf-8")
    _dump(rep, args.out)


def cmd_sim(args):
    from .model import Team
    from .sim.montecarlo import simulate
    cat = _catalog(args.catalog)
    s = simulate(Team.load(args.team_a), Team.load(args.team_b), cat, _asm(args), n=args.n, seed=args.seed,
                 priors=_priors(args.priors), workers=args.workers, key_heroes=args.key)
    _dump(s, args.out)


def cmd_compare(args):
    from .model import Team
    from .sim.montecarlo import compare
    cat = _catalog(args.catalog)
    _dump(compare(Team.load(args.team_a), Team.load(args.team_a2), [Team.load(p) for p in args.opponents], cat, _asm(args),
                  n=args.n, seed=args.seed, priors=_priors(args.priors)), args.out)


def cmd_matchup(args):
    from .matchup import MatchupAnalyzer
    from .model import Team
    from .optimize.search import Roster
    cat = _catalog(args.catalog)
    ma = MatchupAnalyzer(cat, _asm(args), n=args.n, seed=args.seed, priors=_priors(args.priors))
    my, en = Team.load(args.my), Team.load(args.enemy)
    rep = {"analysis": ma.analyze(my, en, key_heroes=args.key)}
    if args.suggest:
        roster = Roster.from_dict(json.loads(Path(args.roster).read_text())) if args.roster else None
        rep["suggestions"] = ma.suggest(my, en, roster=roster)
    if args.ablation:
        rep["ablation"] = ma.ablation(my, en)
    _dump(rep, args.out)


def cmd_optimize(args):
    from .matchup import mode_objective, filter_roster_no_donation
    from .model import Team
    from .optimize.search import Roster, Evaluator, genetic_algorithm, beam_search
    cat = _catalog(args.catalog)
    roster = Roster.from_dict(json.loads(Path(args.roster).read_text()))
    mo = mode_objective(args.mode)
    if mo.get("filter") == "no_donation":
        roster = filter_roster_no_donation(roster, cat)
    opps = [Team.load(p) for p in args.opponents]
    ev = Evaluator(opps, cat, _asm(args), n=args.n, seed=args.seed, priors=_priors(args.priors))
    if args.algo == "beam":
        r = beam_search(roster, ev, n_screen=args.n)
    else:
        r = genetic_algorithm(roster, ev, generations=args.generations, pop_size=args.pop, weights=mo["weights"],
                              multi_objective=args.pareto, n_screen=args.n, n_final=args.n_final)
    r["team"].save(Path(args.save) if args.save else REPORTS / "optimized_team.json")
    r["team"] = r["team"].to_dict()
    r["mode"] = mo
    _dump(r, args.out)


def cmd_scenario(args):
    from . import scenarios
    if args.name == "hypotheses":
        _dump(scenarios.run_hypotheses(n=args.n, workers=args.workers), args.out)
    elif args.name == "scenario3":
        _dump(scenarios.scenario3(workers=args.workers), args.out)


def cmd_meta(args):
    from . import meta
    from .kb import KnowledgeBase
    if args.action == "list":
        _dump(meta.query(region=args.region, kind=args.kind, status=args.status), args.out)
    elif args.action == "forecast":
        _dump(meta.forecast_ru(), args.out)
    elif args.action == "diff":
        d = meta.region_diff(KnowledgeBase.load())
        d["summary"] = {"|".join(k): v for k, v in d["summary"].items()}
        _dump(d, args.out)
    elif args.action == "add":
        _dump(meta.add(json.loads(Path(args.file).read_text(encoding="utf-8"))))


def cmd_validate(args):
    from . import validation as V
    if args.action == "import":
        p = Path(args.file)
        suf = p.suffix.lower()
        if suf in (".csv", ".xlsx", ".xlsm"):
            r = V.import_table(p)
        elif suf == ".json":
            r = V.import_battle_json(p)
        elif suf == ".md":
            r = V.import_markdown(p)
        elif suf in (".png", ".jpg", ".jpeg", ".webp"):
            r = V.register_screenshot(p, kind=args.kind)
        elif suf in (".mp4", ".mov", ".mkv", ".webm"):
            r = V.extract_video_frames(p)
        else:
            raise SystemExit(f"unsupported file type {suf}")
        _dump(r if isinstance(r, dict) else {"imported": len(r), "sample": r[:3]})
    elif args.action == "status":
        _dump(V.status())
    elif args.action == "calibrate":
        grid = json.loads(Path(args.grid).read_text()) if args.grid else {"dmg.k_def": [5000, 10000, 20000]}
        _dump(V.calibrate(_catalog(args.catalog), _asm(args), grid, n=args.n, force=args.force), args.out)


def cmd_resources(args):
    from . import resources
    d = json.loads(Path(args.file).read_text(encoding="utf-8"))
    _dump(resources.plan(d["upgrades"], d["budget"]) if args.action == "plan" else
          resources.long_term(d["upgrades"], d.get("have", {}), d.get("income_per_day", {}), d.get("horizon_days", 90)), args.out)


def cmd_collect(args):
    from . import collector
    if args.offline_dir:
        _dump(collector.ingest_offline_dir(args.offline_dir, args.region))
    else:
        _dump(collector.fetch(args.url or collector.SOURCES["RU"]["base"]))


def cmd_export(args):
    from .export import export
    rep = json.loads(Path(args.report).read_text(encoding="utf-8"))
    print(*export(rep, args.out, args.fmt), sep="\n")


def cmd_dashboard(args):
    from .dashboard.server import serve
    serve(args.host, args.port)


def main(argv=None):
    p = argparse.ArgumentParser(prog="luna", description="Luna Fantasy AI - knowledge base, combat engine, simulator, optimizer")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, sim=True):
        sp.add_argument("--catalog", help="catalog JSON (default data/kb/catalog_RU.json)")
        sp.add_argument("--out", help="output file (.json/.xlsx/.csv/.html)")
        if sim:
            sp.add_argument("--preset", default="exploratory_v1", help="assumption preset (luna assumptions)")
            sp.add_argument("--set", action="append", help="override assumption: key=value (JSON value)")
            sp.add_argument("--seed", type=int, default=1)
            sp.add_argument("--priors", help="PriorBook JSON for UNKNOWN stats")

    sp = sub.add_parser("env-check"); sp.set_defaults(fn=cmd_env_check)
    sp = sub.add_parser("kb"); sp.add_argument("action", choices=["status", "hero", "conflicts", "import-csv", "accept"])
    sp.add_argument("arg", nargs="?"); sp.add_argument("--out"); sp.set_defaults(fn=cmd_kb)
    sp = sub.add_parser("glossary"); sp.add_argument("term", nargs="?"); sp.set_defaults(fn=cmd_glossary)
    sp = sub.add_parser("assumptions"); sp.set_defaults(fn=cmd_assumptions)
    sp = sub.add_parser("validate-team"); sp.add_argument("team"); sp.add_argument("--catalog"); sp.add_argument("--inventory")
    sp.add_argument("--rules-dir", help="facts dir with rules.* (default KB)"); sp.set_defaults(fn=cmd_validate_team)
    sp = sub.add_parser("battle"); sp.add_argument("team_a"); sp.add_argument("team_b"); sp.add_argument("--log"); common(sp)
    sp.set_defaults(fn=cmd_battle)
    sp = sub.add_parser("sim"); sp.add_argument("team_a"); sp.add_argument("team_b"); sp.add_argument("-n", type=int, default=1000)
    sp.add_argument("--workers", type=int); sp.add_argument("--key", nargs="*"); common(sp); sp.set_defaults(fn=cmd_sim)
    sp = sub.add_parser("compare"); sp.add_argument("team_a"); sp.add_argument("team_a2"); sp.add_argument("--opponents", nargs="+", required=True)
    sp.add_argument("-n", type=int, default=500); common(sp); sp.set_defaults(fn=cmd_compare)
    sp = sub.add_parser("matchup"); sp.add_argument("my"); sp.add_argument("enemy"); sp.add_argument("-n", type=int, default=300)
    sp.add_argument("--key", nargs="*"); sp.add_argument("--suggest", action="store_true"); sp.add_argument("--ablation", action="store_true")
    sp.add_argument("--roster"); common(sp); sp.set_defaults(fn=cmd_matchup)
    sp = sub.add_parser("optimize"); sp.add_argument("--roster", required=True); sp.add_argument("--opponents", nargs="+", required=True)
    sp.add_argument("--mode", default="best_overall"); sp.add_argument("--algo", choices=["ga", "beam"], default="ga")
    sp.add_argument("-n", type=int, default=40); sp.add_argument("--n-final", type=int, default=200)
    sp.add_argument("--generations", type=int, default=6); sp.add_argument("--pop", type=int, default=12)
    sp.add_argument("--pareto", nargs="*", help="objectives for NSGA-II ranking, e.g. win_rate robust_wr speed")
    sp.add_argument("--save"); common(sp); sp.set_defaults(fn=cmd_optimize)
    sp = sub.add_parser("scenario"); sp.add_argument("name", choices=["hypotheses", "scenario3"]); sp.add_argument("-n", type=int, default=400)
    sp.add_argument("--workers", type=int, default=4); sp.add_argument("--out"); sp.set_defaults(fn=cmd_scenario)
    sp = sub.add_parser("meta"); sp.add_argument("action", choices=["list", "forecast", "diff", "add"]); sp.add_argument("--region")
    sp.add_argument("--kind"); sp.add_argument("--status"); sp.add_argument("--file"); sp.add_argument("--out"); sp.set_defaults(fn=cmd_meta)
    sp = sub.add_parser("validate"); sp.add_argument("action", choices=["import", "status", "calibrate"]); sp.add_argument("file", nargs="?")
    sp.add_argument("--kind", default="hero"); sp.add_argument("--grid"); sp.add_argument("-n", type=int, default=100)
    sp.add_argument("--force", action="store_true"); common(sp); sp.set_defaults(fn=cmd_validate)
    sp = sub.add_parser("resources"); sp.add_argument("action", choices=["plan", "long-term"]); sp.add_argument("file"); sp.add_argument("--out")
    sp.set_defaults(fn=cmd_resources)
    sp = sub.add_parser("collect"); sp.add_argument("--offline-dir"); sp.add_argument("--url"); sp.add_argument("--region", default="RU")
    sp.set_defaults(fn=cmd_collect)
    sp = sub.add_parser("export"); sp.add_argument("report"); sp.add_argument("out"); sp.add_argument("--fmt"); sp.set_defaults(fn=cmd_export)
    sp = sub.add_parser("dashboard"); sp.add_argument("--host", default="127.0.0.1"); sp.add_argument("--port", type=int, default=8765)
    sp.set_defaults(fn=cmd_dashboard)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
