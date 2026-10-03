"""The granular server's sandbox redirect matches the compound server's on macOS.

On macOS /tmp is a symlink to /private/tmp, and Resolve's exporters fail
silently into both, so src/server.py redirects them. The granular copy of
_resolve_safe_dir only knew /var/ and /private/var/, which left its
save_project export fallback (tempfile.gettempdir() is "/tmp" when TMPDIR is
unset) and encrypt_dctl (which resolves the output folder, /tmp -> /private/tmp)
staging into a directory Resolve cannot write.
"""
import os
import unittest
from unittest.mock import patch

from src import server
from src.granular import common


REDIRECT = os.path.join(os.path.expanduser("~"), "Documents", "resolve-stills")


class GranularSafeDirMacOSTest(unittest.TestCase):
    def _both(self, path):
        with patch("platform.system", return_value="Darwin"):
            return server._resolve_safe_dir(path), common._resolve_safe_dir(path)

    def test_tmp_paths_redirect_like_the_compound_server(self):
        for path in ("/tmp", "/tmp/out", "/private/tmp", "/private/tmp/out",
                     "/var/folders/xy/T", "/private/var/folders/xy/T"):
            with self.subTest(path=path):
                compound, granular = self._both(path)
                self.assertEqual(compound, REDIRECT)
                self.assertEqual(granular, compound)

    def test_other_paths_are_left_alone(self):
        for path in ("/Users/me/Desktop", "/tmpfiles/out", "/Volumes/Media/stills"):
            with self.subTest(path=path):
                compound, granular = self._both(path)
                self.assertEqual(granular, compound)
                self.assertEqual(granular, path)


class SafeDirLinuxTest(unittest.TestCase):
    """On Linux the redirect compared by character prefix, not by segment.

    `startswith("/tmp")` is true of /tmpfiles, /tmp-scratch and /tmpdata, and
    `startswith("/var/tmp")` of /var/tmpdata — ordinary directories a Linux
    workstation can carry at the root, none of them a temp directory Resolve
    fails into. An export aimed at one of them was silently rewritten to
    ~/Documents/resolve-stills: gallery_stills(grab_and_export) passes the
    caller's folder_path straight through this helper and then creates and
    exports into whatever comes back. The Darwin branch has always compared by
    segment, and the macOS test above already requires /tmpfiles/out to survive.
    """

    def _both(self, path):
        with patch("platform.system", return_value="Linux"):
            return server._resolve_safe_dir(path), common._resolve_safe_dir(path)

    def test_real_temp_paths_still_redirect(self):
        for path in ("/tmp", "/tmp/out", "/var/tmp", "/var/tmp/out"):
            with self.subTest(path=path):
                compound, granular = self._both(path)
                self.assertEqual(compound, REDIRECT)
                self.assertEqual(granular, compound)

    def test_siblings_named_like_tmp_are_left_alone(self):
        for path in ("/tmpfiles/out", "/tmp-scratch/stills", "/tmpdata",
                     "/var/tmpdata/out", "/home/me/stills"):
            with self.subTest(path=path):
                compound, granular = self._both(path)
                self.assertEqual(granular, compound)
                self.assertEqual(granular, path)


if __name__ == "__main__":
    unittest.main()
