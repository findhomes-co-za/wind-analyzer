"""Download and grid real elevation data for the model domain.

Source: Mapzen/Amazon "terrarium" terrain tiles on AWS Open Data
(https://registry.opendata.aws/terrain-tiles/), derived from SRTM and other
open DEMs. Public, no API key. Elevation is encoded in the RGB channels:
    elevation_m = (R * 256 + G + B / 256) - 32768
"""

from __future__ import annotations

import hashlib
import io
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from scipy.ndimage import gaussian_filter, map_coordinates

from .config import Domain

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
TILE_SIZE = 256
EARTH_M_PER_DEG = 111_320.0


@dataclass
class TerrainGrid:
    zs: np.ndarray      # (ny, nx) elevation m ASL, ocean clipped to 0
    lats: np.ndarray    # (ny,) cell-centre latitudes, ascending (south -> north)
    lons: np.ndarray    # (nx,) cell-centre longitudes, ascending (west -> east)
    dx: float           # grid spacing (m), same in x and y
    dy: float

    @property
    def ny(self) -> int:
        return self.zs.shape[0]

    @property
    def nx(self) -> int:
        return self.zs.shape[1]

    def lonlat_to_ij(self, lon: float, lat: float) -> tuple[float, float]:
        """Fractional (j, i) grid indices of a lon/lat point."""
        i = (lon - self.lons[0]) / (self.lons[1] - self.lons[0])
        j = (lat - self.lats[0]) / (self.lats[1] - self.lats[0])
        return j, i

    def x_km(self) -> np.ndarray:
        return np.arange(self.nx) * self.dx / 1000.0

    def y_km(self) -> np.ndarray:
        return np.arange(self.ny) * self.dy / 1000.0


def _lonlat_to_global_px(lon: np.ndarray, lat: np.ndarray, zoom: int):
    """Web-Mercator global pixel coordinates at the given zoom."""
    n = TILE_SIZE * (2 ** zoom)
    px = (lon + 180.0) / 360.0 * n
    lat_r = np.radians(lat)
    py = (1.0 - np.arcsinh(np.tan(lat_r)) / math.pi) / 2.0 * n
    return px, py


def _fetch_tile(z: int, x: int, y: int, cache_dir: Path, retries: int = 3) -> np.ndarray:
    cache = cache_dir / f"terrarium_{z}_{x}_{y}.png"
    if cache.exists():
        raw = cache.read_bytes()
    else:
        url = TILE_URL.format(z=z, x=x, y=y)
        last_err: Exception | None = None
        for attempt in range(retries):
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                raw = resp.content
                cache.write_bytes(raw)
                break
            except Exception as err:  # noqa: BLE001 - retry then re-raise
                last_err = err
                time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"failed to download terrain tile {url}: {last_err}")
    img = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"), dtype=np.float64)
    return img[:, :, 0] * 256.0 + img[:, :, 1] + img[:, :, 2] / 256.0 - 32768.0


def fetch_dem(domain: Domain, zoom: int = 12, cache_dir: str | Path = "data/cache") -> TerrainGrid:
    """Build a uniform model grid of elevations for the domain."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    key = hashlib.md5(
        f"{domain.lon_min}_{domain.lon_max}_{domain.lat_min}_{domain.lat_max}_"
        f"{domain.resolution_m}_{zoom}".encode()
    ).hexdigest()[:12]
    grid_cache = cache_dir / f"dem_grid_{key}.npz"
    if grid_cache.exists():
        d = np.load(grid_cache)
        return TerrainGrid(d["zs"], d["lats"], d["lons"], float(d["dx"]), float(d["dy"]))

    # Target model grid (cell centres), uniform in metres via local equirectangular scaling.
    res = domain.resolution_m
    dlat = res / EARTH_M_PER_DEG
    dlon = res / (EARTH_M_PER_DEG * math.cos(math.radians(domain.lat_mid)))
    ny = int(round((domain.lat_max - domain.lat_min) / dlat))
    nx = int(round((domain.lon_max - domain.lon_min) / dlon))
    lats = domain.lat_min + (np.arange(ny) + 0.5) * dlat
    lons = domain.lon_min + (np.arange(nx) + 0.5) * dlon

    # Mosaic of the tiles covering the bounding box.
    px_min, py_max = _lonlat_to_global_px(np.array(domain.lon_min), np.array(domain.lat_min), zoom)
    px_max, py_min = _lonlat_to_global_px(np.array(domain.lon_max), np.array(domain.lat_max), zoom)
    tx0, tx1 = int(px_min // TILE_SIZE), int(px_max // TILE_SIZE)
    ty0, ty1 = int(py_min // TILE_SIZE), int(py_max // TILE_SIZE)

    mosaic = np.zeros(((ty1 - ty0 + 1) * TILE_SIZE, (tx1 - tx0 + 1) * TILE_SIZE))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            tile = _fetch_tile(zoom, tx, ty, cache_dir)
            r0, c0 = (ty - ty0) * TILE_SIZE, (tx - tx0) * TILE_SIZE
            mosaic[r0:r0 + TILE_SIZE, c0:c0 + TILE_SIZE] = tile

    # Bilinear sample the mosaic at every model grid point.
    lon2d, lat2d = np.meshgrid(lons, lats)
    px, py = _lonlat_to_global_px(lon2d, lat2d, zoom)
    rows = py - ty0 * TILE_SIZE
    cols = px - tx0 * TILE_SIZE
    zs = map_coordinates(mosaic, [rows, cols], order=1, mode="nearest")

    zs = np.clip(zs, 0.0, None)             # bathymetry -> sea level
    zs = gaussian_filter(zs, sigma=0.8)     # mild smoothing at model resolution

    np.savez_compressed(grid_cache, zs=zs, lats=lats, lons=lons, dx=res, dy=res)
    return TerrainGrid(zs, lats, lons, res, res)
