"""pack.py - build a look PACK (PACK_SPEC_v2.md) into the user's release image: replace / rename / reorder / hide, then the confinement audit and the acceptance battery.

One deterministic pass, fail-closed (nothing is returned unless every step passes):
  1 the pack passes lookfile_check (incl. the pack rules), the image's sha1 equals pack.base.sha1 and is a pinned base (or --allow-other-base: layout still checked);
  2 every look of the pack is written exactly like om10mi_look.py --look --slot (tone lift, dE gate, slot data, name x 34 languages, roll icon);
  3 renames of the other slots (names88);   4 order + hide (order88, in-place row permutations);
  5 pack audit: every changed byte of p0 / p1 lies inside the declared sites of the ops, p2 and all headers unchanged, z26 homes untouched, untouched slots byte-identical
    (matrix / T3 / T2 / names / icons), touched slots read back as intended, footer checksums;
  6 the acceptance battery (accept88: owner criteria A1..A4 on the written image) - mandatory unless `battery=False` (the report then says UNCHECKED).
"""
import hashlib
import json
import os
import struct

from . import audit as A
from . import build as B
from . import container as C
from . import icons88 as IC
from . import names88 as N
from . import slots88 as S


class PackError(B.BuildError):
    pass


def load_pack(path):
    lc = B._lookfile_check()
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise PackError("cannot read the pack: %s" % e)
    rep = lc.check(data, len(raw))
    if rep.errors:
        raise PackError("pack refused by the checker: " + "; ".join(rep.errors[:8]))
    if not isinstance(data.get("pack"), dict):
        raise PackError("the file has no `pack` block (a plain look file goes through --look)")
    return data, rep.warnings


