#!/usr/bin/env python3
"""lutfit_check.py - stub of the local builder's "tone lift" gate for a look file v2 made by the web prototype (model cm-v2-web1).

    python lutfit_check.py LOOK.json [--lut SOURCE.cube|.xmp] [--model web/model-cm-v2-web1.json] [--tol 0.05] [--gate 0.5]

What it does (read-only, no firmware, nothing is written anywhere):
  1. runs the look-file checker (lookfile/lookfile_check.py);
  2. reads fit.mode / fit.matrix_orf / fit.tone (spec 9c) and checks what the lift needs: 33 knots on x = k/32, |d|,|h| <= 0.4,
     Y + h non-decreasing, F_m + d_c not falling faster than F_m itself, matrix rows sum 256 and |E| < 1024;
  3. re-evaluates the numbers with its own pure-Python copy of the cm-v2-web1 model (public json only) on the synthetic reference
     set ref-syn-1 and reports how far the fitted look moves from the stock mode (model-only, no target needed);
  4. with --lut (the source file whose sha256 is in `source`): recomputes the predicted dE (exposure-matched CIEDE2000, mean over
     scenes) and compares it with `fit.predicted.dE`; the builder's own gate refuses above 0.5 dE, this stub also reports against a
     tight --tol (default 0.05) because both sides use the same model.
Exit code 0: file passes (and, with --lut, the recomputed dE is within --tol); 1: errors or mismatch; 2: usage / unreadable input.
Only `ref-syn-1` pictures can be regenerated; a look scored on a user picture is checked structurally only.
Standard library only (the stub is not fast: ~3-5 s per scoring).
"""
import argparse
import hashlib
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lookfile"))
sys.path.insert(0, os.path.join(HERE, "lutimport"))

W = (0.299, 0.587, 0.114)
KNOWN_MODEL = "cm-v2-web1"


# ---------------------------------------------------------------------------------------------------------------- model
def lerp(v, t):
    t = min(1.0, max(0.0, t))
    s = t * (len(v) - 1)
    i = min(int(s), len(v) - 2)
    return v[i] + (v[i + 1] - v[i]) * (s - i)


def wrap11(v):
    return ((v + 1024) % 2048) - 1024


def inv3(m):
    a, b, c, d, e, f, g, h, i = m
    A, B, C = e * i - f * h, -(d * i - f * g), d * h - e * g
    det = a * A + b * B + c * C
    return [A / det, -(b * i - c * h) / det, (b * f - c * e) / det, B / det, (a * i - c * g) / det, -(a * f - c * d) / det,
            C / det, -(a * h - b * g) / det, (a * e - b * d) / det]


def mm(A, B):
    return [sum(A[i * 3 + k] * B[k * 3 + j] for k in range(3)) for i in range(3) for j in range(3)]


class Model:
    def __init__(self, path):
        with open(path) as fh:
            self.j = json.load(fh)
        self.id = self.j["id"]
        self.Sinv = inv3([wrap11(v) / 256 for v in self.j["stock_orf"]])
        self.Ainv = inv3(self.j["base_model"]["A"])
        self.curve = self.j["base_model"]["curve"]

    def mrel(self, orf):
        return mm([wrap11(v) / 256 for v in orf], self.Sinv)

    def render(self, mode, orf, d=None, h=None, luma="yb"):
        """returns f(x after the stock matrix) -> display RGB, per the model of spec 9c; d = 3 knot lists, h = knot list or None;
        luma 'yb': y = F + d - W.d + h(Yb), Yb = W.F;   'post': y = F + d + h(Y3), Y3 = W.(F + d)"""
        F, P = self.j["modes"][mode]["F"], self.j["modes"][mode]["P"]
        M = self.mrel(orf)

        def run(x):
            xc = [M[i * 3] * x[0] + M[i * 3 + 1] * x[1] + M[i * 3 + 2] * x[2] for i in range(3)]
            u = [v ** (1 / 2.4) if v > 0 else 0.0 for v in xc]
            f = [min(1.0, max(0.0, lerp(F, min(uu, 0.85) / 0.85))) for uu in u]
            y = f
            if d is not None:
                dd = [lerp(d[i], u[i]) for i in range(3)]
                if luma == "post":
                    y3 = min(1.0, max(0.0, W[0] * (f[0] + dd[0]) + W[1] * (f[1] + dd[1]) + W[2] * (f[2] + dd[2])))
                    dy, hh = 0.0, lerp(h, y3)
                else:
                    yb = min(1.0, max(0.0, W[0] * f[0] + W[1] * f[1] + W[2] * f[2]))
                    dy = W[0] * dd[0] + W[1] * dd[1] + W[2] * dd[2]
                    hh = lerp(h, yb)
                y = [min(1.0, max(0.0, f[i] + dd[i] - dy + hh)) for i in range(3)]
            return [min(1.0, max(0.0, P[i * 3] * y[0] + P[i * 3 + 1] * y[1] + P[i * 3 + 2] * y[2])) for i in range(3)]
        return run

    def base_to_x(self, rgb):
        c, nk = self.curve, len(self.curve)
        lin = []
        for v in rgb:
            v = min(1.0, max(0.0, v))
            if v <= c[0]:
                u = 0.0
            elif v >= c[-1]:
                u = 1.0
            else:
                lo, hi = 0, nk - 1
                while hi - lo > 1:
                    mid = (lo + hi) >> 1
                    if c[mid] <= v:
                        lo = mid
                    else:
                        hi = mid
                dd = c[hi] - c[lo]
                u = (lo + ((v - c[lo]) / dd if dd > 0 else 0.0)) / (nk - 1)
            lin.append(u ** 2.4)
        A = self.Ainv
        return [A[i * 3] * lin[0] + A[i * 3 + 1] * lin[1] + A[i * 3 + 2] * lin[2] for i in range(3)]


