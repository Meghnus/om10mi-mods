# looktool - optional look pack builder (version 94)

## Easy way (in your browser, nothing to install)

1. Open the [look pack panel](https://meghnus.github.io/om10mi-mods/lut/panel.html), import your LUTs and make your looks.
2. In the **Export** card pick your own official firmware `OLY_E_113_1400_0000_0000.BIN` (E-M10 Mark I, version 1.4; `om10mi-build.exe` or the
   OM Digital Solutions server gives you the file) and press **Build firmware**. The page builds the version 94 image and writes your looks into it, all inside
   the browser (the builder runs as Python in WebAssembly, served from the same site). Your firmware is read on your computer and never uploaded; its hash is
   checked first. It takes a few minutes and needs a desktop browser with about 2 GB of free memory.
3. Download the zip, unzip it, copy the folder `DCOLYMP` to the camera's card and follow `HOW-TO-FLASH.txt`.

If something is wrong the page says what to do next (for example *"X" is too far from what the camera can do in Vivid: pick another base mode*) and
builds nothing. It never touches a camera or a card. You flash at your own risk; keep your official firmware to go back.

Prefer the command line? **Export pack (.omlook.zip)** in the panel gives one file with your looks and the exact LUT files; see below.

## Command line (Python)

The same result on your PC. Python 3.10+ and numpy.

### Steps

1. Build the version 94 image: `python om10mi.py build` (gives `out/DCOLYMP/E1139999.BIN`).
2. Make a pack in the browser: [look list manager](https://meghnus.github.io/om10mi-mods/lut/panel.html)
   (or the single-look page [index](https://meghnus.github.io/om10mi-mods/lut/)). Everything runs in your browser, nothing is uploaded.
   Export the pack JSON.
3. Build: `python looktool/om10mi_look.py --pack NAME.pack.json --base out/DCOLYMP/E1139999.BIN --out DIR --lut-dir DIR_OF_YOUR_LUTS`
   (needs Python 3.10+ and numpy). The result is `DIR/E113_PACK_TEST.BIN` (or `DIR/DCOLYMP/E1139999.BIN` with `--card`).
   Several minutes: the acceptance battery is part of the build and a failing step builds nothing.
`--pack` also takes the `NAME.omlook.zip` of the panel (it carries the LUT files; `--lut-dir` is then optional).

Also: `--stock OLY_E_113_1400_0000_0000.BIN --om10mi om10mi.py` instead of `--base` builds the version 94 image first.

**Which file do I flash?** Only the looktool result. It already contains everything from version 94 plus your looks, so it
replaces the `om10mi-build` image (that one is only the input). With `--card` it is written as `DIR/DCOLYMP/E1139999.BIN`,
ready to copy to the card; without `--card`, rename `DIR/E113_PACK_TEST.BIN` to `E1139999.BIN` inside a `DCOLYMP` folder.

**"REFUSED: LUT file NAME not found in --lut-dir / zip"** means the builder did not find the look's LUT, so it
could only run a stricter check without the LUT, and that refused the look. Pass `--lut-dir` with the same `.cube` / `.xmp` files you used in the web page
(same file names, unmodified: they are matched by name and checksum). The builder then scores the look against the LUT itself.
If a look is still refused ("the exact model scores X dE, the look file predicts Y"), that LUT moves tones further than the
camera can follow in that base mode: choose another base mode for it in the web page (it ranks them) or another slot.

## What it can do

- **Replace** a look slot (1..18, not 2 = Acros) with a look fitted from your LUT. The look keeps the base picture mode of the slot
  (a Vivid-based slot takes a Vivid-based look); the fit is a colour matrix plus tone curves, an approximation of the LUT.
- **Rename** a slot (printable ASCII, no `@`, limited by the slot's name capacity); the name changes in every menu and strip.
  The two icons of a replaced slot become a plain film-roll icon without text (`icon: "keep"` leaves the old one).
- **Reorder** the Picture Mode list: menu, SCP picker, Live Control strip, dial stepping and the RAW Data Edit strip.
  `order` in a pack names the items that go first; to put your looks behind an existing row, name every row up to that row first
  (the web page does this for you). Command line only: `python looktool/reorder.py build BASE.BIN OUT_DIR --order 7,6,9,13 --after 18`
  puts looks 7, 6, 9, 13 directly after look slot 18 (`--after` takes a look slot, a stock row such as `Portrait`, or `i-Enhance`).
  i-Enhance and the base-mode rows (Vivid, Natural, Muted, Portrait) keep their places unless you name them.
- Import: `.cube` (3D LUT) and Adobe Creative Profile `.xmp` that carries an RGB table. Slider presets are not supported.

**Not available: hide.** Hiding a look from the shooting UI has not been proven on a camera. The builder and the web page refuse it.

## Files

| Path | What |
|---|---|
| `webbuild.py`, `lookbuild/guide.py` | entry and plain-language messages of the in-browser build (the same builder, run by Pyodide; bundle: `tools/make_web_bundle.py`) |
| `om10mi_look.py` | the builder (replace / rename / reorder through a pack, or one look into one slot) |
| `reorder.py` | order-only builds, with the `--after` anchor |
| `lookbuild/`, `lutimport/`, `lookfile/`, `lutfit_check.py` | builder modules, LUT readers, file format specs (`LOOKFILE_SPEC_v2.md`, `PACK_SPEC_v2.md`) |
| `web/model-cm-v2-web1.json` | our fitted model of the camera colour engine (CC BY-NC-SA 4.0) |
| `examples/` | example pack and three CC0 LUTs (`teal_orange`, `vivid_pop`, `matte_fade`, synthetic, made by us) |

Example: `python looktool/om10mi_look.py --pack looktool/examples/example.pack.json --lut-dir looktool/examples --base out/DCOLYMP/E1139999.BIN --out out_look`
replaces slots 7, 6 and 9 with the example looks and puts them after Gold 200 (slot 18).

## Licences and credits

Code: Apache-2.0. Model numbers and look files made from them: CC BY-NC-SA 4.0 (`LICENSE-DATA`). The three example LUTs: CC0 1.0.
Your LUT stays yours: the pack stores its name, sha256 and the licence you declare, never the table. Tables under CC BY-SA
(for example the film HaldCLUTs of the RawTherapee Film Simulation Collection by Pat David, Pavlov Dmitry and Michael Ezra) are not
included; if you fit looks from them, their credit and ShareAlike terms apply to what you share. Look list manager and
before/after ideas come from the Caduceus Control Panel (cakelesscoder/caduceus-ep7, Apache-2.0); no code or data copied.
Olympus, OM-D and film names are trademarks of their owners.
