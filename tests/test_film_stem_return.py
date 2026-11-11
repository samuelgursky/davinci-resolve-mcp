"""Film returns preserve source files, timeline origins and unrelated tracks."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from src.utils import film_stem_return as mod


class Media:
    def __init__(self, path, fps=30):
        self.path, self.fps = path, fps
    def GetClipProperty(self, key):
        return {"File Path": self.path, "FPS": str(self.fps)}[key]


class Item:
    def __init__(self, media, start, duration):
        self.media, self.start, self.duration = media, start, duration
    def GetMediaPoolItem(self): return self.media
    def GetStart(self, precision=True): return self.start
    def GetDuration(self, precision=True): return self.duration
    def GetUniqueId(self): return "item-" + self.media.path


class Timeline:
    def __init__(self):
        self.tracks = [("Dialogue", [])]
        self.start, self.fps = 86400, "24"
    def GetUniqueId(self): return "timeline-id"
    def GetName(self): return "Film"
    def GetStartFrame(self): return self.start
    def GetSetting(self, key): return self.fps
    def GetTrackCount(self, kind): return len(self.tracks)
    def GetTrackName(self, kind, index): return self.tracks[index-1][0]
    def GetItemListInTrack(self, kind, index): return self.tracks[index-1][1]
    def AddTrack(self, kind, options):
        self.tracks.append(("Audio", [])); return True
    def SetTrackName(self, kind, index, name):
        self.tracks[index-1] = (name, self.tracks[index-1][1]); return True


class Pool:
    def __init__(self, tl):
        self.tl, self.imports, self.appends = tl, [], []
        self.wrong_start, self.fail = False, False
    def ImportMedia(self, paths):
        self.imports.extend(paths); return [Media(p) for p in paths]
    def AppendToTimeline(self, infos):
        self.appends.extend(infos)
        if self.fail: return []
        info = infos[0]
        item = Item(info['mediaPoolItem'], info['recordFrame'] + int(self.wrong_start),
                    (info['endFrame'] - info['startFrame']) / info['mediaPoolItem'].fps
                    * float(mod._rate(self.tl.fps)))
        self.tl.tracks[info['trackIndex']-1][1].append(item)
        return [item]


class Project:
    def __init__(self): self.tl = Timeline(); self.pool = Pool(self.tl)
    def GetCurrentTimeline(self): return self.tl
    def GetMediaPool(self): return self.pool


def package(root):
    path = root / 'music.wav'
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(2); out.setsampwidth(3); out.setframerate(48000)
        out.writeframes(b'\0' * 48000 * 6)
    manifest = {'schema':'film-stems/v1', 'subtype':'PCM_24',
        'frame_rate':{'numerator':24,'denominator':1}, 'start_frame':24,
        'end_frame':42, 'tail_frames':6, 'sample_rate':48000,
        'start_sample':48000, 'end_sample':96000, 'sample_count':48000,
        'body_sample_count':36000, 'tail_sample_count':12000,
        'stems':[{'name':'music','file':'music.wav','channels':2,
                  'sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'tail_not_quiet':False}]}
    (root/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return manifest


class FilmStemReturnTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.manifest = package(self.root)
        self.project = Project()
    def preview(self): return mod.prepare_return(self.project, str(self.root))
    def apply(self, preview):
        return mod.prepare_return(self.project, str(self.root), preview=False,
            expected_timeline_id='timeline-id', expected_fingerprint=preview['fingerprint'])
    def add_second_stem(self):
        (self.root/'fx.wav').write_bytes((self.root/'music.wav').read_bytes())
        self.manifest['stems'].append(dict(self.manifest['stems'][0], name='fx', file='fx.wav'))
        (self.root/'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_incomplete_import_preserves_known_receipts(self):
        self.add_second_stem()
        preview = self.preview()
        path = str(self.root/'music.wav')
        with patch.object(self.project.pool, 'ImportMedia', return_value=[Media(path)]):
            result = self.apply(preview)
        self.assertEqual(result['status'], 'partial_failure')
        self.assertEqual(result['imported_media'], [path])
        self.assertIs(result.get('partially_created_unknown'), True)
        self.assertEqual(result['created_tracks'], [])
        self.assertEqual(self.project.pool.appends, [])

    def test_import_without_handles_reports_unknown_created_objects(self):
        preview = self.preview()
        for response in (None, [], False):
            with self.subTest(response=response):
                with patch.object(self.project.pool, 'ImportMedia', return_value=response):
                    result = self.apply(preview)
                self.assertEqual(result['status'], 'partial_failure')
                self.assertIs(result.get('partially_created_unknown'), True)
                self.assertEqual(result['imported_media'], [])
                self.assertEqual(result['created_tracks'], [])

    def test_import_exception_reports_unknown_created_objects(self):
        preview = self.preview()
        with patch.object(self.project.pool, 'ImportMedia', side_effect=RuntimeError('API disconnected')):
            result = self.apply(preview)
        self.assertEqual(result['status'], 'partial_failure')
        self.assertIs(result.get('partially_created_unknown'), True)
        self.assertEqual(result['imported_media'], [])
        self.assertEqual(result['created_tracks'], [])

    def test_unreadable_handle_does_not_hide_other_import_receipts(self):
        self.add_second_stem()
        preview = self.preview()
        broken = Media(str(self.root/'music.wav'))
        path = str(self.root/'fx.wav')
        with patch.object(broken, 'GetClipProperty', side_effect=RuntimeError('Handle unavailable')):
            with patch.object(self.project.pool, 'ImportMedia', return_value=[broken, Media(path)]):
                result = self.apply(preview)
        self.assertEqual(result['status'], 'partial_failure')
        self.assertEqual(result['imported_media'], [path])
        self.assertIs(result.get('partially_created_unknown'), True)
        self.assertEqual(result['created_tracks'], [])

    def test_partial_replay_refuses_before_more_mutations(self):
        self.add_second_stem()
        preview = self.preview()
        append = self.project.pool.AppendToTimeline
        def fail_second(infos):
            return [] if len(self.project.pool.appends) == 1 else append(infos)
        with patch.object(self.project.pool, 'AppendToTimeline', side_effect=fail_second):
            result = self.apply(preview)
        self.assertEqual(result['status'], 'partial_failure')
        self.assertEqual(len(self.project.tl.tracks[1][1]), 1)
        self.assertEqual(len(self.project.tl.tracks[2][1]), 0)
        before = (len(self.project.pool.imports), len(self.project.pool.appends), len(self.project.tl.tracks))
        for replay in (self.preview, lambda: self.apply(preview)):
            with self.assertRaises(ValueError): replay()
        self.assertEqual(before, (len(self.project.pool.imports), len(self.project.pool.appends),
                                  len(self.project.tl.tracks)))

    def test_malformed_wav_with_matching_hash_refuses_before_import(self):
        path = self.root/'music.wav'
        original = path.read_bytes()
        for data in (original[:-6], original[:40] + (12).to_bytes(4, 'little') + original[44:]):
            with self.subTest(size=len(data)):
                path.write_bytes(data)
                self.manifest['stems'][0]['sha256'] = hashlib.sha256(data).hexdigest()
                (self.root/'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
                with self.assertRaises(ValueError): self.preview()
                self.assertEqual(self.project.pool.imports, [])
                self.assertEqual(len(self.project.tl.tracks), 1)
    def test_preview_no_mutations(self):
        result = self.preview()
        self.assertEqual(result['status'], 'preview')
        self.assertEqual(result['record_frame'], 86424)
        self.assertEqual(len(self.project.tl.tracks), 1)
        self.assertEqual(self.project.pool.imports, [])
    def test_correct_hour_origin_and_media_source_fps(self):
        before = (self.root/'music.wav').read_bytes()
        result = self.apply(self.preview())
        self.assertEqual(result['status'], 'imported')
        self.assertEqual(self.project.pool.appends[0]['endFrame'], 30)
        self.assertEqual(self.project.tl.tracks[1][1][0].start, 86424)
        self.assertEqual((self.root/'music.wav').read_bytes(), before)
        self.assertEqual(self.project.tl.tracks[0], ('Dialogue', []))
    def test_complete_replay_is_noop(self):
        self.apply(self.preview())
        again = self.preview()
        self.assertEqual(again['status'], 'already_present')
        self.assertEqual(len(self.project.pool.imports), 1)
    def test_changed_timeline_refuses_before_import(self):
        preview = self.preview(); self.project.tl.tracks.append(('User edit', []))
        with self.assertRaises(ValueError): self.apply(preview)
        self.assertEqual(self.project.pool.imports, [])
    def test_missing_confirmation_refuses(self):
        with self.assertRaises(ValueError):
            mod.prepare_return(self.project, str(self.root), preview=False)
    def test_bad_hash_and_bad_clock_refuse(self):
        for key, value in [('sample_count', 1), ('start_sample', 0)]:
            bad = dict(self.manifest, **{key:value})
            (self.root/'manifest.json').write_text(json.dumps(bad), encoding='utf-8')
            with self.assertRaises(ValueError): self.preview()
        (self.root/'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        with (self.root/'music.wav').open(mode='ab') as stream: stream.write(b'x')
        with self.assertRaises(ValueError): self.preview()
    def test_rate_mismatch_refuses_before_mutation(self):
        self.project.tl.fps='25'
        with self.assertRaises(ValueError): self.preview()
        self.assertEqual(self.project.pool.imports, [])
    def test_wrong_readback_reports_partial_not_success(self):
        self.project.pool.wrong_start=True
        result = self.apply(self.preview())
        self.assertEqual(result['status'], 'partial_failure')
        self.assertEqual(len(self.project.tl.tracks), 2)
        self.assertFalse(result['rollback_attempted'])
    def test_append_failure_preserves_created_track(self):
        self.project.pool.fail=True
        result = self.apply(self.preview())
        self.assertEqual(result['status'], 'partial_failure')
        self.assertEqual(len(result['created_tracks']), 1)
        self.assertIs(result.get('partially_created_unknown'), False)
    def test_existing_wrong_placement_is_conflict(self):
        self.project.tl.tracks[0][1].append(Item(Media(str(self.root/'music.wav')), 10,24))
        with self.assertRaises(ValueError): self.preview()
    def test_manifest_paths_cannot_escape(self):
        self.manifest['stems'][0]['file']='../music.wav'
        (self.root/'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        with self.assertRaises(ValueError): self.preview()

    def test_ntsc_uses_absolute_sample_endpoints(self):
        path = self.root/'music.wav'
        with wave.open(str(path),'wb') as out:
            out.setnchannels(2); out.setsampwidth(3); out.setframerate(48000)
            out.writeframes(b'\0'*1601*6)
        self.manifest.update(frame_rate={'numerator':30000,'denominator':1001},
            start_frame=1,end_frame=2,tail_frames=0,start_sample=1602,end_sample=3203,
            sample_count=1601,body_sample_count=1601,tail_sample_count=0)
        self.manifest['stems'][0]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        (self.root/'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')
        self.project.tl.fps='29.97'; self.project.tl.start=0
        result=self.preview()
        self.assertEqual(result['record_frame'],1)
        self.assertEqual(result['duration_frames'],1)
        before = path.read_bytes()
        applied = self.apply(result)
        self.assertEqual(applied['status'], 'imported')
        info = self.project.pool.appends[0]
        self.assertAlmostEqual(info['endFrame'], 1.001)
        self.assertEqual(info['startFrame'], 0)
        self.assertEqual(info['recordFrame'], 1)
        item = self.project.tl.tracks[1][1][0]
        self.assertEqual(item.start, 1)
        self.assertAlmostEqual(item.duration, 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.preview()['status'], 'already_present')

    def test_mcp_action_exposes_read_only_preview(self):
        from unittest.mock import patch
        import src.server as server
        from tests._envelope_helpers import domain_payload
        with patch.object(server,'_check',return_value=(None,self.project,None)):
            result=domain_payload(server.timeline('film_stems_return',{'delivery_dir':str(self.root)}))
        self.assertEqual(result['status'],'preview')
        self.assertEqual(self.project.pool.imports,[])


if __name__ == '__main__': unittest.main()


class SymlinkedPathTests(unittest.TestCase):
    """Resolve reports the path it was handed; the audit resolves symlinks.

    On macOS /var, /tmp and many volumes are symlinks, so a previous import
    reported as /var/... never matched the audited /private/var/... path and
    the duplicate check was skipped. Built here with an explicit symlink so it
    fails on every platform, not only where the temp dir happens to be one.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.real = base / 'real'; self.real.mkdir()
        self.link = base / 'link'
        try:
            self.link.symlink_to(self.real, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'symlinks unavailable: {exc}')
        package(self.real)
        self.project = Project()

    def _existing(self, start, duration):
        reported = str(self.link / 'music.wav')  # unresolved, as Resolve reports it
        self.project.tl.tracks[0][1].append(Item(Media(reported), start, duration))

    def test_existing_stem_via_symlink_is_a_conflict(self):
        self._existing(10, 24)
        with self.assertRaises(ValueError):
            mod.prepare_return(self.project, str(self.link))

    def test_existing_stem_via_symlink_is_already_present(self):
        first = mod.prepare_return(self.project, str(self.real))
        self.project.tl.tracks[0] = (first['track_names'][0], [])
        self._existing(first['record_frame'], first['duration_frames'])
        self.assertEqual(mod.prepare_return(self.project, str(self.real))['status'],
                         'already_present')
