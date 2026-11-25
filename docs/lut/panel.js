// panel.js - look pack builder. Static, no network except same-origin files (model json, panel-slots.json, samples).
// Flow: import a LUT (.cube / .xmp: button, drop anywhere, sample chip) -> base mode + slot -> name + menu position -> before/after -> add to pack.
// Pack I/O and validation: pack.js. Pure flow helpers (drop classification, slots per mode, anchors): flow.js. Editor pipeline (import -> rank -> pool fit ->
// preview -> look object) follows app.js; the numbers written to a look are exactly those of the earlier per-slot editor.
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
import { makeZip, readZip } from "./zip.js";
import * as F from "./flow.js";

const $ = (id) => document.getElementById(id);
const log = (m) => { const el = $("log"); el.textContent += m + "\n"; el.scrollTop = el.scrollHeight; console.log(m); };
const ms = (v) => (v < 10 ? v.toFixed(1) : v.toFixed(0)) + " ms";
const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }

let L = null;      // panel-slots.json
let st = null;     // pack state (pack.js)
const luts = new Map();   // sha256 hex -> { name, bytes }: every LUT file loaded in this page, exactly as read (goes into the .omlook.zip)
// editor state: the LUT in hand, the chosen base mode / slot, the fits, the preview
const ed = { slot: null, pendingSlot: null, mode: null, modes: [], nameDirty: false, model: null, modelJson: null, ds: null, lut: null, lutInfo: null, fileSha: null, fileName: "",
  licence: "", stage1: null, lt: null, selected: null, fits: {}, hdr: null, pool: null, fitting: false, fitWanted: false, gen: 0, preview: null, photo: null, photoName: "",
  useOwn: false, left: "orig", rows: "all", divider: 0.5, shown: null, swept: false };

// ---- icons (own, drawn for this page) ----------------------------------------------------------------------------------------------
const GRIP = '<svg viewBox="0 0 10 16" width="10" height="16" aria-hidden="true"><circle cx="2.5" cy="3" r="1.5"/><circle cx="7.5" cy="3" r="1.5"/><circle cx="2.5" cy="8" r="1.5"/><circle cx="7.5" cy="8" r="1.5"/><circle cx="2.5" cy="13" r="1.5"/><circle cx="7.5" cy="13" r="1.5"/></svg>';
const CHEV = (up) => `<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="${up ? "M3.5 10.5 8 6l4.5 4.5" : "M3.5 5.5 8 10l4.5-4.5"}"/></svg>`;

const keyOf = (it) => P.itemKey(it);
const isLookSlot = (it) => typeof it === "number";
const itemByKey = (k) => st.arrangement.find((it) => keyOf(it) === k);
const visibleRow = (it) => ed.rows === "all" || isLookSlot(it);

// ---- pack list ----------------------------------------------------------------------------------------------------------------------
function rowBase(it) { return isLookSlot(it) ? L.slots[it].mode : L.stock_modes[it] || ""; }

function fixedRow() {
  const r = el("li", "row fixed"), h = el("span", "handle");
  h.innerHTML = GRIP;
  r.append(h, el("span", "pos", "0"), el("span", "nm", "i-Enhance (fixed first; the spare record stays last)"), el("span"));
  return r;
}

