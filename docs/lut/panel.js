// panel.js - look list manager + per-look editor. Static, no network except same-origin files (model json, panel-slots.json, samples).
// Pack I/O and validation: pack.js. Editor pipeline (import -> rank -> pool fit -> preview -> look object) follows app.js.
// Idea source for the list manager and the before/after divider: Caduceus Control Panel (Apache-2.0); no code or data taken from it.
import { importLutText, applyLut } from "./lutcore.js";
import { loadModel, simulate, baseToX } from "./model.js";
import { Ranker, makeDataset } from "./rank.js";
import { SCENE_DEFS, renderScene, synthDataset } from "./refset.js";
import { rgb2lab, de2000 } from "./color.js";
import { buildLookFile, sha256Hex, toneBlock } from "./lookfile.js";
import { fitCandidate, makeHdrProbe, candidateFromCurves } from "./fit.js";
import { FitPool, FitCancelled } from "./pool.js";
import * as P from "./pack.js";

const $ = (id) => document.getElementById(id);
const log = (m) => { const el = $("log"); el.textContent += m + "\n"; el.scrollTop = el.scrollHeight; console.log(m); };
const ms = (v) => (v < 10 ? v.toFixed(1) : v.toFixed(0)) + " ms";
const tick = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

let L = null;      // panel-slots.json
let st = null;     // pack state (pack.js)
const ed = { slot: null, mode: null, model: null, modelJson: null, ds: null, lut: null, lutInfo: null, fileSha: null, fileName: "", licence: "", stage1: null, lt: null,
  selected: null, fits: {}, hdr: null, pool: null, fitting: false, preview: null, divider: 0.5, tgt: null, sim: null };

// ---- list ---------------------------------------------------------------------------------------------------------------------
const EYE = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z"/><circle cx="12" cy="12" r="3"/>';
const eyeSvg = (hidden) => EYE + (hidden ? '<path d="M3 3l18 18"/>' : "") + "</svg>";
const keyOf = (it) => P.itemKey(it);
const isLookSlot = (it) => typeof it === "number";

function srcBadge(it) {
  if (!isLookSlot(it)) return ["stock", "", "stock item (not editable)"];
  const l = st.looks[it];
  if (l) { const s = l.source || {}, t = (s.name || "LUT") + (s.licence ? " | " + s.licence : ""); return [t, "src-look", `${t}; fitted on ${l.fit && l.fit.mode}; predicted dE ${l.fit && l.fit.predicted && l.fit.predicted.dE} (model value)`]; }
  if (st.names[it] !== L.slots[it].stock) return ["renamed only", "src-ren", "stock look, new menu name"];
  return ["stock", "", "stock look: " + L.slots[it].stock];
}

function rowBase(it) { return isLookSlot(it) ? L.slots[it].mode : L.stock_modes[it] || ""; }

function fixedRow() {
  const r = el("div", "row fixed");
  r.setAttribute("role", "listitem");
  r.append(el("span", "handle", "\u2022"), el("span"), el("span", "badge slot", "first"), el("span", "nm", "i-Enhance (fixed first; the spare record stays last, hidden)"), el("span"), el("span"), el("span"), el("span"));
  return r;
}

