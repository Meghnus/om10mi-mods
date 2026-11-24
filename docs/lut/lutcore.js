// lutcore.js - 3D LUT container, .cube and Adobe Creative Profile (.xmp RGBTable) importers.
// JS port of fw/lut_stage1/lutimport/{lutcore,imp_cube,imp_xmp}.py (own code, same behaviour; matched to the Python output by test/).
// Data layout: Float64Array n^3*3 in .cube order, red fastest. Trilinear sampling. No network, no DOM.
import { md5hex } from "./md5.js";

export const COMMON_N = 33;
export class LutError extends Error {}

export class Lut {
  constructor(n, data) {
    if (n < 2 || data.length !== n * n * n * 3) throw new LutError(`LUT size ${n} needs ${n ** 3 * 3} values, got ${data.length}`);
    this.n = n;
    this.data = data;
  }
  static identity(n = COMMON_N) {
    const d = new Float64Array(n ** 3 * 3), s = 1 / (n - 1);
    let k = 0;
    for (let b = 0; b < n; b++) for (let g = 0; g < n; g++) for (let r = 0; r < n; r++) { d[k++] = r * s; d[k++] = g * s; d[k++] = b * s; }
    return new Lut(n, d);
  }
  // trilinear lookup of one pixel (inputs clamped), writes out[o..o+2]
  sample(r, g, b, out, o = 0) {
    const n = this.n, m = n - 1, d = this.data;
    const fr = Math.min(1, Math.max(0, r)) * m, fg = Math.min(1, Math.max(0, g)) * m, fb = Math.min(1, Math.max(0, b)) * m;
    const r0 = Math.min(Math.floor(fr), m - 1), g0 = Math.min(Math.floor(fg), m - 1), b0 = Math.min(Math.floor(fb), m - 1);
    const dr = fr - r0, dg = fg - g0, db = fb - b0;
    const base = (r0 + g0 * n + b0 * n * n) * 3, sr = 3, sg = 3 * n, sb = 3 * n * n;
    for (let c = 0; c < 3; c++) {
      const i = base + c;
      const c000 = d[i], c100 = d[i + sr], c010 = d[i + sg], c110 = d[i + sr + sg];
      const c001 = d[i + sb], c101 = d[i + sr + sb], c011 = d[i + sg + sb], c111 = d[i + sr + sg + sb];
      const x00 = c000 + (c100 - c000) * dr, x10 = c010 + (c110 - c010) * dr;
      const x01 = c001 + (c101 - c001) * dr, x11 = c011 + (c111 - c011) * dr;
      const y0 = x00 + (x10 - x00) * dg, y1 = x01 + (x11 - x01) * dg;
      out[o + c] = y0 + (y1 - y0) * db;
    }
  }
  resample(nOut = COMMON_N) {
    if (nOut === this.n) return new Lut(this.n, Float64Array.from(this.data));
    const d = new Float64Array(nOut ** 3 * 3), s = 1 / (nOut - 1);
    let k = 0;
    for (let b = 0; b < nOut; b++) for (let g = 0; g < nOut; g++) for (let r = 0; r < nOut; r++) { this.sample(r * s, g * s, b * s, d, k); k += 3; }
    return new Lut(nOut, d);
  }
  // Float32 copy of the table (used by the fast pixel loops)
  maxAbsDiff(o) {
    if (o.n !== this.n) throw new LutError("size mismatch");
    let m = 0;
    for (let i = 0; i < this.data.length; i++) m = Math.max(m, Math.abs(this.data[i] - o.data[i]));
    return m;
  }
}

