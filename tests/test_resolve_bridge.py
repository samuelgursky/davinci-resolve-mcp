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
import time
import unittest
from pathlib import Path

from src.utils import resolve_bridge as rb

REPO = Path(__file__).resolve().parent.parent


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
            # ctypes reads Win32 process liveness (issue #112). Core stdlib, and
            # every use is inside a function under try/except, so an interpreter
            # built without it degrades to "liveness unknown" — which the module
            # already treats as "keep serving" — rather than failing to import.
            "ctypes",
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
        open(inside, "w", encoding="utf-8").close()
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
        refusal = roundtrip(blocked)["error"]
        # The surface's own code, not a flattened `operation_failed`. This
        # assertion previously read `operation_failed` and so enshrined the
        # opposite: `process()` was discarding every code the surface chose, and
        # no test caught it because every other code assertion in this file calls
        # `ops.dispatch` directly and never crosses the transport.
        self.assertEqual(refusal["code"], "operation_not_allowed")
        self.assertIn("health", refusal["details"]["available"])

    def test_surface_error_codes_survive_the_transport(self) -> None:
        """A client acts on the code; a client that only ever sees one cannot.

        `stale_handle` means re-fetch, `ambiguous_locator` means disambiguate,
        `no_project` means open something. Flattened to `operation_failed` they
        are one undifferentiated failure and a string to pattern-match.
        """
        import socket as _socket
        import tempfile as _tempfile
        import time as _time
        from src.utils import resolve_bridge_ops as rbo

        root = _tempfile.mkdtemp(prefix="bridge_codes_")
        fake = FakeResolve(timelines=["Cut", "Cut"])
        operations = rbo.ResolveOperations(fake, media_roots=[root], output_roots=[root])
        config = {"host": "127.0.0.1", "port": 0, "token": TOKEN, "auth_clock_skew_seconds": 60}
        bridge = rb.Bridge(fake, config, rbo.make_dispatch(operations))
        bridge.start()
        self.addCleanup(bridge.stop)

        cases = [
            ("get_timeline", {"timeline_name": "Cut"}, "ambiguous_locator"),
            ("get_timeline", {"timeline_name": "Nope"}, "not_found"),
            ("call", {"target": "h:dead:1", "method": "GetName"}, "stale_handle"),
            ("call", {"target": "resolve", "method": "__class__"}, "method_not_allowed"),
            ("shutdown", {}, "capability_unavailable"),
        ]
        for index, (operation, arguments, expected) in enumerate(cases):
            request = {
                "protocol": rb.PROTOCOL_VERSION, "id": str(index),
                "timestamp": int(_time.time()), "nonce": f"c{index:0>23}",
                "operation": operation, "arguments": arguments,
            }
            request["signature"] = rb.sign_request(TOKEN, request)
            with self.subTest(operation=operation, expected=expected):
                with _socket.create_connection(("127.0.0.1", bridge.port), timeout=5) as sock:
                    sock.sendall((json.dumps(request) + "\n").encode())
                    response = json.loads(sock.makefile("rb").readline().decode())
                self.assertEqual(response["error"]["code"], expected, response)


