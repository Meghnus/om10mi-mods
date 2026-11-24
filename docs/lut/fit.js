// fit.js - stage 2: fit the camera look to the target LUT in our own model space (cm-v2-web1): matrix (6 ORF off-diagonals, integers) +
// tone curves = the parameters the camera look can carry (lut_PLAN section 4/7):
//   d_c(u), c = r,g,b : 9 knots each, u = x^(1/2.4)           ~ the camera's per-channel T3 (changes chroma)
//   h(Y)              : 17 knots                               ~ the camera's luma-only T2
// model, luma argument "post" (default, S7): y_c = clip(F_m(u_c) + d_c(u_c) + h(Y3), 0, 1), Y3 = W.(F_m + d), out = clip(P_m y, 0, 1)
//   the luma lift acts on the luma AFTER the per-channel curves, exactly where the camera's T2 acts after T3, so every (d, h) is reachable by
//   a (T3, T2) pair (the lift's remaining difference is the 9-knot T3 grid and the 10-bit tables). "yb" = the web1 definition of spec 9c
//   (y_c = F + d - W.d + h(Yb), Yb = W.F): the luma-neutral d makes h a function of the PRE-curve luma, which a T2 cannot follow pixel by pixel.
//   (q_c terms are not part of a fit)
// Method: matrix = Nelder-Mead (as the quick refit); tone = IRLS-Levenberg-Marquardt on a CIEDE2000-like residual with an analytic sparse
// Jacobian (each pixel touches 8 knots), exact dE2000 for accept/reject, monotone projection of F+d_c and Y+h, smoothness prior;
// then matrix polish, tone polish, highlight-clip guard (as olylook guard_hdr: blend the tone toward stock). Pure functions: no DOM, no network.
import { simulate, lerpK, relMatrix } from "./model.js";
import { rgb2lab, rgb2lab1 } from "./color.js";
import { Scorer } from "./score.js";
import { srgbDecode, srgbEncode } from "./lutcore.js";
import { composedMax, COMPOSED_LIMIT } from "./composed.js";

export const KD = 9, KH = 17, NP = 3 * KD + KH;
const W0 = 0.299, W1 = 0.587, W2 = 0.114, INV24 = 1 / 2.4;
const BOUND = 0.35;

export const HDR_EV = 0.5;
export const LUMA_DEFAULT = "post";   // "post" | "yb"; written to the look file as fit.tone.luma_arg
export class CancelError extends Error {}

// ---- parameter vector helpers ------------------------------------------------------------------------------------------
export const zeroTheta = () => new Float64Array(NP);
export function splitTheta(theta) {
  return { d: [theta.subarray(0, KD), theta.subarray(KD, 2 * KD), theta.subarray(2 * KD, 3 * KD)], h: theta.subarray(3 * KD) };
}
// sample a candidate's own d (129 knots) / h (33 knots) at the fit knots (the grids nest exactly: 128/8, 32/16)
export function thetaFromCandidate(c) {
  const th = zeroTheta();
  if (!c.d) return th;
  for (let ch = 0; ch < 3; ch++) for (let j = 0; j < KD; j++) th[ch * KD + j] = lerpK(c.d[ch], j / (KD - 1));
  for (let j = 0; j < KH; j++) th[3 * KD + j] = lerpK(c.h, j / (KH - 1));
  return th;
}
// 33-knot description (what the look file carries), tone strength a scales all knots (blend toward stock)
export function curves33(theta, a = 1, n = 33) {
  const { d, h } = splitTheta(theta);
  const samp = (v) => Array.from({ length: n }, (_, k) => a * lerpK(v, k / (n - 1)));
  return { d: d.map(samp), h: samp(h) };
}

// candidate object for model.simulate from (mode, ORF matrix, theta)
export function fitCandidate(model, mode, orf, theta, a = 1, luma = LUMA_DEFAULT) {
  const { d, h } = splitTheta(theta);
  const sc = (v) => (a === 1 ? Float64Array.from(v) : Float64Array.from(v, (x) => x * a));
  const zero = Float64Array.of(0, 0);
  return { name: "fit", mode, orf, luma, M: relMatrix(model, orf), d: d.map(sc), h: sc(h), q: [zero, zero, zero], F: model.modes[mode].F, P: model.modes[mode].P };
}
// candidate from a look-file style 33-knot description (re-scoring the exported numbers); cv.luma = fit.tone.luma_arg ("yb" when absent, as in a web1 file)
export function candidateFromCurves(model, mode, orf, cv, luma = cv.luma || "yb") {
  const zero = Float64Array.of(0, 0);
  return { name: "fit", mode, orf, luma, M: relMatrix(model, orf), d: cv.d.map((v) => Float64Array.from(v)), h: Float64Array.from(cv.h), q: [zero, zero, zero], F: model.modes[mode].F, P: model.modes[mode].P };
}