// ---- .cube -----------------------------------------------------------------------------------------------------
export function parseCube(text) {
  let size = null, title = "";
  let dmin = [0, 0, 0], dmax = [1, 1, 1];
  const vals = [];
  for (const raw of text.split(/\r\n|\r|\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const up = line.toUpperCase();
    if (up.startsWith("TITLE")) { const q = line.split(/\s+/); title = q.length > 1 ? line.slice(line.search(/\s/)).trim().replace(/^"|"$/g, "") : ""; continue; }
    if (up.startsWith("LUT_3D_SIZE")) { size = parseInt(line.split(/\s+/)[1], 10); continue; }
    if (up.startsWith("LUT_1D") || up.startsWith("LUT_3D_INPUT_RANGE")) throw new LutError(`1D LUTs / LUT_*_INPUT_RANGE are not supported (${line.split(/\s+/)[0]})`);
    if (up.startsWith("DOMAIN_MIN")) { dmin = line.split(/\s+/).slice(1, 4).map(Number); continue; }
    if (up.startsWith("DOMAIN_MAX")) { dmax = line.split(/\s+/).slice(1, 4).map(Number); continue; }
    const p = line.split(/\s+/);
    if (p.length === 3) {
      const a = Number(p[0]), b = Number(p[1]), c = Number(p[2]);
      if (Number.isNaN(a) || Number.isNaN(b) || Number.isNaN(c)) throw new LutError(`unreadable line: ${line.slice(0, 60)}`);
      vals.push(a, b, c);
    } else throw new LutError(`unknown keyword or malformed line: ${line.slice(0, 60)}`);
  }
  if (size === null || Number.isNaN(size)) throw new LutError("LUT_3D_SIZE not found");
  if (size < 2 || size > 256) throw new LutError(`LUT_3D_SIZE ${size} out of range`);
  if (vals.length !== size ** 3 * 3) throw new LutError(`expected ${size ** 3} entries, got ${vals.length / 3}`);
  const flat = Float64Array.from(vals);
  const identDomain = dmin.every((v) => v === 0) && dmax.every((v) => v === 1);
  if (!identDomain) {
    // DOMAIN_* is the INPUT range the lattice spreads over; rebuild on a plain 0..1 lattice of >= 33 nodes
    const rawLut = new Lut(size, flat);
    const m = Math.max(size, COMMON_N), s = 1 / (m - 1);
    const out = new Float64Array(m ** 3 * 3);
    let k = 0;
    const t = [0, 0, 0];
    for (let b = 0; b < m; b++) for (let g = 0; g < m; g++) for (let r = 0; r < m; r++) {
      const c = [r * s, g * s, b * s];
      for (let i = 0; i < 3; i++) t[i] = dmax[i] !== dmin[i] ? (c[i] - dmin[i]) / (dmax[i] - dmin[i]) : 0;
      rawLut.sample(Math.min(1, Math.max(0, t[0])), Math.min(1, Math.max(0, t[1])), Math.min(1, Math.max(0, t[2])), out, k);
      k += 3;
    }
    return { title, lut: new Lut(m, out) };
  }
  return { title, lut: new Lut(size, flat) };
}

export function formatCube(lut, title = "", comment = "") {
  const lines = [];
  if (comment) lines.push("# " + comment);
  if (title) lines.push(`TITLE "${title.replace(/"/g, "'")}"`);
  lines.push(`LUT_3D_SIZE ${lut.n}`, "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0");
  const d = lut.data;
  for (let i = 0; i < d.length; i += 3) lines.push(`${d[i].toFixed(6)} ${d[i + 1].toFixed(6)} ${d[i + 2].toFixed(6)}`);
  return lines.join("\n") + "\n";
}

// ---- Adobe Creative Profile (.xmp with crs:RGBTable) --------------------------------------------------------------
const ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?`'|()[]{}@%$#";
const IDX = new Map([...ALPHABET].map((c, i) => [c, i]));

export function b85Decode(text) {
  const out = [];
  let val = 0, phase = 0;
  for (const c of text) {
    if (/\s/.test(c)) continue;
    const d = IDX.get(c);
    if (d === undefined) throw new LutError("bad base85 character");
    val += d * 85 ** phase;
    phase++;
    if (phase === 5) {
      if (val > 0xffffffff) throw new LutError("base85 group overflows 32 bits");
      out.push(val & 255, (val >>> 8) & 255, (val >>> 16) & 255, (val >>> 24) & 255);
      val = 0; phase = 0;
    }
  }
  if (phase === 1) throw new LutError("truncated base85 data");
  if (phase >= 2) { // short final group: 1..3 bytes, little endian
    const nb = phase - 1;
    for (let i = 0; i < nb; i++) out.push((val >>> (8 * i)) & 255);
  }
  return Uint8Array.from(out);
}

export function hasRgbTable(text) { return /crs:RGBTable="[0-9A-Fa-f]{32}"/.test(text); }

async function inflate(bytes) {
  const ds = new DecompressionStream("deflate");
  const stream = new Blob([bytes]).stream().pipeThrough(ds);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

export async function decodeTable(encoded, digest) {
  const raw = b85Decode(encoded);
  if (raw.length < 4) throw new LutError("payload too short");
  const want = new DataView(raw.buffer, raw.byteOffset).getUint32(0, true);
  let block;
  try { block = await inflate(raw.subarray(4)); } catch (e) { throw new LutError("zlib: " + e.message); }
  if (block.length !== want) throw new LutError(`size mismatch: header ${want}, got ${block.length}`);
  const ok = md5hex(block) === digest.toLowerCase();
  const dv = new DataView(block.buffer, block.byteOffset, block.byteLength);
  const dims = dv.getUint32(8, true), size = dv.getUint32(12, true);
  if (dims !== 3) throw new LutError(`not a 3D table (dims=${dims})`);
  if (size < 2 || 16 + size ** 3 * 6 > block.length) throw new LutError(`table size ${size} does not match the block length`);
  const nop = [];
  for (let i = 0; i < size; i++) nop.push(Math.floor((i * 0xffff + (size >> 1)) / (size - 1)));
  const data = new Float64Array(size ** 3 * 3);
  let k = 0;
  for (let r = 0; r < size; r++) for (let g = 0; g < size; g++) for (let b = 0; b < size; b++) {
    const o = (r + g * size + b * size * size) * 3;
    data[o] = ((dv.getUint16(16 + 2 * k, true) + nop[r]) & 0xffff) / 65535;
    data[o + 1] = ((dv.getUint16(16 + 2 * k + 2, true) + nop[g]) & 0xffff) / 65535;
    data[o + 2] = ((dv.getUint16(16 + 2 * k + 4, true) + nop[b]) & 0xffff) / 65535;
    k += 3;
  }
  return { lut: new Lut(size, data), md5Ok: ok };
}

export async function parseProfile(text) {
  const m = text.match(/crs:RGBTable="([0-9A-Fa-f]{32})"/);
  if (!m) throw new LutError("no crs:RGBTable digest");
  const digest = m[1];
  const t = text.match(new RegExp(`crs:Table_${digest}="([^"]+)"`, "s"));
  if (!t) throw new LutError(`no crs:Table_${digest}`);
  const { lut, md5Ok } = await decodeTable(t[1], digest);
  const nm = text.match(/<crs:Name>.*?<rdf:li[^>]*>(.*?)<\/rdf:li>/s);
  const am = text.match(/crs:Amount="([-+0-9.eE]+)"/);
  return { name: nm ? nm[1].trim() : "", digest, lut, md5Ok, amount: am ? parseFloat(am[1]) : null };
}

