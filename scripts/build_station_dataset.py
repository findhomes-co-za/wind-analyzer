"""Fetch hourly history for every harvested PWS, QC it, and store a clean set.

Reads data/cache/pws_registry.json (from harvest_stations.py), pulls hourly
wind history for the south-easter season, and keeps only stations that carry a
USABLE wind signal:

  * enough hourly coverage in the window,
  * a live anemometer (peak >= MIN_PEAK m/s and non-constant — many PWS are
    dead or stuck at 0), and
  * we separately record whether the station also reports wind DIRECTION
    (some report speed only, or only at calm hours where direction is null).

Each kept station stores an hourly series {hour_utc -> [dir_deg|null, speed_ms]}
where speed is the mean and direction the CIRCULAR mean of the sub-hourly obs.

Output: data/cache/pws_clean.json  (passed stations + a rejected log w/ reasons)

Day history is cached per (station, day), so the network fetch is resumable and
parallel: a bounded worker pool prefetches uncached days through a GLOBAL rate
limiter (caps aggregate requests/sec no matter the worker count), with jitter,
exponential backoff on 429/5xx, and an abort if the endpoint starts returning
401/403 (key blocked) — i.e. parallel but deliberately polite to the endpoint.

Usage:  .venv/bin/python scripts/build_station_dataset.py --start 20241210 --end 20251209 --kept-only
"""

from __future__ import annotations

import argparse
import json
import math
import random
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests

KEY = "e1f10a1e78da46f5b10a1e78da96f525"
HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0",
           "Referer": "https://www.wunderground.com/", "Origin": "https://www.wunderground.com"}
HIST_URL = "https://api.weather.com/v2/pws/history/hourly"
CACHE = Path("data/cache/pws")
REGISTRY = Path("data/cache/pws_registry.json")
CLEAN = Path("data/cache/pws_clean.json")

RETRYABLE = {429, 500, 502, 503, 504}   # transient — back off and retry
EMPTY_OK = {204, 404}                    # no data for that day — cache empty, don't retry
BLOCKED = {401, 403}                     # key blocked / forbidden — abort the whole run

MIN_PEAK = 4.0          # m/s; below this the sensor is dead or deeply sheltered/broken
MIN_DIR_HOURS = 40      # need at least this many direction readings to validate bearings


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


def _next_day(d):
    y, m, dd = d // 10000, (d // 100) % 100, d % 100
    dim = [31, 29 if y % 4 == 0 else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    dd += 1
    if dd > dim:
        dd, m = 1, m + 1
    if m > 12:
        m, y = 1, y + 1
    return y * 10000 + m * 100 + dd


def _circ_mean(degs):
    r = np.radians(degs)
    return float((math.degrees(math.atan2(np.mean(np.sin(r)), np.mean(np.cos(r)))) + 360.0) % 360.0)


class RateLimiter:
    """Global token spacing: ensures request STARTS are >= 1/rate apart across
    all worker threads, so concurrency never raises the aggregate request rate
    above `rate` per second (plus a little jitter)."""

    def __init__(self, rate):
        self.min_interval = 1.0 / rate
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self):
        with self.lock:
            now = time.monotonic()
            t = max(now, self.next_t)
            self.next_t = t + self.min_interval
        delay = t - time.monotonic()
        if delay > 0:
            time.sleep(delay + random.uniform(0, 0.03))


def _hist_params(sid, ds):
    return {"stationId": sid, "format": "json", "units": "m", "startDate": ds,
            "endDate": ds, "numericPrecision": "decimal", "apiKey": KEY}


def prefetch_day(sid, ds, limiter, abort, counters):
    """Ensure the (station, day) history file is cached. Polite + resilient."""
    cf = CACHE / f"hist_{sid}_{ds}.json"
    if cf.exists():
        return
    for attempt in range(6):
        if abort.is_set():
            return
        limiter.wait()
        try:
            r = requests.get(HIST_URL, params=_hist_params(sid, ds), headers=HEADERS, timeout=60)
        except Exception:                       # network blip — back off and retry
            time.sleep(min(30.0, 2 ** attempt) + random.uniform(0, 1))
            continue
        if r.status_code == 200:
            cf.write_text(r.text)
            with counters["lock"]:
                counters["ok"] += 1
            return
        if r.status_code in EMPTY_OK:
            cf.write_text(json.dumps({"observations": []}))
            return
        if r.status_code in BLOCKED:
            with counters["lock"]:
                counters["blocked"] += 1
                if counters["blocked"] >= 5:    # the key is clearly cut off — stop hammering
                    abort.set()
            return
        if r.status_code in RETRYABLE:
            time.sleep(min(30.0, 2 ** attempt) + random.uniform(0, 1))
            continue
        return                                   # other 4xx: skip this day
    with counters["lock"]:
        counters["failed"] += 1