function rowFor(it, i) {
  const look = isLookSlot(it), hid = look && st.hidden.includes(it);
  const r = el("div", "row " + (look ? "look" : "stock") + (hid ? " hid" : ""));
  r.tabIndex = 0; r.dataset.key = keyOf(it); r.dataset.i = i; r.setAttribute("role", "listitem");
  if (look) r.dataset.slot = it;
  const h = el("span", "handle", "\u2630"); h.title = "drag to move"; h.dataset.role = "handle";
  const ud = el("span", "ud"), up = el("button", "", "\u25b2"), dn = el("button", "", "\u25bc");
  up.title = "move up (Alt+Up)"; dn.title = "move down (Alt+Down)"; up.setAttribute("aria-label", "move up"); dn.setAttribute("aria-label", "move down");
  up.dataset.role = "up"; dn.dataset.role = "down";
  up.disabled = i === 0; dn.disabled = i === st.arrangement.length - 1;
  up.onclick = () => moveTo(i, i - 1); dn.onclick = () => moveTo(i, i + 1);
  ud.append(up, dn);
  const slot = el("span", "badge slot", look ? "#" + it : "stock");
  const nmw = el("span", "nmwrap");
  if (look) {
    const inp = el("input"); inp.value = st.names[it]; inp.maxLength = 40; inp.spellcheck = false; inp.dataset.role = "name"; inp.setAttribute("aria-label", "menu name of slot " + it);
    const cnt = el("span", "count");
    inp.oninput = () => { st.names[it] = inp.value; rowState(r, it); problems(); };
    nmw.append(inp, cnt);
  } else nmw.append(el("span", "nm", it));
  const base = el("span", "badge base " + rowBase(it), rowBase(it) || "-");
  const src = el("span", "badge src"), eye = el("button", "eye"), rep = el("button", "rep");
  eye.dataset.role = "eye"; rep.dataset.role = "replace";
  if (look) {
    eye.innerHTML = eyeSvg(hid); eye.title = "Hide is experimental and not available in this release"; eye.classList.toggle("off", hid); eye.disabled = true;
    eye.setAttribute("aria-pressed", String(hid));
    rep.textContent = st.looks[it] ? "edit..." : "replace...";
    if (!L.slots[it].writable) { rep.disabled = true; rep.title = "Acros (monotone) can be renamed, moved or hidden, never replaced"; }
    else rep.onclick = () => openEditor(it);
  } else { eye.disabled = true; eye.hidden = true; rep.hidden = true; }
  r.append(h, ud, slot, nmw, base, src, eye, rep);
  r.onkeydown = (e) => {
    if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault(); moveTo(i, i + (e.key === "ArrowUp" ? -1 : 1));
  };
  rowState(r, it);
  return r;
}

// name counter, source badge, error mark of one row (in place: typing must not rebuild the row)
function rowState(r, it) {
  const [t, cls, title] = srcBadge(it), s = r.querySelector(".src");
  s.textContent = t; s.title = title; s.className = "badge src " + cls;
  if (!isLookSlot(it)) return;
  const name = st.names[it], cap = P.slotCap(L, it), c = r.querySelector(".count"), bad = P.nameProblem(L, it, name);
  c.textContent = `${name.length}/${cap}`; c.classList.toggle("over", !!bad); c.title = bad || "fits";
  r.classList.toggle("bad", !!bad);
}

function render() {
  const list = $("list");
  list.textContent = "";
  list.append(fixedRow());
  st.arrangement.forEach((it, i) => list.append(rowFor(it, i)));
  problems();
}

function focusRow(it) { const r = document.querySelector(`.row[data-key="${keyOf(it)}"]`); if (r) r.focus(); }
function moveTo(from, to) {
  if (to < 0 || to >= st.arrangement.length || from === to) return;
  const it = st.arrangement[from];
  st.arrangement = P.move(st.arrangement, from, to);
  render(); focusRow(it);
}
function toggleHidden(s) {
  st.hidden = st.hidden.includes(s) ? st.hidden.filter((x) => x !== s) : st.hidden.concat(s).sort((a, b) => a - b);
  render(); const b = document.querySelector(`.row[data-key="${keyOf(s)}"] [data-role=eye]`); if (b) b.focus();
}

// pointer drag of the handle (own implementation): the dragged row stays in place, a line shows the drop position
let drag = null;
function dragTarget(e) {
  const rows = [...$("list").querySelectorAll(".row:not(.fixed)")];
  let to = 0;
  rows.forEach((r, k) => { if (k === drag.from) return; const b = r.getBoundingClientRect(); if (e.clientY > b.top + b.height / 2) to++; });
  const others = rows.filter((_, k) => k !== drag.from);
  rows.forEach((r) => r.classList.remove("drop-before", "drop-after"));
  if (to < others.length) others[to].classList.add("drop-before"); else others[others.length - 1].classList.add("drop-after");
  return to;
}
function dragEnd(e, commit) {
  if (!drag) return;
  const d = drag; drag = null;
  d.handle.releasePointerCapture && d.handle.hasPointerCapture(d.pid) && d.handle.releasePointerCapture(d.pid);
  document.querySelectorAll(".row").forEach((r) => r.classList.remove("drag", "drop-before", "drop-after"));
  if (commit && d.to !== d.from) moveTo(d.from, d.to);
}
$("list").addEventListener("pointerdown", (e) => {
  const h = e.target.closest("[data-role=handle]");
  if (!h || e.button !== 0) return;
  const row = h.closest(".row"); e.preventDefault();
  drag = { from: Number(row.dataset.i), to: Number(row.dataset.i), handle: h, pid: e.pointerId };
  h.setPointerCapture(e.pointerId); row.classList.add("drag");
});
$("list").addEventListener("pointermove", (e) => {
  if (!drag) return;
  drag.to = dragTarget(e);
  if (e.clientY < 60) window.scrollBy(0, -14); else if (e.clientY > window.innerHeight - 60) window.scrollBy(0, 14);
});
$("list").addEventListener("pointerup", (e) => dragEnd(e, true));
$("list").addEventListener("pointercancel", (e) => dragEnd(e, false));

