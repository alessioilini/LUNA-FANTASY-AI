"""Local dashboard server (stage 12): standard library only (http.server + json).

Run with `luna dashboard` (binds 127.0.0.1:8765 by default). The server is a thin JSON layer over the
existing modules - it never computes game numbers itself. Every simulated number it returns carries the
module's own "MODEL ..." label; the frontend repeats that label next to every result.
"""
from __future__ import annotations

import dataclasses
import io
import json
import math
import mimetypes
import re
import tempfile
import threading
import traceback
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
STATIC = Path(__file__).resolve().parent / "static"
DATA = ROOT / "data"
TEAMS_DIR = DATA / "user" / "teams"
PORTRAITS_DIR = DATA / "user" / "portraits"
PORTRAIT_EXT = (".png", ".jpg", ".jpeg", ".webp")

CATALOG_FILES = {
    "ru": DATA / "kb" / "catalog_RU.json",
    "synthetic": DATA / "fixtures" / "synthetic_catalog.json",
}
CATALOG_INFO = {
    "ru": {"label": "RU (lunafantasy.ru)", "kind": "real",
           "warning": "Симулятор не валидирован на реальных боях."},
    "whatif": {"label": "WHAT-IF / ролевые шаблоны", "kind": "whatif",
               "warning": "Обобщённые ролевые шаблоны (гипотезы), статы UNKNOWN - заполняются явными априорными "
                          "распределениями. Это не данные Luna Fantasy."},
    "synthetic": {"label": "SYNTHETIC (тестовая фикстура)", "kind": "synthetic",
                  "warning": "Выдуманные числа для тестов движка, НЕ данные Luna Fantasy."},
}
EMPTY_WARNING = "Данные не загружены (lunafantasy.ru не был доступен). Импортируйте их: `luna kb import` / `luna collect`."

SIM_N_MAX = 5000
MATRIX_N_MAX = 300
MATCHUP_N_MAX = 2000
SUGGEST_N_MAX = 200
COMPARE_N_MAX = 2000
EXPORT_FORMATS = {"xlsx", "csv", "html", "json"}


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# ============================================================================ helpers
_cat_lock = threading.Lock()
_cat_cache: dict = {}


def _catalog(cid: str | None):
    """Return a luna.model.Catalog for a catalog id (ru | whatif | synthetic). File catalogs are re-read
    when the file changes, so `luna kb import` while the dashboard runs is picked up without a restart."""
    from ..model import Catalog
    from .. import scenarios
    cid = cid or "synthetic"
    if cid not in CATALOG_INFO:
        raise ApiError(f"неизвестный каталог '{cid}'; доступны: {', '.join(CATALOG_INFO)}")
    path = CATALOG_FILES.get(cid)
    stamp = path.stat().st_mtime_ns if path and path.exists() else 0
    with _cat_lock:
        hit = _cat_cache.get(cid)
        if hit is None or hit[0] != stamp:
            if path is not None and not path.exists():
                raise ApiError(f"файл каталога не найден: {path}", 404)
            cat = scenarios.whatif_catalog() if cid == "whatif" else Catalog.load(path)
            _cat_cache[cid] = hit = (stamp, cat)
        return hit[1]


def _rules(cid: str):
    from ..kb import KnowledgeBase
    from ..rules import GameRules
    if cid == "synthetic":
        return GameRules.from_kb(KnowledgeBase.load(DATA / "fixtures"), region="SYNTHETIC")
    return GameRules.from_kb(KnowledgeBase.load(), region="RU")


def _fields(cls) -> set:
    return {f.name for f in dataclasses.fields(cls)}


def _team_from(obj, teams_dir: Path):
    """Accept a team dict (Team.to_dict format) or the name of a saved team."""
    from ..model import Team, HeroBuild, Progression
    if isinstance(obj, str):
        return Team.load(_team_path(teams_dir, obj, must_exist=True))
    if not isinstance(obj, dict):
        raise ApiError("ожидается объект команды или имя сохранённой команды")
    d = {k: v for k, v in obj.items() if k in _fields(Team)}
    heroes = []
    for i, h in enumerate(d.get("heroes") or []):
        if not isinstance(h, dict) or not h.get("hero_id"):
            raise ApiError(f"heroes[{i}]: нужен hero_id")
        hd = {k: v for k, v in h.items() if k in _fields(HeroBuild)}
        if isinstance(hd.get("progression"), dict):
            hd["progression"] = {k: v for k, v in hd["progression"].items() if k in _fields(Progression)}
        heroes.append(hd)
    d["heroes"] = heroes
    d.setdefault("name", "team")
    try:
        return Team.from_dict(d)
    except TypeError as e:
        raise ApiError(f"неверный формат команды: {e}") from e


