#!/usr/bin/env python3
"""
Script to generate a table of contents for Markdown documentation files.
This script is used by the .cursorrules file to automatically update the TOC
when the master documentation is modified.
"""

import re
import sys
import json
import os

def generate_toc(file_path, start_marker, end_marker, max_depth=3):
    """
    Generate a table of contents for a Markdown file.
    
    Args:
        file_path (str): Path to the Markdown file
        start_marker (str): Marker indicating where the TOC begins
        end_marker (str): Marker indicating where the TOC ends
        max_depth (int): Maximum header depth to include (default: 3)
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            return False
        
        # Read the file content
        with open(file_path, 'r') as f:
            content = f.read()
        
        # Find the positions of the start and end markers
        start_pos = content.find(start_marker)
        end_pos = content.find(end_marker)
        
        if start_pos == -1 or end_pos == -1:
            print(f"Error: Could not find TOC markers in {file_path}")
            return False
        
        # Extract the header section and the rest of the content
        header_section = content[:start_pos + len(start_marker)]
        footer_section = content[end_pos:]
        
        # Find all markdown headers in the content
        # This regex matches headers like '# Header', '## Subheader', etc.
        header_pattern = r'^(#{1,' + str(max_depth) + r'}) (.+)$'
        headers = re.finditer(header_pattern, content, re.MULTILINE)
        
        # Generate TOC entries
        toc_lines = []
        toc_lines.append("## Table of Contents\n")
        toc_lines.append("")
        
        for match in headers:
            # Skip headers that are inside the TOC section itself
            header_pos = match.start()
            if start_pos < header_pos < end_pos:
                continue
                
            # Get the header level and text
            hashes = match.group(1)
            header_text = match.group(2).strip()
            
            # Skip the main title and the TOC title itself
            if hashes == '#' or header_text == 'Table of Contents':
                continue
            
            # Create a link-friendly version of the header text
            link_text = header_text.lower()
            link_text = re.sub(r'[^\w\s-]', '', link_text)  # Remove special chars
            link_text = re.sub(r'\s+', '-', link_text)      # Replace spaces with hyphens
            
            # Handle special cases with emojis
            if '(' in header_text and ')' in header_text:
                # For headers like "Color Grading Operations (📝 Planned)"
                emoji_match = re.search(r'\((.+)\)', header_text)
                if emoji_match:
                    emoji_part = emoji_match.group(1).strip()
                    base_part = header_text.split('(')[0].strip().lower()
                    base_part = re.sub(r'[^\w\s-]', '', base_part)
                    base_part = re.sub(r'\s+', '-', base_part)
                    link_text = f"{base_part}-{emoji_part.lower()}"
                    link_text = re.sub(r'[^\w\s-]', '', link_text)
                    link_text = re.sub(r'\s+', '-', link_text)
            
            # Calculate the indentation based on header level
            indent = '  ' * (len(hashes) - 1)
            
            # Add the TOC entry
            toc_lines.append(f"{indent}- [{header_text}](#{link_text})")
        
        toc_lines.append("")
        
        # Combine the sections with the new TOC
        updated_content = header_section + '\n'.join(toc_lines) + '\n' + footer_section
        
        # Write the updated content back to the file
        with open(file_path, 'w') as f:
            f.write(updated_content)
            
        print(f"Generated TOC for {file_path}")
        return True
        
    except Exception as e:
        print(f"Error generating TOC: {str(e)}")
        return False

if __name__ == "__main__":
    try:
        # Parse arguments from stdin (Cursor passes arguments as JSON)
        args = json.loads(sys.stdin.read())
        
        # Extract the arguments
        file_path = args.get('file')
        start_marker = args.get('startMarker')
        end_marker = args.get('endMarker')
        max_depth = args.get('maxDepth', 3)
        
        # Validate arguments
        if not all([file_path, start_marker, end_marker]):
            print("Error: Missing required arguments (file, startMarker, endMarker)")
            sys.exit(1)
            
        # Generate TOC
        if generate_toc(file_path, start_marker, end_marker, max_depth):
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1) 