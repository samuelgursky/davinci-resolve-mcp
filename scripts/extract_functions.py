#!/usr/bin/env python3
"""
Script to extract MCP function names and status from source code and update
the master documentation accordingly.
"""

import re
import sys
import json
import os

def extract_mcp_functions(source_file, target_file, function_pattern, status_pattern):
    """
    Extract MCP functions and their status from the source file and update
    the target file's function status.
    
    Args:
        source_file (str): Path to the source code file
        target_file (str): Path to the master documentation file
        function_pattern (str): Regex pattern to match function definitions
        status_pattern (str): Regex pattern to match status comments
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Check if files exist
        if not os.path.exists(source_file):
            print(f"Source file not found: {source_file}")
            return False
            
        if not os.path.exists(target_file):
            print(f"Target file not found: {target_file}")
            return False
        
        # Read the source file
        with open(source_file, 'r') as f:
            source_content = f.read()
        
        # Read the target documentation file
        with open(target_file, 'r') as f:
            doc_content = f.read()
        
        # Find all function definitions with their associated status comments
        function_matches = re.finditer(function_pattern, source_content)
        
        # Process each function found
        functions_updated = 0
        for match in function_matches:
            # Get the function name
            function_name = f"mcp_{match.group(1)}"
            
            # Look for status comment before the function definition
            start_pos = max(0, match.start() - 200)  # Look at most 200 chars before the function
            context = source_content[start_pos:match.start()]
            status_match = re.search(status_pattern, context)
            
            if status_match:
                status = status_match.group(1).strip()
                
                # Update the status in the documentation file
                # We need to find the function in a table row format
                function_pattern_in_doc = r'\| ' + re.escape(function_name) + r' \| ([✅⚠️❌🔄📝🧪][^\|]*) \|'
                replacement = f'| {function_name} | {status} |'
                
                # Use re.sub with a lambda to only replace the status column
                def replace_status(m):
                    parts = m.group(0).split('|')
                    if len(parts) >= 3:  # Ensure we have enough columns
                        parts[2] = f" {status} "
                        return '|'.join(parts)
                    return m.group(0)
                
                doc_content = re.sub(function_pattern_in_doc, replace_status, doc_content)
                functions_updated += 1
        
        # Write the updated documentation back to the file
        with open(target_file, 'w') as f:
            f.write(doc_content)
            
        print(f"Updated status for {functions_updated} functions in {target_file}")
        return True
        
    except Exception as e:
        print(f"Error extracting functions: {str(e)}")
        return False

if __name__ == "__main__":
    try:
        # Parse arguments from stdin (Cursor passes arguments as JSON)
        args = json.loads(sys.stdin.read())
        
        # Extract the arguments
        source_file = args.get('sourceFile')
        target_file = args.get('targetFile')
        function_pattern = args.get('functionPattern')
        status_pattern = args.get('statusPattern')
        
        # Validate arguments
        if not all([source_file, target_file, function_pattern, status_pattern]):
            print("Error: Missing required arguments")
            sys.exit(1)
            
        # Extract functions and update documentation
        if extract_mcp_functions(source_file, target_file, function_pattern, status_pattern):
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1) 