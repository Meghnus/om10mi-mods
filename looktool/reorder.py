#!/usr/bin/env python3
"""reorder.py - free look ORDER for the version 94 image (18-look layout), built on lookbuild/order88.py.

    python looktool/reorder.py build BASE.BIN OUT_DIR --order 7,6,9,13 [--after <slot | Portrait | ... | i-Enhance>] [--hidden 12] [--looks PACK.json [--lut-dir DIR]] [--card] [--no-battery]
    python looktool/reorder.py selftest BASE.BIN                 # negative control + identity on the base, writes nothing
    
The option `order` = an explicit list of LOOK SLOT ids (integers 1..18): those looks go directly after i-Enhance in exactly that sequence, every other
item (base-mode rows Vivid / Natural / Muted / Portrait, the remaining looks, Monotone, Custom, ...) keeps its current relative order. `--after ANCHOR` puts the ordered looks directly behind that row instead (a look slot, a stock row name, default i-Enhance = unchanged behaviour): the rows in front of the anchor and behind the moved window keep their stock positions. A list of all 18
ids is a complete permutation of the look rows. i-Enhance and the base-mode rows are never named (refused with a message); with `hidden` (look slots,
NOT field-proven: only reorder is) a look leaves the shooting lists. Nothing here edits code: only the row order of the 17 order lists (+ LABELS36).

Two modes
  order only   BASE.BIN + --order            -> E113_ORDER_TEST.BIN : the 18 order88 edits and nothing else
  with looks   BASE.BIN + --order --looks P  -> the look pack P (a v2 look file with a `pack` block, PACK_SPEC_v2.md) is built by lookbuild.pack on BASE
                                                with ITS order / hidden REPLACED by --order / --hidden (the pack's `base.sha1` is rewritten to BASE's).

Checks after every build (any failure -> nothing is written): every list the order touches is a PERMUTATION (row multiset) of the base's; the 5 count
words equal the base's (no hidden) or the visible count; nothing changed in 0x7d9bd341..0x7da00000; every changed byte of the order-only build lies in
the plan's declared sites, partitions 1.. and all headers are unchanged, footer checksums; the resulting display order equals the request; the whole
lookbuild.order88.verify battery (68 checks); in `with looks` mode the order bytes equal the order-only build's. A negative control (mutated copies of the
result: duplicated row, cross-list swap, zone byte, count word, strip label) must be REFUSED by the same checks, else the build is refused.
Needs: Python 3.10+, stdlib (the `with looks` mode also numpy etc. through lookbuild). Never talks to a camera or a card.
"""
import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LUT1 = HERE
if LUT1 not in sys.path:
    sys.path.insert(0, LUT1)

from lookbuild import audit as A          # noqa: E402
from lookbuild import build as B          # noqa: E402
from lookbuild import container as C      # noqa: E402
from lookbuild import order88 as O        # noqa: E402

# the pinned base (the version 94 image built by om10mi.py from your own official firmware)
FAMILY = {"baf96f07b86f40aa91bb100a3658f64d9ed4dcf2": "release 94"}
ZONE = (0x7d9bd341, 0x7da00000)            # nothing may change here (audpack: forbidden zone)
BASE_MODE_ROWS = {"vivid", "natural", "muted", "portrait"}
STOCK_ROWS = {s.lower() for s in O.STOCK}
LOOKS = range(1, O.NSLOT + 1)


class ReorderError(ValueError):
    """a refusal: nothing was built"""