// ---- problems (client-side mirror of the checker) -----------------------------------------------------------------------------
function problems() {
  const r = P.validateState(L, st), box = $("problems");
  box.textContent = "";
  for (const e of r.errors) box.append(el("div", "e", `ERROR ${e.where}: ${e.msg}`));
  for (const w of r.warnings) box.append(el("div", "w", `warning ${w.where}: ${w.msg}`));
  if (!r.errors.length) box.append(el("div", "ok", "Pack rules satisfied (client-side check; lookfile_check.py on your PC stays the authority)."));
  const bad = new Set(r.errors.map((e) => e.slot).filter((s) => s));
  document.querySelectorAll(".row[data-slot]").forEach((row) => row.classList.toggle("bad", bad.has(Number(row.dataset.slot))));
  return r;
}

// ---- pack meta + I/O ------------------------------------------------------------------------------------------------------------
function syncMeta() {
  $("pname").value = st.name; $("sha1").value = st.base.sha1;
  const k = L.releases.findIndex((r) => r.sha1 === st.base.sha1);
  $("rel").value = k >= 0 ? String(k) : "custom";
}
function download(name, text, type = "application/json") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; document.body.appendChild(a); a.click(); a.remove();
}
function showOut(text) { const o = $("out"); o.hidden = false; o.textContent = text; }
function exportable() {
  const r = problems();
  if (r.errors.length) { showOut("Not exported: fix the errors listed above first."); return null; }
  return P.buildPack(L, st);
}
async function applyObject(obj, from) {
  const r = P.parsePack(L, obj);
  if (!r.state) {
    const box = $("problems"); box.textContent = "";
    box.append(el("div", "e", `Import refused (${from}): the file breaks the pack rules, nothing was changed.`));
    r.errors.forEach((e) => box.append(el("div", "e", `ERROR ${e.where}: ${e.msg}`)));
    return false;
  }
  closeEditor(); st = r.state; syncMeta(); render();
  const box = $("problems");
  box.prepend(el("div", "ok", `Imported ${from}: ${Object.keys(st.looks).length} look(s), ${st.hidden.length} hidden, order prefix ${P.buildPack(L, st).pack.order ? P.buildPack(L, st).pack.order.length : 0}.`));
  r.warnings.forEach((w) => box.append(el("div", "w", `warning ${w.where}: ${w.msg}`)));
  return true;
}
async function importFile(f) {
  let obj;
  try { obj = JSON.parse(await f.text()); } catch (e) { showOut("Cannot read " + f.name + ": " + e.message); return; }
  await applyObject(obj, f.name);
}
async function shareLink() {
  const obj = exportable(); if (!obj) return;
  const frag = await P.shareEncode(obj), url = location.origin + location.pathname + "#" + frag;
  history.replaceState(null, "", "#" + frag);
  let msg = `Share link (${url.length} characters). The pack is in the URL fragment: this page never sends it anywhere; whoever receives the link gets the names, order and fitted numbers.`;
  if (url.length > 2000) msg += " Long link: some chat apps cut long links, prefer the .pack.json file.";
  try { await navigator.clipboard.writeText(url); msg += " Copied to the clipboard."; } catch { msg += " (clipboard not available: select and copy it)"; }
  showOut(msg + "\n\n" + url);
}
function showCommand() {
  const files = P.lutFiles(st).map((f) => `  slot ${f.slot}: ${f.file}`).join("\n");
  showOut("1. Export pack JSON and save it as " + P.packFileName(st) + " next to looktool/om10mi_look.py.\n2. Put your own release image (sha1 " + st.base.sha1 + ") and the tables the looks were fitted from into folders on your PC.\n3. Run:\n\n  "
    + P.buildCommand(st) + "\n\nTables the builder looks for in --lut-dir (it re-scores each look exactly when found; a missing table uses the target-free gate):\n" + (files || "  (none: no looks replaced)")
    + "\n\nThe builder validates the pack, checks the image sha1, writes slots / names / order, audits and runs the acceptance battery; a failing step builds nothing. It never writes to a camera or a card by itself.");
}

