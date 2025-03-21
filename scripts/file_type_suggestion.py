#!/usr/bin/env python3
"""
file_type_suggestion.py

A utility script for .cursorrules to suggest appropriate directories for new files
based on their type and purpose. This script shows a notification with guidance
when a file is created in the root directory.
"""

import sys
import os
import json

def main():
    # Get arguments from stdin (sent by the cursorrules engine)
    args_str = sys.stdin.read()
    try:
        args = json.loads(args_str)
    except json.JSONDecodeError:
        print("Error: Could not parse arguments")
        sys.exit(1)
    
    # Extract the relevant arguments
    message = args.get("message", "")
    file_path = args.get("file", "")
    
    # If any of the required arguments are missing, exit with an error
    if not all([message, file_path]):
        print("Error: Missing required arguments")
        sys.exit(1)
    
    # Get the file extension and name
    file_ext = os.path.splitext(file_path)[1].lower()
    file_name = os.path.basename(file_path)
    
    # Determine the best target directory based on the file
    target_dir = ""
    if file_ext == ".py":
        if file_name.startswith("test_"):
            target_dir = "tests/"
        elif "example" in file_name.lower() or file_name.startswith("create_") or file_name.startswith("add_"):
            target_dir = "examples/"
        else:
            target_dir = "src/"
    elif file_ext == ".md":
        target_dir = "docs/"
    
    # Build actions list for the notification
    actions = []
    if target_dir:
        actions.append({
            "label": f"Move to {target_dir}",
            "command": "cursor.moveFile",
            "args": {
                "source": file_path,
                "target": os.path.join(target_dir, os.path.basename(file_path))
            }
        })
    
    # Build the notification response
    response = {
        "type": "notification",
        "notification": {
            "type": "info",
            "message": message,
            "actions": actions
        }
    }
    
    # Return the notification as JSON
    print(json.dumps(response))
    sys.exit(0)

if __name__ == "__main__":
    main() 