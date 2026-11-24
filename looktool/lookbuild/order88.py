"""order88.py - reorder and hide the Picture Mode list of the 18-look layout (z26 / z27 / z28), data only, stdlib only.

Layout facts only (addresses, strides, counts); no firmware bytes are stored here. VA = flash virtual address, p0 file offset = VA - P0_BASE.

What the order is made of (every list below was classified from the image):
  ORDER-bearing lists  (rows move whole, in step with the display order; 18 regions)
    service map   tblA records + tblB values (desc 111: dial / arrow stepping, index-of, set-index), enable map, title table,
    menu page 1, SCP picker A/B, LC icon A/B, LC text, RAW-strip icon lists A35/B35, strip caption list L35, strip label table
    LABELS36 (indexed by strip POSITION), RAW-strip value maps 505 / 506 (records + tblB, ORDER indexed)
  value / selector keyed lists with their own order (info, jt, jump-S, iconT, PM-cell T, LV image + ordinal, scf, rules arrays,
    SEL2REC, LOOKBASE, cc2 lists, per-look page rows, ...) are NOT touched; verify() proves they stay byte-identical.
HIDE (stage A) = the look keeps every row that a stored RAW / Myset / RAW Data Edit needs (enable, title, info, icons, loader jt,
    maps 505/506, A35/B35/L35/LABELS36, selector data) but leaves the shooting-UI lists: its rows are moved behind the list
    COUNT of the service map (tblA/tblB), menu, SCP A/B, LC A/B and LC text, and those count words shrink. Dial stepping,
    the menu, SCP and LC therefore never see it. Only counts and the row order of existing lists change: no new space.
Own code, Apache-2.0.
"""
import struct

P0_BASE = 0x7d991020
NSLOT = 18

STOCK = ("Vivid", "Natural", "Muted", "Portrait", "Monotone", "Custom", "e-Portrait", "Color Creator") + tuple("ART%d" % i for i in range(1, 13))
_STOCK_VALUE = {"Vivid": 0, "Natural": 1, "Muted": 2, "Portrait": 5, "Monotone": 3, "Custom": 6, "e-Portrait": 20, "Color Creator": 21}
_STOCK_VALUE.update({"ART%d" % i: 7 + i for i in range(1, 13)})
ITEMS = tuple(range(1, NSLOT + 1)) + STOCK
IENHANCE, SPARE_VALUE = 7, 36


def look_value(s):
    """GUI picture-mode value of look slot s: 22..35 for slots 1..14, 37..40 for 15..18 (36 is the spare record)"""
    return s + 21 if s <= 14 else s + 22


VALUE_OF = {s: look_value(s) for s in range(1, NSLOT + 1)}
VALUE_OF.update(_STOCK_VALUE)
ITEM_OF = {v: k for k, v in VALUE_OF.items()}
N_VALUES = len(ITEMS) + 1          # 38 items + i-Enhance = 39 values in the menu lists


class OrderError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ layout facts
DESC111, DESC505, DESC506 = 0x7dc47dcc, 0x7dc48038, 0x7dc4804c
TBLA, TBLB = 0x7d9b9820, 0x7d9b9a10
SPARE_REC = struct.pack("<III", 7, 0, NSLOT + 1)