function rowFor(it, i, flash) {
  const look = isLookSlot(it), key = keyOf(it);
  const r = el("li", "row " + (look ? "look" : "stock") + (flash ? " flash" : ""));
  r.tabIndex = 0; r.dataset.key = key; r.dataset.i = i;
  if (look) r.dataset.slot = it;
  const h = el("span", "handle"); h.innerHTML = GRIP; h.title = "Drag to move"; h.dataset.role = "handle";
  const main = el("div", "main");
  if (look) {
    const box = el("div", "namebox"), inp = el("input"), cnt = el("span", "count");
    inp.value = st.names[it]; inp.maxLength = 40; inp.spellcheck = false; inp.autocomplete = "off"; inp.dataset.role = "name";
    inp.setAttribute("aria-label", `Menu name of slot ${it}`);
    inp.oninput = () => { st.names[it] = inp.value; rowState(r, it); problems(); renderAnchors(); refreshExport(); };
    box.append(inp, cnt);
    const meta = el("div", "meta"), dot = el("i", "dot " + rowBase(it)), mode = el("span", "", rowBase(it)), src = el("span", "src");
    const rep = el("button", "btn linkish"), rev = el("button", "btn linkish", "Remove look"), unh = el("button", "btn linkish", "Unhide");
    rep.type = rev.type = unh.type = "button";
    rep.dataset.role = "replace"; rev.dataset.role = "revert"; unh.dataset.role = "unhide";
    rep.textContent = "Replace"; rep.title = "Import a LUT into this slot";
    if (!L.slots[it].writable) { rep.hidden = true; }
    rep.onclick = () => replaceSlot(it);
    rev.onclick = () => revertSlot(it);
    unh.onclick = () => { st.hidden = st.hidden.filter((x) => x !== it); render(); focusRow(it); };
    rev.hidden = !st.looks[it];
    unh.hidden = !st.hidden.includes(it);
    meta.append(dot, mode, src, rep, rev, unh);
    main.append(box, meta);
  } else main.append(el("span", "nm", it));
  const ud = el("div", "acts"), up = el("button", "mv"), dn = el("button", "mv");
  up.type = dn.type = "button";
  up.innerHTML = CHEV(true); dn.innerHTML = CHEV(false);
  up.dataset.role = "up"; dn.dataset.role = "down";
  up.setAttribute("aria-label", "Move up"); dn.setAttribute("aria-label", "Move down");
  up.title = "Move up (Alt+Up)"; dn.title = "Move down (Alt+Down)";
  const vis = st.arrangement.filter(visibleRow), vi = vis.indexOf(it);
  up.disabled = vi <= 0; dn.disabled = vi === vis.length - 1;
  up.onclick = () => stepRow(it, -1); dn.onclick = () => stepRow(it, 1);
  ud.append(up, dn);
  r.append(h, el("span", "pos", String(i + 1)), main, ud);
  r.onkeydown = (e) => {
    if (!e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault(); stepRow(it, e.key === "ArrowUp" ? -1 : 1);
  };
  rowState(r, it);
  return r;
}

// source line, name counter and error mark of one row (in place: typing must not rebuild the row)
function rowState(r, it) {
  if (!isLookSlot(it)) return;
  const l = st.looks[it], s = r.querySelector(".src");
  const bits = [];
  if (l) { const so = l.source || {}; bits.push(so.name || "LUT"); if (so.licence) bits.push(so.licence); if (l.fit && l.fit.predicted) bits.push("dE " + l.fit.predicted.dE); s.title = `fitted on ${l.fit && l.fit.mode}; predicted dE ${l.fit && l.fit.predicted && l.fit.predicted.dE} (model value)`; }
  else if (st.names[it] !== L.slots[it].stock) bits.push("renamed, stock look inside");
  else bits.push("stock look");
  if (st.hidden.includes(it)) bits.push("hidden (not available in this release)");
  s.textContent = bits.join(" \u00b7 ");
  s.classList.toggle("tagx", !!l);
  r.classList.toggle("has-look", !!l);
  const name = st.names[it], cap = P.slotCap(L, it), c = r.querySelector(".count"), inp = r.querySelector("[data-role=name]"), bad = P.nameProblem(L, it, name);
  c.textContent = `${name.length}/${cap}`; c.classList.toggle("over", !!bad); c.title = bad || "fits";
  inp.classList.toggle("over", !!bad);
  r.classList.toggle("bad", !!bad);
}

function render(flashKey) {
  const list = $("list");
  list.textContent = "";
  if (ed.rows === "all") list.append(fixedRow());
  st.arrangement.forEach((it, i) => { if (visibleRow(it)) list.append(rowFor(it, i, flashKey != null && keyOf(it) === flashKey)); });
  const n = Object.keys(st.looks).length;
  $("pack_count").textContent = `${n} look${n === 1 ? "" : "s"} of 18 slots`;
  problems(); refreshExport(); renderAnchors();
  if (flashKey != null) requestAnimationFrame(() => requestAnimationFrame(() => document.querySelectorAll(".row.flash").forEach((r) => r.classList.remove("flash"))));
}

function focusRow(it) { const r = document.querySelector(`.row[data-key="${keyOf(it)}"]`); if (r) r.focus(); }
function stepRow(it, dir) {
  const a = F.stepVisible(st.arrangement, it, dir, visibleRow);
  if (a.every((x, i) => x === st.arrangement[i])) return;
  st.arrangement = a; render(); focusRow(it);
}
function replaceSlot(s) {
  ed.pendingSlot = s;
  if (ed.lut && ed.modes.some((m) => m.mode === L.slots[s].mode)) {
    ed.mode = L.slots[s].mode; ed.slot = s; ed.nameDirty = false;
    selectBest(); renderPlace(); renderTable(); drawPreview(); scheduleFit();
    $("h-place").scrollIntoView({ block: "start", behavior: reduceMotion() ? "auto" : "smooth" });
    return;
  }
  $("place_idle").textContent = `Slot ${s} (${st.names[s]}) is waiting for a LUT: import one above.`;
  $("place_idle").hidden = false;
  $("h-import").scrollIntoView({ block: "start", behavior: reduceMotion() ? "auto" : "smooth" });
  $("choose").focus({ preventScroll: true });
}
function revertSlot(s) {
  delete st.looks[s]; st.names[s] = L.slots[s].stock;
  render(); focusRow(s); renderPlace();
  $("ed_msg").textContent = `Slot ${s} is a stock look again.`;
}

// pointer drag of the handle (own implementation): the dragged row stays in place, a line shows the drop position
let drag = null;
function dragTarget(e) {
  const rows = [...$("list").querySelectorAll(".row:not(.fixed)")], others = rows.filter((_, k) => k !== drag.from);
  let to = 0;
  others.forEach((r) => { const b = r.getBoundingClientRect(); if (e.clientY > b.top + b.height / 2) to++; });
  rows.forEach((r) => r.classList.remove("drop-before", "drop-after"));
  if (to < others.length) others[to].classList.add("drop-before"); else others[others.length - 1].classList.add("drop-after");
  return to;
}
function dragEnd(e, commit) {
  if (!drag) return;
  const d = drag; drag = null;
  if (d.handle.hasPointerCapture && d.handle.hasPointerCapture(d.pid)) d.handle.releasePointerCapture(d.pid);
  const rows = [...$("list").querySelectorAll(".row:not(.fixed)")], others = rows.filter((_, k) => k !== d.from);
  document.querySelectorAll(".row").forEach((r) => r.classList.remove("drag", "drop-before", "drop-after"));
  if (!commit || d.to === d.from) return;
  const it = itemByKey(rows[d.from].dataset.key);
  st.arrangement = d.to < others.length ? F.moveBefore(st.arrangement, it, itemByKey(others[d.to].dataset.key)) : F.placeAfter(st.arrangement, it, itemByKey(others[others.length - 1].dataset.key));
  render(); focusRow(it);
}
$("list").addEventListener("pointerdown", (e) => {
  const h = e.target.closest("[data-role=handle]");
  if (!h || e.button !== 0) return;
  const row = h.closest(".row"); e.preventDefault();
  const rows = [...$("list").querySelectorAll(".row:not(.fixed)")], from = rows.indexOf(row);
  drag = { from, to: from, handle: h, pid: e.pointerId };
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
  if (st.hidden.length) box.append(el("div", "w", `warning hidden: slot${st.hidden.length > 1 ? "s" : ""} ${st.hidden.join(", ")} hidden by the imported pack. Hide is not available in this release: use Unhide in the list before you build.`));
  if (!r.errors.length) box.append(el("div", "ok", "Pack rules satisfied (client-side check; lookfile_check.py on your PC stays the authority)."));
  const bad = new Set(r.errors.map((e) => e.slot).filter((s) => s));
  document.querySelectorAll(".row[data-slot]").forEach((row) => row.classList.toggle("bad", bad.has(Number(row.dataset.slot))));
  return r;
}

// ---- export panel -----------------------------------------------------------------------------------------------------------------
function syncMeta() {
  $("pname").value = st.name; $("sha1").value = st.base.sha1;
  const k = L.releases.findIndex((r) => r.sha1 === st.base.sha1);
  $("rel").value = k >= 0 ? String(k) : "custom";
  $("sha_row").hidden = $("rel").value !== "custom";
}
function refreshExport() {
  saveSoon(); refreshBuildState();
  $("pack_file").textContent = P.packFileName(st);
  $("cmd").textContent = P.buildCommand(st);
  const files = P.lutFiles(st).map((f) => `slot ${f.slot}: ${f.file}`);
  $("cmd_files").textContent = files.length
    ? "Tables the builder looks for in --lut-dir (it re-scores each look exactly when found; a missing table is refused when the stricter check fails). The zip export already contains them: " + files.join(", ") + "."
    : "No look replaced yet: the pack only holds names and order.";
}
function download(name, text, type = "application/json") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; document.body.appendChild(a); a.click(); a.remove();
}
function saveBlob(name, bytes, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([bytes], { type }));
  a.download = name; document.body.appendChild(a); a.click(); a.remove();
}
function exportZip() {
  const o = exportable(); if (!o) return;
  const r = P.omlookEntries(st, o, luts);
  if (r.clash.length) return showOut(`Not exported: two different LUT files are both called ${r.clash.join(", ")}. Rename one of them on your disk and import it again.`);
  if (r.missing.length) return showOut(`Not exported as a zip: the page does not hold the LUT file for ${r.missing.join(", ")}. Import that LUT again (Choose file, or drop it on the page) and press Export pack once more. `
    + "(A pack opened from a JSON file or a share link has no LUT files; the plain JSON export below still works with --lut-dir.)");
  const zip = makeZip(r.files), name = P.zipFileName(st);
  saveBlob(name, zip, "application/zip");
  const luts_ = r.files.filter((f) => f.name.startsWith("luts/")).map((f) => f.name.slice(5));
  showOut(`Exported ${name} (${zip.length} bytes): the pack${luts_.length ? " + " + luts_.join(", ") : ""}.\nNext: drop ${name} on om10mi-look.exe, then copy the DCOLYMP folder it makes to the card.`);
}
// ---- in-browser build: the public Python builder (Pyodide, self-hosted in pyodide/) in a Web Worker; the firmware never leaves this page ------------------------
let bw = null, bwResult = null;
// the build log: finished lines + one transient "still working" line (replaced every few seconds), always scrolled to the newest line
let blog = [], btransient = "", tick = null, lastMsg = 0, lastStep = "";
const STALL_S = 180;      // longest silent step measured is about 40 s; 3 minutes without any message = the engine most likely died (out of memory)
function paintLog() { const o = $("build_log"); o.hidden = false; o.textContent = blog.join("\n") + (btransient ? "\n" + btransient : "") + "\n"; o.scrollTop = o.scrollHeight; }
const setBuildLog = (t, add = false) => { if (!add) blog = []; blog.push(t); btransient = ""; paintLog(); };
function startTicker(t0) {
  lastMsg = performance.now(); lastStep = "starting"; $("build_bar").hidden = false;
  tick = setInterval(() => {
    const idle = (performance.now() - lastMsg) / 1000, total = (performance.now() - t0) / 1000;
    btransient = `... still working: ${lastStep} (${total.toFixed(0)} s in total, ${idle.toFixed(0)} s since the last message)`;
    if (idle > STALL_S) btransient += "\nThe build engine has not reported for " + Math.round(idle / 60) + " minutes: it probably stopped (out of memory). Press Cancel, close other tabs and try again; it needs about 2 GB free.";
    paintLog();
  }, 5000);
}
function stopTicker() { clearInterval(tick); tick = null; btransient = ""; $("build_bar").hidden = true; }
const NO_CHANGE_HINT = "Add at least one look (Import a LUT -> Add to pack) or change the order first.";
// Build firmware is only possible when the pack changes something (a replaced look, a rename or an order change); a LUT that was imported but not added is called out
function refreshBuildState() {
  if (!st) return;
  const c = P.packChanges(P.buildPack(L, st)), busy = !!bw;
  $("build").disabled = busy || c.count === 0;
  const parts = [];
  if (c.looks) parts.push(`${c.looks} replaced look${c.looks === 1 ? "" : "s"}`);
  if (c.renames) parts.push(`${c.renames} rename${c.renames === 1 ? "" : "s"}`);
  if (c.order) parts.push("a changed menu order");
  let t = c.count ? "Your pack changes: " + parts.join(", ") + "." : NO_CHANGE_HINT;
  if (ed.lut && !Object.values(st.looks).some((l) => (l.source || {}).sha256 === ed.fileSha))
    t += ` Note: ${ed.fileName} is loaded but not in the pack yet; press Add to pack (Slot and name card) to include it.`;
  $("build_hint").textContent = t;
}
function buildDone() { if (bw) { bw.terminate(); bw = null; } stopTicker(); $("build_cancel").hidden = true; refreshBuildState(); }
function buildFailed(text) { setBuildLog(`STOPPED, nothing was built.\n\n${text}`, true); buildDone(); }
async function buildFirmware() {
  $("build_dl").hidden = true; bwResult = null;
  const f = $("stock_file").files[0];
  if (!f) return setBuildLog("Pick your official firmware file OLY_E_113_1400_0000_0000.BIN (or the unmodified version 94 image) first.");
  const o = exportable(); if (!o) return setBuildLog("Fix the errors listed above first.");
  if (!P.packChanges(o).count) return setBuildLog(NO_CHANGE_HINT);
  const r = P.omlookEntries(st, o, luts);
  if (r.clash.length) return setBuildLog(`Two different LUT files are both called ${r.clash.join(", ")}. Rename one of them on your disk and import it again.`);
  if (r.missing.length) return setBuildLog(`The page does not hold the LUT file for ${r.missing.join(", ")}. Import that LUT again (Choose file, or drop it on the page) and press Build firmware once more.`);
  const lutObj = {};
  for (const x of r.files) if (x.name.startsWith("luts/")) lutObj[x.name.slice(5)] = x.bytes;
  const packText = new TextDecoder().decode(r.files[0].bytes), name = P.zipFileName(st).replace(/\.omlook\.zip$/, "");
  setBuildLog("Reading your firmware file ...");
  const stock = new Uint8Array(await f.arrayBuffer());
  $("build_cancel").hidden = false;
  const t0 = performance.now();
  saveLast(); startTicker(t0);
  bw = new Worker("buildworker.js"); refreshBuildState();
  bw.onmessage = (e) => {
    const m = e.data;
    lastMsg = performance.now();
    if (m.type === "progress") { lastStep = m.text.replace(/^\s+/, ""); return setBuildLog(`[${((performance.now() - t0) / 1000).toFixed(0)} s] ${m.text}`, true); }
    if (m.type === "fail") return buildFailed(m.text);
    if (m.type === "done") {
      const enc = new TextEncoder();
      bwResult = { zip: makeZip([{ name: "DCOLYMP/E1139999.BIN", bytes: m.image }, { name: "HOW-TO-FLASH.txt", bytes: enc.encode(m.howto.replace(/\n/g, "\r\n")) },
        { name: P.zipFileName(st), bytes: makeZip(r.files) }]), name: name + "-firmware.zip", sha1: m.sha1 };
      setBuildLog(`DONE in ${((performance.now() - t0) / 1000).toFixed(0)} s: image sha1 ${m.sha1}.\nDownload the zip, unzip it, copy the DCOLYMP folder to the card and follow HOW-TO-FLASH.txt.\nThis file has NOT been tried on a camera; you flash at your own risk.`, true);
      $("build_dl").hidden = false; $("build_dl").textContent = "Download " + bwResult.name; buildDone();
    }
  };
  bw.onerror = (e) => { e.preventDefault(); buildFailed("The build engine stopped with an error (" + (e.message || "worker error") + "). Close other tabs and try again; it needs about 2 GB free and a current desktop browser."); };
  bw.onmessageerror = () => buildFailed("The build engine sent a result this browser could not read (probably out of memory). Close other tabs and try again; it needs about 2 GB free.");
  bw.postMessage({ cmd: "build", stock, pack: packText, luts: lutObj, name, file: f.name }, [stock.buffer]);
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
  st = r.state; ed.slot = null; ed.pendingSlot = null; ed.nameDirty = false;
  syncMeta(); render(); renderPlace();
  const box = $("problems");
  const pk = P.buildPack(L, st).pack;
  box.prepend(el("div", "ok", `Imported ${from}: ${Object.keys(st.looks).length} look(s), ${st.hidden.length} hidden, order prefix ${pk.order ? pk.order.length : 0}.`));
  r.warnings.forEach((w) => box.append(el("div", "w", `warning ${w.where}: ${w.msg}`)));
  return true;
}
// a pack zip (.omlook.zip, or the firmware zip that holds one): the pack + the LUT files it carries go back into this page, so the pack can be edited and built again
async function openZip(bytes, from) {
  const files = await readZip(bytes);
  const pk = files.find((x) => !x.name.includes("/") && /\.pack\.json$/i.test(x.name));
  if (!pk) {
    const inner = files.find((x) => !x.name.includes("/") && /\.omlook\.zip$/i.test(x.name));
    if (inner) return openZip(inner.bytes, inner.name);
    throw new Error("no *.pack.json inside");
  }
  const obj = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(pk.bytes));
  for (const x of files) if (x.name.startsWith("luts/")) luts.set(await sha256Hex(x.bytes), { name: x.name.slice(5), bytes: x.bytes });
  return applyObject(obj, from);
}
async function importFile(f) {
  if (/\.zip$/i.test(f.name)) {
    try { await openZip(new Uint8Array(await f.arrayBuffer()), f.name); } catch (e) { showOut("Cannot open " + f.name + ": " + e.message + ". Pick the .omlook.zip you saved (or the firmware zip that holds it)."); }
    return;
  }
  let obj;
  try { obj = JSON.parse(await f.text()); } catch (e) { showOut("Cannot read " + f.name + ": " + e.message); return; }
  await applyObject(obj, f.name);
}
// ---- the last pack is remembered in this browser (IndexedDB, same origin only: nothing is sent anywhere) ---------------------------------------------------
const IDB = { db: "om10mi-panel", store: "last", key: "pack", maxBytes: 60 << 20 };
function idb(op) {
  return new Promise((res, rej) => {
    const rq = indexedDB.open(IDB.db, 1);
    rq.onupgradeneeded = () => rq.result.createObjectStore(IDB.store);
    rq.onerror = () => rej(rq.error);
    rq.onsuccess = () => {
      const tx = rq.result.transaction(IDB.store, "readwrite"), r = op(tx.objectStore(IDB.store));
      tx.oncomplete = () => { rq.result.close(); res(r.result); };
      tx.onerror = tx.onabort = () => { rq.result.close(); rej(tx.error); };
    };
  });
}
let saveTimer = null;
function saveLast() {
  clearTimeout(saveTimer); saveTimer = null;
  if (!st || !Object.keys(st.looks).length) return;          // never overwrite the remembered pack with an empty page
  try {
    const obj = P.buildPack(L, st), keep = [];
    let size = 0;
    for (const l of Object.values(st.looks)) {
      const h = luts.get(String((l.source || {}).sha256 || "").toLowerCase());
      if (h && !keep.some((k) => k.sha === l.source.sha256)) { size += h.bytes.length; keep.push({ sha: l.source.sha256.toLowerCase(), name: h.name, bytes: h.bytes }); }
    }
    idb((s) => s.put({ obj, luts: size <= IDB.maxBytes ? keep : [], at: Date.now() }, IDB.key)).catch(() => { /* private mode / quota: not remembered */ });
  } catch { /* not remembered */ }
}
function saveSoon() { clearTimeout(saveTimer); saveTimer = setTimeout(saveLast, 1500); }
async function offerLast() {
  let rec = null;
  try { rec = await idb((s) => s.get(IDB.key)); } catch { return; }
  if (!rec || !rec.obj) return;
  const b = $("continue_last"), n = (rec.obj.looks || []).length;
  b.hidden = false; b.title = `${rec.obj.pack && rec.obj.pack.name ? rec.obj.pack.name + ": " : ""}${n} look(s), saved ${new Date(rec.at).toLocaleString()}`;
  b.onclick = async () => {
    for (const x of rec.luts || []) luts.set(x.sha, { name: x.name, bytes: x.bytes });
    if (await applyObject(rec.obj, "the last pack") && n && !(rec.luts || []).length) showOut("The LUT files were not remembered (too large for this browser's storage): import them again before you build.");
  };
}
async function shareLink() {
  const obj = exportable(); if (!obj) return;
  const frag = await P.shareEncode(obj), url = location.origin + location.pathname + "#" + frag;
  history.replaceState(null, "", "#" + frag);
  let msg = `Share link (${url.length} characters). The pack is in the URL fragment: this page never sends it anywhere; whoever receives the link gets the names, order and fitted numbers.`;
  if (url.length > 2000) msg += " Long link: some chat apps cut long links, prefer the .pack.json file.";
  msg += (await copyText(url)) ? " Copied to the clipboard." : " (clipboard not available: select and copy it)";
  showOut(msg + "\n\n" + url);
}
// clipboard write that cannot hang the page when the browser withholds the permission (no answer within 1.5 s = not copied)
function copyText(t) {
  if (!navigator.clipboard) return Promise.resolve(false);
  return Promise.race([navigator.clipboard.writeText(t).then(() => true, () => false), new Promise((r) => setTimeout(() => r(false), 1500))]);
}
async function copyCommand() {
  const b = $("copy_cmd"), t = $("cmd").textContent;
  const ok = await copyText(t);
  if (!ok) {
    const rg = document.createRange(); rg.selectNodeContents($("cmd")); const s = getSelection(); s.removeAllRanges(); s.addRange(rg);
  }
  b.textContent = ok ? "Copied" : "Selected";
  setTimeout(() => { b.textContent = "Copy"; }, 1600);
}