def find_lut(lut_dir, source):
    """path of the source table in lut_dir whose sha256 equals source.sha256 (None when not found / no dir)"""
    if not lut_dir or not source or not source.get("name"):
        return None
    p = os.path.join(lut_dir, os.path.basename(source["name"]))
    if not os.path.isfile(p):
        return None
    with open(p, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    if source.get("sha256") and source["sha256"].lower() != sha:
        raise PackError("%s in --lut-dir has sha256 %s, the pack says %s: wrong file" % (p, sha[:12], source["sha256"][:12]))
    return p


def audit_pack(base_bin, new_bin, touched, renamed, sites0, sites1, order_sites=()):
    """touched {slot: dict(L16, t3, t2, name or None, roll bool)}, renamed {slot: name}, sites0 / sites1 = declared (file offset, length, note) of p0 / p1.
    -> report dict like audit.audit (ok, checks)"""
    rep = dict(checks=[], ok=True, changed={}, slots=sorted(touched))

    def check(name, ok, detail=""):
        rep["checks"].append(dict(name=name, ok=bool(ok), detail=detail))
        if not ok:
            rep["ok"] = False
    try:
        bp, np_ = C.split_image(base_bin), C.split_image(new_bin)
    except C.ContainerError as e:
        check("container parses", False, str(e))
        return rep
    check("same size and partition count", len(base_bin) == len(new_bin) and len(bp) == len(np_), "%d bytes, %d partitions" % (len(new_bin), len(np_)))
    if len(bp) != len(np_):
        return rep
    problems = C.check_parts(np_)
    check("model id, footer copies, footer checksums of the new image", not problems, "; ".join(problems) or "%d partitions" % len(np_))
    check("headers identical to the base", all(a.header == b.header for a, b in zip(bp, np_)))
    pb, pn = [p.plain() for p in bp], [p.plain() for p in np_]
    declared = {0: list(sites0) + list(order_sites), 1: list(sites1)}
    total = 0
    for i, (a, b) in enumerate(zip(pb, pn)):
        runs = A.merged_ranges(a, b)
        n = sum(e - s for s, e in runs)
        total += n
        rep["changed"][i] = dict(bytes=n, n_ranges=len(runs), ranges=[(hex(s), e - s) for s, e in runs][:64])
        sites = []
        for o, ln, nt in sorted(declared.get(i, [])):                  # adjacent / overlapping declared sites form one interval
            if sites and o <= sites[-1][0] + sites[-1][1]:
                sites[-1] = (sites[-1][0], max(sites[-1][1], o + ln - sites[-1][0]), sites[-1][2])
            else:
                sites.append((o, ln, nt))
        outside = [(s, e) for s, e in runs if not any(s >= o and e <= o + ln for o, ln, _ in sites)]
        check("partition %d: every changed byte lies inside the declared sites" % i, not outside,
              "%d bytes in %d runs%s" % (n, len(runs), "; OUTSIDE: " + ", ".join("%#x+%d" % (s, e - s) for s, e in outside[:8]) if outside else ""))
    check("partition 2 unchanged", pb[2] == pn[2] if len(pb) > 2 else True)
    rep["total_changed_bytes"] = total
    p0n, p0b = bytearray(pn[0]), bytearray(pb[0])
    for va, ln, what in S.HOMES:
        o = S.off(va)
        declared_in = any(o < so + sl and so < o + ln for so, sl, _ in declared[0])
        check("%s %#x+%d untouched" % (what, va, ln), o + ln <= len(p0b) and p0n[o:o + ln] == p0b[o:o + ln] and not declared_in)
    try:
        S.check_layout(p0n)
        S.check_hue_count(S.hue_count(p0n))
        check("slot layout intact (descriptors, bounds), hue-table count <= 1", True)
        for s in S.WRITABLE:
            rb, rn = S.read_slot(p0b, s), S.read_slot(p0n, s)
            if s in touched:
                t = touched[s]
                want = dict(L16=list(t["L16"]), t3=[list(map(int, y)) for y in t["t3"]], t2=list(map(int, t["t2"])))
                check("slot %d reads back as intended (matrix, T3, T2)" % s, dict(L16=rn["L16"], t3=rn["t3"], t2=rn["t2"]) == want)
                check("slot %d base mode unchanged" % s, S.base_mode(p0n, s, S.TBLA_ROWS + 1) == S.base_mode(p0b, s))
            else:
                check("slot %d (untouched) matrix / T3 / T2 identical" % s, rn == rb)
    except (S.SlotError, ValueError) as e:
        check("slot read back", False, str(e))
    try:
        book_b, book_n = N.NameBook(bytearray(pb[1])), N.NameBook(bytearray(pn[1]))
        for s in range(1, S.NSLOT + 1):
            want = (touched.get(s) or {}).get("name") or renamed.get(s)
            now = book_n.current_name(s)
            if want:
                check("name of slot %d reads back as %r in 34 languages, all ids" % (s, want), now == want)
            else:
                check("name of slot %d (untouched) identical" % s, now == book_b.current_name(s))
        p1n, p1b = bytearray(pn[1]), bytearray(pb[1])
        for s in range(1, S.NSLOT + 1):
            if s in touched and touched[s].get("roll"):
                for nm, ok, detail in IC.check(p0n, p1n, s, ids=IC.ids_of(p0b, s)):
                    check("slot %d: %s" % (s, nm), ok, detail)
            else:
                bad = False
                for iid in IC.ids_of(p0b, s):
                    h = IC.header(p1n, iid)
                    bad |= p1n[h["df"]:h["df"] + h["size"]] != p1b[h["df"]:h["df"] + h["size"]]
                check("icons of slot %d (untouched) identical" % s, not bad)
    except (S.SlotError, N.NameError_, IC.IconError, ValueError, KeyError, IndexError, struct.error) as e:
        check("name / icon read back", False, str(e))
    return rep


def build_pack(base_bin, pack_path, lut_dir=None, gate=B.GATE, allow_other_base=False, log=print, battery=True):
    """-> dict(image, report, audit, battery). Raises PackError / BuildError: nothing is produced."""
    data, warns = load_pack(pack_path)
    pack = data["pack"]
    sha = hashlib.sha1(base_bin).hexdigest()
    if sha != pack["base"]["sha1"]:
        raise PackError("this image (sha1 %s) is not the image the pack was made for (%s %s)" % (sha[:12], pack["base"].get("name", "?"), pack["base"]["sha1"][:12]))
    parts = B.check_base(base_bin, allow_other_base)
    p0b = bytearray(parts[0].plain())
    try:
        S.check_layout(p0b)
    except S.SlotError as e:
        raise PackError(str(e))
    looks = data.get("looks") or []
    cur, touched, reports = base_bin, {}, []
    sites0, sites1 = [], []
    for i, look in enumerate(looks):
        slot = look["slot"]
        src = look.get("source") or {}
        lut = find_lut(lut_dir, src)
        log("--- look %d/%d: slot %d %r%s" % (i + 1, len(looks), slot, look.get("name"), "" if lut else " (no source table found: target-free gate)"))
        icon_keep = look.get("icon", "roll") == "keep"
        res = B.build(cur, None, slot=slot, lut_path=lut, gate=gate, allow_other_base=True, log=log, name=look.get("name"), keep_icon=icon_keep,
                      look_obj=(data, look, []))
        cur = res["image"]
        touched[slot] = dict(res["tables"], name=look.get("name"), roll=not icon_keep)
        rep = dict(res["report"])
        rep.pop("warnings", None)
        reports.append(rep)
        for va, n, note in S.sites(slot):
            sites0.append((va - S.P0_BASE, n, note))
        book = N.NameBook(bytearray(C.split_image(base_bin)[1].plain()))
        for _l, _sid, off, n, _pre in book.sites_for(slot, look.get("name")):
            sites1.append((off, n, "name slot %d" % slot))
        if not icon_keep:
            for off, n, note in IC.sites(p0b, bytearray(C.split_image(base_bin)[1].plain()), slot):
                sites1.append((off, n, note))
    # ---- renames of the slots the pack does not replace
    renamed = {}
    p1n = bytearray(C.split_image(cur)[1].plain())
    book = N.NameBook(p1n)
    for k, nm in sorted((pack.get("renames") or {}).items(), key=lambda kv: int(kv[0])):
        s = int(k)
        if s in touched:
            continue
        try:
            for off, n in N.write_name(p1n, book, s, nm):
                sites1.append((off, n, "rename slot %d" % s))
        except (N.NameError_, ValueError) as e:
            raise PackError("rename of slot %d: %s" % (s, e))
        renamed[s] = nm
        log("rename slot %d -> %r" % (s, nm))
    parts_cur = C.split_image(cur)
    p0n = bytearray(parts_cur[0].plain())
    # ---- order + hide
    order, hidden = list(pack.get("order") or []), list(pack.get("hidden") or [])
    if hidden:
        raise PackError("hide is experimental and not available: it has not been proven on a camera, so this builder refuses it")
    order_info = None
    order_sites = []
    if order or hidden:
        try:
            from . import order88 as O
        except ImportError as e:
            raise PackError("order / hidden need lookbuild/order88.py (%s)" % e)
        try:
            p0_pre = bytearray(p0n)                     # after the slot writes, before the reorder: the reference of the order verification
            plan = O.plan(p0n, order, hidden)
            O.apply(p0n, plan)
        except O.OrderError as e:
            raise PackError("order / hide refused: %s" % e)
        order_sites = list(plan.sites())
        order_info = dict(order=list(plan.order), hidden=list(plan.hidden), edits=len(plan.edits), bytes=sum(len(e[1]) for e in plan.edits))
        log("order: %s ... (%d edits, %d bytes); hidden %s" % (plan.order[:8], order_info["edits"], order_info["bytes"], plan.hidden))
        vr = O.verify(p0_pre, p0n, order, hidden)
        badv = [x for x in vr if not x[1]]
        if badv:
            raise PackError("order / hide verification failed: " + "; ".join("%s (%s)" % (a, c) for a, _b, c in badv[:4]))
    image = C.join_image([C.with_plain(parts_cur[0], bytes(p0n)), C.with_plain(parts_cur[1], bytes(p1n))] + parts_cur[2:])
    # ---- audit
    au = audit_pack(base_bin, image, touched, renamed, sites0, sites1, order_sites)
    if not au["ok"]:
        raise PackError("the pack audit failed:\n" + A.format_report(dict(au, slot="pack")))
    # ---- acceptance battery
    bat = None
    if battery:
        try:
            from . import accept88 as AC
        except ImportError as e:
            raise PackError("the acceptance battery (accept88.py) is missing: %s. Refusing to build without it" % e)
        bat = AC.run(base_bin, image, dict(replaced={s: t["name"] for s, t in touched.items()}, renamed=renamed, order=order, hidden=hidden,
                                           keep_icon=[s for s, t in touched.items() if not t["roll"]]))
        failed = [r for r in bat if r[1] == "FAIL"]
        if failed:
            raise PackError("the acceptance battery failed (nothing built):\n" + "\n".join("  %s: %s" % (r[0], r[2]) for r in failed[:12]))
    report = dict(pack=pack.get("name"), base=pack["base"], sha1=hashlib.sha1(image).hexdigest(), looks=reports, renamed=renamed, order=order_info, hidden=hidden,
                  audit_total_changed=au["total_changed_bytes"], battery=("UNCHECKED" if bat is None else [dict(id=r[0], status=r[1], detail=r[2]) for r in bat]),
                  warnings=warns)
    return dict(image=image, report=report, audit=au, battery=bat)