# name, va, rows (physical), stride, key offset (None = keyed by the partner list), role
#   role 'svc'   service map (V + spare + H), 'shrink' V + H and the count word shrinks, 'full' V + H and the count stays,
#   'title' V + H + sentinel 36 (count stays)
_LISTS = (
    ("tblB", TBLB, 40, 4, 0, "svc"),
    ("tblA", TBLA, 40, 12, None, "svc"),
    ("menu", 0x7d9ba970, 39, 36, 0, "shrink"),
    ("scpa", 0x7d9ba1e0, 39, 12, 0, "shrink"),
    ("scpb", 0x7d9ba3c4, 39, 12, 0, "shrink"),
    ("lca", 0x7d9ba5a8, 39, 12, 0, "shrink"),
    ("lcb", 0x7d9ba78c, 39, 12, 0, "shrink"),
    ("lctext", 0x7d9b9cbc, 39, 12, 0, "shrink"),
    ("enable", 0x7d9b9ac0, 39, 8, 0, "full"),
    ("title", 0x7d9b9ea0, 40, 8, 0, "title"),
    ("a35", 0x7d9bb0f4, 39, 8, 0, "full"),
    ("b35", 0x7d9bb23c, 39, 8, 0, "full"),
    ("l35", 0x7d9b67c0, 39, 8, 0, "full"),
    ("map505b", 0x7dc4307c, 39, 4, 0, "full"),
    ("map505a", 0x7dc42e0c, 39, 16, None, "full"),
    ("map506b", 0x7dc435bc, 39, 4, 0, "full"),
    ("map506a", 0x7dc4334c, 39, 16, None, "full"),
)
_PARTNER = {"tblA": "tblB", "map505a": "map505b", "map506a": "map506b"}
LABELS36 = 0x7d9b7950           # 40 x u16: head 0 + one label id per strip position (= ORDER index + 1); then two 0xffff
LABELS36_N = 40

# count words: name -> (va, width, kind): kind 'n' = visible value count, 'n1' = (n + 1) * 12 bytes (desc total), else fixed
_COUNTS = (
    ("desc111 total", DESC111 + 12, 2, "svc"),
    ("menu count", 0x7e5cb74c, 4, "n"),
    ("scp count", 0x7e5af38e, 2, "n"),
    ("lc count", 0x7e5a7ea8, 4, "n"),
    ("lctext count", 0x7e5a7ec4, 4, "n"),
)
_FIXED = (  # (name, va, width, expected): counts / bounds that never change
    ("enable bound", 0x7db6f7cb, 1, 39), ("title count", 0x7e2e1faa, 1, 40), ("labels36 bound", 0x7e28e26b, 1, 39),
    ("l35 count 505", 0x7d9b6188, 4, 39), ("l35 count 506", 0x7d9b6224, 4, 39),
    ("desc111 elsize", DESC111 + 14, 2, 12), ("desc505 total", DESC505 + 12, 2, 624), ("desc506 total", DESC506 + 12, 2, 624),
    ("desc505 elsize", DESC505 + 14, 2, 16), ("desc506 elsize", DESC506 + 14, 2, 16),
    ("desc111 id", DESC111, 2, 111), ("desc505 id", DESC505, 2, 505), ("desc506 id", DESC506, 2, 506),
)
_LISTVA = {n: va for n, va, *_ in _LISTS}
_PTRS = (  # (pointer site VA, list name): every reader of a list must point at its base
    (DESC111 + 4, "tblA"), (DESC111 + 8, "tblB"), (0x7db6f7b9, "enable"), (0x7e2e1fa5, "title"),
    (0x7e5a7ea0, "lca"), (0x7e5a7ea4, "lcb"), (0x7e5a7ec0, "lctext"), (0x7e5af390, "scpa"), (0x7e5af394, "scpb"),
    (0x7e5cb748, "menu"), (0x7e28e277, "LABELS36"),
    (DESC505 + 4, "map505a"), (DESC505 + 8, "map505b"), (DESC506 + 4, "map506a"), (DESC506 + 8, "map506b"),
    (0x7e5f7594, "l35"), (0x7e5f75dc, "l35"),
) + tuple((s, "a35") for s in (0x7d9b87ec, 0x7d9b890c, 0x7d9b8a04, 0x7d9b8b68, 0x7e5f6b14, 0x7e5f6ba4, 0x7e5f763c, 0x7e5f76f0)) \
  + tuple((s + 4, "b35") for s in (0x7d9b87ec, 0x7d9b890c, 0x7d9b8a04, 0x7d9b8b68, 0x7e5f6b14, 0x7e5f6ba4, 0x7e5f763c, 0x7e5f76f0))