// ---- LUT in hand: licence, load, rank ------------------------------------------------------------------------------------------------
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
  $("licnote").textContent = (licenceProblem() || t || "");
  updateAdd();
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
  cancelFit(); ed.gen++;
  ed.lut = info.lut33; ed.lutInfo = info; ed.fileName = fileName; ed.licence = licence; ed.fileSha = await sha256Hex(bytes); luts.set(ed.fileSha, { name: fileName, bytes });
  ed.fits = {}; ed.hdr = null; ed.stage1 = null; ed.nameDirty = false; ed.mode = null;
  $("space").value = info.space;
  $("import_msg").textContent = ""; $("ed_msg").textContent = "";
  $("loaded").hidden = false; $("lut_name").textContent = fileName;
  $("lut_info").textContent = `${info.kind}, native ${info.native.n}^3${info.exactNodes ? "" : " (resampled to 33^3)"}` + (info.notes.length ? "; " + info.notes.join("; ") : "");
  $("lic_row").hidden = licence !== "@page"; licenceNote();
  document.querySelectorAll("[data-sample]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.sample === fileName && licence !== "@page")));
  log(`loaded ${fileName}: ${info.kind} ${info.native.n}^3`);
  await rankNow();
}
async function loadSample(name) {
  const buf = new Uint8Array(await (await fetch("samples/" + name)).arrayBuffer());
  await loadLut(new TextDecoder().decode(buf), name, buf, "CC0-1.0");
}
async function loadLutFile(f) {
  try {
    const buf = new Uint8Array(await f.arrayBuffer());
    await loadLut(new TextDecoder().decode(buf), f.name, buf, "@page");
  } catch (err) {
    $("import_msg").textContent = `Cannot use ${f.name}: ${err.message}`;
    log("ERROR " + err.message);
  }
}

