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


if __name__ == "__main__":
    unittest.main()
