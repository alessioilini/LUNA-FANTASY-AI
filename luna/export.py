"""Export any report (nested dict) to XLSX / CSV / HTML. Tables are found automatically:
a list of dicts becomes a sheet/table; scalars go to a 'summary' table."""
from __future__ import annotations

import csv
import html
import json
from pathlib import Path


def _flatten_tables(rep: dict, prefix: str = "") -> tuple[dict, dict]:
    tables, scalars = {}, {}
    for k, v in rep.items():
        name = f"{prefix}{k}"
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            tables[name] = v
        elif isinstance(v, dict) and v and all(isinstance(x, dict) for x in v.values()) and len(v) <= 500:
            tables[name] = [{"key": kk, **{a: b for a, b in vv.items() if not isinstance(b, (dict, list))}} for kk, vv in v.items()]
            sub_t, sub_s = _flatten_tables({kk: vv for kk, vv in v.items()}, prefix=f"{name}.")
            for tk, tv in sub_t.items():
                tables.setdefault(tk, tv)
        elif isinstance(v, dict):
            st, ss = _flatten_tables(v, prefix=f"{name}.")
            tables.update(st)
            scalars.update(ss)
        else:
            scalars[name] = v if not isinstance(v, (list, tuple)) else json.dumps(v, ensure_ascii=False, default=str)
    return tables, scalars


def _cell(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (list, tuple, dict)):
        return json.dumps(v, ensure_ascii=False, default=str)
    return v


def export(rep: dict, path: str | Path, fmt: str | None = None) -> list[str]:
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    tables, scalars = _flatten_tables(rep)
    tables = {"summary": [{"field": k, "value": v} for k, v in scalars.items()], **tables}
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "xlsx":
        import openpyxl
        from openpyxl.styles import Font
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        used = set()
        for name, rows in tables.items():
            sname = name[-31:].replace("/", "_").replace(":", "_").replace("[", "(").replace("]", ")") or "sheet"
            while sname in used:
                sname = (sname[:28] + str(len(used)))[-31:]
            used.add(sname)
            ws = wb.create_sheet(sname)
            cols = list(dict.fromkeys(c for r in rows for c in r))
            ws.append(cols)
            for c in ws[1]:
                c.font = Font(bold=True)
            for r in rows:
                ws.append([_cell(r.get(c)) for c in cols])
        wb.save(path)
        return [str(path)]
    if fmt == "csv":
        out = []
        base = path.with_suffix("")
        for name, rows in tables.items():
            p = Path(f"{base}.{name.replace('/', '_')}.csv")
            cols = list(dict.fromkeys(c for r in rows for c in r))
            with open(p, "w", encoding="utf-8-sig", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(cols)
                for r in rows:
                    w.writerow([_cell(r.get(c)) for c in cols])
            out.append(str(p))
        return out
    if fmt == "html":
        title = html.escape(str(rep.get("title") or rep.get("label") or "Luna Fantasy AI report"))
        parts = [f"<!doctype html><html lang='ru'><meta charset='utf-8'><title>{title}</title>",
                 "<style>body{font-family:system-ui,sans-serif;margin:16px;background:#fff;color:#111}"
                 "table{border-collapse:collapse;margin:8px 0 24px;font-size:13px}td,th{border:1px solid #ccc;padding:4px 8px}"
                 "th{background:#f0f0f5}.warn{background:#fff4d6;padding:8px;border-left:4px solid #e0a800}"
                 "@media (prefers-color-scheme: dark){body{background:#111;color:#eee}th{background:#222}td,th{border-color:#444}.warn{background:#3a3000}}</style>",
                 f"<h1>{title}</h1><p class='warn'>Модельные результаты не являются реальным процентом побед, пока симулятор "
                 "не прошёл проверку на реальных боях.</p>"]
        for name, rows in tables.items():
            cols = list(dict.fromkeys(c for r in rows for c in r))
            parts.append(f"<h2>{html.escape(name)}</h2><table><tr>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in cols) + "</tr>")
            for r in rows:
                parts.append("<tr>" + "".join(f"<td>{html.escape(str(_cell(r.get(c, ''))))}</td>" for c in cols) + "</tr>")
            parts.append("</table>")
        path.write_text("\n".join(parts), encoding="utf-8")
        return [str(path)]
    if fmt == "json":
        path.write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return [str(path)]
    raise ValueError(f"unknown format {fmt}")
