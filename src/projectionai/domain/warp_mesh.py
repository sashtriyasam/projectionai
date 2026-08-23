"""WarpMesh — canonical projection-mapping warp mesh domain type.

A WarpMesh encodes the per-vertex mapping from SURFACE_LOCAL geometry
to PROJECTOR output space.  Each vertex carries:

- ``position``: SURFACE_LOCAL coordinate (meters, origin at surface centre)
- ``projector_uv``: PROJECTOR_UV [0,1] (where this vertex lands on the
  projector output — origin top-left, V down)
- ``content_uv``: SOURCE/CONTENT UV [0,1] (where to sample the source
  texture — surface UV convention, origin bottom-left, V up)

Triangle indices define the mesh topology.

Coordinate Conventions
======================

- SURFACE_LOCAL: X right, Y up, Z out (right-handed, meters)
- PROJECTOR_UV: [0,1]x[0,1], origin top-left, V down (image convention)
- CONTENT_UV: [0,1]x[0,1], origin bottom-left, V up (OpenGL / surface UV)

Design Decision
===============

A dedicated ``WarpMesh`` type is used instead of reusing ``geometry.Mesh``
because the warp mesh carries projection-mapping-specific semantics
(surface/projector references, grid dimensions, generation method) that
``Mesh`` does not express.  ``WarpMesh.to_geometry_mesh()`` produces a
standard ``Mesh`` for downstream GPU upload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

import numpy as np
from numpy.typing import NDArray

# =============================================================================
# Generation method
# =============================================================================


class WarpMeshGeneration(StrEnum):
    """How the warp mesh was produced."""

    GRID = "grid"  # Regular grid subdivision
    EXPLICIT = "explicit"  # Explicitly provided vertices
    CALIBRATION = "calibration"  # From calibration pipeline
    IMPORTED = "imported"  # From external file


# =============================================================================
# WarpMesh
# =============================================================================


def _array_eq(
    a: NDArray[np.floating[Any]] | NDArray[np.integer[Any]] | None,
    b: NDArray[np.floating[Any]] | NDArray[np.integer[Any]] | None,
) -> bool:
    """Compare two optional NumPy arrays."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return bool(np.array_equal(a, b))


