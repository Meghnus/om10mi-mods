"""camera.py - the two camera models of the builder, numpy.

WebModel  = cm-v2-web1 (public json, our own measured numbers): what the browser fitted and predicted.
CamTables = the exact pc5 model with the USER'S OWN firmware tables read from the image (T1 and the stock luma table T2_m of every
            base mode at pinned addresses): T1 -> T3 (per channel, 3 x 9) -> luma -> T2 (luma only) -> P_m, anchored on F_m so that the
            stock tables reproduce the stock model exactly.   out = P_m clip( F_m(x) + (pre3 - pre) - W.(pre3 - pre) + T2'(W.pre3) - T2_m(W.pre) )
            with pre = T1(g_m x), pre3 = T3(pre).  g_m is the gain that best matches T2_m(T1(g x)) to F_m (computed here, as pc5 does).
Only the tables' ADDRESSES and hashes are in this file; their bytes are read from the user's image at run time and never leave
the machine. Also here: sRGB -> Lab, CIEDE2000 (vectorised, equal to lutfit_check.py to 1e-9), the synthetic reference set ref-syn-1,
the exposure-matched score and the LUT application used to score a target.
"""
import hashlib
import json
import os
import struct

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_MODEL = os.path.join(HERE, "..", "web", "model-cm-v2-web1.json")
W = np.array([0.299, 0.587, 0.114])
KX = np.arange(9) / 8.0
IDX = np.arange(256) / 255.0
P0_BASE = 0x7d991020

# firmware tables the exact model reads (stock p0 addresses; unchanged in the release image): VA and sha256 of the 512 bytes
TABLES = {
    "T1": (0x7df126b8, "3ee0b65a32a24068bbb68882b5ebbef37785bceabd082c48810bfd4c401c2413"),
    "Muted": (0x7df17cc2, "cbfb61b69ed5f06b5805d812457afdda46d81891814694cd0fefa10c1f6bb61d"),
    "Portrait": (0x7df190c2, "a5a48a748cd50de2a161d66e4ae65a5e5c62347cdfe394af38631f733d0266f6"),
    "Vivid": (0x7df178c2, "d149b749e4f584f31d5c3644dd3a4cb2ec97813533605401f88bbccba1df9194"),
    "Natural": (0x7df178c2, "d149b749e4f584f31d5c3644dd3a4cb2ec97813533605401f88bbccba1df9194"),
}


class ModelError(ValueError):
    pass


def wrap11(v):
    return ((np.asarray(v, float) + 1024) % 2048) - 1024


def lerp_knots(v, t):
    """piecewise-linear lookup of the knot vector v (uniform knots on 0..1) at t"""
    v = np.asarray(v, float)
    return np.interp(np.clip(t, 0.0, 1.0), np.linspace(0.0, 1.0, len(v)), v)


