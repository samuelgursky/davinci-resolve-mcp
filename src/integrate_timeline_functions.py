#!/usr/bin/env python
"""
DaVinci Resolve MCP Fixed Timeline Functions Integration

This script integrates the fixed timeline functions into the resolve_mcp.py file.
It replaces the non-working timeline functions with the fixed implementations.
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
fixed_timeline_functions_path = os.path.join(root_dir, "src", "fixed_timeline_functions.py")
davinci_resolve_timeline_path = os.path.join(root_dir, "src", "davinci_resolve_timeline.py")
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

def update_import_section(filename, import_statement):
    """Add an import statement to the file if it doesn't already exist"""
    with open(filename, 'r') as f:
        content = f.read()
    
    # Check if the import already exists
    if import_statement in content:
        print(f"Import already exists: {import_statement}")
        return False
    
    # Find the last import statement
    import_pattern = r"(import .*|from .* import .*)\n"
    matches = list(re.finditer(import_pattern, content))
    
    if matches:
        # Get the last import statement
        last_import = matches[-1]
        last_import_end = last_import.end()
        
        # Insert our import after the last one
        new_content = content[:last_import_end] + import_statement + "\n" + content[last_import_end:]
        
        with open(filename, 'w') as f:
            f.write(new_content)
        
        print(f"Added import: {import_statement}")
        return True
    else:
        print("No import statements found in the file")
        return False

def replace_function_in_file(filename, function_name, new_function_content):
    """Replace a function in a file with new content"""
    with open(filename, 'r') as f:
        content = f.read()
    
    # Create a pattern to find the function and its body
    pattern = rf"def {function_name}\s*\([^)]*\).*?(?=\n\s*def|\Z)"
    
    # Find if the function exists
    match = re.search(pattern, content, re.DOTALL)
    if match:
        # Replace the function
        new_content = content.replace(match.group(0), new_function_content)
        with open(filename, 'w') as f:
            f.write(new_content)
        print(f"Successfully replaced function {function_name}")
        return True
    else:
        print(f"Function pattern not found for {function_name}")
        return False

def integrate_fixed_timeline_functions():
    """Integrate the fixed timeline functions into the davinci_resolve_timeline.py file"""
    # First, create a backup
    backup_file(davinci_resolve_timeline_path)
    
    # Functions to fix
    functions_to_fix = {
        "fixed_delete_timeline": "mcp_delete_timeline",
        "fixed_duplicate_timeline": "mcp_duplicate_timeline"
    }
    
    # First, update the import section to import the fixed functions
    update_import_section(davinci_resolve_timeline_path, 
                          "# Helper functions from fixed_timeline_functions\nfrom .fixed_timeline_functions import find_timeline_by_name, list_all_timelines")
    
    # Update each function
    for fixed_function, target_function in functions_to_fix.items():
        # Get the fixed function content
        fixed_function_content = get_function_content(fixed_timeline_functions_path, fixed_function)
        
        if fixed_function_content:
            # Rename the function to match the target function name
            fixed_function_content = fixed_function_content.replace(
                f"def {fixed_function}", f"def {target_function}")
            
            # Replace the function in the file
            success = replace_function_in_file(davinci_resolve_timeline_path, target_function, fixed_function_content)
            
            if not success:
                print(f"Failed to replace function {target_function}")
        else:
            print(f"Could not find function {fixed_function} in {fixed_timeline_functions_path}")

def main():
    """Main function to integrate the fixed timeline functions"""
    print("Integrating fixed timeline functions...")
    
    if not os.path.exists(davinci_resolve_timeline_path):
        print(f"Error: {davinci_resolve_timeline_path} does not exist")
        sys.exit(1)
    
    if not os.path.exists(fixed_timeline_functions_path):
        print(f"Error: {fixed_timeline_functions_path} does not exist")
        sys.exit(1)
    
    # Add the helper functions from fixed_timeline_functions.py to davinci_resolve_timeline.py
    # and replace the existing functions with the fixed versions
    integrate_fixed_timeline_functions()
    
    print("Integration complete!")
    print("To test the changes, run tests/test_fixed_timeline_functions.py")

if __name__ == "__main__":
    main() 