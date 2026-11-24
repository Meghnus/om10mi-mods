# om10mi look file, version 2 (draft)

Extends `LOOKFILE_SPEC.md` (version 1). Everything in version 1 stays valid and keeps its meaning: a version 1 file
is still checked by exactly the version 1 rules and is read as a version 2 file with no `source`, no `fit` and no `fx`.
Section numbers `v1 N` refer to the version 1 spec. This document only lists what is **new** or **changed**.

Status: draft. The importers (`lutimport/`) and the checker (`lookfile_check.py`, reads 1 and 2) are the Python reference;
a JavaScript port follows. Licence: Apache-2.0 like version 1. The file holds parameters and the author's own measured
numbers only. It never contains the user's LUT, any camera data or any firmware byte (`source` records *which* table
was used, by name and SHA-256, never its contents).

## 1. What a version 2 file is for

```
LUT / preset  --importer-->  33^3 table  --rank + fit (browser or PC)-->  look file v2  --builder-->  firmware (user's PC)
```

* `source`: where the look came from (provenance, licence, approximate flag).
* `base`: the ranked base picture modes for this look (object form).
* `split`, `calibration`, `tone.exposure_ev`, `global.vibrance_pct`, 3..16 `hsl` sectors with a choice of sector model:
  the extra parameters of Lightroom / RapidRAW style slider presets.
* `fx`: grain, halation, bloom, vignette. Stored from day one, **inactive** in the camera (no FX engine yet): the
  builder lists them as dropped. Files made now keep working when the engine exists.
* `fit`: the result of fitting the intent to what a slot can hold, in model-domain numbers (no firmware tables).

## 2. Envelope changes

| Key | Change |
|---|---|
| `version` | `1` or `2`. Anything else is refused |
| `generator` | adds optional `model` (string, the fit model id, e.g. `cm-v2-web1`; the builder needs it to know what `fit` means) |
| `looks` | still 1..17 |

## 3. Look object changes

| Key | Type | Change |
|---|---|---|
| `slot` | integer | **optional in v2** (the UI / builder asks when it is absent). When present: 1..18, not 2, unique. A name without a slot must be at most 17 characters (warning above 5: it will not fit every slot) |
| `source` | object | **new**, section 4 |
| `base` | string **or** object | v1 string still accepted. Object form: section 5 |
| `hsl` | array of **3..16** | v1: exactly 12. `width_deg` optional per sector (required for `hsl_model` `rapidraw8`) |
| `hsl_model` | string | **new**: `tent` (default, v1 section 4 step 2) or `rapidraw8` (section 7) |
| `global` | object | adds `vibrance_pct` -100..100 |
| `tone` | object | adds `exposure_ev` -5..5 and `curve_mode` (`luma` default = v1 step 4, or `per_channel`) |
| `split` | object | **new**, section 6.1 |
| `calibration` | object | **new**, section 6.2 |
| `fx` | object | **new**, section 8 |
| `fit` | object | **new**, section 9 |

`label`, `strength`, `notes`, `wb`, `camera_settings`, `per_hue_table`, `extras` are unchanged. `extras` is where an
importer lists what it could not map (`extras.import_dropped`, array of strings).

## 4. `source` (provenance)

```jsonc
"source": {
  "type": "cube",                    // cube | xmp-profile | lr-preset | rapidraw-preset | pp3 | photos | params
  "name": "Eterna.xmp",              // file name, <= 200 characters
  "licence": "CC BY-NC-SA 4.0",      // free text <= 100; the web app warns for NC / SA sources
  "sha256": "ab..",                  // 64 hex digits of the source file
  "space": "prophoto",               // display | prophoto | vlog : the encoding the table expects
  "approximate": false,              // true for slider presets (the numbers approximate the originating editor)
  "requires_file": true              // LUT types: the intent lives in the referenced table, which this file does NOT contain
}
```

