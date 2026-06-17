"""Precompute wind fields for the web explorer.

Two nested model domains per scenario:
  region — Cape Point to Durbanville to Stellenbosch/Helderberg at 200 m,
  detail — the Table Mountain chain / City Bowl / Atlantic Seaboard at 75 m
           with finer vertical levels, to resolve valley and ridge funneling.

16 compass directions, each at the sector's strong (90th-percentile) speed —
the displayed street-level field is near-linear in inflow and the web colour
scale auto-stretches, so a single strength carries the map (see
docs/ux-panel-analysis.md §0). Per-direction stratification, WorldCover
roughness for street-level wind, and OSM tall buildings (canyon + downwash
diagnostics).

Usage:  .venv/bin/python scripts/precompute_web.py [--only-dir SE]
"""

from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path

import numpy as np

from wind_analyzer.buildings import fetch_tall_buildings, rasterize_heights
from wind_analyzer.config import Domain, WindScenario
from wind_analyzer.diagnostics import compute_surface
from wind_analyzer.landcover import fetch_z0
from wind_analyzer.solver import MassConsistentSolver, build_levels
from wind_analyzer.suburbs import LANDMARKS, SUBURBS, sample_suburbs
from wind_analyzer.terrain import fetch_dem
from wind_analyzer.winddata import SECTOR_LABELS, fetch_climatology, sector_stats

DOMAINS = {
    "region": dict(
        domain=Domain(lon_min=18.28, lon_max=19.00, lat_min=-34.42, lat_max=-33.78,
                      resolution_m=200.0, z_top=5200.0, dz0=16.0, dz_ratio=1.20),
        zoom=12,
    ),
    "detail": dict(
        # Extends down the whole Cape Peninsula to take in Muizenberg and
        # Cape Point (lat_min -34.40 gives the Cape Point headland margin from
        # the boundary; lon_max 18.52) — still nested inside the region domain.
        domain=Domain(lon_min=18.30, lon_max=18.52, lat_min=-34.40, lat_max=-33.84,
                      resolution_m=75.0, z_top=4700.0, dz0=10.0, dz_ratio=1.17),
        zoom=13,
    ),
}

# Bulk stability N (1/s) by direction: the SE-quadrant south-easter is an
# inversion-capped stable marine layer (the "tablecloth"); winter W/NW flow
# is near-neutral frontal air; other directions transitional.
STABILITY_BY_SECTOR = {
    "N": 0.012, "NNE": 0.013, "NE": 0.013, "ENE": 0.015,
    "E": 0.018, "ESE": 0.018, "SE": 0.018, "SSE": 0.018,
    "S": 0.016, "SSW": 0.014, "SW": 0.014, "WSW": 0.011,
    "W": 0.010, "WNW": 0.010, "NW": 0.010, "NNW": 0.011,
}


def air_note(bvf: float) -> str:
    if bvf >= 0.016:
        return "stable capped layer (tablecloth regime)"
    if bvf <= 0.011:
        return "near-neutral frontal air"
    return "moderately stable air"


def q8(a: np.ndarray, lo: float, hi: float) -> dict:
    x = np.clip((np.nan_to_num(a) - lo) / (hi - lo), 0.0, 1.0)
    raw = np.round(x * 255).astype(np.uint8).tobytes()
    return {"min": lo, "max": hi, "b64": base64.b64encode(raw).decode()}


def encode_fields(sf) -> dict:
    effects = (sf.channel_mask.astype(np.uint8)
               + 2 * sf.coanda_mask.astype(np.uint8)
               + 4 * sf.downwash_mask.astype(np.uint8))
    return {
        "speed10": q8(sf.speed10, 0.0, 35.0),
        "gust": q8(sf.gust, 0.0, 45.0),
        "speedup": q8(sf.speedup, 0.0, 2.0),
        "ti": q8(sf.ti, 0.0, 0.7),
        "rotor": q8(sf.rotor, 0.0, 1.0),
        "u10": q8(sf.u10, -40.0, 40.0),
        "v10": q8(sf.v10, -40.0, 40.0),
        "effects": {"min": 0, "max": 7,
                    "b64": base64.b64encode(effects.tobytes()).decode()},
    }


