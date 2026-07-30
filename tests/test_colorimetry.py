"""Tests for src/utils/colorimetry.py — validated against published references.

Colour conversions are the kind of code that looks right and is quietly wrong,
so nothing here asserts against our own output. Lab values come from the CIE
definition; the ΔE2000 pairs are the Sharma/Wu/Dalal (2005) test set, which is
built specifically to catch implementations that fumble the hue-angle wrap.
"""

from __future__ import annotations

import unittest

import numpy as np

from src.utils import colorimetry as cm


class TransferFunctionTests(unittest.TestCase):
    def test_srgb_round_trip_is_lossless(self) -> None:
        values = np.linspace(0.0, 1.0, 257).reshape(-1, 1).repeat(3, axis=1)
        back = cm.linear_to_srgb(cm.srgb_to_linear(values))
        np.testing.assert_allclose(back, values, atol=1e-12)

    def test_companding_joins_continuously_at_the_threshold(self) -> None:
        # The piecewise join is where a mistyped constant shows up.
        below = cm.srgb_to_linear(np.array([cm._SRGB_THRESH - 1e-9]))
        above = cm.srgb_to_linear(np.array([cm._SRGB_THRESH + 1e-9]))
        self.assertAlmostEqual(float(below[0]), float(above[0]), places=7)

    def test_known_srgb_midpoint(self) -> None:
        # 0.5 sRGB is ~0.2140 linear; a wrong exponent moves this visibly.
        self.assertAlmostEqual(float(cm.srgb_to_linear(np.array([0.5]))[0]), 0.21404114, places=7)


class LabConversionTests(unittest.TestCase):
    def test_d65_white_is_exactly_l100_neutral(self) -> None:
        # Exact, not approximate: the white point is derived from the matrix, so
        # any drift here means the two constants have gone out of sync again.
        lab = cm.srgb_to_lab(np.array([[1.0, 1.0, 1.0]]))[0]
        self.assertAlmostEqual(lab[0], 100.0, places=10)
        self.assertAlmostEqual(lab[1], 0.0, places=10)
        self.assertAlmostEqual(lab[2], 0.0, places=10)

    def test_neutral_greys_stay_neutral(self) -> None:
        greys = np.linspace(0.0, 1.0, 32).reshape(-1, 1).repeat(3, axis=1)
        lab = cm.srgb_to_lab(greys)
        np.testing.assert_allclose(lab[..., 1], 0.0, atol=1e-10)
        np.testing.assert_allclose(lab[..., 2], 0.0, atol=1e-10)

    def test_black_is_l0(self) -> None:
        lab = cm.srgb_to_lab(np.array([[0.0, 0.0, 0.0]]))[0]
        self.assertAlmostEqual(lab[0], 0.0, places=6)

    def test_mid_grey_lands_near_l53(self) -> None:
        # sRGB 0.5 → L* ≈ 53.39, the standard published value.
        lab = cm.srgb_to_lab(np.array([[0.5, 0.5, 0.5]]))[0]
        self.assertAlmostEqual(lab[0], 53.3890, places=3)

    def test_lab_round_trip_over_the_cube(self) -> None:
        rng = np.random.default_rng(0)
        rgb = rng.random((512, 3))
        np.testing.assert_allclose(cm.lab_to_srgb(cm.srgb_to_lab(rgb)), rgb, atol=1e-9)

    def test_round_trip_holds_across_the_lab_linear_branch(self) -> None:
        # Deep shadows exercise the kappa branch of f(); a rounded epsilon shows here.
        rgb = np.linspace(0.0, 0.02, 64).reshape(-1, 1).repeat(3, axis=1)
        np.testing.assert_allclose(cm.lab_to_srgb(cm.srgb_to_lab(rgb)), rgb, atol=1e-9)