async function rankNow() {
  if (!ed.lut) return;
  cancelFit(); ed.gen++;
  const ds = getDataset(), res = ds.ranker.stage1(ed.lut, $("space").value);
  ed.stage1 = res; ed.lt = res.lt; ed.fits = {}; ed.hdr = null;
  ed.modes = F.modeChoices(L, res.ranking);
  if (!ed.modes.some((m) => m.mode === ed.mode)) {
    const pm = ed.pendingSlot != null ? L.slots[ed.pendingSlot].mode : null;
    ed.mode = ed.modes.some((m) => m.mode === pm) ? pm : ed.modes[0].mode;
  }
  if (ed.pendingSlot != null && L.slots[ed.pendingSlot].mode === ed.mode) ed.slot = ed.pendingSlot;
  selectBest();
  $("rankinfo").textContent = `Stage 1 on ${ds.label}: ${ms(res.ms)} (target + ${ed.model.candidates.length} candidates). DCP-base-only dE ${res.dcpBaseDE.toFixed(2)}. Scores are model predictions.`;
  renderPlace(); renderTable();
  await drawPreview();
  scheduleFit();
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
    if (ok) {
      const pick = async () => { ed.selected = e.candidate; renderTable(); await drawPreview(); scheduleFit(); };
      tr.tabIndex = 0; tr.onclick = pick;
      tr.onkeydown = (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(); } };
      tr.setAttribute("aria-selected", String(e.candidate === ed.selected));
    } else tr.title = `a slot of base mode ${ed.mode} only takes ${ed.mode} candidates`;
    tb.append(tr);
  });
}