# --------------------------------------------------------------------------------------------- synthetic set ref-syn-1
def _hsv(h, s, v):
    h = (h % 360) / 60.0
    i = int(h)
    f = h - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i % 6]


def _mix(a, b, t):
    return [a[k] + (b[k] - a[k]) * t for k in range(3)]


def _clamp(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def _patches():
    p = [(v, v, v) for v in (0.04, 0.18, 0.34, 0.5, 0.7, 0.92)]
    p += [_hsv(h, 0.85, 0.8) for h in (0, 30, 60, 120, 190, 235)]
    p += [_hsv(h, 0.4, 0.75) for h in (0, 30, 60, 120, 190, 235)]
    p += [(0.45, 0.31, 0.26), (0.76, 0.58, 0.5), (0.36, 0.48, 0.64), (0.34, 0.42, 0.27), (0.5, 0.41, 0.66), (0.62, 0.36, 0.44)]
    return p


PATCHES = _patches()


def _s_patches(u, v):
    c, r = min(5, int(u * 6)), min(3, int(v * 4))
    inside = 0.06 < u * 6 - c < 0.94 and 0.06 < v * 4 - r < 0.94
    return PATCHES[r * 6 + c] if inside else (0.18, 0.18, 0.18)


def _s_sweep(u, v):
    return _hsv(u * 360, 1 - 0.8 * (v * 2), 0.9) if v < 0.5 else _hsv(u * 360, 0.6, 0.9 - 0.75 * (v * 2 - 1))


def _s_skin(u, v):
    c = _mix((0.36, 0.21, 0.15), (0.96, 0.8, 0.7), u ** 0.9)
    sh, w = 0.5 + 0.55 * (1 - v), (1 - v) * 0.04
    return (_clamp(c[0] * sh + w), _clamp(c[1] * sh + w * 0.5), _clamp(c[2] * sh))


def _s_sky(u, v):
    top, hor = _mix((0.1, 0.3, 0.72), (0.2, 0.36, 0.62), u), _mix((0.74, 0.86, 0.97), (0.82, 0.84, 0.88), u)
    return _mix(top, hor, v ** 1.4)


def _s_foliage(u, v):
    c = _mix((0.58, 0.66, 0.2), (0.09, 0.3, 0.13), u)
    sh = 0.4 + 0.7 * (1 - v)
    return (_clamp(c[0] * sh), _clamp(c[1] * sh), _clamp(c[2] * sh))


def _s_ramps(u, v):
    t = u * 0.96 + 0.02
    tint = (0, 0, 0) if v < 0.34 else (0.05, 0.02, -0.05) if v < 0.67 else (-0.05, 0, 0.06)
    return tuple(_clamp(t + tint[k] * t * (1 - t) * 4) for k in range(3))


SCENES = (("colour patches", _s_patches), ("hue / sat sweep", _s_sweep), ("skin tones", _s_skin),
          ("sky gradient", _s_sky), ("foliage", _s_foliage), ("grey ramps", _s_ramps))


def synth_set(w=64, h=48):
    """[(scene name, [rgb, ...])] as web/refset.js synthDataset (pixel centres)"""
    out = []
    for name, fn in SCENES:
        out.append((name, [fn((x + 0.5) / w, (y + 0.5) / h) for y in range(h) for x in range(w)]))
    return out


# -------------------------------------------------------------------------------------------------------- LUT, Lab, dE
def _srgb_dec(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _srgb_enc(c):
    return 0.0 if c <= 0 else c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


SRGB2XYZ = [0.4124564, 0.3575761, 0.1804375, 0.2126729, 0.7151522, 0.0721750, 0.0193339, 0.1191920, 0.9503041]
BRAD_65_50 = [1.0478112, 0.0228866, -0.0501270, 0.0295424, 0.9904844, -0.0170491, -0.0092345, 0.0150436, 0.7521316]
PP2XYZ50 = [0.7976749, 0.1351917, 0.0313534, 0.2880402, 0.7118741, 0.0000857, 0, 0, 0.8252100]
SRGB_TO_PP = mm(inv3(PP2XYZ50), mm(BRAD_65_50, SRGB2XYZ))
PP_TO_SRGB = mm(inv3(SRGB2XYZ), mm(inv3(BRAD_65_50), PP2XYZ50))


def _cl(v):
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def apply_lut(lut, rgb, space):
    if space == "prophoto":
        lin = [_srgb_dec(_cl(v)) for v in rgb]
        t = [_cl(_srgb_enc(max(0.0, sum(SRGB_TO_PP[i * 3 + j] * lin[j] for j in range(3))))) for i in range(3)]
        u = [_cl(v) for v in lut.sample(*t)]
        lin = [_srgb_dec(v) for v in u]
        return [_cl(_srgb_enc(sum(PP_TO_SRGB[i * 3 + j] * lin[j] for j in range(3)))) for i in range(3)]
    return [_cl(v) for v in lut.sample(*rgb)]


XR, XG, XB, YR, YG, YB, ZR, ZG, ZB = 0.412453, 0.35758, 0.180423, 0.212671, 0.71516, 0.072169, 0.019334, 0.119193, 0.950227


def _f(t):
    return t ** (1 / 3) if t > 0.008856451679035631 else 7.787037037037035 * t + 16 / 116


def rgb2lab(rgb):
    r, g, b = (_srgb_dec(_cl(v)) for v in rgb)
    fx, fy, fz = _f((XR * r + XG * g + XB * b) / 0.95047), _f(YR * r + YG * g + YB * b), _f((ZR * r + ZG * g + ZB * b) / 1.08883)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def de2000(l1, l2):
    L1, a1, b1 = l1
    L2, a2, b2 = l2
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cm7 = ((C1 + C2) / 2) ** 7
    G = 0.5 * (1 - math.sqrt(cm7 / (cm7 + 25.0 ** 7)))
    ap1, ap2 = (1 + G) * a1, (1 + G) * a2
    Cp1, Cp2 = math.hypot(ap1, b1), math.hypot(ap2, b2)
    hp1 = math.atan2(b1, ap1) % (2 * math.pi)
    hp2 = math.atan2(b2, ap2) % (2 * math.pi)
    dL, dC, CC = L2 - L1, Cp2 - Cp1, Cp1 * Cp2
    dh = hp2 - hp1
    if CC == 0:
        dh = 0.0
    elif dh > math.pi:
        dh -= 2 * math.pi
    elif dh < -math.pi:
        dh += 2 * math.pi
    dH = 2 * math.sqrt(CC) * math.sin(dh / 2)
    Lb, Cb = (L1 + L2) / 2, (Cp1 + Cp2) / 2
    if CC == 0:
        hb = hp1 + hp2
    else:
        hb = (hp1 + hp2) / 2
        if abs(hp1 - hp2) > math.pi:
            hb += math.pi if hp1 + hp2 < 2 * math.pi else -math.pi
    T = (1 - 0.17 * math.cos(hb - math.radians(30)) + 0.24 * math.cos(2 * hb) + 0.32 * math.cos(3 * hb + math.radians(6))
         - 0.2 * math.cos(4 * hb - math.radians(63)))
    dth = math.radians(30) * math.exp(-(((math.degrees(hb) - 275) / 25) ** 2))
    Rc = 2 * math.sqrt(Cb ** 7 / (Cb ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lb - 50) ** 2 / math.sqrt(20 + (Lb - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cb, 1 + 0.015 * Cb * T
    Rt = -math.sin(2 * dth) * Rc
    x, y, z = dL / Sl, dC / Sc, dH / Sh
    return math.sqrt(max(0.0, x * x + y * y + z * z + Rt * y * z))


def score(scene_lab_t, scene_lab_o):
    """exposure-matched dE per scene (L* shift by the median difference), mean over scenes; also % < 5"""
    tot, lt5 = 0.0, 0.0
    for lt, lo in zip(scene_lab_t, scene_lab_o):
        dl = sorted(a[0] - b[0] for a, b in zip(lt, lo))
        n = len(dl)
        sh = dl[n // 2] if n % 2 else 0.5 * (dl[n // 2 - 1] + dl[n // 2])
        s = c5 = 0
        for a, b in zip(lt, lo):
            d = de2000(a, (b[0] + sh, b[1], b[2]))
            s += d
            c5 += d < 5
        tot += s / n
        lt5 += c5 / n
    return tot / len(scene_lab_t), 100 * lt5 / len(scene_lab_t)


# ------------------------------------------------------------------------------------------------------------ the check
def fmt(v, n=3):
    return ("%." + str(n) + "f") % v


def knots(pts):
    return [p[1] for p in pts]


def check_fit_structure(model, fit, err, warn):
    """returns (d lists, h list) or (None, None) when there is no tone"""
    mode = fit.get("mode")
    if mode not in model.j["modes"]:
        err("fit.mode %r is not a mode of the model" % mode)
        return None, None
    orf = fit.get("matrix_orf")
    if orf is None:
        warn("no fit.matrix_orf: the builder would use the base candidate's own matrix")
    tone = fit.get("tone")
    if tone is None:
        return None, None
    yc, cc = tone.get("y_curve"), tone.get("c_curves") or {}
    if yc is None or set(cc) != {"r", "g", "b"}:
        err("fit.tone needs y_curve and c_curves r, g, b for the lift")
        return None, None
    grid = [k / 32 for k in range(33)]
    for name, pts in [("y_curve", yc)] + [("c_curves." + k, cc[k]) for k in "rgb"]:
        if len(pts) != 33 or any(abs(p[0] - g) > 1e-9 for p, g in zip(pts, grid)):
            err("fit.tone.%s must have 33 knots at x = k/32" % name)
            return None, None
        if any(abs(p[1]) > 0.4 for p in pts):
            err("fit.tone.%s: |y| > 0.4" % name)
    d, h = [knots(cc[k]) for k in "rgb"], knots(yc)
    worst = 0.0
    for k in range(32):
        worst = max(worst, -((h[k + 1] + grid[k + 1]) - (h[k] + grid[k])))
    if worst > 1e-4:
        err("Y + h(Y) falls by %.5f (the camera's luma table must be non-decreasing)" % worst)
    # F + d_c not falling faster than F itself falls, checked on a 257-point u grid
    F = model.j["modes"][mode]["F"]
    for c in range(3):
        bad = 0.0
        prev = None
        for i in range(257):
            u = i / 256
            f = lerp(F, min(u, 0.85) / 0.85)
            g = f + lerp(d[c], u)
            if prev is not None:
                bad = max(bad, -(g - prev[0]) - max(0.0, -(f - prev[1])))
            prev = (g, f)
        if bad > 1e-4:
            err("F + d_%s falls by %.5f more than F itself (the lift would need a decreasing T3)" % ("rgb"[c], bad))
    return d, h


def main(argv):
    ap = argparse.ArgumentParser(description="stub of the builder's tone-lift gate for a cm-v2-web1 look file (read-only)")
    ap.add_argument("look")
    ap.add_argument("--lut", help="the source .cube / .xmp (its sha256 must equal source.sha256)")
    ap.add_argument("--model", default=os.path.join(HERE, "web", "model-cm-v2-web1.json"))
    ap.add_argument("--tol", type=float, default=0.05)
    ap.add_argument("--gate", type=float, default=0.5)
    a = ap.parse_args(argv)
    try:
        with open(a.look, "rb") as fh:
            raw = fh.read()
        data = json.loads(raw.decode("utf-8"))
        model = Model(a.model)
    except (OSError, ValueError, KeyError) as e:
        print("cannot read input: %s" % e)
        return 2
    import lookfile_check
    rep = lookfile_check.check(data, len(raw))
    bad = len(rep.errors)
    for m in rep.warnings:
        print("lookfile_check warning: %s" % m)
    for m in rep.errors:
        print("lookfile_check ERROR: %s" % m)
    gen = (data.get("generator") or {}).get("model")
    if gen != model.id:
        print("generator.model %r != model %r: the builder would ignore `fit` and refit from the intent" % (gen, model.id))
        return 1
    errors = []
    for i, look in enumerate(data.get("looks", [])):
        tag = "looks[%d] %r" % (i, look.get("name"))
        fit = look.get("fit")
        if not fit:
            print("%s: no fit block (nothing to lift)" % tag)
            continue
        err = lambda m, tag=tag: (errors.append(m), print("%s: ERROR %s" % (tag, m)))
        warn = lambda m, tag=tag: print("%s: warning %s" % (tag, m))
        if fit.get("model") != model.id:
            err("fit.model %r is not %r" % (fit.get("model"), model.id))
            continue
        orf = fit.get("matrix_orf")
        if orf is not None and (len(orf) != 9 or any(abs(v) >= 1024 for v in orf) or any(abs(sum(orf[r * 3:r * 3 + 3]) - 256) > 1 for r in range(3))):
            err("matrix_orf must be 9 ints |v| < 1024 with row sums 256")
            continue
        d, h = check_fit_structure(model, fit, err, warn)
        mode = fit["mode"]
        pred = fit.get("predicted") or {}
        print("%s: mode %s, matrix %s, tone %s, tone_strength %s, predicted dE %s (%s)" % (
            tag, mode, "yes" if orf else "no", "yes" if d else "no", (fit.get("guards") or {}).get("tone_strength", "-"),
            pred.get("dE", "-"), pred.get("scenes", "-")))
        regen = str(pred.get("scenes", "")).startswith("ref-syn-1")
        if not regen:
            print("  scored on %r: not regenerable here, structural checks only" % pred.get("scenes"))
            continue
        base_orf = orf or model.j["stock_orf"]
        cand_name = (look.get("base") or {}).get("candidate", "")
        stock = model.render(mode, model.j["stock_orf"])
        luma = (fit.get("tone") or {}).get("luma_arg", "yb")
        fitted = model.render(mode, base_orf, d, h, luma) if d else model.render(mode, base_orf)
        scenes = synth_set()
        xs = [[model.base_to_x(p) for p in px] for _, px in scenes]
        rgb_f = [[fitted(x) for x in sc] for sc in xs]
        rgb_s = [[stock(x) for x in sc] for sc in xs]
        lab_f = [[rgb2lab(p) for p in sc] for sc in rgb_f]
        lab_s = [[rgb2lab(p) for p in sc] for sc in rgb_s]
        move, _ = score(lab_s, lab_f)
        print("  model-only: the fitted look sits %s dE00 (exposure-matched) away from the stock %s render on ref-syn-1; base candidate %r" % (fmt(move, 2), mode, cand_name))
        if a.lut is None:
            print("  predicted dE not recomputed (pass --lut %s)" % ((look.get("source") or {}).get("name", "SOURCE")))
            continue
        try:
            import import_lut
            r = import_lut.import_any(a.lut)[0]
        except Exception as e:  # noqa: BLE001 - report any importer failure
            err("cannot read --lut: %s" % e)
            continue
        src = look.get("source") or {}
        sha = hashlib.sha256(open(a.lut, "rb").read()).hexdigest()
        if src.get("sha256") and src["sha256"].lower() != sha:
            err("--lut sha256 %s does not equal source.sha256 %s" % (sha[:12], src["sha256"][:12]))
            continue
        space = src.get("space", "display")
        tgt = [[rgb2lab(apply_lut(r.lut33, p, space)) for p in px] for _, px in scenes]
        dE, pct = score(tgt, lab_f)
        dE0, _ = score(tgt, lab_s)
        diff = abs(dE - pred["dE"]) if "dE" in pred else None
        print("  recomputed on ref-syn-1: dE %s, %s %% < 5 (stock %s render alone: %s)" % (fmt(dE), fmt(pct, 1), mode, fmt(dE0)))
        if diff is None:
            warn("no predicted.dE to compare")
        else:
            print("  predicted.dE %s, difference %s; builder gate (> %s refuses): %s; stub tolerance %s: %s" % (
                fmt(pred["dE"]), fmt(diff), a.gate, "PASS" if diff <= a.gate else "REFUSE", a.tol, "ok" if diff <= a.tol else "MISMATCH"))
            if diff > a.tol:
                errors.append("recomputed dE differs from predicted.dE by %s" % fmt(diff))
    print("RESULT: %s" % ("FAIL" if bad or errors else "OK"))
    return 1 if bad or errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
