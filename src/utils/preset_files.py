"""Where Resolve writes an exported render or burn-in preset.

``ExportRenderPreset(presetName, exportPath)`` and
``ExportBurnInPreset(presetName, exportPath)`` treat ``exportPath`` as a
folder, not a file. Resolve creates the folder if needed and writes
``<presetName>.xml`` inside it. Measured on free 21.0.4.5 (macOS) through the
in-app bridge:

- ``/tmp/a/My.xml`` became the folder ``/tmp/a/My.xml/`` holding ``My.xml``
- ``/tmp/b/other.xml`` became the folder ``/tmp/b/other.xml/`` holding ``My.xml``
- ``/tmp/c`` (an existing folder) received ``/tmp/c/My.xml``

The import calls take the file itself, so a caller needs the real file path to
round-trip a preset.
"""

from __future__ import annotations

import os


def preset_export_file(export_path: str, preset_name: str) -> str:
    """The file Resolve writes when it exports ``preset_name`` to ``export_path``.

    The folder behaviour above is one build's measurement. If ``export_path``
    is itself a file after the export and ``<export_path>/<preset_name>.xml``
    is not, the build wrote the exact path it was given, so that path is the
    file. Otherwise, including before anything exists, the answer is the
    measured one.
    """
    inside = os.path.join(export_path, f"{preset_name}.xml")
    if os.path.isfile(export_path) and not os.path.isfile(inside):
        return export_path
    return inside