class InstallerTargetTests(unittest.TestCase):
    """Where the bridge gets installed — corrected against real App Store builds.

    A sandboxed container is a virtualized HOME, so Resolve's documented per-user
    path applies *unchanged* beneath `<container>/Data/`. Three traps were hit
    for real and are pinned here:

    1. Which container tree Lite actually scans is not decidable from outside
       Resolve: on one free 21.0.3.7 install the documented tree listed and on
       another it listed nothing while the Fusion standalone tree worked
       (issue #104). Both are targeted; the documented one goes first.
    2. Resolve does not create its own tree until a script is installed, so
       requiring the target to pre-exist skips the free edition entirely.
    3. A container outlives the app that created it, so its existence is not
       proof the edition is installed.
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

    def test_both_container_trees_are_targeted_documented_one_first(self) -> None:
        """Issue #104: the documented tree silently listed nothing on a real
        free 21.0.3.7 App Store install while the Fusion standalone tree worked,
        the exact opposite of the machine this installer was first measured on.
        Neither is reliably detectable from outside Resolve, so install to both
        rather than guess — but keep the documented path first, since that is
        the one Blackmagic actually commits to."""
        import pathlib
        import tempfile
        from unittest import mock

        home = pathlib.Path(tempfile.mkdtemp(prefix="fake_home_"))
        container = home / "Library/Containers/com.blackmagic-design.DaVinciResolveLite"
        (container / "Data").mkdir(parents=True)
        with mock.patch.object(pathlib.Path, "home", staticmethod(lambda: home)):
            targets = self.installer.script_targets()

        documented = container / "Data" / self.installer._SCRIPTS_SUFFIX
        fallback = container / "Data" / self.installer._SANDBOX_FALLBACK_SUFFIX
        self.assertIn(documented, targets)
        self.assertIn(fallback, targets, f"standalone tree not targeted: {targets}")
        self.assertLess(
            targets.index(documented), targets.index(fallback),
            "the documented tree must be installed first",
        )

    def test_the_fusion_standalone_tree_is_only_targeted_inside_a_container(self) -> None:
        """Outside a sandbox this really is Fusion's own tree and has nothing to
        do with Resolve — the dual-target fix must not leak out of the
        container."""
        import pathlib
        import tempfile
        from unittest import mock

        home = pathlib.Path(tempfile.mkdtemp(prefix="fake_home_"))
        (home / self.installer._SANDBOX_FALLBACK_SUFFIX).mkdir(parents=True)
        with mock.patch.object(pathlib.Path, "home", staticmethod(lambda: home)):
            targets = self.installer.script_targets()
        self.assertNotIn(
            home / self.installer._SANDBOX_FALLBACK_SUFFIX, targets,
            f"Fusion's standalone tree targeted outside a container: {targets}",
        )

    def test_a_container_with_no_app_bundle_warns_instead_of_reporting_success(self) -> None:
        """Issue #104: uninstalling Resolve leaves the container behind, and the
        container's existence is what makes us target it — so --probe-only
        reported a clean success on a machine with no Resolve at all."""
        import pathlib
        from unittest import mock

        targets = [pathlib.Path("/Users/x/Library/Containers/com.blackmagic-design.DaVinciResolveLite/Data/x")]
        with mock.patch.object(self.installer, "installed_app_bundles", lambda: []):
            warning = self.installer.stale_container_warning(targets)
        self.assertIsNotNone(warning, "a stale container reported success")
        self.assertIn("outlives", warning.lower())

    def test_no_stale_warning_when_an_app_bundle_is_present(self) -> None:
        import pathlib
        from unittest import mock

        targets = [pathlib.Path("/Users/x/Library/Containers/com.blackmagic-design.DaVinciResolveLite/Data/x")]
        with mock.patch.object(
            self.installer, "installed_app_bundles",
            lambda: ["/Applications/DaVinci Resolve.app"],
        ):
            self.assertIsNone(self.installer.stale_container_warning(targets))

    def test_no_stale_warning_without_container_targets(self) -> None:
        """A normal install has no container in play; the app-bundle check is
        specific to the sandbox case and must not fire on Studio."""
        import pathlib
        from unittest import mock

        with mock.patch.object(self.installer, "installed_app_bundles", lambda: []):
            self.assertIsNone(
                self.installer.stale_container_warning(
                    [pathlib.Path("/Library/Application Support/Blackmagic Design/x")]
                )
            )

    def test_resolve_app_env_var_overrides_the_bundle_search(self) -> None:
        """Consistent with scripts/doctor.py, which already honors RESOLVE_APP —
        an install on an external volume must be able to silence the warning."""
        import os
        import tempfile
        from unittest import mock

        bundle = tempfile.mkdtemp(prefix="DaVinci Resolve.app")
        with mock.patch.dict(os.environ, {"RESOLVE_APP": bundle}):
            self.assertIn(bundle, self.installer.installed_app_bundles())
        with mock.patch.dict(os.environ, {"RESOLVE_APP": "/nope/missing.app"}):
            self.assertNotIn("/nope/missing.app", self.installer.installed_app_bundles())

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
        # ctypes: same reasoning as the bridge's own allowlist — core stdlib,
        # imported inside a function under try/except, and the only way to read
        # a process name on Windows (issue #112).
        allowed = {"ctypes", "json", "os", "subprocess", "sys", "time", "DaVinciResolveScript"}
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

    def _darwin_preflight(self, *, frameworks=(), python3_home=None,
                          shell_home=None, fallback_exists=False):
        """python_preflight() on a synthetic macOS machine.

        Pinned to darwin explicitly: the check is macOS-only, so on a Linux or
        Windows runner an unpinned version would assert the very false alarm the
        platform gate exists to suppress.
        """
        import sys as _sys
        from unittest import mock

        home = {
            "value": python3_home,
            "in_launchd": python3_home is not None,
            "in_this_shell": shell_home,
            "dylib": f"{python3_home}/lib/libpython3.12.dylib" if python3_home else None,
            "usable": python3_home is not None,
        }
        fallback = {
            "path": "/usr/local/bin/python3",
            "exists": fallback_exists,
            "resolves_to": "/usr/local/bin/python3" if fallback_exists else None,
        }
        with mock.patch.object(_sys, "platform", "darwin"), \
                mock.patch.object(self.installer, "framework_pythons", lambda: list(frameworks)), \
                mock.patch.object(self.installer, "python3_home_prefix", lambda: home), \
                mock.patch.object(self.installer, "fallback_python3", lambda: fallback):
            return self.installer.python_preflight()

    def test_no_python_at_all_is_the_silent_failure(self) -> None:
        preflight = self._darwin_preflight()
        self.assertFalse(preflight["resolve_will_list_python_scripts"])
        self.assertIn("silently", preflight["advice"])
        # Both remedies must be offered, cheapest first: the sudo-free one is the
        # whole point of issue #143.
        self.assertIn("PYTHON3HOME", preflight["advice"])
        self.assertIn("launchctl setenv", preflight["advice"])
        self.assertIn("python.org", preflight["advice"])

    def test_a_framework_python_still_satisfies_the_preflight(self) -> None:
        preflight = self._darwin_preflight(
            frameworks=["/Library/Frameworks/Python.framework/Versions/3.11"])
        self.assertTrue(preflight["resolve_will_list_python_scripts"])
        self.assertIsNone(preflight["advice"])

    def test_python3home_alone_satisfies_the_preflight(self) -> None:
        """Issue #143: a uv/pixi/conda-forge interpreter is explicitly NOT a
        framework build and can never become one, but Resolve reads PYTHON3HOME
        before it reads anything else. Free 21.0.4.5 ran the bridge on uv-managed
        CPython 3.12.13 with no python.org Python on the machine at all, so
        demanding a framework build there was a system-wide sudo install
        prescribed for a problem the user did not have."""
        preflight = self._darwin_preflight(
            python3_home="/Users/x/.local/share/uv/python/cpython-3.12.13-macos-aarch64-none")
        self.assertTrue(preflight["resolve_will_list_python_scripts"])
        self.assertIsNone(preflight["advice"])
        self.assertEqual(preflight["framework_pythons"], [])

    def test_usr_local_python3_alone_satisfies_the_preflight(self) -> None:
        """The path actually baked into fusionscript.so. python.org installs work
        because their installer creates it — framework-ness was correlated, not
        causal — so it must count on its own."""
        preflight = self._darwin_preflight(fallback_exists=True)
        self.assertTrue(preflight["resolve_will_list_python_scripts"])
        self.assertIsNone(preflight["advice"])

    def test_python3home_in_the_shell_only_is_called_out(self) -> None:
        """`export PYTHON3HOME=...` is the natural thing to try and it cannot
        work: Resolve is GUI-launched and inherits launchd's environment. Found
        by another route here, so this is a warning, not a failure — but silence
        would let the user conclude the export was what fixed it."""
        preflight = self._darwin_preflight(
            fallback_exists=True, shell_home="/opt/homebrew/opt/python@3.12")
        self.assertTrue(preflight["resolve_will_list_python_scripts"])
        self.assertIn("launchd", preflight["advice"])
        self.assertIn("launchctl setenv", preflight["advice"])

    def test_launchd_env_does_not_read_our_own_environment(self) -> None:
        """The one thing launchd_env must never do. os.environ would report a hit
        for a shell export, which is exactly the case that does not work."""
        import inspect

        import ast
        import textwrap

        source = inspect.getsource(self.installer.launchd_env)
        self.assertIn("launchctl", source)
        # Check the executable body, not the docstring — the docstring names
        # os.environ precisely to say it is deliberately not used.
        fn_node = ast.parse(textwrap.dedent(source)).body[0]
        statements = fn_node.body[1:] if ast.get_docstring(fn_node) else fn_node.body
        body = "\n".join(ast.unparse(node) for node in statements)
        self.assertNotIn("os.environ", body)

    def test_the_framework_python_alarm_is_macos_only(self) -> None:
        """`/Library/Frameworks` does not exist off macOS, so the check found
        nothing there and emitted the macOS remediation regardless — telling the
        Windows 11 user in issue #106, who had a working python.org 3.12, to
        install the Python they already had. Linux had the same false alarm."""
        import sys as _sys
        from unittest import mock

        for platform in ("win32", "linux"):
            with self.subTest(platform=platform):
                with mock.patch.object(_sys, "platform", platform), \
                        mock.patch.object(self.installer, "framework_pythons", lambda: []):
                    preflight = self.installer.python_preflight()
                self.assertIsNone(
                    preflight["advice"],
                    f"macOS framework-Python advice leaked onto {platform}",
                )
                self.assertTrue(preflight["resolve_will_list_python_scripts"])

    def test_homebrew_python_is_on_neither_discovery_route(self) -> None:
        # The exact trap: three Homebrew interpreters on PATH and Resolve sees
        # none — not because they are not frameworks, but because neither the
        # framework roots nor /usr/local/bin/python3 is where Homebrew installs.
        for root in self.installer._FRAMEWORK_PYTHON_ROOTS:
            self.assertNotIn("homebrew", str(root).lower())
            self.assertIn("Python.framework", str(root))
        self.assertNotIn("homebrew", str(self.installer._FALLBACK_PYTHON3).lower())
        self.assertEqual(str(self.installer._FALLBACK_PYTHON3), "/usr/local/bin/python3")

    def test_a_lua_canary_ships_with_every_probe(self) -> None:
        # Lua always enumerates, so the canary separates "Python not detected"
        # from "wrong folder" — the ambiguity that cost four restarts. It must
        # name both remedies, or it sends uv/pixi users to a sudo install they
        # do not need (issue #143).
        self.assertIn("PYTHON3HOME", self.installer._LUA_CANARY)
        self.assertIn("python.org", self.installer._LUA_CANARY)
        self.assertIn("print(", self.installer._LUA_CANARY)

    # ── Windows (issue #106) ────────────────────────────────────────────────
    #
    # `script_targets()` enumerated only macOS and Linux candidates, so `usable`
    # came back empty on every Windows machine and `install()` exited with "Is
    # Resolve installed?" on a working free-edition install — leaving Windows
    # free-edition users with no route to the bridge at all.
    #
    # NOT covered here, and not coverable from macOS: whether Resolve on Windows
    # actually *scans* these folders. The reporter confirmed both exist and are
    # writable; issue #104 is precedent that "the folder exists" and "Resolve
    # reads it" are different claims. These tests pin path construction only.

    def _fake_windows_roots(self) -> tuple[str, str]:
        """%APPDATA% and %PROGRAMDATA% for a machine where Resolve is installed
        but has never had a script installed — i.e. no Fusion/Scripts tree yet,
        which is what a fresh free-edition install looks like."""
        import pathlib
        import tempfile

        roots = []
        for prefix in ("appdata_", "programdata_"):
            root = pathlib.Path(tempfile.mkdtemp(prefix=prefix))
            (root / self.installer._WINDOWS_PRODUCT_ROOT).mkdir(parents=True)
            roots.append(str(root))
        return roots[0], roots[1]

    def _windows_targets(self, appdata: str, programdata: str) -> list:
        import os
        import sys as _sys
        from unittest import mock

        env = {"APPDATA": appdata, "PROGRAMDATA": programdata}
        with mock.patch.object(_sys, "platform", "win32"), \
                mock.patch.dict(os.environ, env):
            return self.installer.script_targets()

    def test_windows_targets_both_documented_script_trees(self) -> None:
        appdata, programdata = self._fake_windows_roots()
        targets = self._windows_targets(appdata, programdata)

        joined = [str(t) for t in targets]
        self.assertTrue(joined, "no Windows targets: the installer cannot run at all")
        self.assertTrue(
            any(t.startswith(appdata) for t in joined),
            f"per-user %APPDATA% tree not targeted: {joined}",
        )
        self.assertTrue(
            any(t.startswith(programdata) for t in joined),
            f"all-users %PROGRAMDATA% tree not targeted: {joined}",
        )

    def test_windows_targets_the_per_user_tree_first(self) -> None:
        """%PROGRAMDATA% needs elevation and %APPDATA% does not, so the target
        that will actually succeed on a normal account must be tried first."""
        appdata, programdata = self._fake_windows_roots()
        joined = [str(t) for t in self._windows_targets(appdata, programdata)]
        first_user = next(i for i, t in enumerate(joined) if t.startswith(appdata))
        first_all = next(i for i, t in enumerate(joined) if t.startswith(programdata))
        self.assertLess(first_user, first_all, f"all-users tree tried first: {joined}")

    def test_only_the_windows_per_user_tree_carries_the_support_segment(self) -> None:
        """The asymmetry is real and load-bearing: Blackmagic's README puts
        `Support` in the per-user path and NOT in the all-users one. Deriving
        either from the other lands in a folder Resolve never scans."""
        self.assertIn("Support/Fusion/Scripts", self.installer._WINDOWS_USER_SCRIPTS_SUFFIX)
        self.assertNotIn("Support", self.installer._WINDOWS_ALL_USERS_SCRIPTS_SUFFIX)
        self.assertIn("Fusion/Scripts/Utility", self.installer._WINDOWS_ALL_USERS_SCRIPTS_SUFFIX)

    def test_windows_paths_do_not_double_the_roaming_segment(self) -> None:
        """Blackmagic's README writes the per-user root as `%APPDATA%\\Roaming\\...`,
        but %APPDATA% already IS `...\\AppData\\Roaming`. Following it literally
        yields `AppData\\Roaming\\Roaming\\...` — a real folder name, silently
        never scanned. Transcribing the README verbatim reintroduces #106."""
        appdata, programdata = self._fake_windows_roots()
        joined = [str(t) for t in self._windows_targets(appdata, programdata)]
        self.assertFalse(
            [t for t in joined if "Roaming/Roaming" in t or "Roaming\\Roaming" in t],
            f"the README's doubled Roaming segment was copied verbatim: {joined}",
        )

    def test_windows_paths_never_leak_onto_macos(self) -> None:
        """The Windows branch is additive: macOS and Linux behavior is untouched,
        which is what makes this safe to ship without a Windows machine to test on."""
        import pathlib
        import sys as _sys
        import tempfile
        from unittest import mock

        home = pathlib.Path(tempfile.mkdtemp(prefix="fake_home_"))
        with mock.patch.object(_sys, "platform", "darwin"), \
                mock.patch.object(pathlib.Path, "home", staticmethod(lambda: home)):
            targets = [str(t) for t in self.installer.script_targets()]
        self.assertFalse(
            [t for t in targets if "Blackmagic Design/DaVinci Resolve/Support" in t],
            f"a Windows-only path was targeted on macOS: {targets}",
        )

    def test_windows_targets_a_resolve_that_has_no_scripts_tree_yet(self) -> None:
        """Resolve does not create `Fusion/Scripts` until a script is installed,
        so gating on that tree — or on its parent being writable — skips a fresh
        free-edition install, which is the one build the bridge exists for. Same
        trap as the sandboxed container on macOS; the product folder is the
        signal instead. `_fake_windows_roots` builds exactly this shape."""
        appdata, programdata = self._fake_windows_roots()
        targets = self._windows_targets(appdata, programdata)
        self.assertTrue(
            targets, "a Resolve install with no Scripts tree yet was skipped entirely"
        )
        for target in targets:
            self.assertFalse(target.exists(), "test no longer covers the create case")

    def test_every_target_anchors_the_runtime_dir_beside_fusion(self) -> None:
        """`install()` places the runtime at `target.parents[1]`, so every
        Scripts/Utility suffix must end `Fusion/Scripts/Utility`. The Windows
        per-user path is a segment deeper than the macOS one (it carries
        `Support`), which is exactly the kind of difference that would silently
        anchor the runtime one level off and leave the launcher importing
        nothing."""
        suffixes = [
            self.installer._SCRIPTS_SUFFIX,
            self.installer._SANDBOX_FALLBACK_SUFFIX,
            self.installer._WINDOWS_USER_SCRIPTS_SUFFIX,
            self.installer._WINDOWS_ALL_USERS_SCRIPTS_SUFFIX,
        ]
        for suffix in suffixes:
            with self.subTest(suffix=suffix):
                self.assertTrue(
                    suffix.endswith("Fusion/Scripts/Utility"),
                    f"runtime would anchor off-by-one for {suffix}",
                )

    def test_windows_skips_roots_where_resolve_is_not_installed(self) -> None:
        """The flip side: without the product folder there is no Resolve, and
        creating a Scripts tree under a bare %APPDATA% would litter the machine
        and report a success that nothing will ever read (the #104 failure)."""
        import pathlib
        import tempfile

        empty = str(pathlib.Path(tempfile.mkdtemp(prefix="no_resolve_")))
        self.assertEqual(self._windows_targets(empty, empty), [])

    def test_windows_candidates_are_skipped_when_the_env_vars_are_absent(self) -> None:
        """%APPDATA%/%PROGRAMDATA% are effectively always set on Windows, but an
        unset one must drop that candidate rather than build a path from None."""
        import os
        import sys as _sys
        from unittest import mock

        with mock.patch.object(_sys, "platform", "win32"), \
                mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.installer._windows_script_candidates(), [])

    def _unwritable_dir(self) -> "object":
        """A directory whose children cannot be created."""
        import os
        import pathlib
        import tempfile

        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("root ignores mode bits, so nothing is unwritable")
        parent = pathlib.Path(tempfile.mkdtemp(prefix="readonly_"))
        os.chmod(parent, 0o500)
        self.addCleanup(os.chmod, parent, 0o700)
        return parent / "Utility"

    def test_an_unwritable_target_does_not_abort_the_whole_install(self) -> None:
        """The Windows all-users tree under %PROGRAMDATA% needs elevation, and
        Windows `os.access(W_OK)` reports the read-only flag rather than the ACL
        — so it cannot be screened out in advance. Without this, adding that
        candidate would make the installer crash on every non-elevated Windows
        account *after* it had already succeeded into the per-user tree."""
        import pathlib
        import tempfile
        from unittest import mock

        good = pathlib.Path(tempfile.mkdtemp(prefix="writable_")) / "Utility"
        bad = self._unwritable_dir()
        with mock.patch.object(self.installer, "script_targets", lambda: [good, bad]):
            result = self.installer.install(probe_only=True, port=49632, rotate=False)

        self.assertTrue(
            (good / "resolve_bridge_probe.py").exists(),
            "the writable target was not installed to",
        )
        self.assertEqual(result["skipped"], [str(bad)])
        self.assertTrue(
            any("unwritable" in w for w in result["warnings"]),
            f"the skip was silent: {result['warnings']}",
        )

    def test_install_fails_only_when_every_target_is_unwritable(self) -> None:
        """A total failure must still be fatal — and must say which folders and
        why, rather than the old "Is Resolve installed?" on a machine where it
        demonstrably is."""
        from unittest import mock

        bad = self._unwritable_dir()
        with mock.patch.object(self.installer, "script_targets", lambda: [bad]):
            with self.assertRaises(SystemExit) as caught:
                self.installer.install(probe_only=True, port=49632, rotate=False)
        message = str(caught.exception)
        self.assertIn(str(bad), message)
        self.assertIn("could not write", message)


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


