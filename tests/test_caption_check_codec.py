"""timeline_ai check_captions_live through the real Node bridge, on an exported-timeline fixture.

test_subtitle_live mocks the codec subprocess; this runs scripts/edit_subtitle_timeline.mjs.
Skipped without Node and the resolve-advanced packages, which CI installs.
"""
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock

from src.utils import subtitle_live as live

READY = bool(shutil.which("node")) and live.subtitle_codec_gap() is None

# Two five-word Resolve auto-captions at 30 fps, as a native timeline export stores them.
BLOBS = [
    "00000002000000748128b52ffd206a5103000a5568007204204f682c72072074686174277372052073756368720220617205206375746578"
    "ec980d7894990d78ba990d78c6990d78d2990d800194990d8001ba990d8001c6990d8001d2990d8001de990da801b6cc0612110000002478"
    "9c6366606420040000b20005",
    "00000002000000738128b52ffd20694903000a5468007204206361747205206974277372022061720420646f6772072064756d6d792e78de"
    "990d78fa990d78ea9a0d78ec9a0d78809b0d8001fa990d8001ea9a0d8001ec9a0d8001809b0d8001949b0da801efcc06121100000024789c"
    "6366606420040000b20005",
]


def _generator(index, blob, name, start, duration):
    return (f'<Element><Sm2TiGenerator DbId="aaaaaaaa-0000-0000-0000-00000000000{index}"><FieldsBlob>{blob}</FieldsBlob>'
            f"<PrettyType>Subtitle</PrettyType><Name>{name}</Name><Start>{start}</Start><Duration>{duration}</Duration>"
            "<MarkersBA/><In/></Sm2TiGenerator></Element>")


def write_drt(path):
    items = (_generator(1, BLOBS[0], " Oh, that's such a cute", 108086, 57)
             + _generator(2, BLOBS[1], " cat it&apos;s a dog dummy.", 108143, 91))
    sequence = "33333333-3333-3333-3333-333333333333"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as drt:
        drt.writestr("project.xml", "<project/>")
        drt.writestr("MediaPool/Master/MpFolder.xml",
                     f'<Sm2Sequence DbId="{sequence}"><FrameRate>0000000000003e400000000000000000</FrameRate></Sm2Sequence>')
        drt.writestr("SeqContainer/22222222-2222-2222-2222-222222222222.xml",
                     "<Sm2SequenceContainer><SubtitleTrackVec><Element>"
                     f'<Sm2TiTrack DbId="11111111-1111-1111-1111-111111111111"><Sequence>{sequence}</Sequence>'
                     f"<Items>{items}</Items><FusionCompHolderItems/></Sm2TiTrack>"
                     "</Element></SubtitleTrackVec></Sm2SequenceContainer>")
    return path


@unittest.skipUnless(READY, "needs Node and resolve-advanced's packages (npm install in resolve-advanced)")
class CaptionCheckCodecTest(unittest.TestCase):
    def check(self, **params):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fixture = write_drt(Path(tmp.name) / "fixture.drt")
        timeline = Mock()
        timeline.GetTrackCount.return_value = 1
        timeline.GetName.return_value = "Cut"
        # Resolve's native export, replaced by copying the fixture to the path the helper asks for.
        timeline.Export.side_effect = lambda path, _format: bool(shutil.copy(fixture, path))
        return live.check_captions_live(Mock(EXPORT_DRT=1), timeline, {"track": 1, **params}, lambda _: tmp.name)

    def test_clean_captions_pass_and_limits_reach_the_codec(self):
        clean = self.check(max_characters=24, min_frames_per_word=3)
        self.assertTrue(clean["success"], clean)
        self.assertEqual((clean["ok"], clean["fps"], clean["timeline"]), (True, 30, "Cut"))
        tight = self.check(max_characters=10)
        self.assertFalse(tight["ok"])
        self.assertEqual({i["code"] for i in tight["issues"]}, {"overflow_length"})
        slow = self.check(min_frames_per_word=12)  # the first caption is 57 frames for 5 words
        self.assertEqual([(i["id"], i["code"]) for i in slow["issues"]], [("108086", "too_short")])


if __name__ == "__main__":
    unittest.main()
