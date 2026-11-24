"""icons88.py - the universal film-roll icon of an imported look (no text), written into the slot's own two icon images (stdlib only).

Every look slot owns one unselected (U) and one selected (S) image id; both are named by the same nine icon fields of the picture-mode
tables (info, scpa, lca, a35, lvimg, iconT = U; scpb, lcb, b35 = S). Each image is 44x32, 8 bpp, type 14, key 0 in the image table of
partition 1; its 24-byte header (size = the capacity of the slot, data VA) is never touched, only the data bytes behind `df` are rewritten.
Own artwork (the silhouette of the shipped look icons without the label band), own codec; the palette INDEX numbers are numbers, not bitmaps.

Stream rules (the proof of b88 / lut8_REPORT): token = colour<<2 | (run-1), run 1..4, six 10-bit tokens per 64-bit LE block, the decoder stops at
w*h = 1408 pixels. The blob is filled to the exact capacity by splitting runs when that size is reachable (545, 1129, 1164, 1216, 1254, 1526, ...);
when it is not (610 B, and the 1988 / 2092 B slots whose maximum stream is 1881 B) the largest reachable stream <= min(capacity, 1881) is written and
the rest of the capacity is ZERO bytes (colour-0 tokens that the stop-at-w*h rule never reads: the same tail the field-proven Portra icon has).
`check_icons` re-reads a built image and proves: header unchanged-by-shape, decode == the design pixel-exact, zero tail, own ids unique, no other
image-table entry aliases the written data or header.
"""
import struct

W, H = 44, 32
NPIX = W * H
GRAD = [103, 87, 88, 90, 91, 92, 94, 95, 96]
WHITE = 22
IMG_TABLE_F = 0x3b2644
N_IMAGES = 3272
ARENAS = ((0xbf06a000, 0x7e0, 0x3d8820), (0xbf46a000, 0x9385e0, 0x39a620))     # (VA, file offset, length) of the two image arenas of p1
P0_BASE = 0x7d991020
# the nine icon fields: anchor = the id word of the row of picture-mode value 37, record stride, role
FIELDS = {"info": (0x7d9ba10a, 12, "U"), "scpa": (0x7d9ba2ca, 12, "U"), "lca": (0x7d9ba692, 12, "U"), "scpb": (0x7d9ba4ae, 12, "S"),
          "lcb": (0x7d9ba876, 12, "S"), "a35": (0x7d9bb190, 8, "U"), "b35": (0x7d9bb2d8, 8, "S"), "lvimg": (0x7e5b6cec, 8, "U"),
          "iconT": (0x7d9baffc, 4, "U")}
ICONT_BASE = 0x7d9bafc0


class IconError(ValueError):
    pass


