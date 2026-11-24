"""audit.py - confinement audit of a built image against its base image (stdlib only).

Proves, byte by byte: (1) the container is intact (headers, footers, checksums, model id) and only the partitions that were meant to change
changed; (2) every changed byte of every partition lies inside the declared sites of the slot that was written; (3) the written slot reads
back as intended and every other slot is byte-identical to the base; (4) the table descriptors, the layout and the base mode of the
slot are unchanged. Returns a report dict; `ok` is the verdict. Nothing is written anywhere.
"""
from . import container as C
from . import icons88 as IC
from . import names88 as N
from . import slots88 as S


def merged_ranges(a, b):
    """[(start, end_exclusive)] of the maximal runs where a and b differ (same length)"""
    if len(a) != len(b):
        raise ValueError("length differs")
    out = []
    n = len(a)
    if a == b:
        return out
    step = 1 << 16
    i = 0
    start = None
    while i < n:
        j = min(n, i + step)
        if a[i:j] == b[i:j]:
            if start is not None:
                # the run may end exactly at i
                out.append((start, i))
                start = None
            i = j
            continue
        for k in range(i, j):
            if a[k] != b[k]:
                if start is None:
                    start = k
            elif start is not None:
                out.append((start, k))
                start = None
        i = j
    if start is not None:
        out.append((start, n))
    return out


def audit(base_bin, new_bin, slot, intended, allowed, base_mode=None, name=None, icon=False):
    """base_bin / new_bin: bytes of the two images. slot: the slot written. intended: dict(L16, t3, t2).
    allowed: {partition index: [(file offset, length, note)]} the declared sites (p0 file offsets = VA - P0_BASE)."""
    rep = dict(slot=slot, checks=[], ok=True, changed={})

    def check(name, ok, detail=""):
        rep["checks"].append(dict(name=name, ok=bool(ok), detail=detail))
        if not ok:
            rep["ok"] = False
    try:
        bp, np_ = C.split_image(base_bin), C.split_image(new_bin)
    except C.ContainerError as e:
        check("container parses", False, str(e))
        return rep
    check("same size and partition count", len(base_bin) == len(new_bin) and len(bp) == len(np_), "%d / %d bytes, %d partitions" % (len(base_bin), len(new_bin), len(np_)))
    if len(bp) != len(np_):
        return rep
    problems = C.check_parts(np_)
    check("model id, footer copies, footer checksums of the new image", not problems, "; ".join(problems) or "%d partitions" % len(np_))
    check("headers identical to the base", all(a.header == b.header for a, b in zip(bp, np_)))
    plains_b, plains_n = [p.plain() for p in bp], [p.plain() for p in np_]
    total = 0
    for i, (a, b) in enumerate(zip(plains_b, plains_n)):
        runs = merged_ranges(a, b)
        n = sum(e - s for s, e in runs)
        total += n
        rep["changed"][i] = dict(bytes=n, ranges=[(hex(s), e - s) for s, e in runs][:64], n_ranges=len(runs))
        sites = allowed.get(i, [])
        outside = [(s, e) for s, e in runs if not any(s >= o and e <= o + ln for o, ln, _ in sites)]
        check("partition %d: every changed byte lies inside the declared sites" % i, not outside,
              "%d bytes changed in %d runs%s" % (n, len(runs), "; OUTSIDE: " + ", ".join("%#x+%d" % (s, e - s) for s, e in outside[:8]) if outside else ""))
        if i not in allowed:
            check("partition %d unchanged" % i, a == b)
    rep["total_changed_bytes"] = total
    p0n, p0b = bytearray(plains_n[0]), bytearray(plains_b[0])
    for va, ln, what in S.HOMES:                 # regions of later builds (z26 homes): untouched, and never inside a declared site
        o = S.off(va)
        inside = o + ln <= len(p0b)
        declared = any(o < so + sl and so < o + ln for so, sl, _ in allowed.get(0, []))
        check("%s %#x+%d untouched" % (what, va, ln), inside and p0n[o:o + ln] == p0b[o:o + ln] and not declared,
              "%d bytes compared, none declared as a site" % ln if inside else "the partition ends before the region")
    try:
        S.check_layout(p0n)
        check("release layout intact (descriptors, bounds)", True)
        rb = S.read_slot(p0n, slot)
        want = dict(L16=list(intended["L16"]), t3=[list(map(int, y)) for y in intended["t3"]], t2=list(map(int, intended["t2"])))
        got = dict(L16=rb["L16"], t3=rb["t3"], t2=rb["t2"])
        check("slot %d reads back as intended (matrix, T3, T2)" % slot, got == want)
        others = [s for s in range(1, S.NSLOT + 1) if s != slot and S.read_slot(p0n, s) != S.read_slot(p0b, s)]
        check("all other slots unchanged", not others, "differ: %s" % others if others else "17 slots identical")
        if base_mode is not None:
            check("base mode of the slot unchanged", S.base_mode(p0n, slot) == base_mode == S.base_mode(p0b, slot), base_mode)
    except S.SlotError as e:
        check("slot layout / read back", False, str(e))
    if name is not None:
        try:
            nb, nn = N.NameBook(plains_b[1]), N.NameBook(plains_n[1])
            check("menu name of slot %d reads back as %r in all 34 languages and both ids" % (slot, name), nn.current_name(slot) == name)
            others = [s for s in range(1, S.NSLOT + 1) if s != slot and nn.current_name(s) != nb.current_name(s)]
            check("all other slot names unchanged", not others, "differ: %s" % others if others else "17 names identical")
        except (N.NameError_, ValueError) as e:
            check("menu names read back", False, str(e))
    if icon:
        try:
            for nm, ok, detail in IC.check(bytearray(plains_n[0]), bytearray(plains_n[1]), slot):
                check(nm, ok, detail)
            ids = []
            for s2 in range(1, S.NSLOT + 1):
                ids += list(IC.ids_of(plains_n[0], s2))
            check("icon ids: 36 unique, one U + one S per slot, same ids as the base", len(set(ids)) == len(ids) == 36 and
                  ids == [i for s2 in range(1, S.NSLOT + 1) for i in IC.ids_of(plains_b[0], s2)])
            other = [s2 for s2 in range(1, S.NSLOT + 1) if s2 != slot and any(
                plains_n[1][h["df"]:h["df"] + h["size"]] != plains_b[1][h["df"]:h["df"] + h["size"]]
                for h in (IC.header(plains_n[1], i) for i in IC.ids_of(plains_n[0], s2)))]
            check("icons of all other slots byte-identical to the base", not other, "differ: %s" % other if other else "17 slots identical")
        except IC.IconError as e:
            check("icon proofs", False, str(e))
    return rep


def format_report(rep):
    lines = ["confinement audit, slot %s: %s (%d bytes changed in total)" % (rep["slot"], "PASS" if rep["ok"] else "FAIL", rep.get("total_changed_bytes", -1))]
    for c in rep["checks"]:
        lines.append("  [%s] %s%s" % ("ok" if c["ok"] else "FAIL", c["name"], (": " + c["detail"]) if c["detail"] else ""))
    for i, c in sorted(rep["changed"].items()):
        lines.append("  partition %d: %d bytes in %d runs %s" % (i, c["bytes"], c["n_ranges"], c["ranges"][:6]))
    return "\n".join(lines)