// ---- look editor -----------------------------------------------------------------------------------------------------------------------
function licenceString() {
  if (ed.licence !== "@page") return ed.licence;
  const kind = $("lic").value, who = $("lic_by").value.replace(/[^\x20-\x7e]/g, "").trim();
  return (kind + (who ? " - " + who : "")).slice(0, 100);
}
function licenceProblem() {
  if (ed.licence !== "@page") return "";
  const kind = $("lic").value, who = $("lic_by").value.trim();
  return /^CC BY/.test(kind) && !who ? "The licence " + kind + " requires attribution: fill in the author / source box." : "";
}
function licenceNote() {
  const t = { "unknown": "Licence unknown: keep the pack private; do not publish a look made from a table whose licence you cannot confirm.",
    "CC BY 4.0": "Attribution required (author / source box). The look numbers are a derivative of the table: credit it wherever you share them.",
    "CC BY-SA 4.0": "Attribution required, and the pack / numbers fitted from this table are ShareAlike: share them under CC BY-SA 4.0 with the credit.",
    "CC BY-NC-SA 4.0": "NonCommercial + ShareAlike: the pack and the numbers fitted from it inherit these terms; no commercial use, share alike, credit the author.",
    "all rights reserved": "Not for redistribution: keep the pack and the built image for your own camera only." }[$("lic").value];
  $("licnote").textContent = t || "";
}

function getDataset() {
  if (ed.ds) return ed.ds;
  const s = synthDataset(64, 48), ds = makeDataset(ed.model, s.base, s.scenes, baseToX);
  ds.label = "ref-syn-1 (synthetic, 6 scenes x 64x48)";
  ds.ranker = new Ranker(ed.model, ds);
  return (ed.ds = ds);
}

async function loadLut(text, fileName, bytes, licence) {
  const info = await importLutText(text, fileName);
  ed.lut = info.lut33; ed.lutInfo = info; ed.fileName = fileName; ed.licence = licence; ed.fileSha = await sha256Hex(bytes);
  ed.fits = {}; ed.hdr = null; ed.stage1 = null;
  $("space").value = info.space;
  $("lutinfo").textContent = `${info.name} - ${info.kind}, native ${info.native.n}^3${info.exactNodes ? "" : " -> resampled to 33^3"}` + (info.notes.length ? "; " + info.notes.join("; ") : "");
  if (ed.slot) $("ed_name").value = P.sanitizeName(fileName.replace(/\.[^.]*$/, "")).trim().slice(0, P.slotCap(L, ed.slot));
  log(`loaded ${fileName}: ${info.kind} ${info.native.n}^3`);
  await rankNow();
  nameCount();
}
async function loadSample(name) {
  const buf = new Uint8Array(await (await fetch("samples/" + name)).arrayBuffer());
  await loadLut(new TextDecoder().decode(buf), name, buf, "CC0-1.0");
}

async function rankNow() {
  if (!ed.lut) return;
  const ds = getDataset(), res = ds.ranker.stage1(ed.lut, $("space").value);
  ed.stage1 = res; ed.lt = res.lt; ed.fits = {}; ed.hdr = null;
  selectBest();
  $("rankinfo").textContent = `Stage 1 on ${ds.label}: ${ms(res.ms)} (target + ${ed.model.candidates.length} candidates). DCP-base-only dE ${res.dcpBaseDE.toFixed(2)}. Scores are model predictions.`;
  renderTable(); await drawPreview();
}
function selectBest() {
  if (!ed.stage1 || !ed.mode) return;
  const best = ed.stage1.ranking.find((e) => e.mode === ed.mode);
  ed.selected = best ? best.candidate : null;
}
const fitView = (r) => {
  const on = $("guard").checked;
  return { candidate: r.candidate, mode: r.mode, luma: r.luma, orf: r.orf, theta: r.theta, strength: on ? r.toneStrength : 1, dE: on ? r.dE : r.dEunguarded,
    pct_lt5: on ? r.pct_lt5 : r.pct_lt5_unguarded, guards: on ? r.guards : { ...r.guards, tone_strength: 1, hdr_clip_pct: null } };
};
function renderTable() {
  const tb = $("rank").querySelector("tbody");
  tb.textContent = "";
  if (!ed.stage1) return;
  ed.stage1.ranking.forEach((e, i) => {
    const tr = el("tr"), ok = e.mode === ed.mode;
    tr.className = (ok ? "" : "off") + (e.candidate === ed.selected ? " sel" : "");
    tr.dataset.cand = e.candidate;
    const ff = ed.fits[e.candidate] ? fitView(ed.fits[e.candidate]).dE.toFixed(3) : "";
    [i + 1, e.candidate, e.mode, e.dE.toFixed(3), e.pct_lt5.toFixed(1), ff].forEach((v) => tr.append(el("td", "", String(v))));
    if (ok) tr.onclick = async () => { ed.selected = e.candidate; renderTable(); await drawPreview(); };
    else tr.title = `a slot of base mode ${ed.mode} only takes ${ed.mode} candidates`;
    tb.append(tr);
  });
}

