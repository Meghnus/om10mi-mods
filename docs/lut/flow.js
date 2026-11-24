// flow.js - the pure part of the panel's flow "import a LUT -> pick a slot -> name it -> see before/after -> add to pack" (no DOM, no model):
// file classification for drag and drop, the slots a base mode offers, name suggestion, menu-position anchors. Runs in node and in the browser.
// It only produces and rearranges pack.js state (arrangement / names); the pack and look file formats are pack.js and lookfile.js, untouched.
import * as P from "./pack.js";

// ---- dropped / chosen files ------------------------------------------------------------------------------------------------------
// "lut" (.cube / Adobe .xmp), "pack" (.json), "photo" (preview picture), "other"
export function classifyFile(name, type = "") {
  const n = String(name).toLowerCase();
  if (/\.(cube|xmp)$/.test(n)) return "lut";
  if (/\.json$/.test(n) || type === "application/json") return "pack";
  if (/\.(jpe?g|png|webp|gif|bmp|avif)$/.test(n) || /^image\//.test(type)) return "photo";
  return "other";
}
// first file of each kind wins, the rest is counted: { lut, pack, photo, ignored: [names] }
export function sortDrop(files) {
  const out = { lut: null, pack: null, photo: null, ignored: [] };
  for (const f of files) {
    const k = classifyFile(f.name, f.type);
    if (k !== "other" && !out[k]) out[k] = f; else out.ignored.push(f.name);
  }
  return out;
}

// ---- slots of a base mode ---------------------------------------------------------------------------------------------------------
export const writableSlots = (L, mode) => Object.keys(L.slots).map(Number).filter((s) => L.slots[s].mode === mode && L.slots[s].writable);

// the base modes a LUT can go to, best first: [{mode, candidate, dE, pct_lt5, slots}]; ranking = Ranker.stage1().ranking (sorted by dE, any order accepted)
export function modeChoices(L, ranking) {
  const best = new Map();
  for (const e of ranking) { const b = best.get(e.mode); if (!b || e.dE < b.dE) best.set(e.mode, e); }
  return [...best.values()].sort((a, b) => a.dE - b.dE)
    .map((e) => ({ mode: e.mode, candidate: e.candidate, dE: e.dE, pct_lt5: e.pct_lt5, slots: writableSlots(L, e.mode) }))
    .filter((c) => c.slots.length);
}

// the slots offered for `mode`, in current menu order
export function slotChoices(L, st, mode) {
  const set = new Set(writableSlots(L, mode));
  return st.arrangement.filter((it) => typeof it === "number" && set.has(it))
    .map((s) => ({ slot: s, stock: L.slots[s].stock, name: st.names[s], cap: P.slotCap(L, s), hasLook: !!st.looks[s], hidden: st.hidden.includes(s) }));
}
// keep `prefer` when the mode offers it, else the first slot that still holds a stock look, else the first slot; null when none
export function defaultSlot(L, st, mode, prefer = null) {
  const c = slotChoices(L, st, mode);
  if (!c.length) return null;
  if (prefer != null && c.some((x) => x.slot === prefer)) return prefer;
  return (c.find((x) => !x.hasLook) || c[0]).slot;
}

// "teal_orange.cube" -> "teal_orange" cut to the capacity of the slot (printable ASCII, no '@', no edge spaces)
export function suggestName(L, slot, fileName) {
  return P.sanitizeName(String(fileName).replace(/\.[^.]*$/, "")).trim().slice(0, P.slotCap(L, slot)).trim();
}

// ---- menu position ------------------------------------------------------------------------------------------------------------------
export const itemName = (st, it) => (typeof it === "number" ? st.names[it] : it);

// anchors for "place after ...": every item of the list except `slot` itself; value = P.itemKey, `top` = first after i-Enhance
export function anchorChoices(st, slot) {
  const out = [{ value: "top", item: null, label: "At the top (after i-Enhance)" }];
  for (const it of st.arrangement) if (it !== slot) out.push({ value: P.itemKey(it), item: it, label: "After " + itemName(st, it) });
  return out;
}
export const anchorValue = (arr, item) => { const i = arr.indexOf(item); return i <= 0 ? "top" : P.itemKey(arr[i - 1]); };
export const anchorItem = (st, value) => (value === "top" ? null : st.arrangement.find((it) => P.itemKey(it) === value));

// `item` moved to directly after `anchor` (null = first); a no-op when anchor is the item itself
export function placeAfter(arr, item, anchor) {
  if (anchor === item) return arr.slice();
  const a = arr.filter((x) => x !== item);
  a.splice(anchor === null ? 0 : a.indexOf(anchor) + 1, 0, item);
  return a;
}
// `item` moved to directly before `ref` (null = end)
export function moveBefore(arr, item, ref) {
  if (ref === item) return arr.slice();
  const a = arr.filter((x) => x !== item);
  a.splice(ref === null ? a.length : a.indexOf(ref), 0, item);
  return a;
}
// one step up (dir -1) / down (+1) among the items `visible(it)` accepts; the items between that are not shown stay where they are
export function stepVisible(arr, item, dir, visible = () => true) {
  const vis = arr.filter((x) => x === item || visible(x)), i = vis.indexOf(item);
  if (i < 0) return arr.slice();
  if (dir < 0) return i === 0 ? arr.slice() : moveBefore(arr, item, vis[i - 1]);
  return i === vis.length - 1 ? arr.slice() : placeAfter(arr, item, vis[i + 1]);
}