class WebModel:
    """cm-v2-web1 (model-cm-v2-web1.json)"""

    def __init__(self, path=WEB_MODEL):
        with open(path, "r", encoding="utf-8") as fh:
            self.j = json.load(fh)
        self.id = self.j["id"]
        self.stock_orf = np.array(self.j["stock_orf"], float)
        self.sinv = np.linalg.inv(wrap11(self.stock_orf).reshape(3, 3) / 256)
        self.F = {m: np.array(v["F"], float) for m, v in self.j["modes"].items()}
        self.P = {m: np.array(v["P"], float).reshape(3, 3) for m, v in self.j["modes"].items()}
        bm = self.j["base_model"]
        self.base_curve = np.array(bm["curve"], float)
        self.base_ainv = np.linalg.inv(np.array(bm["A"], float).reshape(3, 3))
        self.umax = self.j["F_umax"]

    def fm(self, mode, x):
        F = self.F[mode]
        u = np.clip(x, 0, None) ** (1 / 2.4)
        return np.clip(np.interp(np.clip(u, 0, self.umax), np.linspace(0, self.umax, len(F)), F), 0, 1)

    def mrel(self, orf):
        """relative matrix Mrel = wrap11(E)/256 . (S/256)^-1 : x after the stock matrix -> x after the slot matrix"""
        return (wrap11(orf).reshape(3, 3) / 256) @ self.sinv

    def base_to_x(self, rgb):
        """display-referred base picture -> x (camera-linear after the stock matrix), as web/model.js baseToX"""
        u = np.interp(np.clip(rgb, 0, 1), self.base_curve, np.linspace(0, 1, len(self.base_curve)))
        return (u ** 2.4) @ self.base_ainv.T

    def luma_y(self, x, d33, h33, mode, luma="yb", q33=None):
        """pre-P channel values y (before the final clip to 0..1) for x after the slot matrix; d33 = 3 x 33 knots on u, h33 = 33 knots.
        q33 (optional, 'yb' only): 3 x 33 knots of the per-channel luma-lift terms of a shipped-look descriptor, added to h; fits carry none
        luma = 'yb'   : y = F + d - W.d + h(Yb),   Yb = W.F                       (spec 9c, web1)
               'post' : y = F + d + l(Y3),         Y3 = W.(F + d)                 (luma lift on the post-curve luma, as the camera's T2)"""
        u = np.clip(x, 0, None) ** (1 / 2.4)
        f = self.fm(mode, x)
        d = np.stack([lerp_knots(d33[c], u[:, c]) for c in range(3)], -1)
        if luma == "post":
            y3 = np.clip((f + d) @ W, 0, 1)
            return f + d + lerp_knots(h33, y3)[:, None]
        if luma != "yb":
            raise ModelError("unknown luma argument %r" % luma)
        yb = np.clip(f @ W, 0, 1)
        hh = lerp_knots(h33, yb)
        if q33 is not None:
            hh = hh + sum(lerp_knots(q33[c], u[:, c]) for c in range(3))
        return f + d - (d @ W)[:, None] + hh[:, None]

    def out(self, xS, mode, orf, d33=None, h33=None, luma="yb"):
        """camera simulation of pixels xS (x after the stock matrix) -> display RGB"""
        x = xS @ self.mrel(orf).T
        y = self.fm(mode, x) if d33 is None else self.luma_y(x, d33, h33, mode, luma)
        return np.clip(np.clip(y, 0, 1) @ self.P[mode].T, 0, 1)


class CamTables:
    """T1 and the stock luma tables from a main-code partition (plain bytes); verifies their sha256"""

    def __init__(self, p0, model):
        self.model = model
        self.tab = {}
        for name, (va, sha) in TABLES.items():
            raw = bytes(p0[va - P0_BASE:va - P0_BASE + 512])
            if hashlib.sha256(raw).hexdigest() != sha:
                raise ModelError("firmware table %s at %#x is not the one this builder was made for" % (name, va))
            self.tab[name] = np.array(struct.unpack("<256H", raw), float) / 1023.0
        self.t1 = self.tab["T1"]
        self._gain = {}

    @staticmethod
    def lut(t, v):
        return np.interp(np.clip(v, 0, 1), IDX, t)

    def gain(self, mode):
        if mode not in self._gain:
            xs = np.geomspace(1e-3, 0.9, 400)
            f = self.model.fm(mode, xs)
            t2 = self.tab[mode]
            self._gain[mode] = min((float(np.abs(self.lut(t2, self.lut(self.t1, g * xs)) - f).mean()), g) for g in np.linspace(0.6, 1.6, 401))[1]
        return self._gain[mode]

    def pre(self, x, mode):
        return self.lut(self.t1, self.gain(mode) * x)

    @staticmethod
    def t3apply(t3, v):
        t3 = np.asarray(t3, float) / 1023.0
        return np.stack([np.interp(v[..., c], KX, t3[c]) for c in range(3)], -1)

    def y(self, x, mode, t2=None, t3=None):
        """pre-P channel values (before the final clip) for x after the slot matrix; t2 = 256 ints or None (stock), t3 = 3 x 9 ints or None"""
        base = self.model.fm(mode, x)
        pre = self.pre(x, mode)
        pre3 = pre if t3 is None else self.t3apply(t3, pre)
        t2m = self.tab[mode]
        t2n = t2m if t2 is None else np.asarray(t2, float) / 1023.0
        dpre = pre3 - pre
        dy = self.lut(t2n, pre3 @ W) - self.lut(t2m, pre @ W)
        return base + dpre - (dpre @ W)[:, None] + dy[:, None]

    def out(self, xS, mode, orf, t2=None, t3=None):
        x = xS @ self.model.mrel(orf).T
        return np.clip(np.clip(self.y(x, mode, t2, t3), 0, 1) @ self.model.P[mode].T, 0, 1)


