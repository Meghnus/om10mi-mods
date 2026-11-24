// score.js - exposure-matched CIEDE2000 score shared by the ranker and the fitter.
// Per scene: shift the candidate L* by the median L* difference to the target, mean dE2000 over pixels; then mean over scenes.
import { de2000 } from "./color.js";

function median(a, n) {
  const s = Float32Array.from(a.subarray(0, n)).sort();
  return n % 2 ? s[(n - 1) / 2] : 0.5 * (s[n / 2 - 1] + s[n / 2]);
}

export class Scorer {
  // scenes: [{start, count}] in pixels
  constructor(scenes) {
    this.scenes = scenes;
    this.dL = new Float32Array(Math.max(...scenes.map((s) => s.count)));
    this.shift = new Float64Array(scenes.length);
  }
  // lt, lo: Lab Float32Array n*3. Returns { dE, pct_lt5, perScene }; this.shift holds the per-scene L* shifts of the call.
  score(lt, lo) {
    let tot = 0, lt5 = 0;
    const per = [];
    this.scenes.forEach((sc, si) => {
      const o = sc.start * 3, n = sc.count;
      for (let i = 0; i < n; i++) this.dL[i] = lt[o + i * 3] - lo[o + i * 3];
      const sh = median(this.dL, n);
      this.shift[si] = sh;
      let s = 0, c5 = 0;
      for (let i = 0; i < n; i++) {
        const k = o + i * 3;
        const de = de2000(lt[k], lt[k + 1], lt[k + 2], lo[k] + sh, lo[k + 1], lo[k + 2]);
        s += de; if (de < 5) c5++;
      }
      per.push(s / n);
      tot += s / n; lt5 += c5 / n;
    });
    return { dE: tot / this.scenes.length, pct_lt5: (100 * lt5) / this.scenes.length, perScene: per };
  }
}
