#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server - Object Inspection Utilities

This module provides functions for inspecting DaVinci Resolve API objects:
- Exploring available methods and properties
- Generating structured documentation
- Inspecting nested objects
- Converting between Python and Lua objects if needed
"""

import inspect
from typing import Any, Dict, List


def get_object_methods(obj: Any) -> Dict[str, Dict[str, Any]]:
    """
    Get all methods of a DaVinci Resolve object with their documentation.

    Args:
        obj: A DaVinci Resolve API object

    Returns:
        A dictionary of method names and their details
    """
    if obj is None:
        return {"error": "Cannot inspect None object"}

    methods = {}

    # Get all object attributes
    for attr_name in dir(obj):
        # Skip private/internal attributes
        if attr_name.startswith("_"):
            continue

        try:
            attr = getattr(obj, attr_name)

            # Check if it's a callable method
            if callable(attr):
                # Get the method signature if possible
                try:
                    signature = str(inspect.signature(attr))
                except (ValueError, TypeError):
                    signature = "()"

                # Get the docstring if available
                doc = inspect.getdoc(attr) or ""

                methods[attr_name] = {
                    "signature": signature,
                    "doc": doc,
                    "type": "method",
                }
        except Exception as e:
            methods[attr_name] = {"error": str(e), "type": "error"}

    return methods


def get_object_properties(obj: Any) -> Dict[str, Dict[str, Any]]:
    """
    Get all properties (non-callable attributes) of a DaVinci Resolve object.

    Args:
        obj: A DaVinci Resolve API object

    Returns:
        A dictionary of property names and their details
    """
    if obj is None:
        return {"error": "Cannot inspect None object"}

    properties = {}

    # Get all object attributes
    for attr_name in dir(obj):
        # Skip private/internal attributes
        if attr_name.startswith("_"):
            continue

        try:
            attr = getattr(obj, attr_name)

            # Skip if it's a method
            if callable(attr):
                continue

            # Get the property value and type
            properties[attr_name] = {
                "value": str(attr),
                "type": type(attr).__name__,
                "type_category": "property",
            }
        except Exception as e:
            properties[attr_name] = {"error": str(e), "type_category": "error"}

    return properties


def inspect_object(obj: Any, max_depth: int = 1) -> Dict[str, Any]:
    """
    Inspect a DaVinci Resolve API object and return its methods and properties.

    Args:
        obj: A DaVinci Resolve API object
        max_depth: Maximum depth for nested object inspection

    Returns:
        A dictionary containing the object's methods and properties
    """
    if obj is None:
        return {"error": "Cannot inspect None object"}

    result = {
        "type": type(obj).__name__,
        "methods": get_object_methods(obj),
        "properties": get_object_properties(obj),
    }

    # Add string representation
    try:
        result["str"] = str(obj)
    except Exception as e:
        result["str_error"] = str(e)

    # Add repr representation
    try:
        result["repr"] = repr(obj)
    except Exception as e:
        result["repr_error"] = str(e)

    return result


def get_lua_table_keys(lua_table: Any) -> List[str]:
    """
    Get all keys from a Lua table object (if the object supports Lua table iteration).

    Args:
        lua_table: A Lua table object from DaVinci Resolve API

    Returns:
        A list of keys from the Lua table
    """
    if lua_table is None:
        return []

    keys = []

    # Check for DaVinci-specific Lua table iteration methods
    if hasattr(lua_table, "GetKeyList"):
        try:
            # Some DaVinci Resolve objects have a GetKeyList() method
            return lua_table.GetKeyList()
        except:
            pass

    # Try different iteration methods that might work with Lua tables
    try:
        # Some Lua tables can be iterated directly
        for key in lua_table:
            keys.append(key)
        return keys
    except:
        pass

    # Try manual iteration with pairs-like behavior (if available)
    # This is a fallback for APIs that don't support Python-style iteration
    return []


def convert_lua_to_python(lua_obj: Any) -> Any:
    """
    Convert a Lua object from DaVinci Resolve API to a Python object.

    Args:
        lua_obj: A Lua object from DaVinci Resolve API

    Returns:
        The converted Python object
    """
    # Handle None
    if lua_obj is None:
        return None

    # Handle primitive types
    if isinstance(lua_obj, (str, int, float, bool)):
        return lua_obj

    # Try to convert Lua tables to Python dicts or lists
    if hasattr(lua_obj, "GetKeyList") or hasattr(lua_obj, "__iter__"):
        keys = get_lua_table_keys(lua_obj)

        # If we found keys, convert to dict
        if keys:
            result = {}
            for key in keys:
                try:
                    # Get the value for this key
                    value = lua_obj[key]
                    # Recursively convert nested Lua objects
                    result[key] = convert_lua_to_python(value)
                except:
                    result[key] = None
            return result

        # Try to convert to list if it appears numeric-indexed
        try:
            # Common Lua pattern for numeric arrays (1-indexed)
            result = []
            index = 1  # Lua arrays typically start at 1
            while True:
                try:
                    value = lua_obj[index]
                    result.append(convert_lua_to_python(value))
                    index += 1
                except:
                    break

            # If we found items, return as list
            if result:
                return result
        except:
            pass

    # If conversion failed, return string representation
    return str(lua_obj)


def print_object_help(obj: Any) -> str:
    """
    Generate a human-readable help string for a DaVinci Resolve API object.

    Args:
        obj: A DaVinci Resolve API object

    Returns:
        A formatted help string describing the object's methods and properties
    """
    if obj is None:
        return "Cannot provide help for None object"

    obj_type = type(obj).__name__
    methods = get_object_methods(obj)
    properties = get_object_properties(obj)

    help_text = [f"Help for {obj_type} object:"]
    help_text.append("\n" + "=" * 40 + "\n")

    # Add methods
    if methods:
        help_text.append("METHODS:")
        help_text.append("-" * 40)
        for name, info in sorted(methods.items()):
            if "error" in info:
                continue
            signature = info.get("signature", "()")
            doc = info.get("doc", "").strip()
            help_text.append(f"{name}{signature}")
            if doc:
                help_text.append(f"    {doc}\n")
            else:
                help_text.append("")

    # Add properties
    if properties:
        help_text.append("\nPROPERTIES:")
        help_text.append("-" * 40)
        for name, info in sorted(properties.items()):
            if "error" in info:
                continue
            value = info.get("value", "")
            type_name = info.get("type", "")
            help_text.append(f"{name}: {type_name} = {value}")

    return "\n".join(help_text)