// ---- step 2: base mode, slot, name, menu position -----------------------------------------------------------------------------------
function opt(group, value, checked, build, onchange) {
  const lab = el("label", "opt"), inp = el("input"), box = el("span", "box");
  inp.type = "radio"; inp.name = group; inp.value = value; inp.checked = checked;
  inp.onchange = onchange; build(box);
  lab.append(inp, box);
  return lab;
}
function renderPlace() {
  const has = !!ed.stage1;
  $("place").hidden = !has;
  $("place_idle").hidden = has;
  if (!has) { updateAdd(); return; }
  const modes = $("modes"); modes.textContent = "";
  ed.modes.forEach((m, i) => modes.append(opt("mode", m.mode, m.mode === ed.mode, (box) => {
    const t = el("span", "t"); t.append(el("i", "dot " + m.mode), document.createTextNode(m.mode));
    const s = el("span", "s");
    if (i === 0) s.append(el("span", "best", "best match"), document.createTextNode(" \u00b7 "));
    s.append(document.createTextNode(`dE ${m.dE.toFixed(2)}`));
    box.append(t, s);
  }, () => {
    ed.mode = m.mode; ed.slot = null; ed.nameDirty = false;
    selectBest(); renderPlace(); renderTable(); drawPreview(); scheduleFit();
  })));
  ed.slot = F.defaultSlot(L, st, ed.mode, ed.slot);
  const choices = F.slotChoices(L, st, ed.mode), slots = $("slots"); slots.textContent = "";
  $("slot_hint").textContent = `(${choices.length} ${ed.mode} slot${choices.length === 1 ? "" : "s"})`;
  choices.forEach((c) => slots.append(opt("slot", String(c.slot), c.slot === ed.slot, (box) => {
    const t = el("span", "t"), n = el("span", "num", "#" + c.slot);
    t.append(n, document.createTextNode(c.stock));
    box.append(t, el("span", "s", c.hasLook ? `holds ${c.name} (replaced)` : c.name !== c.stock ? `named ${c.name}` : "stock look"));
  }, () => { ed.slot = c.slot; ed.pendingSlot = null; ed.nameDirty = false; fillName(); renderAnchors(); updateAdd(); })));
  fillName(); renderAnchors(); renderCopy();
  updateAdd();
}
function fillName() {
  if (!ed.slot) return;
  if (!ed.nameDirty) $("ed_name").value = ed.lutInfo ? F.suggestName(L, ed.slot, ed.fileName) : st.names[ed.slot];
  nameCount();
}
function nameCount() {
  if (!ed.slot) return;
  const v = $("ed_name").value, bad = P.nameProblem(L, ed.slot, v), c = $("ed_count");
  c.textContent = `${v.length}/${P.slotCap(L, ed.slot)}`; c.title = bad;
  c.classList.toggle("over", !!bad); $("ed_name").classList.toggle("over", !!bad);
  $("ed_name").setAttribute("aria-invalid", String(!!bad));
  $("ed_name").title = bad;
  updateAdd();
}
function renderAnchors() {
  const sel = $("anchor");
  if (!ed.slot || $("place").hidden) return;
  const keep = sel.value, ch = F.anchorChoices(st, ed.slot), cur = F.anchorValue(st.arrangement, ed.slot);
  const curItem = cur === "top" ? null : F.anchorItem(st, cur);
  sel.textContent = "";
  const k = el("option", "", "Keep position" + (curItem === null ? " (top)" : ` (after ${F.itemName(st, curItem)})`)); k.value = "keep"; sel.append(k);
  for (const c of ch) { const o = el("option", "", c.label); o.value = c.value; sel.append(o); }
  sel.value = [...sel.options].some((o) => o.value === keep) ? keep : "keep";
}
function renderCopy() {
  const cs = $("copysel"); cs.textContent = "";
  const others = ed.slot ? Object.keys(st.looks).map(Number).filter((s) => s !== ed.slot && P.slotMode(L, s) === ed.mode) : [];
  others.forEach((s) => { const o = el("option", "", `slot ${s}: ${st.names[s]}`); o.value = s; cs.append(o); });
  $("copyrow").hidden = !others.length;
}
function copyLook() {
  const from = Number($("copysel").value);
  if (!ed.slot || !st.looks[from]) return;
  const l = JSON.parse(JSON.stringify(st.looks[from])), to = ed.slot;
  l.slot = to; st.looks[to] = l;
  st.names[to] = st.names[from].slice(0, P.slotCap(L, to));
  ed.slot = null; ed.nameDirty = false;
  render(keyOf(to)); renderPlace();
  $("ed_msg").textContent = `Copied the look of slot ${from} into slot ${to}` + (st.names[from].length > P.slotCap(L, to) ? " (name shortened to the capacity of this slot)." : ".");
}

