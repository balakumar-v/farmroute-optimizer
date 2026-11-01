---
name: Farmroute Optimizer
description: A painted mandi rate board for farmer produce pooling: ruled grids, ledger lines, one big net figure.
colors:
  limewash: "#e6ecf0"
  board: "#f6f8f9"
  board-2: "#edf1f4"
  enamel-ink: "#10151c"
  ink-2: "#37414d"
  ink-3: "#566170"
  rule: "#c2cbd3"
  rule-strong: "#8e9aa6"
  enamel-blue: "#1b4f9c"
  enamel-blue-deep: "#14407f"
  blue-wash: "#dbe5f4"
  chrome-yellow: "#f2b705"
  yellow-wash: "#fbefc2"
  oxide-red: "#b3301a"
  red-wash: "#f7dfd8"
  ok-green: "#1e7a4c"
typography:
  display:
    fontFamily: "Barlow Condensed, Barlow, ui-sans-serif, system-ui, sans-serif"
    fontSize: "2.5rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.02em"
  headline:
    fontFamily: "Barlow Condensed, Barlow, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 700
    lineHeight: 1.1
    letterSpacing: "0.04em"
  figure:
    fontFamily: "Barlow Condensed, Barlow, ui-sans-serif, system-ui, sans-serif"
    fontSize: "4rem"
    fontWeight: 700
    lineHeight: 0.9
  body:
    fontFamily: "Barlow, ui-sans-serif, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Barlow, ui-sans-serif, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    letterSpacing: "0.08em"
rounded:
  sharp: "2px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "28px"
  xl: "36px"
components:
  button-primary:
    backgroundColor: "{colors.enamel-blue}"
    textColor: "#ffffff"
    rounded: "{rounded.sharp}"
    height: "40px"
    padding: "0 16px"
  button-primary-hover:
    backgroundColor: "{colors.enamel-blue-deep}"
  button-secondary:
    backgroundColor: "{colors.board}"
    textColor: "{colors.enamel-ink}"
    rounded: "{rounded.sharp}"
    height: "40px"
  button-secondary-hover:
    backgroundColor: "{colors.yellow-wash}"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.oxide-red}"
    rounded: "{rounded.sharp}"
  input:
    backgroundColor: "{colors.board}"
    textColor: "{colors.enamel-ink}"
    rounded: "{rounded.sharp}"
    height: "40px"
  tag-real:
    backgroundColor: "{colors.chrome-yellow}"
    textColor: "{colors.enamel-ink}"
    rounded: "{rounded.sharp}"
---

# Design System: Farmroute Optimizer

## Overview

**Creative North Star: "The Painted Rate Board"**

A mandi's rate board is a wall someone has ruled with a brush: a limewash ground, black enamel lettering, painted grid lines, one price per row. This system borrows that grammar, not its costume. Information sits on ruled lines, not in cards. Headings are painted caps. The one figure that matters (net return) is set large and sits under a summing rule, like a ledger total. Nothing imitates paint, chalk or texture; the material is carried by structure, type and a small set of enamel colours.

The density is that of a working board: tables are tight, numerals are tabular, and every row answers either "what did it decide" or "why". The app is for evaluators first, so a scenario must be one click from a working result; chrome never competes with data.

**Key Characteristics:**
- Ruled structure (2px and 3px ink rules, 1px hairlines) instead of boxed panels.
- Barlow Condensed painted caps for headings and prices; Barlow for everything else.
- Three enamel colours with fixed meanings: blue acts, yellow highlights, red is loss.
- Sharp 2px corners everywhere; no pills, no soft cards.
- Tabular numerals throughout; ₹ drawn from a unicode-range fallback so it never changes weight.

## Colors

A cool, blue-tinted limewash ground with blue-black ink, and three sign-painter enamels used by meaning, not decoration.