# ------------------------------------------------------------------------------------------------ request validation
def _slot(x, what):
    if isinstance(x, bool):
        raise ReorderError("%s: %r is not a look slot id (integers 1..%d)" % (what, x, O.NSLOT))
    if isinstance(x, str):
        t = x.strip()
        low = t.lower()
        if low in ("i-enhance", "ienhance"):
            raise ReorderError("%s: i-Enhance is always the first row and cannot be moved" % what)
        if low in BASE_MODE_ROWS:
            raise ReorderError("%s: %r is a base-mode row (i-Enhance / Vivid / Natural / Muted / Portrait stay fixed); the order option moves look slots 1..%d only" % (what, x, O.NSLOT))
        if low in STOCK_ROWS:
            raise ReorderError("%s: %r is a stock row; the order option moves look slots 1..%d only" % (what, x, O.NSLOT))
        if not t.isdigit():
            raise ReorderError("%s: %r is not a look slot id (integers 1..%d)" % (what, x, O.NSLOT))
        x = int(t)
    if not isinstance(x, int):
        raise ReorderError("%s: %r is not a look slot id (integers 1..%d)" % (what, x, O.NSLOT))
    if x not in LOOKS:
        raise ReorderError("%s: slot %d is outside 1..%d" % (what, x, O.NSLOT))
    return x


def normalise(order, hidden=()):
    """-> (order, hidden) as lists of ints. Refuses: non-slot items, base-mode / stock rows, out-of-range, duplicates, a slot both ordered and hidden."""
    if isinstance(order, (str, bytes)) or isinstance(hidden, (str, bytes)):
        raise ReorderError("order / hidden must be lists of slot ids")
    o = [_slot(x, "order") for x in (order or [])]
    if hidden:
        raise ReorderError("hide is experimental and not available: it has not been proven on a camera, so this builder refuses it")
    h = []
    for what, lst in (("order", o), ("hidden", h)):
        dup = sorted({x for x in lst if lst.count(x) > 1})
        if dup:
            raise ReorderError("%s: duplicate slot(s) %s (the list must be a sequence without repeats)" % (what, ", ".join(map(str, dup))))
    both = [x for x in h if x in o]
    if both:
        raise ReorderError("slot(s) %s are both ordered and hidden" % ", ".join(map(str, both)))
    return o, h


_STOCK_BY_LOW = {s.lower(): s for s in O.STOCK}


def normalise_after(after, order=(), hidden=()):
    """-> None (= directly behind i-Enhance, the default) or the anchor row: a look slot (int 1..18) or an exact stock row name (Vivid / Natural / Muted / Portrait /
    Monotone / ...). Refuses unknown rows, an anchor that is itself ordered or hidden. The anchor row must exist in the image (checked in resolve_order)."""
    if after is None:
        return None
    if isinstance(after, bool):
        raise ReorderError("after: %r is not an anchor (a look slot 1..%d, a stock row name or i-Enhance)" % (after, O.NSLOT))
    if isinstance(after, str):
        t = after.strip()
        low = t.lower()
        if low in ("", "i-enhance", "ienhance"):
            return None
        if low in _STOCK_BY_LOW:
            return _STOCK_BY_LOW[low]
        if not t.isdigit():
            raise ReorderError("after: %r is not an anchor (a look slot 1..%d, a stock row name or i-Enhance)" % (after, O.NSLOT))
        after = int(t)
    if not isinstance(after, int):
        raise ReorderError("after: %r is not an anchor (a look slot 1..%d, a stock row name or i-Enhance)" % (after, O.NSLOT))
    if after not in LOOKS:
        raise ReorderError("after: slot %d is outside 1..%d" % (after, O.NSLOT))
    if after in list(order):
        raise ReorderError("after: slot %d is the anchor and is also in the order list (the anchor stays where it is)" % after)
    if after in list(hidden):
        raise ReorderError("after: slot %d is hidden and cannot be an anchor" % after)
    return after


def resolve_order(p0_base, order, hidden=(), after=None):
    """the request as order88 / the pack spec understand it: the list that goes DIRECTLY BEHIND i-Enhance. Without an anchor that is `order` itself (the old
    behaviour, byte-identical); with an anchor it is the rows of the base list up to and including the anchor (the ordered looks removed from them) followed by
    `order` - every row after it keeps its relative order, so the base rows in front of the anchor keep their stock positions."""
    if after is None:
        return list(order)
    rest = [x for x in O.current_order(p0_base) if x not in order and x not in hidden]
    if after not in rest:
        raise ReorderError("after: anchor %r is not a visible row of the base list (rows: %s ...)" % (after, rest[:6]))
    return rest[:rest.index(after) + 1] + list(order)