class BridgeForceFlagTests(unittest.TestCase):
    """`DAVINCI_RESOLVE_BRIDGE` forces the bridge; it does not gate it.

    These once described the variable as the bridge's on-switch. Since the
    automatic fallback landed, an unset variable no longer means "never try the
    bridge" — `connect_resolve` still reaches it when a direct transport yields
    nothing. What the variable controls is *exclusivity*: set, the bridge is the
    only transport tried and its faults surface instead of degrading.
    """

    def test_the_flag_reads_as_a_boolean(self) -> None:
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

        # connect() defaults to require_enabled=True, so it still refuses without
        # the flag. The fallback path reaches the bridge by asking for
        # require_enabled=False instead — see connect_resolve.
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(rbc.BridgeUnavailable) as ctx:
                rbc.connect()
        self.assertIn(rbc.ENV_ENABLE, str(ctx.exception))
        self.assertIn("require_enabled=False", str(ctx.exception))

    def test_a_working_direct_transport_is_never_diverted_to_the_bridge(self) -> None:
        # The Studio path must be untouched by the fallback: when scriptapp
        # returns a handle, the bridge is not consulted and the native handle is
        # what comes back.
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


class RuntimeSourceValidationTests(unittest.TestCase):
    """A reload must be refused *before* the running listener is asked to stop."""

    def _runtime(self, **overrides) -> str:
        import tempfile

        root = tempfile.mkdtemp(prefix="runtime_")
        for name in rb.RUNTIME_MODULES:
            body = overrides.get(name, "x = 1\n")
            if body is not None:
                with open(os.path.join(root, name), "w", encoding="utf-8") as handle:
                    handle.write(body)
        return root

    def test_a_compilable_runtime_reports_no_problems(self) -> None:
        self.assertEqual(rb.validate_runtime_sources(self._runtime()), [])

    def test_a_syntax_error_is_reported_with_the_module_and_line(self) -> None:
        problems = rb.validate_runtime_sources(
            self._runtime(**{"resolve_bridge_ops.py": "def broken(:\n    pass\n"})
        )
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("resolve_bridge_ops.py", problems[0])
        self.assertIn("does not compile", problems[0])

    def test_a_missing_module_is_reported_rather_than_ignored(self) -> None:
        problems = rb.validate_runtime_sources(self._runtime(**{"resolve_bridge.py": None}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("cannot be read", problems[0])

    def test_the_real_installed_modules_validate(self) -> None:
        """The negative control: the guard must pass on the code we actually ship."""
        self.assertEqual(rb.validate_runtime_sources(str(REPO / "src/utils")), [])


class StopRequestTests(unittest.TestCase):
    """`serve()` has to come back, and say why."""

    def _bridge(self, *, with_lifecycle: bool = True):
        from src.utils import resolve_bridge_ops as rbo

        import tempfile
        root = tempfile.mkdtemp(prefix="stop_")
        fake = FakeResolve()
        # The launcher's wiring, in miniature: the surface needs a handle on the
        # bridge, and the bridge needs the surface's dispatch.
        holder = {}
        ops = rbo.ResolveOperations(
            fake, media_roots=[root], output_roots=[root],
            lifecycle=(lambda mode: holder["bridge"].request_stop(mode) and None) if with_lifecycle else None,
        )
        config = {"host": "127.0.0.1", "port": 0, "token": TOKEN, "auth_clock_skew_seconds": 60}
        holder["bridge"] = rb.Bridge(fake, config, rbo.make_dispatch(ops))
        return holder["bridge"]

    def test_an_unknown_stop_mode_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._bridge().request_stop("please")

    def test_serve_returns_the_reason_it_was_stopped(self) -> None:
        import threading as _threading

        for mode in rb.STOP_MODES:
            with self.subTest(mode=mode):
                bridge = self._bridge()
                self.addCleanup(bridge.stop)
                model = {"blocking_required": True, "parent_pid": os.getppid()}
                outcome = {}

                def run(_b=bridge, _m=model, _o=outcome):
                    _o.update(_b.serve(poll_seconds=0.05, host_model=_m))

                thread = _threading.Thread(target=run)
                thread.start()
                for _ in range(200):
                    if bridge._server is not None:
                        break
                    time.sleep(0.01)
                bridge.request_stop(mode)
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive(), "serve() did not return")
                self.assertEqual(outcome.get("stop_reason"), mode)

    def test_the_in_process_branch_still_returns_immediately(self) -> None:
        bridge = self._bridge()
        self.addCleanup(bridge.stop)
        outcome = bridge.serve(host_model={"blocking_required": False, "parent_pid": os.getpid()})
        self.assertIsNone(outcome["stop_reason"])

    def test_the_caller_gets_its_reply_before_the_listener_goes_away(self) -> None:
        """The reason `request_stop` only sets a flag.

        Tearing the socket down inside the handler would lose the reply to the
        very request that asked for it, so the drain has to hold the listener
        open until every in-flight handler has written.
        """
        import socket as _socket
        import threading as _threading

        bridge = self._bridge()
        self.addCleanup(bridge.stop)
        model = {"blocking_required": True, "parent_pid": os.getppid()}
        thread = _threading.Thread(target=lambda: bridge.serve(poll_seconds=0.05, host_model=model))
        thread.start()
        for _ in range(200):
            if bridge._server is not None:
                break
            time.sleep(0.01)
        port = bridge.port

        request = signed(TOKEN, timestamp=int(time.time()), nonce="s" * 24, operation="shutdown")
        with _socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.sendall((json.dumps(request) + "\n").encode())
            reply = json.loads(sock.makefile("rb").readline().decode())
        # The reply arrived even though the request killed the listener.
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["result"]["mode"], "exit")

        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        # ...and the listener really is gone, not merely flagged.
        with self.assertRaises(OSError):
            with _socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
                sock.sendall(b"{}\n")
                if not sock.makefile("rb").readline():
                    raise OSError("closed")


