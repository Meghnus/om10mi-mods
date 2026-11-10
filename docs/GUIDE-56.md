# Version 56 guide

New looks, colour-named sectors, row captions and new icons.

## A. What is new

1. There are 4 new looks in the Picture Mode list: **Portra 400, Kodachrome 64, Ektar 100 and Gold 200**. Each
   has its own colour, close to the real film. The new looks are also in the SCP menu, in Live View, and in RAW
   Data Edit Custom1 and Custom2.
2. The **Sector** row in RAW Data Edit can now be turned. It shows colour names (Green, Amber, Teal, Cyan, Azure,
   Blue, Magenta, Indigo, Olive, Red, Orange, Yellow), so you know which colour you are changing.
3. Every row now has its own name and caption, so there is no more confusing OFF or dash. For example
   "Gradation High Key". If you leave Contrast, Sharpness or Saturation unchanged, the row reads "Picture Mode",
   meaning it follows the Picture Mode setting.
4. New row icons. Every row has its own icon, different from the other rows. Sector has a colour-wheel icon.
5. In the SCP menu (super control panel), Contrast and Sharpness now really work on all looks, including Eterna
   and the new looks. Before, the dial turned but the picture did not change.
6. Acros in RAW Data Edit Custom is black and white again. Before, it came out in colour.

This version already contains everything that came before it (14 film looks, per-sector and per-look colour
editors, looks in RAW Data Edit, a video recording limit of about 60 minutes). A summary is in the
[README](../README.md).

**Known limitation.** The four new looks borrow the icon of an existing look: Portra 400 uses the Pro Neg Std
icon, Kodachrome 64 uses Classic Chrome, Ektar 100 uses Velvia and Gold 200 uses Nostalgic Neg. The names are
shown correctly; own icons are planned for a later version.

## B. Do once after installing

1. Open the User Hue menu and choose **Reset**, once. This clears leftover old values so the 4 new looks start
   from zero.
2. If one of the Custom banks (Custom1 or Custom2) was set to Acros, the text **ART12** may appear there once.
   That is normal. Select Acros again and it goes away.

## C. Risks (read first)

1. The added code runs during RAW Data Edit, in Live View, when shooting with a look, and in the SCP menu.
2. If you see a strange icon, a frozen screen, broken colours, or the camera restarts: remove the battery, power
   on while **holding OK** (update mode), and install the official firmware from `out/RESTORE/DCOLYMP` (steps in
   [INSTALL.md](../INSTALL.md)).
3. The added code does not change your original RAW files.

## D. Installing

See [INSTALL.md](../INSTALL.md). In short: full battery, back up and then format the card in the camera, copy
`DCOLYMP`, hold OK while powering on, wait until it finishes.

## E. Prepare a test photo

Use one RAW (ORF) photo with a colour chart or a varied scene (skin, sky, leaves, coloured objects). Copy it to
the card, folder `DCIM\100OLYMP`, and check that Playback can open it. Use the same photo to compare looks.

## F. Test list (in order; note what you see)

1. Do step B first (User Hue Reset once).
2. Playback, RAW Data Edit, Custom1. Walk through the 17 rows from page 1 to page 3; nothing should freeze.
   Repeat in Custom2.
3. Turn the Sector row through all colours. The colour names should change one by one and wrap around. Check
   Custom2 as well.
4. Look at the caption of each row, for example Gradation High Key. Rows you have not changed read
   "Picture Mode".
5. Look at the icon of each row. No two rows share an icon.
6. Choose the Eterna look on the test photo. In SCP or RAW edit, Contrast +1 must differ from Contrast 0.
   Sharpness +1 must differ too.
7. Open the Picture Mode list. Portra 400, Kodachrome 64, Ektar 100 and Gold 200 are there. Check the SCP menu,
   Live View, and RAW Data Edit (both Custom banks) too.
8. Choose Acros in RAW Data Edit. The picture must be black and white.
9. Shoot the same scene with Portra 400, Kodachrome 64, Ektar 100 and Gold 200. Compare: each look has its own
   colour. Gold 200 and Portra 400 are fairly similar by design.
10. Normal shooting and Live View with the older looks: they look normal.

## G. If something goes wrong (recovery)

Enter update mode (hold OK while powering on) and install the official firmware from `out/RESTORE/DCOLYMP`.