* All values are scalars. A look file never embeds a table (checker: an array or object in `source` is an error, except
  the small `lut` object a RapidRAW preset uses to name the .cube it composed: `{name, sha256, intensity}`).
* `cube`, `xmp-profile` and `pp3` sources are **LUT sources**: the look has no `hsl`/`tone` of its own, so it is not "the
  identity" even though it carries no parameters. The builder needs the user's table file (`--lut`), checks its SHA-256 against
  `source.sha256` and fits it. A file without `sha256` gets a warning.
* `lr-preset`, `rapidraw-preset` sources carry their parameters as look fields; `source.approximate` is `true`.

## 5. `base` object (ranked base)

```jsonc
"base": {
  "mode": "Portrait",                // the chosen picture mode (auto = not decided yet)
  "candidate": "stock Portrait",     // what won: a stock mode or a shipped look used as the base
  "stage": "refit",                  // stock = stage-1 only, refit = stage 2 done
  "ranking": [ {"candidate": "stock Portrait", "mode": "Portrait", "dE": 4.31, "pct_lt5": 56.2, "dE_fit": 3.98, "stage": "refit"}, ... ],
  "tie_dE": 0.1                      // candidates within this dE_fit of the winner are interchangeable
}
```

Two-stage ranking (reference implementation `base_rank.py`, private because it uses the firmware-derived model):
stage 1 scores the LUT against every candidate (4 stock modes + the shipped looks used as bases) by exposure-matched CIEDE2000
on the reference scenes; stage 2 does a quick matrix refit of the top 3 and records `dE_fit`. The recommended base is the
lowest `dE_fit`. The table is always shown with the recommendation: stock-only scores of mild looks differ by only 0.2-0.3 dE
(lut_PLAN section 3), so "best base" is never a hard answer. `ranking` is sorted by `dE` (stage 1), at most 40 entries,
`mode` is one of Vivid / Natural / Muted / Portrait.

## 6. New colour blocks

### 6.1 `split` (colour grading, 3-way)

```jsonc
"split": {"shadows": {"hue": 210, "sat": 20, "lum": 0}, "mid": {...}, "highlights": {...}, "global": {...},
          "balance": 0, "blending": 50}
```
`hue` 0..360 degrees, `sat` 0..100, `lum` -100..100, `balance` -100..100, `blending` 0..100 (all default 0, blending 50).
Rendered by step 2b (section 7): Oklab tint per lightness region with the RapidRAW constants.

### 6.2 `calibration` (camera calibration)

```jsonc
"calibration": {"red": {"hue": 0, "sat": 0}, "green": {...}, "blue": {...}, "shadow_tint": 0}
```
All -100..100. Rendered by step 1b (section 7). Intended as a prior for the 3x3 matrix of the fit.

## 7. Reference renderer, version 2 (changes to v1 section 4)

Input and output are display-referred sRGB (gamma-encoded 0..1), as in v1. Order:

0. **exposure** `tone.exposure_ev`: multiply linear light by 2^EV, re-encode, clip.
1. **white balance** (v1 step 1).
1b. **calibration**: in linear sRGB: hue mixing matrix with `hue/400` terms, saturation weighted by the positive channel share
    with `sat/120`, shadow tint `shadow_tint/100 * 0.25` over a luma mask `1 - smoothstep(0, 0.3, Y)`
    (restated from RapidRAW `apply_color_calibration`).
