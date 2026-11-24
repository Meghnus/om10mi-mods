// composed.js - the builder's composed-coefficient rule for a slot matrix, ported 1:1 from olylook so the page never accepts a matrix the builder refuses.
// Source of truth (Python, same repo):
//   tools/olylook/sites.py  check_matrix(s, L16)  : cave constants L16 are 9 x s16; worst composed |c| over (a) the +-64 row-sum sweep of both stock sources
//        (fw/mndis/scratch/out/cm2_refit.py sweep_ok) and (b) the measured A variants (cm_refit.py max_composed / A_variants) must stay < 1024 (11-bit wrap)
//   cm_refit.py solveL(E)                          : integer L16 whose predicted ORF is closest to E (A = A_STOCK)
//   cm_common.py compose / norm128 / orf_pred      : the cave compose (>> 8) and the diagonal-replacing normaliser
// The integers below are the measured normaliser inputs of those files (numbers of behaviour, not firmware tables).
// composedMax(E) = check_matrix(solveL(E)) for E = the 9 ORF 0x0200-style integers.
const A_STOCK = [223, -90, -5, -28, 174, -18, 10, -52, 170];
const A_OFF = [[-90, -5, -28, -18, 10, -52], [-90, -5, -27, -19, 9, -48]];   // manual lens, AF-lens bank
const A_DIAG = [[194, 225], [172, 175], [167, 172]];

const compose = (L, m) => { const o = []; for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) o.push((L[3 * i] * m[j] + L[3 * i + 1] * m[3 + j] + L[3 * i + 2] * m[6 + j]) >> 8); return o; };
function norm128(m) {
  const o = m.slice();
  o[1] &= ~1; o[0] = 128 - o[1] - o[2];
  if ((o[3] + o[5]) & 2) { o[3] &= ~1; o[5] &= ~1; }
  o[4] = 128 - o[3] - o[5];
  o[7] &= ~1; o[8] = 128 - o[6] - o[7];
  return o;
}
export const orfPred = (L, A = A_STOCK) => norm128(compose(L, A)).map((v) => 2 * v);

const roundEven = (v) => { const r = Math.round(v); return Math.abs(v % 1) === 0.5 && r % 2 ? r - 1 : r; };   // numpy.round
const AINV = (() => {
  const [a, b, c, d, e, f, g, h, i] = A_STOCK, A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g, det = a * A + b * B + c * C;
  return [A / det, -(b * i - c * h) / det, (b * f - c * e) / det, B / det, (a * i - c * g) / det, -(a * f - c * d) / det, C / det, -(a * h - b * g) / det, (a * e - b * d) / det];
})();

export function solveL(E) {
  let L = [];
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) L.push(roundEven(256 * ((E[i * 3] / 2) * AINV[j] + (E[i * 3 + 1] / 2) * AINV[3 + j] + (E[i * 3 + 2] / 2) * AINV[6 + j])));
  const err = (Lv) => { const p = orfPred(Lv); let s = 0; for (let k = 0; k < 9; k++) s += Math.abs(p[k] - E[k]); return s; };
  let cur = err(L);
  for (let it = 0; it < 4; it++) {
    let improved = false;
    for (let k = 0; k < 9; k++) for (const dv of [-2, -1, 1, 2]) {
      const Lt = L.slice(); Lt[k] += dv;
      const e = err(Lt);
      if (e < cur) { L = Lt; cur = e; improved = true; }
    }
    if (!improved) break;
  }
  return L;
}

const maxAbs = (v) => v.reduce((m, x) => Math.max(m, Math.abs(x)), 0);
export function composedMaxL(L) {
  let worst = 0;
  for (const o of A_OFF) {                                      // sweep_ok: +-64 on the row-sum diagonals
    const rs = [128 - o[0] - o[1], 128 - o[2] - o[3], 128 - o[4] - o[5]];
    for (const d0 of [rs[0] - 64, rs[0], rs[0] + 64]) for (const d1 of [rs[1] - 64, rs[1], rs[1] + 64]) for (const d2 of [rs[2] - 64, rs[2], rs[2] + 64])
      worst = Math.max(worst, maxAbs(orfPred(L, [d0, o[0], o[1], o[2], d1, o[3], o[4], o[5], d2])));
  }
  for (const o of A_OFF) {                                      // max_composed: measured diagonal variants
    for (const d0 of A_DIAG[0]) for (const d1 of A_DIAG[1]) for (const d2 of A_DIAG[2]) worst = Math.max(worst, maxAbs(orfPred(L, [d0, o[0], o[1], o[2], d1, o[3], o[4], o[5], d2])));
    worst = Math.max(worst, maxAbs(orfPred(L, [128 - o[0] - o[1], o[0], o[1], o[2], 128 - o[2] - o[3], o[3], o[4], o[5], 128 - o[4] - o[5]])));
  }
  return worst;
}
export const composedMax = (E) => composedMaxL(solveL(E));
export const COMPOSED_LIMIT = 1024;   // builder refuses at >= 1024
