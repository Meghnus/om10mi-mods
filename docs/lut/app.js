// app.js - UI glue for the local LUT -> camera-look prototype. No network except same-origin static files (model json, samples).
import { importLutText, applyLut, formatCube } from "./lutcore.js";
import { loadModel, simulate, baseToX, makeCandidate } from "./model.js";
import { Ranker, makeDataset } from "./rank.js";
import { SCENE_DEFS, renderScene, synthDataset, imageToBase, subsample } from "./refset.js";
import { rgb2lab, de2000 } from "./color.js";
import { buildLookFile, sha256Hex, toneBlock } from "./lookfile.js";
import { fitCandidate, makeHdrProbe, candidateFromCurves } from "./fit.js";
import { FitPool, FitCancelled } from "./pool.js";

const $ = (id) => document.getElementById(id);
const state = { model: null, lut: null, lutInfo: null, fileSha: null, fileName: "", licence: "", ranker: null, datasets: {}, refSource: "synthetic", jpeg: null,
  stage1: null, selected: null, refit: null, fits: {}, hdr: null, pool: null, fitting: false, lt: null, timings: {}, previewSets: null };

function log(msg) { const el = $("log"); el.textContent += msg + "\n"; el.scrollTop = el.scrollHeight; console.log(msg); }
const ms = (v) => (v < 10 ? v.toFixed(1) : v.toFixed(0)) + " ms";
const tick = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));

// ---- reference datasets ------------------------------------------------------------------------------------------------
function getDataset(kind) {
  if (state.datasets[kind]) return state.datasets[kind];
  let ds;
  if (kind === "synthetic") {
    const s = synthDataset(64, 48);
    ds = makeDataset(state.model, s.base, s.scenes, baseToX);
    ds.label = "ref-syn-1 (synthetic, 6 scenes x 64x48)";
  } else {
    const sub = subsample(state.jpeg.base, state.jpeg.w, state.jpeg.h, 4096);
    ds = makeDataset(state.model, sub.base, [{ name: "photo", start: 0, count: sub.w * sub.h }], baseToX);
    ds.label = `user JPEG (${sub.w}x${sub.h} samples, display base assumed sRGB)`;
  }
  const t0 = performance.now();
  ds.ranker = new Ranker(state.model, ds);
  ds.setupMs = performance.now() - t0;
  state.datasets[kind] = ds;
  log(`dataset ${ds.label}: candidate render (21 candidates) ${ms(ds.ranker.renderMs)}`);
  return ds;
}

// ---- loading a LUT -------------------------------------------------------------------------------------------------------
// licence string of the look file's `source` (<= 100 characters, the checker's limit): built-in samples are CC0; a file of your own gets what you
// declare in section 1 (a CC BY / CC BY-SA table needs its attribution, which is written into the string).
export function licenceString() {
  if (state.licence !== "@page") return state.licence;
  const kind = $("lic").value, who = $("lic_by").value.replace(/[^\x20-\x7e]/g, "").trim();
  return (kind + (who ? " - " + who : "")).slice(0, 100);
}
export function licenceProblem() {
  if (state.licence !== "@page") return "";
  const kind = $("lic").value, who = $("lic_by").value.trim();
  if (/^CC BY/.test(kind) && !who) return "The licence " + kind + " requires attribution: fill in the author / source box in section 1.";
  return "";
}
function licenceNote() {
  const kind = $("lic").value, el = $("licnote");
  const t = { "unknown": "Licence unknown: keep the look file private; do not publish a look made from a table whose licence you cannot confirm.",
    "CC0-1.0": "", "own work": "", "CC BY 4.0": "Attribution required (author / source box). The look numbers are a derivative of the table: credit it wherever you share them.",
    "CC BY-SA 4.0": "Attribution required, and the look file / numbers fitted from this table are ShareAlike: share them under CC BY-SA 4.0 with the credit.",
    "CC BY-NC-SA 4.0": "NonCommercial + ShareAlike: the look file and the numbers fitted from it inherit these terms; no commercial use, share alike, credit the author.",
    "all rights reserved": "Not for redistribution: keep the look file and the built image for your own camera only." }[kind];
  el.textContent = t || "";
}
async function loadLut(text, fileName, bytes, licence = "") {
  const t0 = performance.now();
  const info = await importLutText(text, fileName);
  state.timings.parseMs = performance.now() - t0;
  state.lut = info.lut33; state.lutInfo = info; state.fileName = fileName; state.licence = licence;
  state.fileSha = await sha256Hex(bytes);
  $("lutinfo").textContent = `${info.name} - ${info.kind}, native ${info.native.n}^3${info.exactNodes ? "" : " -> resampled to 33^3"}, parse ${ms(state.timings.parseMs)}` + (info.notes.length ? "; " + info.notes.join("; ") : "");
  $("space").value = info.space;
  $("lutname").value = fileName.replace(/\.[^.]*$/, "").replace(/[^\x20-\x7e]/g, "").slice(0, 12);
  log(`loaded ${fileName}: ${info.kind} ${info.native.n}^3, parse ${ms(state.timings.parseMs)}, default space ${info.space}`);
  await rankNow();
}