// preview (6 scenes) + before/after divider
function previewSet() {
  if (ed.preview) return ed.preview;
  const tw = 96, th = 72, w = tw * 3, h = th * 2, base = new Float32Array(w * h * 3);
  SCENE_DEFS.forEach((d, i) => {
    const tile = renderScene(d, tw, th), ox = (i % 3) * tw, oy = Math.floor(i / 3) * th;
    for (let y = 0; y < th; y++) base.set(tile.subarray(y * tw * 3, (y + 1) * tw * 3), ((oy + y) * w + ox) * 3);
  });
  return (ed.preview = { w, h, base, x: baseToX(ed.model, base, new Float32Array(base.length)) });
}
function toCanvas(rgb, w, h) {
  const c = document.createElement("canvas"); c.width = w; c.height = h;
  const ctx = c.getContext("2d"), im = ctx.createImageData(w, h);
  for (let i = 0; i < w * h; i++) { for (let k = 0; k < 3; k++) im.data[i * 4 + k] = rgb[i * 3 + k] * 255 + 0.5; im.data[i * 4 + 3] = 255; }
  ctx.putImageData(im, 0, 0);
  return c;
}
function currentCandidate() {
  const c = ed.model.candidates.find((c) => c.name === ed.selected), f = ed.fits[c.name];
  if (f) { const v = fitView(f); return Object.assign(fitCandidate(ed.model, v.mode, v.orf, Float64Array.from(v.theta), v.strength, v.luma), { name: c.name }); }
  return c;
}
// the numbers that will be written to the file (33-knot curves rounded to 5 decimals), so predicted.dE is the file's own value
function exportedFit(name) {
  const f = ed.fits[name];
  if (!f) return null;
  const v = fitView(f), tb = toneBlock(v.theta, v.strength, v.luma);
  const cv = { d: ["r", "g", "b"].map((k) => tb.c_curves[k].map((p) => p[1])), h: tb.y_curve.map((p) => p[1]), luma: tb.luma_arg };
  const ds = getDataset(), sim = simulate(candidateFromCurves(ed.model, v.mode, v.orf, cv), ds.x, new Float32Array(ds.base.length));
  const sc = ds.ranker.scorer.score(ed.lt, rgb2lab(sim));
  return { ...v, dE: sc.dE, pct_lt5: sc.pct_lt5 };
}
async function drawPreview() {
  if (!ed.lut || !ed.stage1 || !ed.selected) return;
  const set = previewSet(), n = set.w * set.h, t0 = performance.now();
  const tgt = applyLut(ed.lut, set.base, new Float32Array(set.base.length), $("space").value);
  const cand = currentCandidate(), sim = simulate(cand, set.x, new Float32Array(set.base.length));
  const lt = rgb2lab(tgt), lo = rgb2lab(sim), dl = new Float32Array(n);
  for (let i = 0; i < n; i++) dl[i] = lt[i * 3] - lo[i * 3];
  const sh = Float32Array.from(dl).sort()[n >> 1];
  let sum = 0;
  for (let i = 0; i < n; i++) { const k = i * 3; sum += de2000(lt[k], lt[k + 1], lt[k + 2], lo[k] + sh, lo[k + 1], lo[k + 2]); }
  ed.tgt = toCanvas(tgt, set.w, set.h); ed.sim = toCanvas(sim, set.w, set.h);
  paintDivider();
  const f = exportedFit(cand.name), g = f && f.guards;
  $("readout").textContent = `Camera model ${cand.name} (${cand.mode})${f ? ", fitted matrix + tone curves" : ", not fitted yet (stock tone, stock matrix)"}. Mean dE of this preview ${(sum / n).toFixed(2)} (exposure matched, ${ms(performance.now() - t0)}).`
    + (f ? ` Fit on the reference set: dE ${f.dE.toFixed(3)}, ${f.pct_lt5.toFixed(1)} % of pixels < 5; tone strength x${f.strength}${g && g.hdr_clip_pct != null ? ", +0.5 EV clip " + g.hdr_clip_pct + " %" : ""}. These are model predictions, not camera results.` : "");
}
function paintDivider() {
  const cv = $("cmp"), ctx = cv.getContext("2d");
  if (!ed.tgt) { ctx.clearRect(0, 0, cv.width, cv.height); return; }
  const W = cv.width, H = cv.height, x = Math.round(ed.divider * W);
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(ed.tgt, 0, 0, ed.tgt.width, ed.tgt.height, 0, 0, W, H);
  if (x < W) ctx.drawImage(ed.sim, (x / W) * ed.sim.width, 0, ed.sim.width - (x / W) * ed.sim.width, ed.sim.height, x, 0, W - x, H);
  ctx.fillStyle = "#fff"; ctx.fillRect(x - 1, 0, 2, H);
  ctx.beginPath(); ctx.arc(x, H / 2, 14, 0, Math.PI * 2); ctx.fillStyle = "#fff"; ctx.fill();
  ctx.fillStyle = "#222"; ctx.beginPath(); ctx.moveTo(x - 8, H / 2); ctx.lineTo(x - 3, H / 2 - 5); ctx.lineTo(x - 3, H / 2 + 5); ctx.fill();
  ctx.beginPath(); ctx.moveTo(x + 8, H / 2); ctx.lineTo(x + 3, H / 2 - 5); ctx.lineTo(x + 3, H / 2 + 5); ctx.fill();
  ctx.font = "13px system-ui, sans-serif"; ctx.fillStyle = "rgba(0,0,0,.6)"; ctx.fillRect(4, 4, 92, 20); ctx.fillRect(W - 134, 4, 130, 20);
  ctx.fillStyle = "#fff"; ctx.fillText("target (LUT)", 10, 19); ctx.fillText("camera model", W - 128, 19);
}
function setDivider(v) { ed.divider = Math.max(0, Math.min(1, v)); paintDivider(); }
{
  const cv = $("cmp"); let on = false;
  const at = (e) => { const b = cv.getBoundingClientRect(); setDivider((e.clientX - b.left) / b.width); };
  cv.addEventListener("pointerdown", (e) => { on = true; cv.setPointerCapture(e.pointerId); at(e); });
  cv.addEventListener("pointermove", (e) => { if (on) at(e); });
  cv.addEventListener("pointerup", () => { on = false; });
  cv.addEventListener("pointercancel", () => { on = false; });
  cv.addEventListener("keydown", (e) => { if (e.key === "ArrowLeft") { setDivider(ed.divider - 0.03); e.preventDefault(); } else if (e.key === "ArrowRight") { setDivider(ed.divider + 0.03); e.preventDefault(); } });
}

