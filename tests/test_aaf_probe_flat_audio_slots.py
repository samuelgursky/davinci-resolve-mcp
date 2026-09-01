"""Flat AAF sound slots number A, A2, A3 … so separate beds keep their lanes (E109).

Measured 2026-09-01: an Avid-shaped composition with dialog and music as two
FLAT sound MobSlots walked both as "A"; the bridge then refused the turnover
("audio events overlap on audio track 1 — one track cannot hold both"). The
sound Transition between the dialog clips (an audio cross-fade) parsed fine —
it was the lane collapse that blocked the conform.
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
except Exception:  # pragma: no cover - optional dependency
    aaf2 = None

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(REPO, "resolve-advanced", "server", "aaf_probe.py")


def _author_fixture(path):
    with aaf2.open(path, "w") as f:
        er = 24
        opdef = f.create.OperationDef(AUID("0c3bea44-fc05-11d2-8a29-0050040ef7d2"), "MonoAudioDissolve", "audio dissolve")
        opdef.media_kind = "sound"
        opdef["NumberInputs"].value = 2
        f.dictionary.register_def(opdef)
        mobs = {}
        for name in ("DIAL", "MUSIC", "DIAL2"):
            mm = f.create.MasterMob(name)
            f.content.mobs.append(mm)
            ps = mm.create_picture_slot(er)
            src = f.create.SourceClip(media_kind="picture")
            src.start = 0
            src.length = 500
            ps.segment.components.append(src)
            ss = mm.create_sound_slot(er)
            a = f.create.SourceClip(media_kind="sound")
            a.start = 0
            a.length = 500
            ss.segment.components.append(a)
            mobs[name] = mm
        comp = f.create.CompositionMob("E109")
        f.content.mobs.append(comp)
        v = comp.create_picture_slot(er)
        v.segment.components.append(mobs["DIAL"].create_source_clip(1, start=0, length=96))
        v.segment.components.append(mobs["DIAL2"].create_source_clip(1, start=0, length=96))
        a1 = comp.create_sound_slot(er)  # dialog lane with a cross-fade
        a1.segment.components.append(mobs["DIAL"].create_source_clip(2, start=0, length=96))
        t = f.create.Transition()
        t.media_kind = "sound"
        t.length = 24
        t.cutpoint = 12
        og = f.create.OperationGroup("MonoAudioDissolve", length=24, media_kind="sound")
        t["OperationGroup"].value = og
        a1.segment.components.append(t)
        a1.segment.components.append(mobs["DIAL2"].create_source_clip(2, start=0, length=96))
        a2 = comp.create_sound_slot(er)  # music bed across the whole span
        a2.segment.components.append(mobs["MUSIC"].create_source_clip(2, start=0, length=168))


@unittest.skipIf(aaf2 is None, "pyaaf2 not installed")
class AafFlatAudioSlotsTest(unittest.TestCase):
    def _walk(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "e109.aaf")
            _author_fixture(path)
            out = subprocess.run([sys.executable, PROBE, path], capture_output=True, text=True, check=True)
        data = json.loads(out.stdout)
        seqs = data.get("sequences") if isinstance(data, dict) else data
        return (seqs[0] if isinstance(seqs, list) else seqs)["events"]

    def test_flat_sound_slots_keep_their_lanes_and_the_cross_fade_parses(self):
        ev = self._walk()
        aud = [(e["track"], e["source"], e["recIn"], e["recOut"]) for e in ev if e["track"].startswith("A")]
        self.assertEqual(aud, [("A", "DIAL", 0, 96), ("A", "DIAL2", 72, 168), ("A2", "MUSIC", 0, 168)])
        xf = next(e for e in ev if e["source"] == "DIAL2" and e["track"] == "A")
        self.assertEqual(xf["transition"]["duration"], 24)
        self.assertEqual(xf["transition"]["alignment"], "start")
        # Null control: the single flat picture slot keeps the bare V — first-of-kind never numbers.
        self.assertEqual(sorted({e["track"] for e in ev if not e["track"].startswith("A")}), ["V"])


if __name__ == "__main__":
    unittest.main()
