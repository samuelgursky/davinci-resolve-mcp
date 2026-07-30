"""Tests for src/utils/resolve_bridge.py — the free-edition in-app transport.

The replay test is the important one: it reproduces a real defect found in a
third-party bridge, where pruning the nonce cache at `now - skew` while accepting
`|now - ts| <= skew` leaves a replay window the width of the skew for a
future-dated request.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from src.utils import resolve_bridge as rb


def signed(token: str, *, timestamp: int, nonce: str, operation: str = "health", request_id: str = "1"):
    request = {
        "protocol": rb.PROTOCOL_VERSION,
        "id": request_id,
        "timestamp": timestamp,
        "nonce": nonce,
        "operation": operation,
        "arguments": {},
    }
    request["signature"] = rb.sign_request(token, request)
    return request


TOKEN = "t" * 48


class SigningTests(unittest.TestCase):
    def test_signature_covers_every_field_but_itself(self) -> None:
        request = signed(TOKEN, timestamp=1000, nonce="n" * 20)
        self.assertTrue(rb.signature_is_valid(TOKEN, request, request["signature"]))
        tampered = dict(request, operation="delete_everything")
        self.assertFalse(rb.signature_is_valid(TOKEN, tampered, request["signature"]))

    def test_the_token_never_appears_in_the_signed_form(self) -> None:
        request = signed(TOKEN, timestamp=1000, nonce="n" * 20)
        self.assertNotIn(TOKEN.encode(), rb.canonical_request(request))

    def test_canonical_form_is_order_independent(self) -> None:
        a = {"protocol": "1.0", "id": "x", "operation": "health"}
        b = {"operation": "health", "id": "x", "protocol": "1.0"}
        self.assertEqual(rb.canonical_request(a), rb.canonical_request(b))

    def test_a_different_token_does_not_verify(self) -> None:
        request = signed(TOKEN, timestamp=1000, nonce="n" * 20)
        self.assertFalse(rb.signature_is_valid("x" * 48, request, request["signature"]))


class AuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.nonces = rb.NonceCache(60)

    def _auth(self, request, now=1000.0):
        return rb.authenticate(request, token=TOKEN, skew_seconds=60, nonces=self.nonces, now=now)

    def test_a_well_formed_request_authenticates(self) -> None:
        self.assertIsNone(self._auth(signed(TOKEN, timestamp=1000, nonce="n" * 20)))

    def test_a_token_on_the_wire_is_rejected(self) -> None:
        request = signed(TOKEN, timestamp=1000, nonce="n" * 20)
        request["token"] = TOKEN
        self.assertEqual(self._auth(request), "unauthorized")

    def test_protocol_mismatch_is_rejected(self) -> None:
        request = signed(TOKEN, timestamp=1000, nonce="n" * 20)
        request["protocol"] = "0.9"
        self.assertEqual(self._auth(request), "protocol_mismatch")

    def test_a_bad_signature_is_rejected(self) -> None:
        request = signed(TOKEN, timestamp=1000, nonce="n" * 20)
        request["signature"] = "0" * 64
        self.assertEqual(self._auth(request), "unauthorized")

    def test_malformed_nonce_and_signature_are_rejected(self) -> None:
        for mutate in ({"nonce": "short"}, {"signature": "nothex"}, {"timestamp": "1000"}, {"timestamp": True}):
            request = signed(TOKEN, timestamp=1000, nonce="n" * 20)
            request.update(mutate)
            request["signature"] = rb.sign_request(TOKEN, request) if "signature" not in mutate else request["signature"]
            with self.subTest(mutate=mutate):
                self.assertEqual(self._auth(request), "unauthorized")

    def test_a_stale_timestamp_is_rejected(self) -> None:
        self.assertEqual(self._auth(signed(TOKEN, timestamp=800, nonce="n" * 20)), "stale_request")

    def test_immediate_replay_is_rejected(self) -> None:
        request = signed(TOKEN, timestamp=1000, nonce="n" * 20)
        self.assertIsNone(self._auth(request))
        self.assertEqual(self._auth(request), "replayed_request")

    def test_future_dated_replay_is_rejected_across_the_whole_window(self) -> None:
        """The third-party defect this exists to prevent.

        A request signed with a future timestamp is accepted now; pruning the
        nonce at `now - skew` forgets it while its timestamp is still fresh,
        so the same bytes replay successfully later. Retaining nonces for twice
        the skew closes the hole — assert it at every point in the window.
        """
        skew = 60
        nonces = rb.NonceCache(skew)
        request = signed(TOKEN, timestamp=1060, nonce="f" * 24)  # +skew into the future

        self.assertIsNone(
            rb.authenticate(request, token=TOKEN, skew_seconds=skew, nonces=nonces, now=1000.0)
        )
        for offset in range(1, 121, 5):
            now = 1000.0 + offset
            verdict = rb.authenticate(request, token=TOKEN, skew_seconds=skew, nonces=nonces, now=now)
            with self.subTest(offset=offset):
                self.assertIn(
                    verdict, ("replayed_request", "stale_request"),
                    f"replay accepted {offset}s later — the nonce window does not cover "
                    f"the timestamp window",
                )

    def test_nonce_retention_exceeds_the_timestamp_window(self) -> None:
        self.assertGreaterEqual(rb._NONCE_RETENTION_FACTOR, 2)


class ConfigTests(unittest.TestCase):
    def _write(self, payload, mode=0o600):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(payload, handle)
        handle.close()
        os.chmod(handle.name, mode)
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    BASE = {"host": "127.0.0.1", "port": 49632, "token": "k" * 48, "auth_clock_skew_seconds": 60}

    def test_a_valid_config_loads(self) -> None:
        self.assertEqual(rb.load_config(self._write(self.BASE))["port"], 49632)

    @unittest.skipIf(os.name == "nt", "POSIX permissions only")
    def test_a_world_readable_secret_is_refused(self) -> None:
        with self.assertRaises(rb.BridgeConfigError) as ctx:
            rb.load_config(self._write(self.BASE, mode=0o644))
        self.assertIn("chmod 600", str(ctx.exception))

    def test_a_routable_host_is_refused(self) -> None:
        with self.assertRaises(rb.BridgeConfigError) as ctx:
            rb.load_config(self._write({**self.BASE, "host": "0.0.0.0"}))
        self.assertIn("127.0.0.1", str(ctx.exception))

    def test_a_short_token_is_refused(self) -> None:
        with self.assertRaises(rb.BridgeConfigError):
            rb.load_config(self._write({**self.BASE, "token": "short"}))

    def test_out_of_range_port_and_skew_are_refused(self) -> None:
        for bad in ({"port": 80}, {"port": 99999}, {"auth_clock_skew_seconds": 5}, {"auth_clock_skew_seconds": 9999}):
            with self.subTest(bad=bad):
                with self.assertRaises(rb.BridgeConfigError):
                    rb.load_config(self._write({**self.BASE, **bad}))

    def test_a_missing_file_is_refused_clearly(self) -> None:
        with self.assertRaises(rb.BridgeConfigError):
            rb.load_config("/nope/bridge.json")


class HostModelTests(unittest.TestCase):
    """Getting this wrong wedges Resolve or kills the bridge — so it is explicit."""

    def test_a_resolve_parent_means_child_process_and_must_block(self) -> None:
        model = rb._host_model(getppid=lambda: 42, process_name_of=lambda pid: "DaVinci Resolve")
        self.assertEqual(model["model"], "child_process")
        self.assertTrue(model["blocking_required"])
        self.assertIn("daemon thread would die", model["reason"])

    def test_a_fuscript_parent_also_counts_as_child(self) -> None:
        model = rb._host_model(getppid=lambda: 42, process_name_of=lambda pid: "fuscript")
        self.assertTrue(model["blocking_required"])

    def test_resolves_own_interpreter_means_in_process_and_must_not_block(self) -> None:
        # In-process is now decided by THIS interpreter being Resolve, not by the
        # parent being launchd — a launchd parent says nothing either way.
        model = rb._host_model(
            getppid=lambda: 1,
            process_name_of=lambda pid: "launchd",
            self_executable="/Applications/DaVinci Resolve.app/Contents/MacOS/Resolve",
        )
        self.assertEqual(model["model"], "in_process")
        self.assertFalse(model["blocking_required"])
        self.assertIn("wedge", model["reason"])

    def test_an_unreadable_parent_now_defaults_to_BLOCKING(self) -> None:
        """Deliberately inverted after the sandboxed free build disproved the old default.

        The original reasoning was "a wedged Resolve needs a force-quit, a dead
        bridge does not". Correct in the abstract, wrong in practice: the only
        case that actually produces an unreadable parent is the App Store
        sandbox, and that case IS a child process. Not blocking there gives a
        listener that never survives its own startup.
        """
        model = rb._host_model(
            getppid=lambda: 9, process_name_of=lambda pid: "", self_executable="/usr/bin/fuscript"
        )
        self.assertTrue(model["blocking_required"])

    def test_probe_reports_without_starting_anything(self) -> None:
        probe = rb.probe_host_model()
        self.assertIn(probe["model"], ("child_process", "in_process"))
        self.assertEqual(probe["pid"], os.getpid())
        self.assertEqual(probe["protocol_version"], rb.PROTOCOL_VERSION)


class DispatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = []

        def dispatch(operation, arguments):
            self.calls.append((operation, arguments))
            if operation == "boom":
                raise RuntimeError("resolve said no")
            return {"operation": operation}

        self.bridge = rb.Bridge(
            resolve=object(),
            config={"host": "127.0.0.1", "port": 49632, "token": TOKEN, "auth_clock_skew_seconds": 60},
            dispatch=dispatch,
        )

    def test_an_authentic_request_dispatches(self) -> None:
        response = self.bridge.process(signed(TOKEN, timestamp=int(__import__("time").time()), nonce="a" * 20))
        self.assertTrue(response["ok"])
        self.assertEqual(self.calls, [("health", {})])

    def test_an_unauthenticated_request_never_reaches_dispatch(self) -> None:
        request = signed("wrong" * 12, timestamp=int(__import__("time").time()), nonce="b" * 20)
        response = self.bridge.process(request)
        self.assertFalse(response["ok"])
        self.assertEqual(self.calls, [])

    def test_a_failing_operation_returns_an_error_not_a_traceback(self) -> None:
        request = signed(TOKEN, timestamp=int(__import__("time").time()), nonce="c" * 20, operation="boom")
        response = self.bridge.process(request)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "operation_failed")
        self.assertIn("resolve said no", response["error"]["message"])

    def test_a_malformed_operation_is_refused(self) -> None:
        request = {
            "protocol": rb.PROTOCOL_VERSION, "id": "1",
            "timestamp": int(__import__("time").time()), "nonce": "d" * 20,
            "operation": 42, "arguments": {},
        }
        request["signature"] = rb.sign_request(TOKEN, request)
        self.assertEqual(self.bridge.process(request)["error"]["code"], "invalid_request")

    def test_connection_slots_are_bounded(self) -> None:
        taken = [self.bridge.acquire_slot() for _ in range(rb.MAX_CONCURRENT_CONNECTIONS)]
        self.assertTrue(all(taken))
        self.assertFalse(self.bridge.acquire_slot(), "an unauthenticated flood must not be unbounded")
        for _ in taken:
            self.bridge.release_slot()
        self.assertTrue(self.bridge.acquire_slot())
        self.bridge.release_slot()

    def test_preauth_bounds_are_set(self) -> None:
        self.assertLessEqual(rb.PREAUTH_READ_TIMEOUT_S, 10.0)
        self.assertLessEqual(rb.MAX_REQUEST_BYTES, 8 * 1024 * 1024)


class StdlibOnlyTests(unittest.TestCase):
    def test_the_bridge_imports_nothing_the_embedded_interpreter_lacks(self) -> None:
        """It is copied into Resolve's Scripts folder and must import there."""
        import ast
        import pathlib

        source = pathlib.Path(rb.__file__).read_text(encoding="utf-8")
        allowed = {
            "hashlib", "hmac", "json", "os", "re", "socket", "socketserver",
            "stat", "sys", "threading", "time", "collections", "typing",
            "subprocess", "__future__",
        }
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], allowed, alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                self.assertIn(node.module.split(".")[0], allowed, node.module)