class LifecycleOperationTests(unittest.TestCase):
    """Stopping the bridge is an operation on the bridge, not on the project."""

    def _ops(self, lifecycle=None):
        import tempfile
        from src.utils import resolve_bridge_ops as rbo

        root = tempfile.mkdtemp(prefix="lifecycle_")
        return rbo.ResolveOperations(
            FakeResolve(), media_roots=[root], output_roots=[root], lifecycle=lifecycle
        )

    def test_lifecycle_operations_are_separate_from_reads_writes_and_proxy(self) -> None:
        from src.utils import resolve_bridge_ops as rbo

        groups = {
            "read": set(rbo.ResolveOperations.READ_OPERATIONS),
            "write": set(rbo.ResolveOperations.WRITE_OPERATIONS),
            "proxy": set(rbo.ResolveOperations.PROXY_OPERATIONS),
            "lifecycle": set(rbo.ResolveOperations.LIFECYCLE_OPERATIONS),
        }
        for left in groups:
            for right in groups:
                if left < right:
                    self.assertFalse(groups[left] & groups[right], f"{left}/{right} overlap")
        self.assertEqual(
            set(rbo.ResolveOperations.OPERATIONS), set().union(*groups.values())
        )
        # The property the surface shape test measures must survive the addition:
        # lifecycle ops touch the bridge, never the project, so counting them as
        # writes would quietly widen the number that guard is watching.
        self.assertLess(len(groups["write"]), len(groups["read"]))

    def test_a_bridge_with_no_lifecycle_owner_says_so_rather_than_pretending(self) -> None:
        from src.utils import resolve_bridge_ops as rbo

        ops = self._ops()
        self.assertFalse(ops.dispatch("health", {})["lifecycle_available"])
        for operation in rbo.ResolveOperations.LIFECYCLE_OPERATIONS:
            with self.subTest(operation=operation):
                with self.assertRaises(rbo.OperationError) as ctx:
                    ops.dispatch(operation, {})
                self.assertEqual(ctx.exception.code, "capability_unavailable")

    def test_each_operation_asks_for_its_own_mode(self) -> None:
        asked = []
        ops = self._ops(lifecycle=lambda mode: asked.append(mode) or {"generation": 3})
        self.assertEqual(ops.dispatch("shutdown", {}), {"stopping": True, "mode": "exit", "generation": 3})
        self.assertEqual(ops.dispatch("reload", {})["mode"], "reload")
        self.assertEqual(asked, ["exit", "reload"])
        self.assertTrue(ops.dispatch("health", {})["lifecycle_available"])

    def test_a_refused_reload_surfaces_as_an_error_the_client_can_act_on(self) -> None:
        from src.utils import resolve_bridge_ops as rbo

        def lifecycle(mode):
            raise rbo.OperationError("reload_rejected", "the installed runtime will not compile: boom")

        with self.assertRaises(rbo.OperationError) as ctx:
            self._ops(lifecycle=lifecycle).dispatch("reload", {})
        self.assertEqual(ctx.exception.code, "reload_rejected")

    def test_health_exposes_the_session_so_a_reload_can_be_waited_on(self) -> None:
        first, second = self._ops(), self._ops()
        self.assertTrue(first.dispatch("health", {})["session"])
        self.assertNotEqual(
            first.dispatch("health", {})["session"], second.dispatch("health", {})["session"]
        )


class MethodCacheScopeTests(unittest.TestCase):
    """Two Resolve builds can be bridged from one process. The harness does that."""

    def _serve(self, methods):
        import tempfile
        from src.utils import resolve_bridge_client as rbc
        from src.utils import resolve_bridge_ops as rbo

        class Build:
            pass

        for name in methods:
            setattr(Build, name, lambda self, _n=name: _n)
        build = Build()
        root = tempfile.mkdtemp(prefix="cache_")
        ops = rbo.ResolveOperations(build, media_roots=[root], output_roots=[root])
        config = {"host": "127.0.0.1", "port": 0, "token": TOKEN, "auth_clock_skew_seconds": 60}
        bridge = rb.Bridge(build, config, rbo.make_dispatch(ops))
        bridge.start()
        self.addCleanup(bridge.stop)
        transport = rbc.BridgeTransport({**config, "port": bridge.port})
        return rbc.BridgeProxy(transport, "resolve", type_name="Build")

    def test_one_builds_method_set_never_answers_for_another(self) -> None:
        """A class-level cache would let the first build define `hasattr` for both.

        Both proxies report type `Build`, so a cache keyed on the type name alone
        — which is what a shared class attribute amounts to — hands the second
        bridge the first one's surface. That is the exact question `list_methods`
        exists to answer honestly.
        """
        old = self._serve(["GetProductName"])
        new = self._serve(["GetProductName", "CreateMagicMask"])
        self.assertEqual(old.GetProductName(), "GetProductName")
        self.assertEqual(new.CreateMagicMask(), "CreateMagicMask")
        with self.assertRaises(AttributeError):
            getattr(old, "CreateMagicMask")


class ReloadLoopTests(unittest.TestCase):
    """The whole point: new code live without touching Resolve's UI."""

    def test_the_supervisor_loop_swaps_the_surface_under_a_live_client(self) -> None:
        """Mirrors `scripts/resolve_bridge_launcher.py` end to end.

        A client asks for a reload; `serve()` returns `reload`; the supervisor
        builds a fresh surface on the same port; the client sees a new session
        and its old handles are gone. That last part is the contract — a handle
        surviving into a new object graph is the wrong-target failure the session
        scoping exists to prevent.
        """
        import tempfile
        import threading as _threading
        from src.utils import resolve_bridge_client as rbc
        from src.utils import resolve_bridge_ops as rbo

        root = tempfile.mkdtemp(prefix="reload_")
        # Port 0 would give the second generation a different port; the real
        # launcher rebinds the configured one, so pin it the same way.
        probe = rb.Bridge(FakeResolve(), {"host": "127.0.0.1", "port": 0, "token": TOKEN,
                                          "auth_clock_skew_seconds": 60}, lambda *_: None)
        probe.start()
        port = probe.port
        probe.stop()

        config = {"host": "127.0.0.1", "port": port, "token": TOKEN, "auth_clock_skew_seconds": 60}
        generations = []
        done = _threading.Event()

        def supervisor():
            while not done.is_set():
                holder = {}
                ops = rbo.ResolveOperations(
                    FakeResolve(), media_roots=[root], output_roots=[root],
                    lifecycle=lambda mode: holder["bridge"].request_stop(mode) and None,
                )
                holder["bridge"] = rb.Bridge(FakeResolve(), config, rbo.make_dispatch(ops))
                generations.append(ops._session)
                outcome = holder["bridge"].serve(
                    poll_seconds=0.05,
                    host_model={"blocking_required": True, "parent_pid": os.getppid()},
                )
                if outcome.get("stop_reason") != "reload":
                    return

        thread = _threading.Thread(target=supervisor)
        thread.start()
        self.addCleanup(done.set)
        self.addCleanup(thread.join, 10)

        transport = rbc.BridgeTransport(config, timeout=5.0)
        resolve = rbc.BridgeProxy(transport, "resolve", type_name="Resolve")
        for _ in range(200):
            try:
                first_session = resolve.bridge_health()["session"]
                break
            except (rbc.BridgeUnavailable, rbc.BridgeCallError):
                time.sleep(0.01)
        else:
            self.fail("the bridge never came up")

        handle = resolve.GetProjectManager()

        result = resolve.bridge_reload(timeout=15.0)
        self.assertTrue(result["reloaded"])
        self.assertNotEqual(result["session"], first_session)
        self.assertEqual(len(generations), 2, "the supervisor did not build a second surface")

        # A root name still works — it is re-derived, not remembered.
        self.assertEqual(resolve.GetProductName(), "DaVinci Resolve")
        # A handle from before does not, and says why.
        with self.assertRaises(rbc.BridgeCallError) as ctx:
            handle.GetCurrentProject()
        self.assertEqual(ctx.exception.code, "stale_handle")

        resolve.bridge_shutdown()
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive(), "shutdown did not end the supervisor loop")