### Primary
- **Enamel Blue** (#1b4f9c): the only action colour (primary buttons, focus ring) and the identity of ILO, the algorithm being shown. Never used for decoration.

### Secondary
- **Chrome Yellow** (#f2b705): highlight and "market". Active tab underline, active stage cell, real-data tag, market markers on the map, selected story step (as `yellow-wash`). Always carries ink text, never white.

### Tertiary
- **Oxide Red** (#b3301a): loss and absence only: unserved farmers, produce that never got a truck, errors, destructive actions.

### Neutral
- **Limewash** (#e6ecf0): the page ground. **Board** (#f6f8f9): tables, inputs, panels on the ground. **Board 2** (#edf1f4): hover and secondary bars.
- **Enamel Ink** (#10151c): text, heavy rules, the masthead. **Ink 2** (#37414d) body-secondary; **Ink 3** (#566170) muted (5:1 on limewash).
- **Rule** (#c2cbd3) hairlines; **Rule Strong** (#8e9aa6) input borders.
- A full dark theme exists as tokens (`prefers-color-scheme: dark`, or `data-theme="dark"`): ground #0d1217, ink #e8edf1, blue lifts to #6fa2ec.

### Named Rules
**The Meaning-Fixed Rule.** Blue acts, yellow marks, red loses. A colour is never reused for a different meaning on another screen.
**The Vehicle Palette Rule.** Vehicles take colours from a curated 8-colour set (`Vis.VEHICLE_PALETTE`) that excludes red and yellow, so a vehicle can never be mistaken for "unserved" or "market". Ids beyond 8 use a golden-angle hue kept out of the red and yellow bands.

## Typography

**Display Font:** Barlow Condensed (700, 600) with Barlow and system sans fallbacks
**Body Font:** Barlow (400, 500, 600, 700)
**Rupee:** a `unicode-range: U+20B9` face (Noto Sans) so ₹ matches weight; Barlow has no rupee glyph.

**Character:** a condensed highway-sign grotesque for the painted parts, a plain humanist sans for reading. Both ship with tabular figures; numbers always align in columns.

### Hierarchy
- **Display** (700, 2.5rem, 1, uppercase, +0.02em): page titles, one per view.
- **Headline** (700, 1.375rem, 1.1, uppercase, +0.04em): section heads, scenario and algorithm names (up to 1.75rem).
- **Figure** (700, 4rem, 0.9): the single net-return number on the Plan view; scoreboard values at 1.625rem; scenario counts at 1.875rem.
- **Body** (400, 1rem, 1.5): prose capped at 68 to 86ch.
- **Label** (600, 0.75 to 0.8125rem, +0.08em, uppercase): buttons, tabs, table headers. Never used above a heading as a kicker.

### Named Rules
**The Painted-Caps-For-Prices Rule.** Condensed caps are for headings and for figures a person reads as a price. Controls, table cells and prose stay in Barlow.

## Layout

A single column of ruled sections, 1240px max (1480px on the Map view). Every page opens with a title over a 3px ink rule; sections open with a heading over a 2px rule; rows divide with 1px hairlines. Spacing rhythm: 4, 8, 16, 28, 36px, with section gaps of 36px.

The Map view is a workspace: toolbar, then a two-column grid (map + transport bar + stage rail on the left; a 400px Story/Details panel on the right whose content scrolls internally, so the map never moves). Below 1100px the panel stacks under the map. Below 820px the top tabs become a fixed bottom nav with icons, the toolbar compacts to icon buttons, and tables collapse: ledger tables become labelled stacked rows (`table.stack`), data tables scroll horizontally.

## Elevation & Depth

Flat by default. Depth is conveyed by rules and by the tonal step between limewash and board. The only shadow is a soft ambient one (`0 6px 20px rgba(16,21,28,.14)`) on floating panels (connection popover, add-forms). No hard offset shadows, no glass.

## Shapes

One corner radius: 2px, on buttons, inputs, tags, bars and panels. Tags are rectangles with a 1px border; status dots and map markers are the only circles. Progress and comparison bars are flat rectangles that grow once from the left on first render.

## Components

- **Buttons:** 40px tall, uppercase label (0.8125rem, 600, +0.08em). Primary = enamel blue fill; secondary = board fill with 1px ink border (hover tints yellow-wash); danger = red outline that arms into a solid fill for a two-step confirm. Toggles reuse primary for "on" and set `aria-pressed`.
- **Scenario row:** number or REAL marker, name in headline caps, three count stats, a tag (Synthetic outline, Real prices yellow), and one Run button; the long explanation lives in a disclosure.
- **Ledger line:** `dt … dd` with a dotted leader; the total line sits under a 3px ink rule and carries the figure.
- **Scoreboard:** one row per algorithm with two aligned bars (net return, produce sold) and a signed delta against ILO; ILO is blue, baselines are neutral grey.
- **Tabs:** ink masthead tabs with a 4px yellow underline for the active one; icons only appear in the mobile bottom nav.
- **Story step:** a 10px vehicle-colour swatch, text, time; active = yellow-wash.
- **Stage rail:** seven equal cells with painted numerals; active = chrome yellow, passed = blue-wash.
- **Icons:** one 24px sprite at 1.75 stroke (`#i-*` symbols in index.html); no glyph or emoji icons.

## Do's and Don'ts

### Do
- Put return and produce-sold side by side wherever either is shown.
- Label what is real, synthetic, derived or simulated.
- Keep the page reachable in two clicks from first load: Scenarios, Run.
- Keep ILO blue and the baselines neutral.

### Don't
- Don't box content in cards when a ruled row will do.
- Don't use a coloured side stripe to mark state; use a swatch or a background tint.
- Don't use red or yellow for vehicle colours.
- Don't add eyebrows above headings or glyph icons.
- Don't surface the realistic baselines (farm-gate, self-haul, neighbour pooling) until the algorithm work is done; product decision.

## Not canonized (carried defects)
- The map's raster basemap (Esri gray canvas by default, configurable in config.js) was not verified in the build sandbox (no internet); only the offline graticule path was exercised.
- The theater walkthrough keeps its own dark palette literals (`#0d1217`, `#10151c`) rather than theme tokens.
