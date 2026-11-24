# LUT to E-M10 Mark I look (om10mi-lut)

A static web page that turns a colour LUT (`.cube`, Adobe Creative Profile `.xmp`) into a **look file** for the custom look slots of
[om10mi-mods](https://github.com/Meghnus/om10mi-mods) (Olympus OM-D **E-M10 Mark I**, model `0x1130`, firmware 1.4 only). The page ranks the
camera's four base picture modes and the shipped looks against your LUT, fits a matrix and tone curves in our own model of the camera, shows
the predicted result, and writes the look file. A second step on **your PC** (`looktool/om10mi_look.py`, with your own copy of the official
firmware) writes that look into one slot of the look image.

Related: [om10mi-mods](https://github.com/Meghnus/om10mi-mods) (builder, look slots, guide) and
[oly-truepic-harness](https://github.com/Meghnus/oly-truepic-harness) (the firmware analysis harness). Many people asked for ports to other
OM / Olympus cameras: use these tools.

## Use

1. Serve the folder (browsers do not run ES modules from `file://`): `python -m http.server 8765` in this folder, open `http://127.0.0.1:8765/`.
   The page is plain files: no build step, no server code, no CDN, no analytics. Your LUT and photos are read into memory only. The
   Content-Security-Policy allows connections to this site only (the page fetches its own model and samples).
2. Load a LUT (or a CC0 sample). Declare its licence and the author / source in the box (needed for CC BY / CC BY-SA tables).
3. Read the ranking, press **Fit top 3 rows** (a few seconds), pick the base, check the preview and the dE map, choose name and slot,
   **Download look file**.
4. On your PC: `python looktool/om10mi_look.py --look NAME.look.json --slot N --base YOUR_E1139999.BIN --out DIR [--lut SOURCE.cube]`. The builder
   checks the base image, the slot's base mode (a look can only go into a slot with the same base picture mode), re-scores the fit with the
   exact camera model from your own firmware tables (refuses above 0.5 dE of the file's prediction), writes only that slot, and runs a
   confinement audit. It never writes to a camera or a card by itself.

## Look list manager (`panel.html`)

A second page, same rules (static, local, no upload). **Home screen = the Picture Mode list**: i-Enhance (fixed first), the 18 look slots and the stock items
(Vivid, Natural, Muted, Portrait, Monotone, Custom, e-Portrait, Color Creator, ART1..12, greyed). Drag the handle, use the arrows or Alt+Up/Down to reorder;
the name box renames a slot (live capacity counter, printable ASCII, no `@`); `replace...` opens
the per-look editor: import a `.cube` / `.xmp`, the page ranks and fits only candidates of the slot's base picture mode (the same-base rule), shows a
before/after divider on the reference scenes, and `Accept` stores the look in the pack (recipe sliders are not part of this stage). Slot 2 (Acros,
monotone) can be renamed and moved, never replaced. Hiding a look is **not available** (not proven on a camera; the eye is disabled and the builder refuses `hidden`).

Pack I/O: **Export pack JSON** (a look file v2 with a `pack` key: `base` {name, sha1 of the exact release image}, `order`, `renames`, `looks[]`),
**Import pack JSON**, **Share link** (the pack, deflate + base64url, in the URL fragment: this page never sends it anywhere; whoever you give the link to
gets the names, order and fitted numbers), **Show build command**. Build on your PC:
`python looktool/om10mi_look.py --pack NAME.pack.json --base YOUR_IMAGE.BIN --out DIR --lut-dir DIR_OF_YOUR_LUTS`. The page checks the pack rules as it goes
(unique slots, slot 2 never replaced, names within capacity, order items valid, fit mode = slot base mode, 40-hex sha1);
`python fw/lut_stage1/lookfile/lookfile_check.py FILE` and the builder remain the authority. A pack holds no firmware bytes. Scores are model predictions.
List manager and before/after divider ideas from the Caduceus Control Panel (cakelesscoder/caduceus-ep7, Apache-2.0); no code or data copied.

## What the result is, and is not

* Scores are **model predictions** (exposure-matched CIEDE2000 on a synthetic reference set), not camera results; the tone-lift gap between
  the page and the camera model is typically below 0.1 dE, field comparison with the real camera is the open check.
* One slot holds a 3x3 matrix, per-channel tone and a luma table; per-sector hue/saturation, grain, halation, 3D-LUT detail the matrix and
  curves cannot express are **not** transferred. The result is the closest look the slot can hold, not the LUT itself.
* Looks keep the base picture mode of the slot; the slot's name is rewritten in every menu and strip, and its two icons (unselected / selected) become one plain film roll without text (`--keep-icon` leaves the old icon, with its old label).
* No model other than the E-M10 Mark I. Never flash an image built for another model. Flashing is at your own risk.

## Licences and credits

* Page code: Apache-2.0 (`LICENSE`). Model numbers (`model-cm-v2-web1.json`) and look files made from them: CC BY-NC-SA 4.0 (`LICENSE-DATA`),
  credit "om10mi-mods, Meghnus, github.com/Meghnus/om10mi-mods".
* Samples `teal_orange`, `matte_fade`, `vivid_pop`: CC0 1.0.
* Your LUT stays yours. The look file stores its name, sha256 and the licence / credit you enter, never the LUT. A CC BY-SA table such as the
  Fuji film HaldCLUTs of the RawTherapee Film Simulation Collection (Pat David, Pavlov Dmitry, Michael Ezra and contributors, CC BY-SA 4.0) needs
  that credit and ShareAlike wherever you share the look file or numbers fitted from it.
* Olympus, OM-D, E-M10, Fujifilm and film names are trademarks of their owners, used only to describe compatibility or as look names.
  No affiliation with or endorsement by OM Digital Solutions.
