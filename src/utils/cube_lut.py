"""Read, write, and attenuate Iridas/Resolve `.cube` 3D LUTs.

Exists to serve one operation the grade loop needs and nothing else has: producing a
*weaker version of the same look*. When numeric image QC reports that a grade bands the
sky or crunches the highlights, the remedy it prints is "reduce the strength" — and
without a way to actually build the reduced LUT, that remedy is advice an agent cannot
take.

## Attenuation is a blend toward identity

`blend_toward_identity(table, size, s)` returns `(1 - s)·identity + s·table`, which is
the same thing a mix/strength control on a LUT node does. The blend happens in the LUT's
own output encoding, not in a perceptual space: a look LUT's entries *are* output values,
and re-encoding them to blend would change the look at s = 1, where the caller asked for
no change at all. The identity endpoint is exact by construction, so s = 0 is a genuine
no-op rather than an almost-no-op.

## What this refuses

1D LUTs (`LUT_1D_SIZE`) parse as a valid `.cube` and are not interchangeable with a 3D
table; they are refused by name rather than silently reshaped. A `DOMAIN_MIN`/`DOMAIN_MAX`
other than 0..1 is carried through untouched, and blending is refused on mismatched
domains, because interpolating between two different input ranges produces a table that
is wrong everywhere without ever looking malformed.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional, Tuple

try:
    import numpy as _np
except ImportError:  # pragma: no cover - guarded by capabilities()
    _np = None  # type: ignore

#: Every entry point that touches an array calls `_require_numpy()` first, so the
#: arithmetic below treats `_np` as present. Declared machine-readably rather than left
#: implied — see tests/test_optional_dependency_guards.py.
_OPTIONAL_DEPENDENCY_CONTRACT = (
    "numpy: every array entry point calls _require_numpy() first; internals assume it is present"
)

MIN_SIZE = 2
MAX_SIZE = 256
DEFAULT_WRITE_SIZE = 33


class CubeLutError(Exception):
    """A `.cube` file that cannot be read, or an operation that cannot be honest."""


def _require_numpy() -> None:
    if _np is None:
        raise CubeLutError("numpy is required for LUT arithmetic (pip install numpy)")


def read_cube(path: str) -> Dict[str, Any]:
    """Parse a 3D `.cube` file into `{size, table, domain_min, domain_max, title}`.

    `table` is an (N**3, 3) float array in the file's own order: red varies fastest,
    then green, then blue. That ordering is the format's, and it is preserved rather
    than normalised so a write-back round-trips byte-for-byte in value terms.
    """
    _require_numpy()
    if not os.path.isfile(path):
        raise CubeLutError(f"LUT not found: {path}")

    size: Optional[int] = None
    title = ""
    domain_min = [0.0, 0.0, 0.0]
    domain_max = [1.0, 1.0, 1.0]
    rows = []

    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            upper = line.upper()
            if upper.startswith("LUT_1D_SIZE"):
                raise CubeLutError(
                    f"{path} is a 1D LUT. A 1D curve and a 3D cube are not "
                    "interchangeable; supply a 3D .cube."
                )
            if upper.startswith("LUT_3D_SIZE"):
                try:
                    size = int(line.split()[1])
                except (IndexError, ValueError):
                    raise CubeLutError(f"{path}:{line_number}: malformed LUT_3D_SIZE")
                if not MIN_SIZE <= size <= MAX_SIZE:
                    raise CubeLutError(
                        f"{path}: LUT_3D_SIZE {size} outside the supported range "
                        f"{MIN_SIZE}-{MAX_SIZE}"
                    )
                continue
            if upper.startswith("TITLE"):
                match = re.match(r'TITLE\s+"?(.*?)"?\s*$', line, re.I)
                title = match.group(1) if match else ""
                continue
            if upper.startswith("DOMAIN_MIN"):
                domain_min = [float(value) for value in line.split()[1:4]]
                continue
            if upper.startswith("DOMAIN_MAX"):
                domain_max = [float(value) for value in line.split()[1:4]]
                continue
            parts = line.split()
            if len(parts) != 3:
                raise CubeLutError(f"{path}:{line_number}: expected 3 values, got {len(parts)}")
            try:
                rows.append([float(value) for value in parts])
            except ValueError:
                raise CubeLutError(f"{path}:{line_number}: non-numeric entry '{line}'")

    if size is None:
        raise CubeLutError(f"{path}: no LUT_3D_SIZE — not a 3D .cube")
    expected = size ** 3
    if len(rows) != expected:
        raise CubeLutError(
            f"{path}: LUT_3D_SIZE {size} needs {expected} entries, found {len(rows)}"
        )
    return {
        "size": size,
        "table": _np.asarray(rows, dtype=_np.float64),
        "domain_min": domain_min,
        "domain_max": domain_max,
        "title": title,
        "path": path,
    }


def write_cube(
    path: str,
    table: "Any",
    size: int,
    *,
    title: str = "",
    domain_min: Optional[list] = None,
    domain_max: Optional[list] = None,
    precision: int = 6,
) -> str:
    """Write a 3D `.cube`. Returns the path written."""
    _require_numpy()
    array = _np.asarray(table, dtype=_np.float64)
    if array.shape != (size ** 3, 3):
        raise CubeLutError(
            f"table shape {array.shape} does not match LUT_3D_SIZE {size} "
            f"(expected {(size ** 3, 3)})"
        )
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    lines = []
    if title:
        lines.append(f'TITLE "{title}"')
    lines.append(f"LUT_3D_SIZE {size}")
    if domain_min and list(domain_min) != [0.0, 0.0, 0.0]:
        lines.append("DOMAIN_MIN " + " ".join(f"{value:.6f}" for value in domain_min))
    if domain_max and list(domain_max) != [1.0, 1.0, 1.0]:
        lines.append("DOMAIN_MAX " + " ".join(f"{value:.6f}" for value in domain_max))
    lines.append("")
    for row in array:
        lines.append(" ".join(f"{value:.{precision}f}" for value in row))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def identity_table(size: int) -> "Any":
    """The pass-through table for a cube of this size, in red-fastest order."""
    _require_numpy()
    if not MIN_SIZE <= size <= MAX_SIZE:
        raise CubeLutError(f"size {size} outside {MIN_SIZE}-{MAX_SIZE}")
    axis = _np.linspace(0.0, 1.0, size)
    # Red fastest, then green, then blue — index = r + g*N + b*N*N.
    blue, green, red = _np.meshgrid(axis, axis, axis, indexing="ij")
    return _np.stack([red.ravel(), green.ravel(), blue.ravel()], axis=1)


def blend_toward_identity(table: "Any", size: int, strength: float) -> "Any":
    """`(1 - strength)·identity + strength·table`, clamped to [0, 1] strength.

    strength 1.0 returns the table unchanged (not merely close to it), and 0.0 returns
    exact identity. Values between are the same attenuation a LUT mix control applies.
    """
    _require_numpy()
    amount = float(min(1.0, max(0.0, strength)))
    array = _np.asarray(table, dtype=_np.float64)
    if amount == 1.0:
        return array.copy()
    identity = identity_table(size)
    if amount == 0.0:
        return identity
    return (1.0 - amount) * identity + amount * array


def attenuate_file(
    source_lut: str,
    strength: float,
    out_path: str,
    *,
    title_suffix: Optional[str] = None,
) -> Dict[str, Any]:
    """Read a `.cube`, blend it toward identity, write the result. Returns a summary."""
    parsed = read_cube(source_lut)
    if parsed["domain_min"] != [0.0, 0.0, 0.0] or parsed["domain_max"] != [1.0, 1.0, 1.0]:
        # Identity is only identity on a 0..1 domain. Blending against it on a scaled
        # domain silently produces a table that is wrong across the whole range.
        raise CubeLutError(
            f"{source_lut} declares a non-unit domain "
            f"({parsed['domain_min']}..{parsed['domain_max']}); attenuation toward "
            "identity is only defined on 0..1"
        )
    blended = blend_toward_identity(parsed["table"], parsed["size"], strength)
    suffix = title_suffix if title_suffix is not None else f" @ {round(float(strength), 3)}"
    write_cube(
        out_path,
        blended,
        parsed["size"],
        title=(parsed["title"] or os.path.splitext(os.path.basename(source_lut))[0]) + suffix,
    )
    return {
        "path": out_path,
        "size": parsed["size"],
        "strength": round(float(min(1.0, max(0.0, strength))), 4),
        "source_lut": source_lut,
    }


def sample(table: "Any", size: int, rgb: "Any") -> "Any":
    """Trilinearly interpolate the table at RGB inputs in [0, 1].

    Present so the blending maths can be unit-tested without shelling out to ffmpeg.
    The real pixel path is ffmpeg's `lut3d`, and that stays the measurement of record —
    LUT interpolation and encode rounding are where banding is actually introduced.
    """
    _require_numpy()
    array = _np.asarray(table, dtype=_np.float64).reshape(size, size, size, 3)
    points = _np.clip(_np.atleast_2d(_np.asarray(rgb, dtype=_np.float64)), 0.0, 1.0)
    scaled = points * (size - 1)
    low = _np.floor(scaled).astype(int)
    high = _np.minimum(low + 1, size - 1)
    frac = scaled - low

    out = _np.zeros((points.shape[0], 3), dtype=_np.float64)
    for corner in range(8):
        red_hi, green_hi, blue_hi = (corner >> 0) & 1, (corner >> 1) & 1, (corner >> 2) & 1
        weight = (
            (frac[:, 0] if red_hi else 1 - frac[:, 0])
            * (frac[:, 1] if green_hi else 1 - frac[:, 1])
            * (frac[:, 2] if blue_hi else 1 - frac[:, 2])
        )
        # Indexed [blue][green][red] because red varies fastest in the file order.
        corner_values = array[
            high[:, 2] if blue_hi else low[:, 2],
            high[:, 1] if green_hi else low[:, 1],
            high[:, 0] if red_hi else low[:, 0],
        ]
        out += weight[:, None] * corner_values
    return out


def capabilities() -> Dict[str, Any]:
    return {
        "numpy_available": _np is not None,
        "supported": "3D .cube (Iridas/Resolve)",
        "refused": "1D .cube; attenuation on a non-unit DOMAIN_MIN/MAX",
        "size_range": [MIN_SIZE, MAX_SIZE],
    }