async function loadSample(name) {
  const r = await fetch("samples/" + name);
  const buf = new Uint8Array(await r.arrayBuffer());
  await loadLut(new TextDecoder().decode(buf), name, buf, "CC0-1.0");
}

// ---- stage 1 ---------------------------------------------------------------------------------------------------------------
async function rankNow() {
  if (!state.lut) return;
  const kind = state.refSource === "jpeg" && state.jpeg ? "jpeg" : "synthetic";
  const ds = getDataset(kind);
  const space = $("space").value;
  const runs = [];
  let res;
  for (let i = 0; i < 3; i++) { res = ds.ranker.stage1(state.lut, space); runs.push(res.ms); }
  runs.sort((a, b) => a - b);
  state.stage1 = res; state.lt = res.lt; state.refit = null; state.fits = {}; state.hdr = null; state.timings.rankMs = runs[1]; state.timings.rankKind = kind;
  state.selected = res.ranking[0].candidate;
  $("rankinfo").textContent = `Stage 1 on ${ds.label}: ${ms(runs[1])} per LUT (median of 3; target + 21 candidates; the one-time candidate render took ${ms(ds.ranker.renderMs)}). DCP-base-only dE ${res.dcpBaseDE.toFixed(2)}.`;
  renderTable();
  await drawPreview();
}

function renderTable() {
  const tb = $("rank").querySelector("tbody");
  tb.innerHTML = "";
  state.stage1.ranking.forEach((e, i) => {
    const tr = document.createElement("tr");
    if (e.candidate === state.selected) tr.className = "sel";
    const fit = state.refit && state.refit.candidate === e.candidate ? state.refit.dE.toFixed(3) : "";
    const ff = state.fits[e.candidate] ? fitView(state.fits[e.candidate]).dE.toFixed(3) : "";
    tr.innerHTML = `<td>${i + 1}</td><td>${e.candidate}</td><td>${e.mode}</td><td>${e.dE.toFixed(3)}</td><td>${e.pct_lt5.toFixed(1)}</td><td>${fit}</td><td>${ff}</td>`;
    tr.onclick = async () => { state.selected = e.candidate; if (state.refit && state.refit.candidate !== e.candidate) state.refit = null; renderTable(); await drawPreview(); };
    tb.appendChild(tr);
  });
}

// ---- preview ------------------------------------------------------------------------------------------------------------------
const HEAT = (t) => { t = Math.min(1, Math.max(0, t)); const r = Math.min(1, t * 2), g = t < 0.5 ? t * 1.2 : 1 - (t - 0.5) * 1.6, b = Math.max(0, 0.6 - t * 1.2); return [r * 255, Math.max(0, g) * 255, b * 255]; };

