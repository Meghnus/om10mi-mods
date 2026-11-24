"""lift.py - the "tone lift": cm-v2-web1 tone curves (model domain) -> the camera's T3 (3 x 9) and T2 (256) for one base mode.

The browser fits, in our own model domain, per-channel curves d_c(u) (u = x^(1/2.4)) and a luma lift h. The camera can only carry
T3 per channel on the T1 domain (nine knots at v = k/8, v = T1(g x)) and a luma-only table T2 on the post-T3 luma. This module solves
those tables from the user's own firmware tables (CamTables) so that the exact model reproduces the browser's picture:
  T3_c : least squares over a pixel set of  T3_c(v) = v + d_c(u(x_c)),  v = T1(g x_c)       (monotone, 10 bit)
  T2   : least squares over the same pixels of  T2'(W.pre3) = T2_m(W.pre) + H,  H = the luma lift the model applies to that pixel
         (H = h(Yb) for luma 'yb';  H = l(Y3) + W.d for luma 'post')                          (monotone, 10 bit, 33 knots)
A short Levenberg-Marquardt polish (27 T3 + 33 T2 knot values, finite-difference Jacobian, monotone projection after every step, steps accepted
only when the exact model gets closer to the browser's picture) then removes part of the 9-knot-grid error.
Then the caller re-scores the result with the exact model (build.py). Pure functions; no firmware bytes are stored here.
"""
import numpy as np

from . import camera as K

NK_T2 = 33
LAM = 1e-3          # ridge toward the prior (identity T3 / stock T2) for knots without data
SMOOTH = 1e-3       # second-difference smoothness


class LiftError(ValueError):
    pass


def pav(y, w):
    """weighted non-decreasing isotonic regression (pool adjacent violators)"""
    v, ww, cnt = [], [], []
    for yi, wi in zip(y, w):
        v.append(float(yi))
        ww.append(float(wi))
        cnt.append(1)
        while len(v) > 1 and v[-2] > v[-1]:
            t = ww[-2] + ww[-1]
            v[-2:] = [(v[-2] * ww[-2] + v[-1] * ww[-1]) / t]
            ww[-2:] = [t]
            cnt[-2:] = [cnt[-2] + cnt[-1]]
    out = []
    for vi, c in zip(v, cnt):
        out += [vi] * c
    return np.array(out)


def hat(t, nk):
    """(n, nk) piecewise-linear basis on nk uniform knots over 0..1"""
    s = np.clip(t, 0, 1) * (nk - 1)
    i = np.minimum(s.astype(int), nk - 2)
    w = s - i
    b = np.zeros((len(t), nk))
    b[np.arange(len(t)), i] = 1 - w
    b[np.arange(len(t)), i + 1] = w
    return b


def _knots(t, y, w, prior):
    """weighted LS knots for y ~ B t with a ridge toward `prior` and a smoothness term, then monotone (PAV) and clipped to 0..1"""
    nk = len(prior)
    b = hat(t, nk) * np.sqrt(w)[:, None]
    n = w.sum()
    d2 = np.diff(np.eye(nk), 2, axis=0)
    a = b.T @ b / n + LAM * np.eye(nk) + SMOOTH * d2.T @ d2
    rhs = b.T @ (y * np.sqrt(w)) / n + LAM * prior
    sol = np.linalg.solve(a, rhs)
    return np.clip(pav(sol, np.diag(a)), 0.0, 1.0)


def pixel_set(model, orf_act, xS):
    """pixels (x after the slot matrix) and weights: the scene pixels + axis sweeps that keep every knot constrained"""
    m = model.mrel(orf_act)
    x = xS @ m.T
    t = np.linspace(0, 1, 129) ** 2.4
    sw = [np.stack([t, t, t], -1)]
    for c in range(3):
        for other in (0.02, 0.2):
            p = np.full((129, 3), other)
            p[:, c] = t
            sw.append(p)
    sw = np.concatenate(sw)
    w = np.concatenate([np.ones(len(x)), np.full(len(sw), 0.05 * len(x) / len(sw))])
    return np.concatenate([x, sw]), w


def identity_tone(cam, mode):
    """the stock tone of the mode: T3 identity, T2 = the mode's own luma table (the camera behaves exactly as stock)"""
    t3 = [[int(round(k / 8 * 1023)) for k in range(9)] for _ in range(3)]
    t2 = [int(round(v * 1023)) for v in cam.tab[mode]]
    return t3, t2


def _project(th, nk2):
    t3 = th[:27].reshape(3, 9).copy()
    for c in range(3):
        t3[c] = np.clip(pav(t3[c], np.ones(9)), 0, 1)
    return np.concatenate([t3.ravel(), np.clip(pav(th[27:], np.ones(nk2)), 0, 1)])


