# Panel UX Analysis & Simplification Plan — Cape Town Wind Explorer

> **Status: implemented 2026-06-17.** §0 cuts, the pinned legend (R1), the
> settings popover (R5), the in-panel View control (R4), the honesty label (R7),
> prose trim (R3) and the dup-row fix are all live. The 16 `run_*_typical.json`
> files were deleted (web/data 155 MB → 98 MB) and `precompute_web.py` now emits
> strong only.
>
> **Follow-ups since:** (a) wind-flow animation is now always-on (toggle removed
> from the map; the panel's second View button became a **2D/3D switch**).
> (b) The **tabs were merged into one panel** to fix the direction→ranking
> coupling: compass + 2D/3D stay pinned at the top while the ranking scrolls in
> its own region directly below and re-sorts live as you spin the compass (the
> rose was tightened 280 px → 196 px to make room; header reads "Suburb ranking
> · for the SE wind"). Verified desktop (1440×820, panel fits with the table in
> its own ~4-row scroll) and mobile (390×844, ~2.1 screens, table bounded to
> 62 vh). After screenshots: `docs/screenshots/after-desktop.jpeg`,
> `docs/screenshots/after-mobile.jpeg`.

_Analysis date: 2026-06-17. Scope: the left sidebar panel (`web/index.html`,
`web/style.css`, `web/app.js`) on desktop and mobile, plus the on-map controls
that belong to the same interaction loop._

Evidence captured for this analysis:
- Desktop layout — `docs/screenshots/explorer-redesign.jpeg`
- Suburbs tab — `docs/screenshots/explorer-table-final.jpeg`
- Full mobile scroll (390×844) — `docs/screenshots/ux-mobile-full-panel.jpeg`
- Live fold measurements at 390×844 (mobile) and 1440×820 (laptop) — §3.
- Typical-vs-strong field comparison (justifies §0) — §0.

---

## 0. Scope decision (2026-06-17) — cut the feature set first

Before any layout work, we are **reducing what the tool does**. The original
panel's biggest UX problem was simply *too many features competing for one
column*; removing features is the highest-leverage fix and it makes the rest of
the redesign far smaller.

**Locked decisions:**

1. **The map shows only street-level wind.** Cut Gusts, Speed-up, Turbulence, and
   Effect-zones as *map layers*.
2. **Fix the scenario to strong wind (top 10%).** Remove the Typical/Strong
   toggle entirely.
3. **Keep the Suburbs ranking tab and its multi-factor score intact**
   (Score = 55% mean + 30% gusts + 15% turbulence; columns Score/Wind/Gust/Turb).
   Gusts and turbulence stay as *ranking inputs and popup detail*, just not as
   map layers.

### Why dropping the strength toggle is safe (verified, not assumed)

The concern: this model has Froude-number-dependent physics (downslope windstorm,
lee rotors), and Froude number depends on wind speed — so a stronger inflow
*could* change the map even at the same direction. I checked the actual
precomputed fields (SE, `run_06_typical` vs `run_06_strong`).

The displayed colour scale already auto-stretches to each scenario's inflow
(`overlayRange()`), so what the eye compares is each field *normalised by its own
inflow*. On that basis the two scenarios are nearly identical:

| Street-level wind, SE | Region grid (118k cells) | Detail grid (224k cells) |
|---|---|---|
| Median shape difference | **0.5%** | **0.6%** |
| 90th percentile | 2.8% | 3.3% |
| 99th percentile | 10.6% | 10.2% |
| Cells differing > 20% | **0.0%** | **0.0%** |
| Raw strong/typical mean ratio | 1.266 | 1.270 |

The last row is the proof: the field scales by ~1.27 — almost exactly the inflow
ratio (13.87/10.88 = 1.275) — so the model is **nearly linear in inflow speed**
and the map barely moves. The residual differences (<3% over 90% of the map, max
~15–20%) sit only in a few Froude-sensitive lee-slope cells. **Conclusion: which
strength you show is, visually, a coin flip — so collapsing to one is free.**

**Why strong rather than typical:** the choice is visually immaterial (above), so
pick the one that fits the story. The tagline is literally _"see who gets
blasted"_ — that's the strong (top-10%) case. Strong is also already the app
default (`state.strength = "strong"`), so the Suburbs table needs no change.

> ⚠️ **Honesty caveat to carry into the UI:** we now show *only* the top-10%
> blow, not everyday wind. The map must say so plainly (see R7) so nobody reads
> these speeds as typical conditions.

### What these cuts remove from the product

| Removed | Files / code touched |
|---|---|
| 5 of 6 map overlays (gust, speedup, ti, effects, none) | `OVERLAYS` in `app.js`; the `#overlayList` picker; categorical/effects legend; `drawDomainField` categorical branch |
| Strength toggle + caption | `#strengthSeg` section in `index.html`; `setStrength`, `updateStrengthSeg`, preset strength-setting |
| Layer-swapping legend logic | `renderLegend` collapses to one fixed gradient |
| The 16 `run_XX_typical.json` data files | `web/data/` (≈ halves the data payload); `precompute_web.py` can stop emitting them |
| `o=` and `s=` URL params | `syncHash` / `parseHash` |

Net: the Wind tab loses its two largest sections (the ~360 px overlay block and
the strength control), and the legend stops needing to change — which finally
lets it live where it belongs (on the map). Everything below is rewritten around
this smaller surface.

---

## 1. Who is the user, and what is the core task?

Two audiences share this page:

- **The curious local / casual visitor** (likely mobile, from a shared link):
  _"Is my suburb windy? Where's calm? What does the south-easter actually do?"_
- **The enthusiast** (desktop): explores the suburbs ranking, 3D, the physics.

The **core loop, after the cuts, is shorter** — there's no "choose a layer" step:

> **Pick a direction** (compass / preset) → **read the wind map** (needs the
> legend) → **drill into suburbs** (table, probe, pins, popups).

The redesign should make those three steps obvious and, on most screens,
visible without scrolling.

---

## 2. Panel inventory — after the cuts

**Wind tab (new):**
1. Header: title + 1-line tagline + `[units]` `[How it works]`
2. Tab bar: `Wind | Suburbs`
3. Presets: `☀️ Summer SE | 🌧️ Winter NW` (now pure direction quick-picks)
4. Wind direction: compass rose + a tightened caption
5. _(Strength — **removed**)_
6. _(Map-layer picker — **removed**; only one layer)_
7. _(Legend — **moved onto the map**, fixed, see R1)_
8. _(Opacity — **demoted** to a small control / settings, see R5)_

**Suburbs tab (unchanged):** ranking + CSV, search, 9 group filters, sortable
table (`# / Suburb / Score / Wind / Gust / Turb`), caption, score ⓘ popover.

**On-map:** zoom, compass, pitch, **3D toggle, animation toggle** (relabel — R4),
scale bar, **fixed wind legend (new)**, scenario chip (top-left), probe
(hover), pocket pins, suburb popups.

---

## 3. Measured evidence — where the fold falls (and the projected win)

Positions measured live on the *current* app.

### Mobile — 390 × 844 (layout is `column-reverse`: map on top, panel below)

| Element | Scroll top (px) | In first screen? |
|---|---|---|
| Map (hero) | 0–523 | ✅ |
| Header | 542 | ✅ |
| Tab bar | 681 | ✅ |
| **Compass (primary)** | **789–1146** | ❌ starts at the fold |
| Strength _(to be removed)_ | 1186 | ❌ |
| Map-layer _(to be removed)_ | 1310–1671 | ❌ |
| **Legend** _(to move to map)_ | **1789** | ❌ ~1,270 px below the map |

Total document height **1,977 px ≈ 2.3 screens**.

### Desktop — 1440 × 820 (sidebar is a `100vh` scroll container, content 1,401 px)

Overflows by **581 px**. The legend sits at 1,213 px — **393 px below the fold**.
It only fits without scrolling on viewports taller than ~1,400 px (≈ no laptops).

### Projected after the cuts

Removing the strength section (~95 px), the map-layer block (~480 px incl.
opacity), and the in-panel legend (~90 px) takes the Wind-tab content from
**~1,401 px → ~735 px**. That **fits an 820 px laptop sidebar with no scroll**,
and on mobile cuts the total page to **~1.5 screens** with nothing essential
stranded far below the compass. Most of the original layout problems dissolve
because the content simply got short.

---

## 4. Findings — and what the cut already fixes

| # | Finding | Status after cuts |
|---|---|---|
| F1 | **Legend buried** below the fold on every device; no hover-probe on touch, so on mobile it's the *only* colour decoder and the hardest to reach. | **Now easy to fix** — there's a single fixed legend; pin it to the map (R1). |
| F2 | **No hierarchy** — every section equally weighted, all behind a caption. | **Largely resolved** — far fewer sections; remaining ones get a light hierarchy (R2). |
| F3 | **Too much always-on prose** — taglines, 6 overlay descriptions, a 3-line map-layer caption duplicating the modal. | **Mostly gone** — the overlay descriptions and strength/layer captions disappear with their sections (R3 trims the rest). |
| F4 | **3D + animation undiscoverable** — tiny `3D` / `〰` map buttons, `〰` unlabeled, announced only in a caption that's being deleted. | **Still open** — and now *more* urgent, since the caption that mentioned them is gone (R4). |
| F5 | **Set-once controls crowd explore-often ones** (units, opacity). | **Simpler** — opacity is the only tuner left; demote it (R5). |
| F6 | **Mobile loop inverted/long**; no sticky tabs; no touch probe. | **Improved by brevity**; sticky tabs + map legend still recommended (R6). |
| F7 | **Redundancy / bugs** — suburb popup prints "Speed-up" twice (`app.js:761`/`:763`); score formula repeated 4×; grid-resolution prose duplicated. | **Still open** (R7); already flagged as a task. |

What's good and stays: the compass rose (excellent dual picker + climatology);
presets as quick-start; the Suburbs tab's search → filter → sortable table with a
ⓘ score popover (the disclosure pattern to copy); map-on-top on mobile.

---

## 5. Recommendations (revised for the smaller surface)

### R1 — Pin the (now single, fixed) wind legend to the map
With one layer, the legend never changes — so it no longer belongs in a scrolling
panel at all. Render it as a **small, fixed key on the map** (bottom-left, near
the probe): the turbo gradient with min/mid/max labels plus the green calm-pocket
pin note. _Why: the key is finally always visible while reading the map, on every
device, with zero scroll — and on mobile this replaces the missing hover-probe as
the colour decoder. `renderLegend` collapses from four branches to one._

### R2 — Give the short panel a light hierarchy
With strength and the layer picker gone, the Wind tab is essentially
**Presets → Compass**. Group them under one quiet "Wind direction" heading so the
panel reads as a single obvious step, and let the compass be the visual centre of
gravity. No heavy restructure needed — the brevity does most of the work.

### R3 — Trim the surviving prose
- Tagline to one line.
- Tighten the rose caption to the essentials (share % + strong speed). It can
  still mention the typical speed as context, but there's no toggle to explain.
- Push any remaining grid-resolution / model detail to the "How it works" modal
  (it's already there). _Why: the casual user gets a clean surface; depth stays
  one tap away._

### R4 — Make 3D + animation discoverable and legible (now urgent)
The caption that pointed at them is being deleted, so without action they become
invisible. Keep them as map-view controls but **relabel** (`〰` → an icon **plus**
a short word like `Flow`/`Wind`), and add a tiny matching **"View" affordance in
the panel**. Fix the mobile collision where the scenario chip wraps into the
top-right button stack (hard `max-width` on the chip, or move it to the map's
bottom on mobile). _Why: these showcase features earn near-zero discovery today
and the one breadcrumb to them is going away._

### R5 — Demote opacity (the only tuner left)
Opacity is set once. Move it off the main flow: either a small control on the map
(next to the legend) or into a `⚙` settings popover alongside **units**. A units
popover can also show all three options at once instead of the current cycling
button that hides `m/s` and `kt`. _Why: separate "configure once" from "drive
often"; with so few controls left, even one stray tuner stands out._

### R6 — Mobile polish (cheaper now that the panel is short)
- **Sticky `Wind | Suburbs` tab bar** so the mode switch survives scrolling.
- **Map-pinned legend** (R1) — the top mobile win, since there's no hover probe.
- Optionally a **tap-to-probe** for point values on touch.
- With the panel down to ~1.5 screens, an accordion is probably no longer needed
  — re-measure after the cuts before adding one.

### R7 — Honesty label + quick fixes
- **Label the scenario clearly as the strong (top-10%) case**, not everyday wind
  — in the scenario chip and a one-liner near the compass — so the single fixed
  scenario isn't mistaken for average conditions. (Carries the §0 caveat.)
- Remove the duplicated **"Speed-up"** row in the suburb popup
  (`app.js:761`/`:763`).
- De-duplicate the score formula (table popover / popup / modal) and any
  remaining grid-resolution prose.

---

## 6. Before / after — Wind tab

| Today | After cuts + redesign |
|---|---|
| Title + 3-line tagline | Title + 1-line tagline |
| `[km/h]` `[How it works]` | `[How it works]` `[⚙ units + opacity]` |
| Tab bar | **Sticky** tab bar |
| Presets (set dir + strong) | Presets (set direction) |
| Compass rose (+ caption + rose legend) | Compass rose (tighter caption) — _panel ends here_ |
| Strength + caption | **removed** |
| Map-layer picker (6 descriptions) | **removed** |
| Opacity + 3-line caption | **→ settings / map control** |
| Legend (bottom, below fold) | **→ fixed key pinned on the map** |
| Footer credits | collapsed / smaller |

Net: the Wind tab becomes **Presets → Compass**, fits without scrolling on a
laptop, and the legend is always visible on the map.

---

## 7. Toggle-triage table (post-cut)

| Control | Frequency | Recommended home | Why |
|---|---|---|---|
| Direction (compass) | constant | Panel — top | The core interaction |
| Presets | frequent (entry) | Panel — above compass | One-tap common directions |
| **Wind legend** | **constant (read)** | **Fixed on the map** | One layer ⇒ never changes ⇒ pin it |
| Tab `Wind/Suburbs` | frequent | Panel — **sticky** | Mode switch mustn't scroll away |
| Suburb search/filter/sort | frequent (in tab) | Suburbs tab (as-is) | Already well-placed |
| 3D terrain | occasional | Map corner — **labelled** + panel mirror | Improve discovery (R4) |
| Wind animation | occasional | Map corner — **labelled** + panel mirror | `〰` is cryptic (R4) |
| **Units** | set once | `⚙` settings popover | Show all 3 options at once |
| **Opacity** | set once | `⚙` settings / small map control | Tuned once, then ignored |
| ~~Map layer~~ | — | **removed** | Only street-level wind now |
| ~~Strength~~ | — | **removed** | Visually identical to typical (§0) |
| How it works | reference | Header button | Deep content on demand |
| Score ⓘ / CSV | reference / rare | Suburbs tab (as-is) | Good as-is |

---

## 8. Effort vs. impact

| Step | Impact | Effort |
|---|---|---|
| §0 Cut layers + strength toggle (+ prune `*_typical.json`, URL params) | ★★★ | Low–Med |
| R1 Fixed legend pinned to map | ★★★ | Low |
| R3 Trim prose | ★★ | Low |
| R4 Relabel + surface 3D/animation | ★★ | Low |
| R7 Honesty label + dup-row fix | ★★ | Trivial–Low |
| R5 Settings popover (units, opacity) | ★ | Med |
| R6 Sticky tabs / tap-probe | ★★ (mobile) | Med |

**Suggested sequence:** §0 (the cuts — unlocks everything) → R1 + R3 + R7 (fast,
high-value cleanups) → R4 → R5 + R6 (the polish). Re-measure the fold after §0+R1
before deciding whether R6's accordion is still warranted.

---

## 9. Implementation checklist (concrete, for when we build it)

- [ ] `app.js`: reduce `OVERLAYS` to `speed10` only; delete the categorical /
      effects / gust / ti / speedup branches in `drawDomainField` & `renderLegend`.
- [ ] `index.html`: delete the `#overlayList` section and the `#strengthSeg`
      section; move `#legendSection` markup onto the map container.
- [ ] `app.js`: remove `setStrength` / `updateStrengthSeg`; presets set direction
      only; hard-code `state.strength = "strong"`.
- [ ] `app.js`: `syncHash`/`parseHash` drop `o=` and `s=`.
- [ ] Render the fixed legend as an on-map control (bottom-left), incl. the
      calm-pocket pin note.
- [ ] Relabel the `〰` view button; add an in-panel "View" affordance.
- [ ] Add the "strong / top-10%" honesty label (chip + near compass).
- [ ] Remove the duplicate "Speed-up" popup row (`app.js:761`/`:763`).
- [ ] `precompute_web.py`: stop emitting `run_XX_typical.json`; delete the 16
      existing ones from `web/data/`.
- [ ] Demote opacity + units into a `⚙` settings popover (or small map control).
- [ ] Make the tab bar sticky; re-measure the mobile fold.

---

## 10. Open question for the product owner

The Suburbs ranking keeps gusts + turbulence as score inputs, but they're no
longer shown as map layers. If, after using it, that feels inconsistent (the map
says "wind" while the table ranks on a blended score), revisit whether the score
should simplify to mean wind too. Deferred for now per the "map layers only"
decision.