def domain_static(terrain) -> dict:
    dlat = float(terrain.lats[1] - terrain.lats[0])
    dlon = float(terrain.lons[1] - terrain.lons[0])
    return {
        "bbox": {
            "lon_min": float(terrain.lons[0] - dlon / 2),
            "lon_max": float(terrain.lons[-1] + dlon / 2),
            "lat_min": float(terrain.lats[0] - dlat / 2),
            "lat_max": float(terrain.lats[-1] + dlat / 2),
        },
        "shape": [terrain.ny, terrain.nx],
        "dx_m": terrain.dx,
        "elevation_u16": base64.b64encode(
            np.round(terrain.zs).astype("<u2").tobytes()).decode(),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--outdir", default="web/data")
    p.add_argument("--only-dir", default=None, help="compute one sector label (smoke test)")
    args = p.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print("preparing inputs (terrain, landcover, buildings, climatology) ...")
    grids = {}
    for name, cfg in DOMAINS.items():
        d = cfg["domain"]
        terrain = fetch_dem(d, zoom=cfg["zoom"])
        z0 = fetch_z0(terrain)
        grids[name] = {"domain": d, "terrain": terrain, "z0": z0,
                       "zf": build_levels(d.dz0, d.dz_ratio, d.z_top)}
        print(f"  {name}: {terrain.ny}x{terrain.nx} @ {terrain.dx:.0f} m, "
              f"zmax {terrain.zs.max():.0f} m, levels {len(grids[name]['zf']) - 1}, "
              f"z0 {'ok' if z0 is not None else 'fallback'}")

    reg_dom = DOMAINS["region"]["domain"]
    blds = fetch_tall_buildings(
        (reg_dom.lat_min, reg_dom.lon_min, reg_dom.lat_max, reg_dom.lon_max))
    print(f"  tall buildings (>=25 m): {len(blds)}")
    for name, g in grids.items():
        g["bld_h"] = rasterize_heights(g["terrain"], blds)

    clim = fetch_climatology()
    sectors = sector_stats(clim)

    # Suburbs are sampled from the finest domain that contains them.
    det = grids["detail"]["domain"]
    in_detail = [s for s in SUBURBS
                 if det.lon_min < s.lon < det.lon_max and det.lat_min < s.lat < det.lat_max]
    in_region_only = [s for s in SUBURBS if s not in in_detail]
    print(f"  suburbs: {len(in_detail)} in detail domain, {len(in_region_only)} region-only")

    static = {
        "domains": {name: domain_static(g["terrain"]) for name, g in grids.items()},
        "suburbs": [{"name": s.name, "lat": s.lat, "lon": s.lon, "group": s.group,
                     "radius_m": s.radius_m} for s in SUBURBS],
        "landmarks": [{"name": n, "lat": la, "lon": lo, "height_m": h}
                      for n, la, lo, h in LANDMARKS],
        "buildings": [b for b in blds if b["height_m"] >= 40.0],
        "sectors": sectors,
        "climatology_period":
            f"{clim['hourly']['time'][0][:10]} .. {clim['hourly']['time'][-1][:10]}",
    }
    (outdir / "static.json").write_text(json.dumps(static))
    print("static.json written")

    for k, sec in enumerate(sectors):
        if args.only_dir and sec["label"] != args.only_dir.upper():
            continue
        for strength in ("strong",):   # strong only — see module docstring
            t0 = time.time()
            speed = sec["speed_p90"]
            scn = WindScenario(
                direction_deg=sec["direction"], speed_10m=speed,
                gust_factor=sec["gust_factor"],
                label=f"{strength} {sec['label']} wind ({speed:.1f} m/s observed)",
                bvf=STABILITY_BY_SECTOR[sec["label"]],
            )
            run_domains, rows = {}, []
            for name, g in grids.items():
                terrain = g["terrain"]
                solver = MassConsistentSolver(terrain.zs, terrain.dx, terrain.dy,
                                              g["zf"], alpha_ratio=scn.alpha_ratio())
                u_in, v_in = scn.components(1.0)
                prof = scn.profile(solver.zc)
                flow = solver.solve(prof * u_in, prof * v_in)
                sf = compute_surface(flow, terrain, scn,
                                     z0=g["z0"] if g["z0"] is not None else 0.05,
                                     bld_h=g["bld_h"])
                run_domains[name] = {"shape": [terrain.ny, terrain.nx],
                                     "fields": encode_fields(sf)}
                rows += sample_suburbs(
                    terrain, sf, in_detail if name == "detail" else in_region_only)
            rows.sort(key=lambda r: r["speed10_mean"], reverse=True)

            run = {
                "meta": {
                    "dir_deg": sec["direction"], "dir_label": sec["label"],
                    "strength": strength, "speed_10m": round(speed, 2),
                    "gust_factor": round(sec["gust_factor"], 2),
                    "froude": round(scn.froude(), 2),
                    "alpha_ratio": round(scn.alpha_ratio(), 2),
                    "bvf": scn.bvf, "air_note": air_note(scn.bvf),
                    "n_hours": sec["n_hours"], "sparse": sec["sparse"],
                    "summer_share": sec["summer_share"],
                    "winter_share": sec["winter_share"],
                },
                "domains": run_domains,
                "ranking": rows,
            }
            name = f"run_{k:02d}_{strength}.json"
            (outdir / name).write_text(json.dumps(run))
            print(f"{name}: {sec['label']:>3} {speed:5.1f} m/s  Fr {scn.froude():.2f}  "
                  f"({time.time() - t0:.0f}s)")

    print("done.")


if __name__ == "__main__":
    main()
