#!/usr/bin/env python3
"""
Script to generate API reference documentation from source code.
This script is used by the .cursorrules file for manual invocation
to create a comprehensive API reference.
"""

import re
import sys
import json
import os
import glob
import ast
import inspect
from typing import List, Dict, Tuple, Optional

def parse_docstring(docstring: str) -> Dict[str, str]:
    """
    Parse a docstring into a dictionary of sections.
    
    Args:
        docstring (str): The function docstring
        
    Returns:
        Dict[str, str]: A dictionary with sections (description, args, returns, etc.)
    """
    if not docstring:
        return {'description': 'No documentation available.'}
    
    # Clean up the docstring
    docstring = inspect.cleandoc(docstring)
    
    # Default sections
    sections = {
        'description': '',
        'args': '',
        'returns': '',
        'raises': '',
        'examples': ''
    }
    
    # Extract description (everything before Args/Returns/Raises)
    section_match = re.search(r'^(Args|Returns|Raises|Examples):', docstring, re.MULTILINE)
    if section_match:
        sections['description'] = docstring[:section_match.start()].strip()
        remaining = docstring[section_match.start():]
    else:
        sections['description'] = docstring.strip()
        remaining = ''
    
    # Extract each section
    for section in ['Args', 'Returns', 'Raises', 'Examples']:
        section_match = re.search(fr'^{section}:(.*?)(?:^(?:Args|Returns|Raises|Examples):|$)', 
                                  remaining, re.MULTILINE | re.DOTALL)
        if section_match:
            sections[section.lower()] = section_match.group(1).strip()
    
    return sections

def parse_function_signature(func_def: str) -> Tuple[str, List[Dict[str, str]]]:
    """
    Parse a function definition to extract the function name and parameters.
    
    Args:
        func_def (str): The function definition string
        
    Returns:
        Tuple[str, List[Dict[str, str]]]: Function name and list of parameter info
    """
    # Extract function name and parameters
    match = re.match(r'def\s+(\w+)\s*\((.*?)\):', func_def, re.DOTALL)
    if not match:
        return '', []
    
    func_name = match.group(1)
    params_str = match.group(2).strip()
    
    # If no parameters, return empty list
    if not params_str:
        return func_name, []
    
    # Split parameters and parse each one
    params = []
    for param in params_str.split(','):
        param = param.strip()
        if not param:
            continue
            
        # Check for default value
        if '=' in param:
            name, default = param.split('=', 1)
            param_info = {
                'name': name.strip(),
                'default': default.strip(),
                'required': False
            }
        else:
            param_info = {
                'name': param,
                'default': None,
                'required': True
            }
            
        # Check for type annotations
        if ':' in param_info['name']:
            name, type_annotation = param_info['name'].split(':', 1)
            param_info['name'] = name.strip()
            param_info['type'] = type_annotation.strip()
        else:
            param_info['type'] = None
            
        params.append(param_info)
    
    return func_name, params

