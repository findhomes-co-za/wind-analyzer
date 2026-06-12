"""Maps, CSV ranking and markdown report."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LightSource, TwoSlopeNorm

from .config import WindScenario
from .diagnostics import SurfaceFields
from .suburbs import LANDMARKS, SUBURBS
from .terrain import TerrainGrid


def _km_extent(t: TerrainGrid):
    return [0, t.nx * t.dx / 1000.0, 0, t.ny * t.dy / 1000.0]


def _annotate(ax, t: TerrainGrid, label_suburbs=True, label_peaks=True):
    if label_suburbs:
        for s in SUBURBS:
            j, i = t.lonlat_to_ij(s.lon, s.lat)
            if 0 <= j < t.ny and 0 <= i < t.nx:
                x, y = i * t.dx / 1000.0, j * t.dy / 1000.0
                ax.plot(x, y, "o", ms=2.5, color="white", mec="black", mew=0.4)
                ax.annotate(s.name, (x, y), textcoords="offset points", xytext=(3, 2),
                            fontsize=4.5, color="white",
                            path_effects=_halo())
    if label_peaks:
        for name, lat, lon, _h in LANDMARKS:
            j, i = t.lonlat_to_ij(lon, lat)
            if 0 <= j < t.ny and 0 <= i < t.nx:
                x, y = i * t.dx / 1000.0, j * t.dy / 1000.0
                ax.plot(x, y, "^", ms=4, color="black", mec="white", mew=0.5)
                ax.annotate(name, (x, y), textcoords="offset points", xytext=(3, -6),
                            fontsize=5, color="black", style="italic",
                            path_effects=_halo("white"))


def _halo(color="black"):
    import matplotlib.patheffects as pe

    return [pe.withStroke(linewidth=1.2, foreground=color)]


def _wind_arrow(ax, scn: WindScenario, extent):
    u, v = scn.components(1.0)
    x0, y0 = extent[1] * 0.88, extent[3] * 0.90
    ax.annotate(
        "", xy=(x0 + u * 2.2, y0 + v * 2.2), xytext=(x0, y0),
        arrowprops=dict(arrowstyle="-|>", lw=2, color="crimson"),
    )
    ax.annotate(f"SE wind\n{scn.speed_10m:.1f} m/s", (x0, y0),
                textcoords="offset points", xytext=(-8, 8), fontsize=6,
                color="crimson", ha="right", path_effects=_halo("white"))


def _base(t: TerrainGrid, figsize=(8.5, 9.5)):
    fig, ax = plt.subplots(figsize=figsize, dpi=200)
    ls = LightSource(azdeg=315, altdeg=45)
    shade = ls.hillshade(t.zs, vert_exag=2, dx=t.dx, dy=t.dy)
    ax.imshow(shade, cmap="gray", origin="lower", extent=_km_extent(t), alpha=0.45)
    ax.set_xlabel("km east")
    ax.set_ylabel("km north")
    return fig, ax


def save_maps(t: TerrainGrid, sf: SurfaceFields, scn: WindScenario, outdir: Path):
    ext = _km_extent(t)
    xkm, ykm = t.x_km(), t.y_km()

    # 1. Terrain
    fig, ax = _base(t)
    im = ax.imshow(t.zs, cmap="terrain", origin="lower", extent=ext, alpha=0.6)
    fig.colorbar(im, ax=ax, shrink=0.7, label="elevation (m)")
    _annotate(ax, t)
    ax.set_title("Cape Peninsula model terrain (SRTM via AWS terrain tiles)")
    fig.savefig(outdir / "terrain.png", bbox_inches="tight")
    plt.close(fig)

    # 2. 10 m wind speed + streamlines
    fig, ax = _base(t)
    im = ax.imshow(sf.speed10, cmap="turbo", origin="lower", extent=ext, alpha=0.75)
    fig.colorbar(im, ax=ax, shrink=0.7, label="10 m wind speed (m/s)")
    step = max(1, t.nx // 70)
    ax.streamplot(xkm[::step], ykm[::step], sf.u10[::step, ::step], sf.v10[::step, ::step],
                  density=1.4, color="white", linewidth=0.45, arrowsize=0.5)
    _annotate(ax, t)
    _wind_arrow(ax, scn, ext)
    ax.set_title(f"Modelled 10 m wind — {scn.label}")
    fig.savefig(outdir / "wind_speed.png", bbox_inches="tight")
    plt.close(fig)

    # 3. Speed-up factor
    fig, ax = _base(t)
    im = ax.imshow(sf.speedup, cmap="RdBu_r", origin="lower", extent=ext, alpha=0.75,
                   norm=TwoSlopeNorm(vcenter=1.0, vmin=0.0, vmax=max(1.6, float(np.nanmax(sf.speedup)))))
    fig.colorbar(im, ax=ax, shrink=0.7, label="speed-up factor (local / inflow)")
    _annotate(ax, t)
    ax.set_title("Terrain speed-up: red = accelerated, blue = sheltered")
    fig.savefig(outdir / "speedup.png", bbox_inches="tight")
    plt.close(fig)

    # 4. Turbulence index + rotor zones
    fig, ax = _base(t)
    im = ax.imshow(sf.ti, cmap="inferno", origin="lower", extent=ext, alpha=0.75)
    fig.colorbar(im, ax=ax, shrink=0.7, label="turbulence intensity index")
    if sf.rotor.max() > 0.05:
        ax.contour(xkm, ykm, sf.rotor, levels=[0.3, 0.6], colors="cyan", linewidths=0.7)
    _annotate(ax, t)
    ax.set_title("Turbulence index (cyan contours: lee-rotor potential)")
    fig.savefig(outdir / "turbulence.png", bbox_inches="tight")
    plt.close(fig)

    # 5. Venturi / Coanda effect zones
    fig, ax = _base(t)
    ax.imshow(t.zs, cmap="Greys", origin="lower", extent=ext, alpha=0.25)
    ven = np.ma.masked_where(~sf.channel_mask, np.ones_like(t.zs))
    coa = np.ma.masked_where(~sf.coanda_mask, np.ones_like(t.zs))
    ax.imshow(coa, cmap=matplotlib.colors.ListedColormap(["#00bcd4"]), origin="lower",
              extent=ext, alpha=0.55)
    ax.imshow(ven, cmap=matplotlib.colors.ListedColormap(["#ff6f00"]), origin="lower",
              extent=ext, alpha=0.65)
    _annotate(ax, t)
    _wind_arrow(ax, scn, ext)
    import matplotlib.patches as mpatches

    ax.legend(handles=[
        mpatches.Patch(color="#ff6f00", label="Venturi channeling (confined + accelerated)"),
        mpatches.Patch(color="#00bcd4", label="Coanda deflection (attached + turned > 25°)"),
    ], loc="lower left", fontsize=6)
    ax.set_title("Flow-effect classification")
    fig.savefig(outdir / "effects.png", bbox_inches="tight")
    plt.close(fig)


def write_csv(rows: list[dict], path: Path):
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def format_table(rows: list[dict], limit: int | None = None) -> str:
    hdr = (f"{'#':>2} {'Suburb':<20} {'Group':<18} {'Mean':>6} {'P90':>6} "
           f"{'Gust':>6} {'Spd-up':>7} {'TI':>5} {'Effects':<16}")
    lines = [hdr, "-" * len(hdr)]
    for n, r in enumerate(rows[:limit] if limit else rows, 1):
        effects = []
        if r["channel_share"] > 0.15:
            effects.append("venturi")
        if r["coanda_share"] > 0.25:
            effects.append("coanda")
        if r["rotor_mean"] > 0.25:
            effects.append("rotor")
        lines.append(
            f"{n:>2} {r['suburb']:<20} {r['group']:<18} {r['speed10_mean']:>6.1f} "
            f"{r['speed10_p90']:>6.1f} {r['gust_mean']:>6.1f} {r['speedup']:>7.2f} "
            f"{r['ti_mean']:>5.2f} {','.join(effects):<16}"
        )
    return "\n".join(lines)


def write_report(outdir: Path, scn: WindScenario, stats: dict | None,
                 rows: list[dict], solve_info: dict):
    md = [
        "# Cape Town South-Easter Wind Analysis",
        "",
        f"**Scenario:** {scn.label}",
        f"**Inflow:** {scn.speed_10m:.1f} m/s at 10 m from {scn.direction_deg:.0f}° "
        f"(gust factor {scn.gust_factor:.2f})",
        f"**Stability:** N = {scn.bvf} s⁻¹, Froude number (1000 m obstacle) = "
        f"{scn.froude():.2f}, mass-consistent alpha ratio r = {scn.alpha_ratio():.2f}",
        f"**Solver:** {solve_info.get('cells', '?')} fluid cells, max |div| "
        f"{solve_info.get('div_before', 0):.2e} -> {solve_info.get('div_after', 0):.2e} s⁻¹",
        "",
    ]
    if stats:
        md += [
            "## Observed south-easter climatology (upwind point, False Bay)",
            "",
            f"- Period: {stats['period']}, {stats['n_hours']} south-easterly hours "
            f"({100 * stats['share_of_season_hours']:.0f}% of Oct-Mar hours)",
            f"- Mean direction {stats['direction_mean']:.0f}°, median speed "
            f"{stats['speed_median']:.1f} m/s, 90th percentile {stats['speed_p90']:.1f} m/s, "
            f"max {stats['speed_max']:.1f} m/s",
            "",
        ]
    md += [
        "## Suburb ranking (windiest first)",
        "",
        "| # | Suburb | Group | Mean 10 m (m/s) | P90 (m/s) | Gust (m/s) | Speed-up | TI | Venturi | Coanda | Rotor |",
        "|---|--------|-------|------|-----|------|----------|----|---------|--------|-------|",
    ]
    for n, r in enumerate(rows, 1):
        md.append(
            f"| {n} | {r['suburb']} | {r['group']} | {r['speed10_mean']:.1f} | "
            f"{r['speed10_p90']:.1f} | {r['gust_mean']:.1f} | {r['speedup']:.2f} | "
            f"{r['ti_mean']:.2f} | {100 * r['channel_share']:.0f}% | "
            f"{100 * r['coanda_share']:.0f}% | {r['rotor_mean']:.2f} |"
        )
    md += [
        "",
        "## Maps",
        "",
        "![terrain](terrain.png)",
        "![wind speed](wind_speed.png)",
        "![speed-up](speedup.png)",
        "![turbulence](turbulence.png)",
        "![effects](effects.png)",
        "",
        "## Model notes and limitations",
        "",
        "- Mass-consistent diagnostic model (NUATMOS/WindNinja family): mass is",
        "  conserved exactly but momentum is not solved, so dynamic separation,",
        "  hydraulic jumps and unsteady gusts are represented heuristically",
        "  (rotor/TI diagnostics), not explicitly.",
        "- Venturi channeling and Coanda-style attachment emerge from the",
        "  continuity solve with stability-weighted vertical motion; the masks",
        "  shown are diagnostic classifications of the solved field.",
        "- Elevation: SRTM-derived terrarium tiles (~30 m source, modelled at",
        "  grid resolution). Wind climatology: Open-Meteo reanalysis archive.",
    ]
    (outdir / "REPORT.md").write_text("\n".join(md))
