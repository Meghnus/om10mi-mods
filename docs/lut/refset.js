// refset.js - synthetic reference set ref-syn-1 (our own generator: colour patches, hue/sat sweep, skin / sky / foliage gradients, grey ramps).
// Images are display-referred sRGB "base" pictures (what a LUT is normally applied to); the camera side gets x = baseToX(base).
// Everything is computed from formulas here: no photographs, no firmware data.
const clamp = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
function hsv(h, s, v) {
  h = ((h % 360) + 360) % 360 / 60;
  const i = Math.floor(h), f = h - i, p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f));
  return [[v, t, p], [q, v, p], [p, v, t], [p, q, v], [t, p, v], [v, p, q]][i % 6];
}
const mix = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

// each generator: (u, v) in 0..1 (x, y of the picture) -> [r, g, b]
const PATCHES = (() => {
  const p = [];
  for (const v of [0.04, 0.18, 0.34, 0.5, 0.7, 0.92]) p.push([v, v, v]);
  for (const h of [0, 30, 60, 120, 190, 235]) p.push(hsv(h, 0.85, 0.8));
  for (const h of [0, 30, 60, 120, 190, 235]) p.push(hsv(h, 0.4, 0.75));
  p.push([0.45, 0.31, 0.26], [0.76, 0.58, 0.5], [0.36, 0.48, 0.64], [0.34, 0.42, 0.27], [0.5, 0.41, 0.66], [0.62, 0.36, 0.44]);
  return p;
})();

export const SCENE_DEFS = [
  { name: "colour patches", f: (u, v) => { const c = Math.min(5, Math.floor(u * 6)), r = Math.min(3, Math.floor(v * 4)); const in_ = (u * 6 - c > 0.06 && u * 6 - c < 0.94 && v * 4 - r > 0.06 && v * 4 - r < 0.94); return in_ ? PATCHES[r * 6 + c] : [0.18, 0.18, 0.18]; } },
  { name: "hue / sat sweep", f: (u, v) => (v < 0.5 ? hsv(u * 360, 1 - 0.8 * (v * 2), 0.9) : hsv(u * 360, 0.6, 0.9 - 0.75 * (v * 2 - 1))) },
  { name: "skin tones", f: (u, v) => { const c = mix([0.36, 0.21, 0.15], [0.96, 0.8, 0.7], Math.pow(u, 0.9)); const sh = 0.5 + 0.55 * (1 - v); const w = (1 - v) * 0.04; return [clamp(c[0] * sh + w), clamp(c[1] * sh + w * 0.5), clamp(c[2] * sh)]; } },
  { name: "sky gradient", f: (u, v) => { const top = mix([0.1, 0.3, 0.72], [0.2, 0.36, 0.62], u), hor = mix([0.74, 0.86, 0.97], [0.82, 0.84, 0.88], u); return mix(top, hor, Math.pow(v, 1.4)); } },
  { name: "foliage", f: (u, v) => { const c = mix([0.58, 0.66, 0.2], [0.09, 0.3, 0.13], u); const sh = 0.4 + 0.7 * (1 - v); return [clamp(c[0] * sh), clamp(c[1] * sh), clamp(c[2] * sh)]; } },
  { name: "grey ramps", f: (u, v) => { const t = u * 0.96 + 0.02; const tint = v < 0.34 ? [0, 0, 0] : v < 0.67 ? [0.05, 0.02, -0.05] : [-0.05, 0, 0.06]; return [clamp(t + tint[0] * t * (1 - t) * 4), clamp(t + tint[1] * t * (1 - t) * 4), clamp(t + tint[2] * t * (1 - t) * 4)]; } },
];

export function renderScene(def, w, h) {
  const out = new Float32Array(w * h * 3);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const c = def.f((x + 0.5) / w, (y + 0.5) / h), k = (y * w + x) * 3;
    out[k] = c[0]; out[k + 1] = c[1]; out[k + 2] = c[2];
  }
  return out;
}

// ranking dataset: every scene at w x h, concatenated (scene = group of pixels, equal weight as in the Python ranker)
export function synthDataset(w = 64, h = 48) {
  const parts = SCENE_DEFS.map((d) => renderScene(d, w, h));
  const base = new Float32Array(parts.reduce((s, p) => s + p.length, 0));
  const scenes = [];
  let o = 0;
  parts.forEach((p, i) => { base.set(p, o); scenes.push({ name: SCENE_DEFS[i].name, start: o / 3, count: w * h }); o += p.length; });
  return { base, scenes };
}

// a user picture (RGBA ImageData-like, 0..255) -> display base Float32Array + one-scene dataset downsampled to ~maxPx pixels
export function imageToBase(rgba, w, h) {
  const out = new Float32Array(w * h * 3);
  for (let i = 0; i < w * h; i++) { out[i * 3] = rgba[i * 4] / 255; out[i * 3 + 1] = rgba[i * 4 + 1] / 255; out[i * 3 + 2] = rgba[i * 4 + 2] / 255; }
  return out;
}
export function subsample(base, w, h, maxPx = 4096) {
  const step = Math.max(1, Math.ceil(Math.sqrt((w * h) / maxPx)));
  const ow = Math.floor(w / step), oh = Math.floor(h / step), out = new Float32Array(ow * oh * 3);
  for (let y = 0; y < oh; y++) for (let x = 0; x < ow; x++) {
    const k = ((y * step + (step >> 1)) * w + x * step + (step >> 1)) * 3, o = (y * ow + x) * 3;
    out[o] = base[k]; out[o + 1] = base[k + 1]; out[o + 2] = base[k + 2];
  }
  return { base: out, w: ow, h: oh };
}
