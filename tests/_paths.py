"""A path the temp-path guards will always reject, wherever the suite runs.

Tests that assert `require_temp_path` / `require_temp_target` refuses a target
used to build it from `os.getcwd()`. That silently couples the assertion to
where the suite happens to run: inside a git worktree under `/tmp` the cwd *is*
a temp path, the guard correctly permits the write, and the test fails — after
`_safe_export_lut` has already written a real `look.cube` into the working
directory. One such artifact was committed by accident.

`_render_temp_path_ok` accepts a path under `tempfile.gettempdir()`, `/tmp` or
`/private/tmp`. A directory at the filesystem root is under none of them on
POSIX, and on Windows `commonpath` either lands on the drive root or raises
`ValueError` across drives — rejected either way. Nothing is created here: the
guard refuses before any mkdir, and that refusal is the whole assertion.
"""
import os

# Deliberately implausible, so a stray write is obvious in a diff rather than
# blending into a plausible-looking output directory.
NON_TEMP_DIR = os.path.join(os.path.abspath(os.sep), "davinci-resolve-mcp-not-a-temp-dir")

# For guards that check existence *before* they check temp-ness: a
# non-existent directory trips "does not exist" and the temp assertion never
# runs. The filesystem root (drive root on Windows) is the one directory that
# is both guaranteed to exist and guaranteed not to sit under a temp root —
# `commonpath` puts it at the root itself, which never equals a temp root.
NON_TEMP_EXISTING_DIR = os.path.abspath(os.sep)


def non_temp_path(*parts: str) -> str:
    """An absolute path guaranteed to sit outside every temp root.

    The path does not exist, and tests relying on it must not create it.
    """
    return os.path.join(NON_TEMP_DIR, *parts)
