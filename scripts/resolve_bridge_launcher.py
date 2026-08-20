"""Workspace ▸ Scripts ▸ resolve_bridge — starts the in-app bridge.

Installed by ``python scripts/install_resolve_bridge.py``. Run it once per
Resolve session; it holds the loopback listener open until Resolve exits or a
client asks it to stop.

**This blocks, on purpose.** A Scripts-menu script is a child process of Resolve
(measured on Studio 19.1.3.7 and free 21.0.3.7), so a background thread dies the
instant this function returns. `serve()` detects the host model and blocks or
returns accordingly — see `src/utils/resolve_bridge.py`. While it is running this
script will appear "busy" in Resolve; that is the listener staying alive, not a
hang, and Resolve's UI is unaffected because this is a separate process.

The runtime directory is written in by the installer, because Resolve's Scripts
folder has no relation to the repository and nothing can be imported from it.

## The supervisor loop

Blocking has a cost: this script cannot be re-run while it is alive, so a stale
runtime used to mean quitting Resolve. `serve()` now reports *why* it returned,
and a `reload` sends us back around this loop with the runtime re-imported from
disk — new code live, no UI interaction.

Re-importing is done into a **throwaway module object** rather than with
`importlib.reload`, so a module that fails halfway cannot leave the running one
half-overwritten. The old modules keep serving and the failure is reported.
"""

import base64
import importlib.util
import os
import sys
import traceback

RUNTIME_ROOT = base64.urlsafe_b64decode("@@RUNTIME_ROOT_B64@@".encode("ascii")).decode("utf-8")
_HOME_CONFIG = base64.urlsafe_b64decode("@@CONFIG_PATH_B64@@".encode("ascii")).decode("utf-8")

if RUNTIME_ROOT not in sys.path:
    sys.path.insert(0, RUNTIME_ROOT)


def resolve_config_path():
    """Runtime-local config first — the only one a sandboxed build can read.

    Inside the App Store sandbox, `~` is the container, so the absolute
    real-home path baked in at install time raises "Operation not permitted".
    The runtime directory sits inside the container next to the modules, so a
    copy there is always reachable. Both copies carry the same token, so the
    out-of-sandbox MCP client still authenticates from ~/.config.
    """
    local = os.path.join(RUNTIME_ROOT, "bridge.json")
    if os.path.isfile(local):
        return local
    return _HOME_CONFIG


CONFIG_PATH = resolve_config_path()


def acquire_resolve():
    candidate = globals().get("resolve")
    if candidate is not None:
        return candidate
    bmd = globals().get("bmd")
    if bmd is not None:
        try:
            return bmd.scriptapp("Resolve")
        except Exception:
            return None
    try:
        import DaVinciResolveScript as script_module
        return script_module.scriptapp("Resolve")
    except Exception:
        return None


def load_runtime():
    """Import the two runtime modules fresh, into new module objects.

    Returns ``(resolve_bridge, resolve_bridge_ops)`` or raises. Nothing already
    imported is mutated, so a failed reload leaves the running bridge intact.
    """
    loaded = []
    for name in ("resolve_bridge", "resolve_bridge_ops"):
        path = os.path.join(RUNTIME_ROOT, name + ".py")
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise ImportError("cannot load %s from %s" % (name, path))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Registered only once both have executed, so a half-loaded pair is
        # never visible to anything that imports by name.
        loaded.append((name, module))
    for name, module in loaded:
        sys.modules[name] = module
    return loaded[0][1], loaded[1][1]


def main():
    print("=" * 70)
    print("DaVinci Resolve MCP - in-app bridge")
    print("=" * 70)

    resolve_object = acquire_resolve()
    if resolve_object is None:
        print("  ERROR: no 'resolve' object. Run this from Workspace > Scripts.")
        return

    try:
        resolve_bridge, resolve_bridge_ops = load_runtime()
    except Exception:
        print("  ERROR: could not import the bridge runtime from:")
        print("    %s" % RUNTIME_ROOT)
        print("  Re-run: python scripts/install_resolve_bridge.py")
        traceback.print_exc()
        return

    try:
        product = resolve_object.GetProductName()
        version = resolve_object.GetVersionString()
    except Exception:
        product, version = "DaVinci Resolve", "?"

    generation = 0
    while True:
        try:
            config = resolve_bridge.load_config(CONFIG_PATH)
        except Exception as exc:
            print("  ERROR: bridge config unusable: %s" % exc)
            print("    tried: %s" % CONFIG_PATH)
            if CONFIG_PATH != _HOME_CONFIG:
                print("    (runtime-local copy; the ~/.config one is unreachable from a sandbox)")
            print("  Re-run: python scripts/install_resolve_bridge.py")
            return

        bridge_holder = {}

        def lifecycle(mode, _ops=resolve_bridge_ops, _rb=resolve_bridge, _holder=bridge_holder):
            """Vet the request, then flag the serve loop. Never stops in place."""
            if mode == "reload":
                problems = _rb.validate_runtime_sources(RUNTIME_ROOT)
                if problems:
                    # Refused by a bridge that is still serving, which is the
                    # whole point of checking before stopping.
                    raise _ops.OperationError(
                        "reload_rejected",
                        "the installed runtime will not compile: " + "; ".join(problems),
                    )
            _holder["bridge"].request_stop(mode)
            return {"generation": generation}

        operations = resolve_bridge_ops.ResolveOperations(
            resolve_object,
            media_roots=list(config.get("allowed_media_roots") or [os.path.expanduser("~")]),
            output_roots=list(config.get("allowed_output_roots") or [os.path.expanduser("~")]),
            lifecycle=lifecycle,
        )
        bridge = resolve_bridge.Bridge(
            resolve_object, config, resolve_bridge_ops.make_dispatch(operations)
        )
        bridge_holder["bridge"] = bridge

        model = resolve_bridge._host_model()
        print("  product     : %s %s" % (product, version))
        print("  listening   : 127.0.0.1:%s" % config["port"])
        print("  config      : %s" % CONFIG_PATH)
        print("  host model  : %s (blocking=%s)" % (model["model"], model["blocking_required"]))
        print("  operations  : %d" % len(resolve_bridge_ops.ResolveOperations.OPERATIONS))
        print("  generation  : %d" % generation)
        print()
        print("  The MCP server uses this bridge automatically when external")
        print("  scripting is unavailable. DAVINCI_RESOLVE_BRIDGE=1 forces it.")
        if model["blocking_required"]:
            print("  This script now HOLDS the listener open and will look busy until")
            print("  Resolve exits. That is expected — closing it stops the bridge.")
        print("=" * 70)

        try:
            outcome = bridge.serve(host_model=model)
        except KeyboardInterrupt:
            bridge.stop()
            print("  bridge stopped (interrupted).")
            return
        finally:
            bridge.stop()

        reason = (outcome or {}).get("stop_reason")
        if reason != "reload":
            print("  bridge stopped (%s)." % (reason or "returned"))
            return

        print("  reload requested — re-importing the runtime from disk...")
        try:
            resolve_bridge, resolve_bridge_ops = load_runtime()
        except Exception:
            # The old module objects are untouched, so serving again with them
            # is a real fallback rather than a hope.
            print("  RELOAD FAILED — continuing on the previously loaded runtime:")
            traceback.print_exc()
        generation += 1


main()