if __name__ == "__main__":
    unittest.main()


class FakeResolve:
    """Minimal stand-in for Resolve's proxy object graph."""

    def __init__(self, *, product="DaVinci Resolve", timelines=("Cut v1",), clips=(), fail=()):
        self.product = product
        self._timelines = list(timelines)
        self._clips = list(clips)
        self._fail = set(fail)
        self.saved = False
        self.current_timeline = self._timelines[0] if self._timelines else None

    # resolve
    def GetProductName(self): return self.product
    def GetVersionString(self): return "21.0.0"
    def GetCurrentPage(self): return "edit"
    def GetProjectManager(self): return self

    # project manager
    def GetCurrentProject(self): return None if "no_project" in self._fail else self
    def GetCurrentFolder(self): return "root"
    def GetCurrentDatabase(self): return {"DbName": "local", "IpAddress": "10.0.0.5"}
    def GetProjectListInCurrentFolder(self): return ["Alpha", "Beta"]
    def SaveProject(self):
        if "save" in self._fail:
            return False
        self.saved = True
        return True

    # project
    def GetName(self): return "Alpha"
    def GetTimelineCount(self): return len(self._timelines)
    def GetTimelineByIndex(self, index):
        try:
            return _FakeTimeline(self._timelines[index - 1])
        except IndexError:
            return None
    def GetCurrentTimeline(self):
        return _FakeTimeline(self.current_timeline) if self.current_timeline else None
    def SetCurrentTimeline(self, timeline):
        self.current_timeline = timeline.GetName()
        return True
    def GetMediaPool(self): return self
    def GetRenderFormats(self): return {"QuickTime": "mov"}
    def GetCurrentRenderFormatAndCodec(self): return {"format": "mov", "codec": "H.264"}

    # media pool
    def GetRootFolder(self): return _FakeFolder(self._clips)


