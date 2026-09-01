"""AAF walker fade synthesis (E93).

The aaf_probe component walker synthesizes zero-length BL pseudo-events at
filler-adjacent (or sequence-edge) Transitions so the interchange bridge's
black machinery can author real fades — Resolve's own importers drop them.
Authored here with pyaaf2 (skipped when unavailable), probed with the real
walker over a real .aaf: no stubs.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

try:
    import aaf2
    from aaf2.auid import AUID
except Exception:  # pragma: no cover - environment-dependent
    aaf2 = None

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(REPO, "resolve-advanced", "server", "aaf_probe.py")


def _author_fixture(path):
    with aaf2.open(path, "w") as f:
        edit_rate = 24
        opdef = f.create.OperationDef(
            AUID("0c3bea40-fc05-11d2-8a29-0050040ef7d2"), "VideoDissolve", "video dissolve"
        )
        opdef.media_kind = "picture"
        opdef["NumberInputs"].value = 2
        f.dictionary.register_def(opdef)
        mobs = {}
        for name in ("SRCA", "SRCB"):
            mm = f.create.MasterMob(name)
            f.content.mobs.append(mm)
            slot = mm.create_picture_slot(edit_rate)
            src = f.create.SourceClip(media_kind="picture")
            src.start = 0
            src.length = 500
            slot.segment.components.append(src)
            mobs[name] = mm
        comp = f.create.CompositionMob("E93_FIXTURE")
        f.content.mobs.append(comp)
        slot = comp.create_picture_slot(edit_rate)
        seq = slot.segment

        def sc(name, start, length):
            return mobs[name].create_source_clip(1, start=start, length=length)

        def trans(dur):
            t = f.create.Transition()
            t.media_kind = "picture"
            t.length = dur
            t.cutpoint = dur // 2
            og = f.create.OperationGroup("VideoDissolve", length=dur, media_kind="picture")
            t["OperationGroup"].value = og
            return t

        def filler(dur):
            g = f.create.Filler()
            g.media_kind = "picture"
            g.length = dur
            return g

        seq.components.append(trans(24))  # fade-in from the sequence head
        seq.components.append(sc("SRCA", 0, 96))
        seq.components.append(trans(24))  # dissolve A->B
        seq.components.append(sc("SRCB", 48, 96))
        seq.components.append(trans(24))  # fade-out
        seq.components.append(filler(48))


@unittest.skipIf(aaf2 is None, "pyaaf2 not installed")
class AafWalkerFadeSynthesisTest(unittest.TestCase):
    def test_filler_adjacent_transitions_emit_bl_pseudo_events(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "e93.aaf")
            _author_fixture(path)
            out = subprocess.run(
                [sys.executable, PROBE, path], capture_output=True, text=True, check=True
            )
            doc = json.loads(out.stdout)
        self.assertTrue(doc["ok"])
        seq = next(s for s in doc["sequences"] if s["name"] == "E93_FIXTURE")
        events = seq["events"]
        shapes = [(e["source"], e["recIn"], e["recOut"]) for e in events]
        # fade-in: zero-length BL predecessor at the overlap start; SRCB
        # overlaps SRCA by the transition (AAF record math, reconciled by the
        # bridge); fade-out: BL leg carrying the transition at the rewound rec.
        self.assertEqual(shapes, [
            ("BL", 0, 0),
            ("SRCA", 0, 96),
            ("SRCB", 72, 168),
            ("BL", 144, 144),
        ])
        self.assertIsNone(events[0]["transition"])
        self.assertEqual(events[1]["transition"]["alignment"], "start")
        self.assertEqual(events[1]["transition"]["cutPoint"], 12)
        self.assertEqual(events[3]["transition"]["duration"], 24)


if __name__ == "__main__":
    unittest.main()
