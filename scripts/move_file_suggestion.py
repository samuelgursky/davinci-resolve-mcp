#!/usr/bin/env python3
"""
move_file_suggestion.py

A utility script for .cursorrules to suggest moving files to appropriate directories.
This script shows a notification when a file is created in an incorrect location.
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
    target_dir = args.get("targetDir", "")
    message = args.get("message", "")
    file_path = args.get("file", "")
    
    # If any of the required arguments are missing, exit with an error
    if not all([target_dir, message, file_path]):
        print("Error: Missing required arguments")
        sys.exit(1)
    
    # Check if the file path already contains the target directory
    if file_path.startswith(target_dir):
        # File is already in the correct directory
        sys.exit(0)
    
    # Build the notification response
    response = {
        "type": "notification",
        "notification": {
            "type": "info",
            "message": message,
            "actions": [
                {
                    "label": f"Move to {target_dir}",
                    "command": "cursor.moveFile",
                    "args": {
                        "source": file_path,
                        "target": os.path.join(target_dir, os.path.basename(file_path))
                    }
                }
            ]
        }
    }
    
    # Return the notification as JSON
    print(json.dumps(response))
    sys.exit(0)

if __name__ == "__main__":
    main() 