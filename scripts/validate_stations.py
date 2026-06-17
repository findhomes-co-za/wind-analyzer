"""Validate the modelled wind pattern against Weather Underground PWS data.

Reanalysis (ERA5) can't resolve the intra-city contrast — Clifton, the City
Bowl and the CBD all fall in one ~25 km cell. Personal weather stations can.
This script:

  1. finds a working PWS near each target suburb,
  2. pulls hourly history for the south-easter season,
  3. classifies SE vs SSE event hours from the regional (ERA5) wind direction,
  4. for those hours computes each station's mean wind normalised by an
     exposed reference station -> an OBSERVED speed-up ratio, per sub-sector,
  5. compares it to the MODEL's speed-up ratio at the same suburb.

PWS are heterogeneous (mounting, obstructions, calibration), so individual
numbers are noisy; the spatial PATTERN across stations during SE events is the
signal, and the SE-vs-SSE contrast at a station is the cleanest test (it
cancels that station's own bias). Results are cached so re-runs are free.

Usage:  .venv/bin/python scripts/validate_stations.py --start 20241201 --end 20250228
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
import requests

KEY = "e1f10a1e78da46f5b10a1e78da96f525"
HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0",
           "Referer": "https://www.wunderground.com/", "Origin": "https://www.wunderground.com"}
CACHE = Path("data/cache/pws")
CITY = (-33.94, 18.42)            # for ERA5 regional direction
SE_RANGE = (105.0, 147.0)
SSE_RANGE = (147.0, 172.0)
MIN_EVENT_SPEED = 5.0             # m/s (ERA5 regional) to ensure a real event

TARGETS = {
    "Clifton": (-33.9365, 18.3776), "Camps Bay": (-33.9508, 18.3776),
    "Bakoven": (-33.9609, 18.3741), "Bantry Bay": (-33.9282, 18.3759),
    "Sea Point": (-33.9170, 18.3870), "Vredehoek": (-33.9405, 18.4225),
    "Oranjezicht": (-33.9419, 18.4119), "Gardens": (-33.9347, 18.4117),
    "Tamboerskloof": (-33.9332, 18.4006), "Hout Bay": (-34.0479, 18.3565),
    "Constantia": (-34.0260, 18.4210), "Muizenberg": (-34.1050, 18.4690),
    "Bloubergstrand": (-33.8000, 18.4600), "Milnerton": (-33.8850, 18.4850),
}
# Hand-picked stations to try first (known-good IDs near these suburbs).
PREFERRED = {
    "Clifton": ["ICAPET147"],
    "Gardens": ["ICAPET193"],
    "Tamboerskloof": ["ICAPET193"],
    "Vredehoek": ["ICAPET156"],
    "Oranjezicht": ["ICAPET185", "ICAPET156"],
}
REFERENCE = "Bloubergstrand"      # open coast, well exposed to the SE


def _get(url, params, cache_name):
    CACHE.mkdir(parents=True, exist_ok=True)
    cf = CACHE / cache_name
    if cf.exists():
        return json.loads(cf.read_text())
    r = requests.get(url, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    cf.write_text(json.dumps(j))
    return j


def near_candidates(lat, lon):
    j = _get("https://api.weather.com/v3/location/near",
             {"geocode": f"{lat},{lon}", "product": "pws", "format": "json", "apiKey": KEY},
             f"near_{lat:.4f}_{lon:.4f}.json")
    loc = j.get("location", {})
    return list(zip(loc.get("stationId", []), loc.get("distanceKm", [])))


def _next_day(d):
    y, m, dd = d // 10000, (d // 100) % 100, d % 100
    dim = [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    dd += 1
    if dd > dim:
        dd, m = 1, m + 1
    if m > 12:
        m, y = 1, y + 1
    return y * 10000 + m * 100 + dd


def fetch_hourly(station_id, start, end):
    """{hour_key 'YYYY-MM-DDTHH' -> (mean_dir, mean_speed_ms)} for a station."""
    by_hour = defaultdict(list)
    d = start
    while d <= end:
        ds = f"{d:08d}"
        try:
            j = _get("https://api.weather.com/v2/pws/history/hourly",
                     {"stationId": station_id, "format": "json", "units": "m",
                      "startDate": ds, "endDate": ds, "numericPrecision": "decimal",
                      "apiKey": KEY}, f"hist_{station_id}_{ds}.json")
            for o in (j.get("observations") or []):
                m = o.get("metric") or {}
                spd = m.get("windspeedAvg", m.get("windSpeed"))
                direc = o.get("winddirAvg", o.get("winddir"))
                t = o.get("obsTimeUtc", "")
                if spd is not None and direc is not None and len(t) >= 13:
                    by_hour[t[:13]].append((float(direc), float(spd) / 3.6))
        except Exception as err:  # noqa: BLE001
            pass
        d = _next_day(d)
    return {k: (float(np.mean([d for d, _ in v])), float(np.mean([s for _, s in v])))
            for k, v in by_hour.items()}


def pick_station(name, lat, lon, start, end, min_hours):
    """First PWS with decent coverage: hand-picked IDs first, then nearest."""
    near = near_candidates(lat, lon)
    dist_of = {sid: d for sid, d in near}
    ordered = [(sid, dist_of.get(sid, 0.0)) for sid in PREFERRED.get(name, [])]
    ordered += [(sid, d) for sid, d in near[:6] if d <= 2.5]
    seen = set()
    for sid, dist in ordered:
        if sid in seen:
            continue
        seen.add(sid)
        series = fetch_hourly(sid, start, end)
        if len(series) >= min_hours:
            return sid, dist, series
    return None, None, {}


def era5_events(start, end):
    """{hour_key -> 'SE'|'SSE'} regional event hours from ERA5."""
    s = f"{start // 10000}-{(start // 100) % 100:02d}-{start % 100:02d}"
    e = f"{end // 10000}-{(end // 100) % 100:02d}-{end % 100:02d}"
    j = _get("https://archive-api.open-meteo.com/v1/archive",
             {"latitude": CITY[0], "longitude": CITY[1], "start_date": s, "end_date": e,
              "hourly": "wind_speed_10m,wind_direction_10m", "wind_speed_unit": "ms",
              "timezone": "UTC"}, f"era5_{start}_{end}.json")
    h = j["hourly"]
    ev = {}
    for t, sp, di in zip(h["time"], h["wind_speed_10m"], h["wind_direction_10m"]):
        if sp is None or di is None or sp < MIN_EVENT_SPEED:
            continue
        key = t[:13]
        if SE_RANGE[0] <= di < SE_RANGE[1]:
            ev[key] = "SE"
        elif SSE_RANGE[0] <= di < SSE_RANGE[1]:
            ev[key] = "SSE"
    return ev


def model_speedups():
    out = {}
    for tag, fn in (("SE", "run_06_strong.json"), ("SSE", "run_07_strong.json")):
        r = json.loads(Path(f"web/data/{fn}").read_text())
        out[tag] = {x["suburb"]: x["speedup"] for x in r["ranking"]}
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=20241210)
    p.add_argument("--end", type=int, default=20250115)
    args = p.parse_args()
    win_days = 0
    d = args.start
    while d <= args.end:
        win_days += 1; d = _next_day(d)
    min_hours = max(60, int(win_days * 24 * 0.20))   # >=20% hourly coverage

    events = era5_events(args.start, args.end)
    n_se = sum(v == "SE" for v in events.values())
    n_sse = sum(v == "SSE" for v in events.values())
    print(f"ERA5 regional events {args.start}..{args.end}: {n_se} SE hours, {n_sse} SSE hours\n")

    print("Picking a working PWS near each suburb ...")
    stations = {}
    for name, (lat, lon) in TARGETS.items():
        sid, dist, series = pick_station(name, lat, lon, args.start, args.end, min_hours)
        if sid:
            stations[name] = {"id": sid, "dist": dist, "series": series}
            print(f"  {name:14s} -> {sid} ({dist:.1f} km, {len(series)} hrs)")
        else:
            print(f"  {name:14s} -> none with coverage")

    # PWS readings are dominated by each station's siting (mount height,
    # walls, gardens), so cross-station ABSOLUTE comparison is unreliable and
    # a single reference station can be dead (IBLOUBER6 peaks at 3.4 m/s all
    # season). The siting-robust signal is RESPONSIVENESS: a station's mean
    # wind during SE/SSE event hours divided by its own non-event baseline.
    # > 1 means that wind reaches the spot; < 1 means it is sheltered from it.
    def responsiveness(series, sector):
        ev_v = [series[k][1] for k in series if events.get(k) == sector]
        base = [series[k][1] for k in series if k not in events]
        if not ev_v or not base or np.mean(base) < 0.2:
            return None
        return float(np.mean(ev_v)) / float(np.mean(base))

    model = model_speedups()
    print("\nSiting-robust validation: RESPONSIVENESS = mean wind in that sector")
    print("/ the station's own non-event baseline.  >1 reached, <1 sheltered.\n")
    hdr = (f"{'suburb':<14} {'base m/s':>8} {'SE resp':>7} {'SSE resp':>8} | "
           f"{'mod SE':>6} {'mod SSE':>7}  read")
    print(hdr); print("-" * len(hdr))
    rows_out = []
    for name in TARGETS:
        if name not in stations:
            continue
        s = stations[name]["series"]
        base = np.mean([s[k][1] for k in s if k not in events]) if s else 0.0
        re_se, re_sse = responsiveness(s, "SE"), responsiveness(s, "SSE")
        if re_se is None or re_sse is None:
            continue
        peak = max((v[1] for v in s.values()), default=0.0)
        read = "low?" if peak < 4.0 else ""    # flag likely dead/sheltered sensors
        mse = model["SE"].get(name, float("nan"))
        msse = model["SSE"].get(name, float("nan"))
        print(f"{name:<14} {base:>8.1f} {re_se:>7.2f} {re_sse:>8.2f} | "
              f"{mse:>6.2f} {msse:>7.2f}  {read}")
        rows_out.append({"suburb": name, "station": stations[name]["id"],
                         "baseline_ms": round(float(base), 2), "peak_ms": round(peak, 1),
                         "obs_se_resp": round(re_se, 3), "obs_sse_resp": round(re_sse, 3),
                         "model_se_speedup": round(mse, 3), "model_sse_speedup": round(msse, 3)})

    Path("output").mkdir(exist_ok=True)
    Path("output/station_validation.json").write_text(json.dumps(
        {"window": [args.start, args.end], "n_se_hours": n_se, "n_sse_hours": n_sse,
         "metric": "responsiveness = sector mean / non-event baseline (per station)",
         "rows": rows_out}, indent=2))
    print("\nWritten output/station_validation.json")
    print("Read each suburb's SE vs SSE column: the SE-vs-SSE jump is the cleanest")
    print("signal (cancels that station's siting bias).")


if __name__ == "__main__":
    main()
