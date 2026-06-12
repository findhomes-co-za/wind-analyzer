"""Physics validation of the mass-consistent solver on idealised terrain."""

import numpy as np
import pytest

from wind_analyzer.solver import MassConsistentSolver, build_levels


def uniform_profiles(solver, speed=10.0, direction="east"):
    u = np.full(solver.nz, speed if direction == "east" else 0.0)
    v = np.full(solver.nz, speed if direction == "north" else 0.0)
    if direction == "east":
        v[:] = 0.0
    return u, v


def first_fluid_speed(flow, j, i):
    k = flow.fluid[:, j, i].argmax()
    return float(np.hypot(flow.u[k, j, i], flow.v[k, j, i]))


def test_flat_terrain_leaves_flow_unchanged():
    zs = np.zeros((30, 40))
    zf = build_levels(20, 1.25, 2000)
    s = MassConsistentSolver(zs, 100, 100, zf, alpha_ratio=1.0)
    flow = s.solve(*uniform_profiles(s))
    assert flow.div_before < 1e-10
    assert np.nanmax(np.abs(flow.u - 10.0)) < 1e-6
    assert np.nanmax(np.abs(flow.w)) < 1e-6


def test_divergence_is_eliminated_over_real_terrain():
    rng = np.random.default_rng(7)
    ny, nx = 40, 50
    zs = np.zeros((ny, nx))
    for _ in range(6):
        cy, cx = rng.uniform(8, ny - 8), rng.uniform(8, nx - 8)
        h, w = rng.uniform(200, 700), rng.uniform(3, 8)
        jj, ii = np.mgrid[0:ny, 0:nx]
        zs += h * np.exp(-(((jj - cy) / w) ** 2 + ((ii - cx) / w) ** 2))
    zf = build_levels(15, 1.22, 3500)
    s = MassConsistentSolver(zs, 150, 150, zf, alpha_ratio=0.8)
    flow = s.solve(*uniform_profiles(s))
    assert flow.div_before > 1e-3
    assert flow.div_after < 1e-4 * flow.div_before


def test_ridge_crest_accelerates_flow():
    """Flow over a long ridge must speed up at the crest (continuity squeeze)."""
    ny, nx = 24, 80
    jj, ii = np.mgrid[0:ny, 0:nx]
    zs = 800.0 * np.exp(-(((ii - 40) * 100.0 / 1500.0) ** 2))  # ridge across the flow
    zf = build_levels(15, 1.22, 3000)
    s = MassConsistentSolver(zs, 100, 100, zf, alpha_ratio=1.0)
    flow = s.solve(*uniform_profiles(s))
    crest = first_fluid_speed(flow, ny // 2, 40)
    upstream = first_fluid_speed(flow, ny // 2, 5)
    assert crest > 1.05 * upstream


def test_venturi_gap_accelerates_flow():
    """A gap in a blocking ridge must carry faster flow than the inflow."""
    ny, nx = 60, 80
    jj, ii = np.mgrid[0:ny, 0:nx]
    ridge = 700.0 * np.exp(-(((ii - 40) * 100.0 / 1200.0) ** 2))
    gap = np.exp(-(((jj - 30) * 100.0 / 800.0) ** 2))  # opening at mid-y
    zs = ridge * (1.0 - 0.95 * gap)
    zf = build_levels(15, 1.22, 3000)
    s = MassConsistentSolver(zs, 100, 100, zf, alpha_ratio=0.35)  # stable: flow around
    flow = s.solve(*uniform_profiles(s))
    in_gap = first_fluid_speed(flow, 30, 40)
    upstream = first_fluid_speed(flow, 30, 5)
    assert in_gap > 1.15 * upstream


def test_stability_forces_flow_around_not_over():
    """Lateral (Coanda-style) deflection around a peak grows as Fr drops."""
    ny, nx = 50, 60
    jj, ii = np.mgrid[0:ny, 0:nx]
    zs = 900.0 * np.exp(-(((jj - 25) * 100.0 / 900.0) ** 2 + ((ii - 30) * 100.0 / 900.0) ** 2))
    zf = build_levels(15, 1.22, 3200)

    results = {}
    for label, r in (("neutral", 1.0), ("stable", 0.25)):
        s = MassConsistentSolver(zs, 100, 100, zf, alpha_ratio=r)
        flow = s.solve(*uniform_profiles(s))
        k_low = 2  # near-surface level on the flank
        flank_v = np.nanmax(np.abs(flow.v[k_low, :, 28:33]))
        crest_w = np.nanmax(np.abs(np.nan_to_num(flow.w[:, 20:31, 25:36])))
        results[label] = (flank_v, crest_w)

    assert results["stable"][0] > results["neutral"][0]  # more lateral deflection
    assert results["stable"][1] < results["neutral"][1]  # less vertical motion


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