_PTRVA = dict(_LISTVA, LABELS36=LABELS36)

# value / selector keyed regions with their own order or other keys: must stay byte-identical (named for the failure message)
VALUE_KEYED = (
    ("info icon list", 0x7d9b9ff0, 480), ("loader jt", 0x7d9b9c08, 164), ("jump-S + stub", 0x7d9baefc, 180), ("iconT", 0x7d9bafc0, 72),
    ("PM-cell T", 0x7d9bb018, 204), ("LV ordinal", 0x7d9bb380, 324), ("cc2 (SEL2REC, LOOKBASE, Look list, 10063)", 0x7d9bb4d0, 276),
    ("LV image list", 0x7e5b6bc8, 320), ("scf id tables", 0x7d9bd000, 768), ("rules arrays", 0x7d9bb930, 936),
    ("per-look page rows (list2)", 0x7e5c9b30, 17 * 24), ("per-look page stubs", 0x7d9b7780, 68),
)


def off(va):
    return va - P0_BASE


def _u(p0, va, w):
    o = va - P0_BASE
    if o < 0 or o + w > len(p0):
        raise OrderError("main-code partition too short / address %#x outside it" % va)
    return int.from_bytes(p0[o:o + w], "little")


def _rd(p0, va, n):
    return bytes(p0[va - P0_BASE:va - P0_BASE + n])


def _region(name):
    """(va, byte length) of the region of a list / LABELS36"""
    if name == "LABELS36":
        return LABELS36, 2 * LABELS36_N
    for n, va, rows, stride, _k, _r in _LISTS:
        if n == name:
            return va, rows * stride
    raise KeyError(name)


def _spec(name):
    for s in _LISTS:
        if s[0] == name:
            return s
    raise KeyError(name)


# ------------------------------------------------------------------------------------------------ reading a state
class _State:
    pass


def _list_keys(p0, name):
    """keys of the physical rows of a list (keyed by the partner list when the rows carry no key)"""
    _n, va, rows, stride, koff, _r = _spec(name)
    if koff is None:
        return _list_keys(p0, _PARTNER[name])
    return [_u(p0, va + stride * i + koff, 4) for i in range(rows)]


def _check_facts(p0):
    """fixed layout facts of the 18-look release layout (z26 / z27 / z28); raises OrderError naming the first difference"""
    if len(p0) <= off(0x7e5cb750):
        raise OrderError("main-code partition too short for the picture-mode lists (is this the p0 of an E113 image?)")
    for nm, va, w, want in _FIXED:
        got = _u(p0, va, w)
        if got != want:
            raise OrderError("%s at %#x is %d, expected %d: this is not the 18-look layout (z26 / z27 / z28 base)" % (nm, va, got, want))
    for site, nm in _PTRS:
        got = _u(p0, site, 4)
        if got != _PTRVA[nm]:
            raise OrderError("pointer to %s at %#x is %#x, expected %#x: this is not the 18-look layout (z26 / z27 / z28 base)" % (nm, site, got, _PTRVA[nm]))
    if _rd(p0, 0x7e5af38c, 2) != struct.pack("<H", 111) or _u(p0, 0x7e5cb744, 4) != 1:
        raise OrderError("SCP / menu records are not the 18-look layout")