// ---- monotone projection ----------------------------------------------------------------------------------------------
function pav(y) {   // non-decreasing isotonic fit, unit weights
  const v = [], w = [];
  for (const x of y) {
    v.push(x); w.push(1);
    while (v.length > 1 && v[v.length - 2] > v[v.length - 1]) {
      const b = v.pop(), wb = w.pop(), a = v.pop(), wa = w.pop();
      v.push((a * wa + b * wb) / (wa + wb)); w.push(wa + wb);
    }
  }
  const out = [];
  v.forEach((x, i) => { for (let k = 0; k < w[i]; k++) out.push(x); });
  return out;
}
function breakpoints(F) {   // u positions where F + d_c can bend
  const set = new Set();
  for (let j = 0; j < KD; j++) set.add(Math.round((j / (KD - 1)) * 1e9) / 1e9);
  const nF = F.length;
  for (let k = 0; k < nF; k++) set.add(Math.round(0.85 * (k / (nF - 1)) * 1e9) / 1e9);
  set.add(1);
  return Array.from(set).sort((a, b) => a - b);
}
const Fu = (F, u) => lerpK(F, Math.min(u, 0.85) / 0.85);
// F itself is a fitted curve and not strictly monotone, so the rule is relative: F + d_c may not fall more than F falls (g - m non-decreasing,
// m = running sum of F's own decreases over the breakpoints); Y + h must be non-decreasing. Returns the largest violation (0 = fine).
const floorOf = (fG) => { const m = [0]; for (let k = 1; k < fG.length; k++) m.push(m[k - 1] + Math.min(0, fG[k] - fG[k - 1])); return m; };
export function toneViolation(F, theta) {
  const G = breakpoints(F), { d, h } = splitTheta(theta), fG = G.map((u) => Fu(F, u)), m = floorOf(fG);
  let worst = 0;
  for (let c = 0; c < 3; c++) {
    let prev = null;
    G.forEach((u, k) => { const g = fG[k] + lerpK(d[c], u) - m[k]; if (prev !== null) worst = Math.max(worst, prev - g); prev = g; });
  }
  for (let j = 1; j < KH; j++) worst = Math.max(worst, -((h[j] + j / (KH - 1)) - (h[j - 1] + (j - 1) / (KH - 1))));
  return worst;
}
// clamp to the bound and make F + d_c (relative to F's own dips) and Y + h non-decreasing; returns a new theta or null when it cannot be made so.
// Exact for piecewise-linear d: on node interval j the slope of d may not fall below -(smallest non-negative slope of F inside the interval),
// i.e. d_{j+1} - d_j >= -c_j; with d'_j = d_j + sum_{i<j} c_i this is "d' non-decreasing", so PAV is the Euclidean projection.
export function projectTone(F, theta) {
  const th = Float64Array.from(theta, (v) => Math.max(-BOUND, Math.min(BOUND, v)));
  const G = breakpoints(F), { d, h } = splitTheta(th);
  const c = [];
  for (let j = 0; j < KD - 1; j++) {
    const u0 = j / (KD - 1), u1 = (j + 1) / (KD - 1);
    let smin = Infinity;
    for (let k = 0; k + 1 < G.length; k++) {
      if (G[k] < u0 - 1e-12 || G[k + 1] > u1 + 1e-12) continue;
      smin = Math.min(smin, Math.max(0, (Fu(F, G[k + 1]) - Fu(F, G[k])) / (G[k + 1] - G[k])));
    }
    c.push(Number.isFinite(smin) ? (smin * (u1 - u0)) : 0);
  }
  const C = [0]; for (let j = 0; j < KD - 1; j++) C.push(C[j] + c[j]);
  for (let ch = 0; ch < 3; ch++) {
    const dp = pav(Array.from(d[ch], (v, j) => v + C[j]));
    for (let j = 0; j < KD; j++) d[ch][j] = dp[j] - C[j];
  }
  const z = Array.from(h, (v, j) => v + j / (KH - 1)), zi = pav(z);
  for (let j = 0; j < KH; j++) h[j] = zi[j] - j / (KH - 1);
  return toneViolation(F, th) <= 1e-9 ? th : null;
}

