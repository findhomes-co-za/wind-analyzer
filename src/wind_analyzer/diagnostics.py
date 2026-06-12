"""Near-surface fields and derived diagnostics.

From the solved 3D flow we extract 10 m AGL winds and diagnose:

  * speed-up factor relative to the undisturbed inflow,
  * flow deflection (degrees away from the inflow direction),
  * a turbulence-intensity index combining local shear, lee-rotor
    potential (downwind of high crests at favourable Froude number)
    and wake speed deficit,
  * gust estimate calibrated to the observed flat-terrain gust factor,
  * heuristic masks for Venturi channeling (accelerated flow laterally
    confined by higher terrain) and Coanda-style attachment (fast flow
    strongly deflected while hugging steep terrain).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import distance_transform_edt, gaussian_filter, map_coordinates

from .config import WindScenario
from .solver import FlowField
from .terrain import TerrainGrid

Z0_SURFACE = 0.05  # roughness used for the 10 m log-law correction (m)
GUST_PEAK_FACTOR = 2.5


@dataclass
class SurfaceFields:
    speed10: np.ndarray       # (ny, nx) street-level wind: 10 m AGL over local roughness (m/s)
    u10: np.ndarray
    v10: np.ndarray
    speedup: np.ndarray       # speed10 / undisturbed inflow speed at 10 m
    deflection: np.ndarray    # signed deg away from inflow direction (+ = veered cw)
    ti: np.ndarray            # turbulence intensity index (~0.15 over open water)
    gust: np.ndarray          # gust estimate (m/s)
    rotor: np.ndarray         # lee-rotor potential 0..1
    channel_mask: np.ndarray  # bool, Venturi channeling zones
    coanda_mask: np.ndarray   # bool, attachment/deflection zones
    downwash_mask: np.ndarray # bool, tall-building downwash cells
    z_agl: np.ndarray         # height AGL of the first fluid cell centre


def _take_level(a3: np.ndarray, k: np.ndarray) -> np.ndarray:
    return np.take_along_axis(a3, k[None, :, :], axis=0)[0]


def _upstream_max(zs, dx, dy, flow_u, flow_v, fetch=2500.0):
    """Highest terrain within `fetch` metres upwind of every cell."""
    mag = math.hypot(flow_u, flow_v)
    ux, uy = -flow_u / mag, -flow_v / mag
    ny, nx = zs.shape
    jj, ii = np.mgrid[0:ny, 0:nx].astype(float)
    zmax = zs.copy()
    step = min(dx, dy)
    for s in np.arange(step, fetch + 0.1, step):
        rows = jj + uy * s / dy
        cols = ii + ux * s / dx
        zmax = np.maximum(zmax, map_coordinates(zs, [rows, cols], order=1, mode="nearest"))
    return zmax


def _side_max(zs, dx, dy, nx_hat, ny_hat, dists):
    """Max terrain at the given perpendicular offsets (one side)."""
    ny, nx = zs.shape
    jj, ii = np.mgrid[0:ny, 0:nx].astype(float)
    out = np.full_like(zs, -np.inf)
    for d in dists:
        rows = jj + ny_hat * d / dy
        cols = ii + nx_hat * d / dx
        out = np.maximum(out, map_coordinates(zs, [rows, cols], order=1, mode="nearest"))
    return out


def compute_surface(flow: FlowField, terrain: TerrainGrid, scn: WindScenario,
                    z0: float | np.ndarray = Z0_SURFACE,
                    bld_h: np.ndarray | None = None) -> SurfaceFields:
    """Street-level fields.

    z0    : surface roughness (m) — scalar or a (ny, nx) map (e.g. WorldCover).
    bld_h : optional (ny, nx) max tall-building height per cell; adds urban
            canyon attenuation of the mean wind and downwash gust/TI boosts.
    """
    zs, dx, dy = terrain.zs, terrain.dx, terrain.dy
    zc = flow.z_centres
    nz = len(zc)
    z0m = np.broadcast_to(np.asarray(z0, dtype=float), zs.shape)

    ksfc = flow.fluid.argmax(axis=0)
    z_agl = np.maximum(zc[ksfc] - zs, 1.0)

    uc = _take_level(np.nan_to_num(flow.u), ksfc)
    vc = _take_level(np.nan_to_num(flow.v), ksfc)
    spd_c = np.hypot(uc, vc)

    # 10 m street-level correction, two factors:
    #  f_h — log-law height adjustment from the first cell centre to 10 m AGL
    #        (clipped: extrapolating from a near-surface cell must not
    #        amplify staircase noise near cliffs);
    #  f_r — roughness equilibrium: a boundary layer over rough urban/forest
    #        surfaces carries less wind at 10 m than the marine inflow layer
    #        does, for the same forcing aloft (blending height ~200 m),
    #        normalised so open water = 1.
    HB, Z0_SEA = 200.0, 2e-4
    with np.errstate(divide="ignore", invalid="ignore"):
        f_h = np.log(10.0 / z0m) / np.log(np.maximum(z_agl, 4.0) / z0m)
        f_r = ((np.log(10.0 / z0m) / np.log(HB / z0m))
               / (math.log(10.0 / Z0_SEA) / math.log(HB / Z0_SEA)))
    f_h = np.clip(np.nan_to_num(f_h, nan=1.0), 0.6, 1.5)
    fac = f_h * np.clip(np.nan_to_num(f_r, nan=1.0), 0.55, 1.05)
    # Mild smoothing removes the staircase imprint of blocked cells.
    u10 = gaussian_filter(uc * fac, sigma=0.7)
    v10 = gaussian_filter(vc * fac, sigma=0.7)
    speed10 = np.hypot(u10, v10)

    # Tall buildings: dense high fabric slows the mean street wind (canyon
    # sheltering on average) — downwash gust boost is applied further below.
    downwash_mask = np.zeros(zs.shape, dtype=bool)
    if bld_h is not None:
        downwash_mask = bld_h >= 25.0
        damp = np.where(downwash_mask, 0.85, 1.0)
        u10 = u10 * damp
        v10 = v10 * damp
        speed10 = speed10 * damp

    ref10 = max(scn.speed_10m, 0.1)
    speedup = speed10 / ref10

    inflow_dir = scn.direction_deg
    local_dir = (np.degrees(np.arctan2(-u10, -v10))) % 360.0
    deflection = (local_dir - inflow_dir + 180.0) % 360.0 - 180.0
    deflection[speed10 < 0.5] = 0.0

    # --- turbulence intensity ------------------------------------------------
    k2 = np.minimum(ksfc + 2, nz - 1)
    u2 = _take_level(np.nan_to_num(flow.u), k2)
    v2 = _take_level(np.nan_to_num(flow.v), k2)
    spd2 = np.hypot(u2, v2)
    z2 = np.maximum(zc[k2] - zs, z_agl + 1.0)
    ustar = 0.4 * np.maximum(spd2 - spd_c, 0.0) / np.log(z2 / np.maximum(z_agl, 0.5))
    ti_shear = GUST_PEAK_FACTOR * ustar / np.maximum(speed10, 1.0)

    fr = scn.froude()
    fr_mod = math.exp(-(((fr - 1.0) / 0.6) ** 2))  # rotors peak when Fr ~ 1
    # Rotor streamers off Table Mountain reach the full City Bowl: ~4 km fetch.
    drop = _upstream_max(zs, dx, dy, *scn.components(1.0), fetch=4000.0) - zs
    rotor = np.clip((drop - 250.0) / 450.0, 0.0, 1.0) * fr_mod

    wake = np.clip(1.0 - speedup, 0.0, 1.0)
    ti = np.clip(ti_shear + 0.35 * rotor + 0.15 * wake, 0.0, 0.7)
    ti = gaussian_filter(ti, sigma=1.0)

    # Gust peak factor calibrated so flat-terrain gust ratio matches the
    # observed climatological gust factor.
    ti_flat = max(float(np.median(ti[zs < 2.0])), 1e-3)
    g_p = (scn.gust_factor - 1.0) / ti_flat
    gust = speed10 * (1.0 + g_p * ti)

    # Tall-building downwash: towers bring roof-height momentum down to the
    # street — gusts approach ~0.75 x the wind at roof level at corners.
    if bld_h is not None and downwash_mask.any():
        u3, v3 = np.nan_to_num(flow.u), np.nan_to_num(flow.v)
        for j, i in zip(*np.nonzero(downwash_mask)):
            k = int(np.searchsorted(zc, zs[j, i] + bld_h[j, i]))
            k = min(max(k, int(ksfc[j, i])), nz - 1)
            uroof = math.hypot(u3[k, j, i], v3[k, j, i])
            gust[j, i] = max(gust[j, i], 0.75 * uroof)
            ti[j, i] = min(0.7, ti[j, i] + 0.12)

    # --- Venturi channeling --------------------------------------------------
    with np.errstate(invalid="ignore", divide="ignore"):
        uh = np.where(speed10 > 0.5, u10 / np.maximum(speed10, 0.1), 0.0)
        vh = np.where(speed10 > 0.5, v10 / np.maximum(speed10, 0.1), 0.0)
    dists = np.arange(300.0, 1501.0, 300.0)
    # Perpendicular max terrain on both sides of the local flow direction.
    # Loop in coarse blocks to reuse _side_max with scalar offsets.
    left = np.full_like(zs, -np.inf)
    right = np.full_like(zs, -np.inf)
    jj, ii = np.mgrid[0:zs.shape[0], 0:zs.shape[1]].astype(float)
    for d in dists:
        rows = jj + (uh) * d / dy   # left normal = (-vh, +uh)
        cols = ii + (-vh) * d / dx
        left = np.maximum(left, map_coordinates(zs, [rows, cols], order=1, mode="nearest"))
        rows = jj + (-uh) * d / dy  # right normal = (+vh, -uh)
        cols = ii + (vh) * d / dx
        right = np.maximum(right, map_coordinates(zs, [rows, cols], order=1, mode="nearest"))
    confined = (left > zs + 120.0) & (right > zs + 120.0)
    channel_mask = (speedup > 1.15) & confined

    # --- Coanda-style attachment ---------------------------------------------
    gy, gx = np.gradient(zs, dy, dx)
    slope = np.hypot(gx, gy)
    dist_steep = distance_transform_edt(slope < 0.25) * min(dx, dy)
    coanda_mask = (dist_steep < 1200.0) & (np.abs(deflection) > 25.0) & (speedup > 0.85)

    return SurfaceFields(
        speed10=speed10, u10=u10, v10=v10, speedup=speedup, deflection=deflection,
        ti=ti, gust=gust, rotor=rotor, channel_mask=channel_mask,
        coanda_mask=coanda_mask, downwash_mask=downwash_mask, z_agl=z_agl,
    )
