"""Aerodynamic roughness from ESA WorldCover 10 m land cover.

The displayed wind is "street level": the 10 m log-law correction uses the
local surface roughness, so forests, vineyards, dense urban fabric and open
water all modify the wind people actually experience. Source: ESA WorldCover
2021 v200 (public COG on AWS); the S36E018 tile covers the whole Cape
Peninsula and Boland.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from .terrain import TerrainGrid

WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_S36E018_Map.tif"
)

# WorldCover class -> roughness length z0 (m)
Z0_BY_CLASS = {
    10: 0.80,    # tree cover
    20: 0.15,    # shrubland (fynbos)
    30: 0.05,    # grassland
    40: 0.10,    # cropland (vineyards, fields)
    50: 0.55,    # built-up
    60: 0.02,    # bare / sparse
    70: 0.001,   # snow/ice (n/a here)
    80: 0.0002,  # open water
    90: 0.05,    # herbaceous wetland
    95: 0.30,    # mangroves (n/a)
    100: 0.03,   # moss/lichen
}
Z0_DEFAULT = 0.05


def fetch_z0(terrain: TerrainGrid, cache_dir: str | Path = "data/cache") -> np.ndarray | None:
    """Per-cell roughness map on the model grid; None if the fetch fails."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(
        f"z0_{terrain.lons[0]:.5f}_{terrain.lats[0]:.5f}_{terrain.nx}_{terrain.ny}".encode()
    ).hexdigest()[:12]
    cache = cache_dir / f"z0_{key}.npz"
    if cache.exists():
        return np.load(cache)["z0"]

    try:
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.windows import from_bounds

        dlon = terrain.lons[1] - terrain.lons[0]
        dlat = terrain.lats[1] - terrain.lats[0]
        bounds = (
            terrain.lons[0] - dlon / 2, terrain.lats[0] - dlat / 2,
            terrain.lons[-1] + dlon / 2, terrain.lats[-1] + dlat / 2,
        )
        with rasterio.open(WORLDCOVER_URL) as src:
            win = from_bounds(*bounds, transform=src.transform)
            classes = src.read(
                1, window=win, out_shape=(terrain.ny, terrain.nx),
                resampling=Resampling.mode,
            )
    except Exception as err:  # noqa: BLE001 - degrade to uniform roughness
        print(f"  ! WorldCover fetch failed ({err}); using uniform z0={Z0_DEFAULT}")
        return None

    z0 = np.full(classes.shape, Z0_DEFAULT)
    for cls, val in Z0_BY_CLASS.items():
        z0[classes == cls] = val
    z0 = z0[::-1]  # raster rows run north->south; model grid runs south->north
    np.savez_compressed(cache, z0=z0)
    return z0