// ---- Nelder-Mead on the 6 ORF off-diagonals (rows sum 256), integer result -------------------------------------------------
const OFF = [1, 2, 3, 5, 6, 7];
export const orfFromOff = (p) => {
  const E = new Array(9).fill(0);
  OFF.forEach((idx, i) => { E[idx] = Math.round(p[i]); });
  for (let r = 0; r < 3; r++) E[r * 4] = 256 - E[r * 3 + ((r + 1) % 3)] - E[r * 3 + ((r + 2) % 3)];
  return E;
};
// costOfE(E) -> dE (number). Returns the best simplex vertex; the caller compares it with the start.
export function nelderMeadOrf(costOfE, orf0, maxEval = 240, bound = 1000, minEval = 60) {
  const cost = (p) => {
    for (const v of p) if (Math.abs(v) > bound) return 100 + Math.abs(v) - bound;
    const E = orfFromOff(p), cm = composedMax(E);   // builder rule (composed.js): refused at >= 1024
    if (cm >= COMPOSED_LIMIT) return 100 + (cm - COMPOSED_LIMIT) / 100;
    return costOfE(E);
  };
  const p0 = OFF.map((i) => orf0[i]), nD = 6, simp = [p0.slice()];
  for (let i = 0; i < nD; i++) { const q = p0.slice(); q[i] += 24; simp.push(q); }
  const f = simp.map(cost);
  let evals = nD + 1;
  while (evals < maxEval) {
    const idx = f.map((v, i) => i).sort((a, b) => f[a] - f[b]);
    const S = idx.map((i) => simp[i]), Fv = idx.map((i) => f[i]);
    for (let i = 0; i <= nD; i++) { simp[i] = S[i]; f[i] = Fv[i]; }
    if (Math.abs(f[nD] - f[0]) < 1e-4 && evals > minEval) break;
    const cen = new Array(nD).fill(0);
    for (let i = 0; i < nD; i++) for (let j = 0; j < nD; j++) cen[j] += simp[i][j] / nD;
    const mix = (a, b, t) => a.map((v, j) => v + t * (b[j] - v));
    const xr = mix(cen, simp[nD], -1), fr = cost(xr); evals++;
    if (fr < f[0]) {
      const xe = mix(cen, simp[nD], -2), fe = cost(xe); evals++;
      if (fe < fr) { simp[nD] = xe; f[nD] = fe; } else { simp[nD] = xr; f[nD] = fr; }
    } else if (fr < f[nD - 1]) { simp[nD] = xr; f[nD] = fr; }
    else {
      const xc = mix(cen, simp[nD], fr < f[nD] ? -0.5 : 0.5), fc = cost(xc); evals++;
      if (fc < Math.min(fr, f[nD])) { simp[nD] = xc; f[nD] = fc; }
      else for (let i = 1; i <= nD; i++) { simp[i] = mix(simp[0], simp[i], 0.5); f[i] = cost(simp[i]); evals++; }
    }
  }
  let bi = 0;
  for (let i = 1; i <= nD; i++) if (f[i] < f[bi]) bi = i;
  return { orf: orfFromOff(simp[bi]), dE: f[bi], evals };
}

// ---- the tone problem for one matrix ------------------------------------------------------------------------------------
function solveSPD(Hm, g, n) {   // Gaussian elimination with partial pivoting on a copy; returns Float64Array(n) or null
  const A = Float64Array.from(Hm), b = Float64Array.from(g);
  for (let c = 0; c < n; c++) {
    let p = c, best = Math.abs(A[c * n + c]);
    for (let r = c + 1; r < n; r++) if (Math.abs(A[r * n + c]) > best) { best = Math.abs(A[r * n + c]); p = r; }
    if (best < 1e-14) return null;
    if (p !== c) { for (let k = 0; k < n; k++) { const t = A[c * n + k]; A[c * n + k] = A[p * n + k]; A[p * n + k] = t; } const t = b[c]; b[c] = b[p]; b[p] = t; }
    for (let r = c + 1; r < n; r++) {
      const m = A[r * n + c] / A[c * n + c];
      if (m === 0) continue;
      for (let k = c; k < n; k++) A[r * n + k] -= m * A[c * n + k];
      b[r] -= m * b[c];
    }
  }
  const x = new Float64Array(n);
  for (let r = n - 1; r >= 0; r--) { let s = b[r]; for (let k = r + 1; k < n; k++) s -= A[r * n + k] * x[k]; x[r] = s / A[r * n + r]; }
  return x;
}

// smoothness prior: mu * sum (second differences of each curve)^2 + rho * |theta|^2, as a constant NP x NP matrix
function priorMatrix(mu, rho) {
  const Hm = new Float64Array(NP * NP);
  const curve = (o, n) => { for (let j = 1; j + 1 < n; j++) { const idx = [o + j - 1, o + j, o + j + 1], c = [1, -2, 1]; for (let a = 0; a < 3; a++) for (let b = 0; b < 3; b++) Hm[idx[a] * NP + idx[b]] += mu * c[a] * c[b]; } };
  for (let c = 0; c < 3; c++) curve(c * KD, KD);
  curve(3 * KD, KH);
  for (let i = 0; i < NP; i++) Hm[i * NP + i] += rho;
  return Hm;
}
const quad = (Hm, th) => { let s = 0; for (let i = 0; i < NP; i++) { let r = 0; for (let j = 0; j < NP; j++) r += Hm[i * NP + j] * th[j]; s += th[i] * r; } return s; };

