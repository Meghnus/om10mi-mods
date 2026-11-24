// pack.js - look pack I/O + validation (PACK_SPEC_v2.md), pure functions, no DOM: runs in node and in the browser.
// Mirrors lookfile/lookfile_check.py (check_pack + the per-look rules of a pack) and lookbuild/pack.py: the Python checker stays the authority.
// State shape (JSON-friendly): { name, base:{name, sha1}, arrangement:[38 items, top to bottom, i-Enhance implied first], hidden:[slots],
//   names:{slot: menu name}, looks:{slot: look object (buildLookFile output, one look)} }.  Items: look slot = integer 1..18, stock item = string.
// L = parsed panel-slots.json.

export const MAX_BYTES = 1 << 20;
export const PACK_KEYS = ["name", "base", "order", "hidden", "renames"];
const HEX40 = /^[0-9a-f]{40}$/;
const ASCII = /^[\x20-\x7e]*$/;
export const isSlot = (x) => Number.isInteger(x) && x >= 1 && x <= 18;
export const slotMode = (L, s) => L.slots[String(s)].mode;
export const slotCap = (L, s) => L.slots[String(s)].cap;
export const isItem = (L, x) => isSlot(x) || (typeof x === "string" && L.stock_items.includes(x));
export const itemKey = (x) => (typeof x === "number" ? "s" + x : "t" + x);
export const itemLabel = (L, x) => (typeof x === "number" ? "slot " + x + " (" + L.slots[String(x)].stock + ")" : x);

// ---- names ------------------------------------------------------------------------------------------------------------------
// "" if ok (names88.check_name rules + the capacity of the slot)
export function nameProblem(L, slot, name) {
  if (typeof name !== "string" || !name) return "name must not be empty";
  if (name !== name.trim()) return "name must not start or end with a space";
  if (!ASCII.test(name) || name.includes("@")) return "printable ASCII only, no '@'";
  const cap = slotCap(L, slot);
  if (name.length > cap) return `${name.length} characters, slot ${slot} holds at most ${cap}`;
  return "";
}
export const sanitizeName = (s) => String(s).replace(/@/g, "").replace(/[^\x20-\x7e]/g, "");

// ---- order ------------------------------------------------------------------------------------------------------------------
export const applyOrder = (base, order) => order.concat(base.filter((x) => !order.includes(x)));
const same = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

// the shortest `order` that turns the base list into `arr` as far as the camera can show it (hidden items do not count: they are not in the
// lists, and the spec forbids them in `order`)
export function derivePrefix(base, arr, hidden = []) {
  const H = new Set(hidden), bv = base.filter((x) => !H.has(x)), av = arr.filter((x) => !H.has(x));
  for (let k = 0; k <= av.length; k++) {
    const pre = av.slice(0, k);
    if (same(applyOrder(bv, pre), av)) return pre;
  }
  return av;
}

export function move(arr, from, to) {
  const a = arr.slice();
  if (from === to || from < 0 || from >= a.length) return a;
  const [x] = a.splice(from, 1);
  a.splice(Math.max(0, Math.min(a.length, to)), 0, x);
  return a;
}

// ---- state <-> pack object ---------------------------------------------------------------------------------------------------
export function emptyState(L, release = 0) {
  const r = L.releases[release] || L.releases[0], names = {};
  for (const s of Object.keys(L.slots)) names[s] = L.slots[s].stock;
  return { name: "", base: { name: r.name, sha1: r.sha1 }, arrangement: L.base_order.slice(), hidden: [], names, looks: {} };
}

export function buildPack(L, st) {
  const hidden = st.hidden.slice().sort((a, b) => a - b), order = derivePrefix(L.base_order, st.arrangement, hidden);
  const renames = {};
  for (const s of Object.keys(L.slots)) if (!st.looks[s] && st.names[s] !== L.slots[s].stock) renames[s] = st.names[s];
  const pack = {};
  if (st.name) pack.name = st.name;
  pack.base = { name: st.base.name, sha1: st.base.sha1 };
  if (order.length) pack.order = order;
  if (hidden.length) pack.hidden = hidden;
  if (Object.keys(renames).length) pack.renames = renames;
  const looks = Object.keys(st.looks).map(Number).sort((a, b) => a - b).map((s) => {
    const { slot: _s, name: _n, ...rest } = st.looks[s];
    return { slot: s, name: st.names[s], ...rest };
  });
  return { format: "om10mi-look", version: 2, target: "E113", generator: { name: "om10mi-lut-web", version: "0.2", model: "cm-v2-web1" }, pack, looks };
}

