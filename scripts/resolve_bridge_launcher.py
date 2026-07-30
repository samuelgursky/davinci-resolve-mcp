"""Workspace ▸ Scripts ▸ resolve_bridge — starts the in-app bridge.

Installed by ``python scripts/install_resolve_bridge.py``. Run it once per
Resolve session; it holds the loopback listener open until Resolve exits.

**This blocks, on purpose.** A Scripts-menu script is a child process of Resolve
(measured on Studio 19.1.3.7 and free 21.0.3.7), so a background thread dies the
instant this function returns. `serve()` detects the host model and blocks or
returns accordingly — see `src/utils/resolve_bridge.py`. While it is running this
script will appear "busy" in Resolve; that is the listener staying alive, not a
hang, and Resolve's UI is unaffected because this is a separate process.

The runtime directory is written in by the installer, because Resolve's Scripts
folder has no relation to the repository and nothing can be imported from it.
"""

import base64
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


def main():
    print("=" * 70)
    print("DaVinci Resolve MCP - in-app bridge")
    print("=" * 70)

    resolve_object = acquire_resolve()
    if resolve_object is None:
        print("  ERROR: no 'resolve' object. Run this from Workspace > Scripts.")
        return

    try:
        import resolve_bridge
        import resolve_bridge_ops
    except Exception:
        print("  ERROR: could not import the bridge runtime from:")
        print("    %s" % RUNTIME_ROOT)
        print("  Re-run: python scripts/install_resolve_bridge.py")
        traceback.print_exc()
        return

    try:
        config = resolve_bridge.load_config(CONFIG_PATH)
    except Exception as exc:
        print("  ERROR: bridge config unusable: %s" % exc)
        print("    tried: %s" % CONFIG_PATH)
        if CONFIG_PATH != _HOME_CONFIG:
            print("    (runtime-local copy; the ~/.config one is unreachable from a sandbox)")
        print("  Re-run: python scripts/install_resolve_bridge.py")
        return

    try:
        product = resolve_object.GetProductName()
        version = resolve_object.GetVersionString()
    except Exception:
        product, version = "DaVinci Resolve", "?"

    operations = resolve_bridge_ops.ResolveOperations(
        resolve_object,
        media_roots=list(config.get("allowed_media_roots") or [os.path.expanduser("~")]),
        output_roots=list(config.get("allowed_output_roots") or [os.path.expanduser("~")]),
    )
    bridge = resolve_bridge.Bridge(
        resolve_object, config, resolve_bridge_ops.make_dispatch(operations)
    )

    model = resolve_bridge._host_model()
    print("  product     : %s %s" % (product, version))
    print("  listening   : 127.0.0.1:%s" % config["port"])
    print("  config      : %s" % CONFIG_PATH)
    print("  host model  : %s (blocking=%s)" % (model["model"], model["blocking_required"]))
    print("  operations  : %d" % len(resolve_bridge_ops.ResolveOperations.OPERATIONS))
    print()
    print("  The MCP server connects with DAVINCI_RESOLVE_BRIDGE=1.")
    if model["blocking_required"]:
        print("  This script now HOLDS the listener open and will look busy until")
        print("  Resolve exits. That is expected — closing it stops the bridge.")
    print("=" * 70)

    try:
        bridge.serve(host_model=model)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
        print("  bridge stopped.")


main()
