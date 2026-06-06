#!/usr/bin/env python3
"""
DaVinci Resolve MCP Server - Object Inspection Utilities

This module provides functions for inspecting DaVinci Resolve API objects:
- Exploring available methods and properties
- Generating structured documentation
- Inspecting nested objects
- Converting between Python and Lua objects if needed
"""

import sys
import inspect
import logging
from typing import Any, Dict, List, Optional, Union, Callable

logger = logging.getLogger(__name__)


def get_object_members(
    obj: Any,
    include_methods: bool = True,
    include_properties: bool = True,
) -> Dict[str, Any]:
    """
    Inspect a DaVinci Resolve object's methods and/or properties in a single pass.

    DaVinci Resolve API objects are C extensions: every attribute access is a
    bridge round-trip, so we walk ``dir(obj)`` exactly once and classify each
    attribute, rather than walking it separately for methods and properties.

    Args:
        obj: A DaVinci Resolve API object
        include_methods: Collect callable attributes
        include_properties: Collect non-callable attributes

    Returns:
        A dict with ``"methods"`` and/or ``"properties"`` keys, or ``{"error": ...}``
    """
    if obj is None:
        return {"error": "Cannot inspect None object"}

    methods: Dict[str, Dict[str, Any]] = {}
    properties: Dict[str, Dict[str, Any]] = {}

    for attr_name in dir(obj):
        # Skip private/internal attributes
        if attr_name.startswith('_'):
            continue

        try:
            attr = getattr(obj, attr_name)
        except Exception as e:
            if include_methods:
                methods[attr_name] = {"error": str(e), "type": "error"}
            if include_properties:
                properties[attr_name] = {"error": str(e), "type_category": "error"}
            continue

        if callable(attr):
            if not include_methods:
                continue
            # Only real Python functions/methods carry an introspectable
            # signature. Resolve API methods are C extensions where
            # inspect.signature() is slow and almost always raises, so we skip
            # the attempt and default to "()" for them.
            if inspect.isfunction(attr) or inspect.ismethod(attr):
                try:
                    signature = str(inspect.signature(attr))
                except (ValueError, TypeError):
                    signature = "()"
            else:
                signature = "()"

            # Read __doc__ directly instead of inspect.getdoc() to avoid the
            # MRO walk for inherited docstrings (irrelevant for C-ext methods).
            doc = (getattr(attr, "__doc__", "") or "").strip()

            methods[attr_name] = {
                "signature": signature,
                "doc": doc,
                "type": "method",
            }
        else:
            if not include_properties:
                continue
            properties[attr_name] = {
                "value": str(attr),
                "type": type(attr).__name__,
                "type_category": "property",
            }

    result: Dict[str, Any] = {}
    if include_methods:
        result["methods"] = methods
    if include_properties:
        result["properties"] = properties
    return result


def get_object_methods(obj: Any) -> Dict[str, Dict[str, Any]]:
    """
    Get all methods of a DaVinci Resolve object with their documentation.

    Thin wrapper over :func:`get_object_members` kept for backwards compatibility.
    """
    res = get_object_members(obj, include_methods=True, include_properties=False)
    return res.get("methods", res)


def get_object_properties(obj: Any) -> Dict[str, Dict[str, Any]]:
    """
    Get all properties (non-callable attributes) of a DaVinci Resolve object.

    Thin wrapper over :func:`get_object_members` kept for backwards compatibility.
    """
    res = get_object_members(obj, include_methods=False, include_properties=True)
    return res.get("properties", res)


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
    
    members = get_object_members(obj)
    result = {
        "type": type(obj).__name__,
        "methods": members.get("methods", {}),
        "properties": members.get("properties", {}),
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
    if hasattr(lua_table, 'GetKeyList'):
        try:
            # Some DaVinci Resolve objects have a GetKeyList() method
            return lua_table.GetKeyList()
        except Exception:
            logger.debug("Lua table GetKeyList() lookup failed", exc_info=True)
            
    # Try different iteration methods that might work with Lua tables
    try:
        # Some Lua tables can be iterated directly
        for key in lua_table:
            keys.append(key)
        return keys
    except Exception:
        logger.debug("Lua table direct iteration failed", exc_info=True)
        
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
    if hasattr(lua_obj, 'GetKeyList') or hasattr(lua_obj, '__iter__'):
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
                except Exception:
                    logger.debug("Failed to convert Lua table key %r", key, exc_info=True)
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
                except Exception:
                    logger.debug("Lua numeric iteration stopped at index %s", index, exc_info=True)
                    break
            
            # If we found items, return as list
            if result:
                return result
        except Exception:
            logger.debug("Lua numeric-indexed conversion failed", exc_info=True)
    
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
    members = get_object_members(obj)
    methods = members.get("methods", {})
    properties = members.get("properties", {})

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
