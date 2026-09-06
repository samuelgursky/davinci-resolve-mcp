"""The managed install must contain everything the bins it registers import.

Issue #179: `npx davinci-resolve-mcp setup` registered
`davinci-resolve-advanced` in every generated client config, pointing at
`<managed root>/bin/davinci-resolve-advanced-mcp.mjs` — but the bootstrapper's
SYNC_ITEMS never copied `resolve-advanced/`, which that bin imports. The
process died with ERR_MODULE_NOT_FOUND before the MCP handshake and clients
reported only "subprocess closed stdout before responding".

These tests drive the real sync into a temp root rather than restating the
SYNC_ITEMS list, so a future edit that drops the tree again fails here.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = PROJECT_ROOT / "bin" / "davinci-resolve-mcp.mjs"
NODE_MIN = (20, 9)


def _node_version(cmd):
    try:
        out = subprocess.run([cmd, "--version"], capture_output=True, text=True,
                             timeout=10, check=False).stdout.strip()
        parts = out.lstrip("v").split(".")
        return (int(parts[0]), int(parts[1]))
    except Exception:
        return None


def find_node():
    """A Node >= the repo floor, or None.

    The default `node` on a developer machine is routinely older than the
    floor (nvm's default lags), and under an old Node the advanced bin exits
    on the version check before reaching the layout preflight these tests are
    about — which would make them pass for the wrong reason.
    """
    on_path = shutil.which("node")
    if on_path and (_node_version(on_path) or (0, 0)) >= NODE_MIN:
        return on_path
    nvm_dir = Path.home() / ".nvm" / "versions" / "node"
    best = None
    if nvm_dir.is_dir():
        for entry in nvm_dir.iterdir():
            candidate = entry / "bin" / "node"
            if not candidate.exists():
                continue
            version = _node_version(str(candidate))
            if version and version >= NODE_MIN and (best is None or version > best[0]):
                best = (version, str(candidate))
    return best[1] if best else None


NODE = find_node()
requires_node = unittest.skipIf(
    NODE is None, f"needs Node >= {NODE_MIN[0]}.{NODE_MIN[1]}")


@requires_node
class ManagedSyncTest(unittest.TestCase):
    """`davinci-resolve-mcp sync` produces a root the advanced bin can boot from."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "managed"
        cls.sync()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @classmethod
    def sync(cls, root=None):
        env = dict(os.environ)
        env["DAVINCI_RESOLVE_MCP_INSTALL_ROOT"] = str(root or cls.root)
        # --no-deps keeps the test offline: it exercises the file sync, not npm.
        return subprocess.run(
            [NODE, str(BOOTSTRAP), "sync", "--no-deps"],
            capture_output=True, text=True, env=env, timeout=300, check=False)

    def test_managed_root_receives_the_tree_the_advanced_bin_imports(self):
        entry = self.root / "resolve-advanced" / "server" / "index.mjs"
        self.assertTrue(
            entry.is_file(),
            f"{entry} is missing — the advanced bin imports exactly this path")

    def test_managed_root_receives_the_advanced_dependency_manifest(self):
        # install.py and the bin both read this file to learn which deps are
        # required; without it neither can tell a bootable root from a broken one.
        manifest = self.root / "resolve-advanced" / "package.json"
        self.assertTrue(manifest.is_file())
        with open(manifest, "r", encoding="utf-8") as fh:
            self.assertTrue(json.load(fh).get("dependencies"))

    def test_sync_does_not_copy_a_dev_checkout_node_modules(self):
        # A developer's resolve-advanced/node_modules holds optional native
        # deps built for their platform+ABI. Copying those into a managed
        # install is slow and ships binaries that may not load there.
        if not (PROJECT_ROOT / "resolve-advanced" / "node_modules").is_dir():
            self.skipTest("no dev node_modules to copy in the first place")
        self.assertFalse((self.root / "resolve-advanced" / "node_modules").exists())

    def test_resync_preserves_provisioned_dependencies(self):
        # Every command syncs before it runs. If the sync cleared this
        # directory, provisioned deps would be destroyed on the next launch
        # and the server would be unbootable again. Its own root, so the
        # sentinel does not leak into the sibling tests' shared install.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "managed"
            self.sync(root)
            modules = root / "resolve-advanced" / "node_modules" / "sentinel-pkg"
            modules.mkdir(parents=True)
            (modules / "package.json").write_text('{"name":"sentinel-pkg"}', encoding="utf-8")
            self.sync(root)
            self.assertTrue(
                (modules / "package.json").is_file(),
                "re-syncing wiped provisioned Node deps out of the managed install")
            # ...and the tree itself is still refreshed around it.
            self.assertTrue(
                (root / "resolve-advanced" / "server" / "index.mjs").is_file())


@requires_node
class AdvancedBinPreflightTest(unittest.TestCase):
    """An unbootable install must name the fix, not raise ERR_MODULE_NOT_FOUND."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "managed"
        (self.root / "bin").mkdir(parents=True)
        shutil.copy2(PROJECT_ROOT / "bin" / "davinci-resolve-advanced-mcp.mjs",
                     self.root / "bin")
        shutil.copy2(PROJECT_ROOT / "package.json", self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def run_bin(self, *args):
        return subprocess.run(
            [NODE, str(self.root / "bin" / "davinci-resolve-advanced-mcp.mjs"), *args],
            capture_output=True, text=True, timeout=60, check=False)

    def test_version_still_answers_without_the_server_tree(self):
        # --version/--help must not depend on the layout: they are what a user
        # reaches for when the server will not start.
        result = self.run_bin("--version")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.strip())

    def test_missing_tree_reports_the_repair_command(self):
        result = self.run_bin()
        self.assertEqual(result.returncode, 1)
        self.assertIn("cannot start", result.stderr)
        self.assertIn("resolve-advanced", result.stderr)
        self.assertIn("davinci-resolve-mcp setup", result.stderr)
        self.assertNotIn("ERR_MODULE_NOT_FOUND", result.stderr)

    def test_the_failure_never_writes_to_stdout(self):
        # stdout is the JSON-RPC channel; a diagnostic there corrupts the
        # handshake instead of explaining it.
        self.assertEqual(self.run_bin().stdout, "")


class AdvancedConfigEntryTest(unittest.TestCase):
    """install.py must not register a bin this install cannot boot."""

    def setUp(self):
        import install
        self.install = install
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "install"
        (self.root / "src").mkdir(parents=True)
        (self.root / "src" / "server.py").write_text("", encoding="utf-8")
        (self.root / "bin").mkdir()
        self.server_path = self.root / "src" / "server.py"

    def tearDown(self):
        self._tmp.cleanup()

    def _write_advanced_tree(self, deps, *, install_into=None):
        adv = self.root / "resolve-advanced"
        (adv / "server").mkdir(parents=True, exist_ok=True)
        (adv / "server" / "index.mjs").write_text("", encoding="utf-8")
        (adv / "package.json").write_text(
            json.dumps({"dependencies": {d: "^1.0.0" for d in deps}}), encoding="utf-8")
        for dep in (install_into or []):
            (adv / "node_modules" / dep).mkdir(parents=True, exist_ok=True)

    def test_no_tree_falls_back_to_npx(self):
        entry = self.install.build_advanced_entry(str(self.server_path))
        self.assertEqual(entry["command"], "npx")
        self.assertIn("davinci-resolve-advanced-mcp", entry["args"])

    def test_tree_without_deps_falls_back_to_npx(self):
        self._write_advanced_tree(["zod"])
        entry = self.install.build_advanced_entry(str(self.server_path))
        self.assertEqual(entry["command"], "npx")

    def test_provisioned_tree_uses_the_managed_bin(self):
        self._write_advanced_tree(["zod"], install_into=["zod"])
        entry = self.install.build_advanced_entry(str(self.server_path))
        self.assertNotEqual(entry["command"], "npx")
        self.assertIn("davinci-resolve-advanced-mcp.mjs", entry["args"][0])

    def test_hoisted_deps_also_count_as_bootable(self):
        # A plain `npm install davinci-resolve-mcp` hoists deps to the package
        # root rather than into resolve-advanced/node_modules.
        self._write_advanced_tree(["zod"])
        (self.root / "node_modules" / "zod").mkdir(parents=True)
        entry = self.install.build_advanced_entry(str(self.server_path))
        self.assertNotEqual(entry["command"], "npx")

    def test_scoped_dep_is_checked_by_its_full_name(self):
        self._write_advanced_tree(["@modelcontextprotocol/sdk"])
        entry = self.install.build_advanced_entry(str(self.server_path))
        self.assertEqual(entry["command"], "npx")
        self._write_advanced_tree(["@modelcontextprotocol/sdk"],
                                  install_into=["@modelcontextprotocol/sdk"])
        entry = self.install.build_advanced_entry(str(self.server_path))
        self.assertNotEqual(entry["command"], "npx")

    def test_npx_fallback_pins_the_package_version(self):
        entry = self.install.build_advanced_entry(str(self.server_path))
        pinned = [a for a in entry["args"] if a.startswith("davinci-resolve-mcp@")]
        self.assertEqual(len(pinned), 1)
        self.assertNotEqual(pinned[0], "davinci-resolve-mcp@latest")

    def test_fallback_still_pins_the_aaf_probe_interpreter(self):
        entry = self.install.build_advanced_entry(str(self.server_path), "/venv/bin/python")
        self.assertEqual(entry["env"]["AAF_PROBE_PYTHON"], "/venv/bin/python")


if __name__ == "__main__":
    unittest.main()
