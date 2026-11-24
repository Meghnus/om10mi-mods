// lookfile.js - builds an om10mi look file, version 2 (spec: fw/lut_stage1/lookfile/LOOKFILE_SPEC_v2.md; validated by lookfile_check.py).
// The file holds intent + our own fitted numbers; it NEVER embeds the user's LUT (source = name + sha256 + space, requires_file).
import { curves33, LUMA_DEFAULT } from "./fit.js";
import { composedMax } from "./composed.js";

export async function sha256Hex(bytes) {
  const d = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(d), (b) => b.toString(16).padStart(2, "0")).join("");
}

const r3 = (v) => Math.round(v * 1000) / 1000;
const validOrf = (m) => Array.isArray(m) && m.length === 9 && m.every((v) => Number.isInteger(v) && v > -1024 && v < 1024)
  && [0, 1, 2].every((i) => Math.abs(m[i * 3] + m[i * 3 + 1] + m[i * 3 + 2] - 256) <= 1);

// fit.tone for cm-v2-web1: what the builder's "tone lift" needs. 33 uniform knots on 0..1, piecewise linear, tone strength already applied.
// luma_arg "post" (S7): y_c = clip(F_m(u_c)+d_c(u_c)+h(Y3),0,1), Y3 = W.(F_m+d)  (the luma lift acts after the per-channel curves, as the camera's T2 after T3);
//          "yb" (web1, absent in older files): y_c = clip(F_m(u_c)+d_c(u_c)-W.d+h(Yb),0,1), Yb = W.F_m
export const TONE_DOMAIN = "cm-v2-web1: c_curves x=u=x^(1/2.4) of the camera-linear x after the matrix, y=d_c additive on the base-mode curve F_m(u_c); "
  + "y_curve x=Y3=W.(F_m+d) (luma_arg post) or Yb=W.F_m (luma_arg yb), y=h additive luma lift; luma_arg post: y_c=clip(F_m(u_c)+d_c(u_c)+h(Y3),0,1); luma_arg yb: y_c=clip(F_m(u_c)+d_c(u_c)-W.d+h(Yb),0,1); "
  + "out=clip(P_m y,0,1); W=0.299,0.587,0.114; 33 uniform knots, piecewise linear; tone_strength already applied";
const r5 = (v) => Math.round(v * 1e5) / 1e5 + 0;   // + 0: no -0
export function toneBlock(theta, a = 1, luma = LUMA_DEFAULT) {
  const cv = curves33(Float64Array.from(theta), a), xs = Array.from({ length: 33 }, (_, k) => k / 32);
  const pts = (v) => v.map((y, k) => [xs[k], r5(y)]);
  return { y_curve: pts(cv.h), c_curves: { r: pts(cv.d[0]), g: pts(cv.d[1]), b: pts(cv.d[2]) }, luma_arg: luma, domain: TONE_DOMAIN };
}

// args: { name, slot|null, source:{type,name,licence,sha256,space,title,table_md5?}, stage1 {ranking}, chosen {candidate, mode},
//         refit {orf, dE, pct_lt5}|null (quick matrix refit), fit {orf, theta, strength, dE, pct_lt5, guards}|null (full fit; wins over refit),
//         fits {candidate: {dE}} (other fitted bases, for dE_fit), tieDE, scenes }
export function buildLookFile({ name, slot = null, source, stage1, chosen, refit = null, fit: full = null, fits = {}, tieDE = 0.1, scenes = "ref-syn-1 (synthetic, 6 scenes)", notes = "" }) {
  const done = full || refit;
  const ranking = stage1.ranking.map((e) => {
    const isC = e.candidate === chosen.candidate, f = isC ? (full || refit) : fits[e.candidate];
    return { candidate: e.candidate, mode: e.mode, dE: r3(e.dE), pct_lt5: Math.round(e.pct_lt5 * 10) / 10, dE_fit: f ? r3(f.dE) : null, stage: f ? "refit" : "stock" };
  });
  const src = { type: source.type, name: source.name, licence: source.licence || "", sha256: source.sha256, space: source.space, title: (source.title || "").slice(0, 120), approximate: false, requires_file: true };
  if (source.tableMd5) src.table_md5 = source.tableMd5;
  const cand = stage1.ranking.find((e) => e.candidate === chosen.candidate);
  const fit = { model: "cm-v2-web1", mode: chosen.mode, predicted: { dE: r3(done ? done.dE : cand.dE), pct_lt5: Math.round((done ? done.pct_lt5 : cand.pct_lt5) * 10) / 10, scenes } };
  const orf = done ? done.orf : chosen.orf;
  if (validOrf(orf)) fit.matrix_orf = orf.slice();
  if (full) {
    fit.tone = toneBlock(full.theta, full.strength, full.luma);
    const g = full.guards || {};
    fit.guards = { composed_max: g.composed_max != null ? g.composed_max : composedMax(orf), tone_strength: full.strength };
    if (g.hdr_clip_pct != null) fit.guards.hdr_clip_pct = g.hdr_clip_pct;
  }
  const look = {
    name: String(name).replace(/@/g, "").replace(/[^\x20-\x7e]/g, "").slice(0, 17) || "Web Look",
    source: src,
    base: { mode: chosen.mode, candidate: chosen.candidate, stage: done ? "refit" : "stock", ranking, tie_dE: tieDE },
    fit,
    notes: (notes || "Ranked, fitted and previewed in the local web prototype (cm-v2-web1, " + (full ? "matrix + tone curves" : "matrix") + "). Predicted dE is a model value, not a camera result.").slice(0, 200),
  };
  if (slot) look.slot = slot;
  return { format: "om10mi-look", version: 2, target: "E113", generator: { name: "om10mi-lut-web", version: "0.1", model: "cm-v2-web1" }, looks: [look] };
}