export class ToneProblem {
  // xS: Float32Array n*3 (x after the stock matrix); lt: target Lab Float32Array n*3; scenes [{start,count}]
  // lt/scenes null = clip probe only (setMatrix + clipFrac)
  constructor(model, mode, xS, lt, scenes, { mu = 5, rho = 0.02, luma = LUMA_DEFAULT } = {}) {
    this.model = model; this.mode = mode; this.xS = xS; this.lt = lt; this.scenes = scenes;
    this.luma = luma; this.post = luma === "post";
    this.n = xS.length / 3;
    this.F = model.modes[mode].F; this.P = model.modes[mode].P;
    const n = this.n;
    if (!lt) this._alloc(n); else this._init(n, mu, rho);
  }
  _alloc(n) {
    this.u = new Float64Array(3 * n); this.f = new Float64Array(3 * n); this.yb = new Float64Array(n); this.hs = new Float64Array(n);
    this.sd = new Uint8Array(3 * n); this.wd = new Float64Array(3 * n); this.sh = new Uint8Array(n); this.wh = new Float64Array(n);
  }
  _init(n, mu, rho) {
    const { lt, scenes } = this;
    this.scorer = new Scorer(scenes);
    this.Hprior = priorMatrix(mu, rho);
    this._alloc(n);
    this.lab = new Float32Array(3 * n);
    this.scene = new Uint16Array(n); this.sw = new Float64Array(n);
    scenes.forEach((s, i) => { for (let k = 0; k < s.count; k++) { this.scene[s.start + k] = i; this.sw[s.start + k] = 1 / (scenes.length * s.count); } });
    // target-side residual projection (CIEDE2000 first order: dL/S_L, chroma / S_C and hue / S_H directions, G-corrected a)
    this.R = new Float32Array(5 * n);   // iSL, c_a, c_b, h_a, h_b
    for (let i = 0; i < n; i++) {
      const L = lt[i * 3], a = lt[i * 3 + 1], b = lt[i * 3 + 2];
      const C = Math.hypot(a, b), C7 = C ** 7, G = 0.5 * (1 - Math.sqrt(C7 / (C7 + 6103515625)));
      const ap = (1 + G) * a, Cp = Math.hypot(ap, b);
      const hb = Math.atan2(b, ap), T = 1 - 0.17 * Math.cos(hb - 0.5235987755982988) + 0.24 * Math.cos(2 * hb) + 0.32 * Math.cos(3 * hb + 0.10471975511965977) - 0.2 * Math.cos(4 * hb - 1.0995574287564276);
      const l50 = (L - 50) * (L - 50), SL = 1 + (0.015 * l50) / Math.sqrt(20 + l50), SC = 1 + 0.045 * Cp, SH = 1 + 0.015 * Cp * T;
      const er = Cp > 1e-6 ? [ap / Cp, b / Cp] : [1, 0], et = [-er[1], er[0]];
      const o = i * 5;
      this.R[o] = 1 / SL; this.R[o + 1] = ((1 + G) * er[0]) / SC; this.R[o + 2] = er[1] / SC; this.R[o + 3] = ((1 + G) * et[0]) / SH; this.R[o + 4] = et[1] / SH;
    }
    this.shift = new Float64Array(scenes.length);
    this.tmpLab = new Float64Array(3);
  }
  setMatrix(orf) {
    this.orf = orf;
    const M = relMatrix(this.model, orf), F = this.F, xS = this.xS, n = this.n;
    for (let i = 0; i < n; i++) {
      const k = i * 3, a = xS[k], b = xS[k + 1], c = xS[k + 2];
      const x = [M[0] * a + M[1] * b + M[2] * c, M[3] * a + M[4] * b + M[5] * c, M[6] * a + M[7] * b + M[8] * c];
      const f = [0, 0, 0];
      for (let ch = 0; ch < 3; ch++) {
        const u = x[ch] > 0 ? x[ch] ** INV24 : 0, uc = u < 0 ? 0 : u > 1 ? 1 : u;
        this.u[k + ch] = u;
        let v = lerpK(F, Math.min(u, 0.85) / 0.85); v = v < 0 ? 0 : v > 1 ? 1 : v;
        f[ch] = v; this.f[k + ch] = v;
        const s = uc * (KD - 1); let j = s | 0; if (j > KD - 2) j = KD - 2;
        this.sd[k + ch] = j; this.wd[k + ch] = s - j;
      }
      let yb = W0 * f[0] + W1 * f[1] + W2 * f[2]; yb = yb < 0 ? 0 : yb > 1 ? 1 : yb;
      this.yb[i] = yb;
      const s = yb * (KH - 1); let j = s | 0; if (j > KH - 2) j = KH - 2;
      this.sh[i] = j; this.wh[i] = s - j;
    }
    return this;
  }
  // y before the final clip for pixel i
  _y(i, dk, hk, a, out) {
    const k = i * 3;
    const s0 = this.sd[k], s1 = this.sd[k + 1], s2 = this.sd[k + 2];
    const d0 = a * (dk[0][s0] + (dk[0][s0 + 1] - dk[0][s0]) * this.wd[k]);
    const d1 = a * (dk[1][s1] + (dk[1][s1 + 1] - dk[1][s1]) * this.wd[k + 1]);
    const d2 = a * (dk[2][s2] + (dk[2][s2 + 1] - dk[2][s2]) * this.wd[k + 2]);
    if (this.post) {   // y = F + d + h(Y3), Y3 = clip(W.(F + d)); sh / wh / hs follow the current d (the h interval and slope depend on theta)
      const y3r = W0 * (this.f[k] + d0) + W1 * (this.f[k + 1] + d1) + W2 * (this.f[k + 2] + d2), y3 = y3r < 0 ? 0 : y3r > 1 ? 1 : y3r;
      const s = y3 * (KH - 1); let j = s | 0; if (j > KH - 2) j = KH - 2;
      this.sh[i] = j; this.wh[i] = s - j;
      this.hs[i] = y3r > 0 && y3r < 1 ? a * (hk[j + 1] - hk[j]) * (KH - 1) : 0;
      const hp = a * (hk[j] + (hk[j + 1] - hk[j]) * (s - j));
      out[0] = this.f[k] + d0 + hp; out[1] = this.f[k + 1] + d1 + hp; out[2] = this.f[k + 2] + d2 + hp;
      return;
    }
    const sh = this.sh[i], hh = a * (hk[sh] + (hk[sh + 1] - hk[sh]) * this.wh[i]), dy = W0 * d0 + W1 * d1 + W2 * d2;
    out[0] = this.f[k] + d0 - dy + hh; out[1] = this.f[k + 1] + d1 - dy + hh; out[2] = this.f[k + 2] + d2 - dy + hh;
  }
  // Lab of the whole picture for theta (tone strength a)
  render(theta, a = 1, lab = this.lab) {
    const { d, h } = splitTheta(theta), P = this.P, y = [0, 0, 0], n = this.n;
    for (let i = 0; i < n; i++) {
      this._y(i, d, h, a, y);
      const c0 = y[0] < 0 ? 0 : y[0] > 1 ? 1 : y[0], c1 = y[1] < 0 ? 0 : y[1] > 1 ? 1 : y[1], c2 = y[2] < 0 ? 0 : y[2] > 1 ? 1 : y[2];
      rgb2lab1(P[0] * c0 + P[1] * c1 + P[2] * c2, P[3] * c0 + P[4] * c1 + P[5] * c2, P[6] * c0 + P[7] * c1 + P[8] * c2, lab, i * 3);
    }
    return lab;
  }
  score(theta, a = 1) {
    const r = this.scorer.score(this.lt, this.render(theta, a));
    this.shift.set(this.scorer.shift);
    return r;
  }
  // fraction of pixels whose rendered display RGB has a channel >= 0.999
  clipFrac(theta, a = 1) {
    const { d, h } = splitTheta(theta), P = this.P, y = [0, 0, 0], n = this.n;
    let c = 0;
    for (let i = 0; i < n; i++) {
      this._y(i, d, h, a, y);
      const c0 = Math.min(1, Math.max(0, y[0])), c1 = Math.min(1, Math.max(0, y[1])), c2 = Math.min(1, Math.max(0, y[2]));
      if (P[0] * c0 + P[1] * c1 + P[2] * c2 >= 0.999 || P[3] * c0 + P[4] * c1 + P[5] * c2 >= 0.999 || P[6] * c0 + P[7] * c1 + P[8] * c2 >= 0.999) c++;
    }
    return c / n;
  }
  // IRLS normal equations at theta (shifts from the last accepted score): fills H, g; returns the weighted cost
  linearize(theta, H, g, shift) {
    const { d, h } = splitTheta(theta), P = this.P, n = this.n, R = this.R, lt = this.lt;
    H.fill(0); g.fill(0);
    const y = [0, 0, 0], yc = [0, 0, 0], lab0 = this.tmpLab, labk = [new Float64Array(3), new Float64Array(3), new Float64Array(3)];
    const JL = new Float64Array(9), A = new Float64Array(9), idx = new Int32Array(8), av = new Float64Array(24), dy = new Float64Array(3);
    const EPS = 1e-3;
    let cost = 0;
    const out = (c0, c1, c2, lab) => rgb2lab1(P[0] * c0 + P[1] * c1 + P[2] * c2, P[3] * c0 + P[4] * c1 + P[5] * c2, P[6] * c0 + P[7] * c1 + P[8] * c2, lab, 0);
    for (let i = 0; i < n; i++) {
      this._y(i, d, h, 1, y);
      const m = [0, 0, 0];
      for (let k = 0; k < 3; k++) { yc[k] = y[k] < 0 ? 0 : y[k] > 1 ? 1 : y[k]; m[k] = y[k] > 0 && y[k] < 1 ? 1 : 0; }
      out(yc[0], yc[1], yc[2], lab0);
      for (let k = 0; k < 3; k++) {
        const e = yc[k] + EPS > 1 ? -EPS : EPS, t = [yc[0], yc[1], yc[2]]; t[k] += e;
        out(t[0], t[1], t[2], labk[k]);
        for (let r = 0; r < 3; r++) JL[r * 3 + k] = (labk[k][r] - lab0[r]) / e;
      }
      const sc = this.scene[i], o = i * 3, ro = i * 5;
      const dL = lt[o] - (lab0[0] + shift[sc]), da = lt[o + 1] - lab0[1], db = lt[o + 2] - lab0[2];
      const r0 = R[ro] * dL, r1 = R[ro + 1] * da + R[ro + 2] * db, r2 = R[ro + 3] * da + R[ro + 4] * db;
      const rn = Math.sqrt(r0 * r0 + r1 * r1 + r2 * r2), w = this.sw[i] / Math.max(rn, 0.25);
      cost += this.sw[i] * rn;
      // A = Rproj . JL
      for (let k = 0; k < 3; k++) {
        const j0 = JL[k], j1 = JL[3 + k], j2 = JL[6 + k];
        A[k] = R[ro] * j0; A[3 + k] = R[ro + 1] * j1 + R[ro + 2] * j2; A[6 + k] = R[ro + 3] * j1 + R[ro + 4] * j2;
      }
      let np = 0;
      const push = (pi, v0, v1, v2) => {
        const a0 = A[0] * v0 + A[1] * v1 + A[2] * v2, a1 = A[3] * v0 + A[4] * v1 + A[5] * v2, a2 = A[6] * v0 + A[7] * v1 + A[8] * v2;
        idx[np] = pi; av[np * 3] = a0; av[np * 3 + 1] = a1; av[np * 3 + 2] = a2; np++;
      };
      for (let c = 0; c < 3; c++) {
        const s = this.sd[o + c], fr = this.wd[o + c], Wc = c === 0 ? W0 : c === 1 ? W1 : W2;
        for (let q = 0; q < 2; q++) {
          const wt = q ? fr : 1 - fr;
          for (let k = 0; k < 3; k++) dy[k] = wt * ((k === c ? 1 : 0) + (this.post ? this.hs[i] * Wc : -Wc)) * m[k];
          push(c * KD + s + q, dy[0], dy[1], dy[2]);
        }
      }
      for (let q = 0; q < 2; q++) { const wt = q ? this.wh[i] : 1 - this.wh[i]; push(3 * KD + this.sh[i] + q, wt * m[0], wt * m[1], wt * m[2]); }
      for (let p = 0; p < np; p++) {
        const ip = idx[p], p0 = av[p * 3], p1 = av[p * 3 + 1], p2 = av[p * 3 + 2];
        g[ip] += w * (p0 * r0 + p1 * r1 + p2 * r2);
        for (let q = 0; q < np; q++) H[ip * NP + idx[q]] += w * (p0 * av[q * 3] + p1 * av[q * 3 + 1] + p2 * av[q * 3 + 2]);
      }
    }
    return cost;
  }
  prior(theta) { return quad(this.Hprior, theta); }
  // IRLS-LM from theta0. Returns { theta, dE, pct_lt5, iters, evals }
  // frozen: optional Uint8Array(NP), 1 = parameter held at its start value (used by controlled experiments)
  fitTone(theta0, { maxIter = 40, tol = 2e-4, onIter = null, checkCancel = null, frozen = null } = {}) {
    let th = projectTone(this.F, theta0) || zeroTheta();
    let sc = this.score(th), cur = sc.dE + this.prior(th), shift = Float64Array.from(this.shift);
    let lam = 1e-2, evals = 1, it = 0, still = 0;
    const H = new Float64Array(NP * NP), g = new Float64Array(NP), Ht = new Float64Array(NP * NP), gt = new Float64Array(NP);
    for (; it < maxIter; it++) {
      if (checkCancel && checkCancel()) throw new CancelError();
      this.linearize(th, H, g, shift);
      for (let i = 0; i < NP; i++) { let r = 0; for (let j = 0; j < NP; j++) r += this.Hprior[i * NP + j] * th[j]; gt[i] = g[i] - r; }
      let accepted = false;
      for (let tries = 0; tries < 8; tries++) {
        Ht.set(H);
        for (let i = 0; i < NP * NP; i++) Ht[i] += this.Hprior[i];
        for (let i = 0; i < NP; i++) Ht[i * NP + i] += lam * (H[i * NP + i] + 1e-9) + 1e-9;
        if (frozen) for (let i = 0; i < NP; i++) if (frozen[i]) { for (let j = 0; j < NP; j++) { Ht[i * NP + j] = 0; Ht[j * NP + i] = 0; } Ht[i * NP + i] = 1; }
        const gz = frozen ? Float64Array.from(gt, (v, i) => (frozen[i] ? 0 : v)) : gt;
        const dl = solveSPD(Ht, gz, NP);
        if (!dl) { lam *= 10; continue; }
        const cand = projectTone(this.F, Float64Array.from(th, (v, i) => v + dl[i]));
        if (!cand) { lam *= 10; continue; }
        const s2 = this.score(cand); evals++;
        const c2 = s2.dE + this.prior(cand);
        if (c2 < cur - 1e-7) {
          still = cur - c2 < tol ? still + 1 : 0;
          th = cand; sc = s2; cur = c2; shift = Float64Array.from(this.shift); lam = Math.max(lam / 3, 1e-7); accepted = true; break;
        }
        lam *= 4;
      }
      if (onIter) onIter({ iter: it + 1, maxIter, dE: sc.dE });
      if (!accepted || still >= 2) { it++; break; }
    }
    return { theta: th, dE: sc.dE, pct_lt5: sc.pct_lt5, perScene: sc.perScene, iters: it, evals };
  }
}

