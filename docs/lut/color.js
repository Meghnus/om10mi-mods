// color.js - sRGB -> CIELAB (D65, as skimage.color.rgb2lab) and CIEDE2000 (Sharma et al. 2005, as skimage deltaE_ciede2000).
const XR = 0.412453, XG = 0.35758, XB = 0.180423, YR = 0.212671, YG = 0.71516, YB = 0.072169, ZR = 0.019334, ZG = 0.119193, ZB = 0.950227;
const WX = 0.95047, WY = 1.0, WZ = 1.08883;
const lin = (c) => (c > 0.04045 ? ((c + 0.055) / 1.055) ** 2.4 : c / 12.92);
const f = (t) => (t > 0.008856451679035631 ? Math.cbrt(t) : 7.787037037037035 * t + 16 / 116);

// LUT of linearised 8-bit-ish values is not used: inputs are floats. rgb: Float32Array/Float64Array n*3 (0..1, clipped here) -> lab Float32Array n*3
export function rgb2lab(rgb, lab) {
  const n = rgb.length / 3;
  lab = lab || new Float32Array(rgb.length);
  for (let i = 0; i < n; i++) {
    const k = i * 3;
    const r = lin(Math.min(1, Math.max(0, rgb[k]))), g = lin(Math.min(1, Math.max(0, rgb[k + 1]))), b = lin(Math.min(1, Math.max(0, rgb[k + 2])));
    const fx = f((XR * r + XG * g + XB * b) / WX), fy = f((YR * r + YG * g + YB * b) / WY), fz = f((ZR * r + ZG * g + ZB * b) / WZ);
    lab[k] = 116 * fy - 16; lab[k + 1] = 500 * (fx - fy); lab[k + 2] = 200 * (fy - fz);
  }
  return lab;
}

// one colour: r,g,b in 0..1 (clipped) -> lab[o..o+2]
export function rgb2lab1(r, g, b, lab, o = 0) {
  r = lin(r < 0 ? 0 : r > 1 ? 1 : r); g = lin(g < 0 ? 0 : g > 1 ? 1 : g); b = lin(b < 0 ? 0 : b > 1 ? 1 : b);
  const fx = f((XR * r + XG * g + XB * b) / WX), fy = f((YR * r + YG * g + YB * b) / WY), fz = f((ZR * r + ZG * g + ZB * b) / WZ);
  lab[o] = 116 * fy - 16; lab[o + 1] = 500 * (fx - fy); lab[o + 2] = 200 * (fy - fz);
}

const RAD = Math.PI / 180, POW25_7 = 6103515625;
// one pair of Lab triples starting at offsets a, b
export function de2000(L1, a1, b1, L2, a2, b2) {
  const C1 = Math.sqrt(a1 * a1 + b1 * b1), C2 = Math.sqrt(a2 * a2 + b2 * b2);
  const cm = (C1 + C2) / 2, cm2 = cm * cm, Cb7 = cm2 * cm2 * cm2 * cm;
  const G = 0.5 * (1 - Math.sqrt(Cb7 / (Cb7 + POW25_7)));
  const ap1 = (1 + G) * a1, ap2 = (1 + G) * a2;
  const Cp1 = Math.sqrt(ap1 * ap1 + b1 * b1), Cp2 = Math.sqrt(ap2 * ap2 + b2 * b2);
  let hp1 = Math.atan2(b1, ap1); if (hp1 < 0) hp1 += 2 * Math.PI;
  let hp2 = Math.atan2(b2, ap2); if (hp2 < 0) hp2 += 2 * Math.PI;
  const dL = L2 - L1, dC = Cp2 - Cp1, CC = Cp1 * Cp2;
  let dh = hp2 - hp1;
  if (CC === 0) dh = 0; else if (dh > Math.PI) dh -= 2 * Math.PI; else if (dh < -Math.PI) dh += 2 * Math.PI;
  const dH = 2 * Math.sqrt(CC) * Math.sin(dh / 2);
  const Lb = (L1 + L2) / 2, Cb = (Cp1 + Cp2) / 2;
  let hb;
  if (CC === 0) hb = hp1 + hp2;
  else {
    hb = (hp1 + hp2) / 2;
    if (Math.abs(hp1 - hp2) > Math.PI) hb += hp1 + hp2 < 2 * Math.PI ? Math.PI : -Math.PI;
  }
  const T = 1 - 0.17 * Math.cos(hb - 0.5235987755982988) + 0.24 * Math.cos(2 * hb) + 0.32 * Math.cos(3 * hb + 0.10471975511965977) - 0.2 * Math.cos(4 * hb - 1.0995574287564276);
  const hd = (hb - 4.799655442984406) * 2.2918311805232929;   // (hb deg - 275) / 25
  const dTh = 0.5235987755982988 * Math.exp(-(hd * hd));
  const cb2 = Cb * Cb, Cb7b = cb2 * cb2 * cb2 * Cb;
  const Rc = 2 * Math.sqrt(Cb7b / (Cb7b + POW25_7));
  const l50 = (Lb - 50) * (Lb - 50);
  const Sl = 1 + (0.015 * l50) / Math.sqrt(20 + l50);
  const Sc = 1 + 0.045 * Cb, Sh = 1 + 0.015 * Cb * T;
  const Rt = -Math.sin(2 * dTh) * Rc;
  const x = dL / Sl, y = dC / Sc, z = dH / Sh;
  return Math.sqrt(x * x + y * y + z * z + Rt * y * z);
}