def check_base(data, allow_other=False):
    sha = hashlib.sha1(data).hexdigest()
    if sha not in FAMILY and not allow_other:
        raise ReorderError("the base image (sha1 %s) is not in the order family (%s); order88 refuses any other layout anyway"
                           % (sha[:12], ", ".join("%s %s" % (v, k[:8]) for k, v in FAMILY.items())))
    try:
        parts = B.check_base(data, allow_other=True)
    except B.BuildError as e:
        raise ReorderError(str(e))
    return sha, parts


# ------------------------------------------------------------------------------------------------ independent checks
def _rows(p0, va, rows, stride):
    o = va - O.P0_BASE
    return [bytes(p0[o + stride * i:o + stride * (i + 1)]) for i in range(rows)]


def expected_order(p0_base, order, hidden, after=None):
    """display order after the request, derived here from the semantic of PACK_SPEC_v2 + the anchor (not from order88's plan): the base order without the
    ordered / hidden items, the ordered looks inserted directly behind the anchor (default: directly behind i-Enhance)"""
    hid = set(hidden)
    rest = [x for x in O.current_order(p0_base) if x not in order and x not in hid]
    k = 0 if after is None else rest.index(after) + 1
    return rest[:k] + list(order) + rest[k:]


def check_result(p0b, p0n, order, hidden, sites=None, with_verify=True, verify_ref=None, after=None):
    """[(name, ok, detail)] - never raises. p0b / p0n = plain main-code partitions (base, result)."""
    res = []

    def chk(name, ok, detail=""):
        res.append((name, bool(ok), detail))
    # 1 every order list (+ LABELS36) is a permutation of the base's rows
    bad = []
    for nm, va, rows, stride, _k, _r in O._LISTS:
        if sorted(_rows(p0b, va, rows, stride)) != sorted(_rows(p0n, va, rows, stride)):
            bad.append(nm)
    chk("17 order lists are permutations of the base (row multiset)", not bad, "differs: %s" % ", ".join(bad) if bad else "%d lists" % len(O._LISTS))
    lb = _rows(p0b, O.LABELS36, O.LABELS36_N, 2)
    ln = _rows(p0n, O.LABELS36, O.LABELS36_N, 2)
    chk("LABELS36 is a permutation of the base's", sorted(lb) == sorted(ln))
    # 2 count words
    try:
        vis = len(O.current_order(p0n)) + 1
        base_plain = not O.current_hidden(p0b) and not hidden
    except O.OrderError as e:
        chk("result readable by order88", False, str(e))
        return res
    cw = {nm: O._u(p0n, va, w) for nm, va, w, _k in O._COUNTS}
    if base_plain:
        cb = {nm: O._u(p0b, va, w) for nm, va, w, _k in O._COUNTS}
        chk("count words unchanged", cw == cb, "%s" % (cw if cw != cb else "5 words identical"))
    else:
        want = {nm: (((vis + 1) * 12) if k == "svc" else vis) for nm, va, w, k in O._COUNTS}
        chk("count words = visible count", cw == want, "%s" % cw)
    # 3 forbidden zone
    o0, o1 = ZONE[0] - O.P0_BASE, min(ZONE[1] - O.P0_BASE, len(p0b))
    chk("nothing in %#x..%#x" % ZONE, bytes(p0b[o0:o1]) == bytes(p0n[o0:o1]) and len(p0b) == len(p0n))
    # 4 confinement to the plan's sites
    if sites is not None:
        runs = A.merged_ranges(bytes(p0b), bytes(p0n))
        outside = [(s, e) for s, e in runs if not any(s >= o and e <= o + ln_ for o, ln_, _ in sites)]
        chk("every changed byte lies inside the declared order sites", not outside, ("OUTSIDE %s" % outside[:4]) if outside else "%d runs" % len(runs))
    # 5 resulting order = request
    try:
        got = O.current_order(p0n)
        want = expected_order(p0b, order, hidden, after)
        chk("resulting display order equals the request", got == want, "%s" % (got[:12],))
        k = 0 if after is None else got.index(after) + 1
        chk("i-Enhance first, requested looks directly behind %s" % ("it" if after is None else "the anchor %s" % after), got[k:k + len(order)] == list(order))
        base_modes = [x for x in got if x in ("Vivid", "Natural", "Muted", "Portrait")]
        chk("base-mode rows keep their relative order", base_modes == [x for x in O.current_order(p0b) if x in base_modes] and len(base_modes) == 4, str(base_modes))
        if order and not hidden:
            # only the window between the anchor and the old places of the ordered looks may move: every other row (base-mode rows, stock rows behind the looks)
            # keeps its stock index in the display order AND its physical row in all 17 lists
            bvis = O.current_order(p0b)
            old = [bvis.index(x) for x in order]
            a = -1 if after is None else bvis.index(after)
            lo, hi = min(old + [a + 1]), max(old + [a])
            fixed = [bvis[i] for i in range(len(bvis)) if not lo <= i <= hi]
            moved = [x for i, x in enumerate(bvis) if not lo <= i <= hi and got[i] != x]
            chk("rows outside the moved window keep their stock index (display order)", not moved, "window %d..%d of %d rows, %d rows fixed%s" % (lo, hi, len(bvis), len(fixed), ("; MOVED %s" % moved) if moved else ""))
            drift = []
            val = lambda x: O.IENHANCE if x == "i-Enhance" else O.VALUE_OF[x]
            for nm in O.LIST_NAMES:
                rb, rn = O.row_map(p0b, nm), O.row_map(p0n, nm)
                drift += ["%s:%s" % (nm, x) for x in ["i-Enhance"] + fixed if rb[val(x)] != rn[val(x)]]
            chk("rows outside the moved window keep their physical row in all 17 lists", not drift, "%d lists x %d rows" % (len(O.LIST_NAMES), len(fixed) + 1) if not drift else "DRIFT %s" % drift[:4])
    except (O.OrderError, ValueError) as e:
        chk("resulting display order equals the request", False, str(e))
    if with_verify:
        try:
            req = resolve_order(p0b, order, hidden, after)
        except (ReorderError, O.OrderError) as e:
            req = list(order)
            chk("anchor resolvable on the base", False, str(e))
        vr = O.verify(p0b if verify_ref is None else verify_ref, p0n, req, hidden)
        badv = [x for x in vr if not x[1]]
        chk("lookbuild.order88.verify (%d checks)" % len(vr), not badv, "; ".join("%s (%s)" % (a, c) for a, _b, c in badv[:3]) or "all pass")
    return res


