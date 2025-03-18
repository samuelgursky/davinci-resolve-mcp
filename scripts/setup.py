#!/usr/bin/env python
"""
Setup script for DaVinci Resolve MCP Server.

This script helps configure the environment for the MCP server.
"""
import os
import sys
import platform
import shutil
from pathlib import Path
import argparse
import re
import subprocess
import tempfile

def get_script_directory():
    """Get the directory of this script."""
    return Path(__file__).parent

def get_project_root():
    """Get the project root directory."""
    return get_script_directory().parent

def detect_resolve_paths():
    """Detect DaVinci Resolve API paths based on the operating system."""
    system = platform.system()
    api_path = None
    lib_path = None
    
    if system == "Darwin":  # macOS
        api_path = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/"
        lib_path = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
        
    elif system == "Windows":
        programdata = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
        program_files = os.environ.get("PROGRAMFILES", "C:\\Program Files")
        
        api_path = os.path.join(programdata, "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting")
        lib_path = os.path.join(program_files, "Blackmagic Design", "DaVinci Resolve", "fusionscript.dll")
        
    elif system == "Linux":
        api_path = "/opt/resolve/Developer/Scripting/"
        lib_path = "/opt/resolve/libs/Fusion/fusionscript.so"
        
        # Check for standard ISO Linux installation
        if not Path(api_path).exists():
            api_path = "/home/resolve/Developer/Scripting/"
            lib_path = "/home/resolve/libs/Fusion/fusionscript.so"
    
    return api_path, lib_path

def check_resolve_installation():
    """Check if DaVinci Resolve is installed and API is available."""
    api_path, lib_path = detect_resolve_paths()
    
    api_exists = Path(api_path).exists() if api_path else False
    lib_exists = Path(lib_path).exists() if lib_path else False
    
    return {
        "api_path": api_path,
        "lib_path": lib_path,
        "api_exists": api_exists,
        "lib_exists": lib_exists,
        "fully_available": api_exists and lib_exists
    }

def create_env_file(api_path, lib_path, host="127.0.0.1", port=8765, api_key=None):
    """Create a .env file with the necessary configuration."""
    env_template = """# DaVinci Resolve API Environment Variables
RESOLVE_SCRIPT_API="{api_path}"
RESOLVE_SCRIPT_LIB="{lib_path}"
PYTHONPATH="$PYTHONPATH:{api_path}/Modules/"

# MCP Server Configuration
MCP_SERVER_HOST={host}
MCP_SERVER_PORT={port}
MCP_SERVER_NAME=DaVinci Resolve MCP
MCP_SERVER_VERSION=0.1.0
MCP_SERVER_DEBUG=true

# Security
MCP_API_KEY={api_key}
MCP_ALLOWED_ORIGINS=http://localhost:3000,https://claude.ai
"""
    
    # Handle Windows path specifics
    if platform.system() == "Windows":
        api_path = api_path.replace("\\", "\\\\")
        lib_path = lib_path.replace("\\", "\\\\")
        pythonpath = f"%PYTHONPATH%;{api_path}\\\\Modules\\\\"
    else:
        pythonpath = f"$PYTHONPATH:{api_path}/Modules/"
    
    env_content = env_template.format(
        api_path=api_path,
        lib_path=lib_path,
        pythonpath=pythonpath,
        host=host,
        port=port,
        api_key=f'"{api_key}"' if api_key else "None"
    )
    
    env_file_path = get_project_root() / ".env"
    
    with open(env_file_path, "w") as f:
        f.write(env_content)
    
    print(f"Created .env file at {env_file_path}")
    return env_file_path

def install_dependencies():
    """Install required Python dependencies."""
    requirements_path = get_project_root() / "requirements.txt"
    
    if not requirements_path.exists():
        print("Error: requirements.txt not found.")
        return False
    
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(requirements_path)])
        print("Installed dependencies from requirements.txt")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error installing dependencies: {e}")
        return False

def check_python_version():
    """Check if the Python version is compatible."""
    major, minor = sys.version_info[:2]
    
    if major < 3 or (major == 3 and minor < 6):
        print(f"Warning: Python {major}.{minor} detected. This project requires Python 3.6+")
        return False
    
    print(f"Python {major}.{minor} detected (compatible)")
    return True

def generate_api_key():
    """Generate a random API key."""
    import uuid
    return str(uuid.uuid4())

def main():
    """Main function to set up the MCP server."""
    parser = argparse.ArgumentParser(description="Setup DaVinci Resolve MCP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the MCP server to")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind the MCP server to")
    parser.add_argument("--api-key", help="Custom API key (generated if not provided)")
    parser.add_argument("--skip-deps", action="store_true", help="Skip installing dependencies")
    parser.add_argument("--resolve-api-path", help="Custom path to DaVinci Resolve API")
    parser.add_argument("--resolve-lib-path", help="Custom path to DaVinci Resolve library")
    
    args = parser.parse_args()
    
    print("Setting up DaVinci Resolve MCP Server...")
    
    # Check Python version
    if not check_python_version():
        print("Warning: Continuing with incompatible Python version. This may cause issues.")
    
    # Install dependencies if not skipped
    if not args.skip_deps:
        if not install_dependencies():
            print("Warning: Failed to install dependencies. You may need to install them manually.")
    else:
        print("Skipping dependency installation.")
    
    # Check for DaVinci Resolve installation
    resolve_status = check_resolve_installation()
    
    api_path = args.resolve_api_path or resolve_status["api_path"]
    lib_path = args.resolve_lib_path or resolve_status["lib_path"]
    
    if not api_path or not lib_path:
        print("Error: Could not determine DaVinci Resolve API paths.")
        print("Please provide them manually using --resolve-api-path and --resolve-lib-path.")
        return 1
    
    if not resolve_status["fully_available"]:
        if not resolve_status["api_exists"]:
            print(f"Warning: DaVinci Resolve API directory not found at {api_path}")
        if not resolve_status["lib_exists"]:
            print(f"Warning: DaVinci Resolve library not found at {lib_path}")
        print("You may need to install DaVinci Resolve or provide correct paths.")
    else:
        print(f"Found DaVinci Resolve API at {api_path}")
        print(f"Found DaVinci Resolve library at {lib_path}")
    
    # Generate or use provided API key
    api_key = args.api_key or generate_api_key()
    
    # Create .env file
    env_path = create_env_file(api_path, lib_path, args.host, args.port, api_key)
    
    print("\nSetup complete!")
    print(f"API Key: {api_key}")
    print(f"Server will run on: {args.host}:{args.port}")
    print("\nTo start the server, run:")
    print("python scripts/run_server.py")
    
    return 0

if __name__ == "__main__":
    sys.exit(main()) 