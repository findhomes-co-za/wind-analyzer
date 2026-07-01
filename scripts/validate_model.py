"""Validate the wind model against ALL QC'd PWS in the domain.

Inputs:
  * data/cache/pws_clean.json   — QC'd hourly station series (build_station_dataset.py)
  * web/data/run_06_strong.json — model SE  field (speedup + u10/v10 rasters)
  * web/data/run_07_strong.json — model SSE field
  * web/data/static.json        — detail-domain bbox (to map lat/lon -> grid)

Method:
  1. Classify SE / SSE event hours from Open-Meteo at the FALSE BAY input point
     (-34.20, 18.65) — the point that actually FORCES the model — so the test is
     "when the model was driven SE, what did the stations see?".
  2. SPEED (siting-robust): each station's responsiveness = mean wind in that
     sector / its own non-event baseline.  PWS absolute speeds are not
     comparable (siting), so we rank-correlate (Spearman) responsiveness against
     the model's speed-up sampled at the station, and check the SE->SSE contrast.
  3. DIRECTION (siting-robust): circular-mean observed bearing during event
     hours vs the model's local wind bearing sampled at the station.  Direction
     barely depends on anemometer height/siting, so this is an absolute test.

Usage:  .venv/bin/python scripts/validate_model.py --start 20241210 --end 20250115
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
from scipy.stats import spearmanr

KEY = "e1f10a1e78da46f5b10a1e78da96f525"
HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0",
           "Referer": "https://www.wunderground.com/", "Origin": "https://www.wunderground.com"}
CACHE = Path("data/cache/pws")
CLEAN = Path("data/cache/pws_clean.json")
WEBDATA = Path("web/data")

FALSE_BAY = (-34.20, 18.65)       # model forcing point (winddata.UPWIND_POINT)
SE_RANGE = (105.0, 147.0)
SSE_RANGE = (147.0, 172.0)
MIN_EVENT_SPEED = 5.0             # m/s at the forcing point -> a real event
# which web run encodes which sector (precompute_web sector index)
RUN_FILE = {"SE": "run_06_strong.json", "SSE": "run_07_strong.json"}


# ---------------------------------------------------------------- model rasters
def _decode(field, shape):
    raw = np.frombuffer(base64.b64decode(field["b64"]), dtype=np.uint8).astype(float)
    return (raw / 255.0 * (field["max"] - field["min"]) + field["min"]).reshape(shape)


class ModelField:
    """Sample the detail-domain model rasters at any (lat, lon)."""

    def __init__(self, sector):
        run = json.loads((WEBDATA / RUN_FILE[sector]).read_text())
        det = run["domains"]["detail"]
        self.shape = det["shape"]                      # [ny, nx], row 0 = south
        f = det["fields"]
        self.speedup = _decode(f["speedup"], self.shape)
        self.u10 = _decode(f["u10"], self.shape)
        self.v10 = _decode(f["v10"], self.shape)
        bb = json.loads((WEBDATA / "static.json").read_text())["domains"]["detail"]["bbox"]
        self.lat0, self.lat1 = bb["lat_min"], bb["lat_max"]
        self.lon0, self.lon1 = bb["lon_min"], bb["lon_max"]

    def _rc(self, lat, lon):
        ny, nx = self.shape
        row = (lat - self.lat0) / (self.lat1 - self.lat0) * (ny - 1)
        col = (lon - self.lon0) / (self.lon1 - self.lon0) * (nx - 1)
        return row, col

    def inside(self, lat, lon):
        return self.lat0 <= lat <= self.lat1 and self.lon0 <= lon <= self.lon1

    def sample(self, lat, lon):
        """(speedup, model_from_bearing_deg) bilinearly at the station."""
        r, c = self._rc(lat, lon)
        rc = [[r], [c]]
        su = float(map_coordinates(self.speedup, rc, order=1, mode="nearest")[0])
        u = float(map_coordinates(self.u10, rc, order=1, mode="nearest")[0])
        v = float(map_coordinates(self.v10, rc, order=1, mode="nearest")[0])
        frm = (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0  # meteorological FROM
        return su, frm


# ---------------------------------------------------------------- events
def _get(url, params, cache_name):
    cf = CACHE / cache_name
    if cf.exists():
        return json.loads(cf.read_text())
    r = requests.get(url, params=params, headers=HEADERS, timeout=60)
    r.raise_for_status()
    j = r.json()
    cf.write_text(json.dumps(j))
    return j


def false_bay_events(start, end):
    """{hour 'YYYY-MM-DDTHH' -> 'SE'|'SSE'} from Open-Meteo at the forcing point."""
    s = f"{start // 10000}-{(start // 100) % 100:02d}-{start % 100:02d}"
    e = f"{end // 10000}-{(end // 100) % 100:02d}-{end % 100:02d}"
    j = _get("https://archive-api.open-meteo.com/v1/archive",
             {"latitude": FALSE_BAY[0], "longitude": FALSE_BAY[1], "start_date": s,
              "end_date": e, "hourly": "wind_speed_10m,wind_direction_10m",
              "wind_speed_unit": "ms", "timezone": "UTC"},
             f"falsebay_{start}_{end}.json")
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


# ---------------------------------------------------------------- metrics
def responsiveness(series, events, sector):
    ev = [v[1] for k, v in series.items() if events.get(k) == sector]
    base = [v[1] for k, v in series.items() if k not in events]
    if not ev or not base or np.mean(base) < 0.2:
        return None
    return float(np.mean(ev)) / float(np.mean(base))


def circ_mean(degs):
    r = np.radians(degs)
    return float((math.degrees(math.atan2(np.mean(np.sin(r)), np.mean(np.cos(r)))) + 360.0) % 360.0)


def circ_diff(a, b):
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def signed_diff(a, b):
    """Smallest signed angle a-b in (-180, 180]; + = a is clockwise of b."""
    return ((a - b + 180.0) % 360.0) - 180.0


def obs_dir(series, events, sector):
    ds = [v[0] for k, v in series.items() if events.get(k) == sector and v[0] is not None]
    return circ_mean(ds) if len(ds) >= 10 else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", type=int, default=20241210)
    p.add_argument("--end", type=int, default=20250115)
    args = p.parse_args()

    clean = json.loads(CLEAN.read_text())
    stations = clean["kept"]
    events = false_bay_events(args.start, args.end)
    n_se = sum(v == "SE" for v in events.values())
    n_sse = sum(v == "SSE" for v in events.values())
    print(f"False Bay {FALSE_BAY} events {args.start}..{args.end}: {n_se} SE, {n_sse} SSE hours")
    print(f"{len(stations)} QC'd stations in domain\n")

    fields = {"SE": ModelField("SE"), "SSE": ModelField("SSE")}

    rows = []
    for st in stations:
        if not fields["SE"].inside(st["lat"], st["lon"]):
            continue
        series = st["series"]
        re_se, re_sse = responsiveness(series, events, "SE"), responsiveness(series, events, "SSE")
        m_su_se, m_dir_se = fields["SE"].sample(st["lat"], st["lon"])
        m_su_sse, m_dir_sse = fields["SSE"].sample(st["lat"], st["lon"])
        o_dir_se = obs_dir(series, events, "SE") if st["has_dir"] else None
        o_dir_sse = obs_dir(series, events, "SSE") if st["has_dir"] else None
        rows.append({
            "id": st["id"], "name": st["name"], "lat": st["lat"], "lon": st["lon"],
            "dist_km": st["dist_km"], "peak_ms": st["peak_ms"],
            "obs_se_resp": round(re_se, 3) if re_se else None,
            "obs_sse_resp": round(re_sse, 3) if re_sse else None,
            "model_se_speedup": round(m_su_se, 3), "model_sse_speedup": round(m_su_sse, 3),
            "obs_se_dir": round(o_dir_se, 1) if o_dir_se is not None else None,
            "model_se_dir": round(m_dir_se, 1),
            "se_dir_err": round(circ_diff(o_dir_se, m_dir_se), 1) if o_dir_se is not None else None,
            "obs_sse_dir": round(o_dir_sse, 1) if o_dir_sse is not None else None,
            "model_sse_dir": round(m_dir_sse, 1),
            "sse_dir_err": round(circ_diff(o_dir_sse, m_dir_sse), 1) if o_dir_sse is not None else None,
        })

    # Per-station vane QC + offset-robust direction skill.  A PWS vane has an
    # unknown fixed installation offset (many here are ~180 deg reversed), which
    # poisons the ABSOLUTE bearing test but CANCELS in the SE->SSE veer (the
    # change in bearing between the two event types).  So veer is the fair
    # direction-skill metric, and a station whose bearing is >120 deg off in
    # BOTH sectors is flagged as a suspect/reversed vane.
    for r in rows:
        r["vane_suspect"] = (r["se_dir_err"] is not None and r["se_dir_err"] > 120
                             and r["sse_dir_err"] is not None and r["sse_dir_err"] > 120)
        if r["obs_se_dir"] is not None and r["obs_sse_dir"] is not None:
            r["obs_veer"] = round(signed_diff(r["obs_sse_dir"], r["obs_se_dir"]), 1)
            r["model_veer"] = round(signed_diff(r["model_sse_dir"], r["model_se_dir"]), 1)
            r["veer_err"] = round(abs(r["obs_veer"] - r["model_veer"]), 1)
        else:
            r["obs_veer"] = r["model_veer"] = r["veer_err"] = None

    # ---- SPEED: rank-correlate responsiveness vs model speed-up across stations
    se_pairs = [(r["obs_se_resp"], r["model_se_speedup"]) for r in rows if r["obs_se_resp"]]
    sse_pairs = [(r["obs_sse_resp"], r["model_sse_speedup"]) for r in rows if r["obs_sse_resp"]]
    rho_se = spearmanr([a for a, _ in se_pairs], [b for _, b in se_pairs]) if len(se_pairs) >= 5 else None
    rho_sse = spearmanr([a for a, _ in sse_pairs], [b for _, b in sse_pairs]) if len(sse_pairs) >= 5 else None
    # SE->SSE contrast (cancels each station's siting): obs ratio vs model ratio
    contrast = [(r["obs_sse_resp"] / r["obs_se_resp"], r["model_sse_speedup"] / r["model_se_speedup"])
                for r in rows if r["obs_se_resp"] and r["obs_sse_resp"] and r["model_se_speedup"]]
    rho_contrast = (spearmanr([a for a, _ in contrast], [b for _, b in contrast])
                    if len(contrast) >= 5 else None)

    # ---- DIRECTION: absolute error (vane-offset contaminated) + offset-robust veer
    suspect = [r for r in rows if r["vane_suspect"]]
    good = [r for r in rows if not r["vane_suspect"]]
    se_errs = [r["se_dir_err"] for r in good if r["se_dir_err"] is not None]
    sse_errs = [r["sse_dir_err"] for r in good if r["sse_dir_err"] is not None]
    veer_errs = [r["veer_err"] for r in rows if r["veer_err"] is not None]
    veer_pairs = [(r["obs_veer"], r["model_veer"]) for r in rows if r["veer_err"] is not None]
    rho_veer = (spearmanr([a for a, _ in veer_pairs], [b for _, b in veer_pairs])
                if len(veer_pairs) >= 5 else None)
    # Signed bias (obs - model): + means observations are CLOCKWISE of the model
    # (i.e. the real south-easter reaches the station more southerly than the
    # uniform-inflow model rotates it).  Median over well-oriented vanes only.
    se_bias = [signed_diff(r["obs_se_dir"], r["model_se_dir"]) for r in good if r["obs_se_dir"] is not None]
    sse_bias = [signed_diff(r["obs_sse_dir"], r["model_sse_dir"]) for r in good if r["obs_sse_dir"] is not None]

    def summ(name, rho):
        if rho is None:
            return f"  {name}: too few stations"
        return f"  {name}: Spearman rho={rho.statistic:+.2f} (p={rho.pvalue:.3f})"

    print("SPEED — does the model rank stations by exposure the way observations do?")
    print(summ(f"SE responsiveness vs model speed-up (n={len(se_pairs)})", rho_se))
    print(summ(f"SSE responsiveness vs model speed-up (n={len(sse_pairs)})", rho_sse))
    print(summ(f"SE->SSE contrast ratio (n={len(contrast)})", rho_contrast))
    print(f"\nDIRECTION — {len(suspect)}/{len(rows)} stations have a suspect/reversed vane "
          f"(>120 deg off in both sectors): {', '.join(r['id'] for r in suspect)}")
    print("Absolute bearing error EXCLUDING suspect vanes (model local bearing vs obs):")
    if se_errs:
        print(f"  SE  (n={len(se_errs)}): median |err| {np.median(se_errs):.0f} deg, "
              f"within 30 deg: {np.mean(np.array(se_errs) <= 30)*100:.0f}%")
    if sse_errs:
        print(f"  SSE (n={len(sse_errs)}): median |err| {np.median(sse_errs):.0f} deg, "
              f"within 30 deg: {np.mean(np.array(sse_errs) <= 30)*100:.0f}%")
    if se_bias:
        print(f"  systematic bias obs-model (well-oriented vanes): "
              f"SE {np.median(se_bias):+.0f} deg, SSE {np.median(sse_bias):+.0f} deg "
              f"(+ = obs more southerly/clockwise than model)")
    print("Offset-robust SE->SSE veer (cancels each vane's fixed offset, incl. 180 flips):")
    if veer_errs:
        print(f"  veer |err| (n={len(veer_errs)}): median {np.median(veer_errs):.0f} deg, "
              f"within 15 deg: {np.mean(np.array(veer_errs) <= 15)*100:.0f}%")
    print(summ(f"  obs veer vs model veer (n={len(veer_pairs)})", rho_veer))

    out = {
        "window": [args.start, args.end], "event_point": FALSE_BAY,
        "n_se_hours": n_se, "n_sse_hours": n_sse, "n_stations": len(rows),
        "speed": {
            "metric": "Spearman(obs responsiveness vs model speedup) across stations",
            "se_rho": rho_se.statistic if rho_se else None,
            "sse_rho": rho_sse.statistic if rho_sse else None,
            "contrast_rho": rho_contrast.statistic if rho_contrast else None,
            "n_se": len(se_pairs), "n_sse": len(sse_pairs), "n_contrast": len(contrast),
        },
        "direction": {
            "metric": "circular |model_bearing - obs_bearing| during event hours, deg",
            "n_vane_suspect": len(suspect),
            "vane_suspect_ids": [r["id"] for r in suspect],
            "abs_excl_suspect": {
                "se_median_err": float(np.median(se_errs)) if se_errs else None,
                "se_within_30deg": float(np.mean(np.array(se_errs) <= 30)) if se_errs else None,
                "sse_median_err": float(np.median(sse_errs)) if sse_errs else None,
                "sse_within_30deg": float(np.mean(np.array(sse_errs) <= 30)) if sse_errs else None,
                "n_se": len(se_errs), "n_sse": len(sse_errs),
            },
            "veer_offset_robust": {
                "note": "SE->SSE veer cancels each vane's fixed offset incl. 180 flips",
                "median_err": float(np.median(veer_errs)) if veer_errs else None,
                "within_15deg": float(np.mean(np.array(veer_errs) <= 15)) if veer_errs else None,
                "rho": rho_veer.statistic if rho_veer else None,
                "n": len(veer_pairs),
            },
            "signed_bias_obs_minus_model": {
                "note": "+ = obs more southerly/clockwise than model; well-oriented vanes only",
                "se_median": float(np.median(se_bias)) if se_bias else None,
                "sse_median": float(np.median(sse_bias)) if sse_bias else None,
            },
        },
        "rows": sorted(rows, key=lambda r: (r["lat"], r["lon"])),
    }
    Path("output").mkdir(exist_ok=True)
    Path("output/station_validation.json").write_text(json.dumps(out, indent=2))
    print("\nWritten output/station_validation.json")


if __name__ == "__main__":
    main()