function previewSet() {
  if (state.previewSets && state.previewSets.key === state.refSource + (state.jpeg ? state.jpeg.name : "")) return state.previewSets;
  let w, h, base;
  if (state.refSource === "jpeg" && state.jpeg) {
    const j = state.jpeg, step = Math.max(1, Math.ceil(Math.max(j.w, j.h) / 480));
    w = Math.floor(j.w / step); h = Math.floor(j.h / step); base = new Float32Array(w * h * 3);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const k = ((y * step + (step >> 1)) * j.w + x * step + (step >> 1)) * 3, o = (y * w + x) * 3; base[o] = j.base[k]; base[o + 1] = j.base[k + 1]; base[o + 2] = j.base[k + 2]; }
  } else {
    const tw = 192, th = 144; w = tw * 3; h = th * 2; base = new Float32Array(w * h * 3);
    SCENE_DEFS.forEach((d, i) => {
      const tile = renderScene(d, tw, th), ox = (i % 3) * tw, oy = Math.floor(i / 3) * th;
      for (let y = 0; y < th; y++) base.set(tile.subarray(y * tw * 3, (y + 1) * tw * 3), ((oy + y) * w + ox) * 3);
    });
  }
  const x = baseToX(state.model, base, new Float32Array(base.length));
  state.previewSets = { key: state.refSource + (state.jpeg ? state.jpeg.name : ""), w, h, base, x };
  return state.previewSets;
}

function paint(canvas, rgb, w, h) {
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext("2d"), im = ctx.createImageData(w, h);
  for (let i = 0; i < w * h; i++) { im.data[i * 4] = rgb[i * 3] * 255 + 0.5; im.data[i * 4 + 1] = rgb[i * 3 + 1] * 255 + 0.5; im.data[i * 4 + 2] = rgb[i * 3 + 2] * 255 + 0.5; im.data[i * 4 + 3] = 255; }
  ctx.putImageData(im, 0, 0);
}

function currentCandidate() {
  const c = state.model.candidates.find((c) => c.name === state.selected);
  const f = state.fits[c.name];
  if (f) { const v = fitView(f); return Object.assign(fitCandidate(state.model, v.mode, v.orf, Float64Array.from(v.theta), v.strength, v.luma), { name: c.name }); }
  if (state.refit && state.refit.candidate === c.name) return makeCandidate(state.model, c.src, state.refit.orf);
  return c;
}

async function drawPreview() {
  if (!state.lut || !state.stage1) return;
  const set = previewSet(), n = set.w * set.h;
  const t0 = performance.now();
  const tgt = applyLut(state.lut, set.base, new Float32Array(set.base.length), $("space").value);
  const t1 = performance.now();
  const cand = currentCandidate();
  const sim = simulate(cand, set.x, new Float32Array(set.base.length));
  const t2 = performance.now();
  // dE heat map (exposure-matched on the whole picture)
  const lt = rgb2lab(tgt), lo = rgb2lab(sim);
  const dl = new Float32Array(n); for (let i = 0; i < n; i++) dl[i] = lt[i * 3] - lo[i * 3];
  const sorted = Float32Array.from(dl).sort(), sh = sorted[n >> 1];
  const heat = new Float32Array(n * 3);
  let sum = 0;
  for (let i = 0; i < n; i++) { const k = i * 3, de = de2000(lt[k], lt[k + 1], lt[k + 2], lo[k] + sh, lo[k + 1], lo[k + 2]); sum += de; const c = HEAT(de / 10); heat[k] = c[0] / 255; heat[k + 1] = c[1] / 255; heat[k + 2] = c[2] / 255; }
  const t3 = performance.now();
  paint($("c_target"), tgt, set.w, set.h);
  paint($("c_sim"), sim, set.w, set.h);
  paint($("c_heat"), heat, set.w, set.h);
  const t4 = performance.now();
  state.timings.previewMs = t4 - t0;
  state.timings.preview = { px: n, lut: t1 - t0, camera: t2 - t1, dE: t3 - t2, paint: t4 - t3 };
  $("previewinfo").textContent = `Preview ${set.w}x${set.h} (${n} px): ${ms(t4 - t0)} total = LUT ${ms(t1 - t0)} + camera model ${ms(t2 - t1)} + dE map ${ms(t3 - t2)} + paint ${ms(t4 - t3)}. Mean dE of this picture ${(sum / n).toFixed(2)} (candidate ${cand.name}${state.fits[cand.name] ? ", fitted matrix + tone curves" : state.refit && state.refit.candidate === cand.name ? ", refit matrix" : ""}).`;
  $("c_sim_label").textContent = `Camera model: ${cand.name} (${cand.mode})`;
}

