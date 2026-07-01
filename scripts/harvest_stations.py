"""Harvest every active Weather Underground PWS inside the model domain.

The weather.com `near` endpoint only returns the ~10 nearest stations to a
single point, so to enumerate ALL personal weather stations in the domain we
tile the query across the domain bounding box on a ~3 km grid and dedup by
station id.  The response carries each station's lat/lon (needed later to
sample the model wind field at the station) plus liveness signals
(`updateTimeUtc`, `qcStatus`).

Output: data/cache/pws_registry.json  — one entry per unique station:
    {id, name, lat, lon, dist_km, qc, update_utc}

Usage:  .venv/bin/python scripts/harvest_stations.py
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import requests

from wind_analyzer.config import Domain

KEY = "e1f10a1e78da46f5b10a1e78da96f525"
HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0",
           "Referer": "https://www.wunderground.com/", "Origin": "https://www.wunderground.com"}
CACHE = Path("data/cache/pws")
REGISTRY = Path("data/cache/pws_registry.json")

TILE_KM = 3.0  # spacing of the `near` query grid


def _get(url, params, cache_name):
    CACHE.mkdir(parents=True, exist_ok=True)
    cf = CACHE / cache_name
    if cf.exists():
        return json.loads(cf.read_text()), True
    r = requests.get(url, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    cf.write_text(json.dumps(j))
    return j, False


def near(lat, lon):
    j, cached = _get("https://api.weather.com/v3/location/near",
                     {"geocode": f"{lat:.4f},{lon:.4f}", "product": "pws",
                      "format": "json", "apiKey": KEY},
                     f"near_{lat:.4f}_{lon:.4f}.json")
    return j.get("location", {}), cached


def main():
    dom = Domain()
    # ~3 km grid spacing in degrees at this latitude.
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * abs(math.cos(math.radians(dom.lat_mid)))
    dlat = TILE_KM / km_per_deg_lat
    dlon = TILE_KM / km_per_deg_lon

    lat = dom.lat_min
    grid = []
    while lat <= dom.lat_max + 1e-9:
        lon = dom.lon_min
        while lon <= dom.lon_max + 1e-9:
            grid.append((lat, lon))
            lon += dlon
        lat += dlat
    print(f"Domain lon[{dom.lon_min},{dom.lon_max}] lat[{dom.lat_min},{dom.lat_max}] "
          f"-> {len(grid)} `near` queries on a {TILE_KM:.0f} km grid")

    stations = {}  # id -> best record (nearest distance wins)
    live_calls = 0
    for i, (qlat, qlon) in enumerate(grid):
        loc, cached = near(qlat, qlon)
        if not cached:
            live_calls += 1
            time.sleep(0.15)
        ids = loc.get("stationId", []) or []
        for k, sid in enumerate(ids):
            slat = loc["latitude"][k]
            slon = loc["longitude"][k]
            if slat is None or slon is None:
                continue
            # Keep only stations physically inside the model domain — outside it
            # there is no model field to compare against.
            if not (dom.lat_min <= slat <= dom.lat_max and dom.lon_min <= slon <= dom.lon_max):
                continue
            dist = loc.get("distanceKm", [None] * len(ids))[k]
            rec = {"id": sid, "name": loc.get("stationName", [None] * len(ids))[k],
                   "lat": slat, "lon": slon,
                   "dist_km": dist, "qc": loc.get("qcStatus", [None] * len(ids))[k],
                   "update_utc": loc.get("updateTimeUtc", [None] * len(ids))[k]}
            prev = stations.get(sid)
            if prev is None or (dist is not None and dist < (prev["dist_km"] or 1e9)):
                stations[sid] = rec

    regs = sorted(stations.values(), key=lambda r: (r["lat"], r["lon"]))
    REGISTRY.write_text(json.dumps({"domain": [dom.lon_min, dom.lon_max, dom.lat_min, dom.lat_max],
                                    "tile_km": TILE_KM, "count": len(regs),
                                    "stations": regs}, indent=2))
    print(f"{live_calls} live calls, {len(grid) - live_calls} from cache")
    print(f"Found {len(regs)} unique PWS inside the domain -> {REGISTRY}")
    # quick liveness preview
    import datetime as dt
    now = time.time()
    recent = sum(1 for r in regs if r["update_utc"] and (now - r["update_utc"]) < 86400 * 14)
    print(f"  {recent}/{len(regs)} reported within the last 14 days (by updateTimeUtc)")


if __name__ == "__main__":
    main()
