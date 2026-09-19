"""Keep every Python child process of the offline suite away from DaVinci Resolve.

`tests/offline_guard.py` guards the test process by swapping the server's entry
points in place, and nothing it swaps exists in a child process. Some tests start
real Python children. `server._open_control_panel` runs `src/analysis_dashboard.py`
with `subprocess.Popen`, and that child imported Blackmagic's module and connected
to whatever Resolve was open. Measured with a tripwire standing in for the library,
a full `python -m unittest discover -s tests -t .` run of v4.8.4 made 6
`scriptapp("Resolve")` calls from 3 panel children. The calls came from
`_current_resolve_project_context`, the inventory warm-up and `_resolve_identity`,
all through `_connect_resolve_read_only`. The children came from
`test_control_panel_ipv6_loopback` (twice), whose docstring says "No Resolve", and
from `test_tool_argument_validation`, which walks every action including
`open_control_panel`.

So the guard puts this directory first on PYTHONPATH. A Python child that inherits
the environment imports this file at startup, before any code of its own, and:

1. Runs the `sitecustomize` it shadows. Homebrew's Python ships one that fixes
   `sys.path` and `sys.prefix`, and a developer's own tripwire is one as well.
   This runs first so that the stand-in below goes in front of anything the
   shadowed file installs. If that file chains on to the next `sitecustomize`
   and lands back here, the chain continues past this file instead of looping.
2. Answers `DaVinciResolveScript` and `fusionscript` with an empty module, from a
   finder at `sys.meta_path[0]`, the same kind of stand-in `offline_guard`
   installs in the test process. A test's own fake on the child's `sys.path` loses
   to it too, and that is deliberate, because a fake found on the path looks
   exactly like the real module. The stand-in has no `scriptapp`, so
   `connect_resolve()` raises before its bridge fallback instead of falling
   through to it. Any other missing attribute fails with a message that names
   this file.
3. Refuses to start the Resolve application through `subprocess`. A child that
   imports `src.server` and calls a tool falls through `get_resolve()` to
   `_launch_resolve()` whenever Resolve is closed, and the in-process swap of that
   function does not exist in a child.

The parent closes the in-app bridge. `offline_guard` points
`DAVINCI_RESOLVE_BRIDGE_CONFIG` at a file that does not exist, and children
inherit that value, including children that replace PYTHONPATH.

Limits. A child started with its own PYTHONPATH, with `-E` or `-I`, or with an
environment built from scratch never loads this file. `scripts/doctor.py`'s probe
sets PYTHONPATH to the Modules directory. That is why the fake DaVinciResolveScript
in `test_doctor_paths` still loads in its probe, and why every doctor test patches
the paths it probes. `install.verify_resolve_connection` does the same, and
`test_scripting_lib_discovery.test_the_live_probe_agrees_with_the_summary` runs it
for real whenever Resolve is installed. Its child imports Blackmagic's module and
calls `scriptapp("Resolve")` on the open application, and nothing here stops it.
Launches that bypass `subprocess` (`os.system`, `os.exec*`) are not intercepted.

Kept free of `src` and `tests` imports, and of syntax newer than Python 3.6,
because every Python interpreter the suite starts runs this file, including one
that is not the suite's own.
"""

import errno
import functools
import importlib.machinery
import importlib.util
import os
import shlex
import sys

#: Blackmagic's scripting modules. `DaVinciResolveScript.py` is only a loader: it
#: tries `import fusionscript`, then loads the native library by path. Both names
#: are answered here, so neither route reaches the library.
SCRIPTING_MODULES = ("DaVinciResolveScript", "fusionscript")

#: Set on every stand-in module. It is the same marker the in-process guard uses,
#: so a test can tell a stand-in apart from the real library and from its own stub.
STUB_MARKER = "__resolve_offline_guard_stub__"

#: Set on the finder and on the wrapped `Popen.__init__`, so a second copy of this
#: file (another checkout on PYTHONPATH) does not install a second layer.
GUARD_MARKER = "resolve_offline_guard"

#: Startup state shared by every execution of this file in one process, kept on
#: `sys` because a re-executed copy is a new module object. It exists only while
#: the chain below runs.
_CHAIN_STATE = "_resolve_offline_guard_sitecustomize_chain"

_HERE = os.path.dirname(os.path.abspath(__file__))


def _is_guard_dir(entry):
    """True for this directory and for a copy of it from another checkout."""
    path = os.path.realpath(entry or os.curdir)
    return path == os.path.realpath(_HERE) or os.path.basename(path) == os.path.basename(_HERE)


def run_shadowed_sitecustomize(ran):
    """Execute the first `sitecustomize` on `sys.path` that has not run yet.

    Python imports only the first `sitecustomize` it finds, so putting this
    directory first would otherwise silently drop the interpreter's own. Every
    copy of this directory is skipped, and so is every file in `ran`, the set of
    origins already executed. A shadowed file often chains in turn to "the next
    sitecustomize that is not me", as a developer's tripwire does, and that
    lands back on this file. The copy that runs then continues from here, which
    reaches the file the shadowed one would have reached without the guard on the
    path. Without `ran` the two files chain into each other until RecursionError,
    and the guard is never installed.

    A failure is reported the way `site` reports one, and the guard is installed
    regardless.
    """
    for entry in sys.path:
        if _is_guard_dir(entry):
            continue
        spec = importlib.machinery.PathFinder.find_spec("sitecustomize", [entry])
        if spec is None or spec.loader is None or spec.origin in ran:
            continue
        ran.add(spec.origin)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.stderr.write(
                "Error in sitecustomize %s (run by the offline test guard): %s: %s\n"
                % (spec.origin, exc.__class__.__name__, exc)
            )
        return module
    return None