// ---- refit + export ---------------------------------------------------------------------------------------------------------
async function doRefit() {
  if (!state.stage1) return;
  $("refitinfo").textContent = "refitting...";
  await tick();
  const r = state.ranker_for_refit || (getDataset(state.timings.rankKind || "synthetic").ranker);
  const f = r.refit(state.selected, state.lt);
  state.refit = { candidate: state.selected, ...f };
  $("refitinfo").textContent = `Matrix refit of ${state.selected}: dE ${state.stage1.ranking.find((e) => e.candidate === state.selected).dE.toFixed(3)} -> ${f.dE.toFixed(3)} (${f.pct_lt5.toFixed(1)} % < 5), ${f.evals} evaluations, ${ms(f.ms)}. ORF ${f.orf.join(", ")}`;
  state.timings.refitMs = f.ms;
  renderTable();
  await drawPreview();
}

// ---- full fit (matrix + tone curves) in a Web Worker pool --------------------------------------------------------------------
// the guarded / unguarded view of a fit result (guard = highlight-clip guard of fit.js; unchecked = full-strength tone)
function fitView(r) {
  const on = $("guard").checked;
  return { candidate: r.candidate, mode: r.mode, luma: r.luma, orf: r.orf, theta: r.theta, strength: on ? r.toneStrength : 1, dE: on ? r.dE : r.dEunguarded,
    pct_lt5: on ? r.pct_lt5 : r.pct_lt5_unguarded, guards: on ? r.guards : { ...r.guards, tone_strength: 1, hdr_clip_pct: null } };
}

function showFitProgress(rows) {
  const box = $("fitprogress");
  box.innerHTML = "";
  return rows.map((name) => {
    const div = document.createElement("div");
    div.innerHTML = `<span class="fn">${name}</span> <progress max="1" value="0"></progress> <span class="fi">queued</span>`;
    box.appendChild(div);
    return { bar: div.querySelector("progress"), info: div.querySelector(".fi") };
  });
}

