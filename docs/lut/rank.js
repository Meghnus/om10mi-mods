// rank.js - stage-1 base ranking (all candidates) + optional quick matrix refit, on a reference dataset.
// Method = fw/mndis/scratch/out/lut1_w/base_rank.py stage 1: target = LUT applied to the display base; candidate = camera model on x;
// score = per-scene exposure-matched CIEDE2000 (shift L* by the median L* difference), mean over pixels, then mean over scenes.
import { applyLut } from "./lutcore.js";
import { rgb2lab } from "./color.js";
import { simulate, makeCandidate } from "./model.js";
import { Scorer } from "./score.js";
import { nelderMeadOrf } from "./fit.js";

// dataset: { x: Float32Array(n*3), base: Float32Array(n*3), scenes: [{name, start, count}] }
export function makeDataset(model, base, scenes, baseToX) {
  const x = baseToX(model, base, new Float32Array(base.length));
  return { x, base, scenes, n: base.length / 3 };
}

export class Ranker {
  constructor(model, ds) {
    this.model = model;
    this.ds = ds;
    this.out = new Float32Array(ds.base.length);
    this.scorer = new Scorer(ds.scenes);
    this.candLab = new Map();
    this.renderMs = 0;
    const t0 = performance.now();
    for (const c of model.candidates) this.candLab.set(c.name, this.lab(c));
    this.renderMs = performance.now() - t0;
  }
  lab(cand) {
    simulate(cand, this.ds.x, this.out);
    return rgb2lab(this.out);
  }
  // target Lab for a LUT {lut33, space}
  target(lut, space = "display", strength = 1) {
    const tmp = applyLut(lut, this.ds.base, new Float32Array(this.ds.base.length), space, strength);
    return rgb2lab(tmp);
  }
  // exposure-matched dE of candidate Lab `lo` against target Lab `lt`
  score(lt, lo) {
    const r = this.scorer.score(lt, lo);
    return { dE: r.dE, pct_lt5: r.pct_lt5 };
  }
  // stage 1: rank every candidate; returns { ranking, dcpBaseDE, ms }
  stage1(lut, space = "display", strength = 1) {
    const t0 = performance.now();
    const lt = this.target(lut, space, strength);
    const res = this.model.candidates.map((c) => ({ candidate: c.name, mode: c.mode, ...this.score(lt, this.candLab.get(c.name)) }));
    res.sort((a, b) => a.dE - b.dE);
    const dcp = this.score(lt, rgb2lab(this.ds.base)).dE;
    return { ranking: res, dcpBaseDE: dcp, lt, ms: performance.now() - t0 };
  }
  // quick matrix-only refit (6 free off-diagonals, rows sum 256, candidate's own tone kept): Nelder-Mead (fit.js), integer result
  refit(candName, lt, maxEval = 240) {
    const t0 = performance.now();
    const c0 = this.model.candidates.find((c) => c.name === candName);
    const r = nelderMeadOrf((E) => this.score(lt, this.lab(makeCandidate(this.model, c0.src, E))).dE, c0.orf, maxEval);
    let E = r.orf, dE = r.dE;
    const d0 = this.score(lt, this.candLab.get(candName)).dE;
    if (d0 <= dE) { E = c0.orf.slice(); dE = d0; }            // never worse than the candidate as shipped
    const sc = this.score(lt, this.lab(makeCandidate(this.model, c0.src, E)));
    return { orf: E, dE: sc.dE, pct_lt5: sc.pct_lt5, evals: r.evals, ms: performance.now() - t0 };
  }
}