class _FakeTimeline:
    def __init__(self, name): self._name = name
    def GetName(self): return self._name
    def GetUniqueId(self): return f"tl-{self._name}"
    def GetStartFrame(self): return 0
    def GetEndFrame(self): return 240
    def GetStartTimecode(self): return "01:00:00:00"
    def GetTrackCount(self, kind): return 1 if kind == "video" else 0
    def GetTrackName(self, kind, index): return f"{kind}{index}"
    def GetIsTrackEnabled(self, kind, index): return True
    def GetIsTrackLocked(self, kind, index): return False


class _FakeFolder:
    def __init__(self, clips): self._clips = clips
    def GetUniqueId(self): return "root"
    def GetClipList(self): return [_FakeClip(*c) for c in self._clips]
    def GetSubFolderList(self): return []


class _FakeClip:
    def __init__(self, name, path): self._name, self._path = name, path
    def GetName(self): return self._name
    def GetUniqueId(self): return f"clip-{self._name}"
    def GetClipProperty(self): return {"File Path": self._path, "Duration": "00:00:10:00", "FPS": "24"}


class OperationSurfaceTests(unittest.TestCase):
    import tempfile as _tf
    ROOT = _tf.mkdtemp(prefix="bridge_ops_")

    def _ops(self, **kw):
        from src.utils import resolve_bridge_ops as ops
        return ops.ResolveOperations(
            kw.pop("resolve", None) or FakeResolve(**kw),
            media_roots=[self.ROOT], output_roots=[self.ROOT],
        )

    def test_an_unlisted_operation_is_refused_with_the_available_list(self) -> None:
        from src.utils import resolve_bridge_ops as ops
        with self.assertRaises(ops.OperationError) as ctx:
            self._ops().dispatch("DeleteProject", {})
        self.assertEqual(ctx.exception.code, "operation_not_allowed")
        self.assertIn("health", ctx.exception.details["available"])

    def test_no_destructive_verb_is_exposed(self) -> None:
        from src.utils import resolve_bridge_ops as ops
        surface = " ".join(ops.ResolveOperations.OPERATIONS).lower()
        for verb in ("delete", "remove", "import", "export", "archive", "close"):
            self.assertNotIn(verb, surface, f"{verb!r} must not be on the bridge surface")

    def test_health_advertises_the_surface_so_it_is_discoverable(self) -> None:
        health = self._ops().dispatch("health", {})
        from src.utils import resolve_bridge_ops as ops
        self.assertEqual(set(health["operations"]), set(ops.ResolveOperations.OPERATIONS))
        self.assertEqual(health["edition"], "free")

    def test_studio_edition_is_detected(self) -> None:
        health = self._ops(product="DaVinci Resolve Studio").dispatch("health", {})
        self.assertEqual(health["edition"], "studio")

    def test_database_ip_address_is_not_leaked(self) -> None:
        listing = self._ops().dispatch("list_projects", {})
        self.assertNotIn("IpAddress", listing["database"])
        self.assertIn("DbName", listing["database"])

    def test_media_paths_outside_the_roots_are_not_leaked(self) -> None:
        import os
        inside = os.path.join(self.ROOT, "a.mov")
        open(inside, "w").close()
        ops = self._ops(clips=[("inside", inside), ("outside", "/etc/passwd")])
        by_name = {c["name"]: c["file_path"] for c in ops.dispatch("list_media", {})["clips"]}
        # Resolve's own path is returned verbatim (it is what relinking needs);
        # only the visibility *check* resolves symlinks, which is why a
        # /var -> /private/var fixture still reads as inside the root.
        self.assertEqual(by_name["inside"], inside)
        self.assertEqual(by_name["outside"], "<outside-allowed-roots>")

    def test_a_false_return_is_an_error_not_a_success(self) -> None:
        from src.utils import resolve_bridge_ops as ops
        with self.assertRaises(ops.OperationError) as ctx:
            self._ops(fail=["save"]).dispatch("save_project", {})
        self.assertEqual(ctx.exception.code, "operation_failed")

    def test_no_open_project_is_refused_clearly(self) -> None:
        from src.utils import resolve_bridge_ops as ops
        with self.assertRaises(ops.OperationError) as ctx:
            self._ops(fail=["no_project"]).dispatch("get_project", {})
        self.assertEqual(ctx.exception.code, "no_project")

    def test_duplicate_timeline_names_are_ambiguous_not_arbitrary(self) -> None:
        from src.utils import resolve_bridge_ops as ops
        with self.assertRaises(ops.OperationError) as ctx:
            self._ops(timelines=["Cut", "Cut"]).dispatch("get_timeline", {"timeline_name": "Cut"})
        self.assertEqual(ctx.exception.code, "ambiguous_locator")

    def test_a_missing_timeline_is_not_found(self) -> None:
        from src.utils import resolve_bridge_ops as ops
        with self.assertRaises(ops.OperationError) as ctx:
            self._ops().dispatch("get_timeline", {"timeline_name": "Nope"})
        self.assertEqual(ctx.exception.code, "not_found")

    def test_set_current_timeline_requires_a_name(self) -> None:
        from src.utils import resolve_bridge_ops as ops
        with self.assertRaises(ops.OperationError):
            self._ops().dispatch("set_current_timeline", {})

    def test_reads_and_writes_are_separately_enumerated(self) -> None:
        from src.utils import resolve_bridge_ops as ops
        self.assertFalse(set(ops.ResolveOperations.READ_OPERATIONS) & set(ops.ResolveOperations.WRITE_OPERATIONS))
        self.assertLess(
            len(ops.ResolveOperations.WRITE_OPERATIONS),
            len(ops.ResolveOperations.READ_OPERATIONS),
            "the write surface must stay narrower than the read surface",
        )

    def test_listings_are_bounded(self) -> None:
        ops = self._ops(timelines=[f"T{i}" for i in range(50)])
        ops.max_items = 5
        listing = ops.dispatch("list_timelines", {})
        self.assertEqual(len(listing["timelines"]), 5)
        self.assertTrue(listing["truncated"])

    def test_path_policy_rejects_traversal_and_relative_paths(self) -> None:
        from src.utils import resolve_bridge_ops as ops
        policy = ops.PathPolicy([self.ROOT], [self.ROOT])
        for bad in ("relative.mov", "/etc/passwd", ""):
            with self.subTest(path=bad):
                with self.assertRaises(ops.OperationError):
                    policy.input_file(bad)

    def test_the_ops_module_is_stdlib_only(self) -> None:
        import ast, pathlib
        from src.utils import resolve_bridge_ops as ops
        allowed = {"os", "typing", "collections", "__future__"}
        tree = ast.parse(pathlib.Path(ops.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], allowed, alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                self.assertIn(node.module.split(".")[0], allowed, node.module)


class BridgeIntegrationTests(unittest.TestCase):
    """Transport + surface together, over a real loopback socket."""

    def test_a_signed_request_reaches_the_operation_surface(self) -> None:
        import socket as _socket
        import tempfile as _tempfile
        import time as _time
        from src.utils import resolve_bridge_ops as rbo

        root = _tempfile.mkdtemp(prefix="bridge_int_")
        operations = rbo.ResolveOperations(FakeResolve(), media_roots=[root], output_roots=[root])
        config = {"host": "127.0.0.1", "port": 0, "token": TOKEN, "auth_clock_skew_seconds": 60}
        bridge = rb.Bridge(FakeResolve(), config, rbo.make_dispatch(operations))
        bridge.start()
        self.addCleanup(bridge.stop)

        def roundtrip(request):
            with _socket.create_connection(("127.0.0.1", bridge.port), timeout=5) as sock:
                sock.sendall((json.dumps(request) + "\n").encode())
                return json.loads(sock.makefile("rb").readline().decode())

        good = signed(TOKEN, timestamp=int(_time.time()), nonce="i" * 24)
        response = roundtrip(good)
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["connected"], True)

        # Same bytes again: the nonce is spent.
        self.assertEqual(roundtrip(good)["error"]["code"], "replayed_request")

        # Wrong token never reaches the surface.
        bad = signed("z" * 48, timestamp=int(_time.time()), nonce="j" * 24)
        self.assertEqual(roundtrip(bad)["error"]["code"], "unauthorized")

        # An unlisted operation is refused by the surface, not executed.
        blocked = signed(TOKEN, timestamp=int(_time.time()), nonce="k" * 24, operation="DeleteProject")
        self.assertEqual(roundtrip(blocked)["error"]["code"], "operation_failed")


