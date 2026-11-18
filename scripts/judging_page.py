"""Turn an M4 judging sheet into ONE local HTML page you open by double-click.

    uv run python scripts/judging_page.py --sheet data/eval/m4/sheet.pilot.v1.json --session 1 \\
        --out data/interim/judge.m4-pilot.html

The page has no network use. It holds the sheet text and no key data. It times each item,
saves answers in the browser and exports ``answers.NAME.sessionN.csv``. Add ``--arm-guess`` for a
test sheet. See docs/JUDGING_PROTOCOL.md.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Same list and order as scripts.judging_sheet.TEMPLATE_COLUMNS (a test checks it).
COLUMNS = ["item_id", "choice", "strength", "would_cook_left", "would_cook_right",
           "seconds", "session"]  # fmt: skip
# Verbatim from docs/JUDGING_PROTOCOL.md, section "Rubric (approved ...)". A test checks it.
RUBRIC = [
    "Imagine you own exactly these ingredients, plus the usual staples (salt, oil, water and similar).",
    "You may make one trip to the shop for the missing lines shown under a title.",
    "Which list gives you the better choice for tonight?",
    "A list is better when it holds a dish you would actually cook and eat tonight, and the trip is short.",
    "Do not judge a recipe in general. Judge the list for this pantry.",
    "Choose A (left list), B (right list), or tie. Choose tie only when you cannot prefer one list.",
    "If you chose A or B, give a strength: 1 means a slight preference. 2 means a clear preference. For a tie, leave strength blank.",
    'Then answer for each list: "Would I cook any dish from this list tonight?" yes or no.',
    'Test sheets only: "Which list do you think the new model made?" left, right or unsure.',
]  # fmt: skip


def _clean(sheet: dict) -> list[dict]:
    """Keep only what a judge may see. Drop every other key."""
    rows = lambda lst: [{"title": r["title"], "missing": list(r["missing"])} for r in lst]  # noqa: E731
    return [
        {
            "item_id": it["item_id"],
            "pantry": list(it["pantry"]),
            "left": rows(it["left"]),
            "right": rows(it["right"]),
        }
        for it in sheet["items"]
    ]


def _json_for_script(obj: dict) -> str:
    # ensure_ascii escapes U+2028/2029; the replaces stop "</script>" and "<!--" from closing the tag
    s = json.dumps(obj, ensure_ascii=True, sort_keys=True)
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def build_page(sheet: dict, session: int, name: str, arm_guess: bool = False) -> str:
    items = _clean(sheet)
    digest = hashlib.sha256(
        json.dumps(items, sort_keys=True, ensure_ascii=True).encode("ascii")
    ).hexdigest()[:16]
    data = {
        "name": name,
        "session": session,
        "arm_guess": arm_guess,
        "columns": COLUMNS + (["arm_guess"] if arm_guess else []),
        "rubric": RUBRIC if arm_guess else RUBRIC[:-1],
        "hash": digest,
        "items": items,
    }
    return (
        TEMPLATE.replace("%%DATA%%", _json_for_script(data))
        .replace("%%JS%%", JS)
        .replace("%%CSS%%", CSS)
    )  # ponytail: placeholders, not a template engine; none of the three strings holds the others


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--session", type=int, required=True)
    ap.add_argument("--out")
    ap.add_argument("--arm-guess", action="store_true", help="test sheet: ask which list is new")
    args = ap.parse_args(argv)
    sheet_path = Path(args.sheet)
    m = re.match(r"sheet\.(.+?)\.v\d+$", sheet_path.stem)
    name = m.group(1) if m else sheet_path.stem
    sheet = json.loads(sheet_path.read_text(encoding="utf-8"))
    arm_guess = args.arm_guess or bool(sheet.get("arm_guess"))
    out = Path(args.out) if args.out else ROOT / f"data/interim/judge.m4-{name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    html = build_page(sheet, args.session, name, arm_guess)
    out.write_bytes(html.encode("utf-8"))
    print(f"{len(sheet['items'])} items -> {out} ({out.stat().st_size} bytes)")
    return 0


CSS = r"""
:root{--bg:#fff;--fg:#111;--mut:#444;--line:#555;--acc:#0b57d0;--accfg:#fff;--card:#f4f6fa;--warn:#7a2e00}
@media (prefers-color-scheme:dark){:root{--bg:#111;--fg:#f5f5f5;--mut:#ccc;--line:#aaa;--acc:#8ab4f8;--accfg:#111;--card:#1d2026;--warn:#ffb77a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:18px/1.45 system-ui,sans-serif}
main{max-width:70rem;margin:0 auto;padding:16px}
h1{font-size:1.3rem;margin:.2rem 0}h2{font-size:1.1rem;margin:.2rem 0}
.bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between}
button,summary{min-height:44px;min-width:44px;font:inherit;padding:8px 16px;border:2px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);cursor:pointer}
button.primary{background:var(--acc);color:var(--accfg);border-color:var(--acc);font-weight:600}
button:disabled{opacity:.55;cursor:not-allowed}
:focus-visible{outline:3px solid var(--acc);outline-offset:2px}
details{margin:8px 0;border:1px solid var(--line);border-radius:8px;padding:0 12px;background:var(--card)}
summary{border:0;background:none;padding-left:0}
.chips{display:flex;flex-wrap:wrap;gap:6px;padding:0;margin:6px 0;list-style:none}
.chips li{border:1px solid var(--line);border-radius:999px;padding:2px 12px;background:var(--card)}
.lists{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media (max-width:640px){.lists{grid-template-columns:1fr}}
.list{border:2px solid var(--line);border-radius:8px;padding:8px 12px}
.list ol{margin:0;padding-left:1.4rem}.list li{margin:.5rem 0}
.need{margin:0;padding-left:1.2rem;color:var(--mut)}
fieldset{border:2px solid var(--line);border-radius:8px;margin:12px 0;padding:6px 12px}
legend{font-weight:600;padding:0 6px}
label{display:inline-flex;align-items:center;gap:8px;min-height:44px;min-width:44px;margin-right:14px;cursor:pointer}
input[type=radio]{width:24px;height:24px;accent-color:var(--acc)}
.dis{opacity:.55}.warn{color:var(--warn);font-weight:600}
textarea{width:100%;min-height:9rem;font:14px/1.3 ui-monospace,monospace;background:var(--card);color:var(--fg);border:2px solid var(--line);border-radius:8px}
[hidden]{display:none!important}
.list,fieldset{transition:opacity .15s}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""

JS = r"""
"use strict";
const D = JSON.parse(document.getElementById("sheet").textContent);
const N = D.items.length, KEY = "pcjudge:" + D.hash + ":" + D.session;
const LIMIT = 45 * 60 * 1000;
const $ = (id) => document.getElementById(id);
let A = D.items.map(() => ({ c: "", s: "", l: "", r: "", g: "", sec: 0 }));
let ms = D.items.map(() => 0); // ms on screen per item; saved as whole seconds only
let cur = 0, since = null, paused = false, saves = true, first = true;

try { localStorage.setItem(KEY + ":t", "1"); localStorage.removeItem(KEY + ":t"); } catch (e) { saves = false; }
if (saves) try { const o = JSON.parse(localStorage.getItem(KEY) || "null");
  if (o && Array.isArray(o.a) && o.a.length === N) { A = o.a; ms = A.map((x) => x.sec * 1000); }
} catch (e) { /* bad saved data: start clean */ }

const done = (a) => !!a.c && (a.c === "tie" || !!a.s) && !!a.l && !!a.r && (!D.arm_guess || !!a.g);
const firstOpen = () => { const i = A.findIndex((a) => !done(a)); return i < 0 ? N - 1 : i; };
cur = firstOpen(); // resume at the first unanswered item
function save() { if (!saves) return; try { localStorage.setItem(KEY, JSON.stringify({ a: A, cur })); } catch (e) { saves = false; note(); } }
function stop() { if (since !== null) { ms[cur] += Date.now() - since; since = null; A[cur].sec = Math.round(ms[cur] / 1000); save(); } }
function go() { if (since === null && !paused && document.visibilityState === "visible" && !$("review").hidden) since = Date.now(); }
function total() { return ms.reduce((x, y) => x + y, 0) + (since !== null ? Date.now() - since : 0); }
document.addEventListener("visibilitychange", () => { document.visibilityState === "visible" ? go() : stop(); });

function el(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined) e.textContent = text; if (cls) e.className = cls; return e; }
function fillList(id, rows) {
  const box = $(id); box.replaceChildren();
  const ol = el("ol");
  rows.forEach((r) => { const li = el("li"); li.appendChild(el("strong", r.title));
    if (r.missing.length) { const u = el("ul", undefined, "need"); r.missing.forEach((m) => u.appendChild(el("li", m))); li.appendChild(u); }
    else li.appendChild(el("div", "Nothing to buy", "need"));
    ol.appendChild(li); });
  box.appendChild(ol);
}
function radios(name) { return Array.from(document.getElementsByName(name)); }
function setRadio(name, v) { radios(name).forEach((r) => { r.checked = r.value === v; }); }
function getRadio(name) { const r = radios(name).find((x) => x.checked); return r ? r.value : ""; }

function show() {
  const it = D.items[cur], a = A[cur];
  $("prog").textContent = "item " + (cur + 1) + " of " + N;
  const ch = $("pantry"); ch.replaceChildren(); it.pantry.forEach((p) => ch.appendChild(el("li", p)));
  fillList("left", it.left); fillList("right", it.right);
  setRadio("choice", a.c); setRadio("strength", a.s); setRadio("wl", a.l); setRadio("wr", a.r); setRadio("guess", a.g);
  sync();
  $("back").disabled = cur === 0;
  const f = document.activeElement; if (f && f.disabled) f.blur(); // a disabled button would swallow Enter
  $("next").textContent = cur === N - 1 ? "Save and finish" : "Next";
  if (first) { $("rubric").open = true; first = false; }
  go();
}
function sync() {
  const a = A[cur];
  a.c = getRadio("choice"); a.l = getRadio("wl"); a.r = getRadio("wr"); a.g = getRadio("guess");
  const tie = a.c === "tie";
  radios("strength").forEach((r) => { r.disabled = tie || !a.c; if (tie) r.checked = false; });
  a.s = tie ? "" : getRadio("strength");
  $("strengthset").classList.toggle("dis", tie);
  $("next").disabled = !done(a);
  save(); note();
}
function note() {
  const t = total();
  $("end").hidden = t < LIMIT;
  $("nosave").hidden = saves;
  $("count").textContent = A.filter(done).length + " of " + N + " answered";
}
function next() {
  if (!done(A[cur])) return;
  stop();
  if (cur < N - 1) { cur++; save(); show(); } else { save(); finish(); }
}
function back() { if (cur === 0) return; stop(); cur--; save(); show(); }

function esc(v) { v = String(v); return /[",\n\r]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; }
function csv() {
  const rows = [D.columns.join(",")];
  D.items.forEach((it, i) => { const a = A[i], ok = done(a);
    const v = [it.item_id, ok ? (a.c === "tie" ? "tie" : a.c.toUpperCase()) : "", ok ? a.s : "", ok ? a.l : "", ok ? a.r : "",
      ok ? Math.max(1, Math.round(ms[i] / 1000)) : "", D.session];
    if (D.arm_guess) v.push(ok ? a.g : "");
    rows.push(v.map(esc).join(",")); });
  return rows.join("\n") + "\n";
}
function finish() {
  stop(); $("review").hidden = true; $("done").hidden = false;
  const miss = A.map((a, i) => (done(a) ? null : D.items[i].item_id)).filter(Boolean);
  $("missing").textContent = miss.length ? "Not answered (rows stay blank): " + miss.join(", ") : "All items answered.";
  $("csvtext").value = csv();
}
function download() {
  const b = new Blob([csv()], { type: "text/csv" }), u = URL.createObjectURL(b), a = document.createElement("a");
  a.href = u; a.download = "answers." + D.name + ".session" + D.session + ".csv";
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(u), 1000);
}
function setPause(p) {
  if (p) { stop(); paused = true; } else { paused = false; go(); }
  $("work").hidden = p; $("pausebox").hidden = !p; $("pause").hidden = p;
  if (p) $("resume").focus(); else $("next").focus();
}

$("next").addEventListener("click", next);
$("back").addEventListener("click", back);
$("finishnow").addEventListener("click", finish);
$("pause").addEventListener("click", () => setPause(true));
$("resume").addEventListener("click", () => setPause(false));
$("export").addEventListener("click", () => { $("csvtext").value = csv(); download(); });
$("copy").addEventListener("click", () => { const t = $("csvtext"); t.select(); try { navigator.clipboard.writeText(t.value); } catch (e) { document.execCommand("copy"); } });
$("fix").addEventListener("click", () => { $("done").hidden = true; $("review").hidden = false; cur = firstOpen(); show(); });
document.querySelectorAll("input[type=radio]").forEach((r) => r.addEventListener("change", sync));
const KEYS = { a: ["choice", "A"], b: ["choice", "B"], t: ["choice", "tie"], 1: ["strength", "1"], 2: ["strength", "2"],
  q: ["wl", "yes"], w: ["wl", "no"], o: ["wr", "yes"], p: ["wr", "no"], l: ["guess", "left"], r: ["guess", "right"], u: ["guess", "unsure"] };
document.addEventListener("keydown", (e) => {
  if (paused || $("review").hidden || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "Enter") { if (e.target.tagName !== "BUTTON" && e.target.tagName !== "SUMMARY") { e.preventDefault(); next(); } return; }
  const k = KEYS[e.key.toLowerCase()];
  if (!k || (k[0] === "guess" && !D.arm_guess)) return;
  const r = radios(k[0]).find((x) => x.value === k[1]);
  if (r && !r.disabled) { r.checked = true; sync(); }
});
$("rubrictext").replaceChildren(...D.rubric.map((t) => el("p", t)));
$("title").textContent = "Judging " + D.name + ", session " + D.session;
if (D.arm_guess) { $("guessset").hidden = false; $("guesslegend").textContent = D.rubric[D.rubric.length - 1].replace(/^Test sheets only: /, "").replace(/"/g, "") + " (keys l, r, u)"; }
setInterval(note, 5000);
if (A.every(done)) { cur = N - 1; show(); finish(); } else show();
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>Judging page</title>
<style>%%CSS%%</style>
</head>
<body>
<main>
<div class="bar"><h1 id="title">Judging</h1><div><span id="prog" role="status"></span> | <span id="count"></span></div></div>
<p id="end" class="warn" hidden>Session end: you have worked about 45 minutes. Stop after this item and finish the session.</p>
<p id="nosave" class="warn" hidden>This browser blocks storage. Your answers are NOT saved. Do not reload. Export before you close the page.</p>
<div id="review">
<details id="rubric"><summary>Rubric (read it at the start of each session)</summary><div id="rubrictext"></div></details>
<div class="bar"><button id="pause" type="button">Pause</button></div>
<div id="pausebox" hidden><p>Paused. The clock is stopped and the item is hidden.</p><button id="resume" type="button" class="primary">Resume</button></div>
<div id="work">
<h2>Pantry</h2>
<ul id="pantry" class="chips"></ul>
<div class="lists">
<section class="list" aria-labelledby="hl"><h2 id="hl">A (left)</h2><div id="left"></div></section>
<section class="list" aria-labelledby="hr"><h2 id="hr">B (right)</h2><div id="right"></div></section>
</div>
<fieldset><legend>Which list is better for tonight? (keys a, b, t)</legend>
<label><input type="radio" name="choice" value="A">A (left)</label>
<label><input type="radio" name="choice" value="B">B (right)</label>
<label><input type="radio" name="choice" value="tie">Tie</label></fieldset>
<fieldset id="strengthset"><legend>Strength (keys 1, 2)</legend>
<label><input type="radio" name="strength" value="1">1 slight</label>
<label><input type="radio" name="strength" value="2">2 clear</label></fieldset>
<fieldset><legend>Would I cook any dish from the left list tonight? (keys q, w)</legend>
<label><input type="radio" name="wl" value="yes">Yes</label><label><input type="radio" name="wl" value="no">No</label></fieldset>
<fieldset><legend>Would I cook any dish from the right list tonight? (keys o, p)</legend>
<label><input type="radio" name="wr" value="yes">Yes</label><label><input type="radio" name="wr" value="no">No</label></fieldset>
<fieldset id="guessset" hidden><legend id="guesslegend"></legend>
<label><input type="radio" name="guess" value="left">Left</label>
<label><input type="radio" name="guess" value="right">Right</label>
<label><input type="radio" name="guess" value="unsure">Unsure</label></fieldset>
<div class="bar"><button id="back" type="button">Back</button><button id="next" type="button" class="primary" disabled>Next</button></div>
<p>Enter also saves and goes on.</p>
</div>
<div class="bar"><button id="finishnow" type="button">Finish now and export</button></div>
</div>
<div id="done" hidden>
<h2>Export</h2>
<p id="missing" role="status"></p>
<div class="bar"><button id="export" type="button" class="primary">Download CSV</button><button id="fix" type="button">Go back to unanswered items</button></div>
<p><label for="csvtext">CSV text (fallback: copy it into a file)</label></p>
<textarea id="csvtext" readonly></textarea>
<p><button id="copy" type="button">Copy</button></p>
</div>
</main>
<script type="application/json" id="sheet">%%DATA%%</script>
<script>%%JS%%</script>
</body>
</html>
"""

if __name__ == "__main__":
    raise SystemExit(main())
