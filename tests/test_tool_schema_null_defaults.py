"""Every tool argument that defaults to ``None`` must accept ``null``.

An argument annotated ``str = None`` (or ``float = None``, ``bool = None``)
becomes a schema like ``{"type": "string", "default": null}``: it advertises a
default its own type rejects. Some agent frameworks fill every optional argument
with its advertised default, so they send ``null``, and the call fails argument
validation before the tool runs. Sixteen granular arguments had this shape, for
example ``create_project.media_location_path``.

Runs fully offline: enumerating tools via ``mcp.list_tools()`` touches no live
handle.
"""
import asyncio
import unittest


def _allows_null(schema):
    if schema.get("type") == "null":
        return True
    if isinstance(schema.get("type"), list) and "null" in schema["type"]:
        return True
    return any(_allows_null(s) for s in schema.get("anyOf", []))


def _null_default_args_rejecting_null(mcp):
    bad = []
    for tool in asyncio.run(mcp.list_tools()):
        for name, prop in tool.inputSchema.get("properties", {}).items():
            if "default" in prop and prop["default"] is None and not _allows_null(prop):
                bad.append(f"{tool.name}.{name}")
    return sorted(bad)


class NullDefaultSchemaTest(unittest.TestCase):
    def test_compound_server(self):
        import src.server as server

        self.assertEqual(_null_default_args_rejecting_null(server.mcp), [])

    def test_granular_server(self):
        from src.granular import mcp

        self.assertEqual(_null_default_args_rejecting_null(mcp), [])


if __name__ == "__main__":
    unittest.main()
