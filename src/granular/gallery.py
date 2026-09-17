"""Gallery, still album, and powergrade tools."""

from src.granular.common import *  # noqa: F401,F403

resolve = ResolveProxy()


def _index_in_range(idx, length):
    """True for a real 0-based position. Negatives are refused: Python would read
    `albums[-1]` as the last album and act on something nobody named."""
    return isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < length


def _invalid_indices(indices, length):
    """The entries of `indices` that are not a 0-based position below `length`."""
    return [i for i in indices if not _index_in_range(i, length)]


@mcp.tool(annotations=READ_ONLY_TOOL)
def get_gallery_album_name() -> Dict[str, Any]:
    """Get the name of the current gallery album."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    name = gallery.GetAlbumName()
    return {"album_name": name if name else ""}


@mcp.tool()
@granular_destructive_op()
def set_gallery_album_name(name: str) -> Dict[str, Any]:
    """Set the name of the current gallery album.

    Args:
        name: New album name.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    result = gallery.SetAlbumName(name)
    return {"success": bool(result)}


@mcp.tool()
def get_gallery_still_albums() -> Dict[str, Any]:
    """Get list of all gallery still albums."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    albums = gallery.GetGalleryStillAlbums()
    return {"albums": [str(a) for a in albums] if albums else []}


@mcp.tool()
def get_gallery_power_grade_albums() -> Dict[str, Any]:
    """Get list of all gallery power grade albums."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    albums = gallery.GetGalleryPowerGradeAlbums()
    return {"albums": [str(a) for a in albums] if albums else []}


@mcp.tool()
def get_current_still_album() -> Dict[str, Any]:
    """Get the current still album."""
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    album = gallery.GetCurrentStillAlbum()
    return {"has_album": album is not None}


@mcp.tool()
@granular_destructive_op()
def set_current_still_album(album_index: int) -> Dict[str, Any]:
    """Set the current still album by index.

    Args:
        album_index: 0-based index of the album in GetGalleryStillAlbums() list.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index < 0 or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    result = gallery.SetCurrentStillAlbum(albums[album_index])
    return {"success": bool(result)}


@mcp.tool()
def create_gallery_still_album(album_name: str = "") -> Dict[str, Any]:
    """Create a new gallery still album.

    Args:
        album_name: Optional name for the new album.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    if album_name:
        album = gallery.CreateGalleryStillAlbum(album_name)
    else:
        album = gallery.CreateGalleryStillAlbum()
    return {"success": album is not None}


@mcp.tool()
def create_gallery_power_grade_album(album_name: str = "") -> Dict[str, Any]:
    """Create a new gallery power grade album.

    Args:
        album_name: Optional name for the new album.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    if album_name:
        album = gallery.CreateGalleryPowerGradeAlbum(album_name)
    else:
        album = gallery.CreateGalleryPowerGradeAlbum()
    return {"success": album is not None}


@mcp.tool()
def get_album_stills(album_index: int = 0) -> Dict[str, Any]:
    """Get list of stills in a gallery album.

    Args:
        album_index: 0-based index of the album. Default: 0.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    if not gallery:
        return {"error": "Failed to get Gallery"}
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index < 0 or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    return {"still_count": len(stills) if stills else 0}


@mcp.tool()
def get_still_label(album_index: int, still_index: int) -> Dict[str, Any]:
    """Get the label of a still in a gallery album.

    Args:
        album_index: 0-based album index.
        still_index: 0-based still index.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index < 0 or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    if not stills or still_index < 0 or still_index >= len(stills):
        return {"error": f"No still at index {still_index}"}
    label = albums[album_index].GetLabel(stills[still_index])
    return {"label": label if label else ""}


@mcp.tool()
@granular_destructive_op()
def set_still_label(album_index: int, still_index: int, label: str) -> Dict[str, Any]:
    """Set the label of a still in a gallery album.

    Args:
        album_index: 0-based album index.
        still_index: 0-based still index.
        label: New label for the still.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index < 0 or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    if not stills or still_index < 0 or still_index >= len(stills):
        return {"error": f"No still at index {still_index}"}
    result = albums[album_index].SetLabel(stills[still_index], label)
    return {"success": bool(result)}


@mcp.tool()
def import_stills_to_album(album_index: int, file_paths: List[str]) -> Dict[str, Any]:
    """Import stills from file paths into a gallery album.

    Args:
        album_index: 0-based album index.
        file_paths: List of absolute file paths to import.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index < 0 or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    result = albums[album_index].ImportStills(file_paths)
    return {"success": bool(result)}


@mcp.tool()
def export_stills_from_album(album_index: int, folder_path: str, file_prefix: str = "still", format: str = "dpx") -> Dict[str, Any]:
    """Export stills from a gallery album.

    Args:
        album_index: 0-based album index.
        folder_path: Directory to export to.
        file_prefix: Filename prefix. Default: 'still'.
        format: File format (dpx, cin, tif, jpg, png, ppm, bmp, xpm, drx). Default: 'dpx'.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index < 0 or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    if not stills:
        return {"error": "No stills in album"}
    result = albums[album_index].ExportStills(stills, folder_path, file_prefix, format)
    return {"success": bool(result)}


@mcp.tool()
@granular_destructive_op()
def delete_stills_from_album(album_index: int, still_indices: List[int]) -> Dict[str, Any]:
    """Delete stills from a gallery album.

    Args:
        album_index: 0-based album index.
        still_indices: List of 0-based still indices to delete.
    """
    resolve = get_resolve()
    if resolve is None:
        return {"error": "Not connected to DaVinci Resolve"}
    project = resolve.GetProjectManager().GetCurrentProject()
    if not project:
        return {"error": "No project open"}
    gallery = project.GetGallery()
    albums = gallery.GetGalleryStillAlbums()
    if not albums or album_index < 0 or album_index >= len(albums):
        return {"error": f"No album at index {album_index}"}
    stills = albums[album_index].GetStills()
    if not stills:
        return {"error": "No stills in album"}
    # A negative index is a real Python index (`stills[-1]` is the last still),
    # and an out-of-range one used to be dropped while the rest were deleted.
    # Refuse the whole call instead of deleting a set nobody asked for.
    invalid = _invalid_indices(still_indices, len(stills))
    if invalid:
        return {"error": f"still_indices out of range for {len(stills)} stills: {invalid}"}
    to_delete = [stills[i] for i in still_indices]
    result = albums[album_index].DeleteStills(to_delete)
    return {"success": bool(result)}