// ---- validation (mirror of lookfile_check.check + check_pack) ---------------------------------------------------------------
// returns { errors: [{where, msg, slot?}], warnings: [...] }
export function validateObject(L, obj, { size = 0 } = {}) {
  const errors = [], warnings = [];
  const err = (where, msg, slot) => errors.push({ where, msg, slot });
  const warn = (where, msg, slot) => warnings.push({ where, msg, slot });
  if (size > MAX_BYTES) err("file", "larger than 1 MiB");
  if (!obj || typeof obj !== "object" || Array.isArray(obj)) { err("file", "top level must be an object"); return { errors, warnings }; }
  if (obj.format !== "om10mi-look") err("file", 'format must be "om10mi-look"');
  if (obj.version !== 2) err("file", "version must be 2 (a pack is a look file v2)");
  if (obj.target !== "E113") err("file", 'target must be "E113" (E-M10 Mark I)');
  for (const k of Object.keys(obj)) if (!["format", "version", "target", "generator", "looks", "pack"].includes(k)) err("file", "unknown key " + JSON.stringify(k));
  const looks = obj.looks;
  if (!Array.isArray(looks) || looks.length > L.max_looks) { err("file", `looks must be a list of at most ${L.max_looks} objects`); return { errors, warnings }; }
  const pack = obj.pack;
  const hasPack = pack !== undefined;
  const hidden = hasPack && pack && Array.isArray(pack.hidden) && pack.hidden.every(isSlot) ? pack.hidden : [];
  const seen = new Set();
  looks.forEach((l, i) => {
    const w = `looks[${i}]`;
    if (!l || typeof l !== "object" || Array.isArray(l)) { err(w, "must be an object"); return; }
    const s = l.slot;
    if (s === undefined || s === null) { if (hasPack) err(w, "a pack look needs its slot"); }
    else if (!isSlot(s)) err(w, "slot must be an integer 1..18");
    else if (s === 2) err(w, "slot 2 is reserved (Monotone only): it can be renamed, moved or hidden, never replaced", 2);
    else if (seen.has(s)) err(w, `slot ${s} used twice`, s);
    else seen.add(s);
    if (typeof l.name !== "string" || !l.name) err(w, "name is required (non-empty string)", isSlot(s) ? s : undefined);
    else if (isSlot(s)) { const p = nameProblem(L, s, l.name); if (p) err(w, `name ${JSON.stringify(l.name)}: ${p}`, s); }
    if (l.icon !== undefined && l.icon !== "roll" && l.icon !== "keep") err(w, 'icon must be "roll" or "keep"', isSlot(s) ? s : undefined);
    if (hasPack) {
      if (!l.fit || typeof l.fit !== "object") err(w, "a pack look needs a fit block (cm-v2-web1)", isSlot(s) ? s : undefined);
      else if (isSlot(s) && l.fit.mode !== slotMode(L, s)) err(w, `slot ${s} has the base mode ${slotMode(L, s)} but the look was fitted on ${l.fit.mode} (a look only goes into a slot of its base mode)`, s);
      if (isSlot(s) && hidden.includes(s)) warn(w, `slot ${s} is hidden: its new look cannot be selected in the camera`, s);
    }
  });
  if (!hasPack) return { errors, warnings };
  const w = "pack";
  if (!pack || typeof pack !== "object" || Array.isArray(pack)) { err(w, "must be an object"); return { errors, warnings }; }
  for (const k of Object.keys(pack)) if (!PACK_KEYS.includes(k)) err(w, "unknown key " + JSON.stringify(k));
  if (pack.name !== undefined && !(typeof pack.name === "string" && pack.name.length <= 40 && ASCII.test(pack.name))) err(w, "name must be at most 40 printable ASCII characters");
  const b = pack.base;
  if (!b || typeof b !== "object" || Array.isArray(b)) err(w, "base {name, sha1} is required");
  else {
    for (const k of Object.keys(b)) if (k !== "name" && k !== "sha1") err(w + ".base", "unknown key " + JSON.stringify(k));
    if (typeof b.sha1 !== "string" || !HEX40.test(b.sha1)) err(w + ".base", "sha1 must be 40 lower-case hex digits (the exact release image the pack is for)");
    if (b.name !== undefined && !(typeof b.name === "string" && b.name.length <= 24)) err(w + ".base", "name must be a string of at most 24 characters");
  }
  const hid = pack.hidden === undefined ? [] : pack.hidden, ord = pack.order === undefined ? [] : pack.order;
  const dist = (a) => new Set(a.map((x) => itemKey(x))).size === a.length;
  if (!Array.isArray(hid) || !hid.every(isSlot) || !dist(hid)) err(w, "hidden must be a list of distinct look slots 1..18");
  if (!Array.isArray(ord) || !ord.every((x) => isItem(L, x)) || !dist(ord)) err(w, "order must be a list of distinct look slots (integers 1..18) / stock items (Vivid, Natural, ... ART12)");
  else if (Array.isArray(hid)) { const both = ord.filter((x) => typeof x === "number" && hid.includes(x)); if (both.length) err(w, "hidden slots cannot also be in order: " + both.join(", ")); }
  const rn = pack.renames === undefined ? {} : pack.renames;
  if (!rn || typeof rn !== "object" || Array.isArray(rn)) err(w, "renames must be an object {slot: name}");
  else for (const [k, v] of Object.entries(rn)) {
    if (!/^[0-9]+$/.test(k) || !isSlot(Number(k))) { err(w + ".renames", `key ${JSON.stringify(k)} is not a slot 1..18`); continue; }
    const s = Number(k), p = nameProblem(L, s, v);
    if (p) err(w + ".renames", `name of slot ${s}: ${p}`, s);
    if (seen.has(s)) warn(w + ".renames", `slot ${s} is also in looks[]: its looks[] name wins`, s);
  }
  return { errors, warnings };
}

