"""Per-station, per-direction observed wind aggregates for the web explorer.

For every QC'd PWS and every one of the 16 wind-rose directions, aggregate the
station's OBSERVED wind over the hours when the False Bay INPUT (the model's
forcing point) blew from that direction, and pair it with the MODEL's predicted
wind at that station — so the map can show, per selected direction, how closely
each station matches the simulation.

Reads:  data/cache/pws_clean.json, web/data/run_*_strong.json, web/data/static.json
Writes: web/data/stations.json
        { window, min_hours, stations: [ {id,name,lat,lon, by_dir: {
            LABEL: {n, obs_dir, obs_speed, model_dir, model_speedup,
                    model_speed, dir_err} } } ] }

Usage:  .venv/bin/python scripts/precompute_stations_web.py
"""

from __future__ import annotations

import argparse
import base64
import json
import math
from pathlib import Path

import numpy as np
import requests
from scipy.ndimage import map_coordinates

KEY = "e1f10a1e78da46f5b10a1e78da96f525"
HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0",
           "Referer": "https://www.wunderground.com/", "Origin": "https://www.wunderground.com"}
CACHE = Path("data/cache/pws")
CLEAN = Path("data/cache/pws_clean.json")
WEBDATA = Path("web/data")
OUT = WEBDATA / "stations.json"

FALSE_BAY = (-34.20, 18.65)
MIN_INPUT_SPEED = 4.0    # m/s at the forcing point — a real wind from that quarter
MIN_HOURS = 6            # per direction, else that station has no marker there
LABELS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
          "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def _decode(field, shape):
    raw = np.frombuffer(base64.b64decode(field["b64"]), dtype=np.uint8).astype(float)
    return (raw / 255.0 * (field["max"] - field["min"]) + field["min"]).reshape(shape)


class ModelField:
    """Sample one direction's detail-domain model rasters at any (lat, lon)."""

    def __init__(self, idx, bbox):
        run = json.loads((WEBDATA / f"run_{idx:02d}_strong.json").read_text())
        self.speed_in = run["meta"]["speed_10m"]
        det = run["domains"]["detail"]
        self.shape = det["shape"]
        f = det["fields"]
        self.speedup = _decode(f["speedup"], self.shape)
        self.u10 = _decode(f["u10"], self.shape)
        self.v10 = _decode(f["v10"], self.shape)
        self.lat0, self.lat1 = bbox["lat_min"], bbox["lat_max"]
        self.lon0, self.lon1 = bbox["lon_min"], bbox["lon_max"]

    def inside(self, lat, lon):
        return self.lat0 <= lat <= self.lat1 and self.lon0 <= lon <= self.lon1

    def sample(self, lat, lon):
        ny, nx = self.shape
        r = (lat - self.lat0) / (self.lat1 - self.lat0) * (ny - 1)
        c = (lon - self.lon0) / (self.lon1 - self.lon0) * (nx - 1)
        rc = [[r], [c]]
        su = float(map_coordinates(self.speedup, rc, order=1, mode="nearest")[0])
        u = float(map_coordinates(self.u10, rc, order=1, mode="nearest")[0])
        v = float(map_coordinates(self.v10, rc, order=1, mode="nearest")[0])
        frm = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0
        return su, frm


def _get(url, params, cache_name):
    cf = CACHE / cache_name
    if cf.exists():
        return json.loads(cf.read_text())
    r = requests.get(url, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    cf.write_text(json.dumps(j))
    return j


def false_bay_sectors(start, end):
    """{hour 'YYYY-MM-DDTHH' -> sector LABEL} from Open-Meteo at the forcing point."""
    s = f"{start // 10000}-{(start // 100) % 100:02d}-{start % 100:02d}"
    e = f"{end // 10000}-{(end // 100) % 100:02d}-{end % 100:02d}"
    j = _get("https://archive-api.open-meteo.com/v1/archive",
             {"latitude": FALSE_BAY[0], "longitude": FALSE_BAY[1], "start_date": s,
              "end_date": e, "hourly": "wind_speed_10m,wind_direction_10m",
              "wind_speed_unit": "ms", "timezone": "UTC"},
             f"falsebay_{start}_{end}.json")
    h = j["hourly"]
    out = {}
    for t, sp, di in zip(h["time"], h["wind_speed_10m"], h["wind_direction_10m"]):
        if sp is None or di is None or sp < MIN_INPUT_SPEED:
            continue
        out[t[:13]] = LABELS[round(di / 22.5) % 16]
    return out


def circ_mean(degs):
    r = np.radians(degs)
    return float((math.degrees(math.atan2(np.mean(np.sin(r)), np.mean(np.cos(r)))) + 360.0) % 360.0)


def circ_diff(a, b):
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=20241210)
    p.add_argument("--end", type=int, default=20250115)
    args = p.parse_args()

    bbox = json.loads((WEBDATA / "static.json").read_text())["domains"]["detail"]["bbox"]
    fields = {LABELS[i]: ModelField(i, bbox) for i in range(16)}
    sectors = false_bay_sectors(args.start, args.end)
    counts = {lab: sum(v == lab for v in sectors.values()) for lab in LABELS}
    print("False Bay input hours per direction:")
    print("  " + "  ".join(f"{lab}:{counts[lab]}" for lab in LABELS if counts[lab]))

    clean = json.loads(CLEAN.read_text())["kept"]
    out_stations = []
    for st in clean:
        if not fields["SE"].inside(st["lat"], st["lon"]):
            continue
        series = st["series"]
        by_dir = {}
        for lab in LABELS:
            hrs = [series[k] for k in series if sectors.get(k) == lab]
            if len(hrs) < MIN_HOURS:
                continue
            speeds = [v[1] for v in hrs]
            dirs = [v[0] for v in hrs if v[0] is not None]
            obs_dir = circ_mean(dirs) if len(dirs) >= 3 else None
            m_su, m_dir = fields[lab].sample(st["lat"], st["lon"])
            by_dir[lab] = {
                "n": len(hrs),
                "obs_dir": round(obs_dir, 1) if obs_dir is not None else None,
                "obs_speed": round(float(np.mean(speeds)), 2),
                "obs_speed_p90": round(float(np.percentile(speeds, 90)), 2),
                "model_dir": round(m_dir, 1),
                "model_speedup": round(m_su, 3),
                "model_speed": round(m_su * fields[lab].speed_in, 2),
                "dir_err": round(circ_diff(obs_dir, m_dir), 1) if obs_dir is not None else None,
            }
        if by_dir:
            out_stations.append({"id": st["id"], "name": st["name"], "lat": st["lat"],
                                 "lon": st["lon"], "by_dir": by_dir})

    OUT.write_text(json.dumps({"window": [args.start, args.end], "min_hours": MIN_HOURS,
                               "min_input_speed": MIN_INPUT_SPEED,
                               "stations": out_stations}, indent=2))
    covered = {lab: sum(1 for s in out_stations if lab in s["by_dir"]) for lab in LABELS}
    print(f"\n{len(out_stations)} stations -> {OUT}")
    print("Stations with a marker per direction:")
    print("  " + "  ".join(f"{lab}:{covered[lab]}" for lab in LABELS if covered[lab]))


if __name__ == "__main__":
    main()
