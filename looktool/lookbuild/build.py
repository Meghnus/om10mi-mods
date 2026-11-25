"""build.py - local builder path: a v2 look file (cm-v2-web1 fit) -> one look slot of the user's own release-layout image.

Steps (every one fail-closed; nothing is written unless all pass):
  1  the base image is the published release layout (sha1) and parses; the look file passes lookfile_check (no errors);
  2  slot / base-mode rule: the slot's base mode (value-map record) must equal fit.mode - the writer never touches the base-mode sites;
  3  matrix: E = fit.matrix_orf -> L16 = solve_l(E) -> composed |c| < 1024 (olylook check_matrix);  E_act = the ORF matrix the camera applies;
  4  tone lift (lift.py) with the user's own T1 / T2_m (camera.CamTables): T3 3 x 9, T2 256, monotone, 10 bit;
  5  re-score with the exact model on ref-syn-1 and refuse beyond the gate:
       with the source LUT (sha256 = source.sha256): |dE_exact - fit.predicted.dE| > gate   (lut_PLAN section 7)
       without it: the mean web-vs-exact picture difference on ref-syn-1 > gate (target-free)
  6  write the slot (slots88.write_slot), rebuild the container (footer checksums), run the confinement audit.
"""
import hashlib
import json
import os
import sys

from . import audit as A
from . import composed as CO
from . import container as C
from . import icons88 as IC
from . import names88 as N
from . import slots88 as S

HERE = os.path.dirname(os.path.abspath(__file__))
LUT1 = os.path.normpath(os.path.join(HERE, ".."))
RELEASE_SHA1 = "baf96f07b86f40aa91bb100a3658f64d9ed4dcf2"          # release 94
RELEASE_SIZE = 70254592
# the pinned base: the version 94 image that om10mi.py builds from your own official firmware (the layout is checked at runtime too)
KNOWN_BASES = {RELEASE_SHA1: "release 94"}
GATE = 0.5


class BuildError(Exception):
    """a refusal: nothing was written"""


class GateRefused(BuildError):
    """a dE gate refused the look (kind "lut": exact model vs the look file's prediction with the LUT; "model": exact vs browser model without it); .mode = base picture mode"""
    def __init__(self, text, kind, look_name, mode, de, ref, gate):
        self.kind, self.look_name, self.mode, self.de, self.ref, self.gate = kind, look_name, mode, de, ref, gate
        BuildError.__init__(self, text)


class LutNotFound(BuildError):
    """the look's source LUT was not available, and the stricter target-free check (the only one possible without it) refused the look"""
    def __init__(self, lut_name, look_name, de, gate):
        self.lut_name, self.look_name, self.de, self.gate = lut_name, look_name, de, gate
        BuildError.__init__(self, "LUT file %s not found in --lut-dir / zip (needed by look %r). Without it only the stricter target-free check can run, "
                            "and it refused the look (%.3f dE > %.2f). Put the exact file you imported in the panel (same name, unmodified) "
                            "next to the pack (--lut-dir), or use the .omlook.zip export that carries it. Not written" % (lut_name, look_name, de, gate))