def failed(res):
    return [r for r in res if not r[1]]


def negative_control(p0b, p0n, order, hidden, verify_ref=None, after=None):
    """mutated copies of the result; every one must fail check_result. -> [(mutant, refused, first failing check)]"""
    def spec(name):
        return next(s for s in O._LISTS if s[0] == name)

    def row(p, name, i):
        _n, va, rows, stride, *_ = spec(name)
        o = va - O.P0_BASE + stride * i
        return o, stride

    def dup_row(name):
        q = bytearray(p0n)
        o1, st = row(q, name, 3)
        o2, _ = row(q, name, 4)
        q[o2:o2 + st] = q[o1:o1 + st]
        return q

    def swap_rows(name):
        q = bytearray(p0n)
        o1, st = row(q, name, 3)
        o2, _ = row(q, name, 4)
        a, b = bytes(q[o1:o1 + st]), bytes(q[o2:o2 + st])
        q[o1:o1 + st], q[o2:o2 + st] = b, a
        return q

    def zone_byte():
        q = bytearray(p0n)
        q[ZONE[0] - O.P0_BASE] ^= 0x01
        return q

    def count_word():
        q = bytearray(p0n)
        va = next(v for n, v, w, k in O._COUNTS if n == "menu count")
        q[va - O.P0_BASE] ^= 0x01
        return q

    def label_swap():
        q = bytearray(p0n)
        o = O.LABELS36 - O.P0_BASE
        q[o + 6:o + 8], q[o + 8:o + 10] = bytes(q[o + 8:o + 10]), bytes(q[o + 6:o + 8])
        return q

    def wrong_anchor():
        """a perfectly valid permutation at the WRONG place (the order bytes of another anchor): only the display-order check can refuse it"""
        try:
            q = bytearray(p0n)
            alt = "Portrait" if after is None else None
            O.apply(q, O.plan(q, resolve_order(q, order, hidden, alt), hidden))
        except (ReorderError, O.OrderError):
            return None
        return q if bytes(q) != bytes(p0n) else None
    mutants = [("duplicated row in the menu list (not a permutation)", dup_row("menu")),
               ("duplicated row in tblA (not a permutation)", dup_row("tblA")),
               ("two rows swapped in tblB only (permutation, lists disagree)", swap_rows("tblB")),
               ("two rows swapped in the SCP picker B only", swap_rows("scpb")),
               ("LABELS36 entries swapped", label_swap()),
               ("a byte flipped at %#x" % ZONE[0], zone_byte()),
               ("menu count word changed", count_word())]
    wa = wrong_anchor() if order else None
    if wa is not None:
        mutants.append(("valid permutation at the wrong anchor (%s)" % ("behind Portrait" if after is None else "behind i-Enhance"), wa))
    out = []
    for name, q in mutants:
        r = failed(check_result(p0b, bytes(q), order, hidden, verify_ref=verify_ref, after=after))
        out.append((name, bool(r), "; ".join(x[0] for x in r) if r else "ACCEPTED"))
    return out


