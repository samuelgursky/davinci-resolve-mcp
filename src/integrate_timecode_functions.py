"""
DaVinci Resolve MCP - Timecode Functions Integration

This module integrates the source timecode functions with the main MCP module.
"""

import os
import sys
from typing import Dict, Any, List

# Import source timecode functions
try:
    from .timecode_functions.source_timecode import (
        mcp_get_clip_source_timecode,
        mcp_get_source_timecode_report,
        mcp_export_source_timecode_report,
    )
except ImportError:
    # Fallback for direct script execution
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.timecode_functions.source_timecode import (
        mcp_get_clip_source_timecode,
        mcp_get_source_timecode_report,
        mcp_export_source_timecode_report,
    )


def register_timecode_functions(mcp):
    """
    Register timecode functions with the MCP server.
    
    Args:
        mcp: MCP server instance
    """
    @mcp.tool()
    def get_clip_source_timecode(
        track_type: str = "video", track_index: int = 1, clip_index: int = 0
    ) -> Dict[str, Any]:
        """
        Get detailed source timecode information about a specific clip in the timeline.

        Args:
            track_type: The type of track ('video' or 'audio')
            track_index: The index of the track (1-based)
            clip_index: The index of the clip in the track (0-based)

        Returns:
            A dictionary with clip source timecode details or an error message
        """
        return mcp_get_clip_source_timecode(track_type, track_index, clip_index)

    @mcp.tool()
    def get_source_timecode_report() -> Dict[str, Any]:
        """
        Generate a comprehensive report of all clips in the timeline with their source timecode information.
        
        Returns:
            A dictionary with the timeline name and a list of clips with source timecodes
        """
        return mcp_get_source_timecode_report()

    @mcp.tool()
    def export_source_timecode_report(
        export_path: str,
        format: str = "csv",  # Options: csv, json, edl
        video_tracks_only: bool = False
    ) -> Dict[str, Any]:
        """
        Export a report of all timeline clips with their source timecodes.
        
        Args:
            export_path: Path where the report should be saved
            format: Report format (csv, json, or edl)
            video_tracks_only: If True, only include video tracks in the report
        
        Returns:
            Status of the export operation
        """
        return mcp_export_source_timecode_report(export_path, format, video_tracks_only)


# If this script is run directly, print a message
if __name__ == "__main__":
    print("This module is intended to be imported, not run directly.")
    print("To use these functions, import them through the main MCP module.") 