@dataclass(frozen=True, eq=False)
class WarpMesh:
    """Projection-mapping warp mesh.

    Each vertex maps a SURFACE_LOCAL position to a PROJECTOR_UV location
    and a CONTENT_UV texture coordinate.

    Parameters
    ----------
    surface_id : str
        Stable reference to the ``ConfiguredSurface``.
    projector_id : str
        Stable reference to the ``ProjectorModel``.
    vertices : NDArray[np.float64]
        ``(V, 3)`` surface-local vertex positions (meters).
    projector_uvs : NDArray[np.float64]
        ``(V, 2)`` PROJECTOR_UV coordinates [0,1].
    content_uvs : NDArray[np.float64]
        ``(V, 2)`` SOURCE/CONTENT UV [0,1] (surface UV convention).
    indices : NDArray[np.int32]
        ``(F, 3)`` triangle indices.
    grid_rows : int
        Number of grid rows (1 for non-grid meshes).
    grid_cols : int
        Number of grid columns (1 for non-grid meshes).
    generation_method : WarpMeshGeneration
        How the mesh was produced.
    metadata : dict[str, Any]
        Arbitrary metadata (serialisation info, etc.).
    """

    surface_id: str = ""
    projector_id: str = ""
    vertices: NDArray[np.float64] = field(
        default_factory=lambda: np.zeros((0, 3), dtype=np.float64)
    )
    projector_uvs: NDArray[np.float64] = field(
        default_factory=lambda: np.zeros((0, 2), dtype=np.float64)
    )
    content_uvs: NDArray[np.float64] = field(
        default_factory=lambda: np.zeros((0, 2), dtype=np.float64)
    )
    indices: NDArray[np.int32] = field(
        default_factory=lambda: np.zeros((0, 3), dtype=np.int32)
    )
    grid_rows: int = 1
    grid_cols: int = 1
    generation_method: WarpMeshGeneration = WarpMeshGeneration.GRID
    metadata: dict[str, Any] = field(default_factory=dict)

    # -- Derived properties ---------------------------------------------------

    @property
    def num_vertices(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def num_faces(self) -> int:
        return int(self.indices.shape[0])

    @property
    def has_content(self) -> bool:
        return self.num_vertices > 0 and self.num_faces > 0

    # -- Validation -----------------------------------------------------------

    def validate(self) -> list[str]:
        """Return a list of validation error strings (empty = valid)."""
        errors: list[str] = []

        if self.vertices.ndim != 2 or self.vertices.shape[1] != 3:
            errors.append(f"vertices must be (V, 3), got {self.vertices.shape}")
            return errors  # Can't check the rest

        v = self.num_vertices
        f = self.num_faces

        if self.projector_uvs.shape != (v, 2):
            errors.append(f"projector_uvs shape {self.projector_uvs.shape} != ({v}, 2)")
        if self.content_uvs.shape != (v, 2):
            errors.append(f"content_uvs shape {self.content_uvs.shape} != ({v}, 2)")
        if self.indices.ndim != 2 or self.indices.shape[1] != 3:
            errors.append(f"indices must be (F, 3), got {self.indices.shape}")
            return errors

        # UV range checks
        pu = self.projector_uvs
        cu = self.content_uvs
        if pu.size > 0 and (float(pu.min()) < -1e-6 or float(pu.max()) > 1.0 + 1e-6):
            errors.append(
                f"projector_uvs out of [0,1]: "
                f"[{float(pu.min()):.6f}, {float(pu.max()):.6f}]"
            )
        if cu.size > 0 and (float(cu.min()) < -1e-6 or float(cu.max()) > 1.0 + 1e-6):
            errors.append(
                f"content_uvs out of [0,1]: "
                f"[{float(cu.min()):.6f}, {float(cu.max()):.6f}]"
            )

        # Index bounds
        if f > 0:
            max_idx = int(self.indices.max())
            min_idx = int(self.indices.min())
            if min_idx < 0 or max_idx >= v:
                errors.append(
                    f"indices range [{min_idx}, {max_idx}] "
                    f"out of vertex range [0, {v - 1}]"
                )

        return errors

    # -- Conversion to geometry.Mesh ------------------------------------------

    def to_geometry_mesh(self) -> Any:
        """Convert to a ``geometry.Mesh`` for downstream GPU upload.

        The returned mesh uses ``projector_uvs`` as ``uv_coords`` so
        the GPU path can interpolate the projector-space location.
        """
        from projectionai.domain.geometry import Mesh

        return Mesh(
            vertices=self.vertices.astype(np.float64),
            faces=self.indices.astype(np.int32),
            uv_coords=self.projector_uvs.astype(np.float64),
        )

    # -- Serialisation --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-compatible dict."""
        return {
            "surface_id": self.surface_id,
            "projector_id": self.projector_id,
            "vertices": self.vertices.tolist(),
            "projector_uvs": self.projector_uvs.tolist(),
            "content_uvs": self.content_uvs.tolist(),
            "indices": self.indices.tolist(),
            "grid_rows": self.grid_rows,
            "grid_cols": self.grid_cols,
            "generation_method": self.generation_method.value,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> WarpMesh:
        """Deserialise from a dict."""
        return WarpMesh(
            surface_id=data.get("surface_id", ""),
            projector_id=data.get("projector_id", ""),
            vertices=np.array(data["vertices"], dtype=np.float64),
            projector_uvs=np.array(data["projector_uvs"], dtype=np.float64),
            content_uvs=np.array(data["content_uvs"], dtype=np.float64),
            indices=np.array(data["indices"], dtype=np.int32),
            grid_rows=data.get("grid_rows", 1),
            grid_cols=data.get("grid_cols", 1),
            generation_method=WarpMeshGeneration(data.get("generation_method", "grid")),
            metadata=data.get("metadata", {}),
        )

    # -- Equality (NumPy arrays) ----------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WarpMesh):
            return NotImplemented
        return (
            self.surface_id == other.surface_id
            and self.projector_id == other.projector_id
            and _array_eq(self.vertices, other.vertices)
            and _array_eq(self.projector_uvs, other.projector_uvs)
            and _array_eq(self.content_uvs, other.content_uvs)
            and _array_eq(self.indices, other.indices)
            and self.grid_rows == other.grid_rows
            and self.grid_cols == other.grid_cols
            and self.generation_method == other.generation_method
            and self.metadata == other.metadata
        )

    __hash__: ClassVar[None] = None  # type: ignore[assignment]


# =============================================================================
# Factory: planar grid warp mesh
# =============================================================================


def create_planar_grid_warp_mesh(
    surface_id: str,
    projector_id: str,
    width_m: float,
    height_m: float,
    grid_rows: int,
    grid_cols: int,
    projector_uv_corners: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ],
    generation_method: WarpMeshGeneration = WarpMeshGeneration.GRID,
    metadata: dict[str, Any] | None = None,
    projector_uvs_full: NDArray[np.float64] | None = None,
) -> WarpMesh:
    """Create a planar grid warp mesh from surface dimensions and UV corners.

    Parameters
    ----------
    surface_id, projector_id : str
        Stable references.
    width_m, height_m : float
        Physical surface dimensions (meters).
    grid_rows, grid_cols : int
        Grid subdivisions.  Vertices = (rows+1) x (cols+1).
    projector_uv_corners : tuple of 4 (u, v) tuples
        PROJECTOR_UV for each surface corner in order:
        bottom-left, bottom-right, top-right, top-left.
    generation_method : WarpMeshGeneration
    metadata : dict or None
    projector_uvs_full : NDArray of shape ((rows+1)*(cols+1), 2), optional
        Pre-computed per-vertex projector UVs.  When provided, overrides
        bilinear interpolation of corners — enables perspective-correct
        mapping for off-axis projectors.
    """
    if grid_rows < 1 or grid_cols < 1:
        raise ValueError(
            f"grid_rows and grid_cols must be >= 1, "
            f"got rows={grid_rows}, cols={grid_cols}"
        )

    rows = grid_rows
    cols = grid_cols
    expected_verts = (rows + 1) * (cols + 1)

    if projector_uvs_full is not None:
        if projector_uvs_full.shape != (expected_verts, 2):
            raise ValueError(
                f"projector_uvs_full must have shape ({expected_verts}, 2), "
                f"got {projector_uvs_full.shape}"
            )
        if not np.all(np.isfinite(projector_uvs_full)):
            raise ValueError("projector_uvs_full contains non-finite values")

    for i, corner in enumerate(projector_uv_corners):
        if not all(np.isfinite(v) for v in corner):
            raise ValueError(
                f"projector_uv_corners[{i}] contains non-finite values: {corner}"
            )

    # Surface-local vertex positions (origin at centre, X right, Y up)
    hw = width_m * 0.5
    hh = height_m * 0.5
    vertices = np.zeros(((rows + 1) * (cols + 1), 3), dtype=np.float64)
    content_uvs = np.zeros(((rows + 1) * (cols + 1), 2), dtype=np.float64)
    projector_uvs = np.zeros(((rows + 1) * (cols + 1), 2), dtype=np.float64)

    # Unpack corner projector UVs (BL, BR, TR, TL) — used only when
    # projector_uvs_full is not provided (bilinear fallback).
    pu_bl, pu_br, pu_tr, pu_tl = projector_uv_corners

    idx = 0
    for r in range(rows + 1):
        for c in range(cols + 1):
            # Parametric [0,1] across the grid
            s = c / cols  # horizontal (left→right)
            t = r / rows  # vertical (bottom→top)

            # Surface-local position
            vertices[idx, 0] = -hw + s * width_m  # X: -hw → +hw
            vertices[idx, 1] = -hh + t * height_m  # Y: -hh → +hh
            # Z = 0 (planar)

            # Content UV (surface UV convention: origin bottom-left, V up)
            content_uvs[idx, 0] = s
            content_uvs[idx, 1] = t

            # Projector UV: use pre-computed per-vertex values when available,
            # otherwise fall back to bilinear interpolation of corners.
            if projector_uvs_full is not None:
                projector_uvs[idx, 0] = projector_uvs_full[idx, 0]
                projector_uvs[idx, 1] = projector_uvs_full[idx, 1]
            else:
                projector_uvs[idx, 0] = (
                    (1 - s) * (1 - t) * pu_bl[0]
                    + s * (1 - t) * pu_br[0]
                    + s * t * pu_tr[0]
                    + (1 - s) * t * pu_tl[0]
                )
                projector_uvs[idx, 1] = (
                    (1 - s) * (1 - t) * pu_bl[1]
                    + s * (1 - t) * pu_br[1]
                    + s * t * pu_tr[1]
                    + (1 - s) * t * pu_tl[1]
                )

            idx += 1

    # Triangle indices (grid triangulation)
    tris: list[list[int]] = []
    for r in range(rows):
        for c in range(cols):
            v00 = r * (cols + 1) + c
            v10 = v00 + 1
            v01 = (r + 1) * (cols + 1) + c
            v11 = v01 + 1
            tris.append([v00, v10, v11])
            tris.append([v00, v11, v01])

    indices = np.array(tris, dtype=np.int32)

    if not np.all(np.isfinite(vertices)):
        raise ValueError("Computed vertices contain non-finite values")
    if not np.all(np.isfinite(content_uvs)):
        raise ValueError("Computed content_uvs contain non-finite values")
    if not np.all(np.isfinite(projector_uvs)):
        raise ValueError("Computed projector_uvs contain non-finite values")

    return WarpMesh(
        surface_id=surface_id,
        projector_id=projector_id,
        vertices=vertices,
        projector_uvs=projector_uvs,
        content_uvs=content_uvs,
        indices=indices,
        grid_rows=rows,
        grid_cols=cols,
        generation_method=generation_method,
        metadata=metadata or {},
    )


def create_identity_warp_mesh(
    width: int,
    height: int,
    grid_rows: int = 1,
    grid_cols: int = 1,
) -> WarpMesh:
    """Create an identity warp mesh (source == output).

    For a source image of size ``width x height``, the identity mesh
    maps every pixel to itself.

    Content UVs == Projector UVs == pixel coordinates normalised to [0,1].

    Used for Section 4 (planar reference case) testing.
    """
    # Content UV and projector UV are the same for identity
    # Corners: BL=(0,1), BR=(1,1), TR=(1,0), TL=(0,0)
    # (content UV convention: V up; projector UV convention: V down)
    # For identity: content UV at surface UV (s, t) = (s, t)
    #               projector UV at same point = (s, 1-t) (V-flip)
    # So identity means projector UV = (s, 1-t), content UV = (s, t)

    mesh = create_planar_grid_warp_mesh(
        surface_id="identity_surface",
        projector_id="identity_projector",
        width_m=float(width),
        height_m=float(height),
        grid_rows=grid_rows,
        grid_cols=grid_cols,
        projector_uv_corners=(
            (0.0, 1.0),  # BL → projector (0,1)
            (1.0, 1.0),  # BR → projector (1,1)
            (1.0, 0.0),  # TR → projector (1,0)
            (0.0, 0.0),  # TL → projector (0,0)
        ),
        generation_method=WarpMeshGeneration.EXPLICIT,
    )
    return mesh
