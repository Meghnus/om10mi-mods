"""composed.py - the slot-matrix rules of the local builder (stdlib only), a port of web/composed.js (which is a 1:1 port of olylook).

A slot matrix is stored as 9 signed 16-bit cave constants L16; the camera composes them with its own stored matrix A (>> 8) and
normalises the result into the 11-bit ORF 0x0200 coefficients. The builder refuses any L16 whose composed coefficient reaches 1024
(the 11-bit wrap) for any measured A variant or a +-64 row-sum sweep of them.
  solve_l(E)       integer cave constants whose predicted ORF matrix is closest to E (E = 9 ints, rows sum 256)
  orf_pred(L, A)   the ORF matrix the camera applies for L16 and A (A = the camera's own matrix, default the stock one)
  composed_max(L)  worst composed |c| (check_matrix); must be < 1024
The integers below are measured normaliser inputs (numbers of behaviour, not firmware tables), as in web/composed.js.
"""
import itertools

A_STOCK = [223, -90, -5, -28, 174, -18, 10, -52, 170]
A_OFF = [[-90, -5, -28, -18, 10, -52], [-90, -5, -27, -19, 9, -48]]     # manual lens, AF-lens bank
A_DIAG = [[194, 225], [172, 175], [167, 172]]
LIMIT = 1024


def compose(L, m):
    return [(L[3 * i] * m[j] + L[3 * i + 1] * m[3 + j] + L[3 * i + 2] * m[6 + j]) >> 8 for i in range(3) for j in range(3)]


def norm128(m):
    o = list(m)
    o[1] &= ~1
    o[0] = 128 - o[1] - o[2]
    if (o[3] + o[5]) & 2:
        o[3] &= ~1
        o[5] &= ~1
    o[4] = 128 - o[3] - o[5]
    o[7] &= ~1
    o[8] = 128 - o[6] - o[7]
    return o


def orf_pred(L, A=A_STOCK):
    return [2 * v for v in norm128(compose(L, A))]


def _inv3(m):
    a, b, c, d, e, f, g, h, i = m
    A, B, C = e * i - f * h, -(d * i - f * g), d * h - e * g
    det = a * A + b * B + c * C
    return [A / det, -(b * i - c * h) / det, (b * f - c * e) / det, B / det, (a * i - c * g) / det, -(a * f - c * d) / det,
            C / det, -(a * h - b * g) / det, (a * e - b * d) / det]


_AINV = _inv3(A_STOCK)


def _round_even(v):
    return round(v)         # Python rounds half to even, like numpy.round


def solve_l(E):
    L = [_round_even(256 * ((E[i * 3] / 2) * _AINV[j] + (E[i * 3 + 1] / 2) * _AINV[3 + j] + (E[i * 3 + 2] / 2) * _AINV[6 + j]))
         for i in range(3) for j in range(3)]

    def err(Lv):
        p = orf_pred(Lv)
        return sum(abs(p[k] - E[k]) for k in range(9))
    cur = err(L)
    for _ in range(4):
        improved = False
        for k in range(9):
            for dv in (-2, -1, 1, 2):
                Lt = list(L)
                Lt[k] += dv
                e = err(Lt)
                if e < cur:
                    L, cur, improved = Lt, e, True
        if not improved:
            break
    return L


def _max_abs(v):
    return max(abs(x) for x in v)


def composed_max_l(L):
    worst = 0
    for o in A_OFF:
        rs = [128 - o[0] - o[1], 128 - o[2] - o[3], 128 - o[4] - o[5]]
        for d in itertools.product(*[(v - 64, v, v + 64) for v in rs]):
            worst = max(worst, _max_abs(orf_pred(L, [d[0], o[0], o[1], o[2], d[1], o[3], o[4], o[5], d[2]])))
    for o in A_OFF:
        for d in itertools.product(*A_DIAG):
            worst = max(worst, _max_abs(orf_pred(L, [d[0], o[0], o[1], o[2], d[1], o[3], o[4], o[5], d[2]])))
        worst = max(worst, _max_abs(orf_pred(L, [128 - o[0] - o[1], o[0], o[1], o[2], 128 - o[2] - o[3], o[3], o[4], o[5], 128 - o[4] - o[5]])))
    return worst


def composed_max(E):
    return composed_max_l(solve_l(E))
