// model.js - cm-v2-web1: the browser camera model, from our own measured per-mode parameters (model-cm-v2-web1.json).
//   x   = camera-linear RGB after the stock ORF matrix S (what the reference sets store)
//   x_c = Mrel x,   Mrel = wrap11(E)/256 . (S/256)^-1        (E = the candidate's 9 ORF 0x0200 integers)
//   y   = clip( F_m(x) + d(x) - W.d(x) + h(W.F_m(x)) + sum_c q_c(u_c) , 0, 1 ),   out = clip(P_m y, 0, 1)
//   F_m : 24-knot curve on u = x^(1/2.4) over 0..0.85;  d_c : per-channel curve (33 knots, u in 0..1);  h : luma lift (33 knots, Y in 0..1), q_c : per-channel luma-lift terms (33 knots, u in 0..1)
// Stock candidates have no d / h. All numbers come from the JSON: no firmware tables.
import { inv3 } from "./lutcore.js";

const W0 = 0.299, W1 = 0.587, W2 = 0.114;
export const wrap11 = (v) => ((((v + 1024) % 2048) + 2048) % 2048) - 1024;

export async function loadModel(url = "model-cm-v2-web1.json") {
  const r = await fetch(url);
  if (!r.ok) throw new Error("model json: HTTP " + r.status);
  return prepareModel(await r.json());
}

export function prepareModel(json) {
  const S = Float64Array.from(json.stock_orf.map((v) => wrap11(v) / 256));
  const Sinv = inv3(Array.from(S));
  const modes = {};
  for (const [name, m] of Object.entries(json.modes)) modes[name] = { F: Float64Array.from(m.F), P: Float64Array.from(m.P) };
  const base = json.base_model;
  const model = { id: json.id, provenance: json.provenance, stockOrf: json.stock_orf, Sinv, modes, json,
    baseA: Float64Array.from(base.A), baseCurve: Float64Array.from(base.curve), baseAinv: Float64Array.from(inv3(base.A)) };
  model.candidates = json.candidates.map((c) => makeCandidate(model, c));
  return model;
}

export function relMatrix(model, orf) {
  const E = orf.map((v) => wrap11(v) / 256), S = model.Sinv, M = new Float64Array(9);
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) { let s = 0; for (let k = 0; k < 3; k++) s += E[i * 3 + k] * S[k * 3 + j]; M[i * 3 + j] = s; }
  return M;
}

export function makeCandidate(model, c, orfOverride) {
  const orf = orfOverride || c.orf;
  return { name: c.name, mode: c.mode, orf, M: relMatrix(model, orf), d: c.d ? [Float64Array.from(c.d.r), Float64Array.from(c.d.g), Float64Array.from(c.d.b)] : null,
    h: c.h ? Float64Array.from(c.h) : null, q: c.q ? [Float64Array.from(c.q.r), Float64Array.from(c.q.g), Float64Array.from(c.q.b)] : null, F: model.modes[c.mode].F, P: model.modes[c.mode].P, kind: c.name.startsWith("stock") ? "stock" : "look", src: c };
}

const INV24 = 1 / 2.4;
// piecewise-linear lookup of knot vector v (nk knots) at t in 0..1
export function lerpK(v, t) {
  const nk = v.length, s = (t < 0 ? 0 : t > 1 ? 1 : t) * (nk - 1);
  let i = s | 0; if (i > nk - 2) i = nk - 2;
  const w = s - i;
  return v[i] + (v[i + 1] - v[i]) * w;
}

