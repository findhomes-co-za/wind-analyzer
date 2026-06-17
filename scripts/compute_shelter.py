"""Precompute 25 m sub-grid shelter factors for all 16 wind directions.

Writes web/data/shelter_{k:02d}.json. The website multiplies the solved
75 m wind by these factors to highlight wind-protected pockets.

Usage:  .venv/bin/python scripts/compute_shelter.py
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import numpy as np

from wind_analyzer.shelter import fetch_micro_dem, shelter_factor
from wind_analyzer.winddata import SECTOR_LABELS

# Must match the "detail" domain bbox in precompute_web.py.
# Must match the "detail" domain bbox in precompute_web.py.
BBOX = dict(lon_min=18.30, lon_max=18.52, lat_min=-34.40, lat_max=-33.84)
RES_M = 25.0


def main():
    outdir = Path("web/data")
    outdir.mkdir(parents=True, exist_ok=True)

    print("fetching Copernicus GLO-30 micro-DEM ...")
    t = fetch_micro_dem(**BBOX, res_m=RES_M)
    print(f"  {t.ny} x {t.nx} at {t.dx:.0f} m, zmax {t.zs.max():.0f} m")

    dlat = float(t.lats[1] - t.lats[0])
    dlon = float(t.lons[1] - t.lons[0])
    bbox_edges = {
        "lon_min": float(t.lons[0] - dlon / 2), "lon_max": float(t.lons[-1] + dlon / 2),
        "lat_min": float(t.lats[0] - dlat / 2), "lat_max": float(t.lats[-1] + dlat / 2),
    }

    for k in range(16):
        t0 = time.time()
        direction = k * 22.5
        f = shelter_factor(t, direction)
        lo, hi = 0.35, 1.3
        q = np.round(np.clip((f - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)
        out = {
            "dir_label": SECTOR_LABELS[k],
            "dir_deg": direction,
            "bbox": bbox_edges,
            "shape": [t.ny, t.nx],
            "res_m": RES_M,
            "factor": {"min": lo, "max": hi, "b64": base64.b64encode(q.tobytes()).decode()},
        }
        (outdir / f"shelter_{k:02d}.json").write_text(json.dumps(out))
        print(f"shelter_{k:02d}.json  {SECTOR_LABELS[k]:>3}  "
              f"sheltered<0.7: {(f < 0.7).mean() * 100:.1f}% of pixels  ({time.time() - t0:.0f}s)")

    print("done.")


if __name__ == "__main__":
    main()
