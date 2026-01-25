"""
Resolve AI Chatbot Package

A standalone AI-powered chatbot for controlling DaVinci Resolve
using natural language commands via Google Gemini.

Usage:
    # Launch the chatbot window
    python -m autonomous.chatbot.chat_window
    
    # Or from the scripts folder
    scripts/launch-chatbot.bat
    
    # Or from within DaVinci Resolve
    Workspace > Scripts > Edit > Resolve AI Chat
"""

__version__ = "1.0.0"

# Lazy imports to avoid circular dependencies
def get_chat_window():
    """Get the ResolveChatWindow class."""
    from .chat_window import ResolveChatWindow
    return ResolveChatWindow

def get_gemini_client():
    """Get the GeminiClient class."""
    from .gemini_client import GeminiClient
    return GeminiClient

def get_tool_router():
    """Get the ToolRouter class."""
    from .tool_router import ToolRouter
    return ToolRouter

# For direct imports
try:
    from .chat_window import ResolveChatWindow, create_chat_application
    from .gemini_client import GeminiClient, is_gemini_available
    from .tool_router import ToolRouter
    from .tool_definitions import get_tool_definitions, get_tool_names
except ImportError:
    # Dependencies may not be available yet
    pass

__all__ = [
    'ResolveChatWindow', 
    'GeminiClient', 
    'ToolRouter',
    'create_chat_application',
    'is_gemini_available',
    'get_tool_definitions',
    'get_tool_names',
]