class InstallerTargetTests(unittest.TestCase):
    """Where the bridge gets installed — corrected against a real App Store build.

    A sandboxed container is a virtualized HOME, so Resolve's documented per-user
    path applies *unchanged* beneath `<container>/Data/`. Two traps were hit for
    real and are pinned here:

    1. `<container>/Data/Library/Application Support/Fusion/Scripts/Utility`
       exists and is pre-scaffolded — but it is Fusion's standalone tree, not
       Resolve's, and Resolve does not scan it.
    2. Resolve does not create its own tree until a script is installed, so
       requiring the target to pre-exist skips the free edition entirely.
    """

    def setUp(self) -> None:
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "scripts"))
        import install_resolve_bridge
        self.installer = install_resolve_bridge

    def test_the_sandbox_path_keeps_the_vendor_segment(self) -> None:
        # The decoy drops it; Resolve's documented path does not.
        self.assertIn("Blackmagic Design/DaVinci Resolve", self.installer._SCRIPTS_SUFFIX)

    def test_a_container_is_targeted_even_when_the_tree_does_not_exist(self) -> None:
        import pathlib
        import tempfile
        from unittest import mock

        home = pathlib.Path(tempfile.mkdtemp(prefix="fake_home_"))
        container = home / "Library/Containers/com.blackmagic-design.DaVinciResolveLite"
        (container / "Data").mkdir(parents=True)  # container only; NO Fusion tree
        with mock.patch.object(pathlib.Path, "home", staticmethod(lambda: home)):
            targets = self.installer.script_targets()
        expected = container / "Data" / self.installer._SCRIPTS_SUFFIX
        self.assertIn(expected, targets, f"container skipped because its tree is absent: {targets}")

    def test_the_fusion_standalone_tree_is_not_mistaken_for_resolves(self) -> None:
        import pathlib
        import tempfile
        from unittest import mock

        home = pathlib.Path(tempfile.mkdtemp(prefix="fake_home_"))
        container = home / "Library/Containers/com.blackmagic-design.DaVinciResolveLite"
        # The decoy, pre-scaffolded exactly as a real install has it.
        (container / "Data/Library/Application Support/Fusion/Scripts/Utility").mkdir(parents=True)
        with mock.patch.object(pathlib.Path, "home", staticmethod(lambda: home)):
            targets = self.installer.script_targets()
        for target in targets:
            if "Containers" in str(target):
                self.assertIn("Blackmagic Design", str(target), f"decoy path selected: {target}")

    def test_non_resolve_blackmagic_containers_are_ignored(self) -> None:
        import pathlib
        import tempfile
        from unittest import mock

        home = pathlib.Path(tempfile.mkdtemp(prefix="fake_home_"))
        for name in ("com.blackmagic-design.BlackmagicRawPlayer", "com.blackmagic-design.IOXPC"):
            (home / "Library/Containers" / name / "Data").mkdir(parents=True)
        with mock.patch.object(pathlib.Path, "home", staticmethod(lambda: home)):
            targets = self.installer.script_targets()
        self.assertFalse(
            [t for t in targets if "RawPlayer" in str(t) or "IOXPC" in str(t)],
            f"a non-Resolve Blackmagic container was targeted: {targets}",
        )

    def test_the_probe_is_self_contained(self) -> None:
        """It is copied into Resolve's Scripts folder, where the repo is not
        importable. An import from src/ would raise in Resolve's console."""
        import ast
        import pathlib

        probe = pathlib.Path(__file__).resolve().parents[1] / "scripts/resolve_bridge_probe.py"
        tree = ast.parse(probe.read_text(encoding="utf-8"))
        allowed = {"json", "os", "subprocess", "sys", "time", "DaVinciResolveScript"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], allowed, alias.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertIsNotNone(node.module)
                self.assertIn(node.module.split(".")[0], allowed, node.module)
        self.assertNotIn("src.utils", probe.read_text(encoding="utf-8"))

    def test_probe_and_bridge_agree_on_the_parent_markers(self) -> None:
        """The detection is duplicated for self-containment; it must not drift.

        Parses the probe's own PARENT_MARKERS literal and compares it to the
        bridge's — so changing one without the other fails here rather than
        producing a probe that answers a different question from the runtime.
        """
        import ast
        import pathlib

        probe_path = pathlib.Path(__file__).resolve().parents[1] / "scripts/resolve_bridge_probe.py"
        tree = ast.parse(probe_path.read_text(encoding="utf-8"))
        probe_markers = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "PARENT_MARKERS" for t in node.targets
            ):
                probe_markers = tuple(ast.literal_eval(node.value))
        self.assertIsNotNone(probe_markers, "probe has no PARENT_MARKERS to compare")
        self.assertEqual(tuple(rb.PARENT_MARKERS), probe_markers)

    def test_framework_python_detection_drives_the_preflight(self) -> None:
        """Resolve lists .py scripts only with a framework Python — silently."""
        from unittest import mock

        with mock.patch.object(self.installer, "framework_pythons", lambda: []):
            preflight = self.installer.python_preflight()
        self.assertFalse(preflight["resolve_will_list_python_scripts"])
        self.assertIn("python.org", preflight["advice"])
        self.assertIn("silently", preflight["advice"])

        with mock.patch.object(
            self.installer, "framework_pythons",
            lambda: ["/Library/Frameworks/Python.framework/Versions/3.11"],
        ):
            preflight = self.installer.python_preflight()
        self.assertTrue(preflight["resolve_will_list_python_scripts"])
        self.assertIsNone(preflight["advice"])

    def test_homebrew_python_does_not_count_as_a_framework_install(self) -> None:
        # The exact trap: three Homebrew interpreters on PATH and Resolve sees none.
        for root in self.installer._FRAMEWORK_PYTHON_ROOTS:
            self.assertNotIn("homebrew", str(root).lower())
            self.assertIn("Python.framework", str(root))

    def test_a_lua_canary_ships_with_every_probe(self) -> None:
        # Lua always enumerates, so the canary separates "Python not detected"
        # from "wrong folder" — the ambiguity that cost four restarts.
        self.assertIn("framework Python", self.installer._LUA_CANARY)
        self.assertIn("print(", self.installer._LUA_CANARY)