def _read(p0):
    """validated state of the image: visible / hidden values, one physical order P shared by every list"""
    _check_facts(p0)
    s = _State()
    s.n = _u(p0, 0x7e5cb74c, 4)
    if not 1 <= s.n <= N_VALUES:
        raise OrderError("menu count %d is not 1..%d" % (s.n, N_VALUES))
    for nm, va, w, kind in _COUNTS:
        got = _u(p0, va, w)
        want = (s.n + 1) * 12 if kind == "svc" else s.n
        if got != want:
            raise OrderError("%s at %#x is %d, expected %d (the lists do not share one visible count)" % (nm, va, got, want))
    keys = {nm: _list_keys(p0, nm) for nm, *_ in _LISTS}
    s.P = keys["menu"]
    if len(set(s.P)) != N_VALUES or set(s.P) != set(VALUE_OF.values()) | {IENHANCE} or s.P[0] != IENHANCE:
        raise OrderError("menu page 1 does not hold the 39 picture-mode values with i-Enhance first")
    for nm, _v, _r, _s, _k, role in _LISTS:
        want = {"svc": s.P[:s.n] + [SPARE_VALUE] + s.P[s.n:], "title": s.P + [SPARE_VALUE]}.get(role, s.P)
        if keys[nm] != want:
            i = next(i for i, (a, b) in enumerate(zip(keys[nm], want)) if a != b)
            raise OrderError("list %s differs from the menu order at row %d (%d, expected %d): another build?" % (nm, i, keys[nm][i], want[i]))
    s.V, s.H = list(s.P[:s.n]), list(s.P[s.n:])
    if any(v not in VALUE_OF.values() or v not in range(22, 41) or v == 36 for v in s.H):
        raise OrderError("a hidden (past-the-count) row is not a look value")
    # selector of every look record, spare record last
    rec = {k: _rd(p0, TBLA + 12 * i, 12) for i, k in enumerate(keys["tblB"])}
    s.rec = rec
    if rec[SPARE_VALUE] != SPARE_REC:
        raise OrderError("the service map spare record is not {7,0,%d}" % (NSLOT + 1))
    for sl in range(1, NSLOT + 1):
        if struct.unpack("<III", rec[look_value(sl)])[2] != sl:
            raise OrderError("value %d does not carry selector %d: the look value layout differs" % (look_value(sl), sl))
    # strip label table follows L35 by position
    l35 = {k: _u(p0, _LISTVA["l35"] + 8 * i + 4, 4) for i, k in enumerate(keys["l35"])}
    lab = [_u(p0, LABELS36 + 2 * i, 2) for i in range(LABELS36_N)]
    if lab[0] != 0 or lab[1:] != [l35[v] for v in s.P] or _u(p0, LABELS36 + 80, 4) != 0xFFFFFFFF:
        raise OrderError("LABELS36 does not follow the strip caption list L35 (position keyed table differs)")
    return s


def current_order(p0):
    """display order of the image: items of the Picture Mode list after i-Enhance (spare excluded); hidden items are not listed"""
    st = _read(p0)
    return [ITEM_OF[v] for v in st.V[1:]]


def current_hidden(p0):
    """hidden look slots of the image, in the order of their rows behind the counts"""
    return [ITEM_OF[v] for v in _read(p0).H]


LIST_NAMES = tuple(n for n, *_ in _LISTS)


def row_map(p0, name):
    """{value: VA of its row} of one ORDER-bearing list as the image holds it now (rows past a shrinking list's count are the hidden ones).
    For battery / audit code: after a reorder the row of a value is no longer at a fixed address, find it by key"""
    if name not in LIST_NAMES:
        raise OrderError("unknown list %r (one of %s)" % (name, ", ".join(LIST_NAMES)))
    _n, va, rows, stride, _k, _r = _spec(name)
    return {k: va + stride * i for i, k in enumerate(_list_keys(p0, name))}


def _values(items, what):
    out = []
    for it in items:
        if isinstance(it, str) and it.strip().lower() in ("i-enhance", "ienhance"):
            raise OrderError("%s: i-Enhance is always first and cannot be named" % what)
        if isinstance(it, str) and it.strip().lower() == "spare":
            raise OrderError("%s: the spare record is always last and cannot be named" % what)
        if isinstance(it, bool) or not isinstance(it, (int, str)) or it not in VALUE_OF:
            raise OrderError("%s: unknown item %r (look slots 1..%d or a stock name)" % (what, it, NSLOT))
        out.append(it)
    dup = sorted({str(i) for i in out if out.count(i) > 1})
    if dup:
        raise OrderError("%s: duplicate item(s) %s" % (what, ", ".join(dup)))
    return out