// ---- common entry: text -> { kind, name, native, lut33, exactNodes, space, notes } ---------------------------------------
export async function importLutText(text, fileName) {
  const notes = [];
  if (hasRgbTable(text)) {
    const p = await parseProfile(text);
    if (!p.md5Ok) throw new LutError("MD5 self-check failed: the table is damaged or not a supported variant");
    let lut = p.lut;
    let exact = lut.n === COMMON_N;
    if (p.amount !== null && p.amount !== 1.0 && p.amount !== 100.0) {
      const frac = p.amount > 1 ? p.amount / 100 : p.amount;
      const id = Lut.identity(lut.n);
      lut = new Lut(lut.n, lut.data.map((v, i) => id.data[i] + frac * (v - id.data[i])));
      notes.push(`crs:Amount ${p.amount} applied as a blend toward identity (assumed linear [inference])`);
      exact = false;
    }
    if (lut.n !== COMMON_N) notes.push(`native size ${lut.n}^3 resampled trilinearly to ${COMMON_N}^3`);
    return { kind: "xmp-profile", name: p.name || fileName.replace(/\.[^.]*$/, ""), native: lut, lut33: lut.resample(COMMON_N), exactNodes: exact, space: "prophoto", notes, tableMd5: p.digest };
  }
  if (/crs:/.test(text) && !/LUT_3D_SIZE/.test(text)) throw new LutError("this .xmp is a slider preset without an RGBTable: the web prototype reads only 3D-table profiles and .cube files");
  const { title, lut } = parseCube(text);
  if (lut.n !== COMMON_N) notes.push(`native size ${lut.n}^3 resampled trilinearly to ${COMMON_N}^3`);
  return { kind: "cube", name: title || fileName.replace(/\.[^.]*$/, ""), native: lut, lut33: lut.resample(COMMON_N), exactNodes: lut.n === COMMON_N, space: "display", notes };
}

