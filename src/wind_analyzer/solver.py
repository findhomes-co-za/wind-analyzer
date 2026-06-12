"""Three-dimensional mass-consistent diagnostic wind model.

Approach (NUATMOS / MATHEW / WindNinja family):

  1. Fill the domain with the undisturbed inflow profile u0(z).
  2. Zero the velocity on every face that touches terrain (blocking).
  3. Find the smallest adjustment that makes the field divergence-free:

       minimise  J = ∫ alpha1^2 (du^2 + dv^2) + alpha2^2 dw^2  dV
       s.t.      div(u0 + du) = 0

     The Euler-Lagrange equations give  du = dλ/dx, dv = dλ/dy,
     dw = r^2 dλ/dz  with r = alpha1/alpha2, where λ solves the
     anisotropic Poisson equation driven by the divergence of the
     blocked initial field.

The stability ratio r encodes stratification: r -> 1 lets air rise freely
over terrain (neutral); r -> 0 suppresses vertical motion so air is forced
*around* obstacles (stable, low Froude number) - exactly the regime of the
inversion-capped Cape south-easter. Channeling through gaps (Venturi) and
lateral deflection that hugs terrain (Coanda-like attachment) emerge from
mass conservation; no momentum equation is solved, which is the standard
trade-off of diagnostic wind models.

Discretisation: finite volumes on a staggered Cartesian grid with blocked
(solid) cells below terrain, stretched vertical levels, Dirichlet λ=0 on
open lateral/top boundaries (flow-through) and homogeneous Neumann on
terrain (no flux). The SPD system is solved with algebraic multigrid.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp


def build_levels(dz0: float, ratio: float, z_top: float) -> np.ndarray:
    """Geometrically stretched vertical face heights from 0 to >= z_top."""
    faces = [0.0]
    dz = dz0
    while faces[-1] < z_top:
        faces.append(faces[-1] + dz)
        dz *= ratio
    return np.asarray(faces)


@dataclass
class FlowField:
    u: np.ndarray            # (nz, ny, nx) cell-centre eastward velocity
    v: np.ndarray            # (nz, ny, nx) northward
    w: np.ndarray            # (nz, ny, nx) vertical
    fluid: np.ndarray        # (nz, ny, nx) bool, False below terrain
    z_centres: np.ndarray    # (nz,) cell-centre heights ASL
    div_before: float        # max |divergence| of blocked initial field (1/s)
    div_after: float         # max |divergence| after adjustment (1/s)


class MassConsistentSolver:
    def __init__(self, zs: np.ndarray, dx: float, dy: float,
                 z_faces: np.ndarray, alpha_ratio: float = 1.0):
        self.zs = np.asarray(zs, dtype=float)
        self.dx, self.dy = float(dx), float(dy)
        self.zf = np.asarray(z_faces, dtype=float)
        self.zc = 0.5 * (self.zf[1:] + self.zf[:-1])
        self.dz = np.diff(self.zf)
        self.nz = len(self.zc)
        self.ny, self.nx = self.zs.shape
        self.r2 = float(alpha_ratio) ** 2

        if self.zs.max() >= self.zf[-1]:
            raise ValueError("terrain reaches the domain top; raise z_top")

        # Cell is fluid if its centre lies above the terrain surface.
        self.fluid = self.zc[:, None, None] >= self.zs[None, :, :]
        # Open (flux-carrying) faces: both neighbouring cells fluid, or a
        # fluid cell at an open domain boundary (lateral and top).
        f = self.fluid
        nz, ny, nx = self.nz, self.ny, self.nx
        self.fx_open = np.zeros((nz, ny, nx + 1), bool)
        self.fx_open[:, :, 1:nx] = f[:, :, :-1] & f[:, :, 1:]
        self.fx_open[:, :, 0] = f[:, :, 0]
        self.fx_open[:, :, nx] = f[:, :, -1]
        self.fy_open = np.zeros((nz, ny + 1, nx), bool)
        self.fy_open[:, 1:ny, :] = f[:, :-1, :] & f[:, 1:, :]
        self.fy_open[:, 0, :] = f[:, 0, :]
        self.fy_open[:, ny, :] = f[:, -1, :]
        self.fz_open = np.zeros((nz + 1, ny, nx), bool)
        self.fz_open[1:nz] = f[:-1] & f[1:]
        self.fz_open[0] = False                  # ground
        self.fz_open[nz] = f[-1]                 # open top

    # ------------------------------------------------------------------ #

    def initial_faces(self, u_prof: np.ndarray, v_prof: np.ndarray):
        """Face velocities of the inflow, blocked at terrain.

        The profile (sampled at the cell-centre heights, interpreted as
        heights above ground) is applied terrain-following: each column gets
        the profile as a function of height above the LOCAL surface. Without
        this, elevated flat terrain (e.g. the Cape Flats) would inherit the
        faster winds found higher up the inflow profile — a classic
        blocked-cell artefact.
        """
        nz, ny, nx = self.nz, self.ny, self.nx
        zagl = np.maximum(self.zc[:, None, None] - self.zs[None, :, :], self.zc[0])
        u0 = np.interp(zagl, self.zc, u_prof)
        v0 = np.interp(zagl, self.zc, v_prof)
        uf = np.zeros((nz, ny, nx + 1))
        uf[:, :, 1:nx] = 0.5 * (u0[:, :, :-1] + u0[:, :, 1:])
        uf[:, :, 0] = u0[:, :, 0]
        uf[:, :, nx] = u0[:, :, -1]
        vf = np.zeros((nz, ny + 1, nx))
        vf[:, 1:ny, :] = 0.5 * (v0[:, :-1, :] + v0[:, 1:, :])
        vf[:, 0, :] = v0[:, 0, :]
        vf[:, ny, :] = v0[:, -1, :]
        wf = np.zeros((nz + 1, ny, nx))
        uf[~self.fx_open] = 0.0
        vf[~self.fy_open] = 0.0
        wf[~self.fz_open] = 0.0
        return uf, vf, wf

    def _divergence(self, uf, vf, wf) -> np.ndarray:
        """Net outward volume flux of every cell (m^3/s)."""
        Ax = self.dy * self.dz[:, None, None]
        Ay = self.dx * self.dz[:, None, None]
        Az = self.dx * self.dy
        return ((uf[:, :, 1:] - uf[:, :, :-1]) * Ax
                + (vf[:, 1:, :] - vf[:, :-1, :]) * Ay
                + (wf[1:] - wf[:-1]) * Az)

    def _assemble(self):
        """SPD matrix of the anisotropic Poisson equation on fluid cells."""
        nz, ny, nx = self.nz, self.ny, self.nx
        dx, dy, dz, zc, r2 = self.dx, self.dy, self.dz, self.zc, self.r2

        ids = -np.ones((nz, ny, nx), dtype=np.int64)
        nf = int(self.fluid.sum())
        ids[self.fluid] = np.arange(nf)

        rows, cols, vals = [], [], []
        diag = np.zeros(nf)

        def add_internal(mask, id_a, id_b, coeff):
            a, b = id_a[mask], id_b[mask]
            c = coeff[mask] if isinstance(coeff, np.ndarray) else np.full(a.size, coeff)
            rows.append(a); cols.append(b); vals.append(-c)
            rows.append(b); cols.append(a); vals.append(-c)
            np.add.at(diag, a, c)
            np.add.at(diag, b, c)

        # x-direction internal faces
        cx = np.broadcast_to((dy * dz / dx)[:, None, None], (nz, ny, nx - 1))
        m = self.fx_open[:, :, 1:nx]
        add_internal(m, ids[:, :, :-1], ids[:, :, 1:], cx)
        # y-direction internal faces
        cy = np.broadcast_to((dx * dz / dy)[:, None, None], (nz, ny - 1, nx))
        m = self.fy_open[:, 1:ny, :]
        add_internal(m, ids[:, :-1, :], ids[:, 1:, :], cy)
        # z-direction internal faces (distance between cell centres varies)
        dzc = zc[1:] - zc[:-1]
        cz = np.broadcast_to((r2 * dx * dy / dzc)[:, None, None], (nz - 1, ny, nx))
        m = self.fz_open[1:nz]
        add_internal(m, ids[:-1], ids[1:], cz)

        # Open boundary faces: Dirichlet λ=0 at the face (half-cell distance).
        for mask, cell_ids, coeff in (
            (self.fx_open[:, :, 0], ids[:, :, 0], 2 * dy * dz / dx),
            (self.fx_open[:, :, nx], ids[:, :, -1], 2 * dy * dz / dx),
            (self.fy_open[:, 0, :], ids[:, 0, :], 2 * dx * dz / dy),
            (self.fy_open[:, ny, :], ids[:, -1, :], 2 * dx * dz / dy),
        ):
            cb = np.broadcast_to(coeff[:, None], mask.shape)
            np.add.at(diag, cell_ids[mask], cb[mask])
        m = self.fz_open[nz]
        c_top = r2 * dx * dy / (0.5 * dz[-1])
        np.add.at(diag, ids[-1][m], np.full(int(m.sum()), c_top))

        rows.append(np.arange(nf)); cols.append(np.arange(nf)); vals.append(diag)
        A = sp.coo_matrix(
            (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
            shape=(nf, nf),
        ).tocsr()
        return A, ids

    def _solve_poisson(self, A, b, verbose=False) -> np.ndarray:
        bnorm = float(np.linalg.norm(b))
        if bnorm == 0.0:
            return np.zeros_like(b)
        try:
            import pyamg

            ml = pyamg.smoothed_aggregation_solver(A, max_coarse=500)
            x = ml.solve(b, tol=1e-10, accel="cg", maxiter=400)
        except ImportError:
            from scipy.sparse.linalg import LinearOperator, cg

            d = A.diagonal()
            M = LinearOperator(A.shape, matvec=lambda r: r / d)
            x, info = cg(A, b, rtol=1e-8, maxiter=20000, M=M)
            if info != 0:
                raise RuntimeError(f"CG failed to converge (info={info})")
        if verbose:
            res = float(np.linalg.norm(b - A @ x)) / bnorm
            print(f"  Poisson solve: {A.shape[0]} unknowns, rel. residual {res:.2e}")
        return x

    # ------------------------------------------------------------------ #

    def solve(self, u_prof: np.ndarray, v_prof: np.ndarray, verbose: bool = False) -> FlowField:
        nz, ny, nx = self.nz, self.ny, self.nx
        dx, dy, dz, zc, r2 = self.dx, self.dy, self.dz, self.zc, self.r2

        uf, vf, wf = self.initial_faces(u_prof, v_prof)
        div0 = self._divergence(uf, vf, wf)
        cell_vol = (dx * dy * dz)[:, None, None]
        div_before = float(np.abs(div0[self.fluid] / np.broadcast_to(cell_vol, div0.shape)[self.fluid]).max())

        A, ids = self._assemble()
        b = div0[self.fluid]
        lam = self._solve_poisson(A, b, verbose=verbose)

        lam3 = np.zeros((nz, ny, nx))
        lam3[self.fluid] = lam

        # Adjust face velocities with the λ gradient (Dirichlet 0 at open
        # boundary faces, no adjustment across solid faces).
        gx = np.zeros_like(uf)
        gx[:, :, 1:nx] = (lam3[:, :, 1:] - lam3[:, :, :-1]) / dx
        gx[:, :, 0] = (lam3[:, :, 0] - 0.0) / (0.5 * dx)
        gx[:, :, nx] = (0.0 - lam3[:, :, -1]) / (0.5 * dx)
        uf = np.where(self.fx_open, uf + gx, 0.0)

        gy = np.zeros_like(vf)
        gy[:, 1:ny, :] = (lam3[:, 1:, :] - lam3[:, :-1, :]) / dy
        gy[:, 0, :] = (lam3[:, 0, :] - 0.0) / (0.5 * dy)
        gy[:, ny, :] = (0.0 - lam3[:, -1, :]) / (0.5 * dy)
        vf = np.where(self.fy_open, vf + gy, 0.0)

        gz = np.zeros_like(wf)
        dzc = (zc[1:] - zc[:-1])[:, None, None]
        gz[1:nz] = r2 * (lam3[1:] - lam3[:-1]) / dzc
        gz[nz] = r2 * (0.0 - lam3[-1]) / (0.5 * dz[-1])
        wf = np.where(self.fz_open, wf + gz, 0.0)

        div1 = self._divergence(uf, vf, wf)
        div_after = float(np.abs(div1[self.fluid] / np.broadcast_to(cell_vol, div1.shape)[self.fluid]).max())

        u = 0.5 * (uf[:, :, 1:] + uf[:, :, :-1])
        v = 0.5 * (vf[:, 1:, :] + vf[:, :-1, :])
        w = 0.5 * (wf[1:] + wf[:-1])
        for arr in (u, v, w):
            arr[~self.fluid] = np.nan

        return FlowField(u, v, w, self.fluid, self.zc, div_before, div_after)