def generate_api_reference(source_pattern: str, output_file: str, function_pattern: str) -> bool:
    """
    Generate API reference documentation from source code.
    
    Args:
        source_pattern (str): Glob pattern for source code files
        output_file (str): Path to the output file
        function_pattern (str): Regex pattern to match function definitions
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Find all source files matching the pattern
        source_files = glob.glob(source_pattern)
        if not source_files:
            print(f"No source files found matching pattern: {source_pattern}")
            return False
        
        # Dictionary to store functions by module
        functions_by_module = {}
        
        # Process each source file
        for source_file in source_files:
            with open(source_file, 'r') as f:
                source_content = f.read()
            
            module_name = os.path.basename(source_file).replace('.py', '')
            
            # Find all function definitions matching the pattern
            func_matches = re.finditer(function_pattern, source_content, re.MULTILINE)
            
            for match in func_matches:
                # Get the full function definition
                func_start = match.start()
                
                # Find the function body by parsing the indentation
                lines = source_content[func_start:].split('\n')
                func_def_line = lines[0]
                
                # Get the indentation of the function
                func_indent = len(func_def_line) - len(func_def_line.lstrip())
                
                # Collect the function body lines
                func_lines = [func_def_line]
                for line in lines[1:]:
                    if line.strip() == '' or len(line) - len(line.lstrip()) > func_indent:
                        func_lines.append(line)
                    else:
                        break
                
                func_def = '\n'.join(func_lines)
                
                # Get function name and parameters
                func_name = f"mcp_{match.group(1)}"
                func_params_str = match.group(2) if len(match.groups()) > 1 else ""
                
                # Parse function signature
                _, params = parse_function_signature(func_def)
                
                # Extract docstring
                docstring = ""
                doc_match = re.search(r'"""(.*?)"""', func_def, re.DOTALL)
                if doc_match:
                    docstring = doc_match.group(1).strip()
                
                # Parse docstring
                doc_sections = parse_docstring(docstring)
                
                # Store function info
                if module_name not in functions_by_module:
                    functions_by_module[module_name] = []
                
                functions_by_module[module_name].append({
                    'name': func_name,
                    'params': params,
                    'docs': doc_sections,
                    'signature': f"{func_name}({func_params_str})"
                })
        
        # If no functions found, return
        if not functions_by_module:
            print("No functions found matching pattern in source files")
            return False
        
        # Generate API reference document
        output = "# DaVinci Resolve MCP API Reference\n\n"
        output += "This document provides a comprehensive API reference for all functions in the DaVinci Resolve MCP integration.\n\n"
        
        # Add a table of contents
        output += "## Table of Contents\n\n"
        
        for module_name, functions in sorted(functions_by_module.items()):
            module_title = module_name.replace('_', ' ').title()
            output += f"- [{module_title}](#{module_name})\n"
            
            for func_info in sorted(functions, key=lambda x: x['name']):
                func_anchor = func_info['name'].lower().replace('_', '-')
                output += f"  - [{func_info['name']}](#{func_anchor})\n"
        
        output += "\n"
        
        # Add sections for each module
        for module_name, functions in sorted(functions_by_module.items()):
            module_title = module_name.replace('_', ' ').title()
            output += f"## {module_title} <a name=\"{module_name}\"></a>\n\n"
            
            for func_info in sorted(functions, key=lambda x: x['name']):
                func_anchor = func_info['name'].lower().replace('_', '-')
                output += f"### {func_info['name']} <a name=\"{func_anchor}\"></a>\n\n"
                output += f"```python\n{func_info['signature']}\n```\n\n"
                
                output += f"{func_info['docs']['description']}\n\n"
                
                if func_info['docs']['args']:
                    output += "**Parameters:**\n\n"
                    
                    # Check if the Args section follows the standard format with parameter descriptions
                    params_match = re.findall(r'(\w+)(?:\s+\(([^)]+)\))?\s*:\s*(.+?)(?=\n\s*\w+\s*(?:\([^)]+\))?\s*:|$)', 
                                              func_info['docs']['args'], re.DOTALL)
                    
                    if params_match:
                        for param_name, param_type, param_desc in params_match:
                            param_desc = param_desc.strip()
                            if param_type:
                                output += f"- `{param_name}` ({param_type}): {param_desc}\n"
                            else:
                                output += f"- `{param_name}`: {param_desc}\n"
                    else:
                        # Fall back to just showing the raw args section
                        output += func_info['docs']['args'] + "\n"
                        
                    output += "\n"
                
                if func_info['docs']['returns']:
                    output += "**Returns:**\n\n"
                    output += func_info['docs']['returns'] + "\n\n"
                
                if func_info['docs']['raises']:
                    output += "**Raises:**\n\n"
                    output += func_info['docs']['raises'] + "\n\n"
                
                if func_info['docs']['examples']:
                    output += "**Examples:**\n\n"
                    output += "```python\n" + func_info['docs']['examples'] + "\n```\n\n"
                
                output += "---\n\n"
        
        # Add footer
        output += "## About This Document\n\n"
        output += "This API reference was automatically generated from source code docstrings. "
        output += "If you find any errors or have suggestions for improvements, please contribute to the documentation.\n\n"
        output += f"Last generated: {os.environ.get('DATE', 'YYYY-MM-DD')}\n"
        
        # Write the output to file
        with open(output_file, 'w') as f:
            f.write(output)
            
        print(f"Generated API reference at {output_file}")
        return True
        
    except Exception as e:
        print(f"Error generating API reference: {str(e)}")
        return False

if __name__ == "__main__":
    try:
        # Parse arguments from stdin (Cursor passes arguments as JSON)
        args = json.loads(sys.stdin.read())
        
        # Extract the arguments
        source_pattern = args.get('sourcePattern')
        output_file = args.get('outputFile')
        function_pattern = args.get('functionPattern')
        
        # Validate arguments
        if not all([source_pattern, output_file, function_pattern]):
            print("Error: Missing required arguments")
            sys.exit(1)
            
        # Set DATE environment variable for the footer
        import datetime
        os.environ['DATE'] = datetime.datetime.now().strftime('%Y-%m-%d')
            
        # Generate API reference
        if generate_api_reference(source_pattern, output_file, function_pattern):
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1) 