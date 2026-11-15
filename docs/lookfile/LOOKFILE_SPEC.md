# om10mi look file, version 1 (draft)

A small JSON file that an external editor (for example the Caduceus Control Panel) exports and that the
om10mi builder turns into look slots of the **Olympus OM-D E-M10 Mark I** (E113, firmware 1.4 with the
version 56 look layout). The file describes *what the look should be*. It never contains camera data, and the
builder never reads firmware bytes from it.

Status: draft for discussion. Field names and ranges are meant to be stable; the builder side (section 8)
is not finished. The conversion constants in section 5 are the reference values of version 1.
For now, look files are built into firmware by the repository owner; a public build path may follow.
Licence: this spec, the example and `lookfile_check.py` are Apache-2.0 (see `LICENSE`).

## 1. How it is used

```
editor  --export-->  my_looks.json  --om10mi builder-->  firmware file (DCOLYMP/E1139999.BIN)
```

1. The builder checks the file (section 9). Any error: nothing is built.
2. For every look it renders a **target** from the parameters with the reference renderer (section 4).
3. It fits the target to what a look slot of this body can express (section 5) and reports the predicted error.
4. It writes the fitted data into the chosen slots of the official firmware, which stays on your PC.

## 2. File layout

UTF-8 JSON object, at most 1 MiB, numbers are plain JSON numbers (no NaN, no Infinity).

| Key | Type | Required | Meaning |
|---|---|---|---|
| `format` | string | yes | must be `"om10mi-look"` |
| `version` | integer | yes | `1`. The builder refuses another major version. New optional keys may appear without a version change; unknown keys are ignored with a warning |
| `target` | string | yes | must be `"E113"` (E-M10 Mark I). Any other value is refused: files and firmware of other bodies must never be mixed |
| `generator` | object | no | `{"name": string, "version": string}`, informational |
| `looks` | array | yes | 1 to 17 look objects (section 3) |

## 3. Slots

The body has **18 look slots** in the version 56 layout (14 shipped film looks plus 4 added looks). A look
object replaces the look in the slot it names. Slots you do not mention keep the shipped look. The number of
menu rows does not change and rows cannot be added or removed.

Slot 2 (Acros) is Monotone-only and is **reserved**: a look for slot 2 is refused in version 1. This leaves
17 usable slots.

| Slot | Shipped look | Default base | Name length limit |
|---|---|---|---|
| 1 | Eterna | Muted | 6 |
| 2 | Acros | Monotone | reserved |
| 3 | Provia | Portrait | 7 |
| 4 | Velvia | Muted | 7 |
| 5 | Astia | Muted | 5 |
| 6 | Classic Chrome | Vivid | 14 |
| 7 | Classic Neg | Vivid | 11 |
| 8 | Pro Neg Std | Portrait | 11 |
| 9 | Pro Neg Hi | Natural | 11 |
| 10 | Nostalgic Neg | Muted | 13 |
| 11 | Reala Ace | Vivid | 9 |
| 12 | Bleach Bypass | Vivid | 13 |
| 13 | CineStill 800T | Portrait | 15 |
| 14 | Severn | Portrait | 8 |
| 15 | Portra 400 | Portrait | 10 |
| 16 | Kodachrome 64 | Portrait | 17 |
| 17 | Ektar 100 | Portrait | 10 |
| 18 | Gold 200 | Portrait | 8 |

The name limits come from the shortest of the camera's 34 language strings for that row. Slot numbers are
stable: later builder versions add numbers, they never renumber.

### Look object