// ---- ProPhoto <-> sRGB (table applied in ProPhoto-sRGB-gamma, as the repo's 'fuji' kind) --------------------------------
const SRGB2XYZ = [0.4124564, 0.3575761, 0.1804375, 0.2126729, 0.7151522, 0.0721750, 0.0193339, 0.1191920, 0.9503041];
const BRAD_65_50 = [1.0478112, 0.0228866, -0.0501270, 0.0295424, 0.9904844, -0.0170491, -0.0092345, 0.0150436, 0.7521316];
const PP2XYZ50 = [0.7976749, 0.1351917, 0.0313534, 0.2880402, 0.7118741, 0.0000857, 0, 0, 0.8252100];
const mul = (A, B) => { const o = new Array(9).fill(0); for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) for (let k = 0; k < 3; k++) o[i * 3 + j] += A[i * 3 + k] * B[k * 3 + j]; return o; };
export function inv3(m) {
  const [a, b, c, d, e, f, g, h, i] = m;
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
  const det = a * A + b * B + c * C;
  return [A / det, -(b * i - c * h) / det, (b * f - c * e) / det, B / det, (a * i - c * g) / det, -(a * f - c * d) / det, C / det, -(a * h - b * g) / det, (a * e - b * d) / det];
}
const XYZ50_PP = inv3(PP2XYZ50), BRAD_50_65 = inv3(BRAD_65_50), XYZ_SRGB = inv3(SRGB2XYZ);
export const SRGB_TO_PP = mul(XYZ50_PP, mul(BRAD_65_50, SRGB2XYZ));   // linear sRGB -> linear ProPhoto
export const PP_TO_SRGB = mul(XYZ_SRGB, mul(BRAD_50_65, PP2XYZ50));
export const srgbDecode = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
export const srgbEncode = (c) => (c <= 0 ? 0 : c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055);
const cl = (v) => Math.min(1, Math.max(0, v));
// sRGB display (0..1) -> ProPhoto-sRGB-gamma, clipped; and back
export function toPPsrgb(r, g, b, o, k) {
  const lr = srgbDecode(cl(r)), lg = srgbDecode(cl(g)), lb = srgbDecode(cl(b)), M = SRGB_TO_PP;
  o[k] = cl(srgbEncode(Math.max(0, M[0] * lr + M[1] * lg + M[2] * lb)));
  o[k + 1] = cl(srgbEncode(Math.max(0, M[3] * lr + M[4] * lg + M[5] * lb)));
  o[k + 2] = cl(srgbEncode(Math.max(0, M[6] * lr + M[7] * lg + M[8] * lb)));
}
export function fromPPsrgb(r, g, b, o, k) {
  const lr = srgbDecode(cl(r)), lg = srgbDecode(cl(g)), lb = srgbDecode(cl(b)), M = PP_TO_SRGB;
  o[k] = cl(srgbEncode(M[0] * lr + M[1] * lg + M[2] * lb));
  o[k + 1] = cl(srgbEncode(M[3] * lr + M[4] * lg + M[5] * lb));
  o[k + 2] = cl(srgbEncode(M[6] * lr + M[7] * lg + M[8] * lb));
}

// apply a LUT to an RGB Float32Array (display sRGB in, display out); space 'display' | 'prophoto'; strength 0..1
export function applyLut(lut, rgb, out, space = "display", strength = 1) {
  const n = rgb.length / 3, t = new Float64Array(3), u = new Float64Array(3);
  for (let i = 0; i < n; i++) {
    const k = i * 3;
    let r = rgb[k], g = rgb[k + 1], b = rgb[k + 2];
    if (space === "prophoto") { toPPsrgb(r, g, b, t, 0); lut.sample(t[0], t[1], t[2], u, 0); cl3(u); fromPPsrgb(u[0], u[1], u[2], t, 0); }
    else { lut.sample(r, g, b, t, 0); cl3(t); }
    if (strength < 1) { t[0] = strength * t[0] + (1 - strength) * r; t[1] = strength * t[1] + (1 - strength) * g; t[2] = strength * t[2] + (1 - strength) * b; }
    out[k] = cl(t[0]); out[k + 1] = cl(t[1]); out[k + 2] = cl(t[2]);
  }
  return out;
}
function cl3(a) { a[0] = cl(a[0]); a[1] = cl(a[1]); a[2] = cl(a[2]); }
