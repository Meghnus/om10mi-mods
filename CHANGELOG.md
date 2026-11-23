# Changes

## 88 (current release)

The builder produces this version; the result must have sha1 `7f35e97bfc4d185a18e15be99f9292bd56643e0a`.

New in 88 compared with 87:
- **Per-look colour editor on each look's own page.** In Picture Mode, highlight a colour look and press the
  **right arrow**: the page has **User Hue** (On / Off / Reset), **Sector**, **Hue**, **Sector Sat** and
  **Lightness**. The edit applies to that look only. Acros has no such page. This replaces the single editor
  that used to sit on the Custom page; **User Hue Reset** is now on a look's right-arrow page. See
  [docs/GUIDE-56.md](docs/GUIDE-56.md), section "Per-look colour editor".
- The builder now makes version 88 only (`patch/looks88.json`).

Known issues in 88:
- The help text of one button-function option reads "Sector Sat".
- In the SCP (super control panel), for the film looks, Sharpness / Contrast / Saturation values set on the OK
  adjust screen may not be shown on the SCP tile. This is being investigated.

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