// full fit in the worker pool (one job; the candidate is the best one of the slot's base mode unless another one of that mode is selected)
async function doFit() {
  if (!ed.stage1 || !ed.selected || ed.fitting) return;
  const ds = getDataset(), space = $("space").value, name = ed.selected;
  if (!ed.hdr) ed.hdr = makeHdrProbe(ds.x, ds.base, (b) => applyLut(ed.lut, b, new Float32Array(b.length), space));
  if (!ed.pool) ed.pool = new FitPool(ed.modelJson);
  const job = { candidate: name, xS: ds.x, lt: ed.lt, scenes: ds.scenes.map((s) => ({ start: s.start, count: s.count })), hdr: ed.hdr, opts: {} };
  const box = $("fitprogress"); box.textContent = "";
  const row = el("div"), bar = document.createElement("progress"), info = el("span", "fi", "queued");
  bar.max = 1; bar.value = 0; row.append(el("span", "fn", name), bar, document.createTextNode(" "), info); box.append(row);
  ed.fitting = true; $("fit").disabled = true; $("cancel").disabled = false;
  const t0 = performance.now(); let pend = null, queued = false;
  try {
    const out = await ed.pool.run([job], (i, p) => {
      pend = p; if (queued) return; queued = true;
      requestAnimationFrame(() => { queued = false; bar.value = pend.frac; info.textContent = `${pend.stage} ${Math.round(pend.frac * 100)}%${pend.dE != null ? "  dE " + pend.dE.toFixed(3) : ""}`; });
    });
    const o = out[0];
    if (o.error) { info.textContent = "error: " + o.error; log(`fit ${name} ERROR ${o.error}`); }
    else {
      const r = o.result; ed.fits[r.candidate] = r; bar.value = 1;
      info.textContent = `done: dE ${r.dE.toFixed(3)}${r.toneStrength < 1 ? " (clip guard: tone x" + r.toneStrength + ", unguarded " + r.dEunguarded.toFixed(3) + ")" : ""}, ${(r.ms / 1000).toFixed(1)} s`;
      $("fitinfo").textContent = `Fit done in ${((performance.now() - t0) / 1000).toFixed(1)} s on a worker.`;
      log(`fit ${r.candidate}: dE ${r.startDE.toFixed(3)} -> ${r.dEunguarded.toFixed(3)} unguarded / ${r.dE.toFixed(3)} guarded (strength ${r.toneStrength}), ${r.ms} ms`);
    }
  } catch (e) {
    $("fitinfo").textContent = e instanceof FitCancelled ? "fit cancelled (worker terminated)" : "fit failed: " + e.message;
    info.textContent = e instanceof FitCancelled ? "cancelled" : "failed";
  } finally { ed.fitting = false; $("fit").disabled = false; $("cancel").disabled = true; }
  renderTable(); await drawPreview();
}

