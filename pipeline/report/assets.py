"""Stylesheet and script for the offline report (one file, no network, no framework).

Tokens follow the status palette (good / warning / serious / critical) and a neutral
surface scale, defined for light and dark. Layout: a sticky top bar, a sidebar of
sections (tabs on narrow screens), one section shown at a time, and an inbox-style
incident view (list + detail).
"""

STYLE = """
:root { color-scheme: light;
  --bg:#f5f5f3; --surface:#ffffff; --surface-2:#f2f1ee; --surface-3:#e9e8e4; --line:#e3e1dc;
  --text:#0b0b0b; --text-2:#52514e; --text-3:#7b7a74; --accent:#2a78d6; --accent-soft:#e6effb;
  --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b;
  --neutral:#8a8983; --muted:#c3c2b7; --series:#2a78d6;
  --shadow:0 1px 2px rgba(0,0,0,.04), 0 4px 16px rgba(0,0,0,.04); }
@media (prefers-color-scheme: dark) { :root:where(:not([data-theme="light"])) {
  color-scheme: dark; --bg:#121211; --surface:#1a1a19; --surface-2:#222220; --surface-3:#2a2a28;
  --line:#2f2f2c; --text:#ffffff; --text-2:#c3c2b7; --text-3:#8f8e87; --accent:#3987e5;
  --accent-soft:#1b2a3d; --neutral:#8f8e87; --muted:#4a4a46; --series:#3987e5;
  --shadow:none; } }
:root[data-theme="dark"] { color-scheme: dark; --bg:#121211; --surface:#1a1a19; --surface-2:#222220;
  --surface-3:#2a2a28; --line:#2f2f2c; --text:#ffffff; --text-2:#c3c2b7; --text-3:#8f8e87;
  --accent:#3987e5; --accent-soft:#1b2a3d; --neutral:#8f8e87; --muted:#4a4a46; --series:#3987e5;
  --shadow:none; }
* { box-sizing:border-box; }
html, body { margin:0; }
body { background:var(--bg); color:var(--text); font:14px/1.5 Inter, "Segoe UI", system-ui, -apple-system, sans-serif; }
a { color:var(--accent); }
button { font:inherit; }
code { font-size:.86em; background:var(--surface-2); padding:1px 5px; border-radius:5px; }

/* ---- app shell */
.topbar { position:sticky; top:0; z-index:20; display:flex; align-items:center; gap:14px;
  height:60px; padding:0 20px; background:var(--surface); border-bottom:1px solid var(--line); }
.brand { width:34px; height:34px; border-radius:9px; background:var(--accent); color:#fff;
  display:grid; place-items:center; font-weight:700; font-size:.9rem; flex:none; }
.topbar .title { font-weight:650; font-size:1rem; line-height:1.2; }
.topbar .meta { color:var(--text-3); font-size:.8rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.topbar .spacer { flex:1; }
.btn { display:inline-flex; align-items:center; gap:6px; background:var(--surface); color:var(--text-2);
  border:1px solid var(--line); border-radius:8px; padding:6px 12px; cursor:pointer; text-decoration:none;
  font-size:.84rem; }
.btn:hover { background:var(--surface-2); color:var(--text); }
.btn.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
.shell { display:grid; grid-template-columns:232px minmax(0,1fr); min-height:calc(100vh - 60px); }
.sidebar { position:sticky; top:60px; height:calc(100vh - 60px); padding:18px 12px; border-right:1px solid var(--line);
  background:var(--surface); overflow:auto; }
.sidebar .group { color:var(--text-3); font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; margin:4px 10px 8px; }
.nav a { display:flex; align-items:center; gap:10px; padding:8px 10px; border-radius:8px; color:var(--text-2);
  text-decoration:none; font-weight:500; margin-bottom:2px; }
.nav a:hover { background:var(--surface-2); color:var(--text); }
.nav a[aria-current="page"] { background:var(--accent-soft); color:var(--accent); }
.nav .ico { width:18px; text-align:center; opacity:.9; }
.nav .count { margin-left:auto; font-size:.75rem; color:var(--text-3); background:var(--surface-2);
  border-radius:999px; padding:0 8px; }
.sidebar .foot { margin:18px 10px 0; color:var(--text-3); font-size:.75rem; line-height:1.45; }
main { padding:28px 32px 64px; max-width:1320px; width:100%; }
section.page { display:none; }
section.page.active { display:block; }
.page-head { display:flex; align-items:flex-end; gap:16px; margin-bottom:20px; flex-wrap:wrap; }
.page-head h1 { font-size:1.45rem; margin:0; font-weight:650; letter-spacing:-.01em; }
.page-head p { margin:4px 0 0; color:var(--text-2); max-width:720px; }
.page-head .actions { margin-left:auto; display:flex; gap:8px; flex-wrap:wrap; }

/* ---- building blocks */
.card { background:var(--surface); border:1px solid var(--line); border-radius:14px; box-shadow:var(--shadow); }
.card > .card-head { display:flex; align-items:center; gap:10px; padding:14px 18px; border-bottom:1px solid var(--line); }
.card > .card-head h2 { font-size:.95rem; margin:0; font-weight:650; }
.card > .card-head .hint { color:var(--text-3); font-size:.8rem; margin-left:auto; }
.card > .card-body { padding:16px 18px; }
.grid { display:grid; gap:16px; align-items:start; }
.grid.cols-2 { grid-template-columns:repeat(2, minmax(0,1fr)); }
.grid.cols-3-2 { grid-template-columns:minmax(0,3fr) minmax(0,2fr); }
.stack-gap > * + * { margin-top:16px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:12px; margin-bottom:16px; }
.kpi { background:var(--surface); border:1px solid var(--line); border-radius:12px; padding:14px 16px; box-shadow:var(--shadow); }
.kpi .label { color:var(--text-2); font-size:.8rem; }
.kpi .value { font-size:1.75rem; font-weight:650; line-height:1.25; margin-top:2px; font-variant-numeric:tabular-nums; }
.kpi .note { color:var(--text-3); font-size:.78rem; }
.chip { display:inline-flex; align-items:center; gap:5px; padding:1px 9px; border-radius:999px; font-size:.75rem;
  font-weight:600; background:var(--surface-2); color:var(--text); border:1px solid var(--line); white-space:nowrap; }
.chip i { font-style:normal; }
.sw { display:inline-block; width:9px; height:9px; border-radius:3px; flex:none; }
.muted { color:var(--text-3); }
.sub { color:var(--text-2); margin:0; }
.small { font-size:.8rem; }
.banner { display:flex; gap:12px; align-items:flex-start; background:var(--surface); border:1px solid var(--line);
  border-left:4px solid var(--warning); border-radius:10px; padding:10px 14px; color:var(--text-2); margin-bottom:16px; font-size:.86rem; }
table { width:100%; border-collapse:collapse; font-size:.85rem; }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--text-3); font-weight:600; font-size:.76rem; text-transform:uppercase; letter-spacing:.04em; }
tr:last-child td { border-bottom:none; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
details > summary { cursor:pointer; color:var(--text-2); font-size:.84rem; margin-top:10px; }
.empty { color:var(--text-3); padding:20px 0; text-align:center; }

/* ---- replay */
video#video { width:100%; border-radius:10px; background:#000; display:block; aspect-ratio:16/9; }
svg text { fill:var(--text-3); font-size:11px; }
.lane-label { fill:var(--text-2); font-size:12px; font-weight:600; }
.span { cursor:pointer; }
.span:hover, .span:focus { opacity:.8; outline:none; }
.legend { display:flex; gap:14px; flex-wrap:wrap; color:var(--text-2); font-size:.8rem; align-items:center; margin-top:8px; }
.legend > span { display:inline-flex; align-items:center; gap:6px; }
.hatch { background-image:repeating-linear-gradient(45deg, var(--muted) 0 2px, transparent 2px 6px); }

/* ---- priority list (overview) */
.prio { list-style:none; margin:0; padding:0; }
.prio li { display:grid; grid-template-columns:4px 1fr auto; gap:12px; align-items:center; padding:10px 4px;
  border-bottom:1px solid var(--line); cursor:pointer; }
.prio li:last-child { border-bottom:none; }
.prio li:hover .t { color:var(--accent); }
.prio .bar { width:4px; height:34px; border-radius:2px; background:var(--sev); }
.prio .t { font-weight:600; font-size:.88rem; }
.rules-mini { display:grid; gap:8px; }
.rules-mini > div { display:grid; grid-template-columns:34px 1fr auto; gap:10px; align-items:center; }

/* ---- incidents inbox */
.toolbar { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:12px; }
.seg { display:inline-flex; border:1px solid var(--line); border-radius:9px; overflow:hidden; background:var(--surface); }
.seg button { border:none; background:none; padding:6px 12px; color:var(--text-2); cursor:pointer; font-size:.82rem; }
.seg button + button { border-left:1px solid var(--line); }
.seg button[aria-pressed="true"] { background:var(--accent-soft); color:var(--accent); font-weight:600; }
.inbox { display:grid; grid-template-columns:minmax(300px, 380px) minmax(0,1fr); gap:16px; align-items:start; }
.list { max-height:calc(100vh - 230px); overflow:auto; padding:6px; }
.row { display:grid; grid-template-columns:4px 1fr; gap:12px; padding:10px 10px; border-radius:10px; cursor:pointer;
  border:1px solid transparent; }
.row + .row { margin-top:2px; }
.row:hover { background:var(--surface-2); }
.row[aria-selected="true"] { background:var(--accent-soft); border-color:var(--accent); }
.row .bar { border-radius:2px; background:var(--sev); }
.row .top { display:flex; gap:6px; align-items:center; }
.row .t { font-weight:600; font-size:.88rem; }
.row .m { color:var(--text-3); font-size:.78rem; display:flex; gap:8px; flex-wrap:wrap; margin-top:2px; }
.row .verdict { margin-left:auto; font-size:.72rem; color:var(--text-3); }
.row[hidden], .detail[hidden] { display:none; }
.list .section-label { color:var(--text-3); font-size:.72rem; text-transform:uppercase; letter-spacing:.06em; padding:10px 10px 4px; }
.detail { position:sticky; top:80px; }
.detail .d-head { padding:18px 20px 12px; border-bottom:1px solid var(--line); }
.detail .d-head h2 { margin:8px 0 2px; font-size:1.15rem; }
.detail .d-body { padding:18px 20px; display:grid; grid-template-columns:minmax(0,1fr) 220px; gap:20px; }
.detail .media video, .detail .media img { width:100%; border-radius:10px; background:#000; display:block; }
.detail .crop img { width:100%; max-height:300px; object-fit:contain; border-radius:10px; background:var(--surface-2); }
.detail .say { margin:14px 0 0; font-size:.92rem; }
.detail .action { margin-top:10px; padding:10px 12px; border-radius:10px; background:var(--surface-2); font-size:.9rem; }
.detail .action b { display:block; font-size:.72rem; color:var(--text-3); text-transform:uppercase; letter-spacing:.06em; margin-bottom:2px; }
.facts { margin-top:14px; }
.facts td:first-child { color:var(--text-3); width:120px; }
.badge { font-size:.72rem; color:var(--text-3); margin-left:6px; }
.q { font-size:.72rem; color:var(--text-3); white-space:nowrap; }
.q::before { content:''; display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:5px; vertical-align:1px; background:var(--q); }
.btn.sm { padding:2px 9px; font-size:.78rem; border-radius:7px; }
figure.site img { width:100%; border-radius:10px; display:block; }
.review { display:flex; gap:6px; flex-wrap:wrap; align-items:center; padding:14px 20px; border-top:1px solid var(--line); }
.review .btn[aria-pressed="true"] { background:var(--accent); color:#fff; border-color:var(--accent); }
.trace svg { width:100%; height:84px; display:block; }
.trace .cap { color:var(--text-3); font-size:.78rem; margin-top:4px; }
.section-title { font-size:.8rem; color:var(--text-3); text-transform:uppercase; letter-spacing:.06em; margin:18px 0 6px; }

/* ---- charts */
.bars .row-b { display:grid; grid-template-columns:150px minmax(0,1fr) 210px; gap:12px; align-items:center; margin:8px 0; }
.bars .track { height:14px; }
.bars .fill { height:14px; background:var(--series); border-radius:0 4px 4px 0; min-width:2px; }
.bars .val { color:var(--text-2); font-size:.82rem; font-variant-numeric:tabular-nums; }
.stack { display:flex; gap:2px; height:12px; }
.stack span { display:block; height:100%; }
.stack span:first-child { border-radius:4px 0 0 4px; } .stack span:last-child { border-radius:0 4px 4px 0; }
.stack span:only-child { border-radius:4px; }
.cov-row { display:grid; grid-template-columns:40px 210px 170px minmax(0,1fr); gap:12px; align-items:center; padding:10px 0;
  border-bottom:1px solid var(--line); }
.cov-row:last-of-type { border-bottom:none; }
figure.heat { margin:0; }
figure.heat img { width:100%; border-radius:10px; display:block; }
figure.heat figcaption { color:var(--text-3); font-size:.8rem; margin-top:8px; display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.ramp { display:inline-block; width:110px; height:10px; border-radius:3px; background:linear-gradient(90deg, #faba76, #d03b3b); }
.tooltip { position:fixed; pointer-events:none; background:var(--surface); color:var(--text); border:1px solid var(--line);
  border-radius:8px; padding:8px 10px; font-size:.8rem; box-shadow:0 6px 24px rgba(0,0,0,.18); display:none; max-width:280px; z-index:50; }
ul.clean { margin:0; padding-left:18px; color:var(--text-2); }
ul.clean li + li { margin-top:4px; }

/* ---- responsive */
@media (max-width:1100px) {
  .inbox { grid-template-columns:1fr; }
  .detail { position:static; }
  .grid.cols-3-2, .grid.cols-2 { grid-template-columns:1fr; }
}
@media (max-width:860px) {
  .shell { grid-template-columns:1fr; }
  .sidebar { position:sticky; top:60px; height:auto; z-index:10; padding:8px; border-right:none; border-bottom:1px solid var(--line); overflow-x:auto; }
  .sidebar .group, .sidebar .foot { display:none; }
  .nav { display:flex; gap:4px; }
  .nav a { white-space:nowrap; margin:0; }
  main { padding:18px 16px 48px; }
  .detail .d-body { grid-template-columns:1fr; }
  .cov-row { grid-template-columns:40px 1fr; } .cov-row > .stack, .cov-row > .chip-cell { grid-column:1 / -1; }
  .bars .row-b { grid-template-columns:1fr; }
  .topbar .meta { display:none; }
}
"""