| Key | Type | Range / values | Default | Meaning |
|---|---|---|---|---|
| `slot` | integer | 1..18, not 2, unique in the file | required | Slot to replace |
| `name` | string | printable ASCII, no `@`, 1..limit characters (table above) | required | Menu name. Shown identically in all languages |
| `label` | string | `A-Z 0-9 space . -`, 1..7 characters | uppercased name | Text rendered into the row icon. Slots 1-14 only. Slots 15-18 borrow an existing icon, so a label there is ignored with a warning |
| `base` | string | `auto`, `Vivid`, `Natural`, `Muted`, `Portrait` | `auto` | Camera picture mode the slot is built on (it fixes the slot's default contrast, saturation, sharpness and its base colour tables). `auto` lets the builder pick the best-fitting one. `Monotone` is refused |
| `strength` | number | 1..100 | 100 | Percent of the look applied, blended toward the unmodified base before fitting |
| `notes` | string | up to 200 characters | empty | Free text, copied to the build report only |
| `hsl` | array of 12 | section 3.1 | all zero | Per-colour hue, saturation and lightness |
| `global` | object | `hue_deg`, `sat_pct` | zero | Whole-picture hue rotation and saturation |
| `wb` | object | `amber_blue`, `green_magenta` | zero | White-balance shift in camera fine-tune steps |
| `tone` | object | `curve`, `curve_rgb` | identity | Tone curves |
| `camera_settings` | object | `contrast`, `sharpness`, `saturation` | not given | Settings the look recommends in the camera. Advice only |
| `per_hue_table` | boolean | | `false` | Ask for the camera's per-hue correction table (section 5.4) |
| `extras` | object | anything | none | Parameters the body has no stage for. Ignored, listed in the report (section 6) |

### 3.1 Per-colour table `hsl`

Exactly 12 objects, one per colour sector, listed in increasing `centre_deg`:

| Key | Type | Range | Unit | Meaning |
|---|---|---|---|---|
| `centre_deg` | number | 0 <= x < 360 | degrees on the HSV hue wheel (red 0, yellow 60, green 120, cyan 180, blue 240, magenta 300) | Where the editor puts this sector. Required for every entry, because editors place their sectors differently. Entries must be at least 5 degrees apart, going around the wheel |
| `hue_deg` | number | -60..60 | degrees | Hue rotation of this sector. Positive = towards larger hue angle (red -> yellow -> green) |
| `sat_pct` | number | -100..100 | percent | Change of HSV saturation: `S' = S * (1 + sat_pct/100)`. -100 removes the colour |
| `light_pct` | number | -50..50 | percent | Change of HSV value: `V' = V * (1 + light_pct/100)` |

Editors with steps (for example hue/light +-7, saturation +-5) convert their steps to these units with the
same factors their own preview uses, so that the preview and the builder's target agree.

### 3.2 Whole-picture `global`

| Key | Type | Range | Unit | Meaning |
|---|---|---|---|---|
| `hue_deg` | number | -60..60 | degrees | Added to every hue |
| `sat_pct` | number | -100..100 | percent | Multiplies HSV saturation of every pixel |

### 3.3 `wb`

| Key | Type | Range | Unit | Meaning |
|---|---|---|---|---|
| `amber_blue` | number | -7..7 | camera fine-tune steps | Positive = amber (warmer), negative = blue |
| `green_magenta` | number | -7..7 | camera fine-tune steps | Positive = green, negative = magenta |

A step is one step of the body's own white-balance fine-tune menu. Fractions are allowed.

### 3.4 `tone`

| Key | Type | Meaning |
|---|---|---|
| `curve` | array of `[x, y]` | Master tone curve on luma (display-referred, 0..1). 2 to 33 points, `x` strictly increasing with first `x` = 0 and last `x` = 1, `y` within 0..1 and not decreasing. Straight lines between points are assumed, so sample your editor's curve densely enough (9 to 17 points are usually plenty) |
| `curve_rgb` | object `{"r": [...], "g": [...], "b": [...]}` | Optional per-channel curves, same rules as `curve`. Any of the three may be omitted (identity) |

Editors with Highlights / Shadows / Midtones / Blacks / Whites sliders export the **curve their preview applies**
(sample it), not the slider values, so that every editor maps to the same field.

### 3.5 `camera_settings`

Integers -2..2 each: `contrast`, `sharpness`, `saturation`. These are the in-camera Picture Mode settings the
look was designed with. They are **not baked**: the builder prints them on the card sheet for the slot, and the
look's own contrast and saturation should be in `tone.curve` and `global.sat_pct`. Sharpness has no stage inside
a look slot, so it can only be advice.

## 4. Reference renderer (what the file means)

The look is defined as a function from display-referred sRGB (gamma-encoded, floats 0..1) to the same, applied
in this order. The builder implements exactly this; an editor can implement it to preview.

1. **White balance.** Linearise, multiply R, G, B by gains derived from `wb` (section 5.3), re-encode.
2. **Per-colour and global colour.** Convert to HSV. Let `h` be the pixel hue and `w_k(h)` the weight of sector
   `k`: tent functions on the hue circle that equal 1 at `centre_deg` of sector `k`, fall linearly to 0 at the
   centres of the two neighbouring sectors, and sum to 1 everywhere. Let `g(S) = smoothstep(0, 0.2, S)`, so grey
   pixels are never touched. Then
   `h' = h + global.hue_deg + g * sum_k w_k * hue_deg_k`,
   `S' = clamp(S * (1 + global.sat_pct/100) * (1 + g * sum_k w_k * sat_pct_k/100), 0, 1)`,
   `V' = clamp(V * (1 + g * sum_k w_k * light_pct_k/100), 0, 1)`.
   Convert back to RGB.
3. **Per-channel curves** `curve_rgb`, if present.
4. **Master curve** `tone.curve` on luma `Y = 0.2126 R + 0.7152 G + 0.0722 B` (gamma-encoded values): `Y'` =
   curve(Y); R, G, B are scaled by `Y'/Y` and clipped to 0..1.
5. **Strength.** `out = base + strength/100 * (out - base)` where `base` is the input.

## 5. Mapping to the slot, and what is approximated

A look slot holds: a base picture mode, a 3x3 colour matrix, a luma tone curve (T2), per-channel tone curves
(T3), optionally a 12-region per-hue table, and a name and icon. There is no 3D lookup stage on this body.
The builder renders the target (section 4) on a fixed set of training scenes, fits the slot data to it, and
reports the result per slot.

### 5.1 Matrix (approximate)

A 3x3 matrix in integer steps of 1/256 whose rows sum to 256 (grey stays grey). It carries the overall colour
character: `global.hue_deg`, `global.sat_pct` and as much of `hsl` as a single linear mix can follow. Limits
the builder enforces: the composed coefficients must stay below 1024 in absolute value; if the fit would exceed
that, the matrix is pulled toward the stock one in steps. What a matrix cannot do is separate two hues that
lie close to each other: a request to push yellow-green one way and green the other is only met on average.

### 5.2 Tone curves (approximate)

`tone.curve` and `curve_rgb` go into the luma curve (256 entries of 10 bits, fitted with 17 free knots) and
the per-channel curves (3 x 9 knots, 10 bits). Both are forced monotone. Sharp features narrower than about
1/16 of the range are smoothed. A guard limits clipped highlights to the target's clipping plus 0.2 percentage
points and at most 1 point above the unmodified base; if the curve breaks that, it is blended toward stock and
the report shows the blend (`tone_strength`). A look that needs a very steep highlight roll-off therefore comes
out softer than designed.

### 5.3 White balance (approximate)

The body applies its own white balance before a look is applied, so a look cannot change it. The shift is
instead imitated by per-channel gains in the per-channel curves: `amber_blue` raises R and lowers B,
`green_magenta` moves G against R and B. The size of one step is a builder constant (reference value to be
calibrated on the camera, section 8) and is the same on the whole tone range. Highlights and shadows are
tinted equally, which an in-camera shift does not do exactly.

### 5.4 Per-hue table (optional, limited)

The camera has a 12-region table of hue shift, saturation and lightness per colour region. When `per_hue_table` is `true` the builder spends it on what the matrix could not follow: hue shifts
(steps of 5 degrees on this body) and saturation. The regions have fixed positions and the base picture mode's
table switches some of them off, so only the editor sectors that fall into an active region are honoured.
Lightness in this table is not fitted in version 1. The number of slots that can have such a table is limited
by the layout (currently **0** in the version 56 layout, so `true` is accepted and ignored with a warning;
a later layout is expected to allow 2). The saturation unit of the table is not yet calibrated against the
camera, so use of it will stay experimental.

### 5.5 Base mode and contrast defaults

The base mode brings its own default contrast, saturation and sharpness. `auto` tries the four colour bases
and keeps the one with the lowest predicted error. Film-style looks have so far fitted best on Portrait.

### 5.6 Expected fit quality

Measured on the existing looks (model prediction on training scenes, not a camera JPEG, no noise reduction or
sharpening): typically 70 to 80 percent of pixels within dE2000 5 of the target, mean dE2000 between 3.3
and 4.6 for the four film looks of version 56. Looks with strong hue-selective colour (a Classic Neg type)
fit worst, around 40 percent. The report states the numbers for every look so the result is never a surprise.

## 6. What is dropped

Nothing below has a stage in a look slot on this body. It is accepted in `extras` (so that one file can carry
the whole editor look), ignored, and listed in the build report:

grain, noise-reduction mode, halation, bloom / glow, clarity, vignette, split toning, art effects, lens
correction, monochrome filters and monochrome looks (`kind: "mono"` is not exported to this body), sharpening
as a look property, and any 3D lookup table. Per-slot WB *override* is not available either: `wb` is the
approximation of section 5.3.

## 7. Worked example

See `lookfile_example.json` next to this file. It has two looks:

* slot 6 `Soft Teal Neg` (13 of 14 allowed characters), a Classic-Chrome-style replacement: reds shifted
  slightly orange and desaturated, yellows and greens pulled down in saturation, cyans slightly richer, lifted
  blacks, a slight cool balance (`amber_blue` -1), global saturation -8 percent. `base` is `auto`. It also
  carries `extras` with grain and bloom that the body cannot do.
* slot 16 `Warm Fade` replacing Kodachrome 64: per-channel curves that lift blue in the shadows and warm the
  highlights, a gentle master S-curve, `per_hue_table` requested. In the version 56 layout this request is
  ignored with a warning.

Expected builder behaviour for that file: both looks pass the check; the report lists for slot 6 the dropped
`extras.grain` and `extras.effect`, and for slot 16 the ignored `per_hue_table`; each slot gets a predicted
error line, a recommended in-camera setting line (contrast 0, sharpness 0, saturation 0) and the realised
tone blend. Run `python lookfile_check.py lookfile_example.json` to check a file yourself.

## 8. For editor authors: mapping from the Caduceus look

How a Caduceus Control Panel look (`caduceus-pack/1`, `Look` in `webapp/src/pack.ts`) would map. All of it is
done by the exporter; the builder only sees the file.

| Caduceus `Look` field | om10mi field | Note |
|---|---|---|
| `name` (up to 12) | `looks[].name` | Cut to the slot limit, non-ASCII folded or the export refuses |
| `hue[12]` (+-7 steps) | `hsl[k].hue_deg` | Steps to degrees with the preview's factor |
| `sat[12]` (+-5 steps) | `hsl[k].sat_pct` | |
| `light[12]` (+-7 steps) | `hsl[k].light_pct` | |
| sector order `SECTORS` (Yellow first) | `hsl[k].centre_deg` | The exporter states the real centre of each of its sectors. The order in the file is by angle |
| `tone` highlights / shadows / midtones (+-7), blacks / whites (+-5) | `tone.curve` | Sample the curve the preview draws |
| `wb.a_b`, `wb.g_m` (+-7) | `wb.amber_blue`, `wb.green_magenta` | A positive = amber, G positive = green |
| `advice.contrast`, `advice.sharpness` | `camera_settings.contrast`, `.sharpness` | Clamp to +-2. An E-M10 Mark I camera profile would set `settings: true` in `cameras.ts` |
| `grain`, `film_grain`, `effect` (bloom, halation, clarity), `vignette`, `art_effect`, `split`, `lens_correction` | `extras` | Dropped |
| `kind: "mono"` | not exported | `supports()` returns a reason |
| `notes` | `notes` | |
| pack `slots` / `looks` order | `slot` | The target needs an assignment of looks to slots 1..18 (without 2). A look list longer than 17 is refused |

An export target for this body is therefore one module next to `targets/om3.ts` that writes
`om10mi-looks.json`; its `supports()` rejects mono looks, and its `export()` throws when more than 17 looks
are assigned or two looks share a slot.

Open points that the editor can help to settle are in section 10.

## 9. Validation rules (what the builder refuses)

Checked first, before any fitting or any firmware access. `lookfile_check.py` implements exactly these.

1. The file is UTF-8 JSON, at most 1 MiB, the top level is an object, all numbers are finite.
2. `format` is `"om10mi-look"`, `version` is the integer 1 (any other major: refuse), `target` is `"E113"`.
3. `looks` is a list of 1 to 17 objects. Every `slot` is an integer in 1..18, not 2, and occurs once.
4. `name`: string of printable ASCII, no `@`, length 1 to the slot's limit (section 3).
5. `label` (optional): characters `A-Z 0-9 space . -`, 1 to 7 long. On slots 15..18: warning, ignored.
6. `base`: one of `auto`, `Vivid`, `Natural`, `Muted`, `Portrait`.
7. `strength`: number 1..100. `notes`: string up to 200 characters.
8. `hsl`: exactly 12 objects. `centre_deg` in [0, 360), strictly increasing, each gap (also the wrap-around
   gap) at least 5 degrees. `hue_deg` within +-60, `sat_pct` within +-100, `light_pct` within +-50.
   Missing values mean 0.
9. `global`: `hue_deg` within +-60, `sat_pct` within +-100.
10. `wb`: both values within +-7.
11. Each curve: 2 to 33 points `[x, y]`, first `x` = 0, last `x` = 1, `x` strictly increasing, all within 0..1,
    `y` not decreasing. `curve_rgb` keys are only `r`, `g`, `b`.
12. `camera_settings`: integers within +-2.
13. `per_hue_table`: boolean. More requests than the layout allows: warning, the surplus is ignored.
14. Unknown keys: warning. `extras` content is never interpreted.
15. A look that equals the identity (no `hsl`, `global`, `wb`, `tone`) and is not a plain rename: warning.

After the file passes, the builder additionally refuses, with a message and without writing anything, when:

* the firmware it finds is not the E-M10 Mark I v1.4 image it expects (model ID, size and SHA-1 checks);
* any fitted result fails the structural guards: matrix rows not summing to 256 or composed coefficients out
  of range after pulling toward stock, a non-monotone tone curve, a name that does not fit its slot's string;
* the written image differs from the unmodified firmware anywhere other than the declared slot data sites, or
  a footer checksum does not verify.

## 10. Open points

* Direction and size of the editor's hue steps, and the centre angles of its 12 sectors.
* Step size of white-balance fine-tune in the pictures this body produces (to be calibrated on the camera).
* Whether the per-hue table can be offered at all in the final layout, and its saturation unit.
* Whether a pack with more than 17 looks should export as several files.

## 11. Licence note

This document describes parameters only. No firmware, decoded data or derived table is part of it or of the
files next to it. Look files you write are yours; the firmware stays the property of OM Digital Solutions and
is only ever downloaded to your own PC by the builder.