# ------------------------------------------------------------------------------------------------ build
def _rebuild(parts, p0):
    return C.join_image([C.with_plain(parts[0], bytes(p0))] + parts[1:])


def build_order_only(data, order, hidden=(), allow_other=False, log=print, after=None):
    """-> dict(image, plan, checks, negative); raises ReorderError / O.OrderError-as-ReorderError, nothing produced"""
    order, hidden = normalise(order, hidden)
    after = normalise_after(after, order, hidden)
    if not order and not hidden:
        raise ReorderError("nothing to do: give an order (look slot ids) and / or hidden slots")
    sha, parts = check_base(data, allow_other)
    p0b = bytes(parts[0].plain())
    p0 = bytearray(p0b)
    try:
        req = resolve_order(p0b, order, hidden, after)
        plan = O.plan(p0, req, hidden)
        O.apply(p0, plan)
    except O.OrderError as e:
        raise ReorderError("order refused by order88: %s" % e)
    image = _rebuild(parts, p0)
    pn = C.split_image(image)
    probs = C.check_parts(pn)
    if probs:
        raise ReorderError("footer / model check of the result failed: %s" % "; ".join(probs))
    if any(a.header != b.header for a, b in zip(parts, pn)) or len(parts) != len(pn):
        raise ReorderError("headers changed")
    for i in range(1, len(parts)):
        if parts[i].plain() != pn[i].plain():
            raise ReorderError("partition %d changed (the order edits live in partition 0 only)" % i)
    res = check_result(p0b, bytes(p0), order, hidden, sites=plan.sites(), after=after)
    bad = failed(res)
    if bad:
        raise ReorderError("post-build checks failed: " + "; ".join("%s (%s)" % (a, c) for a, _b, c in bad[:4]))
    neg = negative_control(p0b, bytes(p0), order, hidden, after=after)
    miss = [n for n, refused, _w in neg if not refused]
    if miss:
        raise ReorderError("negative control: mutant(s) NOT refused: %s" % "; ".join(miss))
    log("order %s%s -> display order %s ... (%d edits, %d bytes changed)" % (order, "" if after is None else " after %s" % after, plan.order[:8], len(plan.edits), plan.changed_bytes()))
    return dict(image=image, plan=plan, checks=res, negative=neg, base_sha1=sha, p0=bytes(p0), after=after, prefix=req)