class LauncherTemplateTests(unittest.TestCase):
    def test_the_installed_launcher_compiles_before_substitution(self) -> None:
        """The installer writes this file verbatim; a syntax error ships silently.

        Resolve reports nothing when a Scripts-menu script fails to parse — the
        same silence as the framework-Python trap — so the check belongs here.
        """
        path = REPO / "scripts/resolve_bridge_launcher.py"
        compile(path.read_text(encoding="utf-8"), str(path), "exec")

    def test_the_launcher_imports_only_what_the_embedded_interpreter_has(self) -> None:
        import ast

        path = REPO / "scripts/resolve_bridge_launcher.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        # `resolve_bridge*` come from the installed runtime directory, not a package.
        allowed = {"base64", "importlib", "os", "sys", "traceback",
                   "DaVinciResolveScript", "resolve_bridge", "resolve_bridge_ops"}
        self.assertFalse(imported - allowed, f"launcher imports {imported - allowed}")


class MethodSetIdentityTests(unittest.TestCase):
    """Reproduces the live defect: one class name for every Resolve object.

    Measured on DaVinci Resolve 21.0.3.7 (free) — the Resolve root, Project and
    TimelineItem all report `type(obj).__name__ == "PyRemoteObject"`, with 34, 49
    and 88 methods respectively. Caching method sets on that name made the first
    object touched define `hasattr` for every object afterwards, so
    `resolve.GetProjectManager().GetCurrentProject()` raised AttributeError
    against real Resolve while passing every unit test — because the fakes here
    have distinct class names and so never collided.

    The fixtures below deliberately share ONE class name, which is what makes
    this a regression test rather than a restatement.
    """

    class PyRemoteObject:
        """Stands in for Resolve's single wrapper class."""

        def __init__(self, methods, children=None):
            self._names = tuple(methods)
            self._children = children or {}
            for name in methods:
                setattr(self, name, (lambda _n=name: self._children.get(_n, _n)))

        def __dir__(self):
            return list(self._names)

    def _serve(self, root):
        import tempfile
        from src.utils import resolve_bridge_client as rbc
        from src.utils import resolve_bridge_ops as rbo

        temp = tempfile.mkdtemp(prefix="shape_")
        ops = rbo.ResolveOperations(root, media_roots=[temp], output_roots=[temp])
        config = {"host": "127.0.0.1", "port": 0, "token": TOKEN, "auth_clock_skew_seconds": 60}
        bridge = rb.Bridge(root, config, rbo.make_dispatch(ops))
        bridge.start()
        self.addCleanup(bridge.stop)
        transport = rbc.BridgeTransport({**config, "port": bridge.port})
        return rbc.BridgeProxy(transport, "resolve", type_name="Resolve", shape="resolve"), transport

    def _tree(self):
        project = self.PyRemoteObject(["GetName", "GetTimelineCount"])
        manager = self.PyRemoteObject(["GetCurrentProject", "SaveProject"],
                                      {"GetCurrentProject": project})
        return self.PyRemoteObject(["GetProductName", "GetProjectManager"],
                                   {"GetProjectManager": manager})

    def test_a_chain_survives_every_object_sharing_one_class_name(self) -> None:
        resolve, _ = self._serve(self._tree())
        self.assertEqual(resolve.GetProductName(), "GetProductName")
        manager = resolve.GetProjectManager()
        # The failing step against real Resolve: `GetCurrentProject` is absent
        # from the *root's* method set, which is what the type-keyed cache held.
        project = manager.GetCurrentProject()
        self.assertEqual(project.GetName(), "GetName")

    def test_capability_detection_still_refuses_what_is_genuinely_absent(self) -> None:
        resolve, _ = self._serve(self._tree())
        manager = resolve.GetProjectManager()
        self.assertTrue(hasattr(manager, "SaveProject"))
        self.assertFalse(hasattr(manager, "CreateMagicMask"))
        self.assertIsNone(getattr(manager, "SmartReframe", None))
        # A root method must not leak onto a child through a shared cache entry.
        self.assertFalse(hasattr(manager, "GetProductName"))

    def test_the_cache_is_keyed_on_provenance_not_the_class_name(self) -> None:
        resolve, transport = self._serve(self._tree())
        resolve.GetProductName()
        manager = resolve.GetProjectManager()
        manager.SaveProject()
        self.assertIn("resolve", transport.method_cache)
        self.assertIn("resolve.GetProjectManager", transport.method_cache)
        self.assertNotIn("PyRemoteObject", transport.method_cache)
        self.assertNotEqual(
            transport.method_cache["resolve"],
            transport.method_cache["resolve.GetProjectManager"],
        )

    def test_siblings_from_one_call_share_a_single_fetch(self) -> None:
        """The reason provenance beats keying per handle: homogeneous lists."""
        items = [self.PyRemoteObject(["GetName", "GetStart"]) for _ in range(20)]
        track = self.PyRemoteObject(["GetItemListInTrack"], {"GetItemListInTrack": items})
        resolve, transport = self._serve(track)
        resolve.GetItemListInTrack  # warm the root's own shape, which is not what this measures

        seen = []
        original = transport.request

        def counting(operation, arguments):
            seen.append(operation)
            return original(operation, arguments)

        transport.request = counting
        for item in resolve.GetItemListInTrack():
            item.GetName()
        # 20 items: one list_methods for the shape they share, not one each.
        self.assertEqual(seen.count("list_methods"), 1, seen)

    def test_absence_is_reverified_so_a_stale_shape_cannot_invent_one(self) -> None:
        """The safety net under the provenance hint.

        Poison the cache with a shape that lacks a method the object really has.
        A cache that were the last word would report it missing; re-verifying
        against the object itself is what makes a wrong hint harmless.
        """
        resolve, transport = self._serve(self._tree())
        manager = resolve.GetProjectManager()
        transport.method_cache["resolve.GetProjectManager"] = frozenset({"SaveProject"})
        self.assertTrue(hasattr(manager, "GetCurrentProject"))
        self.assertIn("GetCurrentProject", transport.method_cache["resolve.GetProjectManager"])
        # And a name that is genuinely absent still refuses after the re-check.
        self.assertFalse(hasattr(manager, "NoSuchMethod"))


