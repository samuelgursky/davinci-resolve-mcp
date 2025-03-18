"""
Configuration module for the MCP server.
"""
import os
from typing import List, Dict, Any, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class MCPServerSettings(BaseSettings):
    """Settings for the MCP server."""
    
    # Server settings
    HOST: str = Field(
        default="127.0.0.1", 
        description="Host to run the MCP server on"
    )
    PORT: int = Field(
        default=8765, 
        description="Port to run the MCP server on"
    )
    DEBUG: bool = Field(
        default=False, 
        description="Enable debug mode"
    )
    
    # MCP settings
    SERVER_NAME: str = Field(
        default="DaVinci Resolve MCP", 
        description="Name of the MCP server"
    )
    SERVER_VERSION: str = Field(
        default="0.1.0", 
        description="Version of the MCP server"
    )
    
    # Security settings
    API_KEY: Optional[str] = Field(
        default=None, 
        description="API key for authentication"
    )
    ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "https://claude.ai"], 
        description="List of allowed origins for CORS"
    )
    
    # Use model_config instead of Config class for Pydantic v2
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MCP_",
        extra="ignore"  # Ignore extra fields from env file
    )

# Create settings instance
settings = MCPServerSettings()

# MCP server info dictionary
SERVER_INFO = {
    "mcp_version": "0.1.0",
    "name": settings.SERVER_NAME,
    "version": settings.SERVER_VERSION,
    "display_name": settings.SERVER_NAME,
    "description": "MCP server for DaVinci Resolve integration",
    "contact_email": "your-email@example.com",
    "icons": {
        "small": "https://raw.githubusercontent.com/yourusername/davinci-resolve-mcp/main/assets/icon-small.png",
        "medium": "https://raw.githubusercontent.com/yourusername/davinci-resolve-mcp/main/assets/icon-medium.png",
        "large": "https://raw.githubusercontent.com/yourusername/davinci-resolve-mcp/main/assets/icon-large.png",
    },
    "categories": ["video-editing", "creativity"],
    "authentication": {
        "type": "api_key" if settings.API_KEY else "none",
        "api_key_location": "header" if settings.API_KEY else None,
        "api_key_name": "X-API-Key" if settings.API_KEY else None,
    },
    "capabilities": {
        "read_projects": True,
        "modify_projects": True,
        "read_timeline": True,
        "modify_timeline": True,
        "read_media": True,
        "render_export": True,
        "color_grading": True,
    }
}

# Supported operations - ensure select_clips_by_name is included
SUPPORTED_OPERATIONS = [
    "get_projects",
    "get_project_info",
    "get_timeline_info",
    "get_media_pool_items",
    "get_timeline_clips",
    "create_project",
    "open_project",
    "add_clip_to_timeline",
    "export_timeline",
    "apply_lut",
    "render_project",
    "get_api_capabilities",
    "select_clips_by_name"  # Make sure this is included
] 