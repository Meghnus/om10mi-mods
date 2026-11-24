"""lutcore.py - the common 3D LUT container of the om10mi LUT importers (stdlib only).

A Lut is an n x n x n table of RGB triples in [0, 1] (display-referred unless the importer says otherwise),
stored flat in .cube order: index = (r + g*n + b*n*n) * 3, red fastest. All importers end here; the
common working size is 33 (COMMON_N). Trilinear interpolation everywhere, as the .cube / HaldCLUT
consumers do (RawTherapee's HaldCLUT and the .cube convention are both trilinear in red, green, blue).

Own code, Apache-2.0 like the rest of the public look-file tooling. No firmware data.
"""
import math

COMMON_N = 33


class LutError(ValueError):
    pass


class Lut:
    __slots__ = ("n", "data")

    def __init__(self, n, data):
        if n < 2 or len(data) != n * n * n * 3:
            raise LutError("LUT size %d needs %d values, got %d" % (n, n ** 3 * 3, len(data)))
        self.n = n
        self.data = data

    # -- constructors -------------------------------------------------------------------------
    @classmethod
    def identity(cls, n=COMMON_N):
        d = []
        s = 1.0 / (n - 1)
        for b in range(n):
            for g in range(n):
                for r in range(n):
                    d += [r * s, g * s, b * s]
        return cls(n, d)

    @classmethod
    def from_function(cls, fn, n=COMMON_N):
        """fn(r, g, b) -> (r, g, b) on the lattice; results are clipped to 0..1."""
        d = []
        s = 1.0 / (n - 1)
        for b in range(n):
            for g in range(n):
                for r in range(n):
                    o = fn(r * s, g * s, b * s)
                    d += [min(1.0, max(0.0, o[0])), min(1.0, max(0.0, o[1])), min(1.0, max(0.0, o[2]))]
        return cls(n, d)

    # -- access ---------------------------------------------------------------------------------
    def node(self, r, g, b):
        i = (r + g * self.n + b * self.n * self.n) * 3
        return self.data[i], self.data[i + 1], self.data[i + 2]

    def sample(self, r, g, b):
        """Trilinear lookup; inputs clamped to 0..1."""
        n = self.n
        m = n - 1
        out = [0.0, 0.0, 0.0]
        fr = min(1.0, max(0.0, r)) * m
        fg = min(1.0, max(0.0, g)) * m
        fb = min(1.0, max(0.0, b)) * m
        r0 = min(int(fr), m - 1)
        g0 = min(int(fg), m - 1)
        b0 = min(int(fb), m - 1)
        dr, dg, db = fr - r0, fg - g0, fb - b0
        d = self.data
        base = (r0 + g0 * n + b0 * n * n) * 3
        sr, sg, sb = 3, 3 * n, 3 * n * n
        for c in range(3):
            c000 = d[base + c]
            c100 = d[base + sr + c]
            c010 = d[base + sg + c]
            c110 = d[base + sr + sg + c]
            c001 = d[base + sb + c]
            c101 = d[base + sr + sb + c]
            c011 = d[base + sg + sb + c]
            c111 = d[base + sr + sg + sb + c]
            x00 = c000 + (c100 - c000) * dr
            x10 = c010 + (c110 - c010) * dr
            x01 = c001 + (c101 - c001) * dr
            x11 = c011 + (c111 - c011) * dr
            y0 = x00 + (x10 - x00) * dg
            y1 = x01 + (x11 - x01) * dg
            out[c] = y0 + (y1 - y0) * db
        return out[0], out[1], out[2]

    def resample(self, n_out=COMMON_N):
        """Re-lattice to n_out nodes per axis by trilinear lookup (identity when the size already matches)."""
        if n_out == self.n:
            return Lut(self.n, list(self.data))
        d = []
        s = 1.0 / (n_out - 1)
        for b in range(n_out):
            for g in range(n_out):
                for r in range(n_out):
                    d += self.sample(r * s, g * s, b * s)
        return Lut(n_out, d)

    def apply(self, rgb):
        return self.sample(rgb[0], rgb[1], rgb[2])

    def clipped(self):
        return Lut(self.n, [min(1.0, max(0.0, v)) for v in self.data])

    def max_abs_diff(self, other):
        if self.n != other.n:
            raise LutError("size mismatch %d vs %d" % (self.n, other.n))
        return max(abs(a - b) for a, b in zip(self.data, other.data))

    def is_identity(self, tol=1e-6):
        return self.max_abs_diff(Lut.identity(self.n)) <= tol

    def stats(self):
        """Small summary used by the importers' reports."""
        ident = Lut.identity(self.n)
        diffs = [abs(a - b) for a, b in zip(self.data, ident.data)]
        return {"n": self.n, "max_dev_from_identity": max(diffs),
                "mean_dev_from_identity": sum(diffs) / len(diffs),
                "min": min(self.data), "max": max(self.data)}