class AttributeReadingTests(unittest.TestCase):
    """Resolve's API constants are attributes, and `dir()` does not list them.

    `Timeline.Export(path, resolve.EXPORT_AAF, resolve.EXPORT_AAF_NEW)` is the
    documented conform idiom; `resolve.AUDIO_SYNC_*` configures AutoSyncAudio.
    Measured on 21.0.3.7: `dir(resolve)` returns 34 names, none of them
    `EXPORT_*`, while the constants themselves read back as real values
    (EXPORT_EDL 2.0, EXPORT_NONE -1.0, EXPORT_OTIO 15.0).

    With no way to read them the proxy answered `hasattr(resolve, "EXPORT_AAF")`
    False, and `_timeline_export_value` in the server then falls through to
    passing the bare string "EXPORT_AAF" to Resolve — a silent degradation of the
    whole conform surface rather than a failure anyone would see.
    """

    class RemoteLike:
        """Resolve's shape: dir() lists methods only, getattr never raises."""

        CONSTANTS = {"EXPORT_AAF": 0.0, "EXPORT_EDL": 2.0, "EXPORT_NONE": -1.0}

        def GetProductName(self):
            return "DaVinci Resolve"

        def __dir__(self):
            return ["GetProductName"]

        def __getattr__(self, name):
            # Unknown names come back as None instead of raising — the measured
            # behaviour that makes None indistinguishable from absent.
            return self.CONSTANTS.get(name)

    def _serve(self, target):
        import tempfile
        from src.utils import resolve_bridge_client as rbc
        from src.utils import resolve_bridge_ops as rbo

        root = tempfile.mkdtemp(prefix="attr_")
        ops = rbo.ResolveOperations(target, media_roots=[root], output_roots=[root])
        config = {"host": "127.0.0.1", "port": 0, "token": TOKEN, "auth_clock_skew_seconds": 60}
        bridge = rb.Bridge(target, config, rbo.make_dispatch(ops))
        bridge.start()
        self.addCleanup(bridge.stop)
        transport = rbc.BridgeTransport({**config, "port": bridge.port})
        return rbc.BridgeProxy(transport, "resolve", type_name="Resolve", shape="resolve"), transport

    def test_constants_absent_from_dir_are_still_readable(self) -> None:
        resolve, _ = self._serve(self.RemoteLike())
        self.assertEqual(resolve.EXPORT_AAF, 0.0)
        self.assertEqual(resolve.EXPORT_EDL, 2.0)
        # -1.0 and 0.0 are both falsy; a caller must be able to tell them apart
        # from "not there", so identity of the value matters, not truthiness.
        self.assertEqual(resolve.EXPORT_NONE, -1.0)
        self.assertTrue(hasattr(resolve, "EXPORT_AAF"))

    def test_methods_are_still_methods_not_values(self) -> None:
        resolve, _ = self._serve(self.RemoteLike())
        self.assertEqual(resolve.GetProductName(), "DaVinci Resolve")

    def test_a_none_answer_does_not_make_hasattr_true_for_everything(self) -> None:
        """The trap that reading attributes could have re-opened.

        Resolve returns None for a name that does not exist, so treating a
        present-but-None attribute as a value would answer `hasattr` with True
        for any string at all — exactly the always-true behaviour the strict
        proxy exists to replace.
        """
        resolve, _ = self._serve(self.RemoteLike())
        self.assertFalse(hasattr(resolve, "Xyzzy_NotAThing"))
        self.assertIsNone(getattr(resolve, "TotallyMadeUpConstant", None))

    def test_the_bridge_reports_the_kind_rather_than_a_bare_value(self) -> None:
        from src.utils import resolve_bridge_ops as rbo

        _, transport = self._serve(self.RemoteLike())
        self.assertEqual(transport.request("get_attribute", {"target": "resolve", "name": "EXPORT_EDL"}),
                         {"kind": "value", "value": 2.0})
        self.assertEqual(transport.request("get_attribute", {"target": "resolve", "name": "GetProductName"})["kind"],
                         "callable")
        self.assertEqual(transport.request("get_attribute", {"target": "resolve", "name": "Nope"})["kind"],
                         "none")
        # A plain Python object CAN tell absence apart, and still does.
        plain, plain_transport = self._serve(type("Plain", (), {"REAL": 7})())
        self.assertEqual(plain_transport.request("get_attribute", {"target": "resolve", "name": "REAL"}),
                         {"kind": "value", "value": 7})
        self.assertEqual(plain_transport.request("get_attribute", {"target": "resolve", "name": "Nope"})["kind"],
                         "absent")
        self.assertIn("get_attribute", rbo.ResolveOperations.OPERATIONS)

    def test_a_fusion_object_reaches_its_own_unenumerated_methods(self) -> None:
        """Fusion under-reports itself, and unlike Resolve it cannot be probed.

        `dir()` on a live Fusion Tool omits GetAttrs/SetAttrs — documented
        methods that work perfectly when called (measured on free 21.0.3.7:
        GetAttrs returned TOOLS_Name "Blur1"). Because Resolve fabricates a
        callable for any name, dir() is the only evidence of absence there is,
        so an omitted name can only be recovered by knowing about it.

        The stub overrides __dir__ rather than just seeding the method cache:
        the proxy re-fetches the list before declaring absence, so a stub whose
        dir() still shows GetAttrs makes this test pass with the fix removed.

        Without this, `fusion_comp add_tool` — which calls GetAttrs to build its
        return value — died on the free edition and took every server-authored
        Fusion graph with it.
        """
        class FusionToolLike:
            """Callable GetAttrs, invisible to dir() — what Fusion actually does."""

            def ConnectInput(self, *a): return True
            def FindMainInput(self, *a): return None
            def GetControlPageNames(self): return []
            def SetInput(self, *a): return True
            def GetAttrs(self): return {"TOOLS_Name": "Blur1", "TOOLS_RegID": "Blur"}

            def __dir__(self):
                return ["ConnectInput", "FindMainInput", "GetControlPageNames", "SetInput"]

        tool, _ = self._serve(FusionToolLike())
        self.assertNotIn("GetAttrs", tool._methods(refresh=True))
        self.assertEqual(tool.GetAttrs(), {"TOOLS_Name": "Blur1", "TOOLS_RegID": "Blur"})

    def test_resolve_objects_still_refuse_an_absent_method(self) -> None:
        """The exception above must not become a hole in capability detection.

        A Resolve API object has none of the Fusion markers, so GetAttrs stays
        absent there — and an invented name stays absent on the Fusion object
        too. This is what keeps `getattr(item, "CreateMagicMask", None)` honest.
        """
        resolve, _ = self._serve(self.RemoteLike())
        self.assertFalse(hasattr(resolve, "GetAttrs"))

        class FusionToolLike:
            def ConnectInput(self, *a): return True
            def GetAttrs(self): return {}
            def __dir__(self): return ["ConnectInput"]

        tool, _ = self._serve(FusionToolLike())
        self.assertFalse(hasattr(tool, "Xyzzy_NotAFusionMethod"))

    def test_private_names_are_refused_here_too(self) -> None:
        from src.utils import resolve_bridge_ops as rbo

        _, transport = self._serve(self.RemoteLike())
        for name in ("__class__", "_secret", "__globals__"):
            with self.subTest(name=name):
                with self.assertRaises(Exception) as ctx:
                    transport.request("get_attribute", {"target": "resolve", "name": name})
                self.assertEqual(getattr(ctx.exception, "code", None), "method_not_allowed")
        self.assertTrue(rbo.ResolveOperations.PROXY_OPERATIONS)


class ServerReachesTheBridgeTests(unittest.TestCase):
    """The bridge has to be reachable on the machine it was built for.

    Blackmagic's `DaVinciResolveScript` ships with the *installer*, not with the
    App Store build — a free-edition-only machine has no
    Developer/Scripting/Modules tree at all, so the import fails and
    `server.dvr_script` is None. `_try_connect` returned on that check before ever
    calling `connect_resolve`, which is the function that accepts None in bridge
    mode. Verified against a healthy live bridge with the import blocked:
    `get_resolve()` answered None, so the entire feature was inert on its target
    configuration.
    """

    def _server_module(self):
        import importlib

        module = importlib.import_module("src.server")
        return module

    def test_a_missing_scripting_module_no_longer_blocks_the_bridge(self) -> None:
        from unittest import mock

        server = self._server_module()
        sentinel = mock.MagicMock(name="bridge-proxy")
        with mock.patch.object(server, "dvr_script", None), \
                mock.patch.object(server, "_bridge_requested", return_value=True), \
                mock.patch.object(server, "connect_resolve", return_value=sentinel) as connect, \
                mock.patch.object(server, "_is_resolve_handle_live", return_value=True):
            self.assertIs(server._try_connect(), sentinel)
        # And it was handed None, which is exactly what bridge mode expects.
        connect.assert_called_once_with(None)

    def test_without_the_bridge_a_missing_module_still_short_circuits(self) -> None:
        from unittest import mock

        server = self._server_module()
        with mock.patch.object(server, "dvr_script", None), \
                mock.patch.object(server, "_bridge_requested", return_value=False), \
                mock.patch.object(server, "connect_resolve") as connect:
            self.assertIsNone(server._try_connect())
        connect.assert_not_called()

    def test_bridge_mode_never_auto_launches_resolve(self) -> None:
        """Launching cannot produce a bridge, and opens a window nobody asked for.

        The listener only exists once someone runs Workspace > Scripts inside an
        already-running Resolve, so an auto-launch here fails to connect anyway —
        after starting an application unprompted.
        """
        from unittest import mock

        server = self._server_module()
        # conftest replaces `_launch_resolve` for the whole suite so no test can
        # open Resolve; this is the one test that must exercise the real thing, so
        # it reaches for the original. The fallback keeps it working under plain
        # unittest, where conftest never loads.
        launch = getattr(server, "_launch_resolve_unpatched", server._launch_resolve)
        with mock.patch.object(server, "_bridge_requested", return_value=True), \
                mock.patch.object(server.subprocess, "Popen") as popen:
            self.assertFalse(launch())
        popen.assert_not_called()

    def test_both_macos_editions_are_candidates_for_auto_launch(self) -> None:
        """Only the installer path was checked, so a free-only machine found nothing
        — and a machine with both always got Studio."""
        from src.utils import resolve_runtime

        self.assertIn("/Applications/DaVinci Resolve.app", resolve_runtime.MACOS_RESOLVE_APPS)
        self.assertIn(
            "/Applications/DaVinci Resolve/DaVinci Resolve.app", resolve_runtime.MACOS_RESOLVE_APPS
        )

    def test_bridge_requested_reads_the_environment_at_call_time(self) -> None:
        from unittest import mock

        server = self._server_module()
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(server._bridge_requested())
        with mock.patch.dict(os.environ, {"DAVINCI_RESOLVE_BRIDGE": "1"}):
            self.assertTrue(server._bridge_requested())


class HandleEvictionTests(unittest.TestCase):
    """The handle table is bounded, and *which* entry it drops is load-bearing.

    Measured against a 400-item timeline on free 21.0.3.7: 6000 handles minted,
    a handle touched every round still valid at the end, an untouched one evicted
    and refusing with `stale_handle`. Long sessions depend on the first half;
    correctness depends on the second, because a recycled id that resolved to a
    different object would be a wrong-target edit with nothing to indicate it.
    """

    def _ops(self, ceiling):
        import tempfile
        from src.utils import resolve_bridge_ops as rbo

        root = tempfile.mkdtemp(prefix="evict_")
        ops = rbo.ResolveOperations(FakeResolve(), media_roots=[root], output_roots=[root])
        ops.MAX_HANDLES = ceiling
        return ops

    def _mint(self, ops):
        return ops.dispatch("call", {"target": "resolve", "method": "GetProjectManager"})["value"]["__handle__"]

    def test_a_handle_in_continuous_use_is_never_the_one_dropped(self) -> None:
        ops = self._ops(8)
        warm = self._mint(ops)
        for _ in range(50):
            self._mint(ops)
            # Touching it promotes it, which is the whole point.
            ops.dispatch("call", {"target": warm, "method": "GetName"})
        ops.dispatch("call", {"target": warm, "method": "GetName"})  # must not raise

    def test_an_untouched_handle_is_evicted_and_refuses_rather_than_resolving(self) -> None:
        from src.utils import resolve_bridge_ops as rbo

        ops = self._ops(8)
        cold = self._mint(ops)
        for _ in range(50):
            self._mint(ops)
        with self.assertRaises(rbo.OperationError) as ctx:
            ops.dispatch("call", {"target": cold, "method": "GetName"})
        self.assertEqual(ctx.exception.code, "stale_handle")

    def test_the_table_never_exceeds_its_ceiling(self) -> None:
        ops = self._ops(8)
        for _ in range(200):
            self._mint(ops)
        self.assertLessEqual(len(ops._handles), 8)