// ---- preview (6 reference scenes or the user's photo) + before/after divider --------------------------------------------------------
function scenesSet() {
  if (ed.preview) return ed.preview;
  const tw = 192, th = 144, w = tw * 3, h = th * 2, base = new Float32Array(w * h * 3);
  SCENE_DEFS.forEach((d, i) => {
    const tile = renderScene(d, tw, th), ox = (i % 3) * tw, oy = Math.floor(i / 3) * th;
    for (let y = 0; y < th; y++) base.set(tile.subarray(y * tw * 3, (y + 1) * tw * 3), ((oy + y) * w + ox) * 3);
  });
  return (ed.preview = { w, h, base, x: baseToX(ed.model, base, new Float32Array(base.length)) });
}
const previewSet = () => (ed.useOwn && ed.photo ? ed.photo : scenesSet());
function paintRGB(canvas, rgb, w, h) {
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext("2d"), im = ctx.createImageData(w, h);
  for (let i = 0; i < w * h; i++) { for (let k = 0; k < 3; k++) im.data[i * 4 + k] = rgb[i * 3 + k] * 255 + 0.5; im.data[i * 4 + 3] = 255; }
  ctx.putImageData(im, 0, 0);
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
let drawSeq = 0;
async function drawPreview() {
  const seq = ++drawSeq, set = previewSet(), stage = $("stage");
  stage.style.setProperty("--ar", String(set.w / set.h));
  const ready = ed.lut && ed.stage1 && ed.selected;
  stage.classList.toggle("empty", !ready);
  stage.setAttribute("aria-disabled", String(!ready));
  if (!ready) {
    ed.shown = { w: set.w, h: set.h, orig: set.base, tgt: null, sim: null };
    paintRGB($("cv_left"), set.base, set.w, set.h); paintRGB($("cv_right"), set.base, set.w, set.h);
    $("readout").textContent = ""; return;
  }
  await new Promise((r) => setTimeout(r, 0));       // let the click / toggle paint first
  if (seq !== drawSeq) return;
  const n = set.w * set.h, t0 = performance.now();
  const tgt = applyLut(ed.lut, set.base, new Float32Array(set.base.length), $("space").value);
  const cand = currentCandidate(), sim = simulate(cand, set.x, new Float32Array(set.base.length));
  const lt = rgb2lab(tgt), lo = rgb2lab(sim), dl = new Float32Array(n);
  for (let i = 0; i < n; i++) dl[i] = lt[i * 3] - lo[i * 3];
  const sh = Float32Array.from(dl).sort()[n >> 1];
  let sum = 0;
  for (let i = 0; i < n; i++) { const k = i * 3; sum += de2000(lt[k], lt[k + 1], lt[k + 2], lo[k] + sh, lo[k + 1], lo[k + 2]); }
  ed.shown = { w: set.w, h: set.h, orig: set.base, tgt, sim };
  paintLeft(); paintRGB($("cv_right"), sim, set.w, set.h);
  $("tag_r").textContent = ed.fits[cand.name] ? "Camera model" : "Camera model (not fitted yet)";
  const f = exportedFit(cand.name), g = f && f.guards;
  $("readout").textContent = `${ed.useOwn && ed.photo ? "Your photo " + ed.photoName : "Reference scenes"}. Camera model ${cand.name} (${cand.mode})${f ? ", fitted matrix + tone curves" : ", stock tone and matrix until the fit is done"}. Mean dE to the LUT ${(sum / n).toFixed(2)} (exposure matched, ${ms(performance.now() - t0)}).`
    + (f ? ` Fit on the reference set: dE ${f.dE.toFixed(3)}, ${f.pct_lt5.toFixed(1)} % of pixels < 5; tone strength x${f.strength}${g && g.hdr_clip_pct != null ? ", +0.5 EV clip " + g.hdr_clip_pct + " %" : ""}. Model predictions, not camera results.` : "");
  if (!ed.swept) { ed.swept = true; sweepIn(); }
}
function paintLeft() {
  const s = ed.shown;
  if (!s) return;
  const lut = ed.left === "lut" && s.tgt;
  paintRGB($("cv_left"), lut ? s.tgt : s.orig, s.w, s.h);
  $("tag_l").textContent = lut ? "LUT target" : "Original";
}
function sweepIn() {
  if (reduceMotion()) return;
  const stage = $("stage");
  stage.classList.add("sweep"); setDivider(1);
  stage.getBoundingClientRect();
  setDivider(0.5);
  setTimeout(() => stage.classList.remove("sweep"), 650);
}
function setDivider(v) {
  ed.divider = Math.max(0, Math.min(1, v));
  const stage = $("stage");
  stage.style.setProperty("--d", String(ed.divider));
  stage.setAttribute("aria-valuenow", String(Math.round(ed.divider * 100)));
  stage.setAttribute("aria-valuetext", `${Math.round(ed.divider * 100)} percent ${ed.left === "lut" ? "LUT target" : "original"} on the left`);
}
{
  const stage = $("stage"); let on = false;
  const at = (e) => { const b = stage.getBoundingClientRect(); setDivider((e.clientX - b.left) / b.width); };
  stage.addEventListener("pointerdown", (e) => { if (stage.classList.contains("empty") || e.button !== 0) return; on = true; stage.setPointerCapture(e.pointerId); at(e); });
  stage.addEventListener("pointermove", (e) => { if (on) at(e); });
  stage.addEventListener("pointerup", () => { on = false; });
  stage.addEventListener("pointercancel", () => { on = false; });
  stage.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 0.1 : 0.03;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") setDivider(ed.divider - step);
    else if (e.key === "ArrowRight" || e.key === "ArrowUp") setDivider(ed.divider + step);
    else if (e.key === "Home") setDivider(0); else if (e.key === "End") setDivider(1);
    else if (e.key === "PageUp") setDivider(ed.divider + 0.1); else if (e.key === "PageDown") setDivider(ed.divider - 0.1);
    else return;
    e.preventDefault();
  });
}
function setPressed(group, attr, value) {
  document.querySelectorAll(`[${attr}]`).forEach((b) => { if (b.closest(group)) b.setAttribute("aria-pressed", String(b.getAttribute(attr) === value)); });
}
// a photo for the preview: decoded in this tab, scaled to at most 640 px on the long edge (display sRGB, like the reference scenes)
async function loadPhoto(f) {
  try {
    const bmp = await createImageBitmap(f, { imageOrientation: "from-image" }), k = Math.min(1, 640 / Math.max(bmp.width, bmp.height));
    const w = Math.max(2, Math.round(bmp.width * k)), h = Math.max(2, Math.round(bmp.height * k));
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const ctx = c.getContext("2d", { willReadFrequently: true }); ctx.drawImage(bmp, 0, 0, w, h); bmp.close && bmp.close();
    const px = ctx.getImageData(0, 0, w, h).data, base = new Float32Array(w * h * 3);
    for (let i = 0; i < w * h; i++) for (let j = 0; j < 3; j++) base[i * 3 + j] = px[i * 4 + j] / 255;
    ed.photo = { w, h, base, x: baseToX(ed.model, base, new Float32Array(base.length)) }; ed.photoName = f.name; ed.useOwn = true;
    $("import_msg").textContent = "";
    const b = document.querySelector('[data-photo="own"]'); b.disabled = false;
    setPressed(".photo-row", "data-photo", "own");
    log(`photo ${f.name}: ${w}x${h}`);
    await drawPreview();
  } catch (e) { $("import_msg").textContent = `Cannot read ${f.name} as a picture: ${e.message}`; }
}

