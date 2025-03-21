import os
from ..resolve_init import get_resolve

def export_timeline_xml(output_path=None, format_type="xml"):
    """
    Export the current timeline as XML/EDL/AAF
    
    Args:
        output_path: Path where the XML file should be saved
        format_type: Export format - "xml", "edl", or "aaf"
    
    Returns:
        Status of export operation including the path to the exported file
    """
    resolve = get_resolve()
    if not resolve:
        return {"error": "Could not connect to DaVinci Resolve"}
    
    pm = resolve.GetProjectManager()
    if not pm:
        return {"error": "Could not get Project Manager"}
    
    project = pm.GetCurrentProject()
    if not project:
        return {"error": "No project is open"}
    
    timeline = project.GetCurrentTimeline()
    if not timeline:
        return {"error": "No timeline is open"}
    
    timeline_name = timeline.GetName()
    
    # If no output path provided, create a default one in user's home directory
    if not output_path:
        home_dir = os.path.expanduser("~")
        export_dir = os.path.join(home_dir, "davinci-resolve-mcp", "exports")
        os.makedirs(export_dir, exist_ok=True)
        
        extension = format_type.lower()
        output_path = os.path.join(export_dir, f"{timeline_name}.{extension}")
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    
    # Export the timeline
    format_map = {
        "xml": {"formatType": "xml", "method": timeline.Export},
        "edl": {"formatType": "edl", "method": timeline.Export},
        "aaf": {"formatType": "aaf", "method": timeline.Export},
        "fcpxml": {"formatType": "fcpxml", "method": timeline.Export}
    }
    
    if format_type.lower() not in format_map:
        return {"error": f"Unsupported format: {format_type}. Use 'xml', 'edl', 'aaf', or 'fcpxml'"}
    
    format_info = format_map[format_type.lower()]
    success = format_info["method"](output_path, format_info["formatType"])
    
    if success:
        return {
            "status": "success",
            "timeline": timeline_name,
            "output_path": output_path,
            "format": format_type
        }
    else:
        return {
            "error": f"Failed to export timeline as {format_type}",
            "timeline": timeline_name
        }

def mcp_export_timeline_xml(output_path=None, format_type="xml"):
    """
    MCP function to export the current timeline as XML/EDL/AAF
    
    Args:
        output_path: Path where the XML file should be saved
        format_type: Export format - "xml", "edl", "aaf" or "fcpxml"
        
    Returns:
        Status of export operation
    """
    return export_timeline_xml(output_path, format_type) 