def _expected(st, order, hidden):
    """(visible values V, hidden values H) after the request; shared definition of the order semantic"""
    o, h = _values(order, "order"), _values(hidden, "hidden")
    for it in h:
        if isinstance(it, str):
            raise OrderError("hidden: stock item %r cannot be hidden (look slots only)" % it)
    both = [it for it in h if it in o]
    if both:
        raise OrderError("hidden item(s) %s are also in order" % ", ".join(map(str, both)))
    ov, hv = [VALUE_OF[i] for i in o], {VALUE_OF[i] for i in h}
    rest = [v for v in st.P[1:] if v not in ov and v not in hv]
    return [IENHANCE] + ov + rest, [v for v in st.P if v in hv]


# ------------------------------------------------------------------------------------------------ plan / apply
class Plan:
    def __init__(self, edits, olds, order, hidden, visible, hid_values):
        self.edits = edits
        self._olds = olds
        self.order = order
        self.hidden = hidden
        self.visible_values = visible
        self.hidden_values = hid_values

    def sites(self):
        return [(off(va), len(new), note) for va, new, note in self.edits]

    def changed_bytes(self):
        return sum(sum(a != b for a, b in zip(o, n)) for (va, n, _), o in zip(self.edits, self._olds))


def plan(p0, order=(), hidden=()):
    """edits (va, new bytes, note) that put `order` on top of the Picture Mode list and hide `hidden`; ([] when nothing changes)"""
    st = _read(p0)
    V, H = _expected(st, order, hidden)
    P = V + H
    n = len(V)
    edits, olds = [], []

    def put(va, new, note):
        old = _rd(p0, va, len(new))
        if old != new:
            edits.append((va, bytes(new), note))
            olds.append(old)

    rows_of = {}
    for nm, va, rows, stride, koff, role in _LISTS:
        keys = _list_keys(p0, nm)
        by = {k: _rd(p0, va + stride * i, stride) for i, k in enumerate(keys)}
        want = {"svc": V + [SPARE_VALUE] + H, "title": P + [SPARE_VALUE]}.get(role, P)
        put(va, b"".join(by[k] for k in want),
            "%s: %d rows x %d B in the new order%s" % (nm, rows, stride, (" (%d hidden rows behind the count)" % len(H)) if H and role in ("svc", "shrink") else ""))
        rows_of[nm] = by
    l35 = {k: _u(p0, _LISTVA["l35"] + 8 * i + 4, 4) for i, k in enumerate(_list_keys(p0, "l35"))}
    put(LABELS36, struct.pack("<%dH" % LABELS36_N, 0, *[l35[v] for v in P]), "LABELS36: 40 x u16 strip labels by position in the new order")
    for nm, va, w, kind in _COUNTS:
        put(va, ((n + 1) * 12 if kind == "svc" else n).to_bytes(w, "little"), "%s -> %d" % (nm, (n + 1) * 12 if kind == "svc" else n))
    return Plan(edits, olds, [ITEM_OF[v] for v in V[1:]], [ITEM_OF[v] for v in H], V, H)


def apply(p0, pl):
    """write the plan into the bytearray p0 (every site is checked to hold the bytes the plan was made from); returns changed bytes"""
    for (va, new, note), old in zip(pl.edits, pl._olds):
        if _rd(p0, va, len(new)) != old:
            raise OrderError("%s: the image changed since the plan was made" % note)
    for va, new, note in pl.edits:
        p0[off(va):off(va) + len(new)] = new
    return pl.changed_bytes()