// ---- step 3: fit (automatic, in the worker pool) and add ----------------------------------------------------------------------------
function cancelFit() { if (ed.fitting && ed.pool) ed.pool.cancel(); }
function scheduleFit() {
  if (!ed.stage1 || !ed.selected) { updateAdd(); return; }
  if (ed.fits[ed.selected]) { fitDoneInfo(); updateAdd(); return; }
  if (ed.fitting) { ed.fitWanted = true; cancelFit(); return; }
  doFit();
}
function fitDoneInfo() {
  const f = exportedFit(ed.selected);
  $("fitbar").value = 1;
  $("fitinfo").textContent = f ? `Fitted ${ed.selected}: dE ${f.dE.toFixed(2)}, ${f.pct_lt5.toFixed(0)} % of pixels under 5 (model prediction).` : "";
}
// full fit in the worker pool (one job; the candidate is the best one of the base mode unless another one of that mode is selected)
async function doFit() {
  if (!ed.stage1 || !ed.selected || ed.fitting) return;
  const ds = getDataset(), space = $("space").value, name = ed.selected, gen = ed.gen;
  if (!ed.hdr) ed.hdr = makeHdrProbe(ds.x, ds.base, (b) => applyLut(ed.lut, b, new Float32Array(b.length), space));
  if (!ed.pool) ed.pool = new FitPool(ed.modelJson);
  const job = { candidate: name, xS: ds.x, lt: ed.lt, scenes: ds.scenes.map((s) => ({ start: s.start, count: s.count })), hdr: ed.hdr, opts: {} };
  const bar = $("fitbar"), info = $("fitinfo");
  bar.value = 0; info.textContent = `Fitting ${name}...`; $("fit_sr").textContent = `Fitting ${name}.`;
  ed.fitting = true; updateAdd();
  const t0 = performance.now(); let pend = null, queued = false, cancelled = false;
  try {
    const out = await ed.pool.run([job], (i, p) => {
      pend = p; if (queued) return; queued = true;
      requestAnimationFrame(() => { queued = false; if (gen !== ed.gen || !ed.fitting) return; bar.value = pend.frac; info.textContent = `Fitting ${name}: ${pend.stage} ${Math.round(pend.frac * 100)} %${pend.dE != null ? ", dE " + pend.dE.toFixed(2) : ""}`; });
    });
    const o = out[0];
    if (gen !== ed.gen) cancelled = true;
    else if (o.error) { info.textContent = "Fit error: " + o.error; log(`fit ${name} ERROR ${o.error}`); }
    else {
      const r = o.result; ed.fits[r.candidate] = r;
      log(`fit ${r.candidate}: dE ${r.startDE.toFixed(3)} -> ${r.dEunguarded.toFixed(3)} unguarded / ${r.dE.toFixed(3)} guarded (strength ${r.toneStrength}), ${r.ms} ms, ${((performance.now() - t0) / 1000).toFixed(1)} s`);
    }
  } catch (e) {
    cancelled = true;
    if (!(e instanceof FitCancelled)) { info.textContent = "Fit failed: " + e.message; cancelled = false; }
  } finally { ed.fitting = false; }
  if (ed.fitWanted) { ed.fitWanted = false; scheduleFit(); return; }
  if (cancelled) { updateAdd(); return; }
  renderTable(); fitDoneInfo(); updateAdd();
  $("fit_sr").textContent = "Fit done. Add to pack is ready.";
  await drawPreview();
}

// the Add button: armed once a fit exists for the chosen candidate, a slot is chosen and the name passes the slot's rules
function updateAdd() {
  const b = $("accept");
  let why = "";
  if (!ed.lut) why = "Import a LUT first.";
  else if (!ed.slot) why = "Choose a slot.";
  else if (ed.fitting || !ed.selected || !ed.fits[ed.selected]) why = "Waiting for the fit to finish.";
  else if (P.nameProblem(L, ed.slot, $("ed_name").value)) why = "Name: " + P.nameProblem(L, ed.slot, $("ed_name").value);
  else if (licenceProblem()) why = licenceProblem();
  b.disabled = !!why;
  b.title = why;
  if (!why && !$("ed_msg").textContent) {
    $("ed_msg").className = "ok-t"; $("ed_msg").textContent = "Fit done. Press Add to pack to put this look into your pack: nothing is built until it is added.";
    b.scrollIntoView({ block: "center", behavior: reduceMotion() ? "auto" : "smooth" });     // the button sits below the fold on a normal screen
  }
  refreshBuildState();
  if (!ed.lut) { $("fitinfo").textContent = "Waiting for a LUT."; $("fitbar").value = 0; }
}
function acceptLook() {
  const msg = (t) => { $("ed_msg").textContent = t; $("ed_msg").className = "err-t"; return null; };
  if (!ed.slot) return;
  const slot = ed.slot, name = $("ed_name").value, np = P.nameProblem(L, slot, name);
  if (np) return msg("Name: " + np);
  if (!ed.stage1 || !ed.selected) return msg("Load a LUT first.");
  const fit = exportedFit(ed.selected);
  if (!fit) return msg("The fit is not done yet.");
  if (fit.mode !== ed.mode) return msg(`Candidate mode ${fit.mode} does not match the slot's base mode ${ed.mode}.`);
  const lp = licenceProblem();
  if (lp) { $("licnote").textContent = lp; return msg(lp); }
  const chosen = ed.model.candidates.find((c) => c.name === ed.selected), fits = {};
  for (const n of Object.keys(ed.fits)) fits[n] = fitView(ed.fits[n]);
  const info = ed.lutInfo;
  const lf = buildLookFile({ name, slot, source: { type: info.kind, name: ed.fileName, licence: licenceString(), sha256: ed.fileSha, space: $("space").value, title: info.name, tableMd5: info.tableMd5 },
    stage1: ed.stage1, chosen: { candidate: chosen.name, mode: chosen.mode, orf: chosen.orf }, fit, fits, scenes: getDataset().label, notes: $("ed_notes").value });
  const look = lf.looks[0];
  if ($("ed_icon").value === "keep") look.icon = "keep";
  st.looks[slot] = look; st.names[slot] = name;
  const a = $("anchor").value;
  if (a !== "keep") { const ai = F.anchorItem(st, a); if (ai !== undefined) st.arrangement = F.placeAfter(st.arrangement, slot, ai); }
  const at = F.anchorValue(st.arrangement, slot), pred = at === "top" ? null : F.anchorItem(st, at);
  ed.slot = null; ed.pendingSlot = null; ed.nameDirty = false;
  render(keyOf(slot)); renderPlace();
  const m = $("ed_msg"); m.className = "ok-t";
  m.textContent = `Added to slot ${slot} as ${name}: ${look.fit.mode}, predicted dE ${look.fit.predicted.dE} (model value), ${pred === null ? "at the top of the menu" : "after " + F.itemName(st, pred)}.`;
  const row = document.querySelector(`.row[data-key="${keyOf(slot)}"]`);
  if (row) row.scrollIntoView({ block: "nearest", behavior: reduceMotion() ? "auto" : "smooth" });
}

