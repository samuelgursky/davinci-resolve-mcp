"""Display-referred colour science: sRGB ↔ linear ↔ XYZ ↔ CIE Lab (D65), ΔE2000.

Pure numpy, no third-party colour library, so the conversions can be unit-tested
against published reference values rather than trusted.

Everything here is **display-referred**. RGB is float in [0, 1] with an sRGB
transfer function; Lab is L* in [0, 100] with a/b roughly [-128, 128]. Feeding
log or scene-referred RGB (ACEScct, S-Log3, LogC) through these functions
produces numbers that look plausible and mean nothing — `image_qc` is the layer
that refuses that case, and it refuses rather than converting silently because
the correct conversion depends on a transform this module cannot know.

ΔE2000 is implemented rather than ΔE76 because ΔE76 badly under-weights hue
error in the blues and over-weights chroma error in saturated colours, and any
number a human reads as "how close is this" should not carry that distortion.
The implementation is validated against the Sharma/Wu/Dalal (2005) test set,
which is specifically constructed to exercise the hue-rotation and chroma
discontinuities where naive implementations disagree.
"""

from __future__ import annotations

import numpy as np

# sRGB (IEC 61966-2-1) companding thresholds.
_SRGB_THRESH = 0.04045
_SRGB_LIN_THRESH = 0.0031308

# sRGB primaries → XYZ (D65).
_RGB2XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)
_XYZ2RGB = np.linalg.inv(_RGB2XYZ)

#: D65 reference white, derived from the matrix rather than quoted.
#:
#: The usual rounded literal [0.95047, 1.0, 1.08883] is *not* exactly the white
#: this matrix produces from RGB 1,1,1 — they disagree in the 6th decimal, which
#: leaves sRGB white landing at L* = 100.0000039 with a non-zero a*/b*. Deriving
#: it keeps the two constants consistent by construction, so white is exactly
#: neutral and the Lab round-trip closes.
_D65 = _RGB2XYZ @ np.ones(3, dtype=np.float64)

# CIE Lab constants, in the exact-rational form (CIE 15:2004) rather than the
# rounded 0.008856 / 903.3 that older references use — the rounded pair puts a
# small discontinuity at the linear/cube-root join.
_LAB_EPS = 216.0 / 24389.0  # (6/29)^3
_LAB_KAPPA = 24389.0 / 27.0  # (29/3)^3


def srgb_to_linear(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.float64)
    return np.where(rgb <= _SRGB_THRESH, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(rgb: np.ndarray) -> np.ndarray:
    rgb = np.asarray(rgb, dtype=np.float64)
    return np.where(
        rgb <= _SRGB_LIN_THRESH,
        rgb * 12.92,
        1.055 * np.power(np.clip(rgb, 0.0, None), 1.0 / 2.4) - 0.055,
    )


def linear_to_xyz(rgb_lin: np.ndarray) -> np.ndarray:
    return np.asarray(rgb_lin, dtype=np.float64) @ _RGB2XYZ.T


def xyz_to_linear(xyz: np.ndarray) -> np.ndarray:
    return np.asarray(xyz, dtype=np.float64) @ _XYZ2RGB.T


def _f_forward(t: np.ndarray) -> np.ndarray:
    return np.where(t > _LAB_EPS, np.cbrt(t), (_LAB_KAPPA * t + 16.0) / 116.0)


def _f_inverse(f: np.ndarray) -> np.ndarray:
    f3 = f**3
    return np.where(f3 > _LAB_EPS, f3, (116.0 * f - 16.0) / _LAB_KAPPA)


def xyz_to_lab(xyz: np.ndarray) -> np.ndarray:
    scaled = np.asarray(xyz, dtype=np.float64) / _D65
    fx, fy, fz = (_f_forward(scaled[..., i]) for i in range(3))
    return np.stack([116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)], axis=-1)


def lab_to_xyz(lab: np.ndarray) -> np.ndarray:
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16.0) / 116.0
    fx = fy + lab[..., 1] / 500.0
    fz = fy - lab[..., 2] / 200.0
    return np.stack([_f_inverse(fx) * _D65[0], _f_inverse(fy) * _D65[1], _f_inverse(fz) * _D65[2]], axis=-1)


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    return xyz_to_lab(linear_to_xyz(srgb_to_linear(rgb)))


