# Model validation against Weather Underground PWS

Validates the Cape Doctor wind model against **all** personal weather stations
(PWS) inside the model domain, conditioned on real south-easter events.

## Method

1. **Harvest** every active PWS in the domain (lon 18.30–18.55, lat −34.10 to
   −33.84) by tiling the weather.com `near` endpoint on a 3 km grid and
   deduping → **92 stations** (`scripts/harvest_stations.py`).
2. **QC + store** hourly history for the season; keep only a usable wind signal
   — coverage ≥ 20 %, peak ≥ 4 m/s, non-constant — and record whether the vane
   reports direction → **41 kept** (all with direction), 51 rejected
   (`scripts/build_station_dataset.py`).
3. **Condition events on the False Bay forcing point** (−34.20, 18.65) — the
   point that actually drives the model (`winddata.UPWIND_POINT`), *not* the
   city point — classifying SE (105–147°) and SSE (147–172°) event hours from
   Open-Meteo. Window 2024-12-10 … 2025-01-15 → **109 SE / 227 SSE** event hours.
4. **Compare** observations to the model sampled at each station's coordinates
   from the precomputed `web/data` rasters — speed-up and the `u10/v10` wind
   vector (`scripts/validate_model.py`).

Why not compare absolute m/s directly? PWS speeds are dominated by siting
(mount height, walls, gardens) and **half the domain's stations are dead or
stuck** (all 51 rejects peaked < 4 m/s). So the comparison is **relative**:
each station's *responsiveness* (event mean ÷ its own non-event baseline) rank-
correlated against the model, and **direction**, which barely depends on siting.

## Results

### Speed — does the model rank exposure the way observations do?  ✅

| test | Spearman ρ | p | n |
|---|---|---|---|
| SE responsiveness vs model speed-up | **+0.40** | 0.015 | 37 |
| SSE responsiveness vs model speed-up | **+0.48** | 0.003 | 37 |
| SE→SSE contrast ratio (siting-cancelling) | +0.15 | 0.375 | 37 |

The model orders stations by south-easter exposure correctly and significantly.
It does **not** capture the per-station *SE-vs-SSE sensitivity contrast* — the
hardest test — consistent with the known difficulty calibrating directional
contrasts (e.g. Clifton SE vs SSE).

### Direction — model local bearing vs observed bearing

Two findings:

1. **PWS vane quality.** 7 of 37 stations (~19 %) read > 120° off in *both*
   sectors — clearly **reversed or grossly misaligned vanes** (e.g. Milnerton
   IMILNE8 reads 332° during an SE event, ~180° backwards). These are data-
   quality casualties, flagged and excluded, not model error.
2. **Systematic under-veer.** Excluding suspect vanes, the model is biased
   **anticlockwise** of observations: **SE +27°, SSE +11°** (observations are
   more *southerly*). The real south-easter wraps around the Peninsula and
   reaches the City Bowl from the S–SSE; the single-uniform-inflow diagnostic
   model holds its inflow bearing too rigidly and under-rotates it. The smaller
   SSE bias fits — the SSE inflow (157°) already sits closer to the observed
   city flow.

| metric (excl. suspect vanes) | SE | SSE |
|---|---|---|
| median \|bearing error\| | 47° | 30° |
| within 30° | 27 % | 50 % |
| signed bias (obs − model) | +27° | +11° |
| offset-robust SE→SSE veer, median \|err\| | 26° (n=37) | |

## Bottom line

- **Speed/exposure ranking: validated.** The model puts the right suburbs in
  the right order under the south-easter (ρ ≈ 0.4–0.5, significant).
- **Direction: a real, explainable bias.** The model under-rotates the
  south-easter into the City Bowl by ~25° in SE — a limitation of uniform-inflow
  diagnostic modelling, distinct from the ~1-in-5 PWS with a broken vane.
- **Not yet validated:** absolute speed magnitude (PWS siting unreliable) and
  the per-direction sensitivity contrast.

Machine-readable detail: `output/station_validation.json`.

## Interactive overlay

`scripts/precompute_stations_web.py` writes `web/data/stations.json` — per
station, per wind-rose direction: observed aggregate bearing + speed (over the
hours the False Bay input blew from that direction) paired with the model's
prediction sampled at the station. The web explorer draws each station as a
downwind arrow coloured by how closely its observed bearing matches the model
(green ≤ 20°, amber ≤ 45°, red beyond), updating as you change the wind-rose
direction. Toggle in the map legend. Screenshots in `docs/screenshots/stations-*`.
The summer window populates 12 of 16 directions (the NNE–E quarter is empty —
it barely blew from there); extend the station fetch to a full year to fill it.

## Reproduce

```bash
.venv/bin/python scripts/harvest_stations.py
.venv/bin/python scripts/build_station_dataset.py    --start 20241210 --end 20250115
.venv/bin/python scripts/validate_model.py           --start 20241210 --end 20250115
.venv/bin/python scripts/precompute_stations_web.py  --start 20241210 --end 20250115
# then: python3 -m http.server 8741 -d web   ->  http://localhost:8741/#d=SE
```
