#!/usr/bin/env python3
"""
Script to update testing status in the master documentation based on test results
in test files. This script is used by the .cursorrules file to automatically
keep the testing status current.
"""

import re
import sys
import json
import os

def update_test_status(source_file, target_file, test_pattern, result_pattern):
    """
    Update the testing status in the master documentation based on test results
    in test files.
    
    Args:
        source_file (str): Path to the test file
        target_file (str): Path to the master documentation file
        test_pattern (str): Regex pattern to match test function names
        result_pattern (str): Regex pattern to match test result comments
        
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
        
        # Read the source test file
        with open(source_file, 'r') as f:
            source_content = f.read()
        
        # Read the target documentation file
        with open(target_file, 'r') as f:
            doc_content = f.read()
        
        # Find all test functions with their associated result comments
        test_matches = re.finditer(test_pattern, source_content)
        
        # Process each test function found
        tests_updated = 0
        for match in test_matches:
            # Get the function name (without the test_ prefix)
            function_name = f"mcp_{match.group(1)}"
            
            # Look for result comment in the test function
            # Search from the start of the match to the next function definition or end of file
            start_pos = match.start()
            next_func_match = re.search(r'^def\s+', source_content[match.end():], re.MULTILINE)
            if next_func_match:
                end_pos = match.end() + next_func_match.start()
            else:
                end_pos = len(source_content)
                
            function_body = source_content[start_pos:end_pos]
            result_match = re.search(result_pattern, function_body)
            
            if result_match:
                result = result_match.group(1).strip()
                
                # Update the testing status in the documentation file
                # We need to find the function in a table row format
                # The testing status is in the third column
                function_pattern_in_doc = r'\| ' + re.escape(function_name) + r' \| [✅⚠️❌🔄📝🧪][^\|]* \| ([^\|]*) \|'
                
                # Use re.sub with a lambda to only replace the testing status column
                def replace_test_status(m):
                    parts = m.group(0).split('|')
                    if len(parts) >= 4:  # Ensure we have enough columns
                        parts[3] = f" {result} "
                        return '|'.join(parts)
                    return m.group(0)
                
                doc_content = re.sub(function_pattern_in_doc, replace_test_status, doc_content)
                tests_updated += 1
        
        # Write the updated documentation back to the file
        with open(target_file, 'w') as f:
            f.write(doc_content)
            
        print(f"Updated testing status for {tests_updated} functions in {target_file}")
        return True
        
    except Exception as e:
        print(f"Error updating test status: {str(e)}")
        return False

if __name__ == "__main__":
    try:
        # Parse arguments from stdin (Cursor passes arguments as JSON)
        args = json.loads(sys.stdin.read())
        
        # Extract the arguments
        source_file = args.get('sourceFile')
        target_file = args.get('targetFile')
        test_pattern = args.get('testPattern')
        result_pattern = args.get('resultPattern')
        
        # Validate arguments
        if not all([source_file, target_file, test_pattern, result_pattern]):
            print("Error: Missing required arguments")
            sys.exit(1)
            
        # Update test status
        if update_test_status(source_file, target_file, test_pattern, result_pattern):
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1) 