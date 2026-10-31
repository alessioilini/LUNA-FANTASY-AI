/* Luna Fantasy AI dashboard - vanilla JS single-page app (no build step, no CDN).
 * All game numbers come from the server (catalog / KB / simulator). This file never invents values:
 * empty stats stay empty or "UNKNOWN", and every simulated number is shown as a MODEL result. */
"use strict";

// ============================================================================ state
const S = {
  catalogs: [], cid: null, cat: null, schema: null, glossary: {}, portraits: {}, saved: [],
  team: null, curHero: 0, selSlot: null, results: {}, tab: "heroes", heroFilter: "all", kbCache: {},
};
const MODEL_NOTE = "Модельные результаты, не реальный процент побед";
const SECTION_RU = {
  sigils: "Сигилы", talents: "Таланты", limbs: "Лимбы", decorations: "Украшения", pets: "Питомцы",
  charm_cards: "Карты прелестей", runes: "Руны", princess_weapon_parts: "Оружие принцессы", relics: "Реликты",
};

// ============================================================================ tiny DOM helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const $ = (sel, root = document) => root.querySelector(sel);
const clone = (o) => JSON.parse(JSON.stringify(o));

function store(key, val) {
  try {
    if (val === undefined) return JSON.parse(localStorage.getItem("luna." + key));
    localStorage.setItem("luna." + key, JSON.stringify(val));
  } catch (e) { return null; }
  return null;
}

function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, isErr ? 7000 : 3000);
}

// ============================================================================ formatting
function num(v, digits) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v !== "number") return String(v);
  if (!isFinite(v)) return String(v);
  const a = Math.abs(v);
  const d = digits !== undefined ? digits : (a >= 1000 ? 0 : a >= 10 ? 1 : a === Math.round(a) ? 0 : 3);
  return v.toLocaleString("ru-RU", { maximumFractionDigits: d, minimumFractionDigits: 0 });
}
const pct = (v, d = 1) => (typeof v === "number" ? (v * 100).toFixed(d) + "%" : "—");
const ci = (c) => (Array.isArray(c) ? `${pct(c[0])} … ${pct(c[1])}` : "—");

function cellText(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return num(v);
  if (typeof v === "boolean") return v ? "да" : "нет";
  if (Array.isArray(v)) return v.map((x) => (typeof x === "object" ? JSON.stringify(x) : cellText(x))).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** Generic table. cols: [{k, t, num, f(row) -> node|text}] or list of keys. */
function table(rows, cols, opts = {}) {
  rows = rows || [];
  if (!cols) cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  cols = cols.map((c) => (typeof c === "string" ? { k: c, t: c } : c));
  if (!rows.length) return h("div", { class: "muted small" }, opts.empty || "Нет данных");
  return h("div", { class: "table-wrap" },
    h("table", { class: opts.class || "" },
      h("thead", {}, h("tr", {}, cols.map((c) => h("th", { class: c.num ? "num" : "" }, c.t)))),
      h("tbody", {}, rows.map((r) => h("tr", { class: opts.rowClass ? opts.rowClass(r) : "" },
        cols.map((c) => {
          const v = c.f ? c.f(r) : r[c.k];
          return h("td", { class: c.num ? "num" : "" }, v instanceof Node ? v : cellText(v));
        }))))));
}

function kpi(label, value, sub) {
  return h("div", { class: "kpi" }, h("div", { class: "k" }, label), h("div", { class: "v" }, value), sub ? h("div", { class: "s" }, sub) : null);
}
function badge(text, cls) { return h("span", { class: "badge " + (cls || String(text)) }, text); }
function modelLabel(text) { return h("div", { class: "model-label" }, "МОДЕЛЬ · " + (text || MODEL_NOTE)); }

// ============================================================================ API
async function api(path, body, method) {
  const opts = { method: method || (body !== undefined ? "POST" : "GET"), headers: {} };
  if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, opts);
  let data;
  try { data = await r.json(); } catch (e) { throw new Error(`HTTP ${r.status}: ответ не JSON`); }
  if (!r.ok || (data && data.error)) throw new Error(data && data.error ? data.error : `HTTP ${r.status}`);
  return data;
}

async function exportReport(report, fmt, name) {
  try {
    const r = await fetch("/api/export", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ report, fmt, name: name || "luna_report" }),
    });
    if (!r.ok) {
      let msg = `HTTP ${r.status}`;
      try { msg = (await r.json()).error || msg; } catch (e) { /* binary */ }
      throw new Error(msg);
    }
    const blob = await r.blob();
    const cd = r.headers.get("Content-Disposition") || "";
    const m = /filename\*=UTF-8''([^;]+)/.exec(cd) || /filename="([^"]+)"/.exec(cd);
    const fname = m ? decodeURIComponent(m[1]) : `${name || "report"}.${fmt === "csv" ? "zip" : fmt}`;
    const url = URL.createObjectURL(blob);
    const a = h("a", { href: url, download: fname });
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    toast(`Экспорт: ${fname}`);
  } catch (e) { toast("Ошибка экспорта: " + e.message, true); }
}

function exportBar(getReport, name) {
  return h("div", { class: "export-bar" }, h("span", { class: "label" }, "Экспорт:"),
    ["xlsx", "csv", "html"].map((f) => h("button", {
      class: "btn ghost small", type: "button", "data-export": f,
      onclick: () => { const r = getReport(); if (r) exportReport(r, f, name); else toast("Нет результата для экспорта", true); },
    }, f.toUpperCase())));
}

