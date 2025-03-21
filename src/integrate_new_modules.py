#!/usr/bin/env python
"""
DaVinci Resolve MCP New Modules Integration

This script integrates the new module functions into the resolve_mcp.py file.
It adds the new project settings, timeline, media pool, and render modules.
"""

import os
import sys
import shutil
import importlib.util
from datetime import datetime

# Get the root directory
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Define file paths
resolve_mcp_path = os.path.join(root_dir, "src", "resolve_mcp.py")
project_settings_path = os.path.join(root_dir, "davinci_resolve_project_settings.py")
timeline_path = os.path.join(root_dir, "davinci_resolve_timeline.py")
media_pool_path = os.path.join(root_dir, "davinci_resolve_media_pool.py")
render_path = os.path.join(root_dir, "davinci_resolve_render.py")
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

def get_function_details_from_module(module_path, exclude_functions=None):
    """Extract all functions and their details from a module file"""
    if exclude_functions is None:
        exclude_functions = []
    
    # Load the module dynamically
    module_name = os.path.basename(module_path).replace('.py', '')
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    functions = []
    
    # Get all functions starting with mcp_
    for name in dir(module):
        if name.startswith('mcp_') and name not in exclude_functions:
            func = getattr(module, name)
            if callable(func):
                # Get function signature using inspect
                import inspect
                signature = inspect.signature(func)
                docstring = inspect.getdoc(func) or ""
                
                # Extract description from docstring (first line)
                description = docstring.split('\n')[0].strip()
                
                # Get parameters
                parameters = {}
                for param_name, param in signature.parameters.items():
                    if param_name != 'self':
                        param_info = {
                            "name": param_name,
                            "type": str(param.annotation).replace("<class '", "").replace("'>", ""),
                            "default": None if param.default is inspect.Parameter.empty else param.default
                        }
                        parameters[param_name] = param_info
                
                functions.append({
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                    "source": inspect.getsource(func)
                })
    
    return functions

def add_functions_to_mcp(output_file, functions):
    """Append the functions to the MCP file with proper decorators"""
    with open(output_file, 'a') as f:
        f.write("\n# Added from new modules\n")
        
        for func in functions:
            # Write the decorators and function
            f.write(f"@mcp.tool()\n@safe_api_call\n{func['source']}\n\n")
    
    print(f"Added {len(functions)} functions to {output_file}")

def integrate_modules():
    """Integrate all new module functions into the MCP file"""
    # First, create a backup
    backup_file(resolve_mcp_path)
    
    # Get all existing functions in the MCP file
    existing_functions = []
    with open(resolve_mcp_path, 'r') as f:
        content = f.read()
        
        # Find all function definitions
        import re
        function_defs = re.findall(r'def (mcp_[a-zA-Z0-9_]+)', content)
        existing_functions.extend(function_defs)
    
    print(f"Found {len(existing_functions)} existing functions")
    
    # Get all functions from new modules
    module_paths = [
        project_settings_path,
        timeline_path,
        media_pool_path,
        render_path
    ]
    
    all_new_functions = []
    
    for module_path in module_paths:
        if os.path.exists(module_path):
            module_name = os.path.basename(module_path).replace('.py', '')
            print(f"Processing {module_name} module...")
            
            try:
                functions = get_function_details_from_module(module_path, existing_functions)
                all_new_functions.extend(functions)
                print(f"Found {len(functions)} new functions in {module_name}")
            except Exception as e:
                print(f"Error processing {module_name}: {e}")
        else:
            print(f"Warning: {module_path} does not exist")
    
    # Add the new functions to the MCP file
    if all_new_functions:
        add_functions_to_mcp(resolve_mcp_path, all_new_functions)
    else:
        print("No new functions to add")

def update_imports(file_path):
    """Update the imports in the file"""
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Check if we need to add imports
    if 'from typing import List, Dict, Any, Union, Optional' in content:
        # Replace with expanded imports
        new_imports = 'from typing import List, Dict, Any, Union, Optional, Tuple'
        content = content.replace('from typing import List, Dict, Any, Union, Optional', new_imports)
    else:
        # Add the import at the top
        new_imports = 'from typing import List, Dict, Any, Union, Optional, Tuple\n'
        content = new_imports + content
    
    with open(file_path, 'w') as f:
        f.write(content)
    
    print(f"Updated imports in {file_path}")

if __name__ == "__main__":
    print("Integrating new module functions into resolve_mcp.py...")
    
    if not os.path.exists(resolve_mcp_path):
        print(f"Error: {resolve_mcp_path} does not exist")
        sys.exit(1)
    
    # Update imports
    update_imports(resolve_mcp_path)
    
    # Integrate modules
    integrate_modules()
    
    print("Integration complete!") 