# ------------------------------------------------------------------------------------------------
# .cube
# ------------------------------------------------------------------------------------------------
def parse_cube(text):
    """Parse the text of an Adobe/Iridas .cube 3D LUT. Returns (title, Lut) with the domain normalised to 0..1.

    Accepts TITLE, LUT_3D_SIZE, DOMAIN_MIN, DOMAIN_MAX, comments (#) and blank lines. 1D LUTs and
    LUT_1D_INPUT_RANGE are refused (a 1D shaper in front of a 3D table would need composing, which a
    silent import must not guess).
    """
    size = None
    title = ""
    dmin = [0.0, 0.0, 0.0]
    dmax = [1.0, 1.0, 1.0]
    vals = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        up = line.upper()
        if up.startswith("TITLE"):
            q = line.split(None, 1)
            title = q[1].strip().strip('"') if len(q) > 1 else ""
            continue
        if up.startswith("LUT_3D_SIZE"):
            size = int(line.split()[1])
            continue
        if up.startswith("LUT_1D") or up.startswith("LUT_3D_INPUT_RANGE"):
            raise LutError("1D LUTs / LUT_*_INPUT_RANGE are not supported (%s)" % line.split()[0])
        if up.startswith("DOMAIN_MIN"):
            dmin = [float(x) for x in line.split()[1:4]]
            continue
        if up.startswith("DOMAIN_MAX"):
            dmax = [float(x) for x in line.split()[1:4]]
            continue
        p = line.split()
        if len(p) == 3:
            try:
                vals.append((float(p[0]), float(p[1]), float(p[2])))
            except ValueError:
                raise LutError("unreadable line: %r" % line[:60])
        else:
            raise LutError("unknown keyword or malformed line: %r" % line[:60])
    if size is None:
        raise LutError("LUT_3D_SIZE not found")
    if size < 2 or size > 256:
        raise LutError("LUT_3D_SIZE %d out of range" % size)
    if len(vals) != size ** 3:
        raise LutError("expected %d entries, got %d" % (size ** 3, len(vals)))
    flat = []
    for v in vals:
        flat += [v[0], v[1], v[2]]
    if dmin != [0.0, 0.0, 0.0] or dmax != [1.0, 1.0, 1.0]:
        # DOMAIN_* is the INPUT range the lattice spreads over: input x maps to lattice position
        # t = (x - dmin) / (dmax - dmin), clamped. Rebuild the table on a plain 0..1 lattice
        # (at least 33 nodes, so a narrow domain is not undersampled).
        raw_lut = Lut(size, flat)
        m = max(size, COMMON_N)
        s = 1.0 / (m - 1)
        out = []
        for b in range(m):
            for g in range(m):
                for r in range(m):
                    t = [(c * s - dmin[i]) / (dmax[i] - dmin[i]) if dmax[i] != dmin[i] else 0.0
                         for i, c in enumerate((r, g, b))]
                    out += raw_lut.sample(*[min(1.0, max(0.0, v)) for v in t])
        return title, Lut(m, out)
    return title, Lut(size, flat)


def read_cube(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return parse_cube(fh.read())


def format_cube(lut, title="", comment=""):
    lines = []
    if comment:
        lines.append("# " + comment)
    if title:
        lines.append('TITLE "%s"' % title.replace('"', "'"))
    lines.append("LUT_3D_SIZE %d" % lut.n)
    lines.append("DOMAIN_MIN 0.0 0.0 0.0")
    lines.append("DOMAIN_MAX 1.0 1.0 1.0")
    d = lut.data
    for i in range(0, len(d), 3):
        lines.append("%.6f %.6f %.6f" % (d[i], d[i + 1], d[i + 2]))
    return "\n".join(lines) + "\n"


def write_cube(path, lut, title="", comment=""):
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        fh.write(format_cube(lut, title, comment))


# ------------------------------------------------------------------------------------------------
# colour helpers shared by the importers and the renderer (sRGB transfer, HSV, Oklab)
# ------------------------------------------------------------------------------------------------
def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c):
    if c <= 0.0:
        return 0.0
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def rgb_to_hsv(r, g, b):
    """h in degrees 0..360, s and v in 0..1 (on whatever the inputs are, clipped inputs expected)."""
    mx = max(r, g, b)
    mn = min(r, g, b)
    d = mx - mn
    if d <= 1e-12:
        h = 0.0
    elif mx == r:
        h = (60.0 * ((g - b) / d)) % 360.0
    elif mx == g:
        h = 60.0 * ((b - r) / d) + 120.0
    else:
        h = 60.0 * ((r - g) / d) + 240.0
    s = 0.0 if mx <= 1e-12 else d / mx
    return h % 360.0, s, mx


def hsv_to_rgb(h, s, v):
    h = (h % 360.0) / 60.0
    i = int(math.floor(h)) % 6
    f = h - math.floor(h)
    p = v * (1 - s)
    q = v * (1 - s * f)
    t = v * (1 - s * (1 - f))
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][i]


def smoothstep(e0, e1, x):
    if e1 == e0:
        return 0.0 if x < e0 else 1.0
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


LUMA = (0.2126, 0.7152, 0.0722)


def luma(r, g, b):
    return LUMA[0] * r + LUMA[1] * g + LUMA[2] * b
