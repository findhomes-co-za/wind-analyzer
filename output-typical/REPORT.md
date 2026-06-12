# Cape Town South-Easter Wind Analysis

**Scenario:** typical south-easter from observations 2023-01-01 .. 2025-12-31 (6865 SE hours)
**Inflow:** 10.7 m/s at 10 m from 146° (gust factor 1.29)
**Stability:** N = 0.018 s⁻¹, Froude number (1000 m obstacle) = 1.03, mass-consistent alpha ratio r = 0.72
**Solver:** 667125 fluid cells, max |div| 1.71e-01 -> 5.75e-11 s⁻¹

## Observed south-easter climatology (upwind point, False Bay)

- Period: 2023-01-01 .. 2025-12-31, 6865 south-easterly hours (52% of Oct-Mar hours)
- Mean direction 146°, median speed 10.7 m/s, 90th percentile 13.9 m/s, max 18.4 m/s

## Suburb ranking (windiest first)

| # | Suburb | Group | Mean 10 m (m/s) | P90 (m/s) | Gust (m/s) | Speed-up | TI | Venturi | Coanda | Rotor |
|---|--------|-------|------|-----|------|----------|----|---------|--------|-------|
| 1 | Observatory | Fringe | 11.2 | 13.2 | 13.5 | 1.05 | 0.13 | 0% | 0% | 0.00 |
| 2 | De Waterkant | City Bowl | 10.8 | 12.0 | 14.3 | 1.01 | 0.21 | 0% | 0% | 0.16 |
| 3 | Salt River | Fringe | 10.7 | 12.2 | 12.9 | 1.00 | 0.13 | 0% | 0% | 0.00 |
| 4 | Green Point | Atlantic Seaboard | 10.4 | 11.8 | 12.9 | 0.97 | 0.16 | 0% | 7% | 0.00 |
| 5 | Walmer Estate | City Bowl | 9.9 | 10.5 | 13.1 | 0.92 | 0.21 | 0% | 18% | 0.04 |
| 6 | CBD | City Bowl | 9.8 | 11.2 | 15.8 | 0.91 | 0.40 | 0% | 0% | 0.74 |
| 7 | Tamboerskloof | City Bowl | 9.7 | 11.1 | 17.0 | 0.91 | 0.48 | 0% | 0% | 0.91 |
| 8 | Woodstock | Fringe | 9.6 | 10.8 | 12.1 | 0.90 | 0.17 | 0% | 3% | 0.00 |
| 9 | Foreshore | City Bowl | 9.6 | 10.9 | 12.4 | 0.89 | 0.19 | 0% | 0% | 0.05 |
| 10 | V&A Waterfront | Atlantic Seaboard | 9.5 | 11.7 | 12.3 | 0.89 | 0.19 | 0% | 0% | 0.00 |
| 11 | Bo-Kaap | City Bowl | 9.1 | 11.2 | 15.0 | 0.85 | 0.43 | 0% | 0% | 0.44 |
| 12 | Mouille Point | Atlantic Seaboard | 9.0 | 9.5 | 11.7 | 0.84 | 0.19 | 0% | 0% | 0.00 |
| 13 | District Six | City Bowl | 9.0 | 9.7 | 13.9 | 0.84 | 0.35 | 0% | 7% | 0.43 |
| 14 | Gardens | City Bowl | 8.9 | 9.5 | 16.0 | 0.83 | 0.50 | 0% | 0% | 0.95 |
| 15 | Oranjezicht | City Bowl | 8.8 | 9.6 | 16.2 | 0.83 | 0.53 | 0% | 0% | 0.97 |
| 16 | Devil's Peak Estate | City Bowl | 8.7 | 9.6 | 15.3 | 0.81 | 0.49 | 0% | 35% | 0.70 |
| 17 | Clifton | Atlantic Seaboard | 8.6 | 10.7 | 16.3 | 0.80 | 0.58 | 0% | 0% | 0.93 |
| 18 | Hout Bay | Atlantic Seaboard | 8.3 | 9.4 | 14.0 | 0.77 | 0.44 | 0% | 3% | 0.59 |
| 19 | Higgovale | City Bowl | 7.9 | 8.7 | 15.2 | 0.74 | 0.59 | 0% | 0% | 1.00 |
| 20 | Vredehoek | City Bowl | 7.8 | 8.8 | 14.7 | 0.73 | 0.56 | 0% | 0% | 0.87 |
| 21 | Bantry Bay | Atlantic Seaboard | 7.4 | 9.8 | 13.1 | 0.69 | 0.51 | 0% | 0% | 0.71 |
| 22 | Three Anchor Bay | Atlantic Seaboard | 7.3 | 8.4 | 11.2 | 0.68 | 0.35 | 0% | 0% | 0.02 |
| 23 | Sea Point | Atlantic Seaboard | 7.3 | 8.4 | 11.1 | 0.68 | 0.34 | 0% | 0% | 0.06 |
| 24 | Camps Bay | Atlantic Seaboard | 7.2 | 8.2 | 14.3 | 0.68 | 0.62 | 0% | 0% | 1.00 |
| 25 | Llandudno | Atlantic Seaboard | 7.1 | 8.8 | 12.1 | 0.66 | 0.47 | 0% | 0% | 0.02 |
| 26 | Bakoven | Atlantic Seaboard | 6.7 | 7.3 | 13.3 | 0.63 | 0.62 | 0% | 0% | 0.95 |
| 27 | Fresnaye | Atlantic Seaboard | 6.2 | 7.1 | 11.9 | 0.58 | 0.60 | 0% | 0% | 0.69 |

## Maps

![terrain](terrain.png)
![wind speed](wind_speed.png)
![speed-up](speedup.png)
![turbulence](turbulence.png)
![effects](effects.png)

## Model notes and limitations

- Mass-consistent diagnostic model (NUATMOS/WindNinja family): mass is
  conserved exactly but momentum is not solved, so dynamic separation,
  hydraulic jumps and unsteady gusts are represented heuristically
  (rotor/TI diagnostics), not explicitly.
- Venturi channeling and Coanda-style attachment emerge from the
  continuity solve with stability-weighted vertical motion; the masks
  shown are diagnostic classifications of the solved field.
- Elevation: SRTM-derived terrarium tiles (~30 m source, modelled at
  grid resolution). Wind climatology: Open-Meteo reanalysis archive.