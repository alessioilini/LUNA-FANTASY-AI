"""Battle validation (stage 11): import real results, log simulator-vs-game discrepancies, and
calibrate UNKNOWN formulas on a TRAIN set while reporting on a separate TEST set.

Status rule: the simulator is "NOT VALIDATED" until a held-out test set of >= 20 real battles has a
Brier score better than the 0.25 coin-flip baseline. Until then every win rate is a model number.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

from .engine.assumptions import AssumptionSet
from .localization import resolve_hero
from .model import Catalog, Team
from .sim.montecarlo import simulate, PriorBook

ROOT = Path(__file__).resolve().parents[1]
VDIR = ROOT / "data" / "validation"
JOURNAL = VDIR / "discrepancies.jsonl"
RECORDS = VDIR / "battles.jsonl"
EVIDENCE = VDIR / "evidence"
CLAIMS = VDIR / "old_recommendations.jsonl"
MIN_CALIBRATION = 10
MIN_TEST_FOR_VALIDATED = 20

COLS = {
    "date": ["date", "дата"], "mode": ["mode", "режим"], "result": ["result", "результат", "итог"],
    "rounds": ["rounds", "раунды", "раундов"], "my_team": ["my_team", "моя команда", "моя_команда"],
    "enemy_team": ["enemy_team", "соперник", "команда соперника"], "notes": ["notes", "заметки", "комментарий"],
    "enemy_power": ["enemy_power", "мощь соперника", "бр соперника"], "my_power": ["my_power", "моя мощь", "бр"],
}
RESULT_MAP = {"win": "win", "победа": "win", "w": "win", "1": "win", "loss": "loss", "поражение": "loss", "l": "loss",
              "0": "loss", "draw": "draw", "ничья": "draw"}


def _norm_header(h: str) -> str | None:
    h = (h or "").strip().lower()
    for k, alts in COLS.items():
        if h in alts:
            return k
    return None


def _split_team(s: str) -> list[str]:
    names = [x.strip() for x in re.split(r"[,;/|]", s or "") if x.strip()]
    return [resolve_hero(n) or n for n in names]


def _row_to_record(row: dict, source: str, idx: int) -> dict:
    rec = {"id": f"{Path(source).stem}#{idx}", "source": source, "imported": dt.date.today().isoformat()}
    for h, v in row.items():
        k = _norm_header(str(h))
        if k:
            rec[k] = v
    rec["result"] = RESULT_MAP.get(str(rec.get("result", "")).strip().lower(), "unknown")
    for k in ("my_team", "enemy_team"):
        rec[k] = _split_team(str(rec.get(k, "")))
    try:
        rec["rounds"] = int(rec["rounds"]) if rec.get("rounds") not in (None, "") else None
    except (TypeError, ValueError):
        rec["rounds"] = None
    if isinstance(rec.get("date"), (dt.date, dt.datetime)):
        rec["date"] = rec["date"].isoformat()[:10]
    return rec


def import_table(path: str | Path) -> list[dict]:
    """CSV or XLSX battle history -> normalised records (appended to data/validation/battles.jsonl)."""
    path = Path(path)
    rows = []
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        it = ws.iter_rows(values_only=True)
        header = [str(h or "") for h in next(it)]
        for r in it:
            if any(c is not None for c in r):
                rows.append(dict(zip(header, r)))
    else:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    recs = [_row_to_record(r, str(path), i) for i, r in enumerate(rows)]
    _append(RECORDS, recs)
    return recs


def import_battle_json(path: str | Path) -> dict:
    """Detailed PvP report: {"date","mode","result","rounds","my_team": Team dict, "enemy_team": Team dict, ...}.
    Records with full Team dicts are usable for calibration."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    d.setdefault("id", Path(path).stem)
    d["source"] = str(path)
    d["result"] = RESULT_MAP.get(str(d.get("result", "")).lower(), d.get("result", "unknown"))
    _append(RECORDS, [d])
    return d


def import_markdown(path: str | Path) -> list[dict]:
    """Old recommendations: each bullet/paragraph becomes an UNVERIFIED claim with detected heroes."""
    text = Path(path).read_text(encoding="utf-8")
    claims = []
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip().lstrip("-*0123456789.) ").strip()
        if len(s) < 8 or s.startswith("#"):
            continue
        heroes = sorted({resolve_hero(w) for w in re.findall(r"[\wА-Яа-яЁё]+", s) if resolve_hero(w)})
        claims.append({"source": f"{path}:{i}", "text": s, "heroes": heroes, "status": "unverified_old_recommendation",
                       "imported": dt.date.today().isoformat()})
    _append(CLAIMS, claims)
    return claims


def register_screenshot(path: str | Path, kind: str = "hero", hero_hint: str | None = None) -> dict:
    """Store a screenshot as evidence + create a manual transcription template.
    OCR is not attempted (no OCR engine installed); values must be transcribed and reviewed."""
    p = Path(path)
    h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    dst = EVIDENCE / f"{h}{p.suffix.lower()}"
    shutil.copy2(p, dst)
    tmpl = {"evidence": dst.name, "sha256_16": h, "kind": kind, "hero": hero_hint, "region": "RU",
            "client_version": "UNKNOWN", "captured": dt.date.today().isoformat(),
            "fields": {"ATK": None, "HP": None, "DEF": None, "SPD": None, "CRIT": None, "CRIT_DMG": None,
                       "level": None, "stars": None, "awakening": None},
            "stats_mode": "panel", "ocr": "not_available", "status": "needs_transcription"}
    (EVIDENCE / f"{h}.json").write_text(json.dumps(tmpl, ensure_ascii=False, indent=1), encoding="utf-8")
    return tmpl


