#!/usr/bin/env python
"""
Launcher script for the DaVinci Resolve MCP Server.

This script provides a convenient way to start the MCP server.
"""
import os
import sys
import subprocess
from pathlib import Path
import argparse
import platform
from dotenv import load_dotenv

def get_script_directory():
    """Get the directory of this script."""
    return Path(__file__).parent

def get_project_root():
    """Get the project root directory."""
    return get_script_directory().parent

def set_resolve_env():
    """Set up environment variables for DaVinci Resolve API."""
    env_path = get_project_root() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    
    # Check if variables are set
    if "RESOLVE_SCRIPT_API" not in os.environ or "RESOLVE_SCRIPT_LIB" not in os.environ:
        print("Error: DaVinci Resolve environment variables not set.")
        print("Please run the setup script first: python scripts/setup.py")
        return False
    
    # Add Python modules path
    if platform.system() == "Windows":
        modules_path = os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules")
    else:
        modules_path = os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules")
    
    if os.path.exists(modules_path) and modules_path not in sys.path:
        sys.path.append(modules_path)
    
    return True

def run_server(host=None, port=None, debug=None):
    """Run the MCP server."""
    server_script = get_project_root() / "src" / "mcp_server" / "server.py"
    
    if not server_script.exists():
        print(f"Error: Server script not found at {server_script}")
        return 1
    
    # Override settings from arguments
    env = os.environ.copy()
    if host:
        env["MCP_SERVER_HOST"] = host
    if port:
        env["MCP_SERVER_PORT"] = str(port)
    if debug is not None:
        env["MCP_SERVER_DEBUG"] = "true" if debug else "false"
    
    try:
        process = subprocess.Popen(
            [sys.executable, str(server_script)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        print(f"Starting MCP Server (PID: {process.pid})...")
        print("Press Ctrl+C to stop")
        
        # Forward output
        for line in process.stdout:
            print(line, end="")
        
        return process.wait()
        
    except KeyboardInterrupt:
        print("\nStopping MCP Server...")
        process.terminate()
        return 0
    except Exception as e:
        print(f"Error running server: {e}")
        return 1

def main():
    """Main function to run the server."""
    parser = argparse.ArgumentParser(description="Run DaVinci Resolve MCP Server")
    parser.add_argument("--host", help="Host to bind the MCP server to (overrides .env)")
    parser.add_argument("--port", type=int, help="Port to bind the MCP server to (overrides .env)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode (overrides .env)")
    parser.add_argument("--no-debug", action="store_true", help="Disable debug mode (overrides .env)")
    
    args = parser.parse_args()
    
    # Set up environment
    if not set_resolve_env():
        return 1
    
    # Determine debug mode
    debug = None
    if args.debug:
        debug = True
    elif args.no_debug:
        debug = False
    
    # Run the server
    return run_server(args.host, args.port, debug)

if __name__ == "__main__":
    sys.exit(main()) 