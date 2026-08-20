"""Render format/codec id normalization — display names to the ids Resolve wants.

`Project.GetRenderFormats()` returns ``{display_name: format_id}`` (e.g.
``{"QuickTime": "mov"}``) and `Project.GetRenderCodecs(format_id)` returns
``{display_name: codec_id}`` (e.g. ``{"Apple ProRes 422 HQ": "ProRes422HQ"}``).
But `GetRenderCodecs`, `GetRenderResolutions` and `SetCurrentRenderFormatAndCodec`
all expect the **id**, so passing the label the user actually sees in the UI is
silently rejected.

The format half of this was issue #59. The codec half hid longer because for
``mp4`` the label and id are identical (``{"H.264": "H.264"}``), so the common web
case works by coincidence; only formats where they diverge — QuickTime/ProRes,
i.e. every professional master — actually break.

These live here rather than in `server.py` so the compound and granular servers
share one implementation. The format fix originally landed only in `server.py`
and never reached `src/granular/project.py`; a shared module is what stops that
recurring.

Both resolvers **normalize, they do not validate**: an unrecognized value passes
through unchanged for Resolve to reject. Callers that need a hard failure must
check the Resolve return value (see `_prepare_render_job`, which refuses to queue
a job when `SetCurrentRenderFormatAndCodec` returns False).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

__all__ = [
    "render_format_id_from_formats",
    "render_codec_id_from_codecs",
]


def _match_by_label_or_id(mapping: Dict[Any, Any], value: str) -> Optional[str]:
    """Case-insensitive match of `value` against either side of a {label: id} map."""
    needle = value.lower()
    for label, identifier in mapping.items():
        label_text = str(label)
        id_text = str(identifier)
        if label_text.lower() == needle:
            return id_text or value
        if id_text.lower() == needle:
            return id_text
    return None


def render_format_id_from_formats(formats: Any, fmt: str) -> str:
    """Normalize a render format display name/extension to its format id."""
    if not isinstance(fmt, str) or not fmt or not isinstance(formats, dict):
        return fmt
    if fmt in formats:
        return formats.get(fmt) or fmt
    if fmt in formats.values():
        return fmt
    return _match_by_label_or_id(formats, fmt) or fmt


def render_codec_id_from_codecs(codecs: Any, codec: str) -> str:
    """Normalize a render codec display name to its codec id."""
    if not isinstance(codec, str) or not codec or not isinstance(codecs, dict):
        return codec
    if codec in codecs:
        return codecs.get(codec) or codec
    if codec in codecs.values():
        return codec
    return _match_by_label_or_id(codecs, codec) or codec