// camera simulation of n pixels: xS (x after the stock matrix, Float32Array n*3) -> out display RGB (Float32Array n*3, 0..1)
export function simulate(cand, xS, out, n = xS.length / 3) {
  const M = cand.M, F = cand.F, P = cand.P, d = cand.d, h = cand.h, q = cand.q;
  const nF = F.length;
  for (let i = 0; i < n; i++) {
    const k = i * 3, a = xS[k], b = xS[k + 1], c = xS[k + 2];
    const x0 = M[0] * a + M[1] * b + M[2] * c, x1 = M[3] * a + M[4] * b + M[5] * c, x2 = M[6] * a + M[7] * b + M[8] * c;
    const u0 = x0 > 0 ? x0 ** INV24 : 0, u1 = x1 > 0 ? x1 ** INV24 : 0, u2 = x2 > 0 ? x2 ** INV24 : 0;
    // F_m (clip to 0..1)
    let f0 = lerpK(F, Math.min(u0, 0.85) / 0.85), f1 = lerpK(F, Math.min(u1, 0.85) / 0.85), f2 = lerpK(F, Math.min(u2, 0.85) / 0.85);
    f0 = f0 < 0 ? 0 : f0 > 1 ? 1 : f0; f1 = f1 < 0 ? 0 : f1 > 1 ? 1 : f1; f2 = f2 < 0 ? 0 : f2 > 1 ? 1 : f2;
    let y0 = f0, y1 = f1, y2 = f2;
    if (d) {
      const d0 = lerpK(d[0], u0), d1 = lerpK(d[1], u1), d2 = lerpK(d[2], u2);
      let dy, hh;
      if (cand.luma === "post") {   // luma lift on the post-curve luma, as the camera's T2 acts after T3: y = F + d + l(Y3), Y3 = W.(F + d)
        dy = 0;
        hh = lerpK(h, Math.min(1, Math.max(0, W0 * (f0 + d0) + W1 * (f1 + d1) + W2 * (f2 + d2))));
      } else {
        const yb = Math.min(1, Math.max(0, W0 * f0 + W1 * f1 + W2 * f2));
        dy = W0 * d0 + W1 * d1 + W2 * d2;
        hh = lerpK(h, yb) + lerpK(q[0], u0) + lerpK(q[1], u1) + lerpK(q[2], u2);
      }
      y0 = f0 + d0 - dy + hh; y1 = f1 + d1 - dy + hh; y2 = f2 + d2 - dy + hh;
      y0 = y0 < 0 ? 0 : y0 > 1 ? 1 : y0; y1 = y1 < 0 ? 0 : y1 > 1 ? 1 : y1; y2 = y2 < 0 ? 0 : y2 > 1 ? 1 : y2;
    }
    let o0 = P[0] * y0 + P[1] * y1 + P[2] * y2, o1 = P[3] * y0 + P[4] * y1 + P[5] * y2, o2 = P[6] * y0 + P[7] * y1 + P[8] * y2;
    out[k] = o0 < 0 ? 0 : o0 > 1 ? 1 : o0; out[k + 1] = o1 < 0 ? 0 : o1 > 1 ? 1 : o1; out[k + 2] = o2 < 0 ? 0 : o2 > 1 ? 1 : o2;
  }
  return out;
}

// display-referred base (sRGB-like picture the LUT is applied to) <-> x (camera-linear after the stock matrix)
export function baseToX(model, base, out, n = base.length / 3) {
  const c = model.baseCurve, Ai = model.baseAinv, nk = c.length;
  const u = [0, 0, 0], lin = [0, 0, 0];
  for (let i = 0; i < n; i++) {
    for (let k = 0; k < 3; k++) {
      const v = Math.min(1, Math.max(0, base[i * 3 + k]));
      // invert the (non-decreasing) curve by bisection on the knots
      let lo = 0, hi = nk - 1;
      if (v <= c[0]) u[k] = 0; else if (v >= c[nk - 1]) u[k] = 1;
      else {
        while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (c[mid] <= v) lo = mid; else hi = mid; }
        const dd = c[hi] - c[lo];
        u[k] = (lo + (dd > 0 ? (v - c[lo]) / dd : 0)) / (nk - 1);
      }
      lin[k] = u[k] ** 2.4;
    }
    out[i * 3] = Ai[0] * lin[0] + Ai[1] * lin[1] + Ai[2] * lin[2];
    out[i * 3 + 1] = Ai[3] * lin[0] + Ai[4] * lin[1] + Ai[5] * lin[2];
    out[i * 3 + 2] = Ai[6] * lin[0] + Ai[7] * lin[1] + Ai[8] * lin[2];
  }
  return out;
}