// editor-level problems on the live state (invariants the UI should never break, plus what the exported file will be checked for)
export function validateState(L, st) {
  const obj = buildPack(L, st), r = validateObject(L, obj);
  const items = L.base_order, a = st.arrangement;
  if (a.length !== items.length || !items.every((x) => a.includes(x))) r.errors.push({ where: "list", msg: "internal: the list is not a permutation of the 38 items" });
  return r;
}

// pack object -> state (null state if the file has errors). A plain look file (no `pack`) loads its looks that carry a slot.
export function parsePack(L, obj) {
  const r = validateObject(L, obj);
  if (r.errors.length) return { state: null, errors: r.errors, warnings: r.warnings };
  const st = emptyState(L), p = obj.pack || {};
  if (obj.pack === undefined) r.warnings.push({ where: "file", msg: "no `pack` key: only the looks that carry a slot are loaded; base release left at " + st.base.name });
  else st.base = { name: p.base.name || "", sha1: p.base.sha1 };
  st.name = p.name || "";
  st.hidden = (p.hidden || []).slice().sort((a, b) => a - b);
  st.arrangement = applyOrder(L.base_order, p.order || []);
  for (const [k, v] of Object.entries(p.renames || {})) st.names[k] = v;
  for (const l of obj.looks) {
    if (!isSlot(l.slot)) { r.warnings.push({ where: "looks", msg: "look " + JSON.stringify(l.name) + " has no slot: skipped" }); continue; }
    st.looks[l.slot] = JSON.parse(JSON.stringify(l));
    st.names[l.slot] = l.name;
  }
  return { state: st, errors: [], warnings: r.warnings };
}

// ---- build command + file names -----------------------------------------------------------------------------------------------
export const packFileName = (st) => (st.name || "my_pack").replace(/[^\w.-]+/g, "_").slice(0, 40) + ".pack.json";
export const buildCommand = (st) => `python looktool/om10mi_look.py --pack ${packFileName(st)} --base YOUR_IMAGE.BIN --out DIR --lut-dir DIR_OF_YOUR_LUTS`;
// the table files the builder will look for in --lut-dir (it re-scores each look exactly when it finds its table)
export const lutFiles = (st) => Object.keys(st.looks).map(Number).sort((a, b) => a - b).map((s) => ({ slot: s, file: st.looks[s].source && st.looks[s].source.name }));

// ---- share link: deflate-raw + base64url of the compact JSON (lives in the URL fragment, which the browser never sends to a server) -----
const FRAG = "pack=";
function b64u(u8) {
  let s = "";
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function unb64u(t) {
  if (!/^[A-Za-z0-9_-]*$/.test(t)) throw new Error("share link: not base64url");
  const s = atob(t.replace(/-/g, "+").replace(/_/g, "/")), u = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i);
  return u;
}
async function pipe(bytes, stream, cap = Infinity) {
  const rd = new Blob([bytes]).stream().pipeThrough(stream).getReader(), parts = [];
  let n = 0;
  for (;;) {
    const { done, value } = await rd.read();
    if (done) break;
    n += value.length;
    if (n > cap) { await rd.cancel(); throw new Error("share link: expands to more than " + cap + " bytes"); }
    parts.push(value);
  }
  const out = new Uint8Array(n);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}
export async function shareEncode(obj) {
  return FRAG + b64u(await pipe(new TextEncoder().encode(JSON.stringify(obj)), new CompressionStream("deflate-raw")));
}
export async function shareDecode(fragment) {
  const f = fragment.replace(/^#/, "");
  if (!f.startsWith(FRAG)) throw new Error("share link: no pack= fragment");
  const raw = await pipe(unb64u(f.slice(FRAG.length)), new DecompressionStream("deflate-raw"), MAX_BYTES);
  return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
}
