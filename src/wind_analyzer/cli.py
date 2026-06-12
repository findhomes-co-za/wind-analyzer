"""Command-line entry point: run the full pipeline."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from .config import Domain
from .diagnostics import compute_surface
from .report import format_table, save_maps, write_csv, write_report
from .solver import MassConsistentSolver, build_levels
from .suburbs import sample_suburbs
from .terrain import fetch_dem
from .winddata import make_scenario


def main(argv=None):
    p = argparse.ArgumentParser(prog="wind-analyzer",
                                description="Cape Town south-easter terrain wind model")
    p.add_argument("--strength", choices=["typical", "strong"], default="strong",
                   help="use median or 90th-percentile observed SE speed (default strong)")
    p.add_argument("--direction", type=float, default=None, help="override wind direction (deg from)")
    p.add_argument("--speed", type=float, default=None, help="override 10 m inflow speed (m/s)")
    p.add_argument("--res", type=float, default=150.0, help="grid resolution (m)")
    p.add_argument("--zoom", type=int, default=12, help="terrain tile zoom level")
    p.add_argument("--offline", action="store_true", help="skip the wind-climatology download")
    p.add_argument("--outdir", default="output", help="output directory")
    args = p.parse_args(argv)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    print("[1/5] Terrain: downloading/gridding elevation ...")
    domain = Domain(resolution_m=args.res)
    terrain = fetch_dem(domain, zoom=args.zoom)
    print(f"      grid {terrain.ny} x {terrain.nx} at {terrain.dx:.0f} m, "
          f"max elevation {terrain.zs.max():.0f} m")

    print("[2/5] Wind: characterising the south-easter ...")
    scn, stats = make_scenario(strength=args.strength, offline=args.offline)
    if args.direction is not None:
        scn.direction_deg = args.direction
        scn.label += f" (direction override {args.direction:.0f} deg)"
    if args.speed is not None:
        scn.speed_10m = args.speed
        scn.label += f" (speed override {args.speed:.1f} m/s)"
    print(f"      {scn.label}")
    print(f"      inflow {scn.speed_10m:.1f} m/s from {scn.direction_deg:.0f} deg | "
          f"Froude {scn.froude():.2f} -> alpha ratio {scn.alpha_ratio():.2f}")

    print("[3/5] Solving mass-consistent 3D flow ...")
    t0 = time.time()
    zf = build_levels(domain.dz0, domain.dz_ratio, domain.z_top)
    solver = MassConsistentSolver(terrain.zs, terrain.dx, terrain.dy, zf,
                                  alpha_ratio=scn.alpha_ratio())
    u_in, v_in = scn.components(1.0)
    prof = scn.profile(solver.zc)
    flow = solver.solve(prof * u_in, prof * v_in, verbose=True)
    print(f"      {int(solver.fluid.sum())} fluid cells, {solver.nz} levels, "
          f"{time.time() - t0:.1f} s")
    print(f"      max |divergence| {flow.div_before:.2e} -> {flow.div_after:.2e} 1/s")

    print("[4/5] Diagnostics: surface wind, turbulence, Venturi/Coanda ...")
    sf = compute_surface(flow, terrain, scn)
    rows = sample_suburbs(terrain, sf)

    print("[5/5] Writing maps and report ...")
    save_maps(terrain, sf, scn, outdir)
    write_csv(rows, outdir / "ranking.csv")
    write_report(outdir, scn, stats, rows, {
        "cells": int(solver.fluid.sum()),
        "div_before": flow.div_before,
        "div_after": flow.div_after,
    })
    np.savez_compressed(
        outdir / "fields.npz",
        speed10=sf.speed10, u10=sf.u10, v10=sf.v10, speedup=sf.speedup,
        ti=sf.ti, gust=sf.gust, rotor=sf.rotor, zs=terrain.zs,
        lats=terrain.lats, lons=terrain.lons,
    )

    print()
    print(format_table(rows))
    print(f"\nReport: {outdir / 'REPORT.md'}  |  maps + ranking.csv alongside it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