2. **global colour and per-colour table**:
   * `tent` model: v1 step 2 unchanged (tent weights summing to 1, gate `smoothstep(0, 0.2, S)`, HSV value for `light_pct`).
   * `rapidraw8` model: sector weight = `exp(-1.5 * (d / (width_deg/2))^2)` normalised over the sectors (d = circular hue
     distance to `centre_deg`); hue shift `sum w * hue_deg * smoothstep(0.05, 0.2, S)` degrees; saturation
     `S' = S * (1 + sum w * sat_pct/100 * smoothstep(0.05, 0.2, S))` (times global); lightness changes **luma** (not HSV V):
     `Y' = Y * (1 + sum w * light_pct/100 * smoothstep(0, 1, S))`, colour rescaled to the new luma. Restated from RapidRAW
     `apply_hsl_panel`; the eight RapidRAW sectors are red 358/35, orange 25/45, yellow 60/40, green 115/90, aqua 180/60,
     blue 225/60, purple 280/55, magenta 330/50 (centre / width, degrees).
   * `global.vibrance_pct`: RapidRAW `apply_creative_color` vibrance branch.
2b. **split**: lightness `L = cbrt(Y_linear)`; region weights from `smoothstep` around `1/3 - shift` and `2/3 - shift`
    (`shift = 0.4 * balance/200`, feather `0.06 + 0.24 * blending/100`, luminance feather at least 0.12); tint = region weights
    times `direction(hue) * sat/1000` in Oklab (a, b), plus `lum/1000` on Oklab L; out-of-gamut colours are pulled toward luma
    (RapidRAW `apply_color_grading` with slope 1 on display-referred input).
3. **per-channel curves** `tone.curve_rgb` (v1 step 3).
4. **master curve** `tone.curve`: `curve_mode` `luma` (v1 step 4, scale R, G, B by `Y'/Y`) or `per_channel` (the curve is applied
   to R, G and B separately).
5. **strength** (v1 step 5).

## 8. `fx` (inactive, stored from day one)

```jsonc
"fx": {
  "grain":     {"amount": 0, "size": 25, "roughness": 50, "seed": 0, "source": "lr:GrainAmount/Size/Frequency"},
  "halation":  {"strength": 0, "radius_permille": 12, "threshold": 0.85, "colour": [1.0, 0.35, 0.15]},
  "bloom":     {"strength": 0, "radius_permille": 20},
  "vignette":  {"amount": 0, "midpoint": 50, "feather": 50},
  "active": false
}
```
Ranges: grain `amount`/`size`/`roughness` 0..100 (Lightroom: amount 0-100, size default 25, frequency = roughness default 50),
`seed` integer 0..2^31-1; halation / bloom `strength` 0..100, `radius_permille` 1..100 (of the long image edge), halation
`threshold` 0..1, `colour` 3 x 0..1; vignette `amount` -100..100, `midpoint`/`feather` 0..100. `active` must be `false` for this
target (warning if `true`): the builder writes the block to the report as "inactive until the FX engine exists" and changes no
slot data. Units of `radius_permille` and the grain size scale are placeholders until the engine is designed [inference].
RapidRAW's halation tint (core 1.0 / 0.15 / 0.03, fringe 1.0 / 0.32 / 0.10) is the default colour an importer fills.

## 9. `fit` (the result)

```jsonc
"fit": {
  "model": "cm-v2-web1", "mode": "Portrait",
  "matrix_orf": [316, 40, -100, -60, 292, 24, 6, -160, 410],       // 9 ints, rows sum 256 (+-1)
  "tone": {"y_curve": [[0, 0], ...], "c_curves": {"r": [...], "g": [...], "b": [...]}, "domain": "u=x^(1/2.4), additive over the base-mode curve"},
  "hue_table": null,
  "guards": {"composed_max": 434, "hdr_clip_pct": 0.0, "tone_strength": 1.0},
  "predicted": {"dE": 3.35, "pct_lt5": 81, "scenes": "ref-set-1", "worst": [{"sector": "blue", "dE": 7.1}]}
}
```
A model-domain description of the fitted slot, not firmware data: the local builder converts it to slot data with the user's
own firmware ("tone lift") and re-scores it; it refuses when its own score differs from `predicted` by more than 0.5 dE. An
unknown `fit.model` is ignored by the builder (it refits from the intent) and the checker warns.

## 9c. `fit` for `cm-v2-web1`: what the builder's tone lift reads (added 2026-11-22)