def _max_stream():
    toks = NPIX                                   # one pixel per token = the longest possible stream
    k, r = divmod(toks, 6)
    return 4 + 8 * k + ((10 * r + 7) // 8 if r else 0)


MAX_STREAM = _max_stream()                        # 1881


def pm_value(s):
    return s + 21 if s <= 14 else s + 22


# ------------------------------------------------------------------------------------------------ design
def design(kind):
    """the universal roll: tab + lip + body silhouette of the shipped look icons, no label. kind 'U' (white) or 'S' (focus gradient)"""
    px = [0] * NPIX

    def rect(x0, y0, x1, y1):
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                px[y * W + x] = WHITE
    rect(16, 6, 27, 15)
    rect(14, 6, 29, 7)
    rect(20, 3, 26, 5)
    if kind == "U":
        return px
    rows = [y for y in range(H) if any(px[y * W:(y + 1) * W])]
    t, b = min(rows), max(rows)
    out = []
    for y in range(H):
        g = GRAD[min(8, (y - t) * 9 // (b - t + 1))] if y <= b else 91
        out += [g if v else 0 for v in px[y * W:(y + 1) * W]]
    return out


# ------------------------------------------------------------------------------------------------ codec
def _tokens(px):
    toks = []
    for y in range(H):
        row = px[y * W:(y + 1) * W]
        i = 0
        while i < W:
            v = row[i]
            j = i + 1
            while j < W and row[j] == v and j - i < 4:
                j += 1
            toks.append((v, j - i))
            i = j
    return toks


def _pack(toks):
    out = bytearray()
    for k6 in range(0, len(toks), 6):
        grp = toks[k6:k6 + 6]
        blk = 0
        for k, (v, n) in enumerate(grp):
            blk |= ((v << 2) | (n - 1)) << (10 * k)
        out += blk.to_bytes(min(8, (len(grp) * 10 + 7) // 8), "little")
    return bytes(out)


def _reachable(body):
    """stream body length (head excluded) -> token count, or None"""
    k, rem = divmod(body, 8)
    if rem == 0:
        return 6 * k
    for r in range(1, 6):
        if 8 * k + (10 * r + 7) // 8 == body:
            return 6 * k + r
    return None


def _pad(toks, want):
    out = list(toks)
    i = 0
    while len(out) < want:
        while i < len(out) and out[i][1] == 1:
            i += 1
        if i >= len(out):
            raise IconError("no splittable run left")
        v, n = out[i]
        out[i:i + 1] = [(v, 1), (v, n - 1)]
    return out


def encode(px, size):
    """exactly `size` bytes of 8 bpp stream (4 B head included)"""
    n = _reachable(size - 4)
    toks = _tokens(px)
    if n is None or n < len(toks) or n > NPIX:
        raise IconError("size %d is not reachable for this icon" % size)
    data = bytes([(H - 1) & 255, ((H - 1) >> 8) | (((W - 1) & 0xF) << 4), ((W - 1) >> 4) & 255, 3]) + _pack(_pad(toks, n))
    if len(data) != size:
        raise IconError("internal size mismatch")
    return data


def blob(px, cap):
    """-> (bytes of length cap, stream length): exact fill when reachable, else the largest reachable stream <= min(cap, MAX_STREAM) + zero tail"""
    need = 4 + len(_pack(_tokens(px)))
    for size in range(min(cap, MAX_STREAM), need - 1, -1):
        try:
            return encode(px, size) + b"\0" * (cap - size), size
        except IconError:
            continue
    raise IconError("the icon needs %d B, the slot holds %d" % (need, cap))


def decode(raw):
    """-> (pixels, bytes consumed, w, h); stops at w*h pixels like the engine; consumed counts whole 64-bit blocks' used bytes"""
    raw = bytes(raw)
    h = (raw[0] | ((raw[1] & 0xF) << 8)) + 1
    w = ((raw[1] >> 4) | (raw[2] << 4)) + 1
    if raw[3] != 3:
        raise IconError("not an 8 bpp stream")
    px = []
    ntok = 0
    for p in range(4, len(raw), 8):
        chunk = raw[p:p + 8]
        blk = int.from_bytes(chunk, "little")
        for k in range(len(chunk) * 8 // 10):
            t = (blk >> (10 * k)) & 0x3FF
            px.extend([t >> 2] * ((t & 3) + 1))
            ntok += 1
            if len(px) >= w * h:
                k6, r = divmod(ntok, 6)
                return px[:w * h], 4 + 8 * k6 + ((10 * r + 7) // 8 if r else 0), w, h
    raise IconError("stream ends before w*h pixels")


# ------------------------------------------------------------------------------------------------ image table / fields
def _va2f(va):
    for b, f, ln in ARENAS:
        if b <= va < b + ln:
            return va - b + f
    return None


def header(p1, iid):
    if not 0 < iid < N_IMAGES:
        raise IconError("image id %d out of range" % iid)
    va = struct.unpack_from("<I", p1, IMG_TABLE_F + 4 * iid)[0]
    f = _va2f(va)
    if f is None:
        raise IconError("image id %d: header outside the arenas" % iid)
    t, w, h, bpp, fl, z, size, dva, key = struct.unpack_from("<6HIII", p1, f)
    df = _va2f(dva)
    if df is None:
        raise IconError("image id %d: data outside the arenas" % iid)
    return dict(id=iid, hf=f, type=t, w=w, h=h, bpp=bpp, flags=fl, size=size, df=df, key=key)


def fields(p0, s):
    """{field: (id, value key)} of slot s"""
    v = pm_value(s)
    out = {}
    for f, (a37, st, role) in FIELDS.items():
        if f == "iconT":
            va = ICONT_BASE + 4 * (v - 22)
            out[f] = (struct.unpack_from("<I", p0, va - P0_BASE)[0], None)
            continue
        if f == "lvimg":
            va = a37 - st * (37 - v) if v <= 36 else a37 + st * (v - 37)
        else:
            va = a37 - st * (36 - v) if v <= 35 else a37 + st * (v - 37)
        if st == 12:
            out[f] = (struct.unpack_from("<H", p0, va - P0_BASE)[0], struct.unpack_from("<I", p0, va - 6 - P0_BASE)[0])
        else:
            out[f] = (struct.unpack_from("<I", p0, va - P0_BASE)[0], struct.unpack_from("<I", p0, va - 4 - P0_BASE)[0])
    return out


def ids_of(p0, s):
    """(U id, S id) of slot s; the nine fields must agree and carry the slot's picture-mode value"""
    d = fields(p0, s)
    U = {d[f][0] for f in d if FIELDS[f][2] == "U"}
    S = {d[f][0] for f in d if FIELDS[f][2] == "S"}
    keys = {d[f][1] for f in d if d[f][1] is not None}
    if len(U) != 1 or len(S) != 1 or keys != {pm_value(s)}:
        raise IconError("slot %d: the icon fields do not name one U and one S id (U %s, S %s, keys %s)" % (s, sorted(U), sorted(S), sorted(keys)))
    return U.pop(), S.pop()


def _check_header(h):
    if (h["type"], h["w"], h["h"], h["bpp"], h["flags"], h["key"]) != (14, W, H, 8, 0, 0):
        raise IconError("image %d: header is not type 14, 44x32, 8 bpp, flags 0, key 0 (%s)" % (h["id"], {k: h[k] for k in ("type", "w", "h", "bpp", "flags", "key")}))
    if h["size"] < 480:
        raise IconError("image %d: capacity %d B is too small for the roll" % (h["id"], h["size"]))


def sites(p0, p1, s):
    """[(p1 file offset, capacity, note)] the two data ranges of slot s's icons"""
    out = []
    for kind, iid in zip("US", ids_of(p0, s)):
        h = header(p1, iid)
        _check_header(h)
        out.append((h["df"], h["size"], "icon %s id %d slot %d" % (kind, iid, s)))
    return out


def alias_problems(p1, iids):
    """no other image-table entry may share the header or overlap the data of the written ids"""
    ranges = {}
    for i in range(1, N_IMAGES):
        va = struct.unpack_from("<I", p1, IMG_TABLE_F + 4 * i)[0]
        f = _va2f(va)
        if f is None:
            continue
        t, w, h, bpp, fl, z, size, dva, key = struct.unpack_from("<6HIII", p1, f)
        df = _va2f(dva)
        ranges[i] = (f, df, size)
    bad = []
    for x in iids:
        hf, df, size = ranges[x]
        for i, (f, d, sz) in ranges.items():
            if i == x:
                continue
            if f == hf or (d is not None and df is not None and d < df + size and df < d + sz):
                bad.append((x, i))
    return bad


def write(p0, p1, s):
    """rewrite the universal roll into slot s's U and S images of the bytearray p1; returns [(offset, length, note)] and the stream info"""
    written, info = [], []
    for (df, cap, note), kind in zip(sites(p0, p1, s), "US"):
        data, used = blob(design(kind), cap)
        p1[df:df + cap] = data
        written.append((df, cap, note))
        info.append((kind, cap, used, cap - used))
    bad = alias_problems(p1, ids_of(p0, s))
    if bad:
        raise IconError("slot %d: the icon images alias other image-table entries %s: not written" % (s, bad[:4]))
    return written, info


def check(p0, p1, s, ids=None):
    """-> list of (name, ok, detail) proofs on an image: decode == design pixel-exact, zero tail, header shape, ids own.
    ids = (U, S) when the caller knows them (an image whose Picture Mode rows were reordered no longer has the base row positions the field formulas assume)"""
    res = []
    try:
        U, S = ids if ids else ids_of(p0, s)
    except IconError as e:
        return [("icon fields of slot %d" % s, False, str(e))]
    for kind, iid in (("U", U), ("S", S)):
        h = header(p1, iid)
        okh = (h["type"], h["w"], h["h"], h["bpp"], h["flags"], h["key"]) == (14, W, H, 8, 0, 0)
        raw = bytes(p1[h["df"]:h["df"] + h["size"]])
        try:
            px, used, _, _ = decode(raw)
            exact = px == design(kind)
            tail = not any(raw[used:])
        except IconError as e:
            exact, tail, used = False, False, 0
        res.append(("icon %s id %d: header 44x32 8bpp, decode == design pixel-exact, zero tail" % (kind, iid), okh and exact and tail,
                    "capacity %d B, stream %d B, tail %d B zero" % (h["size"], used, h["size"] - used) if exact and tail else "header %s, exact %s, tail zero %s" % (okh, exact, tail)))
    bad = alias_problems(p1, (U, S))
    res.append(("icon images of slot %d are not aliased by any other image-table entry" % s, not bad, str(bad[:4]) if bad else "%d entries compared" % (N_IMAGES - 3)))
    return res