def _lookfile_check():
    for p in (os.path.join(LUT1, "lookfile"), os.path.join(LUT1, "lutimport")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import lookfile_check
    return lookfile_check


def load_look(path, index=0):
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise BuildError("cannot read the look file: %s" % e)
    rep = _lookfile_check().check(data, len(raw))
    if rep.errors:
        raise BuildError("look file refused by the checker: " + "; ".join(rep.errors[:6]))
    looks = data.get("looks") or []
    if not 0 <= index < len(looks):
        raise BuildError("the look file has %d look(s); --index %d is out of range" % (len(looks), index))
    return data, looks[index], rep.warnings


def check_base(base_bin, allow_other=False):
    sha = hashlib.sha1(base_bin).hexdigest()
    if (sha not in KNOWN_BASES or len(base_bin) != RELEASE_SIZE) and not allow_other:
        raise BuildError("the base image (sha1 %s) is not a pinned base (%s). Build it from your own firmware with om10mi.py first"
                         % (sha[:12], "; ".join("%s %s" % (v, k[:8]) for k, v in KNOWN_BASES.items())))
    try:
        parts = C.split_image(base_bin)
    except C.ContainerError as e:
        raise BuildError(str(e))
    problems = C.check_parts(parts)
    if problems:
        raise BuildError("the base image is damaged: " + "; ".join(problems))
    return parts


def pick_slot(p0, slot, look, mode):
    compat = S.slots_for_mode(p0, mode)
    if slot is None:
        slot = look.get("slot")
    if slot is None:
        raise BuildError("no slot given: pass --slot N or set `slot` in the look file. Slots whose base mode is %s: %s" % (mode, ", ".join(map(str, compat))))
    if slot not in S.WRITABLE:
        raise BuildError("slot %s cannot be written (1..%d except 2)" % (slot, S.NSLOT))
    bm = S.base_mode(p0, slot)
    if bm != mode:
        raise BuildError("slot %d has the base mode %s but the look was fitted on %s (the writer never changes a slot's base mode). Slots with %s: %s"
                         % (slot, bm, mode, mode, ", ".join(map(str, compat))))
    return slot


def tone_arrays(fit):
    tone = fit.get("tone")
    if tone is None:
        return None, None, "yb"
    cc, yc = tone.get("c_curves") or {}, tone.get("y_curve")
    d33 = [[p[1] for p in cc[c]] for c in "rgb"]
    h33 = [p[1] for p in yc]
    return d33, h33, tone.get("luma_arg", "yb")


def lut_target(lut_path, source, base, per, K):
    """target Lab of the source LUT on ref-syn-1 (sha256 must equal source.sha256); None when no LUT was given"""
    if lut_path is None:
        return None
    for p in (os.path.join(LUT1, "lutimport"),):
        if p not in sys.path:
            sys.path.insert(0, p)
    import import_lut
    with open(lut_path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    if source.get("sha256") and source["sha256"].lower() != sha:
        raise BuildError("--lut sha256 %s does not equal source.sha256 %s" % (sha[:12], source["sha256"][:12]))
    r = import_lut.import_any(lut_path)[0]
    return K.rgb2lab(K.lut_apply(r.lut33, base, source.get("space", "display")))


def build(base_bin, look_path, slot=None, lut_path=None, index=0, gate=GATE, allow_other_base=False, model_path=None, log=print, name=None, keep_name=False, keep_icon=False, look_obj=None):
    """-> dict(image=bytes, report=dict, audit=dict, slot=int, tables=dict). Raises BuildError (nothing produced). Needs numpy (tone lift, re-score)."""
    try:
        import numpy as np
        from . import camera as K
        from . import lift as LF
    except ImportError as e:
        raise BuildError("numpy is required for the tone lift and the re-score (%s)" % e)
    parts = check_base(base_bin, allow_other_base)
    p0_base = parts[0].plain()
    p0 = bytearray(p0_base)
    try:
        S.check_layout(p0)
    except S.SlotError as e:
        raise BuildError(str(e))
    data, look, warns = look_obj if look_obj is not None else load_look(look_path, index)
    fit = look.get("fit") or {}
    nh = sum(1 for k in ("hue_table", "per_hue_table") for d in (fit, look) if d.get(k))
    try:
        S.check_hue_count(nh)
    except S.SlotError as e:
        raise BuildError(str(e))
    if nh:
        warns.append("per-sector hue table requested: ignored, this builder writes none (hue cap 0)")
    fit = look.get("fit")
    if not fit or fit.get("model") != "cm-v2-web1":
        raise BuildError("the look has no fit block of the model cm-v2-web1 (a refit from the intent is not implemented in this builder)")
    mode = fit.get("mode")
    if fit.get("matrix_orf") is None:
        raise BuildError("fit.matrix_orf is missing: nothing to write")
    slot = pick_slot(p0, slot, look, mode)
    log("slot %d, base mode %s, look %r" % (slot, mode, look.get("name")))
    # ---- matrix
    E = [int(v) for v in fit["matrix_orf"]]
    L16 = CO.solve_l(E)
    worst = CO.composed_max_l(L16)
    if worst >= CO.LIMIT:
        raise BuildError("composed ORF coefficient %d >= 1024 (11-bit wrap) for this matrix" % worst)
    E_act = CO.orf_pred(L16)
    log("matrix: E %s -> L16 %s (composed max %d), camera applies %s" % (E, L16, worst, E_act))
    # ---- tone lift
    model = K.WebModel(model_path or K.WEB_MODEL)
    cam = K.CamTables(p0, model)
    base, per, scenes = K.synth_base()
    xS = model.base_to_x(base)
    d33, h33, luma = tone_arrays(fit)
    e_act = np.array(E_act, float)
    if d33 is None:
        t3, t2 = LF.identity_tone(cam, mode)
        info = dict(luma="-", note="matrix only: stock tone of the mode")
        web_out = model.out(xS, mode, e_act)
    else:
        t3, t2, info = LF.lift_tone(model, cam, mode, e_act, d33, h33, luma, xS)
        web_out = model.out(xS, mode, e_act, np.array(d33), np.array(h33), luma)
    exact_out = cam.out(xS, mode, e_act, t2, t3)
    lab_w, lab_e = K.rgb2lab(web_out), K.rgb2lab(exact_out)
    mism = K.de2000(lab_w, lab_e)
    rep = dict(slot=slot, mode=mode, name=look.get("name"), E=E, L16=L16, E_act=E_act, composed_max=worst, luma=luma, lift=info,
               mismatch_mean=float(mism.mean()), mismatch_p95=float(np.percentile(mism, 95)), mismatch_max=float(mism.max()), warnings=warns)
    # ---- gate
    pred = (fit.get("predicted") or {})
    tl = lut_target(lut_path, look.get("source") or {}, base, per, K)
    if tl is not None and str(pred.get("scenes", "")).startswith("ref-syn-1") and "dE" in pred:
        dw, _, _ = K.score(tl, lab_w, per)
        de, pct, _ = K.score(tl, lab_e, per)
        diff = abs(de - pred["dE"])
        rep.update(gate_kind="dE vs predicted", dE_web_recomputed=dw, dE_exact=de, pct_lt5_exact=pct, dE_predicted=pred["dE"], gap=diff, gate=gate)
        log("exact model on ref-syn-1: dE %.3f (web recomputed %.3f, file predicted %.3f), gap %.3f, gate %.2f" % (de, dw, pred["dE"], diff, gate))
        if diff > gate:
            raise GateRefused("the exact model scores %.3f dE, the look file predicts %.3f: %.3f > %.2f dE. Not written" % (de, pred["dE"], diff, gate),
                              "lut", look.get("name"), mode, de, pred["dE"], gate)
    else:
        rep.update(gate_kind="web-vs-exact picture difference (no LUT / not ref-syn-1)", gap=float(mism.mean()), gate=gate)
        log("target-free gate: mean web-vs-exact difference on ref-syn-1 %.3f dE (p95 %.2f), gate %.2f" % (mism.mean(), rep["mismatch_p95"], gate))
        if mism.mean() > gate:
            sname = (look.get("source") or {}).get("name")
            if lut_path is None and sname:
                raise LutNotFound(sname, look.get("name"), float(mism.mean()), gate)
            raise GateRefused("the exact model differs from the browser model by %.3f dE on average (> %.2f). Not written" % (mism.mean(), gate),
                              "model", look.get("name"), mode, float(mism.mean()), None, gate)
    # ---- write + audit
    try:
        written = S.write_slot(p0, slot, L16, t3, t2)
    except S.SlotError as e:
        raise BuildError("the slot writer refused: %s" % e)
    new_parts = [C.with_plain(parts[0], bytes(p0))] + parts[1:]
    allowed = {0: [(va - S.P0_BASE, n, note) for va, n, note in written]}
    new_name = None
    p1 = bytearray(parts[1].plain())
    allowed[1] = []
    if not keep_name:
        new_name = name or look.get("name")
        try:
            book = N.NameBook(p1)
            old_name = book.current_name(slot)
            w1 = N.write_name(p1, book, slot, new_name)
        except (N.NameError_, ValueError) as e:
            raise BuildError("menu name: %s (use --name SHORT or --keep-name)" % e)
        allowed[1] += [(off, n, "name slot %d" % slot) for off, n in w1]
        rep.update(name_old=old_name, name_new=new_name, name_cap=N.NAME_CAP[slot])
        log("menu name of slot %d: %r -> %r (capacity %d)" % (slot, old_name, new_name, N.NAME_CAP[slot]))
    if not keep_icon:
        try:
            w2, info = IC.write(p0, p1, slot)
        except IC.IconError as e:
            raise BuildError("icon: %s (use --keep-icon to leave the slot's icon alone)" % e)
        allowed[1] += w2
        rep.update(icon="universal film roll (no text)", icon_streams=[dict(kind=k, capacity=c, stream=u, zero_tail=t) for k, c, u, t in info])
        log("icon of slot %d: universal film roll, U %d B (stream %d + zero tail %d), S %d B (stream %d + zero tail %d)" % ((slot,) + tuple(v for _, c, u, t in info for v in (c, u, t))))
    new_parts[1] = C.with_plain(parts[1], bytes(p1))
    if not allowed[1]:
        del allowed[1]
    image = C.join_image(new_parts)
    intended = dict(L16=L16, t3=t3, t2=t2)
    au = A.audit(base_bin, image, slot, intended, allowed, base_mode=mode, name=new_name, icon=not keep_icon)
    if not au["ok"]:
        raise BuildError("the confinement audit failed:\n" + A.format_report(au))
    rep["sha1"] = hashlib.sha1(image).hexdigest()
    return dict(image=image, report=rep, audit=au, slot=slot, tables=dict(L16=L16, t3=t3, t2=t2))