A file with `generator.model` = `fit.model` = `cm-v2-web1` and a `fit.tone` carries everything the local builder needs; nothing else is read from the browser.

| field | meaning |
|---|---|
| `fit.mode` | the base picture mode `m` (Vivid / Natural / Muted / Portrait): selects the stock tone `T2_m` and per-mode `F_m`, `P_m` |
| `fit.matrix_orf` | the 9 ORF 0x0200-style integers `E` (rows sum 256) of the fitted slot matrix; model matrix `Mrel = wrap11(E)/256 . (S/256)^-1`, `S` = stock ORF matrix |
| `fit.tone.c_curves.{r,g,b}` | `d_c(u)`: 33 knots, x = k/32 = `u`, `u = x_c^(1/2.4)` with `x_c = Mrel x` (camera-linear after the matrix); y = additive delta on the base-mode curve. Per-channel: this is the chroma-changing part (the camera's T3 role) |
| `fit.tone.y_curve` | `h(Y)`: 33 knots, x = k/32 = the luma the lift acts on (`luma_arg`, below), y = additive luma lift (the camera's luma-only T2 role); W = 0.299, 0.587, 0.114 |
| `fit.tone.luma_arg` | `"post"` (written by the S7 web build) or `"yb"` (the web1 definition; also what an absent field means). Selects the model line below |
| model | `luma_arg` `yb`: `y_c = clip(F_m(u_c) + d_c(u_c) - W.d + h(Yb), 0, 1)`, `Yb = W.F_m`;  `luma_arg` `post`: `y_c = clip(F_m(u_c) + d_c(u_c) + h(Y3), 0, 1)`, `Y3 = clip(W.(F_m + d))`; both `out = clip(P_m y, 0, 1)`; knots are piecewise linear; `tone_strength` is already multiplied into the curves |
| `fit.guards` | `composed_max` = the olylook composed-coefficient value of `matrix_orf`, i.e. `sites.check_matrix(solveL(E))` (ported in `web/composed.js`, must be < 1024); `hdr_clip_pct` = clipped percentage on the web's +0.5 EV probe; `tone_strength` 0..1 = how far the clip guard blended the tone toward stock |
| `fit.predicted` | `dE` / `pct_lt5` = exposure-matched CIEDE2000 of the numbers in this file on `scenes` (`ref-syn-1 ...` = the synthetic set, regenerable from formulas; `user JPEG ...` = not regenerable). It is a model value |

Constraints a conforming file meets (`lookfile_check.py` enforces the ones marked C, `lutfit_check.py` all of them): `Y + h(Y)` non-decreasing (C); `F_m + d_c` does not fall faster than `F_m` itself falls (the fitted `F_m` curves are not strictly monotone, so the rule is relative to their own dips); `|d|, |h| <= 0.4` and x within 0..1 (C); 33 knots with x = k/32 for every curve (the checker only requires 2..33 increasing points); rounding to 5 decimals may break strictness by 1e-5 (the builder clamps).
`post` is the camera's own structure: its luma table T2 acts on the luma that is left after the per-channel T3 curves, and T3's luma change passes through at slope 1.00 (measured on the stock tables), so `h` is a function of the post-curve luma `Y3` and `d` is not luma-neutral. `yb` makes `d` luma-neutral and `h` a function of the pre-curve luma, which a T2 can follow only on average. The builder reads both. Measured gaps: `lut7_REPORT.md` section 4.
The builder's tone lift (`looktool/lookbuild/lift.py`) solves the camera's `T3` (per channel) and `T2` (luma) so that the real model reproduces `d_c` and `h` (lut_PLAN section 7 step c), checks the round trip against `predicted.dE` (gate 0.5 dE), then writes the slot. `fw/lut_stage1/lutfit_check.py` is the stub of that gate: it reads the file, re-evaluates the model-domain numbers independently of the browser code and, with the source `.cube`, recomputes `predicted.dE`; it writes nothing.

## 9b. Validation rules added (what `lookfile_check.py` checks for version 2)

All version 1 rules, with these changes, plus:

1. `version` 1 or 2. For `version` 1 the v2 keys are unknown keys (warning, ignored) and `base` must be a string.
2. `slot` may be absent; name length rules as in section 3.
3. `hsl`: 3..16 sectors; `width_deg` 5..180; `light_pct` within +-100 for `rapidraw8`, +-50 for `tent`; `rapidraw8` needs `width_deg` on
   every sector.
4. `tone.exposure_ev` -5..5, `tone.curve_mode` in {luma, per_channel}, `global.vibrance_pct` -100..100.
5. `source`: type in the list, `sha256` 64 hex, `space` in the list, booleans boolean, scalars only; a LUT source without `sha256` -> warning;
   `approximate: true` -> warning.
6. `base` object: `mode` in the four modes or `auto`, `ranking` at most 40 entries with `candidate`, `mode`, `dE` (0..100); sorted by `dE` (warning otherwise).
7. `split`, `calibration`: ranges as in sections 6.1, 6.2. `fx`: ranges of section 8; `fx.active: true` -> warning.
8. `fit`: `model` string (unknown -> warning), `mode` one of the four, `matrix_orf` 9 integers within +-1023 with row sums 256 +-1,
   tone curves 2..33 points with strictly increasing x, `guards.composed_max` below 1024, `tone_strength` 0..1, `predicted` numbers in range.
9. A look with no parameters is not the identity when its `source` is a LUT source (cube / xmp-profile / pp3).

## 10. Mapping from the other editors (importers)

| Source | Importer | Exactness |
|---|---|---|
| `.cube` | `imp_cube.py` | exact: the file's values are the node values (33^3; other sizes are resampled and flagged) |
| Adobe Creative Profile `.xmp` (`crs:RGBTable`) | `imp_xmp.py` | exact: decoded, MD5-checked; table space `prophoto` |
| RawTherapee `.pp3` | `imp_pp3.py` | exact for HaldCLUT film simulation + Standard-mode tone curves (RT source formulas); FilmLike / Luminance / Perceptual curve modes, parametric curves, other sections: flagged |
| RapidRAW `.rrpreset` / `presets.json` | `imp_rapidraw.py` | HSL, colour grading, calibration, saturation, vibrance, curves, grain / halation numbers use RapidRAW's formulas; tone sliders, exposure: flagged approximate |
| Lightroom `.xmp` / `.lrtemplate` sliders | `imp_lr.py` | **approximate always** (Adobe formulas proprietary; RapidRAW's converter constants) |

Lightroom keys (all approximate): `HueAdjustment*` x 0.75 -> `hsl[].hue_deg` (0.6 degrees per RapidRAW unit), `SaturationAdjustment*` /
`LuminanceAdjustment*` -> `sat_pct` / `light_pct`, `ToneCurvePV2012[RGB]` -> `tone.curve_rgb`, `Shadows2012` x 1.5, `Exposure2012` /
`Contrast2012` -> `tone`, `Saturation` / `Vibrance` -> `global`, `ColorGrade*` / `SplitToning*` -> `split`,
`RedHue .. BlueSaturation`, `ShadowTint` -> `calibration`, `GrainAmount/Size/Frequency` -> `fx.grain`, `PostCropVignette*` -> `fx.vignette`.
`Temperature` / `Tint` are not mapped. Masks, local adjustments, lens corrections, sharpening / NR, mono looks: dropped and listed
(mono looks are refused as in v1).

## 11. Examples

`lookfile_example_v2_lut.json` (a LUT source with a ranked base and a fit) and `lookfile_example_v2_preset.json` (a Lightroom-style
slider preset with split toning, calibration, grain and halation) next to this file. Check with
`python lookfile_check.py lookfile_example_v2_lut.json lookfile_example_v2_preset.json`.