function nameCount() {
  if (!ed.slot) return;
  const v = $("ed_name").value, bad = P.nameProblem(L, ed.slot, v), c = $("ed_count");
  c.textContent = `${v.length}/${P.slotCap(L, ed.slot)}` + (bad ? " - " + bad : "");
  c.classList.toggle("over", !!bad);
}
function acceptLook() {
  const msg = (t) => { $("ed_msg").textContent = t; return null; };
  if (!ed.slot) return;
  const name = $("ed_name").value, np = P.nameProblem(L, ed.slot, name);
  if (np) return msg("Name: " + np);
  if (!ed.stage1 || !ed.selected) return msg("Load a LUT first.");
  const fit = exportedFit(ed.selected);
  if (!fit) return msg("Fit the selected candidate first (button above).");
  if (fit.mode !== ed.mode) return msg(`Candidate mode ${fit.mode} does not match the slot's base mode ${ed.mode}.`);
  const lp = licenceProblem();
  if (lp) { $("licnote").textContent = lp; return msg(lp); }
  const chosen = ed.model.candidates.find((c) => c.name === ed.selected), fits = {};
  for (const n of Object.keys(ed.fits)) fits[n] = fitView(ed.fits[n]);
  const info = ed.lutInfo;
  const lf = buildLookFile({ name, slot: ed.slot, source: { type: info.kind, name: ed.fileName, licence: licenceString(), sha256: ed.fileSha, space: $("space").value, title: info.name, tableMd5: info.tableMd5 },
    stage1: ed.stage1, chosen: { candidate: chosen.name, mode: chosen.mode, orf: chosen.orf }, fit, fits, scenes: getDataset().label, notes: $("ed_notes").value });
  const look = lf.looks[0];
  if ($("ed_icon").value === "keep") look.icon = "keep";
  st.looks[ed.slot] = look; st.names[ed.slot] = name;
  render();
  msg(`Accepted into slot ${ed.slot}: ${name}, ${look.fit.mode}, predicted dE ${look.fit.predicted.dE} (model value).`);
}

function openEditor(slot) {
  ed.slot = slot; ed.mode = P.slotMode(L, slot);
  const look = st.looks[slot];
  $("editor").hidden = false;
  $("ed_title").textContent = `slot ${slot} (${L.slots[slot].stock})`; $("ed_mode").textContent = ed.mode;
  $("ed_name").value = look ? st.names[slot] : ed.lutInfo ? P.sanitizeName(ed.fileName.replace(/\.[^.]*$/, "")).trim().slice(0, P.slotCap(L, slot)) : st.names[slot];
  $("ed_icon").value = look && look.icon === "keep" ? "keep" : "roll"; $("ed_notes").value = look && look.notes ? look.notes : "";
  $("ed_msg").textContent = look ? `Stored look: ${look.source && look.source.name}, predicted dE ${look.fit && look.fit.predicted && look.fit.predicted.dE}. Load the table again to change it.` : "";
  $("unlook").disabled = !look;
  const cs = $("copysel"); cs.textContent = "";
  const others = Object.keys(st.looks).map(Number).filter((s) => s !== slot && P.slotMode(L, s) === ed.mode);
  others.forEach((s) => { const o = el("option", "", `slot ${s}: ${st.names[s]}`); o.value = s; cs.append(o); });
  $("copyrow").hidden = !others.length;
  selectBest(); renderTable(); nameCount(); drawPreview();
  $("editor").scrollIntoView({ block: "start" });
}
function closeEditor() { ed.slot = null; ed.mode = null; $("editor").hidden = true; }
function copyLook() {
  const from = Number($("copysel").value);
  if (!ed.slot || !st.looks[from]) return;
  const l = JSON.parse(JSON.stringify(st.looks[from]));
  l.slot = ed.slot; st.looks[ed.slot] = l;
  st.names[ed.slot] = st.names[from].slice(0, P.slotCap(L, ed.slot));
  render(); openEditor(ed.slot);
  $("ed_msg").textContent = `Copied the look of slot ${from} into slot ${ed.slot}` + (st.names[from].length > P.slotCap(L, ed.slot) ? " (name shortened to the capacity of this slot)." : ".");
}

