# Changes

## 94 (current release)

The builder produces this version; the result must have sha1 `baf96f07b86f40aa91bb100a3658f64d9ed4dcf2`.

New in 94 compared with 88:
- **RAW Data Edit bank rows work.** The Custom1 / Custom2 Sector / Hue / Sat / Light rows now change the developed
  picture. Version 88 had a known problem there; it is fixed.
- **Colour wheel centred in the EVF.** Approximate (within a few pixels); the LCD is unchanged.
- **White balance can be set inside Color Creator.** It resets to Auto once when you enter Color Creator, like the stock camera.
- **SCP Contrast / Sharpness / Saturation sync** with the look's own values, and **per-look C / S / Sat rows**.
- **Optional look pack builder** (`looktool/`): replace looks from a `.cube` / `.xmp`, rename looks, reorder the Picture Mode list
  (also behind an anchor row such as Gold 200). Browser pages for it in `docs/lut/`
  ([look list manager](https://meghnus.github.io/om10mi-mods/lut/panel.html)). No firmware is stored in the tool; it works on your own
  built image. CC0 example LUTs and an example pack are included. See [looktool/README.md](looktool/README.md).
- **Build firmware in the browser:** the panel builds the card file itself from your own official firmware (or the unmodified version 94 image) with this
  builder run in WebAssembly (Pyodide, self-hosted in `docs/lut/pyodide/`); nothing is uploaded. The result zip carries `DCOLYMP/E1139999.BIN`,
  `HOW-TO-FLASH.txt` and the pack as `NAME.omlook.zip` (pack + its LUT files) to change looks later; the panel opens that zip and remembers the last pack.
  `om10mi_look.py --pack` takes the `.omlook.zip` too, and a missing LUT now says so ("LUT file NAME not found in --lut-dir / zip").
- The builder now makes version 94 only (`patch/looks94.json`).

Known limits in 94:
- EVF centring of the colour wheel is approximate.
- **Hiding looks is not available** (not proven on a camera; the look pack builder and the web page refuse it).
- The help text of one button-function option reads "Sector Sat".
- The look pack builder fits a matrix plus tone curves, so a look is an approximation of the LUT.

## 88 (superseded)

Per-look colour editor on each look's own page (User Hue On / Off / Reset, Sector, Hue, Sector Sat, Lightness); User Hue Reset
moved there from the Custom page. Known issues in 88: RAW Data Edit bank Sector / Hue / Sat / Light rows had no effect
(fixed in 94); help text of one button-function option reads "Sector Sat".

Carried over from 87:
- Colour wheel in Color Creator (ART position of the mode dial): 12 sectors, Hue / Saturation / Lightness
  (-7 to +7), live preview that matches the JPEG, recipe kept after power-off, on-screen key hint and a COLOR WHEEL
  text in the mode guide. See [docs/GUIDE-COLOR-WHEEL.md](docs/GUIDE-COLOR-WHEEL.md).
- Own icons for the four added looks: Portra 400, Kodachrome 64, Ektar 100 and Gold 200.
- Contrast / Gradation code on the looks made safe when the camera processes two images at once (re-entrancy
  hardening, see [issue #4](https://github.com/Meghnus/om10mi-mods/issues/4)).
- Pop-up message frames (battery, card, format, Wi-Fi) use the correct frame graphic again.
- `tools/prepush_check.py` guards the repository against firmware bytes.

Carried over from earlier versions:
- 56: four new looks (Portra 400, Kodachrome 64, Ektar 100, Gold 200); per-bank Contrast, Sharpness, Saturation,
  Gradation and Sector/Hue/Sat/Light rows in RAW Data Edit; Highlight, Shadow, Contrast and Gradation act on
  looks; colour-named Sector, row titles and captions, new icons; Contrast and Sharpness in the SCP menu work on
  all looks; Acros is black and white again in RAW Data Edit Custom.
- 51: looks selectable in RAW Data Edit Custom1/2.
- 48: per-look colour editor on the Custom page (moved to each look's own page in 88).
- 46: per-sector colour editor (Hue/Saturation/Lightness).
- 40: video recording limit 59:50.
- 37: 14 film looks with their own colour matrix and tone curve.

After installing (recommended): MENU > Shooting Menu 1 > Picture Mode, highlight any colour look, right arrow,
User Hue > Reset, once.

## 87

Look pack 87 (sha1 `2d34ed2deba4f3d3a838b263ef201ac114dc4c22`), superseded by 88: colour wheel, own icons for
the four added looks, Contrast/Gradation stability fix. See the version history in the README.

## 56

Look pack 56 (sha1 `0d4e1649cb930d39fc49a331d92840a7cbcbd83e`), superseded by 88. See the version history in the
README.

## Next

- Import of LUT/.cube/.xmp files into a look slot (planned).
