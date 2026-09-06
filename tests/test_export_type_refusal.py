"""export_timeline_checked refuses unresolved export constants loudly (E105).

Measured: a made-up EXPORT_CMX_3600 reached Timeline.Export as a string and
came back as a bare success:false with no reason; the real constant is
EXPORT_EDL. Offline: the Resolve object is stubbed without the constant.
"""

import unittest

import src.server as compound


class _Tl:
    def Export(self, *a):  # pragma: no cover - must not be reached
        raise AssertionError("Export must not be called with an unresolved constant")


class _NoConstResolve:
    # A build that DOES expose the export vocabulary — just not the made-up name.
    EXPORT_OTIO = 7
    EXPORT_EDL = 1
    EXPORT_NONE = 0


class ExportTypeRefusalTest(unittest.TestCase):
    def setUp(self):
        self._orig = compound.get_resolve
        compound.get_resolve = lambda: _NoConstResolve()

    def tearDown(self):
        compound.get_resolve = self._orig

    def test_unknown_constant_refuses_with_vocabulary(self):
        out = compound._export_timeline_checked(_Tl(), {
            "path": "/tmp/x.edl", "require_temp_path": False, "export_type": "EXPORT_CMX_3600",
        })
        self.assertIn("error", out)
        msg = out["error"]["message"] if isinstance(out["error"], dict) else str(out["error"])
        self.assertIn("EXPORT_CMX_3600", msg)
        self.assertIn("EXPORT_EDL", msg)


if __name__ == "__main__":
    unittest.main()
