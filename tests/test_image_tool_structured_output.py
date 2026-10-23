"""Image-returning tools must reach the client as image content (issue #314).

timeline_frame and timeline_markers are declared `-> Any`. With structured
output left at its default, FastMCP on Python 3.10 infers a `{"result": ...}`
output schema from that annotation, and `convert_result` then fails to
serialize the `Image`: the capture succeeds and the client receives
"Unable to serialize unknown type". On Python 3.11+ `typing.Any` is a class,
the inference finds no schema, and the bug is invisible, so a plain
`call_tool` test passes there with or without the fix.

The other existing tests call the tool functions directly and assert
`isinstance(out, Image)`, which never goes through `convert_result`. These go
through `mcp.call_tool`, and the subprocess test imports the server with the
3.10 inference forced, so the guard holds whichever Python runs the suite.
"""
import asyncio
import os
import subprocess
import sys
import textwrap
import unittest
from unittest import mock

from mcp.server.fastmcp import Image

import src.server as s

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JPEG = b"\xff\xd8capture"


def _blocks(sent):
    return sent[0] if isinstance(sent, tuple) else sent


class ImageToolsThroughCallToolTest(unittest.TestCase):
    def test_timeline_frame_capture_arrives_as_image_content(self):
        image = Image(data=JPEG, format="jpeg")
        with mock.patch.object(s, "_playhead_frame_capture", return_value=image):
            sent = asyncio.run(s.mcp.call_tool("timeline_frame", {"action": "capture"}))
        blocks = _blocks(sent)
        self.assertEqual([b.type for b in blocks], ["image"])
        self.assertEqual(blocks[0].mimeType, "image/jpeg")

    def test_timeline_markers_thumbnail_arrives_as_image_content(self):
        image = Image(data=JPEG, format="jpeg")
        with mock.patch.object(s, "_get_tl", return_value=(None, object(), None)), \
                mock.patch.object(s, "_playhead_frame_preview", return_value=image):
            sent = asyncio.run(s.mcp.call_tool("timeline_markers", {"action": "get_thumbnail_image"}))
        self.assertEqual([b.type for b in _blocks(sent)], ["image"])

    def test_image_tools_declare_no_output_schema(self):
        tools = {t.name: t for t in asyncio.run(s.mcp.list_tools())}
        for name in ("timeline_frame", "timeline_markers"):
            with self.subTest(tool=name):
                self.assertIsNone(tools[name].outputSchema)


# Runs in a child so the patched inference applies when the server registers
# its tools, without disturbing the server already imported in this process.
_PY310_PROBE = textwrap.dedent(
    """
    import asyncio, typing
    from unittest import mock
    import mcp.server.fastmcp.utilities.func_metadata as fm

    _real = fm._try_create_model_and_schema

    def _as_on_py310(original_annotation, type_expr, func_name):
        # Python 3.10: typing.Any is not a class, so it takes the wrapping branch.
        if type_expr is typing.Any:
            model = fm._create_wrapped_model(func_name, original_annotation)
            return model, model.model_json_schema(), True
        return _real(original_annotation, type_expr, func_name)

    fm._try_create_model_and_schema = _as_on_py310

    # The patch must make `-> Any` wrap, or this probe proves nothing.
    def _any_tool() -> typing.Any: ...
    assert fm.func_metadata(_any_tool).wrap_output

    import src.server as s
    from mcp.server.fastmcp import Image

    image = Image(data=b"\\xff\\xd8capture", format="jpeg")
    with mock.patch.object(s, "_playhead_frame_capture", return_value=image):
        sent = asyncio.run(s.mcp.call_tool("timeline_frame", {"action": "capture"}))
    blocks = sent[0] if isinstance(sent, tuple) else sent
    print("TYPES", [b.type for b in blocks])
    """
)


class ImageToolsUnderPy310InferenceTest(unittest.TestCase):
    def test_capture_survives_the_py310_output_schema_inference(self):
        env = dict(os.environ, PYTHONPATH=REPO)
        proc = subprocess.run(
            [sys.executable, "-c", _PY310_PROBE],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertIn("TYPES ['image']", proc.stdout)


if __name__ == "__main__":
    unittest.main()