def extract_video_frames(path: str | Path, every_s: float = 2.0, limit: int = 120) -> dict:
    """Extract keyframes for manual review (ffmpeg). Automatic battle parsing from video is NOT implemented."""
    if not shutil.which("ffmpeg"):
        return {"status": "ffmpeg_missing"}
    p = Path(path)
    h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    out = EVIDENCE / f"video_{h}"
    out.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-loglevel", "error", "-i", str(p), "-vf", f"fps=1/{every_s}", "-frames:v", str(limit),
           str(out / "frame_%04d.png")]
    r = subprocess.run(cmd, capture_output=True, text=True)
    frames = sorted(x.name for x in out.glob("frame_*.png"))
    return {"status": "ok" if r.returncode == 0 else "ffmpeg_error", "stderr": r.stderr[-500:], "dir": str(out),
            "frames": len(frames), "note": "кадры для ручной разметки; автоматический разбор видео не реализован"}


# ------------------------------------------------------------------ journal
def log_discrepancy(record: dict, predicted: dict, note: str = "") -> dict:
    actual = 1.0 if record.get("result") == "win" else 0.0 if record.get("result") == "loss" else 0.5
    p = predicted["model_win_rate"]
    e = {"battle_id": record.get("id"), "date": record.get("date"), "actual": record.get("result"),
         "predicted_wr": round(p, 4), "ci95": predicted.get("ci95"), "abs_error": round(abs(actual - p), 4),
         "brier": round((p - actual) ** 2, 4), "actual_rounds": record.get("rounds"),
         "predicted_rounds": round(predicted.get("avg_rounds", 0), 2),
         "assumptions": predicted.get("assumption_values"), "logged": dt.datetime.now().isoformat(timespec="seconds"),
         "note": note}
    _append(JOURNAL, [e])
    return e


def load_records() -> list[dict]:
    return _read(RECORDS)


def _append(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ------------------------------------------------------------------ calibration
def split_train_test(records: list[dict], test_frac: float = 0.3) -> tuple[list[dict], list[dict]]:
    """Chronological split: never test on battles older than the training data."""
    recs = sorted(records, key=lambda r: (str(r.get("date") or ""), str(r.get("id"))))
    k = max(1, int(round(len(recs) * (1 - test_frac))))
    return recs[:k], recs[k:]


def _score(records, cat, asm, n, seed, priors):
    briers, lls, rows = [], [], []
    for r in records:
        my, en = Team.from_dict(r["my_team"]), Team.from_dict(r["enemy_team"])
        s = simulate(my, en, cat, asm, n=n, seed=seed, priors=priors, workers=1)
        p = min(max(s["model_win_rate"], 1e-3), 1 - 1e-3)
        y = 1.0 if r["result"] == "win" else 0.0
        briers.append((p - y) ** 2)
        lls.append(-(y * math.log(p) + (1 - y) * math.log(1 - p)))
        rows.append({"id": r.get("id"), "p": p, "y": y})
    n_ = max(1, len(records))
    return {"brier": sum(briers) / n_, "logloss": sum(lls) / n_, "rows": rows}


def calibrate(cat: Catalog, base: AssumptionSet, grid: dict, records: list[dict] | None = None, n: int = 100,
              seed: int = 99, priors: PriorBook | None = None, test_frac: float = 0.3, force: bool = False) -> dict:
    """Grid search over UNKNOWN assumption values on the train split; report the held-out test score.
    grid: {"dmg.k_def": [5000, 10000, 20000], "order.tie_break": [[...], [...]]}"""
    records = [r for r in (records if records is not None else load_records())
               if isinstance(r.get("my_team"), dict) and isinstance(r.get("enemy_team"), dict) and r.get("result") in ("win", "loss")]
    if len(records) < MIN_CALIBRATION and not force:
        return {"status": "insufficient_data", "usable_records": len(records), "required": MIN_CALIBRATION,
                "message": "Калибровка по одному-нескольким боям запрещена: соберите ≥10 боёв с полными составами."}
    train, test = split_train_test(records, test_frac)
    import itertools
    keys = list(grid)
    results = []
    for combo in itertools.product(*[grid[k] for k in keys]):
        a = base.copy(**dict(zip(keys, combo)))
        sc = _score(train, cat, a, n, seed, priors)
        results.append({"params": dict(zip(keys, combo)), "train_brier": sc["brier"], "train_logloss": sc["logloss"]})
    results.sort(key=lambda r: r["train_brier"])
    best = results[0]
    a = base.copy(**best["params"])
    test_sc = _score(test, cat, a, n, seed, priors) if test else {"brier": None, "logloss": None}
    validated = bool(test) and len(test) >= MIN_TEST_FOR_VALIDATED and test_sc["brier"] < 0.25
    return {"status": "ok", "train_size": len(train), "test_size": len(test), "best_params": best["params"],
            "train_brier": best["train_brier"], "test_brier": test_sc["brier"], "test_logloss": test_sc["logloss"],
            "baseline_brier": 0.25, "simulator_validated": validated, "grid": results}


def status() -> dict:
    recs = load_records()
    j = _read(JOURNAL)
    full = [r for r in recs if isinstance(r.get("my_team"), dict) and isinstance(r.get("enemy_team"), dict)]
    return {"records": len(recs), "records_with_full_teams": len(full), "journal_entries": len(j),
            "mean_brier": (sum(e["brier"] for e in j) / len(j)) if j else None,
            "simulator_validated": False if len(full) < MIN_TEST_FOR_VALIDATED else "run `luna validate calibrate`",
            "rule": f"validated only if a chronological test set of >= {MIN_TEST_FOR_VALIDATED} real battles beats Brier 0.25"}