def lab_to_srgb(lab: np.ndarray, *, clip: bool = True) -> np.ndarray:
    rgb = linear_to_srgb(xyz_to_linear(lab_to_xyz(lab)))
    return np.clip(rgb, 0.0, 1.0) if clip else rgb


def delta_e76(lab_a: np.ndarray, lab_b: np.ndarray) -> np.ndarray:
    """Plain Euclidean distance in Lab. Kept for cheap internal comparisons only.

    Not for anything a human reads as a quality figure — use `delta_e2000`.
    """
    a = np.asarray(lab_a, dtype=np.float64)
    b = np.asarray(lab_b, dtype=np.float64)
    return np.sqrt(np.sum((a - b) ** 2, axis=-1))


def delta_e2000(
    lab_a: np.ndarray, lab_b: np.ndarray, *, k_l: float = 1.0, k_c: float = 1.0, k_h: float = 1.0
) -> np.ndarray:
    """CIEDE2000 colour difference (CIE 142:2001).

    Validated against the Sharma/Wu/Dalal (2005) test set — see
    `tests/test_colorimetry.py`. The awkward parts are the two hue-difference
    branches, which must use the 180°/360° wrap conventions exactly as specified;
    getting them subtly wrong still passes most casual test pairs.
    """
    a = np.asarray(lab_a, dtype=np.float64)
    b = np.asarray(lab_b, dtype=np.float64)
    l1, a1, b1 = a[..., 0], a[..., 1], a[..., 2]
    l2, a2, b2 = b[..., 0], b[..., 1], b[..., 2]

    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    g = 0.5 * (1.0 - np.sqrt(c_bar**7 / (c_bar**7 + 25.0**7)))

    a1p, a2p = (1.0 + g) * a1, (1.0 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)

    # Hue angles in degrees; undefined (0) when chroma is zero, per the standard.
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0
    h1p = np.where(c1p == 0, 0.0, h1p)
    h2p = np.where(c2p == 0, 0.0, h2p)

    dlp = l2 - l1
    dcp = c2p - c1p

    # Δh′: zero when either chroma is zero, else wrapped to (-180, 180].
    dhp = h2p - h1p
    dhp = np.where(dhp > 180.0, dhp - 360.0, dhp)
    dhp = np.where(dhp < -180.0, dhp + 360.0, dhp)
    dhp = np.where(c1p * c2p == 0, 0.0, dhp)
    dhp_term = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dhp) / 2.0)

    lp_bar = (l1 + l2) / 2.0
    cp_bar = (c1p + c2p) / 2.0

    # H̄′: the mean hue, which needs the wrap handled separately from Δh′ — the
    # sum/2 convention differs from the difference convention above.
    h_sum = h1p + h2p
    h_abs = np.abs(h1p - h2p)
    hp_bar = np.where(
        c1p * c2p == 0,
        h_sum,
        np.where(
            h_abs <= 180.0,
            h_sum / 2.0,
            np.where(h_sum < 360.0, (h_sum + 360.0) / 2.0, (h_sum - 360.0) / 2.0),
        ),
    )

    t = (
        1.0
        - 0.17 * np.cos(np.radians(hp_bar - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * hp_bar))
        + 0.32 * np.cos(np.radians(3.0 * hp_bar + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * hp_bar - 63.0))
    )

    d_theta = 30.0 * np.exp(-(((hp_bar - 275.0) / 25.0) ** 2))
    r_c = 2.0 * np.sqrt(cp_bar**7 / (cp_bar**7 + 25.0**7))
    s_l = 1.0 + (0.015 * (lp_bar - 50.0) ** 2) / np.sqrt(20.0 + (lp_bar - 50.0) ** 2)
    s_c = 1.0 + 0.045 * cp_bar
    s_h = 1.0 + 0.015 * cp_bar * t
    r_t = -np.sin(np.radians(2.0 * d_theta)) * r_c

    return np.sqrt(
        (dlp / (k_l * s_l)) ** 2
        + (dcp / (k_c * s_c)) ** 2
        + (dhp_term / (k_h * s_h)) ** 2
        + r_t * (dcp / (k_c * s_c)) * (dhp_term / (k_h * s_h))
    )