# ----------------------------------------------------------------------------------------------------------- colour
def srgb_dec(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb_enc(c):
    c = np.clip(c, 0, None)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


_RGB2XYZ = np.array([[0.412453, 0.35758, 0.180423], [0.212671, 0.71516, 0.072169], [0.019334, 0.119193, 0.950227]])
_WHITE = np.array([0.95047, 1.0, 1.08883])


def rgb2lab(rgb):
    xyz = srgb_dec(np.clip(rgb, 0, 1)) @ _RGB2XYZ.T / _WHITE
    f = np.where(xyz > 0.008856451679035631, np.cbrt(xyz), 7.787037037037035 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], -1)


def de2000(l1, l2):
    """CIEDE2000 (Sharma) between two (n, 3) Lab arrays"""
    L1, a1, b1 = l1[:, 0], l1[:, 1], l1[:, 2]
    L2, a2, b2 = l2[:, 0], l2[:, 1], l2[:, 2]
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    cm7 = ((C1 + C2) / 2) ** 7
    G = 0.5 * (1 - np.sqrt(cm7 / (cm7 + 25.0 ** 7)))
    ap1, ap2 = (1 + G) * a1, (1 + G) * a2
    Cp1, Cp2 = np.hypot(ap1, b1), np.hypot(ap2, b2)
    hp1, hp2 = np.arctan2(b1, ap1) % (2 * np.pi), np.arctan2(b2, ap2) % (2 * np.pi)
    dL, dC, CC = L2 - L1, Cp2 - Cp1, Cp1 * Cp2
    dh = hp2 - hp1
    dh = np.where(CC == 0, 0.0, np.where(dh > np.pi, dh - 2 * np.pi, np.where(dh < -np.pi, dh + 2 * np.pi, dh)))
    dH = 2 * np.sqrt(CC) * np.sin(dh / 2)
    Lb, Cb = (L1 + L2) / 2, (Cp1 + Cp2) / 2
    hb = np.where(CC == 0, hp1 + hp2, np.where(np.abs(hp1 - hp2) > np.pi, (hp1 + hp2) / 2 + np.where(hp1 + hp2 < 2 * np.pi, np.pi, -np.pi), (hp1 + hp2) / 2))
    T = (1 - 0.17 * np.cos(hb - np.radians(30)) + 0.24 * np.cos(2 * hb) + 0.32 * np.cos(3 * hb + np.radians(6)) - 0.2 * np.cos(4 * hb - np.radians(63)))
    dth = np.radians(30) * np.exp(-(((np.degrees(hb) - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cb ** 7 / (Cb ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lb - 50) ** 2 / np.sqrt(20 + (Lb - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cb, 1 + 0.015 * Cb * T
    Rt = -np.sin(2 * dth) * Rc
    x, y, z = dL / Sl, dC / Sc, dH / Sh
    return np.sqrt(np.maximum(0.0, x * x + y * y + z * z + Rt * y * z))


def score(tlab, olab, per):
    """exposure-matched dE (per-scene median L* shift), mean over scenes of the per-scene means; also the mean % < 5.
    tlab / olab: (n_scenes * per, 3) Lab. Returns (dE, pct_lt5, per-scene list)."""
    n = len(tlab) // per
    des, lt5 = [], []
    for s in range(n):
        a, b = tlab[s * per:(s + 1) * per], olab[s * per:(s + 1) * per].copy()
        b[:, 0] += np.median(a[:, 0] - b[:, 0])
        de = de2000(a, b)
        des.append(float(de.mean()))
        lt5.append(float((de < 5).mean()))
    return float(np.mean(des)), 100 * float(np.mean(lt5)), des


# ------------------------------------------------------------------------------------------------------ synthetic set
def synth_base(w=64, h=48):
    """ref-syn-1 display-referred pixels (n_scenes * w * h, 3) and per-scene pixel count; the generator of lutfit_check.py / refset.js"""
    import sys
    lut1 = os.path.normpath(os.path.join(HERE, ".."))
    if lut1 not in sys.path:
        sys.path.insert(0, lut1)
    import lutfit_check as LC
    sc = LC.synth_set(w, h)
    return np.array([p for _, px in sc for p in px], float), len(sc[0][1]), [n for n, _ in sc]


# ---------------------------------------------------------------------------------------------------------- the LUT
_SRGB2XYZ = np.array([0.4124564, 0.3575761, 0.1804375, 0.2126729, 0.7151522, 0.0721750, 0.0193339, 0.1191920, 0.9503041]).reshape(3, 3)
_BRAD = np.array([1.0478112, 0.0228866, -0.0501270, 0.0295424, 0.9904844, -0.0170491, -0.0092345, 0.0150436, 0.7521316]).reshape(3, 3)
_PP2XYZ50 = np.array([0.7976749, 0.1351917, 0.0313534, 0.2880402, 0.7118741, 0.0000857, 0, 0, 0.8252100]).reshape(3, 3)
_S2PP = np.linalg.inv(_PP2XYZ50) @ _BRAD @ _SRGB2XYZ
_PP2S = np.linalg.inv(_SRGB2XYZ) @ np.linalg.inv(_BRAD) @ _PP2XYZ50


def lut_sample(lut, rgb):
    """trilinear lookup of a lutcore.Lut (flat .cube order, red fastest) for (n, 3) rgb"""
    n = lut.n
    D = np.asarray(lut.data, float).reshape(n, n, n, 3)          # [b][g][r]
    p = np.clip(rgb, 0, 1) * (n - 1)
    i0 = np.minimum(p.astype(int), n - 2)
    f = p - i0
    r0, g0, b0 = i0[:, 0], i0[:, 1], i0[:, 2]
    fr, fg, fb = f[:, 0:1], f[:, 1:2], f[:, 2:3]

    def at(dr, dg, db):
        return D[b0 + db, g0 + dg, r0 + dr]
    c00 = at(0, 0, 0) * (1 - fr) + at(1, 0, 0) * fr
    c10 = at(0, 1, 0) * (1 - fr) + at(1, 1, 0) * fr
    c01 = at(0, 0, 1) * (1 - fr) + at(1, 0, 1) * fr
    c11 = at(0, 1, 1) * (1 - fr) + at(1, 1, 1) * fr
    return np.clip((c00 * (1 - fg) + c10 * fg) * (1 - fb) + (c01 * (1 - fg) + c11 * fg) * fb, 0, 1)


def lut_apply(lut, rgb, space="display"):
    if space == "prophoto":
        lin = srgb_dec(rgb)
        t = np.clip(srgb_enc(np.clip(lin @ _S2PP.T, 0, None)), 0, 1)
        u = lut_sample(lut, t)
        return np.clip(srgb_enc(srgb_dec(u) @ _PP2S.T), 0, 1)
    return lut_sample(lut, rgb)