# ------------------------------------------------------------------------------------------------ verify (independent re-read + replay)
def _interior_refs(p0, regions):
    """LE32 scan: [(site VA, target)] of every u32 (any alignment) whose value lies strictly inside one of the (va, length) regions"""
    lo, hi = min(r[0] for r in regions), max(r[0] + r[1] for r in regions)
    out = []
    for top in sorted({lo >> 24, (hi - 1) >> 24}):
        b = bytes([top])
        p = p0.find(b, 3)
        while p >= 0:
            v = int.from_bytes(p0[p - 3:p + 1], "little")
            if lo < v < hi:
                for va, ln in regions:
                    if va < v < va + ln:
                        out.append((P0_BASE + p - 3, v))
                        break
            p = p0.find(b, p + 1)
    return out


def _is_pointer_like(p0, site):
    """a LE32 hit is pointer-like when it is 4-aligned (table pointer) or sits behind an MN103 imm32 opcode (fc xx / dc / dd); other hits
    are bytes of data blobs that happen to read as an address"""
    o = site - P0_BASE
    return site % 4 == 0 or p0[o - 2] == 0xFC or p0[o - 1] in (0xDC, 0xDD)


def _diff_runs(a, b, blk=1 << 16):
    """[(start, end)] of the byte ranges where equal-length buffers differ"""
    ia = [o + j for o in range(0, len(a), blk) if a[o:o + blk] != b[o:o + blk] for j in range(min(blk, len(a) - o)) if a[o + j] != b[o + j]]
    runs = []
    for i in ia:
        if runs and i == runs[-1][1]:
            runs[-1][1] = i + 1
        else:
            runs.append([i, i + 1])
    return [tuple(r) for r in runs]


def verify(p0_base, p0_new, order=(), hidden=()):
    """[(check name, ok, detail)]: independent re-read of the written image against the base image and the request. Never raises:
    a list that cannot be read as expected is reported as a failed check"""
    res = []
    try:
        _verify(p0_base, p0_new, order, hidden, res)
    except (OrderError, KeyError, IndexError, ValueError, struct.error, StopIteration) as e:
        res.append(("read of the written image", False, "%s: %s" % (type(e).__name__, e)))
    return res