def _safe_name(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", str(name or "").strip(), flags=re.UNICODE).strip("_")
    if not s:
        raise ApiError("пустое имя команды")
    return s[:80]


def _team_path(teams_dir: Path, name: str, must_exist: bool = False) -> Path:
    p = Path(teams_dir) / f"{_safe_name(name)}.json"
    if must_exist and not p.exists():
        raise ApiError(f"команда '{name}' не найдена", 404)
    return p


def _asm(body: dict):
    from ..engine.assumptions import AssumptionSet, PRESETS
    preset = body.get("preset") or "exploratory_v1"
    if preset not in PRESETS:
        raise ApiError(f"неизвестный пресет '{preset}'; доступны: {', '.join(PRESETS)}")
    overrides = body.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise ApiError("overrides должен быть объектом {assumption_id: value}")
    from ..engine.assumptions import REGISTRY
    bad = [k for k in overrides if k != "stacking" and k not in REGISTRY]
    if bad:
        raise ApiError(f"неизвестные допущения: {', '.join(bad)}")
    return AssumptionSet.preset(preset, **dict(overrides))


def _priors(cid: str, body: dict):
    """WHAT-IF heroes have UNKNOWN stats: priors are mandatory there. Elsewhere only on request."""
    from .. import scenarios
    if cid == "whatif" or body.get("use_priors"):
        return scenarios.default_priors()
    return None


def _int(body: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(body.get(key, default) if body.get(key) is not None else default)
    except (TypeError, ValueError):
        raise ApiError(f"{key} должно быть целым числом") from None
    return max(lo, min(hi, v))


def _jsonable(o):
    """Make module outputs JSON-safe (tuples, sets, dataclasses, Team, inf/nan, non-str keys)."""
    from ..model import Team
    if isinstance(o, Team):
        return _jsonable(o.to_dict())
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return _jsonable(dataclasses.asdict(o))
    if isinstance(o, dict):
        return {str(k) if not isinstance(k, str) else k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_jsonable(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None if math.isnan(o) else ("inf" if o > 0 else "-inf")
    if hasattr(o, "value") and o.__class__.__module__.startswith("luna"):   # enums
        return o.value
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    return str(o)


def _sample_teams(cid: str) -> list[dict]:
    """Demo compositions so every tab works out of the box (clearly labelled test teams)."""
    from .. import scenarios
    from ..model import Team, hero_from_catalog
    if cid == "whatif":
        return [scenarios.team("Команда A (сценарий)", scenarios.TEAM_A).to_dict(),
                scenarios.team("Команда B (сценарий)", scenarios.TEAM_B).to_dict()]
    if cid == "synthetic":
        cat = _catalog(cid)
        out = []
        for name, ids in (("Синт. A", ["s_striker", "s_mage", "s_tank", "s_healer", "s_reviver", "s_controller"]),
                          ("Синт. B", ["s_tank", "s_bruiser", "s_reviver", "s_healer", "s_mage", "s_controller"])):
            out.append(Team(name=name, heroes=[hero_from_catalog(cat, h) for h in ids],
                            formation={h: i for i, h in enumerate(ids)}, region=cat.region,
                            balance_version=cat.balance_version,
                            notes="Тестовая синтетическая команда").to_dict())
        return out
    return []


# ============================================================================ API handlers
def api_catalogs(srv, q, body):
    out = []
    for cid, info in CATALOG_INFO.items():
        cat = _catalog(cid)
        n_heroes = len(cat.sections["heroes"])
        n_items = sum(len(v) for k, v in cat.sections.items() if k != "heroes")
        empty = n_heroes == 0 and n_items == 0
        out.append({"id": cid, **info, "warning": EMPTY_WARNING if empty else info["warning"],
                    "region": cat.region, "balance_version": cat.balance_version,
                    "heroes": n_heroes, "items": n_items, "empty": empty, "meta": cat.meta})
    return out


def api_catalog(srv, q, body):
    cid = q.get("id") or "synthetic"
    cat = _catalog(cid)
    d = cat.to_dict()
    d["id"] = cid
    d["info"] = CATALOG_INFO[cid]
    d["empty"] = not any(cat.sections.values())
    d["sample_teams"] = _sample_teams(cid)
    return d


def api_schema(srv, q, body):
    from ..model import STAT_KEYS, FRACTION_STATS, CATALOG_SECTIONS
    from ..engine.assumptions import PRESETS
    return {"stat_keys": STAT_KEYS, "fraction_stats": sorted(FRACTION_STATS), "catalog_sections": CATALOG_SECTIONS,
            "presets": list(PRESETS), "limits": {"sim_n_max": SIM_N_MAX, "matrix_n_max": MATRIX_N_MAX,
                                                 "matchup_n_max": MATCHUP_N_MAX, "suggest_n_max": SUGGEST_N_MAX}}


def api_kb_status(srv, q, body):
    from ..kb import KnowledgeBase
    return KnowledgeBase.load().coverage_report()


def api_kb_hero(srv, q, body):
    from ..kb import KnowledgeBase
    from ..localization import resolve_hero, _load
    hid = q.get("id")
    if not hid:
        raise ApiError("нужен параметр id")
    hid = resolve_hero(hid) or hid
    card = KnowledgeBase.load().hero_card(hid)
    card["glossary"] = _load()["index"].get(f"hero.{hid}")
    return card


def api_glossary(srv, q, body):
    from ..localization import _load, label
    entries = []
    for e in _load()["entries"]:
        entries.append({**e, "label": label(e["key"])})
    return {"entries": entries}


def api_assumptions(srv, q, body):
    from ..engine.assumptions import REGISTRY, PRESETS
    rows = [dataclasses.asdict(a) for a in REGISTRY.values()]
    return {"registry": rows, "presets": PRESETS}


def api_portraits(srv, q, body):
    d = PORTRAITS_DIR
    if not d.exists():
        return {}
    return {p.stem: f"/portraits/{p.name}" for p in sorted(d.iterdir()) if p.suffix.lower() in PORTRAIT_EXT}


def api_teams_list(srv, q, body):
    out = []
    for p in sorted(Path(srv.teams_dir).glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            out.append({"name": p.stem, "file": p.name, "error": "не удалось прочитать"})
            continue
        out.append({"name": p.stem, "file": p.name, "team_name": d.get("name"), "region": d.get("region"),
                    "balance_version": d.get("balance_version"), "status": d.get("status"),
                    "heroes": [h.get("hero_id") for h in d.get("heroes", [])]})
    return out


def api_team_get(srv, q, body, name):
    return _team_from(name, srv.teams_dir).to_dict()


def api_team_save(srv, q, body):
    t = body.get("team", body)
    team = _team_from(t, srv.teams_dir)
    name = body.get("name") or team.name
    path = _team_path(srv.teams_dir, name)
    team.save(path)
    return {"saved": path.stem, "file": path.name}


def api_team_delete(srv, q, body, name):
    p = _team_path(srv.teams_dir, name, must_exist=True)
    p.unlink()
    return {"deleted": p.stem}


def api_validate(srv, q, body):
    from ..rules import validate_team
    cid = body.get("catalog") or "synthetic"
    team = _team_from(body.get("team"), srv.teams_dir)
    rep = validate_team(team, _catalog(cid), _rules(cid), inventory=body.get("inventory"),
                        stacking_assumptions=body.get("stacking"))
    out = rep.to_dict()
    out["catalog"] = cid
    return out


def api_battle(srv, q, body):
    from ..sim.montecarlo import run_battle, battle_report
    cid = body.get("catalog") or "synthetic"
    a = _team_from(body.get("team_a"), srv.teams_dir)
    b = _team_from(body.get("team_b"), srv.teams_dir)
    seed = _int(body, "seed", 1, -2**31, 2**31 - 1)
    res = run_battle(a, b, _catalog(cid), _asm(body), seed=seed, priors=_priors(cid, body), log=False)
    rep = battle_report(res)
    rep["catalog"] = cid
    rep["teams"] = {"A": a.name, "B": b.name}
    return rep


def api_sim(srv, q, body):
    from ..sim.montecarlo import simulate
    cid = body.get("catalog") or "synthetic"
    a = _team_from(body.get("team_a"), srv.teams_dir)
    b = _team_from(body.get("team_b"), srv.teams_dir)
    n = _int(body, "n", 1000, 1, SIM_N_MAX)
    seed = _int(body, "seed", 1, -2**31, 2**31 - 1)
    s = simulate(a, b, _catalog(cid), _asm(body), n=n, seed=seed, priors=_priors(cid, body),
                 workers=1 if n < 2000 else None)
    s["catalog"] = cid
    s["teams"] = {"A": a.name, "B": b.name}
    return s


def api_compare(srv, q, body):
    from ..sim.montecarlo import compare
    cid = body.get("catalog") or "synthetic"
    a = _team_from(body.get("team_a"), srv.teams_dir)
    a2 = _team_from(body.get("team_a2"), srv.teams_dir)
    opps = [_team_from(o, srv.teams_dir) for o in body.get("opponents") or []]
    if not opps:
        raise ApiError("нужен хотя бы один соперник (opponents)")
    names = [o.name for o in opps]
    for i, o in enumerate(opps):          # compare() keys results by opponent name
        if names.count(o.name) > 1:
            o.name = f"{o.name} #{i + 1}"
    n = _int(body, "n", 300, 1, COMPARE_N_MAX)
    out = compare(a, a2, opps, _catalog(cid), _asm(body), n=n, seed=_int(body, "seed", 7, 0, 2**31 - 1),
                  priors=_priors(cid, body))
    out["teams"] = {"a": a.name, "a2": a2.name}
    out["n"] = n
    return out


def api_matchup(srv, q, body):
    from ..matchup import MatchupAnalyzer
    cid = body.get("catalog") or "synthetic"
    my = _team_from(body.get("my"), srv.teams_dir)
    enemy = _team_from(body.get("enemy"), srv.teams_dir)
    n = _int(body, "n", 300, 10, MATCHUP_N_MAX)
    an = MatchupAnalyzer(_catalog(cid), _asm(body), n=n, seed=_int(body, "seed", 21, 0, 2**31 - 1),
                         priors=_priors(cid, body))
    out = {"analysis": an.analyze(my, enemy, key_heroes=body.get("key_heroes") or None)}
    small = min(n, SUGGEST_N_MAX)
    if body.get("suggest"):
        out["suggest"] = an.suggest(my, enemy, n=small)
        out["suggest"].pop("all", None)
    if body.get("ablation"):
        out["ablation"] = an.ablation(my, enemy, n=small)
    if body.get("best_formation"):
        out["best_formation"] = an.best_formation(my, enemy, n=small)
    out["teams"] = {"my": my.name, "enemy": enemy.name}
    out["label"] = "MODEL ANALYSIS - не реальный процент побед"
    return out


def api_matrix(srv, q, body):
    from ..sim.montecarlo import simulate
    cid = body.get("catalog") or "synthetic"
    teams = [_team_from(t, srv.teams_dir) for t in body.get("teams") or []]
    if len(teams) < 2:
        raise ApiError("нужно минимум 2 команды")
    if len(teams) > 8:
        raise ApiError("не более 8 команд (время расчёта растёт квадратично)")
    n = _int(body, "n", 100, 1, MATRIX_N_MAX)
    cat, asm, pri = _catalog(cid), _asm(body), _priors(cid, body)
    seed = _int(body, "seed", 11, 0, 2**31 - 1)
    names = [t.name for t in teams]
    matrix, rows = [], []
    for i, ta in enumerate(teams):
        row = []
        for j, tb in enumerate(teams):
            if i == j:
                row.append(None)
                continue
            s = simulate(ta, tb, cat, asm.copy(), n=n, seed=seed, priors=pri, workers=1)
            cell = {"model_win_rate": s["model_win_rate"], "ci95": list(s["ci95"]), "draws": s["draws"]}
            row.append(cell)
            rows.append({"team": names[i], "vs": names[j], **cell})
        matrix.append(row)
    return {"label": "MODEL counterpick matrix: строка (сторона A) против столбца (сторона B); модельный WR",
            "teams": names, "n": n, "matrix": matrix, "pairs": rows, "catalog": cid}


def api_optimize_equipment(srv, q, body):
    from ..optimize.search import cp_sat_equipment
    cid = body.get("catalog") or "synthetic"
    team = _team_from(body.get("team"), srv.teams_dir)
    inv = body.get("inventory") or {}
    if not isinstance(inv, dict) or not inv:
        raise ApiError("нужен инвентарь {\"limbs:id\": кол-во, \"decorations:id\": кол-во}")
    try:
        inv = {str(k): int(v) for k, v in inv.items()}
    except (TypeError, ValueError):
        raise ApiError("количества в инвентаре должны быть целыми") from None
    res = cp_sat_equipment(team, _catalog(cid), inv, time_limit=float(body.get("time_limit") or 10.0))
    res["label"] = "Эвристическая оценка по весам статов (не процент побед); проверяйте Monte Carlo"
    return res


def api_meta(srv, q, body):
    from .. import meta
    return meta.query(region=q.get("region") or None, kind=q.get("kind") or None, status=q.get("status") or None)


def api_meta_forecast(srv, q, body):
    from .. import meta
    return meta.forecast_ru()


def api_validation(srv, q, body):
    from .. import validation
    return {"status": validation.status(), "records": validation.load_records(),
            "journal": validation._read(validation.JOURNAL)}


def api_resources_plan(srv, q, body):
    from .. import resources
    ups, budget = body.get("upgrades"), body.get("budget")
    if not isinstance(ups, list) or not isinstance(budget, dict):
        raise ApiError("нужны upgrades (список) и budget (объект)")
    for u in ups:
        if not isinstance(u, dict) or "id" not in u:
            raise ApiError("каждое улучшение должно иметь id")
    return resources.plan(ups, budget)


def api_export(srv, q, body):
    """Returns (bytes, content_type, filename) instead of JSON."""
    from ..export import export
    rep = body.get("report")
    fmt = (body.get("fmt") or "xlsx").lower()
    if fmt not in EXPORT_FORMATS:
        raise ApiError(f"fmt должен быть одним из {sorted(EXPORT_FORMATS)}")
    if not isinstance(rep, dict):
        rep = {"rows": rep} if isinstance(rep, list) else None
    if rep is None:
        raise ApiError("нужен report (объект)")
    base = _safe_name(body.get("name") or "luna_report")
    with tempfile.TemporaryDirectory(prefix="luna_export_") as td:
        files = export(rep, Path(td) / f"{base}.{fmt}", fmt)
        if fmt == "csv":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for f in files:
                    z.write(f, Path(f).name)
            return buf.getvalue(), "application/zip", f"{base}_csv.zip"
        data = Path(files[0]).read_bytes()
    ctype = {"xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "html": "text/html; charset=utf-8", "json": "application/json; charset=utf-8"}[fmt]
    return data, ctype, f"{base}.{fmt}"


GET_ROUTES = {
    "/api/catalogs": api_catalogs, "/api/catalog": api_catalog, "/api/schema": api_schema,
    "/api/kb/status": api_kb_status, "/api/kb/hero": api_kb_hero, "/api/glossary": api_glossary,
    "/api/assumptions": api_assumptions, "/api/portraits": api_portraits, "/api/teams": api_teams_list,
    "/api/meta": api_meta, "/api/meta/forecast": api_meta_forecast, "/api/validation": api_validation,
}
POST_ROUTES = {
    "/api/teams": api_team_save, "/api/validate": api_validate, "/api/battle": api_battle, "/api/sim": api_sim,
    "/api/compare": api_compare, "/api/matchup": api_matchup, "/api/matrix": api_matrix,
    "/api/optimize/equipment": api_optimize_equipment, "/api/resources/plan": api_resources_plan,
}


# ============================================================================ HTTP layer
class Handler(BaseHTTPRequestHandler):
    server_version = "LunaDashboard/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the console quiet unless asked
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    # ---------------------------------------------------------------- responses
    def _send(self, status: int, data: bytes, ctype: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, obj, status: int = 200):
        data = json.dumps(_jsonable(obj), ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._send(status, data, "application/json; charset=utf-8")

    def _error(self, msg: str, status: int):
        self._json({"error": msg}, status)

    def _file(self, path: Path):
        if not path.is_file():
            return self._error("не найдено", 404)
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript",):
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20 * 1024 * 1024:
            raise ApiError("слишком большой запрос", 413)
        raw = self.rfile.read(n) if n else b""
        if not raw:
            return {}
        try:
            d = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ApiError(f"неверный JSON: {e}") from None
        if not isinstance(d, dict):
            raise ApiError("тело запроса должно быть JSON-объектом")
        return d

    def _dispatch(self, method: str):
        url = urlparse(self.path)
        path = unquote(url.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if method in ("GET", "HEAD"):
                if path in ("/", "/index.html"):
                    return self._file(STATIC / "index.html")
                if path.startswith("/static/"):
                    return self._file(_inside(STATIC, path[len("/static/"):]))
                if path.startswith("/portraits/"):
                    p = _inside(PORTRAITS_DIR, path[len("/portraits/"):])
                    if p.suffix.lower() not in PORTRAIT_EXT:
                        raise ApiError("не найдено", 404)
                    return self._file(p)
                if path == "/favicon.ico":
                    return self._send(204, b"", "image/x-icon")
                if path in GET_ROUTES:
                    return self._json(GET_ROUTES[path](self.server, q, {}))
                if path.startswith("/api/teams/"):
                    return self._json(api_team_get(self.server, q, {}, path[len("/api/teams/"):]))
                raise ApiError("не найдено", 404)
            if method == "POST":
                body = self._body()
                if path == "/api/export":
                    data, ctype, fname = api_export(self.server, q, body)
                    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", fname)
                    from urllib.parse import quote
                    return self._send(200, data, ctype, {
                        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(fname)}"})
                if path in POST_ROUTES:
                    return self._json(POST_ROUTES[path](self.server, q, body))
                raise ApiError("не найдено", 404)
            if method == "DELETE":
                if path.startswith("/api/teams/"):
                    return self._json(api_team_delete(self.server, q, {}, path[len("/api/teams/"):]))
                raise ApiError("не найдено", 404)
            raise ApiError("метод не поддерживается", 405)
        except ApiError as e:
            return self._error(str(e), e.status)
        except (KeyError, ValueError, TypeError) as e:
            # Typical causes: id missing from the chosen catalog, UNKNOWN stat without priors,
            # critical assumption not set. These are input problems -> 400 with the module's message.
            msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
            return self._error(f"{type(e).__name__}: {msg}", 400)
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            if getattr(self.server, "verbose", False):
                traceback.print_exc()
            name = type(e).__name__
            status = 400 if name in ("AssumptionRequired", "MixedBalanceError") else 500
            return self._error(f"{name}: {e}", status)

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")


def _inside(base: Path, rel: str) -> Path:
    """Resolve rel under base; refuse path traversal."""
    p = (base / rel).resolve()
    if base.resolve() not in p.parents:
        raise ApiError("не найдено", 404)
    return p


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, teams_dir: Path | None = None, verbose: bool = False):
        super().__init__(addr, Handler)
        self.teams_dir = Path(teams_dir or TEAMS_DIR)
        self.teams_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose


def make_server(host: str = "127.0.0.1", port: int = 8765, teams_dir: Path | None = None,
                verbose: bool = False) -> DashboardServer:
    return DashboardServer((host, port), teams_dir=teams_dir, verbose=verbose)


def serve(host: str = "127.0.0.1", port: int = 8765, teams_dir: Path | None = None) -> None:
    srv = make_server(host, port, teams_dir, verbose=True)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(f"ВНИМАНИЕ: сервер слушает {host} - он доступен из сети, аутентификации нет.")
    print(f"Luna dashboard: http://{host}:{srv.server_address[1]}/  (Ctrl+C - остановить)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
