# wind-analyzer

Terrain-driven wind model for Cape Town's south-easter (the **Cape Doctor**):
which suburbs of the City Bowl and Atlantic Seaboard get hammered, and which
are sheltered by Table Mountain, Lion's Head, Signal Hill and Devil's Peak.

## What it does

1. **Terrain** — downloads real elevations (SRTM-derived terrarium tiles from
   the AWS Open Data terrain tiles bucket) and grids them at model resolution.
2. **Wind input** — pulls 3 years of hourly wind records (Open-Meteo archive)
   for a point over False Bay, upwind of the peninsula, and characterises
   south-easter events (direction sector 100–170°, Oct–Mar): median/P90 speed,
   mean direction, gust factor.
3. **Flow model** — a 3D **mass-consistent diagnostic wind model**
   (NUATMOS / MATHEW / WindNinja family). The undisturbed inflow profile is
   blocked by terrain and then minimally adjusted to be exactly
   divergence-free. A stability ratio derived from the Froude number
   (the south-easter is a stable, inversion-capped layer — the "tablecloth")
   weights vertical vs horizontal adjustment, controlling how much air goes
   *over* versus *around* the mountains:
   - **Venturi effect** — mass conservation accelerates flow squeezed through
     gaps (e.g. the saddle between Devil's Peak and Table Mountain that feeds
     the City Bowl, and Kloof Nek between Table Mountain and Lion's Head).
   - **Coanda effect** — stable flow deflects laterally and stays attached
     around curved obstacles (Lion's Head / Signal Hill), wrapping wind onto
     the Atlantic Seaboard.
4. **Diagnostics** — 10 m wind speed, speed-up factor, flow deflection,
   turbulence-intensity index (shear + lee-rotor potential + wake deficit),
   gust estimate, and classified Venturi/Coanda zones.
5. **Output** — ranked suburb table (CSV + markdown report) and five maps.

## Usage

```bash
python -m venv .venv && .venv/bin/pip install -e .
.venv/bin/wind-analyzer                  # strong (P90) south-easter, 150 m grid
.venv/bin/wind-analyzer --strength typical
.venv/bin/wind-analyzer --direction 160 --speed 18 --res 120
.venv/bin/wind-analyzer --offline        # skip climatology download
```

Outputs land in `output/`: `REPORT.md`, `ranking.csv`, `terrain.png`,
`wind_speed.png`, `speedup.png`, `turbulence.png`, `effects.png`, `fields.npz`.

## Interactive website

`web/` is a static explorer (Mapbox GL) with animated flow particles, five
overlays, a climatological wind-rose direction picker (16 directions x
typical/strong, all precomputed), suburb popups, a hover probe, a searchable
sortable ranking table (~82 suburbs in 9 groups) and 3D terrain.

Two nested model domains per scenario:

- **region** — Cape Point → Durbanville → Stellenbosch/Helderberg at 200 m
  (captures the Cape Flats south-easter jet between the Peninsula and
  Hottentots-Holland mountains),
- **detail** — the Table Mountain chain at 75 m with finer vertical levels
  (valley/ridge funneling); the map fades it in as you zoom.

Street-level wind uses local roughness from ESA WorldCover 10 m land cover,
and OSM tall buildings (≥25 m) add urban-canyon damping of the mean wind plus
a downwash gust diagnostic (street gusts approach ~75% of roof-height wind).

The **"Sheltered pockets" overlay** goes one rung finer (25 m): a Winstral Sx
upwind-horizon shelter parameter computed from Copernicus GLO-30 elevations
redistributes the solved 75 m wind within each coarse cell, highlighting calm
hollows, gully mouths and lee toes per wind direction
(`scripts/compute_shelter.py`, ~1 min for all 16 directions). That is the
information limit of open elevation data (~30 m); garden-scale shelter
(hedges, walls, single houses) would need the City of Cape Town's 1–2 m LiDAR
plus building-resolved CFD.

```bash
.venv/bin/python scripts/precompute_web.py   # ~20 min: 64 solver runs -> web/data/
python3 -m http.server 8741 -d web           # then open http://localhost:8741
```

Direction defaults to the summer south-easter; the "Winter north-wester"
preset (or the compass) flips the scenario, with per-direction observed
speeds *and stratification* (the SE is an inversion-capped stable layer;
winter NW flow is near-neutral frontal air). Screenshots in
`docs/screenshots/`.

## Validation

`tests/test_solver.py` checks the physics on idealised terrain:

- flat terrain leaves the inflow untouched,
- divergence is eliminated (>10⁴× reduction) over rough terrain,
- a ridge crest accelerates flow (continuity squeeze),
- a gap in a blocking ridge produces a Venturi jet,
- lowering the Froude number shifts flow from *over* to *around* a peak
  (more lateral deflection, less vertical motion).

```bash
.venv/bin/pytest
```

## Limitations (honest ones)

- Mass-consistent models conserve mass but not momentum: dynamic separation,
  hydraulic jumps and unsteady rotor dynamics are diagnosed heuristically,
  not simulated. For street-level engineering accuracy you'd run LES/RANS CFD
  (e.g. OpenFOAM) nested in a mesoscale model — this tool is a fast,
  physically grounded screening model.
- The stability→alpha mapping (r² = Fr²/(1+Fr²)) is a standard but heuristic
  closure; results are most trustworthy as *relative* rankings between
  suburbs, which is exactly what the tool reports.
- Buildings are sub-grid even at 75 m: the canyon damping (0.85×) and downwash
  gust rule (~0.75 × roof-height wind) are pedestrian-wind-engineering
  heuristics, not resolved aerodynamics. Individual street canyons and corner
  jets need building-resolved CFD.
- Elevation ~30 m source resolution, modelled at 75–200 m: individual streets
  are below the model's resolving power.