class ObservedHostModelTests(unittest.TestCase):
    """Pinned to a real Scripts-menu run, not a guess.

    Measured 2026-07-29 on DaVinci Resolve Studio 19.1.3.7: a Workspace > Scripts
    script runs as a **child process** of Resolve (script pid 97209, parent pid
    97175 = Resolve itself), and the live `resolve` object is available to it.

    This settles the design question the bridge was built around. A daemon thread
    would die the instant the script returns, so the listener MUST block.
    """

    OBSERVED_PARENT = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve"

    def test_the_observed_parent_selects_the_blocking_branch(self) -> None:
        model = rb._host_model(
            getppid=lambda: 97175, process_name_of=lambda pid: self.OBSERVED_PARENT
        )
        self.assertEqual(model["model"], "child_process")
        self.assertTrue(model["blocking_required"])

    def test_a_full_path_parent_is_matched_not_just_a_bare_name(self) -> None:
        # Resolve reports an absolute path, not "Resolve" — substring matching
        # is load-bearing here, and an exact-name comparison would have failed.
        self.assertNotEqual(self.OBSERVED_PARENT, "Resolve")
        self.assertTrue(
            any(m in self.OBSERVED_PARENT.lower() for m in rb.PARENT_MARKERS)
        )

    def test_serve_blocks_for_a_child_process_host(self) -> None:
        """The branch that would have been wrong: returning instead of blocking."""
        model = rb._host_model(
            getppid=lambda: 97175, process_name_of=lambda pid: self.OBSERVED_PARENT
        )
        self.assertTrue(
            model["blocking_required"],
            "serve() would return immediately and the listener would die with the script",
        )

    OBSERVED_FREE_PARENT_PID = 97258   # sandbox: name unreadable, but a real child

    def test_sandboxed_free_build_is_detected_as_a_child_despite_no_parent_name(self) -> None:
        """The bug this replaced: parent-name detection fails under the sandbox.

        Measured on DaVinci Resolve 21.0.3.7 (App Store, free): script pid 97667,
        parent pid 97258, parent name unreadable because `ps` on another process
        is blocked. The old parent-name logic concluded "in_process" and would
        have started a listener that dies the instant the script returns — on the
        one edition the bridge exists for.
        """
        model = rb._host_model(
            getppid=lambda: self.OBSERVED_FREE_PARENT_PID,
            process_name_of=lambda pid: "",  # sandbox blocks it
            self_executable="/Applications/DaVinci Resolve.app/Contents/Libraries/Fusion/fuscript",
        )
        self.assertEqual(model["model"], "child_process")
        self.assertTrue(model["blocking_required"], "sandboxed free build must still block")
        self.assertFalse(model["parent_corroborates"])
        self.assertIn("sandbox", model["reason"])

    def test_only_resolve_itself_counts_as_in_process(self) -> None:
        for executable, expect_in_process in (
            ("/Applications/DaVinci Resolve.app/Contents/MacOS/Resolve", True),
            ("/Applications/DaVinci Resolve.app/Contents/Libraries/Fusion/fuscript", False),
            ("/Library/Frameworks/Python.framework/Versions/3.11/bin/python3", False),
            ("", False),
        ):
            with self.subTest(executable=executable):
                model = rb._host_model(
                    getppid=lambda: 1, process_name_of=lambda pid: "", self_executable=executable
                )
                self.assertEqual(model["model"] == "in_process", expect_in_process)

    def test_an_unknown_interpreter_blocks_rather_than_returning(self) -> None:
        # The safer default, inverted from the original: a bridge that exits
        # early can be restarted; a listener that never starts cannot.
        model = rb._host_model(
            getppid=lambda: 9, process_name_of=lambda pid: "", self_executable="/usr/bin/mystery"
        )
        self.assertTrue(model["blocking_required"])