class NeverLaunchARunningResolveTests(unittest.TestCase):
    """Failing to connect is not the same as nothing running.

    Conflating them opened an application nobody asked for, three times before it
    was traced. The free edition refuses external scripting *by design*, so on a
    machine where only it is running `_try_connect` always fails — and
    `get_resolve` then launched **Studio**, a second and different application, on
    every tool call. On this machine both editions are installed, which is why it
    kept picking the wrong one.
    """

    def setUp(self) -> None:
        """Start from no cached handle, whatever ran before.

        `get_resolve` returns `server.resolve` early whenever the cached handle
        still answers — before it consults `_try_connect`, which is what these
        tests mock. So a handle left behind by an earlier test makes every
        assertion below measure that handle instead of the decision under test.
        It happened for real: under `python -m unittest discover`, where the
        pytest fixture that clears this never runs, an earlier test connected to
        a running Resolve and these three then asserted against a live
        `PyRemoteObject`.

        Cleared here rather than only in the fixture, so the tests hold under
        either runner and in any order.
        """
        server = self._server()
        self._cached_resolve = server.resolve
        server.resolve = None

    def tearDown(self) -> None:
        # Restore rather than blank it: leaving state better than we found it is
        # what let this bug travel between modules in the first place.
        self._server().resolve = self._cached_resolve

    def _server(self):
        import importlib

        return importlib.import_module("src.server")

    def _detector(self, server):
        """The real `resolve_is_running`, not conftest's offline stand-in.

        conftest pins it to False so every test's error messages read the same on
        any machine. These two tests are about the detector itself, so they need
        the original — the stub would make them assert on the stub.
        """
        return getattr(server, "_resolve_is_running_unpatched", server.resolve_is_running)

    def _get_resolve(self, server):
        """The real `get_resolve`, not conftest's offline stand-in.

        conftest replaces it suite-wide so no test can reach a live Resolve. These
        tests are about what that function decides, so they need the original —
        calling the stub instead makes them pass without exercising anything.
        """
        return getattr(server, "_get_resolve_unpatched", server.get_resolve)

    def test_a_running_but_unscriptable_resolve_is_not_launched_again(self) -> None:
        """The exact free-edition case: something is up, scripting refuses."""
        from unittest import mock

        server = self._server()
        with mock.patch.object(server, "_try_connect", return_value=None), \
                mock.patch.object(server, "resolve_is_running", return_value=True), \
                mock.patch.object(server, "_launch_resolve") as launch:
            self.assertIsNone(self._get_resolve(server)())
        launch.assert_not_called()

    def test_an_undeterminable_answer_does_not_launch_either(self) -> None:
        """`None` means "cannot tell", and must not decay into "nothing is running".

        That decay is the whole bug in miniature: the answer that leads to opening
        an application is the one you must never reach by accident.
        """
        from unittest import mock

        server = self._server()
        with mock.patch.object(server, "_try_connect", return_value=None), \
                mock.patch.object(server, "resolve_is_running", return_value=None), \
                mock.patch.object(server, "_launch_resolve") as launch:
            self.assertIsNone(self._get_resolve(server)())
        launch.assert_not_called()

    def test_a_genuinely_absent_resolve_is_still_launched(self) -> None:
        """The behaviour README documents, preserved: nothing running -> launch."""
        from unittest import mock

        server = self._server()
        with mock.patch.object(server, "_try_connect", return_value=None), \
                mock.patch.object(server, "resolve_is_running", return_value=False), \
                mock.patch.object(server, "_launch_resolve") as launch:
            self._get_resolve(server)()
        launch.assert_called_once()

    def test_detection_covers_both_macos_editions_and_the_other_platforms(self) -> None:
        from src.utils import resolve_runtime

        patterns = resolve_runtime.RESOLVE_PROCESS_PATTERNS
        # The App Store build is `/Applications/DaVinci Resolve.app/...` and the
        # installer build `/Applications/DaVinci Resolve/DaVinci Resolve.app/...`;
        # one pattern has to match both, or the edition that is running is missed.
        for command in (
            "/Applications/DaVinci Resolve.app/Contents/MacOS/Resolve",
            "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/MacOS/Resolve",
        ):
            with self.subTest(command=command):
                self.assertTrue(any(p in command for p in patterns), command)
        self.assertTrue(any("Resolve.exe" in p for p in patterns))
        self.assertTrue(any("/opt/resolve/bin/resolve" in p for p in patterns))

    def test_detection_reports_none_when_it_cannot_look(self) -> None:
        from unittest import mock

        server = self._server()
        detect = self._detector(server)
        from src.utils import resolve_runtime

        # The process listing moved into resolve_runtime when headless detection
        # needed the *argv*, not just the presence, of a running Resolve.
        # Patching server.subprocess here would have passed while testing nothing.
        with mock.patch.object(resolve_runtime.subprocess, "run", side_effect=OSError("no ps")):
            self.assertIsNone(detect())

    def test_detection_finds_a_running_resolve_in_a_process_listing(self) -> None:
        from unittest import mock

        server = self._server()
        detect = self._detector(server)
        from src.utils import resolve_runtime

        listing = mock.Mock(returncode=0,
                            stdout="/Applications/DaVinci Resolve.app/Contents/MacOS/Resolve\nfinder\n")
        with mock.patch.object(resolve_runtime.subprocess, "run", return_value=listing):
            self.assertTrue(detect())
        empty = mock.Mock(returncode=0, stdout="finder\nDock\n")
        with mock.patch.object(resolve_runtime.subprocess, "run", return_value=empty):
            self.assertFalse(detect())


