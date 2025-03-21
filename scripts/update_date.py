#!/usr/bin/env python3
"""
Script to update the last updated date in the master documentation file.
This is used by the .cursorrules to automatically keep the documentation date current.
"""

import re
import sys
import json
from datetime import datetime

def update_last_updated_date(file_path, pattern, replacement):
    """
    Update the last updated date in a file by replacing the specified pattern
    with the replacement text. The replacement can include {{dateFormat}} which
    will be replaced with the current date.
    
    Args:
        file_path (str): Path to the file to update
        pattern (str): Regular expression pattern to find the date
        replacement (str): Replacement text, can include {{dateFormat "FORMAT"}}
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Read the file content
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Process the dateFormat template if present
        if '{{dateFormat' in replacement:
            date_format_pattern = r'{{dateFormat\s+"([^"]+)"}}'
            date_format_match = re.search(date_format_pattern, replacement)
            if date_format_match:
                date_format = date_format_match.group(1)
                current_date = datetime.now().strftime(date_format)
                replacement = re.sub(date_format_pattern, current_date, replacement)
        
        # Replace the pattern with the replacement
        updated_content = re.sub(pattern, replacement, content)
        
        # Write the updated content back to the file
        with open(file_path, 'w') as f:
            f.write(updated_content)
            
        print(f"Updated last updated date in {file_path}")
        return True
        
    except Exception as e:
        print(f"Error updating last updated date: {str(e)}")
        return False

if __name__ == "__main__":
    try:
        # Parse arguments from stdin (Cursor passes arguments as JSON)
        args = json.loads(sys.stdin.read())
        
        # Extract the arguments
        file_path = args.get('file')
        pattern = args.get('pattern')
        replacement = args.get('replacement')
        
        # Validate arguments
        if not all([file_path, pattern, replacement]):
            print("Error: Missing required arguments (file, pattern, replacement)")
            sys.exit(1)
            
        # Update the date
        if update_last_updated_date(file_path, pattern, replacement):
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1) 