/** Run an async job bound to a button, render the result into `box` and remember it under `key`. */
async function runJob(btn, box, key, job, render, exportName) {
  const old = btn.textContent;
  btn.disabled = true;
  btn.replaceChildren(h("span", { class: "spinner" }), "Считаю…");
  box.replaceChildren(h("div", { class: "muted" }, h("span", { class: "spinner" }), "Выполняется расчёт…"));
  try {
    const res = await job();
    S.results[key] = { res, render, exportName };
    showResult(key, box);
  } catch (e) {
    box.replaceChildren(h("div", { class: "err-box" }, "Ошибка: " + e.message));
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

function showResult(key, box) {
  const r = S.results[key];
  if (!r) { box.replaceChildren(); return; }
  box.replaceChildren(
    h("div", { class: "row center" }, h("div", { class: "spacer" }), exportBar(() => S.results[key] && S.results[key].res, r.exportName || key)),
    r.render(r.res));
}

// ============================================================================ catalog & names
const sec = (name) => (S.cat && S.cat[name]) || [];
const byId = (name, id) => sec(name).find((x) => x.id === id);
const catKind = () => (S.catalogs.find((c) => c.id === S.cid) || {}).kind;

function gloss(hid) { return S.glossary["hero." + hid] || null; }
function heroNames(hid) {
  const g = gloss(hid) || {};
  const c = (byId("heroes", hid) || {}).names || {};
  return { ru: g.ru || c.ru || null, en: g.en || c.en || hid, jp: g.jp || c.jp || null, ruStatus: g.ru_status || null };
}
function heroName(hid) {
  if (hid === "__team__") return "командный источник";
  const n = heroNames(hid);
  return n.ru || n.en || hid;
}
function itemLabel(section, id) {
  const e = byId(section, id);
  if (!e) return id;
  const nm = e.names ? (e.names.ru || e.names.en) : e.name;
  return nm ? `${nm} (${id})` : id;
}

function initials(name) {
  const p = String(name || "?").replace(/[^\p{L}\p{N} ]/gu, " ").trim().split(/\s+/);
  return ((p[0] || "?")[0] + (p[1] ? p[1][0] : (p[0] || "")[1] || "")).toUpperCase();
}
function hue(s) { let x = 0; for (const ch of String(s)) x = (x * 31 + ch.charCodeAt(0)) % 360; return x; }
function avatar(hid, small) {
  const src = S.portraits[hid];
  const el = h("div", { class: "avatar" + (small ? " sm" : ""), title: heroName(hid), style: { background: `hsl(${hue(hid)} 45% 45%)` } });
  if (src) el.append(h("img", { src, alt: heroName(hid), loading: "lazy" }));
  else el.textContent = initials(heroNames(hid).en || hid);
  return el;
}

// ============================================================================ team model (mirrors luna.model.Team.to_dict)
function newHero(hid) {
  const c = byId("heroes", hid) || {};
  return {
    hero_id: hid,
    progression: { level: "UNKNOWN", stars: "UNKNOWN", awakening: "UNKNOWN", skill_levels: {}, upgrades: [] },
    stats: clone(c.base_stats || {}), stats_mode: c.stats_mode || "base",
    sigils: [], talents: [], limbs: [], decorations: [], pets: [], charm_cards: [], extra_mods: [], abilities_override: null,
  };
}
function newTeam(name) {
  return {
    name: name || "Моя команда", heroes: [], formation: {}, formation_id: null, faction_bonus: [], global_stats: [],
    runes: [], princess_weapon: [], relics: [], region: (S.cat && S.cat.region) || "RU",
    balance_version: (S.cat && S.cat.balance_version) || "UNKNOWN", notes: "", status: "hypothetical",
  };
}
function saveLocal() { store("team." + S.cid, S.team); }
function freePos(team) {
  const used = new Set(Object.values(team.formation).map(Number));
  for (let i = 0; i < 6; i++) if (!used.has(i)) return i;
  return team.heroes.length;
}

/** Team sources for pickers: current editor team, catalog samples, saved files. */
function teamOptions() {
  const opts = [{ v: "cur", t: `Текущая команда (редактор): ${S.team ? S.team.name : ""}` }];
  (S.cat.sample_teams || []).forEach((t, i) => opts.push({ v: "sample:" + i, t: `Пример: ${t.name}` }));
  // Only saved teams of the selected catalog's region + balance version (mixing versions is an error).
  S.saved.filter((t) => t.region === S.cat.region && t.balance_version === S.cat.balance_version)
    .forEach((t) => opts.push({ v: "saved:" + t.name, t: `Сохранена: ${t.name}` }));
  return opts;
}
function teamPicker(id, def) {
  const sel = h("select", { id }, teamOptions().map((o) => h("option", { value: o.v }, o.t)));
  const remembered = store("pick." + id);
  const vals = [...sel.options].map((o) => o.value);
  sel.value = vals.includes(remembered) ? remembered : (vals.includes(def) ? def : "cur");
  sel.addEventListener("change", () => store("pick." + id, sel.value));
  return sel;
}
async function resolveTeam(v) {
  if (v === "cur") return clone(S.team);
  if (v.startsWith("sample:")) return clone(S.cat.sample_teams[+v.slice(7)]);
  if (v.startsWith("saved:")) return api("/api/teams/" + encodeURIComponent(v.slice(6)));
  throw new Error("неизвестный источник команды");
}

// ============================================================================ simulation controls
function simControls(prefix, opts = {}) {
  const presets = (S.schema && S.schema.presets) || ["exploratory_v1"];
  const forced = catKind() === "whatif";
  const c = {
    preset: h("select", { id: prefix + "-preset" }, presets.map((p) => h("option", { value: p }, p))),
    seed: h("input", { id: prefix + "-seed", type: "number", value: opts.seed || 1 }),
    n: h("input", { id: prefix + "-n", type: "number", min: 1, max: opts.nMax || 5000, value: opts.n || 300 }),
    priors: h("input", { id: prefix + "-priors", type: "checkbox", checked: forced, disabled: forced }),
    overrides: h("textarea", { id: prefix + "-ovr", rows: 3, style: { minHeight: "60px" }, placeholder: '{"battle.draw_result": "hp_percent"}' }),
  };
  c.values = () => {
    let overrides = {};
    const txt = c.overrides.value.trim();
    if (txt) {
      try { overrides = JSON.parse(txt); } catch (e) { throw new Error("overrides: неверный JSON - " + e.message); }
    }
    return { preset: c.preset.value, seed: +c.seed.value || 1, n: Math.min(+c.n.value || 1, opts.nMax || 5000),
             use_priors: c.priors.checked, overrides, catalog: S.cid };
  };
  c.node = h("div", { class: "stack" },
    h("div", { class: "row" },
      h("label", { class: "field" }, h("span", {}, "Пресет допущений"), c.preset),
      opts.noSeed ? null : h("label", { class: "field" }, h("span", {}, "Seed"), c.seed),
      opts.noN ? null : h("label", { class: "field" }, h("span", {}, `Боёв n (≤ ${opts.nMax || 5000})`), c.n),
      h("label", { class: "checkbox", title: "Неизвестные статы берутся из явных априорных распределений" }, c.priors,
        forced ? "Априоры (обязательны: статы UNKNOWN)" : "Априоры для UNKNOWN статов")),
    h("details", {}, h("summary", {}, "Переопределить допущения (JSON)"), c.overrides,
      h("div", { class: "muted small" }, "Ключи - id из реестра допущений (см. таблицу ниже на вкладке Battle Simulator).")));
  return c;
}

// ============================================================================ tabs
const TABS = [
  ["heroes", "My Heroes", "Мои героини", renderHeroes],
  ["build", "Build Editor", "Редактор сборки", renderBuild],
  ["team", "Team Builder", "Конструктор команды", renderTeam],
  ["matchup", "Matchup Analyzer", "Анализ матчапа", renderMatchup],
  ["battle", "Battle Simulator", "Симулятор боя", renderBattle],
  ["tier", "Tier List", "Тир-лист", renderTier],
  ["matrix", "Counterpick Matrix", "Матрица контрпиков", renderMatrix],
  ["equip", "Equipment Optimizer", "Оптимизатор экипировки", renderEquip],
  ["meta", "Meta Watch", "Мониторинг меты", renderMeta],
  ["res", "Resource Planner", "Планировщик ресурсов", renderRes],
  ["history", "Battle History", "История боёв", renderHistory],
];

function buildTabs() {
  const nav = $("#tabs");
  nav.replaceChildren(...TABS.map(([id, en, ru]) => h("button", {
    class: "tab", role: "tab", id: "tab-" + id, "aria-selected": "false", type: "button",
    onclick: () => { location.hash = id; },
  }, h("span", { class: "en" }, en), h("span", { class: "ru" }, ru))));
}

function activate(id) {
  const t = TABS.find((x) => x[0] === id) || TABS[0];
  S.tab = t[0];
  document.querySelectorAll(".tab").forEach((b) => b.setAttribute("aria-selected", String(b.id === "tab-" + t[0])));
  const main = $("#main");
  const sec_ = h("section", { id: "section-" + t[0], role: "tabpanel", "aria-labelledby": "tab-" + t[0] });
  sec_.append(h("div", { class: "section-head" }, h("h2", {}, t[1]), h("span", { class: "ru" }, t[2])));
  main.replaceChildren(sec_);
  try { t[3](sec_); } catch (e) { sec_.append(h("div", { class: "err-box" }, "Ошибка интерфейса: " + e.message)); console.warn(e); }
}

function updateBanner() {
  const c = S.catalogs.find((x) => x.id === S.cid);
  const b = $("#banner");
  if (!c) { b.hidden = true; return; }
  const parts = [];
  if (c.empty) {
    b.className = "banner err";
    parts.push(h("b", {}, `Каталог ${c.label} пуст. `), c.warning || "", " Для демонстрации выберите WHAT-IF или SYNTHETIC. ",
      h("b", {}, MODEL_NOTE + "."));
  } else {
    b.className = "banner";
    parts.push(h("b", {}, `${MODEL_NOTE}. `), `Каталог ${c.label}: `, c.warning || "");
  }
  b.replaceChildren(...parts);
  b.hidden = false;
}

// ---------------------------------------------------------------------------- My Heroes
function renderHeroes(root) {
  const catIds = sec("heroes").map((x) => x.id);
  const glossIds = Object.keys(S.glossary).filter((k) => k.startsWith("hero.")).map((k) => k.slice(5));
  const all = [...new Set([...catIds, ...glossIds])];
  const inTeam = new Set((S.team ? S.team.heroes : []).map((x) => x.hero_id));
  const filterSel = h("select", { "aria-label": "Фильтр" },
    h("option", { value: "all" }, "Все известные героини (глоссарий + каталог)"),
    h("option", { value: "catalog" }, "Только героини выбранного каталога"),
    h("option", { value: "team" }, "Только текущая команда"));
  filterSel.value = S.heroFilter;
  filterSel.addEventListener("change", () => { S.heroFilter = filterSel.value; activate("heroes"); });
  const ids = all.filter((id) => S.heroFilter === "all" || (S.heroFilter === "catalog" ? catIds.includes(id) : inTeam.has(id)));

  root.append(h("div", { class: "panel" },
    h("div", { class: "row center" }, filterSel, h("span", { class: "muted small" }, `${ids.length} героинь`), h("div", { class: "spacer" }),
      h("span", { class: "muted small" }, "Портреты: data/user/portraits/<hero_id>.png|jpg|webp (иначе - инициалы)")),
    h("div", { class: "muted small", style: { marginTop: "6px" } },
      "Имена: RU/EN/JP из глоссария. «*» - перевод не подтверждён в RU-клиенте. Факты базы знаний показываются отдельно по регионам и никогда не смешиваются.")));

  const cards = h("div", { class: "cards" });
  for (const hid of ids) {
    const n = heroNames(hid);
    const c = byId("heroes", hid);
    const factsBox = h("div", { class: "facts" });
    const btnFacts = h("button", { class: "btn ghost small", type: "button" }, "Факты БЗ по регионам");
    btnFacts.addEventListener("click", () => loadFacts(hid, factsBox, btnFacts));
    const canAdd = c && S.team && !inTeam.has(hid) && S.team.heroes.length < 6;
    cards.append(h("div", { class: "panel hero-card" },
      h("div", { class: "top" }, avatar(hid),
        h("div", { class: "names" },
          h("div", { class: "n-main" }, n.ru ? n.ru + (n.ruStatus && n.ruStatus !== "user_stated" ? "*" : "") : (n.en || hid)),
          h("div", { class: "n-sub" }, `RU: ${n.ru || "— (нет RU-названия)"}`),
          h("div", { class: "n-sub" }, `EN: ${n.en || "—"}`),
          h("div", { class: "n-sub" }, `JP: ${n.jp || "—"}`))),
      h("div", { class: "tags" },
        h("span", { class: "badge mono" }, hid),
        c ? badge("в каталоге", "ok") : badge("нет в каталоге", "warn"),
        c && c.role ? badge("роль: " + c.role, "info") : null,
        c && c.template ? badge("шаблон: " + c.template, "hypothesis") : null,
        inTeam.has(hid) ? badge("в команде", "medium") : null),
      c && c.evidence ? h("div", { class: "muted small" }, "Основание шаблона: " + c.evidence) : null,
      h("div", { class: "row center" }, btnFacts,
        canAdd ? h("button", { class: "btn small", type: "button", onclick: () => { addHero(hid); activate("heroes"); } }, "+ в команду") : null),
      factsBox));
  }
  root.append(cards);
}

async function loadFacts(hid, box, btn) {
  btn.disabled = true;
  try {
    const card = S.kbCache[hid] || (S.kbCache[hid] = await api("/api/kb/hero?id=" + encodeURIComponent(hid)));
    const regions = Object.entries(card.regions || {});
    if (!regions.length) { box.replaceChildren(h("div", { class: "muted" }, "В базе знаний нет фактов об этой героине.")); return; }
    box.replaceChildren(...regions.map(([reg, attrs]) => h("div", {},
      h("h5", {}, `Регион ${reg}`, reg !== "RU" ? h("span", { class: "muted" }, " (не переносится на RU без подтверждения)") : null),
      table(Object.entries(attrs).map(([k, v]) => ({ k, ...v })), [
        { k: "k", t: "Атрибут" }, { k: "value", t: "Значение" },
        { k: "confidence", t: "Достоверность", f: (r) => badge(r.confidence) },
        { k: "source", t: "Источник", f: (r) => (/^https?:/.test(r.source || "") ? h("a", { href: r.source, target: "_blank", rel: "noopener" }, "ссылка") : r.source || "—") },
      ]))));
  } catch (e) { box.replaceChildren(h("div", { class: "err-box" }, e.message)); }
  finally { btn.disabled = false; }
}

// ---------------------------------------------------------------------------- Team mutations
function addHero(hid) {
  if (!S.team || S.team.heroes.length >= 6 || S.team.heroes.some((x) => x.hero_id === hid)) return;
  S.team.formation[hid] = freePos(S.team);
  S.team.heroes.push(newHero(hid));
  saveLocal();
}
function removeHero(hid) {
  S.team.heroes = S.team.heroes.filter((x) => x.hero_id !== hid);
  delete S.team.formation[hid];
  S.curHero = Math.min(S.curHero, Math.max(0, S.team.heroes.length - 1));
  saveLocal();
}

// ---------------------------------------------------------------------------- Build Editor
function optionList(items, cur, labelFn, emptyText) {
  const sel = h("select", {}, h("option", { value: "" }, emptyText || "—"),
    items.map((it) => h("option", { value: it.id }, labelFn ? labelFn(it) : it.id)));
  if (cur && !items.some((i) => i.id === cur)) sel.append(h("option", { value: cur }, `${cur} (нет в каталоге)`));
  sel.value = cur || "";
  return sel;
}
function parseStat(v) {
  const t = String(v).trim();
  if (t === "") return undefined;
  if (t.toUpperCase() === "UNKNOWN") return "UNKNOWN";
  const n = Number(t.replace(",", "."));
  return isFinite(n) ? n : "UNKNOWN";
}

function modsEditor(list, onChange, layer) {
  const box = h("div", { class: "mods" });
  const keys = (S.schema && S.schema.stat_keys) || [];
  const draw = () => {
    box.replaceChildren(...list.map((m, i) => {
      const stat = h("select", {}, keys.map((k) => h("option", { value: k }, k)));
      stat.value = m.stat || keys[0];
      const val = h("input", { type: "text", value: m.value ?? "", placeholder: "значение" });
      const mode = h("select", {}, h("option", { value: "flat" }, "flat"), h("option", { value: "pct" }, "pct"));
      mode.value = m.mode || "flat";
      const src = h("input", { type: "text", value: m.source_id || "", placeholder: "source_id (источник)" });
      const upd = () => {
        list[i] = { stat: stat.value, value: parseStat(val.value) ?? 0, mode: mode.value, source_id: src.value };
        if (layer) list[i].layer = layer;
        onChange();
      };
      [stat, val, mode, src].forEach((x) => x.addEventListener("change", upd));
      return h("div", { class: "mrow" }, stat, val, mode, src,
        h("button", { class: "btn danger small", type: "button", onclick: () => { list.splice(i, 1); onChange(); draw(); } }, "✕"));
    }), h("button", { class: "btn ghost small", type: "button", onclick: () => {
      list.push({ stat: keys[0] || "ATK", value: 0, mode: "flat", source_id: "", ...(layer ? { layer } : {}) }); onChange(); draw();
    } }, "+ модификатор"));
  };
  draw();
  return box;
}

function renderBuild(root) {
  if (!S.team || !S.team.heroes.length) {
    root.append(h("div", { class: "panel" }, "В текущей команде нет героинь. Добавьте их на вкладке ",
      h("a", { href: "#team" }, "Team Builder"), " или в «My Heroes»."));
    return;
  }
  S.curHero = Math.min(S.curHero, S.team.heroes.length - 1);
  const hb = S.team.heroes[S.curHero];
  const rerender = () => { saveLocal(); activate("build"); };

  root.append(h("div", { class: "panel" },
    h("div", { class: "muted small" }, `Команда: ${S.team.name} · каталог ${S.cid} (${S.cat.region}/${S.cat.balance_version})`),
    h("div", { class: "chips", style: { marginTop: "8px" } }, S.team.heroes.map((x, i) => h("button", {
      class: "chip" + (i === S.curHero ? " on" : ""), type: "button", onclick: () => { S.curHero = i; activate("build"); },
    }, avatar(x.hero_id, true), heroName(x.hero_id))))));

  const talents = sec("talents");
  const sigilTalents = talents.filter((t) => (t.system || "sigil") === "sigil");
  const personalTalents = talents.filter((t) => t.system === "personal");
  const tl = (t) => `${t.id}${t.effect_key ? " · " + t.effect_key : ""}`;

  // sigils: 2 sigils x 2 talents
  const sigBox = h("div", { class: "slot-list" });
  for (let i = 0; i < 2; i++) {
    const s = hb.sigils[i] || { id: "", talents: [] };
    const sSel = optionList(sec("sigils"), s.id, null, "— сигил —");
    const t1 = optionList(sigilTalents, s.talents[0], tl, "— талант —");
    const t2 = optionList(sigilTalents, s.talents[1], tl, "— талант —");
    if (!s.id) { t1.disabled = true; t2.disabled = true; }
    const upd = () => {
      const rows = [];
      for (let j = 0; j < 2; j++) {
        const cur = j === i ? { id: sSel.value, talents: [t1.value, t2.value].filter(Boolean) } : hb.sigils[j];
        if (cur && cur.id) rows.push(cur);
      }
      hb.sigils = rows;
      rerender();
    };
    [sSel, t1, t2].forEach((x) => x.addEventListener("change", upd));
    sigBox.append(h("div", { class: "srow three" }, h("span", {}, `Сигил ${i + 1}`), sSel, t1, t2));
  }

  // personal talents (separate system)
  const ptBox = h("div", { class: "slot-list" });
  for (let i = 0; i < 2; i++) {
    const sel = optionList(personalTalents, hb.talents[i], tl, "— личный талант —");
    sel.addEventListener("change", () => {
      const arr = [hb.talents[0] || "", hb.talents[1] || ""];
      arr[i] = sel.value;
      hb.talents = arr.filter(Boolean);
      rerender();
    });
    ptBox.append(h("div", { class: "srow" }, h("span", {}, `Талант ${i + 1}`), sel));
  }

  // limbs: 4 positions, filtered by catalog position
  const limbBox = h("div", { class: "slot-list" });
  for (let i = 0; i < 4; i++) {
    const items = sec("limbs").filter((l) => l.position === undefined || l.position === null || l.position === i);
    const sel = optionList(items, hb.limbs[i], (l) => `${l.id}${l.set ? " · " + l.set : ""}`, "— пусто —");
    sel.addEventListener("change", () => {
      const arr = [0, 1, 2, 3].map((j) => hb.limbs[j] || null);
      arr[i] = sel.value || null;
      hb.limbs = arr.some(Boolean) ? arr : [];
      rerender();
    });
    limbBox.append(h("div", { class: "srow" }, h("span", {}, `Позиция ${i + 1}`), sel));
  }

  // decorations: up to 8
  const decoBox = h("div", { class: "slot-list" });
  for (let i = 0; i < 8; i++) {
    const sel = optionList(sec("decorations"), hb.decorations[i], null, "— пусто —");
    sel.addEventListener("change", () => {
      const arr = [...Array(8)].map((_, j) => hb.decorations[j] || "");
      arr[i] = sel.value;
      hb.decorations = arr.filter(Boolean);
      rerender();
    });
    decoBox.append(h("div", { class: "srow" }, h("span", {}, `Слот ${i + 1}`), sel));
  }

  const checkList = (section, arr, setter) => {
    const items = sec(section);
    if (!items.length) return h("div", { class: "muted small" }, "В каталоге нет записей");
    return h("div", { class: "checks" }, items.map((it) => {
      const cb = h("input", { type: "checkbox", checked: arr.includes(it.id) });
      cb.addEventListener("change", () => {
        setter(cb.checked ? [...arr, it.id] : arr.filter((x) => x !== it.id));
        rerender();
      });
      return h("label", { class: "checkbox" }, cb, it.id + (it.rarity ? ` (${it.rarity})` : ""));
    }));
  };

  // stats
  const keys = (S.schema && S.schema.stat_keys) || Object.keys(hb.stats);
  const fr = new Set((S.schema && S.schema.fraction_stats) || []);
  const statGrid = h("div", { class: "stat-grid" }, keys.map((k) => {
    const v = hb.stats[k];
    const inp = h("input", { type: "text", value: v === undefined ? "" : v, placeholder: "не задано",
      title: fr.has(k) ? "доля: 0.15 = 15%" : "абсолютное значение" });
    inp.addEventListener("change", () => {
      const pv = parseStat(inp.value);
      if (pv === undefined) delete hb.stats[k]; else hb.stats[k] = pv;
      saveLocal();
      inp.value = pv === undefined ? "" : pv;
    });
    return h("label", { class: "field" }, h("span", {}, k + (fr.has(k) ? " (доля)" : "")), inp);
  }));
  const modeSel = h("select", {}, h("option", { value: "base" }, "base - базовые статы, экипировка прибавится"),
    h("option", { value: "panel" }, "panel - статы с панели (экипировка уже учтена)"));
  modeSel.value = hb.stats_mode || "base";
  modeSel.addEventListener("change", () => { hb.stats_mode = modeSel.value; saveLocal(); });

  const prog = hb.progression || (hb.progression = {});
  const progRow = h("div", { class: "row" }, ["level", "stars", "awakening"].map((k) => {
    const inp = h("input", { type: "text", value: prog[k] ?? "UNKNOWN", style: { width: "110px" } });
    inp.addEventListener("change", () => { prog[k] = parseStat(inp.value) ?? "UNKNOWN"; saveLocal(); });
    return h("label", { class: "field" }, h("span", {}, { level: "Уровень", stars: "Звёзды", awakening: "Пробуждение" }[k]), inp);
  }));

  const catHero = byId("heroes", hb.hero_id);
  root.append(h("div", { class: "build-grid" },
    h("div", { class: "panel" }, h("h3", {}, "Сигилы (2 × 2 таланта)"), sigBox,
      h("div", { class: "muted small" }, "Только таланты с system = «sigil»."),
      h("h3", {}, "Личные таланты (отдельная система)"), ptBox,
      h("div", { class: "muted small" }, "Только таланты с system = «personal».")),
    h("div", { class: "panel" }, h("h3", {}, "Лимбы (4 позиции)"), limbBox, h("h3", {}, "Украшения (до 8)"), decoBox),
    h("div", { class: "panel" },
      h("h3", {}, "Питомцы"), checkList("pets", hb.pets, (v) => { hb.pets = v; }),
      h("h3", {}, "Карты прелестей"), checkList("charm_cards", hb.charm_cards, (v) => { hb.charm_cards = v; }),
      h("h3", {}, "Прочие личные модификаторы (extra_mods)"),
      modsEditor(hb.extra_mods, saveLocal),
      h("div", { class: "muted small" }, "Командные/глобальные бонусы сюда не вносить - они задаются в Team Builder (иначе двойной учёт)."))));

  root.append(h("div", { class: "panel" },
    h("div", { class: "row center" }, h("h3", { style: { margin: 0 } }, `Характеристики: ${heroName(hb.hero_id)}`), h("div", { class: "spacer" }),
      h("label", { class: "field inline" }, h("span", {}, "Режим"), modeSel),
      h("button", { class: "btn ghost small", type: "button", onclick: () => {
        hb.stats = clone((catHero && catHero.base_stats) || {}); rerender();
      } }, "Сбросить к каталогу")),
    h("div", { class: "muted small", style: { margin: "6px 0" } },
      "Число или UNKNOWN. Пустое поле - значение не задано. Ничего не подставляется автоматически."),
    statGrid, h("h4", {}, "Прогресс"), progRow));

  // validation
  const box = h("div");
  const onlyThis = h("input", { type: "checkbox", checked: true });
  const btn = h("button", { class: "btn", type: "button" }, "Проверить ограничения");
  btn.addEventListener("click", () => runJob(btn, box, "validate", () => api("/api/validate", { team: S.team, catalog: S.cid }),
    (r) => renderIssues(r, onlyThis.checked ? S.curHero : null), "validation"));
  root.append(h("div", { class: "panel" },
    h("div", { class: "row center" }, btn, h("label", { class: "checkbox" }, onlyThis, "показать только эту героиню + командные"),
      h("div", { class: "spacer" }), h("button", { class: "btn danger small", type: "button", onclick: () => {
        removeHero(hb.hero_id); activate("build");
      } }, "Убрать героиню из команды")), box));
  if (S.results.validate) showResult("validate", box);
}

function renderIssues(r, heroIdx) {
  let issues = r.issues || [];
  if (heroIdx !== null && heroIdx !== undefined) issues = issues.filter((i) => !/^heroes\[/.test(i.path || "") || (i.path || "").startsWith(`heroes[${heroIdx}]`));
  const order = { ERROR: 0, WARN: 1, INFO: 2 };
  issues = [...issues].sort((a, b) => order[a.level] - order[b.level]);
  const counts = { ERROR: 0, WARN: 0, INFO: 0 };
  (r.issues || []).forEach((i) => { counts[i.level] = (counts[i.level] || 0) + 1; });
  return h("div", {},
    h("div", { class: "row center" }, r.ok ? badge("Ошибок нет", "ok") : badge("Есть ошибки", "err"),
      badge(`ERROR ${counts.ERROR}`, "ERROR"), badge(`WARN ${counts.WARN}`, "WARN"), badge(`INFO ${counts.INFO}`, "INFO")),
    issues.length ? issues.map((i) => h("div", { class: "issue " + i.level }, h("b", {}, `[${i.level}] ${i.code} `), i.message,
      i.path ? h("div", { class: "path" }, i.path) : null)) : h("div", { class: "muted" }, "Замечаний нет."));
}

// ---------------------------------------------------------------------------- Team Builder
function renderTeam(root) {
  const t = S.team;
  const rerender = () => { saveLocal(); activate("team"); };

  // header: name / status / save / load
  const nameIn = h("input", { type: "text", value: t.name, style: { minWidth: "200px" } });
  nameIn.addEventListener("change", () => { t.name = nameIn.value.trim() || "Моя команда"; saveLocal(); });
  const statusSel = h("select", {}, ["hypothetical", "my_roster_confirmed", "observed_opponent"].map((s) => h("option", { value: s }, s)));
  statusSel.value = t.status || "hypothetical";
  statusSel.addEventListener("change", () => { t.status = statusSel.value; saveLocal(); });
  const saveBtn = h("button", { class: "btn", type: "button" }, "Сохранить");
  saveBtn.addEventListener("click", async () => {
    try {
      const r = await api("/api/teams", { team: t, name: t.name });
      await refreshSaved();
      toast(`Сохранено: ${r.file}`);
      activate("team");
    } catch (e) { toast(e.message, true); }
  });
  root.append(h("div", { class: "panel" },
    h("div", { class: "row" },
      h("label", { class: "field" }, h("span", {}, "Название команды"), nameIn),
      h("label", { class: "field" }, h("span", {}, "Статус"), statusSel),
      saveBtn,
      h("button", { class: "btn ghost", type: "button", onclick: () => { S.team = newTeam(); S.curHero = 0; rerender(); } }, "Новая пустая"),
      (S.cat.sample_teams || []).map((st) => h("button", { class: "btn ghost", type: "button", onclick: () => {
        S.team = clone(st); S.curHero = 0; rerender();
      } }, `Пример: ${st.name}`))),
    h("div", { class: "muted small", style: { marginTop: "6px" } },
      `Регион/версия баланса команды: ${t.region}/${t.balance_version} · каталог: ${S.cat.region}/${S.cat.balance_version}`,
      t.region !== S.cat.region || t.balance_version !== S.cat.balance_version
        ? h("span", {}, " ", badge("не совпадает с каталогом", "err"), " ",
          h("button", { class: "btn ghost small", type: "button", onclick: () => {
            t.region = S.cat.region; t.balance_version = S.cat.balance_version; rerender();
          } }, "привязать к каталогу")) : null)));

  // hero picker
  const ids = new Set(t.heroes.map((x) => x.hero_id));
  const heroes = sec("heroes");
  root.append(h("div", { class: "panel" },
    h("h3", {}, `Героини (${t.heroes.length}/6)`),
    heroes.length ? h("div", { class: "chips" }, heroes.map((c) => h("button", {
      class: "chip" + (ids.has(c.id) ? " on" : ""), type: "button", disabled: !ids.has(c.id) && t.heroes.length >= 6,
      onclick: () => { if (ids.has(c.id)) removeHero(c.id); else addHero(c.id); rerender(); },
    }, avatar(c.id, true), heroName(c.id)))) : h("div", { class: "muted" }, "В выбранном каталоге нет героинь.")));

  // formation 2x3
  const posOf = {};
  t.heroes.forEach((x, i) => { posOf[t.formation[x.hero_id] ?? i] = x.hero_id; });
  const slot = (p) => {
    const hid = posOf[p];
    const b = h("button", { type: "button", class: "slot" + (hid ? " filled" : "") + (S.selSlot === p ? " sel" : ""),
      "aria-label": `Позиция ${p + 1}` },
      h("span", { class: "pos" }, `поз. ${p + 1} (index ${p})`),
      hid ? [avatar(hid, true), h("span", { class: "hname" }, heroName(hid))] : h("span", { class: "muted small" }, "пусто"));
    b.addEventListener("click", () => {
      if (S.selSlot === null) { S.selSlot = p; activate("team"); return; }
      const a = S.selSlot; S.selSlot = null;
      if (a !== p) {
        const ha = posOf[a], hb2 = posOf[p];
        if (ha) t.formation[ha] = p;
        if (hb2) t.formation[hb2] = a;
      }
      rerender();
    });
    return b;
  };
  root.append(h("div", { class: "panel" },
    h("h3", {}, "Формация"),
    h("div", { class: "muted small", style: { marginBottom: "8px" } },
      "Нажмите на одну ячейку, затем на другую - героини поменяются местами. Первый ряд = позиции 0,1,2 (допущение formation.front)."),
    h("div", { class: "formation" },
      h("div", { class: "frow" }, h("div", { class: "rlabel" }, "Первый ряд"), [0, 1, 2].map(slot)),
      h("div", { class: "frow" }, h("div", { class: "rlabel" }, "Второй ряд"), [3, 4, 5].map(slot)))));

  // runes / princess weapon / relics / global stats
  const runeBox = h("div", { class: "slot-list" });
  for (let i = 0; i < 4; i++) {
    const sel = optionList(sec("runes"), t.runes[i], null, "— руна —");
    sel.addEventListener("change", () => {
      const arr = [0, 1, 2, 3].map((j) => t.runes[j] || "");
      arr[i] = sel.value;
      t.runes = arr.filter(Boolean);
      rerender();
    });
    runeBox.append(h("div", { class: "srow" }, h("span", {}, `${i + 1}-я`), sel));
  }
  const pwBox = h("div", { class: "slot-list" });
  for (let i = 0; i < 4; i++) {
    const items = sec("princess_weapon_parts").filter((p) => p.position === undefined || p.position === null || p.position === i);
    const sel = optionList(items, t.princess_weapon[i], (p) => `${p.id}${p.set ? " · " + p.set : ""}`, "— пусто —");
    sel.addEventListener("change", () => {
      const arr = [0, 1, 2, 3].map((j) => t.princess_weapon[j] || null);
      arr[i] = sel.value || null;
      t.princess_weapon = arr.some(Boolean) ? arr : [];
      rerender();
    });
    pwBox.append(h("div", { class: "srow" }, h("span", {}, `Позиция ${i + 1}`), sel));
  }
  const relics = sec("relics");
  const relicBox = relics.length ? h("div", { class: "checks" }, relics.map((r) => {
    const cb = h("input", { type: "checkbox", checked: t.relics.includes(r.id) });
    cb.addEventListener("change", () => { t.relics = cb.checked ? [...t.relics, r.id] : t.relics.filter((x) => x !== r.id); rerender(); });
    return h("label", { class: "checkbox" }, cb, r.id);
  })) : h("div", { class: "muted small" }, "В каталоге нет реликтов");

  root.append(h("div", { class: "grid three" },
    h("div", { class: "panel" }, h("h3", {}, "Руны (порядок активации)"), runeBox),
    h("div", { class: "panel" }, h("h3", {}, "Оружие принцессы (4 позиции)"), pwBox),
    h("div", { class: "panel" }, h("h3", {}, "Реликты"), relicBox,
      h("h3", {}, "Глобальные статы (командный слой)"), modsEditor(t.global_stats, saveLocal, "team"),
      h("div", { class: "muted small" }, "Применяются один раз к каждой героине в начале боя."))));

  // validate team
  const vbox = h("div");
  const vbtn = h("button", { class: "btn", type: "button" }, "Проверить команду");
  vbtn.addEventListener("click", () => runJob(vbtn, vbox, "validate_team", () => api("/api/validate", { team: t, catalog: S.cid }),
    (r) => renderIssues(r, null), "team_validation"));
  root.append(h("div", { class: "panel" }, vbtn, vbox));
  if (S.results.validate_team) showResult("validate_team", vbox);

  // saved teams
  root.append(h("div", { class: "panel" }, h("h3", {}, "Сохранённые команды (data/user/teams)"),
    table(S.saved, [
      { k: "name", t: "Имя" }, { k: "region", t: "Регион" }, { k: "balance_version", t: "Версия" },
      { k: "heroes", t: "Героини", f: (r) => (r.heroes || []).map(heroName).join(", ") },
      { k: "_", t: "", f: (r) => h("span", { class: "row" },
        h("button", { class: "btn ghost small", type: "button", onclick: async () => {
          try { S.team = await api("/api/teams/" + encodeURIComponent(r.name)); S.curHero = 0; rerender(); toast("Загружено: " + r.name); }
          catch (e) { toast(e.message, true); }
        } }, "Загрузить"),
        h("button", { class: "btn danger small", type: "button", onclick: async () => {
          if (!confirm(`Удалить команду «${r.name}»?`)) return;
          try { await api("/api/teams/" + encodeURIComponent(r.name), undefined, "DELETE"); await refreshSaved(); activate("team"); }
          catch (e) { toast(e.message, true); }
        } }, "Удалить")) },
    ], { empty: "Пока нет сохранённых команд." })));

  renderCompare(root);
}

function teamDiff(a, b) {
  const rows = [];
  const add = (field, va, vb) => {
    const sa = cellText(va), sb = cellText(vb);
    rows.push({ field, a: sa, b: sb, same: sa === sb ? "=" : "≠" });
  };
  add("Название", a.name, b.name);
  add("Регион / версия", `${a.region}/${a.balance_version}`, `${b.region}/${b.balance_version}`);
  add("Героини", a.heroes.map((x) => x.hero_id), b.heroes.map((x) => x.hero_id));
  for (let p = 0; p < 6; p++) {
    const fa = Object.keys(a.formation).find((k) => +a.formation[k] === p) || "—";
    const fb = Object.keys(b.formation).find((k) => +b.formation[k] === p) || "—";
    add(`Позиция ${p + 1}`, fa, fb);
  }
  add("Руны (порядок)", a.runes, b.runes);
  add("Оружие принцессы", a.princess_weapon, b.princess_weapon);
  add("Реликты", a.relics, b.relics);
  add("Глобальные статы", a.global_stats, b.global_stats);
  const ids = [...new Set([...a.heroes, ...b.heroes].map((x) => x.hero_id))];
  for (const id of ids) {
    const ha = a.heroes.find((x) => x.hero_id === id), hb = b.heroes.find((x) => x.hero_id === id);
    if (!ha || !hb) { add(`${id}`, ha ? "есть" : "нет", hb ? "есть" : "нет"); continue; }
    for (const f of ["stats_mode", "sigils", "talents", "limbs", "decorations", "pets", "charm_cards", "extra_mods", "stats"]) {
      if (JSON.stringify(ha[f]) !== JSON.stringify(hb[f])) add(`${id}.${f}`, ha[f], hb[f]);
    }
  }
  return rows;
}

function renderCompare(root) {
  const pa = teamPicker("cmp-a", "cur"), pb = teamPicker("cmp-b", "sample:1");
  const sim = simControls("cmp", { n: 200, nMax: 2000 });
  const opts = teamOptions();
  const oppBox = h("div", { class: "checks" }, opts.map((o) => h("label", { class: "checkbox" },
    h("input", { type: "checkbox", value: o.v, checked: o.v.startsWith("sample:") }), o.t)));
  const diffBox = h("div"), box = h("div");
  const diffBtn = h("button", { class: "btn ghost", type: "button" }, "Таблица отличий");
  diffBtn.addEventListener("click", async () => {
    try {
      const [a, b] = await Promise.all([resolveTeam(pa.value), resolveTeam(pb.value)]);
      const rows = teamDiff(a, b);
      S.results.diff = { res: { label: "Team diff", rows }, exportName: "team_diff",
        render: (r) => table(r.rows, [{ k: "field", t: "Поле" }, { k: "a", t: "Команда 1" }, { k: "b", t: "Команда 2" }, { k: "same", t: "" }],
          { rowClass: (x) => (x.same === "≠" ? "side-B" : "") }) };
      showResult("diff", diffBox);
    } catch (e) { diffBox.replaceChildren(h("div", { class: "err-box" }, e.message)); }
  });
  const btn = h("button", { class: "btn", type: "button" }, "Сравнить симуляцией (/api/compare)");
  btn.addEventListener("click", () => runJob(btn, box, "compare", async () => {
    const v = sim.values();
    const opps = [...oppBox.querySelectorAll("input:checked")].map((x) => x.value);
    if (!opps.length) throw new Error("выберите хотя бы одного соперника");
    const [a, a2, ...os] = await Promise.all([resolveTeam(pa.value), resolveTeam(pb.value), ...opps.map(resolveTeam)]);
    return api("/api/compare", { team_a: a, team_a2: a2, opponents: os, ...v });
  }, renderCompareResult, "compare"));

  root.append(h("div", { class: "panel" }, h("h3", {}, "Сравнение двух команд"),
    h("div", { class: "row" }, h("label", { class: "field" }, h("span", {}, "Команда 1"), pa),
      h("label", { class: "field" }, h("span", {}, "Команда 2"), pb), diffBtn),
    diffBox,
    h("h4", {}, "Пул соперников"), oppBox, sim.node, h("div", { class: "row", style: { marginTop: "8px" } }, btn), box));
  if (S.results.diff) showResult("diff", diffBox);
  if (S.results.compare) showResult("compare", box);
}

function renderCompareResult(r) {
  const o = r.overall || {};
  const rows = Object.entries(r.per_opponent || {}).map(([k, v]) => ({ opp: k, ...v }));
  return h("div", {}, modelLabel(r.label),
    h("div", { class: "kpis" },
      kpi(`WR «${r.teams.a}»`, pct(o.wr_a)), kpi(`WR «${r.teams.a2}»`, pct(o.wr_b)),
      kpi("Δ (2 − 1)", pct(o.delta), `95% ДИ ${ci(o.ci)}`), kpi("Значимо", o.significant ? "да" : "нет", `n = ${r.n} на соперника`)),
    table(rows, [{ k: "opp", t: "Соперник" }, { k: "wr_a", t: "WR 1", num: true, f: (x) => pct(x.wr_a) },
      { k: "wr_b", t: "WR 2", num: true, f: (x) => pct(x.wr_b) }, { k: "delta", t: "Δ", num: true, f: (x) => pct(x.delta) },
      { k: "ci", t: "95% ДИ Δ", f: (x) => ci(x.ci) }, { k: "significant", t: "Значимо" }]));
}

// ---------------------------------------------------------------------------- Battle Simulator
function renderBattle(root) {
  const pa = teamPicker("bt-a", "cur"), pb = teamPicker("bt-b", "sample:1");
  const sim = simControls("bt", { n: 1000, nMax: (S.schema && S.schema.limits.sim_n_max) || 5000 });
  const box1 = h("div"), box2 = h("div");
  const b1 = h("button", { class: "btn", type: "button", id: "btn-battle" }, "Один бой");
  const b2 = h("button", { class: "btn", type: "button", id: "btn-mc" }, "Monte Carlo");
  const teams = async () => Promise.all([resolveTeam(pa.value), resolveTeam(pb.value)]);
  b1.addEventListener("click", () => runJob(b1, box1, "battle", async () => {
    const v = sim.values(); const [a, b] = await teams();
    return api("/api/battle", { team_a: a, team_b: b, ...v });
  }, renderBattleResult, "battle"));
  b2.addEventListener("click", () => runJob(b2, box2, "sim", async () => {
    const v = sim.values(); const [a, b] = await teams();
    return api("/api/sim", { team_a: a, team_b: b, ...v });
  }, renderSimResult, "monte_carlo"));

  root.append(h("div", { class: "panel" },
    h("div", { class: "row" }, h("label", { class: "field" }, h("span", {}, "Команда A (моя)"), pa),
      h("label", { class: "field" }, h("span", {}, "Команда B (соперник)"), pb)),
    sim.node, h("div", { class: "row", style: { marginTop: "8px" } }, b1, b2,
      h("span", { class: "muted small" }, "n ≥ 2000 считается в нескольких процессах; 5000 боёв - до ~1 мин."))));
  root.append(h("div", { class: "panel" }, h("h3", {}, "Один бой"), box1));
  root.append(h("div", { class: "panel" }, h("h3", {}, "Monte Carlo"), box2));
  if (S.results.battle) showResult("battle", box1);
  if (S.results.sim) showResult("sim", box2);

  const asmBox = h("div");
  const asmBtn = h("button", { class: "btn ghost small", type: "button" }, "Показать реестр допущений");
  asmBtn.addEventListener("click", () => runJob(asmBtn, asmBox, "assumptions", () => api("/api/assumptions"), (r) => h("div", {},
    table(r.registry, [{ k: "id", t: "ID", f: (x) => h("code", {}, x.id) }, { k: "title_ru", t: "Правило" }, { k: "status", t: "Статус", f: (x) => badge(x.status, "warn") },
      { k: "default", t: "По умолчанию", f: (x) => (x.critical ? "— (задать явно)" : cellText(x.default)) }, { k: "options", t: "Варианты" },
      { k: "critical", t: "Критичное" }]),
    h("h4", {}, "Пресеты"), table(Object.entries(r.presets).map(([k, v]) => ({ preset: k, ...v })))), "assumptions"));
  root.append(h("div", { class: "panel" }, h("h3", {}, "Допущения (формулы со статусом UNKNOWN)"), asmBtn, asmBox));
  if (S.results.assumptions) showResult("assumptions", asmBox);
}

function winnerText(w, teams) {
  if (w === "A") return `Победа A (${teams ? teams.A : ""})`;
  if (w === "B") return `Победа B (${teams ? teams.B : ""})`;
  return "Ничья";
}

function renderBattleResult(r) {
  const units = (r.units || []).filter((u) => u.hero !== "__team__");
  const teamSrc = (r.units || []).filter((u) => u.hero === "__team__");
  const order = (r.first_round && r.first_round.order) || [];
  return h("div", {}, modelLabel(r.label),
    h("div", { class: "kpis" }, kpi("Итог", winnerText(r.winner, r.teams), r.end_reason), kpi("Раундов", r.rounds),
      kpi("HP осталось A", pct(r.hp_left && r.hp_left.A)), kpi("HP осталось B", pct(r.hp_left && r.hp_left.B)), kpi("Seed", r.seed)),
    h("h4", {}, "Порядок ходов в 1-м раунде"),
    h("div", { class: "order-list" }, order.map((o, i) => h("span", { class: "o " + String(o[0])[0] },
      `${i + 1}. ${o[0]} ${heroName(o[1])} · СКР ${num(o[2])}`))),
    r.first_round ? h("div", { class: "muted small", style: { marginTop: "4px" } },
      `1-й раунд: урон A ${num(r.first_round.damage && r.first_round.damage.A)}, урон B ${num(r.first_round.damage && r.first_round.damage.B)}, контроль ${num(r.first_round.controls)}, смерти: ${(r.first_round.deaths || []).join(", ") || "нет"}`) : null,
    h("h4", {}, "Героини"),
    table(units, [
      { k: "uid", t: "Юнит" }, { k: "hero", t: "Героиня", f: (u) => heroName(u.hero) },
      { k: "alive", t: "Жива" }, { k: "dmg_raw", t: "Урон (сырой)", num: true }, { k: "dmg_effective", t: "Урон (эффект.)", num: true },
      { k: "dmg_to_shield", t: "В щиты", num: true }, { k: "heal_effective", t: "Лечение", num: true }, { k: "overheal", t: "Оверхил", num: true },
      { k: "dmg_absorbed_by_own_shield", t: "Поглощено щитом", num: true }, { k: "shield_given", t: "Щиты дано", num: true },
      { k: "ctrl_landed", t: "Контроль", num: true, f: (u) => `${u.ctrl_landed}/${u.ctrl_attempts}` },
      { k: "revives_done", t: "Воскрешений", num: true }, { k: "deaths", t: "Смертей", num: true }, { k: "kills", t: "Убийств", num: true },
      { k: "combo_triggers", t: "Комбо", num: true }, { k: "extra_actions", t: "Доп. действий", num: true },
    ], { rowClass: (u) => "side-" + String(u.uid)[0] + (u.alive ? "" : " dead") }),
    teamSrc.length ? h("div", { class: "muted small" }, "Командные источники (руны/оружие/реликты): ",
      teamSrc.map((u) => `${u.uid}: урон ${num(u.dmg_effective)}`).join("; ")) : null,
    h("h4", {}, "Смерти"),
    table(r.deaths || [], [{ k: "round", t: "Раунд", num: true }, { k: "uid", t: "Юнит" }, { k: "hero", t: "Героиня", f: (d) => heroName(d.hero) },
      { k: "killer", t: "Убийца" }, { k: "killer_hero", t: "Героиня-убийца", f: (d) => heroName(d.killer_hero) }, { k: "ability", t: "Способность" },
      { k: "dtype", t: "Тип" }, { k: "overkill", t: "Оверкилл", num: true }], { empty: "Никто не погиб." }),
    h("details", {}, h("summary", {}, `Использованные допущения (${(r.assumptions_used || []).length})`),
      h("div", { class: "mono small" }, (r.assumptions_used || []).join(", "))));
}

function histogram(hist) {
  const entries = Object.entries(hist || {}).map(([k, v]) => [+k, v]).sort((a, b) => a[0] - b[0]);
  if (!entries.length) return h("div", { class: "muted" }, "нет данных");
  const W = 600, H = 150, pad = 22;
  const max = Math.max(...entries.map((e) => e[1]));
  const bw = (W - pad) / entries.length;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "hist");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Гистограмма длительности боёв (раунды)");
  entries.forEach(([k, v], i) => {
    const bh = ((H - pad - 14) * v) / max;
    const r = document.createElementNS(ns, "rect");
    r.setAttribute("x", pad / 2 + i * bw + 2);
    r.setAttribute("y", H - pad - bh);
    r.setAttribute("width", Math.max(2, bw - 4));
    r.setAttribute("height", bh);
    const tt = document.createElementNS(ns, "title");
    tt.textContent = `${k} раундов: ${v}`;
    r.append(tt);
    svg.append(r);
    const tx = document.createElementNS(ns, "text");
    tx.setAttribute("x", pad / 2 + i * bw + bw / 2);
    tx.setAttribute("y", H - 6);
    tx.setAttribute("text-anchor", "middle");
    tx.textContent = k;
    svg.append(tx);
    const tv = document.createElementNS(ns, "text");
    tv.setAttribute("x", pad / 2 + i * bw + bw / 2);
    tv.setAttribute("y", H - pad - bh - 3);
    tv.setAttribute("text-anchor", "middle");
    tv.textContent = v;
    svg.append(tv);
  });
  return svg;
}

function renderSimResult(r) {
  const heroes = Object.entries(r.heroes || {}).filter(([k]) => !k.endsWith(":__team__")).map(([k, v]) => ({ key: k, side: k[0], hero: k.slice(2), ...v }));
  const maxShare = Math.max(0.0001, ...heroes.map((x) => x.damage_share || 0));
  return h("div", {}, modelLabel(r.label),
    h("div", { class: "kpis" },
      kpi("Модельный WR команды A", pct(r.model_win_rate), `95% ДИ ${ci(r.ci95)}`),
      kpi("Победы / поражения / ничьи", `${r.wins} / ${r.losses} / ${r.draws}`, `n = ${r.n}`),
      kpi("Средняя длительность", num(r.avg_rounds, 2) + " р.", `95% ДИ ${num(r.rounds_ci95 && r.rounds_ci95[0], 2)} … ${num(r.rounds_ci95 && r.rounds_ci95[1], 2)}`),
      kpi("Средний HP в конце", `A ${pct(r.avg_hp_left && r.avg_hp_left.A)} · B ${pct(r.avg_hp_left && r.avg_hp_left.B)}`),
      kpi("Завершение", Object.entries(r.end_reasons || {}).map(([k, v]) => `${k}: ${v}`).join(", "))),
    h("h4", {}, "Длительность боя (раунды)"), histogram(r.rounds_hist),
    h("h4", {}, "Вклад героинь (средние за бой)"),
    table(heroes, [
      { k: "key", t: "Героиня", f: (x) => `${x.side}: ${heroName(x.hero)}` },
      { k: "damage_share", t: "Доля урона", f: (x) => h("div", { class: "barcell" },
        h("div", { class: "bar", style: { width: `${(100 * (x.damage_share || 0)) / maxShare}%` } }), pct(x.damage_share)) },
      { k: "dmg_effective", t: "Урон", num: true }, { k: "heal_effective", t: "Лечение", num: true },
      { k: "overheal", t: "Оверхил", num: true }, { k: "dmg_absorbed_by_own_shield", t: "Поглощ. щитом", num: true },
      { k: "ctrl_landed", t: "Контроль", num: true }, { k: "revives_done", t: "Воскр.", num: true },
      { k: "combo_triggers", t: "Комбо", num: true },
      { k: "survival_rate", t: "Выживает", num: true, f: (x) => pct(x.survival_rate) },
      { k: "p_died", t: "P(гибель)", num: true, f: (x) => pct(x.p_died) },
    ], { rowClass: (x) => "side-" + x.side }),
    h("h4", {}, "Кто погибает первой"),
    table(Object.entries(r.first_death || {}).map(([k, v]) => ({ k, share: v / r.n })),
      [{ k: "k", t: "Героиня", f: (x) => `${x.k[0]}: ${heroName(x.k.slice(2))}` }, { k: "share", t: "Доля боёв", num: true, f: (x) => pct(x.share) }],
      { empty: "Никто не погибает." }),
    r.priors ? h("div", { class: "muted small" }, `Априоры для UNKNOWN статов: ${r.priors.label}`) : null,
    h("details", {}, h("summary", {}, `Использованные допущения (${(r.assumptions_used || []).length})`),
      h("div", { class: "mono small" }, (r.assumptions_used || []).join(", "))));
}

// ---------------------------------------------------------------------------- Matchup Analyzer
function renderMatchup(root) {
  const pa = teamPicker("mu-my", "cur"), pb = teamPicker("mu-enemy", "sample:1");
  const sim = simControls("mu", { n: 200, nMax: (S.schema && S.schema.limits.matchup_n_max) || 2000 });
  const cSug = h("input", { type: "checkbox" }), cAbl = h("input", { type: "checkbox" }), cFor = h("input", { type: "checkbox" });
  const box = h("div");
  const btn = h("button", { class: "btn", type: "button" }, "Анализировать");
  btn.addEventListener("click", () => runJob(btn, box, "matchup", async () => {
    const v = sim.values();
    const [my, enemy] = await Promise.all([resolveTeam(pa.value), resolveTeam(pb.value)]);
    return api("/api/matchup", { my, enemy, ...v, suggest: cSug.checked, ablation: cAbl.checked, best_formation: cFor.checked });
  }, renderMatchupResult, "matchup"));
  root.append(h("div", { class: "panel" },
    h("div", { class: "row" }, h("label", { class: "field" }, h("span", {}, "Моя команда"), pa),
      h("label", { class: "field" }, h("span", {}, "Соперник"), pb)),
    sim.node,
    h("div", { class: "checks", style: { margin: "8px 0" } },
      h("label", { class: "checkbox" }, cSug, "Контрпики (замены формации/порядка рун, парный Monte Carlo)"),
      h("label", { class: "checkbox" }, cAbl, "Абляция (вклад каждого компонента)"),
      h("label", { class: "checkbox" }, cFor, "Лучшая формация (перестановки)")),
    h("div", { class: "muted small" }, `Для контрпиков/абляции n ограничено ${(S.schema && S.schema.limits.suggest_n_max) || 200} на вариант.`),
    h("div", { class: "row", style: { marginTop: "8px" } }, btn)));
  root.append(h("div", { class: "panel" }, box));
  if (S.results.matchup) showResult("matchup", box);
}

function renderMatchupResult(r) {
  const a = r.analysis || {};
  const s = a.summary || {};
  const kh = a.key_heroes || {};
  const khCols = [{ k: "hero", t: "Героиня", f: (x) => heroName(x.hero) }, { k: "damage_share", t: "Доля урона", num: true, f: (x) => pct(x.damage_share) },
    { k: "heal", t: "Лечение", num: true }, { k: "revives", t: "Воскр.", num: true }, { k: "ctrl_landed", t: "Контроль", num: true },
    { k: "survival_rate", t: "Выживает", num: true, f: (x) => pct(x.survival_rate) }];
  const changeCols = [{ k: "kind", t: "Тип" }, { k: "change", t: "Изменение" }, { k: "wr_before", t: "WR до", num: true, f: (x) => pct(x.wr_before) },
    { k: "wr_after", t: "WR после", num: true, f: (x) => pct(x.wr_after) }, { k: "delta", t: "Δ", num: true, f: (x) => pct(x.delta) },
    { k: "ci95", t: "95% ДИ", f: (x) => ci(x.ci95) }, { k: "significant", t: "Значимо" },
    { k: "reason", t: "Причина (метрики)", f: (x) => (x.reason || []).join("; ") }];
  const lc = a.loss_causes || {};
  const fr = a.first_round || {};
  const dg = a.dangerous_interactions || {};
  return h("div", {}, modelLabel(a.label),
    h("div", { class: "kpis" }, kpi("Модельный WR", pct(s.model_win_rate), `95% ДИ ${ci(s.ci95)}`), kpi("Боёв", s.n),
      kpi("Ср. раундов", num(s.avg_rounds, 2)), kpi("Ничьи", s.draws)),
    h("div", { class: "grid two" },
      h("div", {}, h("h4", {}, "Сильные стороны"), h("ul", { class: "plain" }, (a.strengths_weaknesses && a.strengths_weaknesses.strengths || []).map((x) => h("li", {}, x)))),
      h("div", {}, h("h4", {}, "Слабые стороны"), h("ul", { class: "plain" }, (a.strengths_weaknesses && a.strengths_weaknesses.weaknesses || []).map((x) => h("li", {}, x))))),
    h("div", { class: "grid two" },
      h("div", {}, h("h4", {}, "Ключевые героини - мои"), table(kh.mine, khCols)),
      h("div", {}, h("h4", {}, "Ключевые героини - соперник"), table(kh.enemy, khCols))),
    h("h4", {}, "Первый раунд"),
    h("div", { class: "muted small" }, `Средний урон: A ${num(fr.avg_damage && fr.avg_damage.A)} / B ${num(fr.avg_damage && fr.avg_damage.B)} · P(смерть в 1-м раунде): A ${pct(fr.p_any_death_r1 && fr.p_any_death_r1.A)} / B ${pct(fr.p_any_death_r1 && fr.p_any_death_r1.B)}`),
    h("h4", {}, `Причины поражений (${lc.n_lost || 0} боёв)`),
    lc.n_lost ? h("div", {}, table((lc.top_killers || []).map(([k, v]) => ({ k, v })), [{ k: "k", t: "Убийца / способность" }, { k: "v", t: "Убийств", num: true }]),
      table(Object.entries(lc.first_to_die || {}).map(([k, v]) => ({ k, v })), [{ k: "k", t: "Первой погибает", f: (x) => heroName(x.k) }, { k: "v", t: "Доля поражений", num: true, f: (x) => pct(x.v) }]))
      : h("div", { class: "muted" }, "Поражений нет."),
    h("h4", {}, "Опасные источники урона соперника"),
    table((dg.enemy_top_damage_sources || []).map(([k, v]) => ({ k, v })), [{ k: "k", t: "Героиня / способность" }, { k: "v", t: "Доля урона", num: true, f: (x) => pct(x.v) }]),
    r.suggest ? h("div", {}, h("h4", {}, `Контрпики: улучшения (${r.suggest.evaluated} вариантов проверено)`), modelLabel(r.suggest.label),
      table(r.suggest.improvements, changeCols, { empty: "Ни одно изменение не улучшило модельный WR." })) : null,
    r.ablation ? h("div", {}, h("h4", {}, "Абляция: вклад компонентов"),
      table(r.ablation, [...changeCols.slice(0, 2), { k: "contribution", t: "Вклад (−Δ)", num: true, f: (x) => pct(x.contribution) }, ...changeCols.slice(5)],
        { empty: "Нет компонентов для абляции (лимбы/питомцы/руны и т.д. не заданы)." })) : null,
    r.best_formation ? h("div", {}, h("h4", {}, "Лучшая формация (локальный поиск)"),
      h("div", {}, `Модельный WR: ${pct(r.best_formation.model_win_rate)} · траектория: ${(r.best_formation.trace || []).map((x) => pct(x)).join(" → ")}`),
      table(Object.entries(r.best_formation.formation || {}).map(([k, v]) => ({ hero: k, pos: v })).sort((x, y) => x.pos - y.pos),
        [{ k: "pos", t: "Позиция", f: (x) => x.pos + 1 }, { k: "hero", t: "Героиня", f: (x) => heroName(x.hero) }])) : null,
    h("details", {}, h("summary", {}, "Использованные допущения"), h("div", { class: "mono small" }, (a.assumptions_used || []).join(", "))));
}

// ---------------------------------------------------------------------------- Tier List
function renderTier(root) {
  const box = h("div", {}, h("span", { class: "spinner" }), "Загрузка…");
  root.append(h("div", { class: "banner", style: { borderRadius: "8px", marginBottom: "12px" } },
    h("b", {}, "Данные сообщества (community), регион JP, низкая достоверность. "),
    "Это не RU-клиент и не результаты нашего симулятора; рейтинг взят из сторонних гайдов как есть."));
  root.append(h("div", { class: "panel" }, box));
  api("/api/meta?kind=tier_list").then((rows) => {
    S.results.tier = { res: { label: "Community tier list (JP, low confidence)", rows }, exportName: "tier_list", render: (r) => {
      const tierOf = (e) => { const m = /rated\s+([A-Z]+)/i.exec(e.summary || ""); return m ? m[1].toUpperCase() : "?"; };
      const groups = {};
      r.rows.forEach((e) => { (groups[tierOf(e)] = groups[tierOf(e)] || []).push(e); });
      const rank = (t) => (t === "?" ? 99 : -t.split("").filter((c) => c === "S").length * 10 + (t.charCodeAt(0) - 65));
      return h("div", {}, Object.keys(groups).sort((a, b) => rank(a) - rank(b)).map((t) => h("div", {},
        h("h3", {}, `Тир ${t}`, h("span", { class: "muted small" }, " (извлечено из текста записи)")),
        table(groups[t], [{ k: "subject", t: "Героиня", f: (e) => h("span", { class: "row center" }, avatar(e.subject, true), heroName(e.subject)) },
          { k: "region", t: "Регион" }, { k: "status", t: "Статус", f: (e) => badge(e.status) },
          { k: "confidence", t: "Достоверность", f: (e) => badge(e.confidence || "low") },
          { k: "summary", t: "Описание" }, { k: "date", t: "Дата" },
          { k: "source", t: "Источник", f: (e) => (e.source ? h("a", { href: e.source, target: "_blank", rel: "noopener" }, "ссылка") : "—") }]))));
    } };
    showResult("tier", box);
  }).catch((e) => box.replaceChildren(h("div", { class: "err-box" }, e.message)));
}

// ---------------------------------------------------------------------------- Counterpick Matrix
function renderMatrix(root) {
  const opts = teamOptions();
  const remembered = store("matrix.sel") || [];
  const checks = h("div", { class: "checks" }, opts.map((o) => h("label", { class: "checkbox" },
    h("input", { type: "checkbox", value: o.v, checked: remembered.length ? remembered.includes(o.v) : o.v !== "cur" }), o.t)));
  const sim = simControls("mx", { n: 60, nMax: (S.schema && S.schema.limits.matrix_n_max) || 300 });
  const box = h("div");
  const btn = h("button", { class: "btn", type: "button" }, "Построить матрицу");
  btn.addEventListener("click", () => runJob(btn, box, "matrix", async () => {
    const sel = [...checks.querySelectorAll("input:checked")].map((x) => x.value);
    store("matrix.sel", sel);
    if (sel.length < 2) throw new Error("выберите минимум 2 команды");
    const teams = await Promise.all(sel.map(resolveTeam));
    return api("/api/matrix", { teams, ...sim.values() });
  }, renderMatrixResult, "counterpick_matrix"));
  root.append(h("div", { class: "panel" }, h("h4", {}, "Команды (2-8)"), checks, sim.node,
    h("div", { class: "muted small" }, "Каждая пара считается в обе стороны (A атакует / B защищается). Время ≈ k·(k−1)·n боёв."),
    h("div", { class: "row", style: { marginTop: "8px" } }, btn)));
  root.append(h("div", { class: "panel" }, box));
  if (S.results.matrix) showResult("matrix", box);
}

function renderMatrixResult(r) {
  const t = r.teams;
  return h("div", {}, modelLabel(r.label),
    h("div", { class: "table-wrap" }, h("table", { class: "heat" },
      h("thead", {}, h("tr", {}, h("th", {}, "A \\ B"), t.map((n) => h("th", {}, n)))),
      h("tbody", {}, r.matrix.map((row, i) => h("tr", {}, h("th", {}, t[i]), row.map((c) => {
        if (!c) return h("td", { class: "diag" }, "—");
        const w = c.model_win_rate;
        return h("td", { class: "cell", title: `95% ДИ ${ci(c.ci95)}; ничьих ${c.draws}`,
          style: { background: `hsl(${Math.round(w * 120)} 55% var(--heat-l))` } }, pct(w, 0));
      })))))),
    h("div", { class: "muted small" }, `n = ${r.n} боёв на ячейку. Цвет: красный - модельный WR строки низкий, зелёный - высокий.`));
}

// ---------------------------------------------------------------------------- Equipment Optimizer
function renderEquip(root) {
  const pa = teamPicker("eq-team", "cur");
  const inv = h("textarea", { rows: 8 });
  inv.value = store("inventory." + S.cid) || "{}";
  inv.addEventListener("change", () => store("inventory." + S.cid, inv.value));
  const fill = h("button", { class: "btn ghost small", type: "button", onclick: () => {
    const o = {};
    sec("limbs").forEach((l) => { o["limbs:" + l.id] = 1; });
    sec("decorations").forEach((d) => { o["decorations:" + d.id] = 1; });
    inv.value = JSON.stringify(o, null, 1);
    store("inventory." + S.cid, inv.value);
  } }, "Шаблон: по 1 шт. каждого лимба/украшения каталога");
  const box = h("div");
  const btn = h("button", { class: "btn", type: "button" }, "Оптимизировать (CP-SAT)");
  btn.addEventListener("click", () => runJob(btn, box, "equip", async () => {
    let inventory;
    try { inventory = JSON.parse(inv.value || "{}"); } catch (e) { throw new Error("инвентарь: неверный JSON - " + e.message); }
    const team = await resolveTeam(pa.value);
    return api("/api/optimize/equipment", { team, inventory, catalog: S.cid });
  }, renderEquipResult, "equipment"));
  root.append(h("div", { class: "panel" },
    h("div", { class: "row" }, h("label", { class: "field" }, h("span", {}, "Команда"), pa)),
    h("h4", {}, "Инвентарь: {\"limbs:<id>\": кол-во, \"decorations:<id>\": кол-во}"), inv,
    h("div", { class: "row", style: { marginTop: "8px" } }, fill, btn),
    h("div", { class: "muted small" }, "Шаблон - только заготовка формата: укажите реальное количество своих предметов.")));
  root.append(h("div", { class: "panel" }, box));
  if (S.results.equip) showResult("equip", box);
}

function renderEquipResult(r) {
  const heroes = (r.team && r.team.heroes) || [];
  return h("div", {}, h("div", { class: "model-label" }, r.label),
    h("div", { class: "kpis" }, kpi("Статус", r.status), kpi("Целевая функция (эвристика)", num(r.objective)), kpi("Время", num(r.wall_time, 2) + " с")),
    table(heroes.map((x) => ({ hero: x.hero_id, limbs: x.limbs, decorations: x.decorations })),
      [{ k: "hero", t: "Героиня", f: (x) => heroName(x.hero) }, { k: "limbs", t: "Лимбы по позициям 1-4", f: (x) => (x.limbs || []).map((l) => l || "—").join(" | ") || "—" },
        { k: "decorations", t: "Украшения" }]),
    h("div", { class: "row", style: { marginTop: "8px" } }, h("button", { class: "btn ghost", type: "button", onclick: () => {
      let n = 0;
      for (const x of heroes) {
        const hb = S.team.heroes.find((y) => y.hero_id === x.hero_id);
        if (hb) { hb.limbs = x.limbs; hb.decorations = x.decorations; n++; }
      }
      saveLocal();
      toast(n ? `Применено к ${n} героиням текущей команды` : "В текущей команде нет этих героинь", !n);
    } }, "Применить к текущей команде")));
}

// ---------------------------------------------------------------------------- Meta Watch
function renderMeta(root) {
  const fRegion = h("select", {}, ["", "RU", "JP", "EN", "KR", "SEA", "RR"].map((x) => h("option", { value: x }, x || "все регионы")));
  const fKind = h("select", {}, ["", "new_hero", "skill_change", "item_change", "combo", "tier_list", "popular_team", "version_diff", "ru_release_forecast", "event"]
    .map((x) => h("option", { value: x }, x || "все типы")));
  const fStatus = h("select", {}, ["", "confirmed", "community", "hypothesis"].map((x) => h("option", { value: x }, x || "все статусы")));
  const box = h("div"), fbox = h("div");
  const load = () => {
    const q = new URLSearchParams({ region: fRegion.value, kind: fKind.value, status: fStatus.value });
    box.replaceChildren(h("span", { class: "spinner" }));
    api("/api/meta?" + q).then((rows) => {
      S.results.meta = { res: { label: "Meta entries", rows }, exportName: "meta", render: (r) => table(r.rows, [
        { k: "date", t: "Дата" }, { k: "region", t: "Регион" }, { k: "kind", t: "Тип" },
        { k: "subject", t: "Предмет", f: (e) => heroName(e.subject) }, { k: "status", t: "Статус", f: (e) => badge(e.status) },
        { k: "confidence", t: "Достоверность", f: (e) => (e.confidence ? badge(e.confidence) : "—") }, { k: "summary", t: "Описание" },
        { k: "ru_available", t: "В RU", f: (e) => (e.ru_available === true ? badge("подтверждено", "ok") : e.region === "RU" ? "—" : badge("не подтверждено", "warn")) },
        { k: "source", t: "Источник", f: (e) => (e.source ? h("a", { href: e.source, target: "_blank", rel: "noopener" }, "ссылка") : "—") },
      ], { empty: "Записей нет." }) };
      showResult("meta", box);
    }).catch((e) => box.replaceChildren(h("div", { class: "err-box" }, e.message)));
  };
  [fRegion, fKind, fStatus].forEach((x) => x.addEventListener("change", load));
  root.append(h("div", { class: "panel" }, h("h3", {}, "Записи меты"),
    h("div", { class: "row", style: { marginBottom: "8px" } }, fRegion, fKind, fStatus), box));
  root.append(h("div", { class: "panel" }, h("h3", {}, "Прогноз релизов в RU (гипотезы)"),
    h("div", { class: "model-label" }, "Героини из других регионов: не доступно в RU до подтверждения в RU-клиенте"), fbox));
  load();
  api("/api/meta/forecast").then((rows) => {
    S.results.forecast = { res: { label: "RU release forecast (hypothesis)", rows }, exportName: "ru_forecast", render: (r) => table(r.rows, [
      { k: "subject", t: "Героиня", f: (e) => h("span", { class: "row center" }, avatar(e.subject, true), heroName(e.subject)) },
      { k: "first_seen_region", t: "Впервые в регионе" }, { k: "first_seen", t: "Дата" },
      { k: "status", t: "Статус", f: (e) => badge(e.status) },
      { k: "ru_available", t: "Доступность в RU", f: () => badge("не доступно в RU до подтверждения", "warn") }, { k: "note", t: "Примечание" },
    ], { empty: "Нет кандидатов." }) };
    showResult("forecast", fbox);
  }).catch((e) => fbox.replaceChildren(h("div", { class: "err-box" }, e.message)));
}

// ---------------------------------------------------------------------------- Resource Planner
const RES_EXAMPLE = {
  _comment: "Пример ФОРМАТА. Замените id, стоимости и прирост своими данными. Неизвестная стоимость - \"UNKNOWN\" (такие улучшения не выбираются).",
  upgrades: [
    { id: "upgrade_1", desc: "описание улучшения", cost: { gold: "UNKNOWN" }, gain: 0, requires: [] },
  ],
  budget: { gold: 0 },
};
function renderRes(root) {
  const ta = h("textarea", { rows: 14 });
  ta.value = store("resources") || JSON.stringify(RES_EXAMPLE, null, 1);
  ta.addEventListener("change", () => store("resources", ta.value));
  const box = h("div");
  const btn = h("button", { class: "btn", type: "button" }, "Рассчитать план (CP-SAT)");
  btn.addEventListener("click", () => runJob(btn, box, "res", async () => {
    let d;
    try { d = JSON.parse(ta.value); } catch (e) { throw new Error("неверный JSON - " + e.message); }
    return api("/api/resources/plan", { upgrades: d.upgrades, budget: d.budget });
  }, (r) => h("div", {}, h("div", { class: "model-label" }, r.label),
    h("div", { class: "kpis" }, kpi("Статус", r.status), kpi("Выбрано", (r.chosen || []).length), kpi("Ожидаемый модельный ΔWR", pct(r.expected_gain_model, 2))),
    h("h4", {}, "Выбранные улучшения"), h("div", {}, (r.chosen || []).join(", ") || "—"),
    h("h4", {}, "Ресурсы"), table(Object.keys(r.spent || {}).map((k) => ({ res: k, spent: r.spent[k], left: r.left[k] })),
      [{ k: "res", t: "Ресурс" }, { k: "spent", t: "Потрачено", num: true }, { k: "left", t: "Остаток", num: true }]),
    (r.cost_unknown || []).length ? h("div", { class: "issue WARN" }, "Стоимость неизвестна (не рассматривались): " + r.cost_unknown.join(", ")) : null),
  "resource_plan"));
  root.append(h("div", { class: "panel" },
    h("div", { class: "muted small", style: { marginBottom: "6px" } },
      "upgrades: [{id, desc, cost: {ресурс: количество|\"UNKNOWN\"}, gain: модельный ΔWR, requires: [id]}], budget: {ресурс: количество}. ",
      "gain удобно брать из абляции/контрпиков (Matchup Analyzer)."),
    ta, h("div", { class: "row", style: { marginTop: "8px" } }, btn,
      h("button", { class: "btn ghost small", type: "button", onclick: () => { ta.value = JSON.stringify(RES_EXAMPLE, null, 1); store("resources", ta.value); } }, "Сбросить к примеру формата"))));
  root.append(h("div", { class: "panel" }, box));
  if (S.results.res) showResult("res", box);
}

// ---------------------------------------------------------------------------- Battle History
function renderHistory(root) {
  const box = h("div", {}, h("span", { class: "spinner" }), "Загрузка…");
  root.append(h("div", { class: "panel" }, box));
  api("/api/validation").then((d) => {
    S.results.history = { res: d, exportName: "battle_history", render: (r) => {
      const st = r.status || {};
      return h("div", {},
        h("div", { class: "kpis" },
          kpi("Статус симулятора", st.simulator_validated === true ? "ВАЛИДИРОВАН" : "НЕ ВАЛИДИРОВАН", st.rule),
          kpi("Реальных боёв", st.records, `с полными составами: ${st.records_with_full_teams}`),
          kpi("Записей журнала расхождений", st.journal_entries), kpi("Средний Brier", st.mean_brier === null ? "—" : num(st.mean_brier, 3), "0.25 = монетка")),
        st.simulator_validated !== true ? h("div", { class: "model-label" }, "Пока симулятор не валидирован, все WR на панели - модельные") : null,
        h("h3", {}, "Реальные бои"),
        table(r.records, ["date", "mode", "result", "rounds", "my_team", "enemy_team", "notes"].map((k) => ({ k, t: k,
          f: (x) => (x[k] && typeof x[k] === "object" && !Array.isArray(x[k]) ? (x[k].name || "команда") : x[k]) })),
          { empty: "Нет импортированных боёв. Импорт: `luna validate import <file.csv|json>`." }),
        h("h3", {}, "Журнал расхождений (симулятор vs игра)"),
        table(r.journal, null, { empty: "Журнал пуст." }));
    } };
    showResult("history", box);
  }).catch((e) => box.replaceChildren(h("div", { class: "err-box" }, e.message)));
}

// ============================================================================ boot
async function refreshSaved() { S.saved = await api("/api/teams"); }

async function loadCatalog(cid) {
  S.cid = cid;
  store("catalog", cid);
  S.cat = await api("/api/catalog?id=" + encodeURIComponent(cid));
  const saved = store("team." + cid);
  S.team = saved && saved.heroes ? saved : (S.cat.sample_teams && S.cat.sample_teams[0] ? clone(S.cat.sample_teams[0]) : newTeam());
  S.curHero = 0;
  S.selSlot = null;
  S.results = {};
  updateBanner();
}

function applyTheme(mode) {
  const root = document.documentElement;
  if (mode === "light" || mode === "dark") root.setAttribute("data-theme", mode); else root.removeAttribute("data-theme");
  $("#theme-toggle").textContent = "Тема: " + ({ light: "светлая", dark: "тёмная" }[mode] || "авто");
}

async function boot() {
  buildTabs();
  let theme = store("theme") || "auto";
  applyTheme(theme);
  $("#theme-toggle").addEventListener("click", () => {
    theme = { auto: "light", light: "dark", dark: "auto" }[theme] || "auto";
    store("theme", theme);
    applyTheme(theme);
  });
  try {
    const [cats, schema, gl, portraits] = await Promise.all([api("/api/catalogs"), api("/api/schema"), api("/api/glossary"), api("/api/portraits")]);
    S.catalogs = cats;
    S.schema = schema;
    S.portraits = portraits || {};
    for (const e of gl.entries) S.glossary[e.key] = e;
    await refreshSaved();
    const sel = $("#catalog-select");
    sel.replaceChildren(...cats.map((c) => h("option", { value: c.id }, `${c.label}${c.empty ? " - пусто" : ` (${c.heroes} героинь)`}`)));
    const want = store("catalog");
    const first = cats.find((c) => c.id === want) || cats.find((c) => !c.empty) || cats[0];
    sel.value = first.id;
    sel.addEventListener("change", async () => {
      try { await loadCatalog(sel.value); activate(S.tab); } catch (e) { toast(e.message, true); }
    });
    await loadCatalog(first.id);
    window.addEventListener("hashchange", () => activate(location.hash.slice(1)));
    activate(location.hash.slice(1) || "heroes");
  } catch (e) {
    $("#main").replaceChildren(h("div", { class: "err-box" }, "Не удалось загрузить панель: " + e.message));
  }
}

document.addEventListener("DOMContentLoaded", boot);