SCRIPT = """
(() => {
const $ = (q, el = document) => el.querySelector(q);
const $$ = (q, el = document) => Array.from(el.querySelectorAll(q));
const runId = document.body.dataset.run;

// ---- sections (hash routing)
function show(id) {
  const target = $('#page-' + id) ? id : 'overview';
  $$('section.page').forEach(s => s.classList.toggle('active', s.id === 'page-' + target));
  $$('.nav a').forEach(a => a.setAttribute('aria-current', a.dataset.page === target ? 'page' : 'false'));
  window.scrollTo({ top: 0 });
}
window.addEventListener('hashchange', () => show(location.hash.slice(1)));
show(location.hash.slice(1) || 'overview');

// ---- replay
const video = $('#video');
const playhead = $('#playhead');
const timeline = $('#timeline');
const duration = timeline ? Number(timeline.dataset.duration) : 1;
function seek(t) {
  if (!video) return;
  if (location.hash !== '#overview') location.hash = 'overview';
  video.currentTime = Math.max(0, t - 1);
  video.play().catch(() => {});
}
$$('[data-seek]').forEach(el => {
  el.addEventListener('click', e => { e.stopPropagation(); seek(Number(el.dataset.seek)); });
  el.addEventListener('keydown', e => { if (e.key === 'Enter') seek(Number(el.dataset.seek)); });
});
if (video && playhead) video.addEventListener('timeupdate', () => {
  const x = 60 + 920 * Math.min(1, video.currentTime / duration);
  playhead.setAttribute('x1', x); playhead.setAttribute('x2', x);
});

// ---- tooltips
const tip = $('#tip');
$$('[data-tip]').forEach(el => {
  el.addEventListener('mousemove', e => { tip.innerHTML = el.dataset.tip; tip.style.display = 'block';
    tip.style.left = Math.min(e.clientX + 14, innerWidth - 300) + 'px'; tip.style.top = (e.clientY + 14) + 'px'; });
  el.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
});

// ---- incidents inbox
const rows = $$('.row[data-id]');
function select(id) {
  rows.forEach(r => r.setAttribute('aria-selected', r.dataset.id === id ? 'true' : 'false'));
  $$('.detail[data-id]').forEach(d => {
    const on = d.dataset.id === id;
    d.hidden = !on;
    if (!on) { const v = $('video', d); if (v) v.pause(); }
  });
}
rows.forEach(r => r.addEventListener('click', () => select(r.dataset.id)));
$$('[data-open]').forEach(el => el.addEventListener('click', () => { location.hash = 'incidents'; select(el.dataset.open); }));
let ruleFilter = 'all', groupFilter = 'all';
function filter() {
  let first = null;
  rows.forEach(r => {
    const ok = (ruleFilter === 'all' || r.dataset.rule === ruleFilter) && (groupFilter === 'all' || r.dataset.group === groupFilter);
    r.hidden = !ok; if (ok && !first) first = r;
  });
  $$('.list .section-label').forEach(l => {
    l.hidden = !rows.some(r => !r.hidden && r.dataset.group === l.dataset.group);
  });
  const current = rows.find(r => r.getAttribute('aria-selected') === 'true' && !r.hidden);
  if (!current && first) select(first.dataset.id);
}
$$('[data-rule-filter]').forEach(b => b.addEventListener('click', () => {
  ruleFilter = b.dataset.ruleFilter;
  $$('[data-rule-filter]').forEach(x => x.setAttribute('aria-pressed', x === b));
  filter();
}));
$$('[data-group-filter]').forEach(b => b.addEventListener('click', () => {
  groupFilter = b.dataset.groupFilter;
  $$('[data-group-filter]').forEach(x => x.setAttribute('aria-pressed', x === b));
  filter();
}));
if (rows.length) select(rows[0].dataset.id);

// ---- human review (stored in this browser; exported for tools/review_incidents.py)
const key = 'safety-review:' + runId;
let verdicts = {};
try { verdicts = JSON.parse(localStorage.getItem(key) || '{}'); } catch (e) { verdicts = {}; }
function paint() {
  rows.forEach(r => {
    const v = verdicts[r.dataset.id];
    const tag = $('.verdict', r);
    if (tag) tag.textContent = v ? ({real: '✓ real', false_alarm: '✗ false alarm', unsure: '? unsure'})[v.verdict] : '';
  });
  $$('.review').forEach(box => {
    const v = verdicts[box.dataset.id];
    $$('[data-verdict]', box).forEach(b => b.setAttribute('aria-pressed', v && v.verdict === b.dataset.verdict ? 'true' : 'false'));
  });
  const done = Object.keys(verdicts).length;
  $$('[data-review-count]').forEach(el => el.textContent = done + ' of ' + rows.length + ' reviewed');
}
$$('.review').forEach(box => $$('[data-verdict]', box).forEach(b => b.addEventListener('click', () => {
  const entry = { verdict: b.dataset.verdict };
  if (b.dataset.reason) entry.reason = b.dataset.reason;
  verdicts[box.dataset.id] = entry;
  try { localStorage.setItem(key, JSON.stringify(verdicts)); } catch (e) {}
  paint();
})));
const exportButton = $('#export-review');
if (exportButton) exportButton.addEventListener('click', () => {
  const lines = Object.entries(verdicts).map(([id, v]) => JSON.stringify({ run_id: runId, incident_id: id, ...v })).join('\\n');
  const blob = new Blob([lines + '\\n'], { type: 'application/x-ndjson' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'incident_verdicts_' + runId + '.jsonl'; a.click();
});
paint();

// ---- theme
const toggle = $('#theme');
if (toggle) toggle.addEventListener('click', () => {
  const root = document.documentElement;
  const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  try { localStorage.setItem('safety-theme', root.dataset.theme); } catch (e) {}
});
try { const saved = localStorage.getItem('safety-theme'); if (saved) document.documentElement.dataset.theme = saved; } catch (e) {}
})();
"""
