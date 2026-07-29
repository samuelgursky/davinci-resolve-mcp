#!/usr/bin/env python3
"""
Platform-specific functionality for DaVinci Resolve MCP Server
"""

import os
import sys
import platform

def get_platform():
    """Identify the current operating system platform.
    
    Returns:
        str: 'windows', 'darwin' (macOS), or 'linux'
    """
    system = platform.system().lower()
    if system == 'darwin':
        return 'darwin'
    elif system == 'windows':
        return 'windows'
    elif system == 'linux':
        return 'linux'
    return system

def get_resolve_paths():
    """Get platform-specific paths for DaVinci Resolve scripting API.
    
    Returns:
        dict: Dictionary containing api_path, lib_path, and modules_path
    """
    platform_name = get_platform()
    
    if platform_name == 'darwin':  # macOS
        api_path = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        lib_path = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
        modules_path = os.path.join(api_path, "Modules")
    
    elif platform_name == 'windows':  # Windows
        program_files = os.environ.get('PROGRAMDATA', 'C:\\ProgramData')
        program_files_64 = os.environ.get('PROGRAMFILES', 'C:\\Program Files')
        
        api_path = os.path.join(program_files, 'Blackmagic Design', 'DaVinci Resolve', 'Support', 'Developer', 'Scripting')
        lib_path = os.path.join(program_files_64, 'Blackmagic Design', 'DaVinci Resolve', 'fusionscript.dll')
        modules_path = os.path.join(api_path, "Modules")
    
    elif platform_name == 'linux':  # Linux (not fully implemented)
        # Default locations for Linux - these may need to be adjusted
        api_path = "/opt/resolve/Developer/Scripting"
        lib_path = "/opt/resolve/libs/fusionscript.so"
        modules_path = os.path.join(api_path, "Modules")
    
    else:
        # Fallback to macOS paths if unknown platform
        api_path = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        lib_path = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
        modules_path = os.path.join(api_path, "Modules")
    
    # An explicit install location wins over the platform default: Resolve is
    # not always under /Applications (external volume, custom install dir).
    env_api = os.environ.get("RESOLVE_SCRIPT_API")
    if env_api and os.path.isdir(env_api):
        api_path = env_api
        modules_path = os.path.join(api_path, "Modules")
    env_lib = os.environ.get("RESOLVE_SCRIPT_LIB")
    if env_lib and os.path.isfile(env_lib):
        lib_path = env_lib

    return {
        "api_path": api_path,
        "lib_path": lib_path,
        "modules_path": modules_path
    }

def get_resolve_plugin_paths():
    """Get platform-specific paths for Resolve plugin install dirs.

    Returns:
        dict: {
            'fuses_dir':  Fusion Fuses directory,
            'dctl_dir':   LUT directory (where regular .dctl files live),
            'aces_idt_dir': ACES IDT transforms (separate scan path; restart
                            required after install),
            'aces_odt_dir': ACES ODT transforms (same caveat),
        }
    """
    platform_name = get_platform()
    home = os.path.expanduser("~")

    # NOTE: The Fuse SDK doc (June 2023) lists Fuses under "Support/Fusion/Fuses"
    # on macOS, but the directory Resolve actually scans is the sibling
    # "Fusion/Fuses" (without "Support") — verified live against Resolve Studio
    # 20.3.2.9 by writing test fuses to both paths and observing which loaded.
    # Per-platform conventions also differ from the SDK doc; we follow the
    # canonical Fusion user-data layout where every Fusion user directory
    # (Macros, Templates, Scripts, Modules, Fuses, ...) lives directly under
    # the platform's Fusion user root.
    if platform_name == 'darwin':
        support = os.path.join(home, "Library", "Application Support",
                               "Blackmagic Design", "DaVinci Resolve")
        fuses_dir = os.path.join(support, "Fusion", "Fuses")
        dctl_dir = os.path.join(support, "LUT")
        aces_root = os.path.join(support, "ACES Transforms")
    elif platform_name == 'windows':
        appdata = os.environ.get('APPDATA', os.path.join(home, 'AppData', 'Roaming'))
        fuses_dir = os.path.join(appdata, 'Blackmagic Design', 'DaVinci Resolve',
                                 'Support', 'Fusion', 'Fuses')
        dctl_dir = os.path.join(appdata, 'Blackmagic Design', 'DaVinci Resolve',
                                'Support', 'LUT')
        aces_root = os.path.join(appdata, 'Blackmagic Design', 'DaVinci Resolve',
                                 'Support', 'ACES Transforms')
    elif platform_name == 'linux':
        base = os.path.join(home, '.local', 'share', 'DaVinciResolve')
        fuses_dir = os.path.join(base, 'Fusion', 'Fuses')
        dctl_dir = os.path.join(base, 'LUT')
        aces_root = os.path.join(base, 'ACES Transforms')
    else:
        support = os.path.join(home, "Library", "Application Support",
                               "Blackmagic Design", "DaVinci Resolve")
        fuses_dir = os.path.join(support, "Fusion", "Fuses")
        dctl_dir = os.path.join(support, "LUT")
        aces_root = os.path.join(support, "ACES Transforms")

    # Resolve scans these subdirs of Fusion/Scripts/ at startup and exposes
    # them in Workspace → Scripts → <category>. Categories per Resolve docs.
    if platform_name == 'darwin':
        scripts_root = os.path.join(support, "Fusion", "Scripts")
    elif platform_name == 'windows':
        scripts_root = os.path.join(appdata, 'Blackmagic Design', 'DaVinci Resolve',
                                    'Support', 'Fusion', 'Scripts')
    elif platform_name == 'linux':
        scripts_root = os.path.join(base, 'Fusion', 'Scripts')
    else:
        scripts_root = os.path.join(support, "Fusion", "Scripts")

    return {
        "fuses_dir": fuses_dir,
        "dctl_dir": dctl_dir,
        "aces_idt_dir": os.path.join(aces_root, "IDT"),
        "aces_odt_dir": os.path.join(aces_root, "ODT"),
        "scripts_root": scripts_root,
        # Category subdirs Resolve actually scans (verified live):
        "scripts_categories": ("Edit", "Color", "Deliver", "Comp",
                               "Tool", "Utility", "Views"),
    }


def setup_environment():
    """Set up environment variables for DaVinci Resolve scripting.
    
    Returns:
        bool: True if setup was successful, False otherwise
    """
    try:
        paths = get_resolve_paths()
        
        os.environ["RESOLVE_SCRIPT_API"] = paths["api_path"]
        os.environ["RESOLVE_SCRIPT_LIB"] = paths["lib_path"]
        
        # Add modules path to Python's path if it's not already there
        if paths["modules_path"] not in sys.path:
            sys.path.append(paths["modules_path"])
        
        return True
    
    except Exception as e:
        print(f"Error setting up environment: {str(e)}")
        return False 