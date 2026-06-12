# Cape Town South-Easter Wind Analysis

**Scenario:** strong south-easter from observations 2023-01-01 .. 2025-12-31 (6865 SE hours)
**Inflow:** 13.9 m/s at 10 m from 146° (gust factor 1.29)
**Stability:** N = 0.018 s⁻¹, Froude number (1000 m obstacle) = 1.34, mass-consistent alpha ratio r = 0.80
**Solver:** 667125 fluid cells, max |div| 2.23e-01 -> 5.01e-11 s⁻¹

## Observed south-easter climatology (upwind point, False Bay)

- Period: 2023-01-01 .. 2025-12-31, 6865 south-easterly hours (52% of Oct-Mar hours)
- Mean direction 146°, median speed 10.7 m/s, 90th percentile 13.9 m/s, max 18.4 m/s

## Suburb ranking (windiest first)

| # | Suburb | Group | Mean 10 m (m/s) | P90 (m/s) | Gust (m/s) | Speed-up | TI | Venturi | Coanda | Rotor |
|---|--------|-------|------|-----|------|----------|----|---------|--------|-------|
| 1 | Observatory | Fringe | 14.5 | 16.8 | 17.4 | 1.04 | 0.13 | 0% | 0% | 0.00 |
| 2 | De Waterkant | City Bowl | 14.1 | 15.6 | 18.3 | 1.01 | 0.19 | 0% | 0% | 0.12 |
| 3 | Salt River | Fringe | 13.8 | 15.8 | 16.7 | 1.00 | 0.13 | 0% | 0% | 0.00 |
| 4 | Green Point | Atlantic Seaboard | 13.5 | 15.3 | 16.8 | 0.97 | 0.16 | 0% | 2% | 0.00 |
| 5 | CBD | City Bowl | 12.9 | 14.8 | 19.4 | 0.93 | 0.32 | 0% | 0% | 0.53 |
| 6 | Tamboerskloof | City Bowl | 12.9 | 14.6 | 20.8 | 0.93 | 0.39 | 0% | 0% | 0.66 |
| 7 | Walmer Estate | City Bowl | 12.8 | 13.6 | 17.0 | 0.92 | 0.21 | 0% | 14% | 0.03 |
| 8 | Foreshore | City Bowl | 12.5 | 14.3 | 16.0 | 0.90 | 0.18 | 0% | 0% | 0.04 |
| 9 | Woodstock | Fringe | 12.5 | 14.0 | 15.8 | 0.90 | 0.17 | 0% | 0% | 0.00 |
| 10 | V&A Waterfront | Atlantic Seaboard | 12.4 | 15.1 | 16.0 | 0.89 | 0.19 | 0% | 0% | 0.00 |
| 11 | Bo-Kaap | City Bowl | 12.1 | 14.5 | 19.1 | 0.87 | 0.38 | 0% | 0% | 0.32 |
| 12 | Gardens | City Bowl | 11.9 | 12.7 | 19.5 | 0.86 | 0.40 | 0% | 0% | 0.69 |
| 13 | Mouille Point | Atlantic Seaboard | 11.8 | 12.4 | 15.3 | 0.85 | 0.18 | 0% | 0% | 0.00 |
| 14 | Oranjezicht | City Bowl | 11.8 | 12.8 | 19.8 | 0.85 | 0.43 | 0% | 0% | 0.70 |
| 15 | District Six | City Bowl | 11.7 | 12.6 | 17.5 | 0.85 | 0.31 | 0% | 2% | 0.31 |
| 16 | Devil's Peak Estate | City Bowl | 11.4 | 12.4 | 19.2 | 0.82 | 0.43 | 0% | 22% | 0.51 |
| 17 | Clifton | Atlantic Seaboard | 11.2 | 14.0 | 20.2 | 0.81 | 0.51 | 0% | 0% | 0.67 |
| 18 | Hout Bay | Atlantic Seaboard | 10.9 | 12.3 | 17.5 | 0.78 | 0.39 | 0% | 0% | 0.43 |
| 19 | Higgovale | City Bowl | 10.6 | 11.7 | 18.9 | 0.76 | 0.49 | 0% | 0% | 0.72 |
| 20 | Vredehoek | City Bowl | 10.5 | 11.7 | 18.4 | 0.75 | 0.48 | 0% | 0% | 0.63 |
| 21 | Bantry Bay | Atlantic Seaboard | 9.8 | 12.7 | 16.8 | 0.70 | 0.48 | 0% | 0% | 0.51 |
| 22 | Sea Point | Atlantic Seaboard | 9.7 | 11.1 | 14.7 | 0.70 | 0.32 | 0% | 0% | 0.04 |
| 23 | Three Anchor Bay | Atlantic Seaboard | 9.7 | 10.9 | 14.9 | 0.70 | 0.35 | 0% | 0% | 0.02 |
| 24 | Camps Bay | Atlantic Seaboard | 9.7 | 11.0 | 18.0 | 0.70 | 0.54 | 0% | 0% | 0.72 |
| 25 | Llandudno | Atlantic Seaboard | 9.3 | 11.5 | 15.9 | 0.67 | 0.46 | 0% | 0% | 0.01 |
| 26 | Bakoven | Atlantic Seaboard | 9.0 | 9.8 | 16.7 | 0.65 | 0.54 | 0% | 0% | 0.69 |
| 27 | Fresnaye | Atlantic Seaboard | 8.3 | 9.5 | 15.7 | 0.60 | 0.56 | 0% | 0% | 0.50 |

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