class DeltaE2000ReferenceTests(unittest.TestCase):
    """Sharma, Wu & Dalal (2005), 'The CIEDE2000 Color-Difference Formula'.

    These pairs are chosen to sit on the discontinuities — hue wrap around 0/360,
    the 275° rotation term, and near-zero chroma. An implementation that averages
    hue naively passes the easy pairs and fails several of these.
    """

    # (Lab1, Lab2, expected ΔE00)
    CASES = [
        ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
        ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
        ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
        ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
        ((50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
        ((50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
        ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
        ((50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
        ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
        ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0010), 7.1792),
        ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0011), 7.2195),
        ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0012), 7.2195),
        ((50.0000, -0.0010, 2.4900), (50.0000, 0.0009, -2.4900), 4.8045),
        ((50.0000, -0.0010, 2.4900), (50.0000, 0.0011, -2.4900), 4.7461),
        ((50.0000, 2.5000, 0.0000), (50.0000, 0.0000, -2.5000), 4.3065),
        ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
        ((50.0000, 2.5000, 0.0000), (61.0000, -5.0000, 29.0000), 22.8977),
        ((50.0000, 2.5000, 0.0000), (56.0000, -27.0000, -3.0000), 31.9030),
        ((50.0000, 2.5000, 0.0000), (58.0000, 24.0000, 15.0000), 19.4535),
        ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
        ((50.0000, 2.5000, 0.0000), (50.0000, 3.2972, 0.0000), 1.0000),
        ((50.0000, 2.5000, 0.0000), (50.0000, 1.8634, 0.5757), 1.0000),
        ((50.0000, 2.5000, 0.0000), (50.0000, 3.2592, 0.3350), 1.0000),
        ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
        ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
        ((61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
        ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
        ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
        ((36.4612, 47.8580, 18.3852), (36.2715, 50.5065, 21.2231), 1.4146),
        ((90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
        ((90.9257, -0.5406, -0.9208), (88.6381, -0.8985, -0.7239), 1.5381),
        ((6.7747, -0.2908, -2.4247), (5.8714, -0.0985, -2.2286), 0.6377),
        ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
    ]

    def test_matches_the_published_values(self) -> None:
        for lab1, lab2, expected in self.CASES:
            with self.subTest(lab1=lab1, lab2=lab2):
                got = float(cm.delta_e2000(np.array(lab1), np.array(lab2)))
                self.assertAlmostEqual(got, expected, places=4)

    def test_is_symmetric(self) -> None:
        for lab1, lab2, _ in self.CASES:
            with self.subTest(lab1=lab1):
                forward = float(cm.delta_e2000(np.array(lab1), np.array(lab2)))
                back = float(cm.delta_e2000(np.array(lab2), np.array(lab1)))
                self.assertAlmostEqual(forward, back, places=10)

    def test_identical_colours_are_zero(self) -> None:
        lab = np.array([52.1, -13.4, 27.9])
        self.assertAlmostEqual(float(cm.delta_e2000(lab, lab)), 0.0, places=12)

    def test_vectorises_over_image_arrays(self) -> None:
        a = np.zeros((4, 5, 3))
        b = np.zeros((4, 5, 3))
        a[..., 0], b[..., 0] = 50.0, 50.0
        a[..., 1], b[..., 2] = 2.5, -2.5
        result = cm.delta_e2000(a, b)
        self.assertEqual(result.shape, (4, 5))
        np.testing.assert_allclose(result, 4.3065, atol=1e-4)

    def test_differs_from_delta_e76_where_it_should(self) -> None:
        # The blue pair ΔE76 badly overstates — the reason we do not ship ΔE76.
        lab1, lab2 = np.array([50.0, 2.6772, -79.7751]), np.array([50.0, 0.0, -82.7485])
        self.assertAlmostEqual(float(cm.delta_e2000(lab1, lab2)), 2.0425, places=4)
        self.assertGreater(float(cm.delta_e76(lab1, lab2)), 4.0)


if __name__ == "__main__":
    unittest.main()
