"""Diagnose why our v2.5.0 Fuses aren't registering.

Tests three hypotheses:
1. Is comp.AddTool working at all? (try a built-in: Background)
2. Does Resolve register a HAND-WRITTEN minimal Fuse? (env check)
3. Does Resolve register one of our GENERATED Fuses? (generator check)
"""

import os
import subprocess
import sys
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

from src.utils.platform import get_resolve_paths, get_resolve_plugin_paths

paths = get_resolve_paths()
os.environ["RESOLVE_SCRIPT_API"] = paths["api_path"]
os.environ["RESOLVE_SCRIPT_LIB"] = paths["lib_path"]
sys.path.insert(0, paths["modules_path"])

import DaVinciResolveScript as dvr_script  # noqa: E402
from src.utils import fuse_templates  # noqa: E402


# Hand-written minimal Fuse — pure pass-through, no aux features.
MINIMAL_FUSE = """\
-- @mcp-fuse name=McpMinimal kind=minimal type=tool
FuRegisterClass("McpMinimal", CT_Tool, {
    REGS_Category = "Fuses\\\\MCP",
    REGS_OpIconString = "Mini",
    REGS_OpDescription = "Hand-written minimal pass-through",
})

function Create()
    InImage = self:AddInput("Input", "Input", {
        LINKID_DataType = "Image",
        LINK_Main = 1,
    })
    OutImage = self:AddOutput("Output", "Output", {
        LINKID_DataType = "Image",
        LINK_Main = 1,
    })
end

function Process(req)
    OutImage:Set(req, InImage:GetValue(req))
end
"""


def main():
    candidate = dvr_script.scriptapp("Resolve")
    if candidate is not None:
        try:
            if candidate.GetVersion():
                print("ABORT: Resolve is already running. Quit it first.")
                sys.exit(1)
        except Exception:
            pass

    fuses_dir = get_resolve_plugin_paths()["fuses_dir"]
    os.makedirs(fuses_dir, exist_ok=True)

    # Install BOTH hand-written and generated Fuses
    installed = []

    minimal_path = os.path.join(fuses_dir, "McpMinimal.fuse")
    with open(minimal_path, "w", encoding="utf-8") as f:
        f.write(MINIMAL_FUSE)
    installed.append(("minimal", "McpMinimal", minimal_path))
    print(f"[OK] hand-written minimal: {os.path.basename(minimal_path)}")

    gen_source = fuse_templates.color_matrix("McpGenerated", {"ops": ["brightness"]})
    gen_path = os.path.join(fuses_dir, "McpGenerated.fuse")
    with open(gen_path, "w", encoding="utf-8") as f:
        f.write(gen_source)
    installed.append(("generated", "McpGenerated", gen_path))
    print(f"[OK] generated color_matrix: {os.path.basename(gen_path)}")

    # Print what's in the generated file for visual inspection
    print("\n=== Generated Fuse first 40 lines ===")
    with open(gen_path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 40:
                break
            print(f"  {i+1:3d}| {line.rstrip()}")

    handle = None
    try:
        print("\n=== Launching Resolve ===")
        subprocess.Popen(["open", "/Applications/DaVinci Resolve/DaVinci Resolve.app"])

        for i in range(60):
            time.sleep(2)
            cand = dvr_script.scriptapp("Resolve")
            if cand is not None:
                try:
                    if cand.GetVersion():
                        handle = cand
                        print(f"  Connected after {(i+1)*2}s")
                        break
                except Exception:
                    continue
        if handle is None:
            print("ABORT: Resolve did not respond")
            sys.exit(1)

        # Build a project + timeline + Fusion-composition clip so we have a
        # real per-clip Fusion comp that accepts AddTool.
        pm = handle.GetProjectManager()
        try:
            pm.DeleteProject("McpDiag")
        except Exception:
            pass
        project = pm.CreateProject("McpDiag")
        if project is None:
            print("ABORT: CreateProject failed")
            sys.exit(1)
        mp = project.GetMediaPool()
        timeline = mp.CreateEmptyTimeline("McpDiagTimeline")
        if timeline is None:
            print("ABORT: CreateEmptyTimeline failed")
            sys.exit(1)
        timeline.InsertFusionCompositionIntoTimeline()
        handle.OpenPage("fusion")
        time.sleep(2)

        fusion = handle.Fusion()
        comp = fusion.GetCurrentComp()
        if comp is None:
            print("ABORT: GetCurrentComp returned None")
            sys.exit(1)
        print(f"  Comp: {comp.GetAttrs().get('COMPS_Name', '?')}")

        # Give Fusion an extra moment to finish indexing Fuses
        print("\n  Waiting 5s for Fuse registry to settle...")
        time.sleep(5)

        def _add(tool_type):
            comp.Lock()
            try:
                return comp.AddTool(tool_type, -1, -1)
            finally:
                comp.Unlock()

        print("\n=== Test 1: Built-in tool baseline ===")
        try:
            t = _add("Background")
            if t is None:
                print("  [FAIL] AddTool('Background') returned None — Lock/Unlock didn't help")
            else:
                attrs = t.GetAttrs() or {}
                print(f"  [OK]   AddTool('Background') -> {attrs.get('TOOLS_RegID', '?')}")
                t.Delete()
        except Exception as e:
            print(f"  [ERR]  {e}")

        print("\n=== Test 2: Hand-written minimal Fuse ===")
        try:
            t = _add("McpMinimal")
            if t is None:
                print("  [FAIL] AddTool('McpMinimal') returned None")
                print("         → Resolve did not register the hand-written Fuse")
            else:
                attrs = t.GetAttrs() or {}
                print(f"  [OK]   AddTool('McpMinimal') -> {attrs.get('TOOLS_RegID', '?')}")
                t.Delete()
        except Exception as e:
            print(f"  [ERR]  {e}")

        print("\n=== Test 3: Generated color_matrix Fuse ===")
        try:
            t = _add("McpGenerated")
            if t is None:
                print("  [FAIL] AddTool('McpGenerated') returned None")
                print("         → Generator output rejected by Fusion's Lua loader")
            else:
                attrs = t.GetAttrs() or {}
                print(f"  [OK]   AddTool('McpGenerated') -> {attrs.get('TOOLS_RegID', '?')}")
                t.Delete()
        except Exception as e:
            print(f"  [ERR]  {e}")

        # As a tiebreaker: enumerate ALL registered tool classes, see if our names appear
        print("\n=== Test 4: Dump tool registry (filter for Mcp*) ===")
        try:
            reg = fusion.GetRegList(2)  # CT_Tool = 2 typically
            if reg:
                mcp_keys = [k for k in reg.keys() if isinstance(k, str) and "Mcp" in k]
                if mcp_keys:
                    for k in mcp_keys:
                        print(f"  registered: {k}")
                else:
                    print("  No Mcp* classes in registry — registration failed")
            else:
                print(f"  GetRegList returned: {reg}")
        except Exception as e:
            print(f"  GetRegList not available: {e}")

    finally:
        print("\n=== Cleanup ===")
        for kind, name, path in installed:
            try:
                os.unlink(path)
                print(f"  removed: {os.path.basename(path)}")
            except OSError:
                pass
        try:
            if 'pm' in locals() and pm is not None:
                cur = pm.GetCurrentProject()
                if cur is not None:
                    pm.CloseProject(cur)
                pm.DeleteProject("McpDiag")
                print("  removed: McpDiag project")
        except Exception:
            pass
        try:
            h = dvr_script.scriptapp("Resolve")
            if h is not None:
                print("  Quitting Resolve...")
                h.Quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