def _verify(p0_base, p0_new, order, hidden, res):
    def chk(name, ok, detail=""):
        res.append((name, bool(ok), detail))

    try:
        sb = _read(p0_base)
    except OrderError as e:
        chk("base layout", False, str(e))
        return
    try:
        V, H = _expected(sb, order, hidden)
    except OrderError as e:
        chk("request", False, str(e))
        return
    P, n = V + H, len(V)
    try:
        _check_facts(p0_new)
        chk("layout facts", True, "descriptors, %d pointers, fixed counts as in the pinned layout" % len(_PTRS))
    except OrderError as e:
        chk("layout facts", False, str(e))
        return res
    got_n = [(nm, _u(p0_new, va, w)) for nm, va, w, _k in _COUNTS]
    want_n = [(nm, (n + 1) * 12 if k == "svc" else n) for nm, _v, _w, k in _COUNTS]
    chk("counts", got_n == want_n, "visible %d: %s" % (n, ", ".join("%s=%d" % x for x in got_n)) if got_n == want_n else "got %s want %s" % (got_n, want_n))
    # -- order of every list and whole-row identity with the base
    bk = {nm: _list_keys(p0_base, nm) for nm, *_ in _LISTS}
    nk = {nm: _list_keys(p0_new, nm) for nm, *_ in _LISTS}
    for nm, va, rows, stride, koff, role in _LISTS:
        want = {"svc": V + [SPARE_VALUE] + H, "title": P + [SPARE_VALUE]}.get(role, P)
        keys = nk[nm]
        ok = keys == want
        chk("order %s" % nm, ok, "%d rows %#x..%#x" % (rows, va, va + rows * stride) if ok else "key sequence %s != expected %s" % (keys, want))
        b_rows = {k: _rd(p0_base, va + stride * i, stride) for i, k in enumerate(bk[nm])}
        bad = [k for i, k in enumerate(keys) if k not in b_rows or _rd(p0_new, va + stride * i, stride) != b_rows[k]]
        chk("rows %s whole" % nm, not bad, "every row equals the base row of its key" if not bad else "rows changed for keys %s" % bad[:6])
        chk("unique %s" % nm, len(set(keys)) == len(keys), "no key twice")
    # -- strip label table by position
    l35 = {k: _u(p0_new, _LISTVA["l35"] + 8 * i + 4, 4) for i, k in enumerate(nk["l35"])}
    lab = [_u(p0_new, LABELS36 + 2 * i, 2) for i in range(LABELS36_N + 2)]
    ok = lab[0] == 0 and lab[1:LABELS36_N] == [l35[v] for v in nk["map505b"]] and lab[1:LABELS36_N] == [l35[v] for v in nk["map506b"]] and lab[LABELS36_N:] == [0xFFFF, 0xFFFF]
    chk("LABELS36 by position", ok, "position p shows the caption id of the p-th row of the RAW strip maps 505/506" if ok else "label at strip position does not follow maps/L35")
    # -- records keep their values
    bm = dict(zip(bk["tblB"], (_rd(p0_base, TBLA + 12 * i, 12) for i in range(40))))
    nm_ = dict(zip(nk["tblB"], (_rd(p0_new, TBLA + 12 * i, 12) for i in range(40))))
    chk("tblB->tblA dict", bm == nm_ and nm_[SPARE_VALUE] == SPARE_REC and nm_[IENHANCE][:4] == struct.pack("<I", 7), "all 40 (value, record) pairs unchanged")
    for a, bnm in (("map505a", "map505b"), ("map506a", "map506b")):
        ma = dict(zip(bk[bnm], (_rd(p0_base, _LISTVA[a] + 16 * i, 16) for i in range(39))))
        mn = dict(zip(nk[bnm], (_rd(p0_new, _LISTVA[a] + 16 * i, 16) for i in range(39))))
        chk("%s dict" % a, ma == mn, "all 39 (value, record) pairs of the RAW strip map unchanged")
    chk("spare last / i-Enhance first", nk["tblB"][n] == SPARE_VALUE and nm_[SPARE_VALUE] == SPARE_REC and nk["menu"][0] == IENHANCE and nk["tblB"][0] == IENHANCE,
        "tblB[%d]=36 with record {7,0,%d}; menu / service map start with i-Enhance" % (n, NSLOT + 1))
    # -- value / selector keyed regions byte-identical
    bad = [nm for nm, va, ln in VALUE_KEYED if _rd(p0_base, va, ln) != _rd(p0_new, va, ln)]
    chk("value-keyed lists identical", not bad, "%d regions (info, jt, jump-S, iconT, PM-cell T, LV ordinal/image, cc2, scf, rules, per-look page) untouched" % len(VALUE_KEYED) if not bad else "changed: %s" % bad)
    # -- confinement: every changed byte inside the order lists / count words
    allowed = [(off(va), off(va) + ln) for va, ln in (_region(nm) for nm, *_ in _LISTS)] + [(off(LABELS36), off(LABELS36) + 2 * LABELS36_N)]
    allowed += [(off(va), off(va) + w) for _nm, va, w, _k in _COUNTS]
    runs = _diff_runs(p0_base, p0_new) if len(p0_base) == len(p0_new) else None
    if runs is None:
        chk("confinement", False, "image sizes differ")
    else:
        out = [r for r in runs if not any(a <= r[0] and r[1] <= b for a, b in allowed)]
        total = sum(e - s for s, e in runs)
        chk("confinement", not out, "%d changed bytes, all inside the %d list regions and %d count words" % (total, len(_LISTS) + 1, len(_COUNTS)) if not out else "bytes outside the lists: %s" % [(hex(P0_BASE + s), e - s) for s, e in out[:4]])
    # -- replay on the written bytes
    nB = nk["tblB"][:(_u(p0_new, DESC111 + 12, 2) // 12)]
    nA = [_rd(p0_new, TBLA + 12 * i, 12) for i in range(len(nB))]
    en_n = _u(p0_new, 0x7db6f7cb, 1)
    en = {_u(p0_new, _LISTVA["enable"] + 8 * i, 4) for i in range(en_n)}
    m = len(nB)

    def index_of(rec):          # index-of: the last record is never compared; a miss returns it (spare)
        return next((i for i in range(m - 1) if nA[i] == rec), m - 1)

    def set_index(v):           # set-index: a miss returns 0 (i-Enhance)
        return nB.index(v) if v in nB else 0

    def walk(d):
        seq, i = [], 0
        for _ in range(m):
            seq.append(nB[i])
            j = i
            for _t in range(m):
                j = (j + d) % m
                if nB[j] in en:
                    break
            i = j
            if i == 0:
                break
        return seq, i

    fwd, i1 = walk(1)
    back, i2 = walk(-1)
    chk("stepping forward", fwd == V and i1 == 0, "dial / arrow stepping visits %d values in the display order, wraps to i-Enhance; spare skipped (no enable row)" % len(V) if fwd == V and i1 == 0 else "got %s" % fwd)
    chk("stepping backward", back == [V[0]] + V[:0:-1] and i2 == 0, "mirror order with wrap" if back == [V[0]] + V[:0:-1] and i2 == 0 else "got %s" % back)
    rt = all(nB[index_of(nA[set_index(v)])] == v and set_index(v) == nB.index(v) for v in V)
    chk("set / get round trip", rt, "set(v) -> its own index and get gives v for all %d visible values" % len(V))
    stray = True
    for raw in (7, 1, 2, 3, 4, 5, 100, 120):
        for sel in range(1, NSLOT + 2):
            b = struct.pack("<III", raw, 1 if raw == 5 else 0, sel)
            if b not in nA[:m - 1] and index_of(b) != m - 1:
                stray = False
    chk("stray states -> spare", stray, "unknown (raw, mono, sel) states resolve to the last record")
    hid_ok = all(set_index(v) == 0 and index_of(bm[v]) == m - 1 and v not in nB and v in en for v in H)
    chk("hidden: service map", hid_ok, "%d hidden value(s): not stepped, set-miss -> i-Enhance, record-miss -> spare; enable rows kept" % len(H) if hid_ok else "hidden values are still in the service map or lost their enable row")
    # -- hidden rows absent from menu / SCP / LC, present in resolver-critical lists
    vis_lists = ("menu", "scpa", "scpb", "lca", "lcb", "lctext")
    absent = all(not set(nk[nm][:n]) & set(H) and nk[nm][:n] == V for nm in vis_lists)
    chk("hidden absent from UI lists", absent, "menu, SCP A/B, LC A/B, LC text list exactly the %d visible values" % n)
    keep = all(set(H) <= set(nk[nm]) for nm in ("enable", "title", "a35", "b35", "l35", "map505b", "map506b"))
    info = {_u(p0_new, _u(p0_new, 0x7e5b2580, 4) + 12 * i, 4) for i in range(40)}
    lvo = {_u(p0_new, _u(p0_new, 0x7e2fa777, 4) + 8 * i, 4) for i in range(40)}
    chk("hidden kept where resolvers need it", keep and set(H) <= info and set(H) <= lvo, "enable, title, A35/B35/L35, maps 505/506, info list, LV ordinal still hold all %d hidden value(s)" % len(H))
    # -- no pointer into a list interior
    regs = [_region(nm) for nm, *_ in _LISTS] + [_region("LABELS36")]
    refs = _interior_refs(p0_new, regs)
    sus = [(a, b) for a, b in refs if _is_pointer_like(p0_new, a)]
    chk("no interior pointers", not sus, "LE32 scan (all alignments): no pointer-like u32 targets the inside of the %d lists (%d data-blob byte coincidences ignored)" % (len(regs), len(refs) - len(sus))
        if not sus else "pointers into list interiors: %s" % [(hex(a), hex(b)) for a, b in sus[:4]])
    return res
