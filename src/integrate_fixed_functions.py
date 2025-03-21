#!/usr/bin/env python
"""
DaVinci Resolve MCP Fixed Functions Integration

This script integrates the fixed functions into the resolve_mcp.py file.
It replaces the non-working functions with the fixed implementations.
"""

import os
import sys
import re
import shutil
from datetime import datetime

# Get the root directory
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Define file paths
resolve_mcp_path = os.path.join(root_dir, "src", "resolve_mcp.py")
fix_functions_path = os.path.join(root_dir, "fix_davinci_resolve_functions.py")
backup_dir = os.path.join(root_dir, "backups")

# Create backup directory if it doesn't exist
if not os.path.exists(backup_dir):
    os.makedirs(backup_dir)

def backup_file(file_path):
    """Create a backup of the file before modifying it"""
    filename = os.path.basename(file_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"{filename}.{timestamp}.bak")
    
    shutil.copy2(file_path, backup_path)
    print(f"Created backup at {backup_path}")
    return backup_path

def get_function_content(filename, function_name):
    """Extract the content of a function from a file"""
    with open(filename, 'r') as f:
        content = f.read()
        
    # Create a pattern to find the function and its body
    pattern = rf"def {function_name}\s*\([^)]*\).*?(?=\n\s*def|\Z)"
    
    match = re.search(pattern, content, re.DOTALL)
    if match:
        return match.group(0)
    return None

def replace_function_in_file(filename, old_function_name, new_function_content):
    """Replace a function in a file with new content"""
    with open(filename, 'r') as f:
        content = f.read()
    
    # Create a pattern to find the old function with its decorators and body
    pattern = rf"@mcp\.tool\(\)\s*@safe_api_call\s*def {old_function_name}\s*\([^)]*\).*?(?=@mcp\.tool\(\)|\Z)"
    
    # Prepare the new function with MCP decorator
    new_function = f"@mcp.tool()\n@safe_api_call\n{new_function_content}\n\n"
    
    # Find if the function exists
    match = re.search(pattern, content, re.DOTALL)
    if match:
        # Replace the function
        new_content = content.replace(match.group(0), new_function)
        with open(filename, 'w') as f:
            f.write(new_content)
        return True
    else:
        print(f"Function pattern not found for {old_function_name}")
        return False

def integrate_functions():
    """Integrate the fixed functions into the resolve_mcp.py file"""
    # First, create a backup
    backup_file(resolve_mcp_path)
    
    # Functions to fix
    functions_to_fix = [
        "mcp_control_playback",
        "mcp_get_selected_clips",
        "mcp_get_media_pool_items",
        "mcp_get_media_pool_structure"
    ]
    
    for function_name in functions_to_fix:
        # Get the new function content
        new_function = get_function_content(fix_functions_path, function_name)
        
        if new_function:
            # Convert function names in resolve_mcp.py (they don't have mcp_ prefix there)
            old_function_name = function_name.replace("mcp_", "")
            
            # Replace the function in the file
            success = replace_function_in_file(resolve_mcp_path, old_function_name, new_function)
            
            if success:
                print(f"Successfully replaced function {old_function_name} with {function_name}")
            else:
                print(f"Failed to replace function {old_function_name}")
        else:
            print(f"Could not find function {function_name} in {fix_functions_path}")

if __name__ == "__main__":
    print("Integrating fixed functions into resolve_mcp.py...")
    
    if not os.path.exists(resolve_mcp_path):
        print(f"Error: {resolve_mcp_path} does not exist")
        sys.exit(1)
    
    if not os.path.exists(fix_functions_path):
        print(f"Error: {fix_functions_path} does not exist")
        sys.exit(1)
    
    integrate_functions()
    print("Integration complete!") 