def build_with_looks(data, order, hidden, pack_path, lut_dir=None, allow_other=False, battery=True, log=print, after=None):
    """the look pack `pack_path` built by lookbuild.pack on the base with its order / hidden replaced by the request. The anchor is written into the pack as an
    explicit `order` prefix (rows of the base list up to the anchor + the ordered looks; stock rows are legal items of a pack `order`): the pack spec needs no new key."""
    from lookbuild import pack as PK
    order, hidden = normalise(order, hidden)
    after = normalise_after(after, order, hidden)
    sha, parts = check_base(data, allow_other)
    if not order and not hidden:
        raise ReorderError("nothing to do: give an order (look slot ids) and / or hidden slots")
    only = build_order_only(data, order, hidden, allow_other, log=lambda *_: None, after=after)
    try:
        with open(pack_path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        raise ReorderError("cannot read the pack: %s" % e)
    if not isinstance(doc.get("pack"), dict):
        raise ReorderError("the file has no `pack` block")
    pk = doc["pack"]
    pk["base"] = dict(pk.get("base") or {}, sha1=sha)
    pk.pop("order", None)
    pk.pop("hidden", None)
    if order:
        pk["order"] = only["prefix"]
    if hidden:
        pk["hidden"] = hidden
    fd, tmp = tempfile.mkstemp(suffix=".pack.json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        try:
            res = PK.build_pack(data, tmp, lut_dir=lut_dir, allow_other_base=True, log=log, battery=battery)
        except B.BuildError as e:
            raise ReorderError("pack refused: %s" % e)
    finally:
        os.unlink(tmp)
    pn = C.split_image(res["image"])
    p0n = pn[0].plain()
    p0b = bytes(parts[0].plain())
    # order88.verify's reference = the image after the slot writes and before the reorder (as pack.py does): the base with the look sites of the result
    p0_pre = bytearray(p0n)
    for va, new, _note in only["plan"].edits:
        p0_pre[va - O.P0_BASE:va - O.P0_BASE + len(new)] = p0b[va - O.P0_BASE:va - O.P0_BASE + len(new)]
    chk = check_result(p0b, bytes(p0n), order, hidden, verify_ref=bytes(p0_pre), after=after)
    if only is not None:
        bad_sites = [note for (va, new, note) in only["plan"].edits if bytes(p0n[va - O.P0_BASE:va - O.P0_BASE + len(new)]) != new]
        chk.append(("order bytes equal the order-only build", not bad_sites, "; ".join(bad_sites[:3]) or "%d sites" % len(only["plan"].edits)))
    bad = failed(chk)
    if bad:
        raise ReorderError("post-build checks failed: " + "; ".join("%s (%s)" % (a, c) for a, _b, c in bad[:4]))
    neg = negative_control(p0b, bytes(p0n), order, hidden, verify_ref=bytes(p0_pre), after=after)
    miss = [n for n, refused, _w in neg if not refused]
    if miss:
        raise ReorderError("negative control: mutant(s) NOT refused: %s" % "; ".join(miss))
    return dict(image=res["image"], pack_report=res["report"], checks=chk, negative=neg, base_sha1=sha, p0=bytes(p0n), plan=only["plan"] if only else None, after=after, prefix=only["prefix"])


def write_result(res, out_dir, card=False, looks=False):
    os.makedirs(out_dir, exist_ok=True)
    if card:
        os.makedirs(os.path.join(out_dir, "DCOLYMP"), exist_ok=True)
        target = os.path.join(out_dir, "DCOLYMP", "E1139999.BIN")
    else:
        target = os.path.join(out_dir, "E113_ORDER_PACK_TEST.BIN" if looks else "E113_ORDER_TEST.BIN")
    with open(target + ".part", "wb") as fh:
        fh.write(res["image"])
    os.replace(target + ".part", target)
    sha = hashlib.sha1(res["image"]).hexdigest()
    rep = dict(base=FAMILY.get(res["base_sha1"], "other"), base_sha1=res["base_sha1"], sha1=sha, size=len(res["image"]),
               order=res["plan"].order if res.get("plan") else None,
               after=res.get("after"), order_prefix=res.get("prefix"),
               checks=[dict(name=a, ok=b, detail=c) for a, b, c in res["checks"]],
               negative_control=[dict(mutant=a, refused=b, by=c) for a, b, c in res["negative"]],
               pack=res.get("pack_report"))
    with open(os.path.join(out_dir, "order_report.json"), "w") as fh:
        json.dump(rep, fh, indent=1)
    return target, sha


def selftest(data, allow_other=False):
    """identity request on the base (0 edits) is a no-op; a real request passes its checks and its negative control. Writes nothing. -> problems"""
    bad = []
    sha, parts = check_base(data, allow_other)
    p0 = bytearray(parts[0].plain())
    if O.plan(p0, [], []).edits:
        bad.append("identity plan has edits")
    cur = [x for x in O.current_order(p0) if isinstance(x, int)]
    for req in ([cur[0]], list(reversed(cur)), list(cur)):
        try:
            r = build_order_only(data, req, [], allow_other, log=lambda *_: None)
        except ReorderError as e:
            bad.append("request %s refused: %s" % (req[:4], e))
            continue
        if not all(c[1] for c in r["checks"]):
            bad.append("checks failed for %s" % req[:4])
    for badreq, why in (([7, 7], "duplicate"), ([0], "out of range"), ([19], "out of range"), (["Vivid"], "base-mode row"), (["i-Enhance"], "i-Enhance"),
                        ([True], "bool"), (["Monotone"], "stock row"), ([7, 6.5], "float"), ([None], "None")):
        try:
            normalise(badreq)
            bad.append("%s %r was ACCEPTED" % (why, badreq))
        except ReorderError:
            pass
    try:
        normalise([7, 6], [6])
        bad.append("hidden+ordered was ACCEPTED")
    except ReorderError:
        pass
    return bad


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="olylook reorder", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("base")
    b.add_argument("out")
    b.add_argument("--order", default="", help="comma separated look slot ids, e.g. 7,6,9,13")
    b.add_argument("--after", default="", help="anchor row the ordered looks go directly behind: a look slot id, a stock row name (Portrait, Vivid, ...) or i-Enhance (default = i-Enhance)")
    b.add_argument("--hidden", default="", help="(disabled: hide is experimental and not available; any value is refused)")
    b.add_argument("--looks", help="a v2 look pack (PACK_SPEC_v2.md): built on the base with its order / hidden replaced")
    b.add_argument("--lut-dir")
    b.add_argument("--card", action="store_true")
    b.add_argument("--no-battery", action="store_true")
    b.add_argument("--allow-other-base", action="store_true", help="skip the version 94 pin (order88 still checks the layout)")
    s = sub.add_parser("selftest")
    s.add_argument("base")
    s.add_argument("--allow-other-base", action="store_true")
    p = ap.parse_args(argv)
    with open(p.base, "rb") as fh:
        data = fh.read()
    try:
        if p.cmd == "selftest":
            bad = selftest(data, p.allow_other_base)
            print("reorder selftest: %s" % ("PASS" if not bad else "FAIL " + "; ".join(bad)))
            return 1 if bad else 0

        def ids(t):
            return [x for x in t.split(",") if x.strip()]
        order, hidden = ids(p.order), ids(p.hidden)
        if p.looks:
            res = build_with_looks(data, order, hidden, p.looks, p.lut_dir, p.allow_other_base, not p.no_battery, after=p.after)
        else:
            res = build_order_only(data, order, hidden, p.allow_other_base, after=p.after)
        target, sha = write_result(res, p.out, p.card, bool(p.looks))
    except (ReorderError, O.OrderError) as e:
        print("REFUSED: %s\nNothing was written." % e)
        return 1
    for a, ok, c in res["checks"]:
        print("  %-4s %s  %s" % ("OK" if ok else "FAIL", a, c))
    for a, refused, by in res["negative"]:
        print("  neg  %s: %s" % (a, "refused (%s)" % by if refused else "ACCEPTED"))
    print("wrote %s (sha1 %s)\nThis file has NOT been checked on a camera. Keep your official firmware ready to restore it (you flash at your own risk)." % (target, sha))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
