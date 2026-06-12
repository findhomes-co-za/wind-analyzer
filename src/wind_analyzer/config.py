"""Domain and wind-scenario configuration."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Domain:
    """Model domain covering the City Bowl, Atlantic Seaboard and upwind fetch.

    The south-easter arrives over False Bay / the Cape Flats, so the domain
    extends east and south of the mountain chain to give the inflow an
    undisturbed boundary.
    """

    lon_min: float = 18.30
    lon_max: float = 18.55
    lat_min: float = -34.10
    lat_max: float = -33.84
    resolution_m: float = 150.0
    z_top: float = 4500.0     # domain top (m ASL); ~4x Table Mountain height
    dz0: float = 14.0         # thickness of lowest cell (m)
    dz_ratio: float = 1.18    # geometric stretching of vertical levels

    @property
    def lat_mid(self) -> float:
        return 0.5 * (self.lat_min + self.lat_max)


@dataclass
class WindScenario:
    """Incoming wind characterisation for one simulation run.

    direction_deg : meteorological convention (direction the wind comes FROM,
                    clockwise from north). The south-easter is ~120-160 deg.
    speed_10m     : wind speed at 10 m AGL over the undisturbed upwind fetch (m/s).
    gust_factor   : observed ratio of gust to mean speed over flat terrain.
    bvf           : bulk Brunt-Vaisala frequency N (1/s). The Cape south-easter
                    is a stable marine layer capped by a sharp inversion near
                    mountain-top height (the "tablecloth"); the bulk stability
                    across that layer is well above the dry-air value, so we
                    default to N ~ 0.018 rather than ~0.012.
    z0            : aerodynamic roughness of the upwind fetch (m); water/flats.
    bl_top        : height (m) above which the inflow log profile is held constant.
    """

    direction_deg: float = 140.0
    speed_10m: float = 10.5
    gust_factor: float = 1.45
    label: str = "typical south-easter (fallback defaults)"
    bvf: float = 0.018
    z0: float = 0.02
    bl_top: float = 1000.0

    def profile(self, z):
        """Inflow speed at height(s) z metres AGL (log law capped at bl_top)."""
        import numpy as np

        zz = np.minimum(np.maximum(np.asarray(z, dtype=float), 2.0), self.bl_top)
        return self.speed_10m * np.log(zz / self.z0) / math.log(10.0 / self.z0)

    def components(self, speed):
        """(u, v) = (eastward, northward) components for this direction."""
        th = math.radians(self.direction_deg)
        return -speed * math.sin(th), -speed * math.cos(th)

    def crest_speed(self, h: float = 1000.0) -> float:
        return float(self.profile(h))

    def froude(self, h: float = 1000.0) -> float:
        """Froude number U/(N h) for an obstacle of height h."""
        return self.crest_speed(h) / (self.bvf * h)

    def alpha_ratio(self, h: float = 1000.0) -> float:
        """Mass-consistent stability ratio r = alpha1/alpha2 in (0, 1].

        r**2 weights the vertical term of the elliptic equation: r -> 1 is
        neutral flow (terrain crossed freely); r -> 0 is strongly stable flow
        (vertical displacement suppressed, air forced AROUND obstacles).
        We use the NUATMOS-style mapping r^2 = Fr^2 / (1 + Fr^2), which has
        the right limits in both regimes.
        """
        fr = self.froude(h)
        return math.sqrt(fr * fr / (1.0 + fr * fr))