async function doFit(names) {
  if (!state.stage1 || !names.length || state.fitting) return;
  const kind = state.timings.rankKind || "synthetic", ds = getDataset(kind), space = $("space").value;
  if (!state.hdr) state.hdr = makeHdrProbe(ds.x, ds.base, (b) => applyLut(state.lut, b, new Float32Array(b.length), space));
  if (!state.pool) state.pool = new FitPool(state.modelJson);
  const jobs = names.map((n) => ({ candidate: n, xS: ds.x, lt: state.lt, scenes: ds.scenes.map((s) => ({ start: s.start, count: s.count })), hdr: state.hdr, opts: {} }));
  const rows = showFitProgress(names);
  state.fitting = true; $("fit").disabled = $("fit3").disabled = true; $("cancel").disabled = false;
  $("fitinfo").textContent = `fitting ${names.length} base(s) on ${state.pool.size} worker(s)...`;
  // main-thread responsiveness probe: worst gap between 50 ms timer ticks while the workers run
  let last = performance.now(), maxLag = 0;
  const lagTimer = setInterval(() => { const t = performance.now(); maxLag = Math.max(maxLag, t - last - 50); last = t; }, 50);
  const t0 = performance.now();
  let pending = null;
  try {
    const out = await state.pool.run(jobs, (i, p) => {
      pending = pending || {};
      pending[i] = p;
      if (state.paintQueued) return;
      state.paintQueued = true;
      requestAnimationFrame(() => {
        state.paintQueued = false;
        for (const [k, q] of Object.entries(pending)) { rows[k].bar.value = q.frac; rows[k].info.textContent = `${q.stage} ${Math.round(q.frac * 100)}%${q.dE != null ? "  dE " + q.dE.toFixed(3) : ""}`; }
      });
    });
    const wall = performance.now() - t0;
    out.forEach((o, i) => {
      if (o.error) { rows[i].info.textContent = "error: " + o.error; log(`fit ${names[i]} ERROR ${o.error}`); return; }
      const r = o.result;
      rows[i].bar.value = 1; rows[i].info.textContent = `done: dE ${r.dE.toFixed(3)}${r.toneStrength < 1 ? " (clip guard: tone x" + r.toneStrength + ", unguarded " + r.dEunguarded.toFixed(3) + ")" : ""}, ${(r.ms / 1000).toFixed(1)} s`;
      state.fits[r.candidate] = r;
      log(`fit ${r.candidate}: dE ${r.startDE.toFixed(3)} -> matrix-only ${r.matrixOnlyDE.toFixed(3)} -> ${r.dEunguarded.toFixed(3)} unguarded / ${r.dE.toFixed(3)} guarded (strength ${r.toneStrength}), ${r.ms} ms, stages ${JSON.stringify(r.stageMs)}`);
    });
    state.timings.fit = { names, wallMs: wall, workers: Math.min(state.pool.size, names.length), maxMainThreadLagMs: Math.round(maxLag), perFitMs: out.map((o) => (o.result ? o.result.ms : null)), dataset: ds.label, px: ds.n };
    $("fitinfo").textContent = `${names.length} fit(s) done in ${(wall / 1000).toFixed(1)} s wall on ${state.timings.fit.workers} worker(s); worst main-thread stall while fitting ${Math.round(maxLag)} ms.`;
  } catch (e) {
    $("fitinfo").textContent = e instanceof FitCancelled ? "fit cancelled (workers terminated)" : "fit failed: " + e.message;
    rows.forEach((r) => { if (r.bar.value < 1) r.info.textContent = e instanceof FitCancelled ? "cancelled" : "failed"; });
    log("fit: " + $("fitinfo").textContent);
  } finally {
    clearInterval(lagTimer);
    state.fitting = false; $("fit").disabled = $("fit3").disabled = false; $("cancel").disabled = true;
  }
  renderTable();
  await drawPreview();
}

function cancelFit() { if (state.pool) state.pool.cancel(); }

// re-score the numbers that will be written to the file (33-knot curves rounded to 5 decimals), so predicted.dE is the file's own value
function exportedFit(name) {
  const f = state.fits[name];
  if (!f) return null;
  const v = fitView(f), tb = toneBlock(v.theta, v.strength, v.luma);
  const cv = { d: ["r", "g", "b"].map((k) => tb.c_curves[k].map((p) => p[1])), h: tb.y_curve.map((p) => p[1]), luma: tb.luma_arg };
  const ds = getDataset(state.timings.rankKind || "synthetic");
  const sim = simulate(candidateFromCurves(state.model, v.mode, v.orf, cv), ds.x, new Float32Array(ds.base.length));
  const sc = ds.ranker.scorer.score(state.lt, rgb2lab(sim));
  return { ...v, dE: sc.dE, pct_lt5: sc.pct_lt5 };
}

async function makeLook() {
  const chosen = state.model.candidates.find((c) => c.name === state.selected);
  const slot = $("slot").value ? parseInt($("slot").value, 10) : null;
  const st = state.lutInfo;
  const fits = {};
  for (const n of Object.keys(state.fits)) fits[n] = fitView(state.fits[n]);
  const lf = buildLookFile({
    name: $("lutname").value, slot,
    source: { type: st.kind, name: state.fileName, licence: licenceString(), sha256: state.fileSha, space: $("space").value, title: st.name, tableMd5: st.tableMd5 },
    stage1: state.stage1, chosen: { candidate: chosen.name, mode: chosen.mode, orf: chosen.orf }, refit: state.refit && state.refit.candidate === chosen.name ? state.refit : null,
    fit: exportedFit(chosen.name), fits,
    scenes: getDataset(state.timings.rankKind || "synthetic").label,
  });
  return lf;
}

async function showExport() {
  const lf = await makeLook();
  const txt = JSON.stringify(lf, null, 1);
  $("lookjson").value = txt;
  state.lookText = txt;
  return lf;
}

function download(name, text, type = "application/json") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name; document.body.appendChild(a); a.click(); a.remove();
}