class ScriptingModuleStub(object):
    """Answer `import DaVinciResolveScript` / `import fusionscript` with an empty module.

    A `sys.meta_path` finder rather than a `sys.modules` entry, so it answers every
    import, including one that follows a test deleting the module.
    """

    resolve_offline_guard = True

    def find_spec(self, fullname, path=None, target=None):
        if fullname not in SCRIPTING_MODULES:
            return None
        return importlib.machinery.ModuleSpec(fullname, self, origin="offline test guard stand-in")

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = module.__name__
        module.__doc__ = "Offline stand-in for Blackmagic's scripting module; no scriptapp."
        setattr(module, STUB_MARKER, True)

        def __getattr__(attr):
            raise AttributeError(
                "%s is the offline test guard's stand-in (%s), which has no %r: a child "
                "process of the offline suite cannot reach DaVinci Resolve"
                % (name, os.path.join("tests", "offline_child_site", "sitecustomize.py"), attr)
            )

        module.__getattr__ = __getattr__


def install_scripting_stub():
    """Put the stand-in at `sys.meta_path[0]`, moving an existing one to the front."""
    existing = [finder for finder in sys.meta_path if getattr(finder, GUARD_MARKER, False)]
    for finder in existing:
        sys.meta_path.remove(finder)
    for name in SCRIPTING_MODULES:
        if name in sys.modules and not getattr(sys.modules[name], STUB_MARKER, False):
            del sys.modules[name]
    sys.meta_path.insert(0, existing[0] if existing else ScriptingModuleStub())


def _mentions_resolve(text):
    """An argument to `open` or `osascript` that names Resolve: bundle, app name or bundle id."""
    lowered = text.lower()
    return "davinci resolve" in lowered or "davinciresolve" in lowered


def _inside_resolve_install(program):
    """A program inside a Resolve installation, on any platform.

    Anchored on the install layout rather than on the words "DaVinci Resolve"
    anywhere in the path, so a checkout or venv under a folder of that name still runs.
    """
    parts = [part.lower() for part in program.replace("\\", "/").split("/") if part]
    if any(part.startswith("davinci resolve") and part.endswith(".app") for part in parts):
        return True  # macOS: anything inside the bundle, including fuscript
    for index, part in enumerate(parts[:-1]):
        if part == "blackmagic design" and parts[index + 1] == "davinci resolve":
            return True  # Windows: C:\Program Files\Blackmagic Design\DaVinci Resolve\...
    return program.replace("\\", "/").startswith("/opt/resolve/")  # Linux


def _argv(args):
    if isinstance(args, (str, bytes)):
        text = os.fsdecode(args)
        # POSIX rules would read the backslashes of a Windows path as escapes.
        posix = os.name != "nt"
        try:
            tokens = shlex.split(text, posix=posix)
        except ValueError:
            tokens = text.split()
        return tokens if posix else [token.strip('"') for token in tokens]
    if isinstance(args, os.PathLike):
        return [os.fsdecode(args)]
    return [os.fsdecode(arg) for arg in args]


def launches_resolve(args, executable=None):
    """Would this `Popen` argument list start the DaVinci Resolve application?

    Matches what `resolve_runtime.launch_command` builds (`open <bundle>`, the
    binary inside the bundle, `Resolve.exe`, `/opt/resolve/bin/resolve`), any
    other program inside an installation such as `fuscript`, and `open -a` or
    AppleScript naming the app. Only `open` and `osascript` have their arguments
    read. For any other program only the program itself is checked, so a Python
    child that merely mentions the bundle path still runs.
    """
    try:
        argv = _argv(args)
    except TypeError:
        return False
    if executable is not None:
        argv = [os.fsdecode(executable)] + argv[1:]
    if not argv:
        return False
    program = argv[0]
    name = program.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name in ("open", "osascript"):
        return any(_mentions_resolve(arg) for arg in argv[1:])
    return _inside_resolve_install(program)


def install_launch_guard():
    import subprocess

    original = subprocess.Popen.__init__
    if getattr(original, GUARD_MARKER, False):
        return

    @functools.wraps(original)
    def guarded_init(self, args, *pargs, **kwargs):
        executable = kwargs.get("executable", pargs[1] if len(pargs) > 1 else None)
        if launches_resolve(args, executable):
            raise PermissionError(
                errno.EPERM,
                "the offline test guard refuses to launch DaVinci Resolve from a test child "
                "process (tests/offline_child_site/sitecustomize.py)",
                " ".join(_argv(args)),
            )
        return original(self, args, *pargs, **kwargs)

    setattr(guarded_init, GUARD_MARKER, True)
    subprocess.Popen.__init__ = guarded_init


def install():
    state = getattr(sys, _CHAIN_STATE, None)
    if state is not None:
        # Reached through a file this one is chaining to. Continue the chain past
        # this directory, and leave installing to the copy that started it: that
        # copy installs after everything in the chain, so its stand-in ends up in
        # front of theirs.
        run_shadowed_sitecustomize(state)
        return
    ran = set()
    importing = sys.modules.get("sitecustomize")
    origin = getattr(getattr(importing, "__spec__", None), "origin", None)
    if origin:
        # The file Python imported as `sitecustomize` is already running. That is
        # this file, or one earlier on the path that chained to it, and in both
        # cases it must not run a second time.
        ran.add(origin)
    setattr(sys, _CHAIN_STATE, ran)
    try:
        run_shadowed_sitecustomize(ran)
    finally:
        delattr(sys, _CHAIN_STATE)
    install_scripting_stub()
    install_launch_guard()


# Only when the interpreter loads this file as its `sitecustomize`. A test that
# loads it under another name to exercise `launches_resolve` must not rewire the
# test process.
if __name__ == "sitecustomize":
    install()
