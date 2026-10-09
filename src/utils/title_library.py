"""Discover the installed native title library; never ship copied vendor templates."""
from pathlib import Path
import zipfile
from src.utils.platform import get_resolve_paths


def title_archive(explicit=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise ValueError("templates_archive must name an installed Templates.drfx")
        return path
    lib = Path(get_resolve_paths()["lib_path"])
    candidates = [lib.parent / "Fusion/Templates/Templates.drfx"]
    for parent in lib.parents:
        candidates.extend([parent / "Fusion/Templates/Templates.drfx",
                           parent / "Resources/Fusion/Templates/Templates.drfx"])
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise ValueError("Installed Templates.drfx unavailable; supply templates_archive explicitly")


def list_title_presets(templates_archive=None):
    archive = title_archive(templates_archive)
    with zipfile.ZipFile(archive) as zipped:
        names = sorted(n for n in zipped.namelist()
                       if n.startswith("Edit/Titles/") and n.endswith(".setting"))
    presets = []
    for entry in names:
        subtitle = entry.startswith("Edit/Titles/Subtitles/")
        presets.append({"name": Path(entry).stem, "template_id": "Templates/" + entry[:-8],
                        "category": "animated_subtitle" if "/Subtitles/Animated/" in entry
                        else "subtitle" if subtitle else "title"})
    return {"success": True, "archive": str(archive), "presets": presets,
            "count": len(presets), "verification": "installed_inventory_only"}


def find_subtitle_preset(name, templates_archive=None):
    matches = [p for p in list_title_presets(templates_archive)["presets"]
               if p["category"] != "title" and name in (p["name"], p["template_id"])]
    if len(matches) != 1:
        raise ValueError("Preset must identify exactly one installed subtitle template")
    return matches[0]