def prefetch_all(stations, days, workers, rate):
    """Parallel, rate-limited prefetch of every uncached (station, day)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    tasks = [(s["id"], ds) for s in stations for ds in days
             if not (CACHE / f"hist_{s['id']}_{ds}.json").exists()]
    total = len(tasks)
    print(f"Prefetch: {len(stations)} stations x {len(days)} days = "
          f"{len(stations) * len(days)} day-files; {total} uncached to fetch "
          f"({workers} workers, <= {rate:.1f} req/s)", flush=True)
    if not total:
        return
    limiter = RateLimiter(rate)
    abort = threading.Event()
    counters = {"ok": 0, "failed": 0, "blocked": 0, "lock": threading.Lock()}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(prefetch_day, sid, ds, limiter, abort, counters) for sid, ds in tasks]
        for f in futs:
            f.result()
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{total} fetched (ok={counters['ok']}, "
                      f"failed={counters['failed']})", flush=True)
    if abort.is_set():
        print("  ABORTED: endpoint returned repeated 401/403 — key likely blocked. "
              "Cached progress is kept; re-run later to resume.", flush=True)
    print(f"Prefetch done: ok={counters['ok']}, failed={counters['failed']}, "
          f"blocked={counters['blocked']}", flush=True)


def fetch_hourly(station_id, start, end):
    """{hour 'YYYY-MM-DDTHH' -> [dir_deg|None, speed_ms]} ; circular-mean direction."""
    speeds = defaultdict(list)
    dirs = defaultdict(list)
    live = 0
    d = start
    while d <= end:
        ds = f"{d:08d}"
        try:
            j, cached = _get("https://api.weather.com/v2/pws/history/hourly",
                             {"stationId": station_id, "format": "json", "units": "m",
                              "startDate": ds, "endDate": ds, "numericPrecision": "decimal",
                              "apiKey": KEY}, f"hist_{station_id}_{ds}.json")
            if not cached:
                live += 1
                time.sleep(0.12)
            for o in (j.get("observations") or []):
                m = o.get("metric") or {}
                spd = m.get("windspeedAvg", m.get("windSpeed"))
                direc = o.get("winddirAvg", o.get("winddir"))
                t = o.get("obsTimeUtc", "")
                if spd is None or len(t) < 13:
                    continue
                key = t[:13]
                speeds[key].append(float(spd) / 3.6)
                # direction is only meaningful when the vane is actually moving
                if direc is not None and float(spd) > 0.5:
                    dirs[key].append(float(direc))
        except Exception:  # noqa: BLE001
            pass
        d = _next_day(d)
    series = {}
    for key, sp in speeds.items():
        dd = _circ_mean(dirs[key]) if dirs.get(key) else None
        series[key] = [dd, float(np.mean(sp))]
    return series, live


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=20241210)
    p.add_argument("--end", type=int, default=20250115)
    p.add_argument("--limit", type=int, default=0, help="only process first N stations (smoke test)")
    p.add_argument("--kept-only", action="store_true",
                   help="only (re)fetch stations already kept in pws_clean.json")
    p.add_argument("--workers", type=int, default=5, help="parallel fetch workers")
    p.add_argument("--rate", type=float, default=5.0, help="max aggregate requests/sec")
    # Fixed coverage floor (NOT a fraction of the window): extending to a full
    # year must not drop summer-only stations that have plenty of summer hours.
    p.add_argument("--min-hours", type=int, default=150)
    args = p.parse_args()

    days, d = [], args.start
    while d <= args.end:
        days.append(f"{d:08d}")
        d = _next_day(d)
    min_hours = args.min_hours

    reg = json.loads(REGISTRY.read_text())["stations"]
    if args.kept_only and CLEAN.exists():
        keep_ids = {r["id"] for r in json.loads(CLEAN.read_text()).get("kept", [])}
        reg = [s for s in reg if s["id"] in keep_ids]
    if args.limit:
        reg = reg[:args.limit]
    print(f"Window {args.start}..{args.end} ({len(days)} d), min coverage {min_hours} hrs, "
          f"{len(reg)} stations")

    prefetch_all(reg, days, args.workers, args.rate)

    kept, rejected = [], []
    for i, st in enumerate(reg):
        series, _ = fetch_hourly(st["id"], args.start, args.end)   # cache reads now
        n = len(series)
        speeds = [v[1] for v in series.values()]
        n_dir = sum(1 for v in series.values() if v[0] is not None)
        peak = max(speeds, default=0.0)
        std = float(np.std(speeds)) if speeds else 0.0

        reasons = []
        if n < min_hours:
            reasons.append(f"coverage {n}<{min_hours}")
        if peak < MIN_PEAK:
            reasons.append(f"peak {peak:.1f}<{MIN_PEAK} (dead/sheltered)")
        if std < 0.1:
            reasons.append("constant (stuck sensor)")
        rec = {"id": st["id"], "name": st["name"], "lat": st["lat"], "lon": st["lon"],
               "dist_km": st["dist_km"], "n_hours": n, "n_dir_hours": n_dir,
               "peak_ms": round(peak, 1), "std_ms": round(std, 2),
               "has_dir": n_dir >= MIN_DIR_HOURS}
        if reasons:
            rec["reasons"] = reasons
            rejected.append(rec)
        else:
            rec["series"] = series
            kept.append(rec)
        flag = "OK " if not reasons else "rej"
        dirf = "dir" if rec["has_dir"] else "   "
        print(f"  [{i+1:>2}/{len(reg)}] {st['id']:<10} {flag} {dirf} "
              f"n={n:>3} peak={peak:>4.1f} {'; '.join(reasons)}")

    CLEAN.write_text(json.dumps({
        "window": [args.start, args.end], "min_hours": min_hours, "min_peak": MIN_PEAK,
        "n_kept": len(kept), "n_rejected": len(rejected),
        "n_with_dir": sum(1 for r in kept if r["has_dir"]),
        "kept": kept, "rejected": rejected}, indent=2))
    print(f"\nKept {len(kept)} "
          f"({sum(1 for r in kept if r['has_dir'])} with usable direction), "
          f"rejected {len(rejected)} -> {CLEAN}")


if __name__ == "__main__":
    main()