// +0.5 EV probe (HDR_EV) for the clip guard: x doubled (linear light), and the target's clipped fraction on the display base brightened by one stop
// (linear sRGB x2, re-encoded). applyTarget(baseOver Float32Array n*3) -> target RGB Float32Array n*3 (the LUT applied by the caller)
export function makeHdrProbe(xS, base, applyTarget, ev = HDR_EV) {
  const n = xS.length / 3, x2 = new Float32Array(xS.length), over = new Float32Array(base.length), g = 2 ** ev;
  for (let i = 0; i < xS.length; i++) { x2[i] = xS[i] * g; over[i] = Math.min(1, srgbEncode(g * srgbDecode(Math.min(1, Math.max(0, base[i]))))); }
  const t = applyTarget(over);
  let c = 0;
  for (let i = 0; i < n; i++) if (t[i * 3] >= 0.999 || t[i * 3 + 1] >= 0.999 || t[i * 3 + 2] >= 0.999) c++;
  return { xS: x2, tClip: c / n };
}

// ---- the full fit of one base candidate --------------------------------------------------------------------------------------
// job: { model (prepared), cand (model.candidates entry), xS, lt, scenes, hdr: {xS: +0.5 EV probe pixels, tClip: clipped fraction of the target on them} | null, opts }
// hooks: { onProgress({stage, frac, dE, detail}), checkCancel() }
export function fitCandidateFull(job, hooks = {}) {
  const { model, cand, xS, lt, scenes } = job;
  const o = { matrixEval: 150, polishEval: 90, toneIter: 40, polishIter: 12, ...(job.opts || {}) };
  const t0 = (typeof performance !== "undefined" ? performance : Date).now();
  const now = () => (typeof performance !== "undefined" ? performance : Date).now();
  const progress = (stage, frac, dE, detail = "") => { if (hooks.onProgress) hooks.onProgress({ stage, frac, dE, detail, ms: now() - t0 }); };
  const cancelled = () => { if (hooks.checkCancel && hooks.checkCancel()) throw new CancelError(); };
  const luma = o.luma || LUMA_DEFAULT;
  const prob = new ToneProblem(model, cand.mode, xS, lt, scenes, { ...(o.prior || {}), luma });
  let evals = 0;
  const times = {};
  const stage = (name, fn) => { const t = now(); const r = fn(); times[name] = Math.round(now() - t); return r; };

  // start: the candidate's own matrix; tone start = zero (stock tone of the mode) or the candidate's own d/h sampled at the knots, whichever scores better
  let orf = cand.orf.slice(), theta = zeroTheta();
  prob.setMatrix(orf);
  const s0 = prob.score(theta), warm = thetaFromCandidate(cand);
  let startKind = "stock-tone", sBest = s0;
  if (cand.d) {
    const wp = projectTone(prob.F, warm), sw = wp ? prob.score(wp) : null;
    if (sw && sw.dE < s0.dE) { theta = wp; sBest = sw; startKind = "candidate-tone"; }
  }
  progress("start", 0, sBest.dE, startKind);

  const matrixStage = (maxEval, label, frac0, frac1) => stage(label, () => {
    let nEv = 0;
    const costOfE = (E) => {
      cancelled(); nEv++;
      const c = fitCandidate(model, cand.mode, E, theta, 1, luma);
      simulate(c, xS, prob.tmpRgb || (prob.tmpRgb = new Float32Array(xS.length)));
      const r = prob.scorer.score(lt, rgb2lab(prob.tmpRgb, prob.lab));
      if (nEv % 10 === 0) progress(label, frac0 + (frac1 - frac0) * Math.min(1, nEv / maxEval), r.dE, `eval ${nEv}`);
      return r.dE;
    };
    const base = costOfE(orf);
    const r = nelderMeadOrf(costOfE, orf, maxEval);
    evals += nEv;
    if (r.dE < base - 1e-9) { orf = r.orf; }
    prob.setMatrix(orf);
    return r;
  });

  matrixStage(o.matrixEval, "matrix", 0.02, 0.3);
  const toneStage = (maxIter, label, f0, f1) => stage(label, () => {
    const r = prob.fitTone(theta, { maxIter, checkCancel: hooks.checkCancel, onIter: (e) => progress(label, f0 + (f1 - f0) * (e.iter / e.maxIter), e.dE, `iter ${e.iter}`) });
    evals += r.evals;
    theta = r.theta;
    return r;
  });
  toneStage(o.toneIter, "tone", 0.3, 0.7);
  const dEafterTone = prob.score(theta).dE;
  // matrix polish under the fitted tone, then a short tone polish; keep only what improves
  const orfBefore = orf.slice(), thBefore = Float64Array.from(theta);
  matrixStage(o.polishEval, "matrix-polish", 0.7, 0.85);
  toneStage(o.polishIter, "tone-polish", 0.85, 0.92);
  const dEpolish = prob.score(theta).dE;
  if (dEpolish > dEafterTone) { orf = orfBefore; theta = thBefore; prob.setMatrix(orf); }

  const unguarded = prob.score(theta, 1);
  // highlight-clip guard (olylook guard_hdr analogue, on a +0.5 EV probe of the same pictures since the web sets hold no HDR frames):
  // clip <= min(target + 0.2 pp, stock + 1 pp); otherwise the tone is blended toward stock in 0.1 steps
  progress("guard", 0.93, null, "");
  let a = 1, clip = null, stockClip = null, tClip = null, warn = null;
  if (job.hdr) {
    const hp = new ToneProblem(model, cand.mode, job.hdr.xS, null, null, { luma }).setMatrix(orf);
    stockClip = hp.clipFrac(zeroTheta()); tClip = job.hdr.tClip == null ? null : job.hdr.tClip;
    const bound = tClip == null ? stockClip + 0.01 : Math.min(tClip + 0.002, stockClip + 0.01);
    clip = hp.clipFrac(theta, a);
    while (clip > bound + 1e-9 && a > 0) { a = Math.round((a - 0.1) * 10) / 10; clip = hp.clipFrac(theta, a); }
    if (a <= 0) warn = "highlight clip guard: tone disabled, matrix only";
  }
  const fin = prob.score(theta, a);
  const matrixOnly = prob.score(zeroTheta(), 1);
  const viol = toneViolation(prob.F, theta.map((v) => v * a));
  progress("done", 1, fin.dE, "");
  const maxE = Math.max(...orf.map(Math.abs));
  return {
    candidate: cand.name, mode: cand.mode, luma, orf, theta: Array.from(theta), toneStrength: a, startKind,
    dE: fin.dE, pct_lt5: fin.pct_lt5, perScene: fin.perScene, dEunguarded: unguarded.dE, pct_lt5_unguarded: unguarded.pct_lt5, startDE: s0.dE, matrixOnlyDE: matrixOnly.dE, dEafterTone, dEpolish,
    guards: { matrix_max_abs: maxE, composed_max: composedMax(orf), hdr_clip_pct: clip == null ? null : Math.round(clip * 1e4) / 100, hdr_clip_stock_pct: stockClip == null ? null : Math.round(stockClip * 1e4) / 100, hdr_clip_target_pct: tClip == null ? null : Math.round(tClip * 1e4) / 100, tone_strength: a, monotone_violation: viol, warning: warn },
    evals, ms: Math.round(now() - t0), stageMs: times,
  };
}