// ---- init ----------------------------------------------------------------------------------------------------------------------------------------
async function init() {
  L = await (await fetch("panel-slots.json")).json();
  ed.modelJson = await (await fetch("model-cm-v2-web1.json")).json();
  ed.model = await loadModel();
  st = P.emptyState(L);
  const rel = $("rel");
  L.releases.forEach((r, i) => { const o = el("option", "", `${r.name} (${r.sha1.slice(0, 8)}...)`); o.value = i; rel.append(o); });
  const oc = el("option", "", "other (enter sha1)"); oc.value = "custom"; rel.append(oc);
  rel.onchange = () => {
    if (rel.value === "custom") { st.base = { name: "custom", sha1: $("sha1").value.trim().toLowerCase() }; }
    else { const r = L.releases[Number(rel.value)]; st.base = { name: r.name, sha1: r.sha1 }; $("sha1").value = r.sha1; }
    problems();
  };
  $("sha1").oninput = () => {
    const v = $("sha1").value.trim().toLowerCase(), k = L.releases.findIndex((r) => r.sha1 === v);
    st.base = k >= 0 ? { name: L.releases[k].name, sha1: v } : { name: "custom", sha1: v };
    rel.value = k >= 0 ? String(k) : "custom"; problems();
  };
  $("pname").oninput = () => { st.name = $("pname").value; problems(); };
  $("export").onclick = () => { const o = exportable(); if (o) { const t = JSON.stringify(o, null, 1); download(P.packFileName(st), t); showOut(`Exported ${P.packFileName(st)} (${t.length} bytes). Check it with: python fw/lut_stage1/lookfile/lookfile_check.py ${P.packFileName(st)}`); } };
  $("import").onchange = async (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) await importFile(f); };
  $("share").onclick = shareLink;
  $("cmd").onclick = showCommand;
  $("reset").onclick = () => { if (window.confirm("Reset the list, names, hidden looks and all stored looks?")) { closeEditor(); st = P.emptyState(L); syncMeta(); render(); $("out").hidden = true; } };
  // editor wiring
  $("file").onchange = async (e) => { const f = e.target.files[0]; if (!f) return; const buf = new Uint8Array(await f.arrayBuffer()); try { await loadLut(new TextDecoder().decode(buf), f.name, buf, "@page"); } catch (err) { $("lutinfo").textContent = "Error: " + err.message; log("ERROR " + err.message); } };
  document.querySelectorAll("button[data-sample]").forEach((b) => (b.onclick = () => loadSample(b.dataset.sample)));
  $("space").onchange = rankNow;
  $("fit").onclick = doFit;
  $("cancel").onclick = () => ed.pool && ed.pool.cancel();
  $("guard").onchange = async () => { renderTable(); await drawPreview(); };
  $("lic").onchange = licenceNote; licenceNote();
  $("ed_name").oninput = nameCount;
  $("accept").onclick = acceptLook;
  $("unlook").onclick = () => { if (!ed.slot) return; delete st.looks[ed.slot]; st.names[ed.slot] = L.slots[ed.slot].stock; render(); openEditor(ed.slot); $("ed_msg").textContent = "Look removed: the slot is stock again."; };
  $("close").onclick = closeEditor;
  $("copy").onclick = copyLook;
  syncMeta(); render();
  window.panel = { get st() { return st; }, ed, L, P, render, openEditor, loadSample, doFit, applyObject, acceptLook, rankNow };
  if (location.hash.startsWith("#" + "pack=")) {
    try { await applyObject(await P.shareDecode(location.hash), "share link"); } catch (e) { showOut("Share link not loaded: " + e.message); }
  }
  $("status").textContent = "ready";
  window.__ready = true;
}
init().catch((e) => { $("status").textContent = "init failed: " + e.message; console.error(e); });