def _tables(th, nk2):
    return np.interp(np.arange(256), np.linspace(0, 255, nk2), th[27:]) * 1023.0, th[:27].reshape(3, 9) * 1023.0


def polish_tables(model, cam, mode, x, w, web_lab, t3, t2, nk2=NK_T2, iters=4):
    """LM on the tone knots so that the exact model's Lab picture on the pixel set x (weights w) approaches web_lab(x). Never worse than the start."""
    th = np.concatenate([np.array(t3, float).ravel() / 1023.0, np.array(t2, float)[np.round(np.linspace(0, 255, nk2)).astype(int)] / 1023.0])
    target = web_lab(x)
    sw = np.sqrt(w / w.sum())[:, None]
    P = model.P[mode].T

    def res(t):
        t2n, t3n = _tables(t, nk2)
        return ((K.rgb2lab(np.clip(np.clip(cam.y(x, mode, t2n, t3n), 0, 1) @ P, 0, 1)) - target) * sw).ravel()
    r = res(th)
    cost, lam, start = float((r ** 2).sum()), 1e-2, float((r ** 2).sum())
    for _ in range(iters):
        jac = np.empty((len(r), len(th)))
        for j in range(len(th)):
            t = th.copy()
            t[j] += 1.5e-3
            jac[:, j] = (res(t) - r) / 1.5e-3
        a, g = jac.T @ jac, jac.T @ r
        ok = False
        for _try in range(6):
            cand = _project(th + np.linalg.solve(a + lam * np.diag(np.diag(a) + 1e-9) + 1e-9 * np.eye(len(th)), -g), nk2)
            rc = res(cand)
            cc = float((rc ** 2).sum())
            if cc < cost:
                th, r, cost, lam, ok = cand, rc, cc, max(lam / 3, 1e-6), True
                break
            lam *= 5
        if not ok:
            break
    t2n, t3n = _tables(th, nk2)
    return [[int(v) for v in np.round(t3n[c])] for c in range(3)], [int(v) for v in np.round(t2n)], dict(polish_cost_start=start, polish_cost_end=cost)


def lift_tone(model, cam, mode, orf_act, d33, h33, luma, xS, nk2=NK_T2, polish=4, q33=None):
    """-> (t3 (3 x 9 ints), t2 (256 ints), info). d33: 3 x 33 knots, h33: 33 knots (tone strength already applied). polish = LM iterations (0 = off)."""
    d33, h33 = np.asarray(d33, float), np.asarray(h33, float)
    x, w = pixel_set(model, orf_act, xS)
    u = np.clip(x, 0, None) ** (1 / 2.4)
    pre = cam.pre(x, mode)
    dd = np.stack([K.lerp_knots(d33[c], u[:, c]) for c in range(3)], -1)
    t3 = []
    for c in range(3):
        k = _knots(pre[:, c], pre[:, c] + dd[:, c], w, K.KX)
        t3.append([int(v) for v in np.round(k * 1023)])
    pre3 = cam.t3apply(t3, pre)
    f = model.fm(mode, x)
    if luma == "post":
        hh = K.lerp_knots(h33, np.clip((f + dd) @ K.W, 0, 1)) + dd @ K.W
    elif luma == "yb":
        hh = K.lerp_knots(h33, np.clip(f @ K.W, 0, 1))
        if q33 is not None:     # a shipped-look descriptor (round-trip proof); fits carry no q
            hh = hh + sum(K.lerp_knots(np.asarray(q33[c], float), u[:, c]) for c in range(3))
    else:
        raise LiftError("unknown luma argument %r" % luma)
    t2m = cam.tab[mode]
    target = cam.lut(t2m, pre @ K.W) + hh
    prior = np.interp(np.linspace(0, 1, nk2), K.IDX, t2m)
    knots = _knots(pre3 @ K.W, target, w, prior)
    t2 = np.interp(np.arange(256), np.linspace(0, 255, nk2), knots)
    t2 = [int(v) for v in np.round(np.clip(t2, 0, 1) * 1023)]
    info = dict(luma=luma, t3_rms_d=float(np.sqrt(np.average((pre3 - pre - dd) ** 2, axis=0, weights=w).mean())), pixels=len(x))
    if polish:
        def web_lab(xx):
            return K.rgb2lab(np.clip(np.clip(model.luma_y(xx, d33, h33, mode, luma, q33), 0, 1) @ model.P[mode].T, 0, 1))
        t3, t2, pinfo = polish_tables(model, cam, mode, x, w, web_lab, t3, t2, nk2, polish)
        info.update(pinfo)
    return t3, t2, info
