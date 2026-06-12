"""Characterise the south-easter from real hourly wind records.

Source: Open-Meteo historical archive (free, no API key). We sample a point
over False Bay, upwind of the peninsula for south-easterly flow, so the
statistics describe the *incoming* wind before terrain modification.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import requests

from .config import WindScenario

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
UPWIND_POINT = (-34.20, 18.65)  # over False Bay, SE of the peninsula

# South-easter definition: direction sector and season (Oct-Mar).
SE_SECTOR = (100.0, 170.0)
SE_MONTHS = {10, 11, 12, 1, 2, 3}
MIN_EVENT_SPEED = 4.0  # m/s; ignore near-calm hours when characterising events


def fetch_climatology(
    start: str = "2023-01-01",
    end: str = "2025-12-31",
    cache_dir: str | Path = "data/cache",
) -> dict:
    """Hourly 10 m wind speed/direction/gusts at the upwind point."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"openmeteo_{start}_{end}.json"
    if cache.exists():
        return json.loads(cache.read_text())

    params = {
        "latitude": UPWIND_POINT[0],
        "longitude": UPWIND_POINT[1],
        "start_date": start,
        "end_date": end,
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "wind_speed_unit": "ms",
        "timezone": "UTC",
    }
    resp = requests.get(ARCHIVE_URL, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    cache.write_text(json.dumps(data))
    return data


def southeaster_stats(clim: dict) -> dict:
    """Statistics of south-easter events from the hourly record."""
    hourly = clim["hourly"]
    t = hourly["time"]
    spd = np.array(hourly["wind_speed_10m"], dtype=float)
    direc = np.array(hourly["wind_direction_10m"], dtype=float)
    gust = np.array(hourly["wind_gusts_10m"], dtype=float)
    month = np.array([int(s[5:7]) for s in t])

    ok = np.isfinite(spd) & np.isfinite(direc) & np.isfinite(gust)
    season = np.isin(month, list(SE_MONTHS))
    se = ok & season & (direc >= SE_SECTOR[0]) & (direc <= SE_SECTOR[1]) & (spd >= MIN_EVENT_SPEED)

    sel_s, sel_d, sel_g = spd[se], direc[se], gust[se]
    # Circular mean of direction.
    rad = np.radians(sel_d)
    mean_dir = math.degrees(math.atan2(np.sin(rad).mean(), np.cos(rad).mean())) % 360.0

    return {
        "n_hours": int(se.sum()),
        "share_of_season_hours": float(se.sum() / max(1, (ok & season).sum())),
        "direction_mean": float(mean_dir),
        "speed_median": float(np.median(sel_s)),
        "speed_p90": float(np.percentile(sel_s, 90)),
        "speed_max": float(sel_s.max()),
        "gust_factor_median": float(np.median(sel_g / np.maximum(sel_s, 0.5))),
        "period": f"{clim['hourly']['time'][0][:10]} .. {clim['hourly']['time'][-1][:10]}",
    }


SECTOR_LABELS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                 "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def sector_stats(clim: dict, n_sectors: int = 16) -> list[dict]:
    """Per-compass-sector wind statistics with seasonal frequencies.

    Summer = Oct-Mar (south-easter season), winter = Apr-Sep (north-westerly
    frontal season). Frequencies are the share of windy hours (>= 2 m/s) in
    that season coming from the sector; speed stats use event hours
    (>= MIN_EVENT_SPEED) from the whole record.
    """
    hourly = clim["hourly"]
    t = hourly["time"]
    spd = np.array(hourly["wind_speed_10m"], dtype=float)
    direc = np.array(hourly["wind_direction_10m"], dtype=float)
    gust = np.array(hourly["wind_gusts_10m"], dtype=float)
    month = np.array([int(s[5:7]) for s in t])

    ok = np.isfinite(spd) & np.isfinite(direc) & np.isfinite(gust)
    windy = ok & (spd >= 2.0)
    summer = np.isin(month, list(SE_MONTHS))
    winter = ~summer
    n_summer = max(1, int((windy & summer).sum()))
    n_winter = max(1, int((windy & winter).sum()))

    half = 180.0 / n_sectors
    overall_median = float(np.median(spd[ok & (spd >= MIN_EVENT_SPEED)]))
    overall_p90 = float(np.percentile(spd[ok & (spd >= MIN_EVENT_SPEED)], 90))

    out = []
    for k in range(n_sectors):
        centre = k * 360.0 / n_sectors
        diff = np.abs((direc - centre + 180.0) % 360.0 - 180.0)
        in_sec = diff <= half
        events = ok & in_sec & (spd >= MIN_EVENT_SPEED)
        n = int(events.sum())
        sparse = n < 100
        stats = {
            "label": SECTOR_LABELS[k],
            "direction": centre,
            "n_hours": n,
            "sparse": sparse,
            "summer_share": float((windy & summer & in_sec).sum() / n_summer),
            "winter_share": float((windy & winter & in_sec).sum() / n_winter),
        }
        if sparse:
            stats["speed_median"] = overall_median
            stats["speed_p90"] = overall_p90
            stats["gust_factor"] = 1.45
        else:
            stats["speed_median"] = float(np.median(spd[events]))
            stats["speed_p90"] = float(np.percentile(spd[events], 90))
            stats["gust_factor"] = float(np.median(gust[events] / np.maximum(spd[events], 0.5)))
        out.append(stats)
    return out


def make_scenario(strength: str = "typical", offline: bool = False,
                  cache_dir: str | Path = "data/cache") -> tuple[WindScenario, dict | None]:
    """Build a simulation scenario from real records (or fallbacks)."""
    stats = None
    if not offline:
        try:
            stats = southeaster_stats(fetch_climatology(cache_dir=cache_dir))
        except Exception as err:  # noqa: BLE001 - degrade gracefully to defaults
            print(f"  ! could not fetch wind climatology ({err}); using fallback defaults")

    if stats is None:
        scn = WindScenario()
        if strength == "strong":
            scn.speed_10m = 15.5
            scn.label = "strong south-easter (fallback defaults)"
        return scn, None

    speed = stats["speed_median"] if strength == "typical" else stats["speed_p90"]
    scn = WindScenario(
        direction_deg=stats["direction_mean"],
        speed_10m=speed,
        gust_factor=stats["gust_factor_median"],
        label=(
            f"{strength} south-easter from observations {stats['period']} "
            f"({stats['n_hours']} SE hours)"
        ),
    )
    return scn, stats