// ---- wiring ------------------------------------------------------------------------------------------------------------------------
async function onJpeg(file) {
  const bmp = await createImageBitmap(file);
  const cv = document.createElement("canvas");
  const scale = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
  cv.width = Math.round(bmp.width * scale); cv.height = Math.round(bmp.height * scale);
  const ctx = cv.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(bmp, 0, 0, cv.width, cv.height);
  const id = ctx.getImageData(0, 0, cv.width, cv.height);
  state.jpeg = { name: file.name + file.size, w: cv.width, h: cv.height, base: imageToBase(id.data, cv.width, cv.height) };
  delete state.datasets.jpeg; state.previewSets = null;
  log(`picture ${file.name}: ${cv.width}x${cv.height} kept in memory only (no upload)`);
  state.refSource = "jpeg"; $("ref_jpeg").checked = true;
  await rankNow();
}

export async function init() {
  state.model = await loadModel();
  state.modelJson = await (await fetch("model-cm-v2-web1.json")).json();
  log(`model ${state.model.id}: ${state.model.candidates.length} candidates (${state.model.candidates.filter((c) => c.kind === "stock").length} stock modes + looks)`);
  $("file").onchange = async (e) => { const f = e.target.files[0]; if (!f) return; const buf = new Uint8Array(await f.arrayBuffer()); try { await loadLut(new TextDecoder().decode(buf), f.name, buf, "@page"); } catch (err) { $("lutinfo").textContent = "Error: " + err.message; log("ERROR " + err.message); } };
  $("jpeg").onchange = async (e) => { const f = e.target.files[0]; if (f) await onJpeg(f); };
  document.querySelectorAll("button[data-sample]").forEach((b) => (b.onclick = () => loadSample(b.dataset.sample)));
  $("space").onchange = rankNow;
  $("ref_syn").onchange = async () => { state.refSource = "synthetic"; await rankNow(); };
  $("ref_jpeg").onchange = async () => { if (state.jpeg) { state.refSource = "jpeg"; await rankNow(); } };
  $("refit").onclick = doRefit;
  $("fit").onclick = () => doFit([state.selected]);
  $("fit3").onclick = () => doFit(state.stage1 ? state.stage1.ranking.slice(0, 3).map((e) => e.candidate) : []);
  $("cancel").onclick = cancelFit;
  $("guard").onchange = async () => { renderTable(); await drawPreview(); };
  $("lic").onchange = licenceNote; licenceNote();
  $("mk").onclick = showExport;
  $("dl").onclick = async () => { const bad = licenceProblem(); if (bad) { $("licnote").textContent = bad; return; } await showExport(); download(($("lutname").value || "look").replace(/[^\w.-]+/g, "_") + ".look.json", state.lookText); };
  $("dlcube").onclick = () => { if (state.lut) download("lut33.cube", formatCube(state.lut, state.lutInfo.name), "text/plain"); };
  $("bench").onclick = bench;
  window.lutweb = { licenceString, state, loadSample, rankNow, doRefit, doFit, cancelFit, fitView, showExport, bench, onJpeg, drawPreview, getDataset };
  $("status").textContent = "ready";
  window.__ready = true;
}

async function bench() {
  if (!state.lut) return;
  const ds = getDataset(state.timings.rankKind || "synthetic");
  const t = [];
  for (let i = 0; i < 10; i++) t.push(ds.ranker.stage1(state.lut, $("space").value).ms);
  t.sort((a, b) => a - b);
  const p = [];
  for (let i = 0; i < 5; i++) { await drawPreview(); p.push(state.timings.previewMs); }
  p.sort((a, b) => a - b);
  state.timings.bench = { rank: t, preview: p };
  $("benchinfo").textContent = `Stage-1 rank: median ${ms(t[5])} (min ${ms(t[0])}, max ${ms(t[9])}) on ${ds.ranker.ds.n} px; preview: median ${ms(p[2])} (${state.previewSets.w}x${state.previewSets.h}).`;
  log("bench: " + $("benchinfo").textContent);
}

init().catch((e) => { $("status").textContent = "init failed: " + e.message; console.error(e); });