class ProxyTests(unittest.TestCase):
    """The proxy exists so existing call sites need no changes. That is the test."""

    @classmethod
    def setUpClass(cls) -> None:
        import tempfile
        from src.utils import resolve_bridge_client as rbc
        from src.utils import resolve_bridge_ops as rbo

        cls.rbc, cls.rbo = rbc, rbo
        cls.root = tempfile.mkdtemp(prefix="proxy_")
        cls.fake = FakeResolve(timelines=["Cut v1", "Cut v2"], clips=[("a", cls.root + "/a.mov")])
        cls.ops = rbo.ResolveOperations(cls.fake, media_roots=[cls.root], output_roots=[cls.root])
        config = {"host": "127.0.0.1", "port": 0, "token": TOKEN, "auth_clock_skew_seconds": 60}
        cls.bridge = rb.Bridge(cls.fake, config, rbo.make_dispatch(cls.ops))
        cls.bridge.start()
        cls.transport = rbc.BridgeTransport({**config, "port": cls.bridge.port})
        cls.resolve = rbc.BridgeProxy(cls.transport, "resolve")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.bridge.stop()

    def test_a_native_style_chain_works_unmodified(self) -> None:
        # Verbatim the shape existing code uses against the real API.
        name = self.resolve.GetProjectManager().GetCurrentProject().GetName()
        self.assertEqual(name, "Alpha")

    def test_scalars_come_back_as_scalars(self) -> None:
        project = self.resolve.GetProjectManager().GetCurrentProject()
        self.assertEqual(project.GetTimelineCount(), 2)
        self.assertEqual(self.resolve.GetProductName(), "DaVinci Resolve")

    def test_live_objects_come_back_as_proxies(self) -> None:
        manager = self.resolve.GetProjectManager()
        self.assertIsInstance(manager, self.rbc.BridgeProxy)

    def test_a_proxy_can_be_passed_back_as_an_argument(self) -> None:
        project = self.resolve.GetProjectManager().GetCurrentProject()
        timeline = project.GetTimelineByIndex(2)
        self.assertTrue(project.SetCurrentTimeline(timeline))
        self.assertEqual(self.fake.current_timeline, "Cut v2")

    def test_dicts_and_lists_survive_the_round_trip(self) -> None:
        project = self.resolve.GetProjectManager().GetCurrentProject()
        formats = project.GetRenderFormats()
        self.assertIsInstance(formats, dict)
        self.assertEqual(formats.get("QuickTime"), "mov")
        self.assertIn("Alpha", self.resolve.GetProjectManager().GetProjectListInCurrentFolder())

    def test_false_is_passed_through_not_raised(self) -> None:
        """Transparency includes the ugly parts.

        Resolve signals failure with False constantly, and every existing call
        site was written knowing that. Raising here would silently change the
        meaning of code that already handles it.
        """
        failing = FakeResolve(fail=["save"])
        ops = self.rbo.ResolveOperations(failing, media_roots=[self.root], output_roots=[self.root])
        config = {"host": "127.0.0.1", "port": 0, "token": TOKEN, "auth_clock_skew_seconds": 60}
        bridge = rb.Bridge(failing, config, self.rbo.make_dispatch(ops))
        bridge.start()
        self.addCleanup(bridge.stop)
        proxy = self.rbc.BridgeProxy(self.rbc.BridgeTransport({**config, "port": bridge.port}), "resolve")
        self.assertIs(proxy.GetProjectManager().SaveProject(), False)

    def test_dunder_access_never_goes_over_the_wire(self) -> None:
        """Dunders resolve locally or fail locally — never as a proxied call.

        Note `__reduce__` and friends ARE found: they exist on `object`, so
        normal lookup succeeds before `__getattr__` runs. That is fine — they are
        real local methods, not requests. What matters is that an *unknown*
        dunder fails locally instead of being sent, and that the bridge refuses
        underscore-prefixed method names regardless of what a client asks for.
        """
        with self.assertRaises(AttributeError):
            self.resolve.__nonexistent_dunder__
        with self.assertRaises(self.rbo.OperationError):
            self.ops.dispatch("call", {"target": "resolve", "method": "__class__"})
        with self.assertRaises(self.rbo.OperationError):
            self.ops.dispatch("call", {"target": "resolve", "method": "_private"})

    def test_only_bridge_minted_handles_resolve(self) -> None:
        for bogus in ("h:deadbeef:1", "arbitrary", "sys", ""):
            with self.subTest(target=bogus):
                with self.assertRaises(self.rbo.OperationError):
                    self.ops.dispatch("call", {"target": bogus, "method": "GetName"})

    def test_a_missing_method_reports_capability_not_success(self) -> None:
        with self.assertRaises(self.rbo.OperationError) as ctx:
            self.ops.dispatch("call", {"target": "resolve", "method": "NoSuchMethod"})
        self.assertEqual(ctx.exception.code, "capability_unavailable")

    def test_the_handle_table_is_bounded(self) -> None:
        ops = self.rbo.ResolveOperations(
            FakeResolve(timelines=[f"T{i}" for i in range(20)]),
            media_roots=[self.root], output_roots=[self.root],
        )
        ops.MAX_HANDLES = 8
        for _ in range(50):
            ops.dispatch("call", {"target": "resolve", "method": "GetProjectManager"})
        self.assertLessEqual(len(ops._handles), 8, "unbounded table pins Resolve objects forever")

    def test_an_evicted_handle_reports_stale_rather_than_wrong(self) -> None:
        ops = self.rbo.ResolveOperations(
            FakeResolve(), media_roots=[self.root], output_roots=[self.root]
        )
        ops.MAX_HANDLES = 2
        first = ops.dispatch("call", {"target": "resolve", "method": "GetProjectManager"})
        handle = first["value"]["__handle__"]
        for _ in range(5):
            ops.dispatch("call", {"target": "resolve", "method": "GetProjectManager"})
        with self.assertRaises(self.rbo.OperationError) as ctx:
            ops.dispatch("call", {"target": handle, "method": "GetName"})
        self.assertEqual(ctx.exception.code, "stale_handle")

    def test_handles_are_session_scoped(self) -> None:
        # A handle from one bridge run must never resolve against another.
        a = self.rbo.ResolveOperations(FakeResolve(), media_roots=[self.root], output_roots=[self.root])
        b = self.rbo.ResolveOperations(FakeResolve(), media_roots=[self.root], output_roots=[self.root])
        handle = a.dispatch("call", {"target": "resolve", "method": "GetProjectManager"})["value"]["__handle__"]
        with self.assertRaises(self.rbo.OperationError) as ctx:
            b.dispatch("call", {"target": handle, "method": "GetName"})
        self.assertEqual(ctx.exception.code, "stale_handle")

    def test_release_handles_frees_them(self) -> None:
        self.resolve.GetProjectManager().GetCurrentProject()
        released = self.resolve.bridge_release_handles()
        self.assertTrue(released["all"])
        self.assertGreater(released["released"], 0)

    def test_an_unauthenticated_proxy_cannot_call(self) -> None:
        bad = self.rbc.BridgeTransport(
            {"host": "127.0.0.1", "port": self.bridge.port, "token": "x" * 48,
             "auth_clock_skew_seconds": 60}
        )
        with self.assertRaises(self.rbc.BridgeCallError) as ctx:
            self.rbc.BridgeProxy(bad, "resolve").GetProductName()
        self.assertEqual(ctx.exception.code, "unauthorized")

    def test_no_bridge_raises_unavailable_rather_than_returning_none(self) -> None:
        # Returning None would let a caller mistake "no bridge" for "no Resolve".
        dead = self.rbc.BridgeTransport(
            {"host": "127.0.0.1", "port": 9, "token": TOKEN, "auth_clock_skew_seconds": 60},
            timeout=1.0,
        )
        with self.assertRaises(self.rbc.BridgeUnavailable):
            self.rbc.BridgeProxy(dead, "resolve").GetProductName()


class BridgeOptInTests(unittest.TestCase):
    def test_the_bridge_is_opt_in(self) -> None:
        from unittest import mock
        from src.utils import resolve_bridge_client as rbc

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(rbc.bridge_enabled())
        for value in ("1", "true", "YES", "on"):
            with mock.patch.dict(os.environ, {rbc.ENV_ENABLE: value}):
                self.assertTrue(rbc.bridge_enabled(), value)

    def test_connect_refuses_when_not_enabled(self) -> None:
        from unittest import mock
        from src.utils import resolve_bridge_client as rbc

        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(rbc.BridgeUnavailable) as ctx:
                rbc.connect()
        self.assertIn("opt-in", str(ctx.exception))

    def test_connect_resolve_does_not_change_behaviour_when_disabled(self) -> None:
        from unittest import mock
        from src.utils import resolve_connection

        calls = []

        class FakeScript:
            def scriptapp(self, *args):
                calls.append(args)
                return "native-handle"

        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_connection.connect_resolve(FakeScript()), "native-handle")
        self.assertEqual(calls, [("Resolve",)])