class NotConnectedMessageTests(unittest.TestCase):
    """What the *caller* is told, not just what gets logged.

    Nine call sites asserted "It was not running and auto-launch failed. Check that
    Resolve Studio is installed." Once `get_resolve` stopped launching a second
    application that was wrong in every way that mattered: no launch was attempted,
    Resolve *was* running, and a free-edition user was being sent to check a Studio
    install they may not have. Observed end to end — the accurate guidance went to
    the log while the tool returned the stale text.
    """

    def _server(self):
        import importlib

        return importlib.import_module("src.server")

    def test_a_running_but_unscriptable_resolve_is_described_accurately(self) -> None:
        from unittest import mock

        server = self._server()
        with mock.patch.object(server, "resolve_is_running", return_value=True), \
                mock.patch.object(server, "_bridge_requested", return_value=False):
            error = server._not_connected_error()["error"]
        self.assertEqual(error["code"], "SCRIPTING_UNAVAILABLE")
        self.assertEqual(error["category"], "not_connected")
        self.assertNotIn("auto-launch", error["message"].lower())
        # Both remedies named: the caller may be on either edition.
        self.assertIn("External scripting", error["remediation"])
        self.assertIn("DAVINCI_RESOLVE_BRIDGE", error["remediation"])
        self.assertTrue(error["state"]["resolve_running"])

    def test_bridge_mode_points_at_the_bridge_not_at_preferences(self) -> None:
        from unittest import mock

        server = self._server()
        with mock.patch.object(server, "resolve_is_running", return_value=True), \
                mock.patch.object(server, "_bridge_requested", return_value=True):
            error = server._not_connected_error()["error"]
        self.assertEqual(error["code"], "BRIDGE_UNAVAILABLE")
        self.assertIn("Workspace > Scripts > resolve_bridge", error["remediation"])
        # The Python-discovery trap cost four restarts to find once; a caller
        # staring at an empty Scripts menu should not have to rediscover it. The
        # remediation must name the sudo-free route, not just python.org — that
        # was issue #143, where the only advice on offer was a system-wide
        # install the reporter's machine did not need and may not have allowed.
        self.assertIn("PYTHON3HOME", error["remediation"])
        self.assertIn("launchctl setenv", error["remediation"])

    def test_a_genuinely_absent_resolve_says_so(self) -> None:
        from unittest import mock

        server = self._server()
        with mock.patch.object(server, "resolve_is_running", return_value=False), \
                mock.patch.object(server, "_bridge_requested", return_value=False):
            error = server._not_connected_error()["error"]
        self.assertEqual(error["code"], "RESOLVE_NOT_RUNNING")
        self.assertIn("not running", error["message"])

    def test_no_error_message_still_claims_an_auto_launch_that_did_not_happen(self) -> None:
        """Checked over `_err(...)` string literals, not the file text.

        A plain substring search flags the comment naming the `not_connected`
        category and the docstring explaining why the old wording was retired —
        prose is not a message. Two real sites *were* found this way, both phrased
        "Resolve isn't running and auto-launch failed", which a grep for the other
        wording had missed.
        """
        import ast

        tree = ast.parse((REPO / "src/server.py").read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_err"):
                continue
            for piece in ast.walk(node):
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    lowered = piece.value.lower()
                    if "auto-launch" in lowered or "resolve studio is installed" in lowered:
                        offenders.append(f"line {node.lineno}: {piece.value[:70]}")
        self.assertEqual(
            offenders, [],
            "these _err() messages assert a launch that no longer happens:\n  "
            + "\n  ".join(offenders),
        )


class NotConnectedRetryabilityTests(unittest.TestCase):
    """A failure the caller must act on is not retryable.

    `not_connected` defaults to retryable=True because auto-launch might succeed
    next time. Neither of the blocked cases can: one needs a preference changed,
    the other needs a script started inside Resolve. Reporting them as retryable
    sends an agent into a loop it cannot win — the same defect the missing-argument
    envelope had.
    """

    def _server(self):
        import importlib

        return importlib.import_module("src.server")

    def test_the_blocked_cases_are_not_retryable(self) -> None:
        from unittest import mock

        server = self._server()
        for running, bridge, expected_code in (
            (True, False, "SCRIPTING_UNAVAILABLE"),
            (True, True, "BRIDGE_UNAVAILABLE"),
        ):
            with self.subTest(code=expected_code):
                with mock.patch.object(server, "resolve_is_running", return_value=running), \
                        mock.patch.object(server, "_bridge_requested", return_value=bridge):
                    error = server._not_connected_error()["error"]
                self.assertEqual(error["code"], expected_code)
                self.assertFalse(error["retryable"], error)

    def test_a_simply_absent_resolve_stays_retryable(self) -> None:
        """Starting Resolve and calling again is the natural flow, so keep it."""
        from unittest import mock

        server = self._server()
        with mock.patch.object(server, "resolve_is_running", return_value=False), \
                mock.patch.object(server, "_bridge_requested", return_value=False):
            error = server._not_connected_error()["error"]
        self.assertEqual(error["code"], "RESOLVE_NOT_RUNNING")
        self.assertTrue(error["retryable"])


class ParentExitDetectionTests(unittest.TestCase):
    """serve() must notice Resolve leaving on Windows, where pids never change.

    `os.getppid() != expected_parent` is a POSIX signal: an orphan is reparented
    and the value changes. Windows does not reparent, so getppid() returns the
    dead parent's pid forever and that check can never fire. The bridge outlived
    Resolve, kept port 49632 and answered with a dead handle, so the next
    session could not bind and the client saw a timeout against a LISTENING
    socket (issue #112).

    These simulate Windows off Windows — a constant getppid plus an injected
    liveness answer — because the platform difference is exactly what made the
    original bug invisible to everyone developing on macOS or Linux.
    """

    WINDOWS_PPID = 22584

    def _windows_getppid(self):
        """Windows: the value never changes, alive or dead."""
        return lambda: self.WINDOWS_PPID

    def test_constant_ppid_still_detects_a_dead_parent(self):
        exited = rb.parent_has_exited(
            self.WINDOWS_PPID, "Resolve.exe",
            getppid=self._windows_getppid(),
            is_alive=lambda pid: False,
            name_of=lambda pid: "",
        )
        self.assertTrue(exited, "a dead parent must be detected without reparenting")

    def test_a_live_parent_keeps_the_bridge_serving(self):
        exited = rb.parent_has_exited(
            self.WINDOWS_PPID, "Resolve.exe",
            getppid=self._windows_getppid(),
            is_alive=lambda pid: True,
            name_of=lambda pid: "Resolve.exe",
        )
        self.assertFalse(exited)

    def test_undeterminable_liveness_is_never_read_as_death(self):
        # The module's standing rule: a bridge that exits early is worse than
        # one that lingers. Access-denied and friends must not end the session.
        exited = rb.parent_has_exited(
            self.WINDOWS_PPID, "Resolve.exe",
            getppid=self._windows_getppid(),
            is_alive=lambda pid: None,
            name_of=lambda pid: "",
        )
        self.assertFalse(exited)

    def test_pid_reuse_by_a_non_resolve_process_counts_as_exited(self):
        # The reparent check would call this "still running" — the pid is alive
        # and unchanged — but it is a different program wearing the same number.
        exited = rb.parent_has_exited(
            self.WINDOWS_PPID, "Resolve.exe",
            getppid=self._windows_getppid(),
            is_alive=lambda pid: True,
            name_of=lambda pid: "notepad.exe",
        )
        self.assertTrue(exited)

    def test_an_unrecognisable_parent_name_is_not_evidence_of_death(self):
        """The sandbox case: parent name unreadable or not marker-shaped.

        `_host_model` documents that `ps` on another process is blocked under
        the App Store sandbox, so a legitimate Resolve child routinely sees an
        empty or non-matching parent name. Reading that as pid reuse would kill
        the bridge on its first poll — on the exact edition it exists for.
        Caught against a real live process whose parent was /bin/zsh.
        """
        for expected, current in (("", "zsh"), ("/bin/zsh", "zsh"), ("python3.11", "python3.11")):
            with self.subTest(expected=expected, current=current):
                self.assertFalse(rb.parent_has_exited(
                    self.WINDOWS_PPID, expected,
                    getppid=self._windows_getppid(),
                    is_alive=lambda pid: True,
                    name_of=lambda pid, c=current: c,
                ))

    def test_reparenting_is_still_the_fast_path_on_posix(self):
        exited = rb.parent_has_exited(
            self.WINDOWS_PPID, "Resolve",
            getppid=lambda: 1,          # reparented to init
            is_alive=lambda pid: True,  # not even consulted
            name_of=lambda pid: "Resolve",
        )
        self.assertTrue(exited)

    def test_a_live_resolve_named_parent_is_accepted_by_marker(self):
        for name in ("Resolve.exe", "fuscript.exe", "Fusion"):
            with self.subTest(name=name):
                self.assertFalse(rb.parent_has_exited(
                    self.WINDOWS_PPID, "Resolve.exe",
                    getppid=self._windows_getppid(),
                    is_alive=lambda pid: True,
                    name_of=lambda pid, n=name: n,
                ))


class ListenerLivenessTests(unittest.TestCase):
    """`is_alive()` on the serve thread is a narrower question than it looks.

    `serve_forever()` keeps its thread alive, so thread-aliveness does not
    establish that the socket is still open. A bridge was reported lingering
    with nothing listening on its port while its serve loop kept polling
    (issue #112). That combination is still unexplained, but a process running
    with no listener is useless either way, so the exit condition now asks the
    socket directly.
    """

    def _bridge(self):
        return rb.Bridge(
            object(),
            {"host": "127.0.0.1", "port": 0, "token": TOKEN, "auth_clock_skew_seconds": 60},
            lambda op, args: {},
        )

    def test_a_started_bridge_reports_a_live_listener(self):
        bridge = self._bridge().start()
        try:
            self.assertTrue(bridge._listener_is_live())
        finally:
            bridge.stop()

    def test_a_stopped_bridge_reports_a_dead_listener(self):
        bridge = self._bridge().start()
        bridge.stop()
        self.assertFalse(bridge._listener_is_live())

    def test_a_closed_socket_is_detected_while_the_thread_still_runs(self):
        bridge = self._bridge().start()
        try:
            self.assertTrue(bridge._thread.is_alive())
            bridge._server.socket.close()  # thread keeps running; socket does not
            self.assertFalse(bridge._listener_is_live(),
                             "a closed socket must not read as a live listener")
        finally:
            try:
                bridge.stop()
            except Exception:
                pass


class BridgePortConflictTests(unittest.TestCase):
    """A stale bridge holding the port must say so, not fail opaquely."""

    def test_bind_failure_names_the_orphan_and_the_way_out(self):
        import socket

        holder = socket.socket()
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        try:
            bridge = rb.Bridge(
                object(),
                {"host": "127.0.0.1", "port": port, "token": TOKEN,
                 "auth_clock_skew_seconds": 60},
                lambda op, args: {},
            )
            with self.assertRaises(rb.BridgeConfigError) as caught:
                bridge.start()
        finally:
            holder.close()
        message = str(caught.exception)
        self.assertIn("still running from an earlier Resolve session", message)
        self.assertIn("shutdown", message)
        self.assertIn(str(port), message)


class BoundMethodKeywordTests(unittest.TestCase):
    """Bridge method proxies are positional-only; a kwarg must fail with
    guidance, not the bare "unexpected keyword argument" that shipped a
    black-box error to a PR #165 reporter."""

    def test_keyword_argument_raises_with_remediation(self):
        from src.utils.resolve_bridge_client import _BoundMethod

        method = _BoundMethod(transport=None, handle="h1", name="StartRendering")
        with self.assertRaises(TypeError) as raised:
            method([1], isInteractiveMode=False)
        message = str(raised.exception)
        self.assertIn("StartRendering", message)
        self.assertIn("isInteractiveMode", message)
        self.assertIn("positionally", message)

    def test_no_resolve_api_call_uses_keyword_arguments(self):
        """PR #165's bug class, guarded for ALL bridge-reachable code.

        The bridge proxies Resolve calls positionally, so a keyword argument
        on any Resolve API method works on Studio's native scripting and dies
        on the free edition. The Resolve method-name set comes from the shipped
        API reference, which is what separates StartRendering from Popen — a
        PascalCase heuristic alone flags every stdlib constructor in the tree.
        The first sweep found the bug a second time, in probe_catalogue.py.
        """
        import ast
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent.parent
        api_doc = (root / "docs" / "reference" / "resolve_scripting_api.txt").read_text(encoding="utf-8")
        api_methods = set(re.findall(r"^\s{2}([A-Z][A-Za-z0-9]+)\(", api_doc, re.M))
        self.assertGreater(len(api_methods), 100, "API doc parse looks broken")

        offenders = []
        for path in sorted((root / "src").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr in api_methods and node.keywords:
                    kw = ", ".join(k.arg or "**" for k in node.keywords)
                    offenders.append(
                        f"{path.relative_to(root)}:{node.lineno} "
                        f"{node.func.attr}({kw}=...)"
                    )
        self.assertEqual(
            offenders, [],
            "Resolve API calls must be positional — a keyword argument dies in "
            "the free-edition bridge's _BoundMethod (PR #165). Rewrite these "
            "positionally:\n  " + "\n  ".join(offenders),
        )
