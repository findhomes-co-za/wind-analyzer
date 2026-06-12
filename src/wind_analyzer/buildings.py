"""Tall buildings from OpenStreetMap (Overpass API).

Buildings far larger than the 75 m grid cell can't be resolved by the flow
solver, so they enter as local diagnostics: dense tall fabric slows the mean
street wind (urban canyon), while tall towers bring roof-height momentum down
to street level (downwash) — raising gusts and turbulence in their cells.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import requests

from .terrain import TerrainGrid

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MIN_HEIGHT_M = 25.0
LEVEL_HEIGHT_M = 3.2


def _parse_height(tags: dict) -> float | None:
    h = None
    if "height" in tags:
        m = re.match(r"\s*([\d.]+)", str(tags["height"]))
        if m:
            h = float(m.group(1))
    if h is None and "building:levels" in tags:
        m = re.match(r"\s*([\d.]+)", str(tags["building:levels"]))
        if m:
            h = float(m.group(1)) * LEVEL_HEIGHT_M + 3.0
    return h


def fetch_tall_buildings(bbox: tuple[float, float, float, float],
                         cache_dir: str | Path = "data/cache") -> list[dict]:
    """Buildings >= MIN_HEIGHT_M in (lat_min, lon_min, lat_max, lon_max)."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"buildings_{'_'.join(f'{v:.3f}' for v in bbox)}.json"
    if cache.exists():
        return json.loads(cache.read_text())

    s, w, n, e = bbox
    query = f"""
    [out:json][timeout:120];
    (
      way["building"]["height"]({s},{w},{n},{e});
      way["building"]["building:levels"]({s},{w},{n},{e});
      relation["building"]["height"]({s},{w},{n},{e});
    );
    out center tags;
    """
    headers = {"User-Agent": "wind-analyzer/0.1 (terrain wind research; contact: local)"}
    elements = None
    for url in (OVERPASS_URL, "https://overpass.kumi.systems/api/interpreter"):
        try:
            resp = requests.post(url, data={"data": query}, headers=headers, timeout=180)
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            break
        except Exception as err:  # noqa: BLE001 - buildings are an optional enhancement
            print(f"  ! Overpass fetch failed at {url} ({err})")
    if elements is None:
        print("  ! continuing without buildings")
        return []

    out = []
    for el in elements:
        tags = el.get("tags", {})
        h = _parse_height(tags)
        centre = el.get("center") or {}
        if h is None or h < MIN_HEIGHT_M or "lat" not in centre:
            continue
        out.append({
            "lat": centre["lat"], "lon": centre["lon"], "height_m": round(h, 1),
            "name": tags.get("name", ""),
        })
    cache.write_text(json.dumps(out))
    return out


def rasterize_heights(terrain: TerrainGrid, buildings: list[dict]) -> np.ndarray | None:
    """Per-cell max building height (m); None when no buildings are known."""
    if not buildings:
        return None
    h = np.zeros((terrain.ny, terrain.nx))
    for b in buildings:
        j, i = terrain.lonlat_to_ij(b["lon"], b["lat"])
        j, i = int(round(j)), int(round(i))
        if 0 <= j < terrain.ny and 0 <= i < terrain.nx:
            # cap guards against OSM mis-tags (nothing in Cape Town tops ~140 m)
            h[j, i] = max(h[j, i], min(b["height_m"], 160.0))
    return h if h.max() > 0 else None
