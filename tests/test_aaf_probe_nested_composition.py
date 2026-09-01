"""An Avid NESTED SEQUENCE used as a clip flattens into the parent (E125).

Measured 2026-09-01: a SourceClip referencing a NAMED CompositionMob walked as a
source named after the composition ("NESTED_SEQ") — an unmapped reel to the
bridge — while the composition's own cuts sat in the same AAF. They now flatten
through the reference's window, tagged fromCompound, like OTIO Stacks (E120).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

try:
    import aaf2
except Exception:  # pragma: no cover - optional dependency
    aaf2 = None

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(REPO, "resolve-advanced", "server", "aaf_probe.py")


def _author(path, nested_start=0, nested_length=48):
    with aaf2.open(path, "w") as f:
        er = 24
        mobs = {}
        for name in ("SRCA", "SRCB", "SRCC"):
            mm = f.create.MasterMob(name)
            f.content.mobs.append(mm)
            ps = mm.create_picture_slot(er)
            src = f.create.SourceClip(media_kind="picture")
            src.start = 0
            src.length = 500
            ps.segment.components.append(src)
            mobs[name] = mm
        nested = f.create.CompositionMob("NESTED_SEQ")
        f.content.mobs.append(nested)
        ns = nested.create_picture_slot(er)
        ns.segment.components.append(mobs["SRCB"].create_source_clip(1, start=10, length=24))
        ns.segment.components.append(mobs["SRCC"].create_source_clip(1, start=20, length=24))
        top = f.create.CompositionMob("E125_TOP")
        f.content.mobs.append(top)
        ts = top.create_picture_slot(er)
        ts.segment.components.append(mobs["SRCA"].create_source_clip(1, start=0, length=48))
        ts.segment.components.append(nested.create_source_clip(1, start=nested_start, length=nested_length))


def _walk(**kw):
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "e125.aaf")
        _author(path, **kw)
        out = subprocess.run([sys.executable, PROBE, path], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    seqs = data.get("sequences") if isinstance(data, dict) else data
    top = next(s for s in seqs if s.get("name") == "E125_TOP")
    return [(e["source"], e["srcIn"], e["srcOut"], e["recIn"], e["recOut"], e.get("fromCompound")) for e in top["events"] if e["track"] == "V"]


@unittest.skipIf(aaf2 is None, "pyaaf2 not installed")
class AafNestedCompositionTest(unittest.TestCase):
    def test_nested_sequence_flattens_into_the_parent(self):
        self.assertEqual(_walk(), [
            ("SRCA", 0, 48, 0, 48, None),
            ("SRCB", 10, 34, 48, 72, "NESTED_SEQ"),
            ("SRCC", 20, 44, 72, 96, "NESTED_SEQ"),
        ])

    def test_the_reference_window_trims_the_inner_cuts(self):
        # Used from its frame 12 for 24 frames: the first inner cut loses 12 head frames, the second is clipped at 24.
        self.assertEqual(_walk(nested_start=12, nested_length=24), [
            ("SRCA", 0, 48, 0, 48, None),
            ("SRCB", 22, 34, 48, 60, "NESTED_SEQ"),
            ("SRCC", 20, 32, 60, 72, "NESTED_SEQ"),
        ])


if __name__ == "__main__":
    unittest.main()