// ---- files: choose, drop anywhere -------------------------------------------------------------------------------------------------------
async function handleFiles(files) {
  const d = F.sortDrop(files);
  if (!d.pack && !d.lut && !d.photo) { $("import_msg").textContent = "Nothing to load: drop a .cube or .xmp LUT, a .json pack or a photo."; return; }
  $("import_msg").textContent = "";
  if (d.pack) await importFile(d.pack);
  if (d.photo) await loadPhoto(d.photo);
  if (d.lut) await loadLutFile(d.lut);
  if (d.ignored.length) $("import_msg").textContent = "Ignored: " + d.ignored.join(", ") + ".";
}
{
  let depth = 0;
  const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
  const show = (on) => { $("overlay").classList.toggle("show", on); document.body.classList.toggle("dragging", on); };
  window.addEventListener("dragenter", (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth++; show(true); });
  window.addEventListener("dragover", (e) => { if (!hasFiles(e)) return; e.preventDefault(); e.dataTransfer.dropEffect = "copy"; });
  window.addEventListener("dragleave", (e) => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) show(false); });
  window.addEventListener("drop", async (e) => { if (!hasFiles(e)) return; e.preventDefault(); depth = 0; show(false); await handleFiles([...e.dataTransfer.files]); });
}

// ---- theme --------------------------------------------------------------------------------------------------------------------------------
function setTheme(t, save) {
  document.documentElement.dataset.theme = t;
  document.querySelectorAll("[data-theme-set]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.themeSet === t)));
  if (save) { try { localStorage.setItem("om10mi-panel-theme", t); } catch { /* private mode: not saved */ } }
}

// ---- init ----------------------------------------------------------------------------------------------------------------------------------
async function init() {
  let t0 = "auto"; try { t0 = localStorage.getItem("om10mi-panel-theme") || "auto"; } catch { /* no storage */ }
  setTheme(["auto", "dark", "light"].includes(t0) ? t0 : "auto", false);
  document.querySelectorAll("[data-theme-set]").forEach((b) => (b.onclick = () => setTheme(b.dataset.themeSet, true)));
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
    $("sha_row").hidden = rel.value !== "custom"; problems(); refreshExport();
  };
  $("sha1").oninput = () => {
    const v = $("sha1").value.trim().toLowerCase(), k = L.releases.findIndex((r) => r.sha1 === v);
    st.base = k >= 0 ? { name: L.releases[k].name, sha1: v } : { name: "custom", sha1: v };
    rel.value = k >= 0 ? String(k) : "custom"; $("sha_row").hidden = rel.value !== "custom"; problems(); refreshExport();
  };
  $("pname").oninput = () => { st.name = $("pname").value; problems(); refreshExport(); };
  $("export_zip").onclick = exportZip;
  $("build").onclick = () => buildFirmware().catch((e) => buildFailed(e.message));
  $("build_cancel").onclick = () => { buildDone(); setBuildLog("Cancelled, nothing was built.", true); };
  $("build_dl").onclick = () => { if (bwResult) saveBlob(bwResult.name, bwResult.zip, "application/zip"); };
  $("export").onclick = () => { const o = exportable(); if (o) { const t = JSON.stringify(o, null, 1); download(P.packFileName(st), t); showOut(`Exported ${P.packFileName(st)} (${t.length} bytes). This plain JSON has no LUT files: the command line needs --lut-dir with the same LUT files (or use the zip export).`); } };
  $("open_pack").onclick = () => $("import").click();
  $("import").onchange = async (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) await importFile(f); };
  $("share").onclick = shareLink;
  $("copy_cmd").onclick = copyCommand;
  {
    const b = $("reset"); let timer = null;
    b.onclick = () => {
      if (!timer) { b.textContent = "Click again to reset"; b.classList.add("armed"); timer = setTimeout(() => { timer = null; b.textContent = "Reset pack"; b.classList.remove("armed"); }, 4000); return; }
      clearTimeout(timer); timer = null; b.textContent = "Reset pack"; b.classList.remove("armed");
      st = P.emptyState(L); ed.slot = null; ed.pendingSlot = null; ed.nameDirty = false; syncMeta(); render(); renderPlace(); $("out").hidden = true; $("ed_msg").textContent = "";
    };
  }
  // import
  $("choose").onclick = () => $("file").click();
  $("file").onchange = async (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) await loadLutFile(f); };
  document.querySelectorAll("button[data-sample]").forEach((b) => (b.onclick = () => loadSample(b.dataset.sample).catch((e) => { $("import_msg").textContent = "Cannot load the sample: " + e.message; })));
  $("choose_photo").onclick = () => $("photo").click();
  $("photo").onchange = async (e) => { const f = e.target.files[0]; e.target.value = ""; if (f) await loadPhoto(f); };
  document.querySelectorAll("[data-photo]").forEach((b) => (b.onclick = async () => {
    ed.useOwn = b.dataset.photo === "own"; setPressed(".photo-row", "data-photo", b.dataset.photo); await drawPreview();
  }));
  document.querySelectorAll("[data-left]").forEach((b) => (b.onclick = () => { ed.left = b.dataset.left; setPressed(".s-stage .card-head", "data-left", ed.left); paintLeft(); setDivider(ed.divider); }));
  document.querySelectorAll("[data-rows]").forEach((b) => (b.onclick = () => { ed.rows = b.dataset.rows; setPressed(".s-list", "data-rows", ed.rows); render(); }));
  // step 2 / 3
  $("space").onchange = rankNow;
  $("guard").onchange = async () => { renderTable(); fitDoneInfo(); await drawPreview(); };
  $("lic").onchange = licenceNote; $("lic_by").oninput = licenceNote;
  $("ed_name").oninput = () => { ed.nameDirty = true; nameCount(); };
  $("accept").onclick = acceptLook;
  $("copy").onclick = copyLook;
  syncMeta(); render(); renderPlace(); setDivider(0.5);
  await drawPreview();
  offerLast();
  window.panel = { get st() { return st; }, ed, L, P, F, render, loadSample, doFit, applyObject, acceptLook, rankNow, handleFiles };
  if (location.hash.startsWith("#" + "pack=")) {
    try { await applyObject(await P.shareDecode(location.hash), "share link"); } catch (e) { showOut("Share link not loaded: " + e.message); }
  }
  $("status").textContent = "ready";
  window.__ready = true;
}
init().catch((e) => { $("status").textContent = "init failed: " + e.message; console.error(e); });
