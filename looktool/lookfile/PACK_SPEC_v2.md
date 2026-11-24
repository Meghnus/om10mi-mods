# om10mi look pack (Stage A of the control panel) - addition to the look file v2

A pack is a normal look file v2 (`format "om10mi-look"`, `version 2`, `looks[]` made by the web app) plus ONE optional top-level key `"pack"`.
A file without `pack` is an ordinary look file; the builder `--pack` needs it. Unknown keys inside `pack` are an error (typos must not pass).

```jsonc
{ "format": "om10mi-look", "version": 2, "target": "E113",
  "generator": {"name": "om10mi-lut-web", "version": "0.2", "model": "cm-v2-web1"},
  "pack": {
    "name": "my pack",                                   // optional label, <= 40 printable ASCII
    "base": {"name": "v94", "sha1": "<40 hex>"},         // REQUIRED for the builder: the exact release BIN the pack was made for; any other image is refused
    "order": [11, 7, 6, "Portrait"],                     // optional: items that go to the TOP of the Picture Mode list, in this sequence (see below)
    "hidden": [12],                                      // optional: look slots made unreachable in the shooting UI (see below)
    "renames": {"3": "Provia X"}                         // optional: slot -> new menu name for slots that are NOT in looks[] (a looks[] name wins)
  },
  "looks": [ { "slot": 11, "name": "Teal Orange", "icon": "roll",   // slot REQUIRED in a pack; icon "roll" (default) | "keep"
               "source": {...}, "base": {...}, "fit": {...} } ]       // the web-made look object, unchanged
}
```

## Items and order
* A **look slot** is an integer 1..18 (slot 2 = Acros, monotone; it can be renamed / moved / hidden but never replaced).
* A **stock item** is one of `"Vivid" "Natural" "Muted" "Portrait" "Monotone" "Custom" "e-Portrait" "Color Creator" "ART1" .. "ART12"`.
* `i-Enhance` is always first and the spare record is always last: they cannot be named in `order`/`hidden` (the builder enforces both).
* `order` = the items named, in that sequence, are placed directly after i-Enhance; every other item follows in the order the base image has now.
  Duplicates / unknown items / hidden items inside `order` are errors. Naming all 38 items (18 look slots + 20 stock items; i-Enhance is fixed first) gives a complete permutation.
* Shown order in the camera: Picture Mode menu, SCP picker, Live Control strip, dial / arrow stepping (and the other lists that follow them in the image).
* GUI values, selectors, base modes, per-look data, icons and names never move with the order: only the row order of the lists changes.

## hidden
* **Not available in this release.** The builder refuses a pack with `hidden` (it has not been proven on a camera). The text below describes the experimental design only.
* `hidden` = look slots that the shooting UI cannot reach (dial stepping skips them; their rows are absent from the Picture Mode menu, SCP and Live Control lists). Their data and the rows that a stored
  RAW / Myset needs to resolve the value are kept, so a RAW already shot with a hidden look still develops.
* Stock items cannot be hidden in stage A. At least 1 look slot per base mode family is not required.

## Per-look
* `looks[]` entries must satisfy `lookfile_check` (v2) and carry `fit` (model cm-v2-web1), `fit.mode` = the base mode of their slot (same-base rule), `name` within the slot's capacity (`names88.NAME_CAP`).
* Several looks may be given; each is built exactly like `om10mi_look.py --look --slot`: tone lift, dE gate (0.5), roll icon (unselected + selected, no text), name x 34 languages.
* `source.sha256` ties the look to the table it was fitted from; `--lut-dir DIR` lets the builder find `source.name` there and re-score exactly (gate against `fit.predicted.dE`); a missing table uses the target-free gate.

## Builder (`om10mi_look.py --pack FILE --base BIN --out DIR [--lut-dir DIR]`)
validate -> base sha1 == `pack.base.sha1` -> per look (fit, lift, gate, write slot data + name + roll icon) -> renames -> order -> hide -> confinement audit -> acceptance battery (every look
the pack touches: menu / SCP / LC, basic functions, RAW Data Edit, LCD + EVF-relevant tables) -> checksums. A failing step builds nothing (exit 1, no BIN). Output `E113_PACK_TEST.BIN` (or `DCOLYMP/E1139999.BIN` with `--card`), `pack_report.json`, `audit.txt`.
