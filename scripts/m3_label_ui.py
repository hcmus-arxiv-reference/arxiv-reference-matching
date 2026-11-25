"""Build a local HTML page for manual M3 labelling from the sheets of ``m3_label_sheet.py`` (M3).

Usage::

    python -m scripts.m3_label_ui --work-dir labels-work

reads every ``labels-*.csv`` in ``--work-dir`` together with ``candidates/<key>.csv`` and writes
``gan-nhan.html`` (one self-contained file: no network, no server). Open it in a browser, label,
then press "Xuất CSV" to download a sheet with exactly the columns and rows of the original file;
check it with ``python -m scripts.m3_check_labels`` before uploading.

The page only displays the hints already in the sheet; it never fills a label by itself. Choosing
a candidate or "Không khớp" is the labeller's action. Progress is kept in the browser's
``localStorage`` per sheet name, and an exported CSV can be loaded back to continue elsewhere.
Labelling rules: ``docs/m3-gan-nhan.md`` section 4.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

DATA_PLACEHOLDER = "/*__DATA__*/null"


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    """Columns and rows of a UTF-8 CSV (a BOM is accepted, as Excel writes one)."""
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def load_sheets(work_dir: Path) -> list[dict]:
    """Every label sheet in ``work_dir`` with the candidate References of its Publications."""
    sheets = []
    for path in sorted(work_dir.glob("labels-*.csv")):
        columns, rows = read_csv(path)
        candidates = {}
        for pid in dict.fromkeys(row["arxiv_id"] for row in rows):
            cpath = work_dir / "candidates" / (pid.replace(".", "-").replace("/", "-") + ".csv")
            candidates[pid] = read_csv(cpath)[1] if cpath.exists() else []
        sheets.append({"name": path.name, "columns": columns, "rows": rows, "candidates": candidates})
    return sheets


def render(sheets: list[dict]) -> str:
    """The page with ``sheets`` embedded as JSON.

    ``</`` is escaped so that an entry containing ``</script>`` cannot end the script block.
    """
    data = json.dumps(sheets, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.replace(DATA_PLACEHOLDER, data, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--work-dir", type=Path, default=Path("labels-work"),
                        help="folder written by m3_label_sheet.py (labels-*.csv, candidates/)")
    parser.add_argument("--out", type=Path, help="output page (default: <work-dir>/gan-nhan.html)")
    args = parser.parse_args(argv)
    sheets = load_sheets(args.work_dir)
    if not sheets:
        parser.error(f"không có labels-*.csv trong {args.work_dir}")
    out = args.out or args.work_dir / "gan-nhan.html"
    out.write_text(render(sheets), encoding="utf-8")
    print(f"Đã ghi {out}: " + ", ".join(f"{s['name']} ({len(s['rows'])} dòng)" for s in sheets))
    return 0


# Page template. CSS and JS are inline so the file opens offline; the data replaces DATA_PLACEHOLDER.
TEMPLATE = r'''<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gán nhãn tay</title>
<style>
:root {
  --bg: #f7f7f5; --panel: #ffffff; --ink: #1d1d1b; --muted: #6b6b66; --line: #e2e1dc;
  --accent: #2456c9; --accent-soft: #e6edfb; --ok: #1f7a4d; --ok-soft: #e3f3ea;
  --warn: #9a5b00; --warn-soft: #fbefd9; --none: #6b4fa3; --none-soft: #eee8f7; --mark: #fff0a8;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #161615; --panel: #1f1f1d; --ink: #ecebe6; --muted: #9c9b95; --line: #34332f;
    --accent: #7aa2ff; --accent-soft: #24304d; --ok: #6fd19d; --ok-soft: #1d3328;
    --warn: #f0b35c; --warn-soft: #3a2d17; --none: #b9a2ec; --none-soft: #2d2640; --mark: #5a4d10; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink);
  font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
header { position: sticky; top: 0; z-index: 5; background: var(--panel); border-bottom: 1px solid var(--line);
  padding: 10px 16px; display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
header h1 { font-size: 15px; margin: 0 8px 0 0; }
.tabs button, .btn { border: 1px solid var(--line); background: var(--panel); color: var(--ink);
  padding: 5px 10px; border-radius: 6px; cursor: pointer; font: inherit; }
.tabs button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn:hover, .tabs button:hover { border-color: var(--accent); }
.spacer { flex: 1; }
.progress { color: var(--muted); font-variant-numeric: tabular-nums; }
label.chk { color: var(--muted); display: inline-flex; gap: 4px; align-items: center; }
.layout { display: grid; grid-template-columns: 230px 1fr; gap: 16px; padding: 16px; max-width: 1300px; margin: 0 auto; }
@media (max-width: 760px) { .layout { grid-template-columns: 1fr; } }
nav .paper { display: block; width: 100%; text-align: left; border: 1px solid var(--line); background: var(--panel);
  color: var(--ink); border-radius: 8px; padding: 8px 10px; margin-bottom: 6px; cursor: pointer; font: inherit; }
nav .paper.on { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
nav .paper small { color: var(--muted); display: block; }
.bar { height: 4px; background: var(--line); border-radius: 2px; margin-top: 6px; overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--ok); }
.help { color: var(--muted); font-size: 12px; margin-top: 12px; }
.help kbd { border: 1px solid var(--line); border-radius: 4px; padding: 0 4px; font-size: 11px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; margin-bottom: 12px; }
.card.focus { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.card .top { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.key { font-family: ui-monospace, Menlo, monospace; font-size: 13px; font-weight: 600; }
.pill { font-size: 11px; padding: 1px 8px; border-radius: 999px; background: var(--line); color: var(--muted); }
.pill.match { background: var(--ok-soft); color: var(--ok); }
.pill.empty { background: var(--none-soft); color: var(--none); }
.pill.unsure { background: var(--warn-soft); color: var(--warn); }
.entry { font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; white-space: pre-wrap; word-break: break-word;
  background: var(--bg); border-radius: 6px; padding: 8px 10px; margin: 0 0 8px; }
mark { background: var(--mark); color: inherit; border-radius: 2px; }
.cands { display: grid; gap: 4px; }
.cand { display: grid; grid-template-columns: 22px 110px 1fr auto auto; gap: 8px; align-items: center; text-align: left;
  border: 1px solid var(--line); background: var(--panel); color: var(--ink); border-radius: 6px; padding: 5px 8px;
  cursor: pointer; font: inherit; }
.cand:hover { border-color: var(--accent); }
.cand.on { border-color: var(--ok); background: var(--ok-soft); }
.cand .n { color: var(--muted); font-size: 12px; }
.cand .id { font-family: ui-monospace, Menlo, monospace; font-size: 12.5px; }
.cand .sc { color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; }
.cand a { color: var(--accent); font-size: 12px; }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 8px; }
.btn.empty.on { background: var(--none-soft); border-color: var(--none); color: var(--none); }
.seg button { border: 1px solid var(--line); background: var(--panel); color: var(--ink); padding: 4px 10px; cursor: pointer; font: inherit; }
.seg button:first-child { border-radius: 6px 0 0 6px; } .seg button:last-child { border-radius: 0 6px 6px 0; border-left: 0; }
.seg button.on.sure { background: var(--ok-soft); color: var(--ok); border-color: var(--ok); }
.seg button.on.unsure { background: var(--warn-soft); color: var(--warn); border-color: var(--warn); }
input[type=text] { border: 1px solid var(--line); background: var(--panel); color: var(--ink); border-radius: 6px;
  padding: 5px 8px; font: inherit; min-width: 0; }
input.search { width: 260px; } input.note { flex: 1; min-width: 160px; }
.results { margin-top: 6px; display: grid; gap: 4px; }
.empty-state { color: var(--muted); padding: 30px; text-align: center; }
.toast { position: fixed; bottom: 16px; right: 16px; background: var(--ink); color: var(--bg); padding: 8px 12px;
  border-radius: 8px; opacity: 0; transition: opacity .2s; pointer-events: none; }
.toast.show { opacity: .92; }
</style>
</head>
<body>
<header>
  <h1>Gán nhãn tay M3</h1>
  <div class="tabs" id="tabs"></div>
  <span class="progress" id="progress"></span>
  <label class="chk"><input type="checkbox" id="onlyTodo"> chỉ dòng chưa gán</label>
  <label class="chk"><input type="checkbox" id="onlyUnsure"> chỉ unsure</label>
  <span class="spacer"></span>
  <button class="btn" id="importBtn">Nạp CSV đã xuất</button>
  <input type="file" id="importFile" accept=".csv" hidden>
  <button class="btn" id="exportBtn">Xuất CSV</button>
</header>
<div class="layout">
  <nav>
    <div id="papers"></div>
    <div class="help">
      Phím tắt (dòng đang chọn):<br>
      <kbd>j</kbd>/<kbd>k</kbd> dòng sau/trước ·
      <kbd>1</kbd><kbd>2</kbd><kbd>3</kbd> chọn gợi ý ·
      <kbd>0</kbd> không khớp ·
      <kbd>u</kbd> đổi sure/unsure ·
      <kbd>/</kbd> tìm ứng viên ·
      <kbd>x</kbd> xóa nhãn<br><br>
      Gợi ý có thể sai, phải tự đối chiếu (docs/m3-gan-nhan.md mục 4).
      Tiến độ tự lưu trong trình duyệt này; vẫn nên Xuất CSV định kỳ.
    </div>
  </nav>
  <main id="main"></main>
</div>
<div class="toast" id="toast"></div>
<script>
const SHEETS = /*__DATA__*/null;
const LABEL_COLS = ["ref_arxiv_id", "confidence", "note"];
const state = { sheet: 0, paper: null, focus: 0 };

const store = {
  key: s => "m3-labels:" + SHEETS[s].name,
  load(s) { try { return JSON.parse(localStorage.getItem(this.key(s)) || "{}"); } catch (e) { return {}; } },
  save(s) {
    const out = {};
    for (const r of SHEETS[s].rows) if (r.confidence || r.ref_arxiv_id || r.note) out[rk(r)] = pick(r);
    try { localStorage.setItem(this.key(s), JSON.stringify(out)); } catch (e) {}
  },
};
const rk = r => r.arxiv_id + "\u0000" + r.citation_key;
const pick = r => ({ ref_arxiv_id: r.ref_arxiv_id || "", confidence: r.confidence || "", note: r.note || "" });

SHEETS.forEach((s, i) => {
  const saved = store.load(i);
  for (const r of s.rows) Object.assign(r, saved[rk(r)] || {});
  s.label = s.name.replace(/^labels-/, "").replace(/\.csv$/, "");
});

const $ = id => document.getElementById(id);
const esc = t => String(t ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const norm = t => String(t || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
const words = t => new Set(norm(t).match(/[a-z0-9]{3,}/g) || []);
const STOP = new Set(["the", "and", "for", "with", "from", "via", "are", "using", "towards", "toward", "into", "its", "our"]);

function highlight(text, titleWords) {
  if (!titleWords.size) return esc(text);
  return esc(text).replace(/[A-Za-zÀ-ỹ0-9]{3,}/g, w => {
    const n = norm(w);
    return titleWords.has(n) && !STOP.has(n) ? `<mark>${w}</mark>` : w;
  });
}
const done = r => !!r.confidence;
function toast(msg) { const t = $("toast"); t.textContent = msg; t.classList.add("show"); setTimeout(() => t.classList.remove("show"), 1600); }

function sheet() { return SHEETS[state.sheet]; }
function papers() { return [...new Set(sheet().rows.map(r => r.arxiv_id))]; }
function visibleRows() {
  return sheet().rows.filter(r => r.arxiv_id === state.paper
    && (!$("onlyTodo").checked || !done(r)) && (!$("onlyUnsure").checked || r.confidence === "unsure"));
}

function renderTabs() {
  $("tabs").innerHTML = SHEETS.map((s, i) =>
    `<button class="${i === state.sheet ? "on" : ""}" data-i="${i}">${esc(s.label)}</button>`).join("");
  $("tabs").querySelectorAll("button").forEach(b => b.onclick = () => {
    state.sheet = +b.dataset.i; state.paper = papers()[0]; state.focus = 0; render();
  });
}
function renderProgress() {
  const rows = sheet().rows, n = rows.filter(done).length, u = rows.filter(r => r.confidence === "unsure").length;
  $("progress").textContent = `${n}/${rows.length} dòng đã gán · ${u} unsure`;
}
function renderPapers() {
  $("papers").innerHTML = papers().map(p => {
    const rows = sheet().rows.filter(r => r.arxiv_id === p), n = rows.filter(done).length;
    return `<button class="paper ${p === state.paper ? "on" : ""}" data-p="${p}">${p}
      <small>${n}/${rows.length} đã gán</small><div class="bar"><i style="width:${100 * n / rows.length}%"></i></div></button>`;
  }).join("");
  $("papers").querySelectorAll(".paper").forEach(b => b.onclick = () => { state.paper = b.dataset.p; state.focus = 0; render(); });
}

function candById(pid, id) { return (sheet().candidates[pid] || []).find(c => c.ref_arxiv_id === id); }
function candRow(r, id, title, score, n) {
  const on = r.ref_arxiv_id === id && r.confidence;
  return `<button class="cand ${on ? "on" : ""}" data-act="pick" data-id="${esc(id)}">
    <span class="n">${n || ""}</span><span class="id">${esc(id)}</span><span>${esc(title)}</span>
    <span class="sc">${score !== undefined && score !== "" ? "gợi ý " + esc(score) : ""}</span>
    <a href="https://arxiv.org/abs/${encodeURIComponent(id)}" target="_blank" rel="noopener" data-act="link">arXiv ↗</a></button>`;
}
function renderCard(r, i) {
  const hints = [1, 2, 3].map(k => ({ id: r["hint_" + k], score: r["score_" + k], title: r["hint_title_" + k] })).filter(h => h.id);
  const chosen = r.ref_arxiv_id ? candById(r.arxiv_id, r.ref_arxiv_id) : null;
  const tw = new Set([...hints.flatMap(h => [...words(h.title)]), ...(chosen ? words(chosen.ref_title) : [])]);
  let status = `<span class="pill">chưa gán</span>`;
  if (done(r)) status = r.ref_arxiv_id ? `<span class="pill match">khớp ${esc(r.ref_arxiv_id)}</span>` : `<span class="pill empty">không khớp</span>`;
  if (r.confidence === "unsure") status += ` <span class="pill unsure">unsure</span>`;
  const extra = chosen && !hints.some(h => h.id === r.ref_arxiv_id)
    ? candRow(r, chosen.ref_arxiv_id, chosen.ref_title, "", "✓") : "";
  return `<section class="card ${i === state.focus ? "focus" : ""}" data-i="${i}">
    <div class="top"><span class="key">${esc(r.citation_key)}</span>${status}</div>
    <pre class="entry">${highlight(r.entry, tw)}</pre>
    <div class="cands">${hints.map((h, k) => candRow(r, h.id, h.title, h.score, k + 1)).join("")}${extra}</div>
    <div class="row">
      <input type="text" class="search" placeholder="Tìm ứng viên khác (tiêu đề hoặc ID)…" data-act="search">
      <button class="btn empty ${done(r) && !r.ref_arxiv_id ? "on" : ""}" data-act="none">Không khớp (rỗng)</button>
      <span class="seg"><button class="sure ${r.confidence === "sure" ? "on" : ""}" data-act="conf" data-v="sure">sure</button><button
        class="unsure ${r.confidence === "unsure" ? "on" : ""}" data-act="conf" data-v="unsure">unsure</button></span>
      <input type="text" class="note" placeholder="note (lý do khi unsure, multi, hai ID…)" value="${esc(r.note)}" data-act="note">
      <button class="btn" data-act="multi">multi</button>
      <button class="btn" data-act="clear">Xóa nhãn</button>
    </div>
    <div class="results"></div>
  </section>`;
}
function renderMain() {
  const rows = visibleRows();
  if (state.focus >= rows.length) state.focus = Math.max(0, rows.length - 1);
  $("main").innerHTML = rows.length ? rows.map(renderCard).join("")
    : `<div class="empty-state">Không còn dòng nào theo bộ lọc này.</div>`;
  $("main").querySelectorAll(".card").forEach(card => bindCard(card, rows[+card.dataset.i]));
}
function render() { renderTabs(); renderProgress(); renderPapers(); renderMain(); }

function update(r, patch) {
  // Với bộ lọc "chưa gán", dòng vừa gán biến mất và dòng kế tiếp nhận focus ở cùng chỉ số.
  Object.assign(r, patch);
  store.save(state.sheet);
  const y = window.scrollY;
  renderProgress(); renderPapers(); renderMain(); window.scrollTo(0, y);
}
function choose(r, id) { update(r, { ref_arxiv_id: id, confidence: r.confidence || "sure" }); }

function bindCard(card, r) {
  card.addEventListener("click", e => {
    const i = +card.dataset.i;
    if (i !== state.focus) { state.focus = i; card.parentElement.querySelectorAll(".card").forEach(c => c.classList.toggle("focus", c === card)); }
    const t = e.target.closest("[data-act]");
    if (!t) return;
    const act = t.dataset.act;
    if (act === "link") { e.stopPropagation(); return; }
    if (act === "pick") choose(r, t.dataset.id);
    if (act === "none") update(r, { ref_arxiv_id: "", confidence: r.confidence || "sure" });
    if (act === "conf") update(r, { confidence: t.dataset.v });
    if (act === "multi") update(r, { note: r.note.includes("multi") ? r.note : (r.note ? r.note + "; multi" : "multi") });
    if (act === "clear") update(r, { ref_arxiv_id: "", confidence: "", note: "" });
  });
  const note = card.querySelector("[data-act=note]");
  note.addEventListener("change", () => update(r, { note: note.value.trim() }));
  const search = card.querySelector("[data-act=search]"), box = card.querySelector(".results");
  search.addEventListener("input", () => {
    const q = norm(search.value).trim();
    if (q.length < 2) { box.innerHTML = ""; return; }
    const hits = (sheet().candidates[r.arxiv_id] || [])
      .filter(c => norm(c.ref_title).includes(q) || c.ref_arxiv_id.includes(q)).slice(0, 10);
    box.innerHTML = hits.length ? hits.map(c => candRow(r, c.ref_arxiv_id, c.ref_title + (c.ref_submission_date ? " · " + c.ref_submission_date.slice(0, 4) : ""), "", "")).join("")
      : `<span class="n">Không có ứng viên nào khớp "${esc(search.value)}" trong ${(sheet().candidates[r.arxiv_id] || []).length} references của bài.</span>`;
  });
}

document.addEventListener("keydown", e => {
  if (e.target.matches("input")) { if (e.key === "Escape") e.target.blur(); return; }
  const rows = visibleRows(), r = rows[state.focus];
  const go = d => { state.focus = Math.min(rows.length - 1, Math.max(0, state.focus + d)); renderMain();
    const c = $("main").querySelector(".card.focus"); if (c) c.scrollIntoView({ block: "nearest", behavior: "smooth" }); };
  if (e.key === "j") return go(1);
  if (e.key === "k") return go(-1);
  if (!r) return;
  if ("123".includes(e.key) && e.key !== "") { const id = r["hint_" + e.key]; if (id) choose(r, id); }
  else if (e.key === "0") update(r, { ref_arxiv_id: "", confidence: r.confidence || "sure" });
  else if (e.key === "u") update(r, { confidence: r.confidence === "unsure" ? "sure" : "unsure" });
  else if (e.key === "x") update(r, { ref_arxiv_id: "", confidence: "", note: "" });
  else if (e.key === "/") { e.preventDefault(); $("main").querySelector(".card.focus [data-act=search]")?.focus(); }
});

const csvCell = v => { v = String(v ?? ""); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
$("exportBtn").onclick = () => {
  const s = sheet();
  const text = [s.columns.join(","), ...s.rows.map(r => s.columns.map(c => csvCell(r[c])).join(","))].join("\r\n") + "\r\n";
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  a.download = s.name; a.click(); URL.revokeObjectURL(a.href);
  toast(`Đã xuất ${s.name}`);
};

function parseCsv(text) {
  const rows = []; let row = [], cell = "", q = false;
  text = text.replace(/^﻿/, "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += c; }
    else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(cell); rows.push(row); row = []; cell = ""; }
    else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  const [head, ...body] = rows;
  return body.filter(r => r.length > 1).map(r => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ""])));
}
$("importBtn").onclick = () => $("importFile").click();
$("importFile").onchange = async e => {
  const f = e.target.files[0]; if (!f) return;
  const rows = parseCsv(await f.text());
  const target = SHEETS.findIndex(s => s.rows.some(r => rows.some(x => rk(x) === rk(r))));
  if (target < 0) { toast("File không khớp phiếu nào"); return; }
  const byKey = new Map(rows.map(x => [rk(x), x]));
  let n = 0;
  for (const r of SHEETS[target].rows) { const x = byKey.get(rk(r)); if (x) { Object.assign(r, pick(x)); n++; } }
  store.save(target); state.sheet = target; state.paper = papers()[0]; state.focus = 0; render();
  toast(`Đã nạp ${n} dòng vào ${SHEETS[target].name}`); e.target.value = "";
};
$("onlyTodo").onchange = $("onlyUnsure").onchange = () => { state.focus = 0; renderMain(); };

state.paper = papers()[0];
render();
</script>
</body>
</html>
'''

if __name__ == "__main__":
    raise SystemExit(main())
