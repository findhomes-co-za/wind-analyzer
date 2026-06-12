"""Sub-grid wind shelter from high-resolution terrain (pocket finder).

The flow solver runs at 75 m, but the open DEMs carry real information at
~30 m. For every ~25 m pixel we compute the Winstral Sx shelter parameter:
the maximum upwind horizon angle to terrain within a fetch of ~1.2 km,
averaged over a small azimuth spread. Pixels behind ridge toes, in gully
mouths or under bluffs see a high upwind horizon -> sheltered pocket;
convex crests see negative angles -> locally exposed.

The resulting factor is normalised by its smoothed (75 m scale) mean, so it
only redistributes wind WITHIN coarse cells — the mesoscale pattern stays
with the solver. Source DEM: Copernicus GLO-30 (AWS Open Data), with the
terrarium tiles as fallback.

Below ~30 m the open data runs out: garden-scale shelter (hedges, walls,
single houses) would need LiDAR plus building-resolved CFD.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

from .terrain import EARTH_M_PER_DEG, TerrainGrid

GLO30_URL = (
    "https://copernicus-dem-30m.s3.amazonaws.com/"
    "Copernicus_DSM_COG_10_{lat}_00_E018_00_DEM/"
    "Copernicus_DSM_COG_10_{lat}_00_E018_00_DEM.tif"
)


def fetch_micro_dem(lon_min: float, lon_max: float, lat_min: float, lat_max: float,
                    res_m: float = 25.0, cache_dir: str | Path = "data/cache") -> TerrainGrid:
    """Copernicus GLO-30 elevations on a uniform ~25 m grid."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(f"glo30_{lon_min}_{lon_max}_{lat_min}_{lat_max}_{res_m}".encode()).hexdigest()[:12]
    cache = cache_dir / f"micro_dem_{key}.npz"
    if cache.exists():
        d = np.load(cache)
        return TerrainGrid(d["zs"], d["lats"], d["lons"], float(d["dx"]), float(d["dy"]))

    import rasterio
    from rasterio.enums import Resampling
    from rasterio.windows import from_bounds

    lat_mid = 0.5 * (lat_min + lat_max)
    dlat = res_m / EARTH_M_PER_DEG
    dlon = res_m / (EARTH_M_PER_DEG * math.cos(math.radians(lat_mid)))
    ny = int(round((lat_max - lat_min) / dlat))
    nx = int(round((lon_max - lon_min) / dlon))
    lats = lat_min + (np.arange(ny) + 0.5) * dlat
    lons = lon_min + (np.arange(nx) + 0.5) * dlon

    zs = np.zeros((ny, nx))
    # GLO-30 1-degree tiles: S34 covers [-34, -33), S35 covers [-35, -34).
    for tile_lat0, tile_name in ((-34.0, "S34"), (-35.0, "S35")):
        sel = (lats >= tile_lat0) & (lats < tile_lat0 + 1.0)
        if not sel.any():
            continue
        rows = np.where(sel)[0]
        lo_lat = lats[rows[0]] - dlat / 2
        hi_lat = lats[rows[-1]] + dlat / 2
        with rasterio.open(GLO30_URL.format(lat=tile_name)) as src:
            win = from_bounds(lon_min, lo_lat, lon_max, hi_lat, transform=src.transform)
            part = src.read(1, window=win, out_shape=(len(rows), nx),
                            resampling=Resampling.bilinear)
        zs[rows] = part[::-1]  # raster rows run north->south; ours south->north

    zs = np.clip(zs, 0.0, None)
    np.savez_compressed(cache, zs=zs, lats=lats, lons=lons, dx=res_m, dy=res_m)
    return TerrainGrid(zs, lats, lons, res_m, res_m)


def shelter_factor(t: TerrainGrid, direction_deg: float,
                   fetch: float = 1200.0, azimuths=(-15.0, 0.0, 15.0),
                   coarse_dx: float = 75.0) -> np.ndarray:
    """Sub-grid wind factor (~0.35 sheltered pocket .. ~1.3 exposed crest).

    Winstral Sx: max upwind horizon angle within `fetch`, averaged over the
    azimuth spread, mapped to a speed factor and normalised at coarse_dx so
    the coarse-cell mean stays ~1 (the solver owns the mesoscale pattern).
    """
    zs, dx, dy = t.zs, t.dx, t.dy
    ny, nx = zs.shape
    jj, ii = np.mgrid[0:ny, 0:nx].astype(np.float32)
    step = max(dx, dy) * 1.2
    dists = np.arange(step, fetch + 0.1, step)

    sx_sum = np.zeros((ny, nx), dtype=np.float32)
    for az in azimuths:
        th = math.radians(direction_deg + az)
        ux, uy = math.sin(th), math.cos(th)  # unit vector pointing upwind
        best = np.full((ny, nx), -np.inf, dtype=np.float32)
        for s in dists:
            rows = jj + (uy * s) / dy
            cols = ii + (ux * s) / dx
            z_up = map_coordinates(zs, [rows, cols], order=1, mode="nearest")
            np.maximum(best, (z_up - zs) / s, out=best)
        sx_sum += np.degrees(np.arctan(best))
    sx = sx_sum / len(azimuths)

    raw = np.clip(1.0 - 0.045 * sx, 0.3, 1.15)
    # Remove the coarse-scale mean: only sub-75 m texture survives.
    norm = gaussian_filter(raw, sigma=coarse_dx / max(dx, dy))
    return np.clip(raw / np.maximum(norm, 0.2), 0.35, 1.3)
