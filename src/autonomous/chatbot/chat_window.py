#!/usr/bin/env python3
"""
Resolve AI Chatbot Window

A standalone tkinter-based chat interface for controlling DaVinci Resolve
using natural language via Google Gemini.
"""

import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Callable, Optional
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("chatbot.window")

# Add src to path
src_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if src_path not in sys.path:
    sys.path.insert(0, src_path)


class ResolveChatWindow:
    """Dark-themed chat window for controlling DaVinci Resolve."""
    
    # Color scheme matching DaVinci Resolve
    COLORS = {
        'bg_dark': '#1a1a1a',
        'bg_medium': '#2a2a2a',
        'bg_light': '#3a3a3a',
        'text': '#e0e0e0',
        'text_dim': '#888888',
        'accent': '#ff7000',  # DaVinci Resolve orange
        'accent_dim': '#cc5a00',
        'user_msg': '#3d5a80',
        'assistant_msg': '#2a3f5f',
        'error': '#ff4444',
        'success': '#44ff44',
        'border': '#444444',
        # Page-specific colors
        'page_media': '#4a90d9',
        'page_cut': '#d94a4a',
        'page_edit': '#4ad94a',
        'page_fusion': '#9b59b6',
        'page_color': '#e67e22',
        'page_fairlight': '#1abc9c',
        'page_deliver': '#3498db'
    }
    
    # Page icons/emojis
    PAGE_ICONS = {
        'media': '📁',
        'cut': '✂️',
        'edit': '🎬',
        'fusion': '✨',
        'color': '🎨',
        'fairlight': '🎵',
        'deliver': '📤',
        'unknown': '❓'
    }
    
    def __init__(self, on_send: Optional[Callable[[str], str]] = None, 
                 context_provider: Optional[Callable] = None):
        """
        Initialize the chat window.
        
        Args:
            on_send: Callback function that takes user message and returns response
            context_provider: Function that returns current page context
        """
        self.on_send = on_send
        self.context_provider = context_provider
        self.is_processing = False
        self.always_on_top = tk.BooleanVar(value=True)
        self.current_page = "unknown"
        
        # Create main window
        self.root = tk.Tk()
        self.root.title("Resolve AI Chat")
        self.root.geometry("600x700")
        self.root.minsize(400, 500)
        
        # Set dark theme
        self.root.configure(bg=self.COLORS['bg_dark'])
        
        # Configure styles
        self._configure_styles()
        
        # Build UI
        self._build_ui()
        
        # Set window properties
        self.root.attributes('-topmost', True)
        
        # Bind keyboard shortcuts
        self.root.bind('<Control-Return>', lambda e: self._send_message())
        self.root.bind('<Escape>', lambda e: self.root.destroy())
        
        # Focus on input
        self.input_text.focus()
    
    def _configure_styles(self):
        """Configure ttk styles for dark theme."""
        style = ttk.Style()
        
        # Try to use a dark theme if available
        available_themes = style.theme_names()
        if 'clam' in available_themes:
            style.theme_use('clam')
        
        # Configure button style
        style.configure(
            'Dark.TButton',
            background=self.COLORS['bg_light'],
            foreground=self.COLORS['text'],
            borderwidth=1,
            focusthickness=0,
            padding=(10, 5)
        )
        style.map(
            'Dark.TButton',
            background=[('active', self.COLORS['accent']), ('pressed', self.COLORS['accent_dim'])],
            foreground=[('active', 'white'), ('pressed', 'white')]
        )
        
        # Configure accent button
        style.configure(
            'Accent.TButton',
            background=self.COLORS['accent'],
            foreground='white',
            borderwidth=0,
            focusthickness=0,
            padding=(15, 8)
        )
        style.map(
            'Accent.TButton',
            background=[('active', self.COLORS['accent_dim']), ('pressed', '#aa4400')]
        )
        
        # Configure checkbutton
        style.configure(
            'Dark.TCheckbutton',
            background=self.COLORS['bg_dark'],
            foreground=self.COLORS['text']
        )
    
    def _build_ui(self):
        """Build the user interface."""
        # Main container
        main_frame = tk.Frame(self.root, bg=self.COLORS['bg_dark'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Header
        self._build_header(main_frame)
        
        # Chat display
        self._build_chat_display(main_frame)
        
        # Input area
        self._build_input_area(main_frame)
        
        # Status bar
        self._build_status_bar(main_frame)
    
    def _build_header(self, parent):
        """Build the header with title and controls."""
        header = tk.Frame(parent, bg=self.COLORS['bg_dark'])
        header.pack(fill=tk.X, pady=(0, 10))
        
        # Title
        title = tk.Label(
            header,
            text="🎬 Resolve AI Assistant",
            font=('Segoe UI', 14, 'bold'),
            bg=self.COLORS['bg_dark'],
            fg=self.COLORS['accent']
        )
        title.pack(side=tk.LEFT)
        
        # Always on top checkbox
        top_check = ttk.Checkbutton(
            header,
            text="Always on Top",
            variable=self.always_on_top,
            command=self._toggle_always_on_top,
            style='Dark.TCheckbutton'
        )
        top_check.pack(side=tk.RIGHT)
        
        # Clear button
        clear_btn = ttk.Button(
            header,
            text="Clear",
            command=self._clear_chat,
            style='Dark.TButton'
        )
        clear_btn.pack(side=tk.RIGHT, padx=5)
    
    def _build_chat_display(self, parent):
        """Build the chat message display area."""
        # Chat container with border
        chat_container = tk.Frame(
            parent,
            bg=self.COLORS['border'],
            highlightthickness=1,
            highlightbackground=self.COLORS['border']
        )
        chat_container.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Chat display
        self.chat_display = scrolledtext.ScrolledText(
            chat_container,
            wrap=tk.WORD,
            font=('Consolas', 10),
            bg=self.COLORS['bg_medium'],
            fg=self.COLORS['text'],
            insertbackground=self.COLORS['text'],
            selectbackground=self.COLORS['accent'],
            padx=10,
            pady=10,
            relief=tk.FLAT,
            state=tk.DISABLED
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        
        # Configure tags for message styling
        self.chat_display.tag_configure('user', foreground='#88ccff', font=('Consolas', 10, 'bold'))
        self.chat_display.tag_configure('assistant', foreground='#ffcc88', font=('Consolas', 10, 'bold'))
        self.chat_display.tag_configure('system', foreground=self.COLORS['text_dim'], font=('Consolas', 9, 'italic'))
        self.chat_display.tag_configure('error', foreground=self.COLORS['error'])
        self.chat_display.tag_configure('success', foreground=self.COLORS['success'])
        self.chat_display.tag_configure('tool', foreground='#88ff88', font=('Consolas', 9))
        
        # Add welcome message
        self._add_system_message(
            "Welcome to Resolve AI Assistant!\n"
            "I'm page-aware - I know which page you're on and can help accordingly:\n"
            "\n"
            "🎨 Color Page: 'Apply cinematic look' or 'Make it warmer'\n"
            "🎵 Fairlight Page: 'Analyze beats' or 'Duck music under voiceover'\n"
            "✨ Fusion Page: 'Add blur effect' or 'Create text animation'\n"
            "🎬 Edit Page: 'Add clip to timeline' or 'Create markers'\n"
            "\n"
            "Just switch pages in Resolve and I'll adapt my suggestions!\n"
        )
    
    def _build_input_area(self, parent):
        """Build the message input area."""
        input_frame = tk.Frame(parent, bg=self.COLORS['bg_dark'])
        input_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Input text field
        input_container = tk.Frame(
            input_frame,
            bg=self.COLORS['border'],
            highlightthickness=1,
            highlightbackground=self.COLORS['border']
        )
        input_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        self.input_text = tk.Text(
            input_container,
            height=3,
            wrap=tk.WORD,
            font=('Consolas', 11),
            bg=self.COLORS['bg_light'],
            fg=self.COLORS['text'],
            insertbackground=self.COLORS['text'],
            selectbackground=self.COLORS['accent'],
            padx=10,
            pady=8,
            relief=tk.FLAT
        )
        self.input_text.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        
        # Bind Enter to send (Shift+Enter for newline)
        self.input_text.bind('<Return>', self._on_enter_key)
        
        # Send button
        self.send_btn = ttk.Button(
            input_frame,
            text="Send",
            command=self._send_message,
            style='Accent.TButton'
        )
        self.send_btn.pack(side=tk.RIGHT, fill=tk.Y)
    
    def _build_status_bar(self, parent):
        """Build the status bar with page indicator."""
        status_frame = tk.Frame(parent, bg=self.COLORS['bg_dark'])
        status_frame.pack(fill=tk.X)
        
        # Status label
        self.status_label = tk.Label(
            status_frame,
            text="Ready",
            font=('Segoe UI', 9),
            bg=self.COLORS['bg_dark'],
            fg=self.COLORS['text_dim']
        )
        self.status_label.pack(side=tk.LEFT)
        
        # Connection indicator
        self.connection_label = tk.Label(
            status_frame,
            text="● Disconnected",
            font=('Segoe UI', 9),
            bg=self.COLORS['bg_dark'],
            fg=self.COLORS['error']
        )
        self.connection_label.pack(side=tk.RIGHT)
        
        # Page indicator (between status and connection)
        self.page_label = tk.Label(
            status_frame,
            text="📍 Page: Unknown",
            font=('Segoe UI', 9, 'bold'),
            bg=self.COLORS['bg_dark'],
            fg=self.COLORS['accent']
        )
        self.page_label.pack(side=tk.RIGHT, padx=15)
        
        # Start page polling
        self._poll_page_context()
    
    def _on_enter_key(self, event):
        """Handle Enter key - send unless Shift is held."""
        if event.state & 0x1:  # Shift is pressed
            return  # Allow newline
        self._send_message()
        return 'break'  # Prevent default newline
    
    def _send_message(self):
        """Send the current message."""
        if self.is_processing:
            return
        
        message = self.input_text.get('1.0', tk.END).strip()
        if not message:
            return
        
        # Clear input
        self.input_text.delete('1.0', tk.END)
        
        # Display user message
        self._add_message("You", message, 'user')
        
        # Process in background
        self.is_processing = True
        self._set_status("Processing...")
        self.send_btn.configure(state=tk.DISABLED)
        
        # Run in thread to avoid blocking UI
        thread = threading.Thread(target=self._process_message, args=(message,))
        thread.daemon = True
        thread.start()
    
    def _process_message(self, message: str):
        """Process a message in background thread."""
        try:
            if self.on_send:
                response = self.on_send(message)
            else:
                response = "No AI backend connected. Please configure the Gemini client."
            
            # Update UI in main thread
            self.root.after(0, lambda: self._add_message("Assistant", response, 'assistant'))
            
        except Exception as e:
            error_msg = f"Error: {e}"
            logger.error(error_msg)
            self.root.after(0, lambda: self._add_message("Error", error_msg, 'error'))
        
        finally:
            self.root.after(0, self._finish_processing)
    
    def _finish_processing(self):
        """Reset UI after processing."""
        self.is_processing = False
        self._set_status("Ready")
        self.send_btn.configure(state=tk.NORMAL)
        self.input_text.focus()
    
    def _add_message(self, sender: str, content: str, tag: str):
        """Add a message to the chat display."""
        self.chat_display.configure(state=tk.NORMAL)
        
        timestamp = datetime.now().strftime("%H:%M")
        
        # Add sender header
        self.chat_display.insert(tk.END, f"\n[{timestamp}] ", 'system')
        self.chat_display.insert(tk.END, f"{sender}:\n", tag)
        
        # Add content
        self.chat_display.insert(tk.END, f"{content}\n", tag if tag != 'user' else None)
        
        # Scroll to bottom
        self.chat_display.see(tk.END)
        self.chat_display.configure(state=tk.DISABLED)
    
    def _add_system_message(self, content: str):
        """Add a system message."""
        self.chat_display.configure(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"{content}\n", 'system')
        self.chat_display.see(tk.END)
        self.chat_display.configure(state=tk.DISABLED)
    
    def _clear_chat(self):
        """Clear the chat display."""
        self.chat_display.configure(state=tk.NORMAL)
        self.chat_display.delete('1.0', tk.END)
        self.chat_display.configure(state=tk.DISABLED)
        self._add_system_message("Chat cleared.\n")
    
    def _toggle_always_on_top(self):
        """Toggle always-on-top mode."""
        self.root.attributes('-topmost', self.always_on_top.get())
    
    def _set_status(self, status: str):
        """Set the status bar text."""
        self.status_label.configure(text=status)
    
    def set_connected(self, connected: bool):
        """Update connection status indicator."""
        if connected:
            self.connection_label.configure(
                text="● Connected",
                fg=self.COLORS['success']
            )
        else:
            self.connection_label.configure(
                text="● Disconnected",
                fg=self.COLORS['error']
            )
    
    def _poll_page_context(self):
        """Poll for page context changes every 2 seconds."""
        try:
            if self.context_provider:
                context = self.context_provider()
                page = context.get("page", "unknown")
                
                if page != self.current_page:
                    self.current_page = page
                    self._update_page_display(page, context)
        except Exception as e:
            logger.debug(f"Could not poll context: {e}")
        
        # Schedule next poll
        self.root.after(2000, self._poll_page_context)
    
    def _update_page_display(self, page: str, context: dict = None):
        """Update the page indicator display."""
        icon = self.PAGE_ICONS.get(page, '❓')
        page_name = page.capitalize() if page != "unknown" else "Unknown"
        
        # Get page-specific color
        color_key = f'page_{page}'
        color = self.COLORS.get(color_key, self.COLORS['accent'])
        
        # Update label
        self.page_label.configure(
            text=f"{icon} {page_name} Page",
            fg=color
        )
        
        # Show context info in status
        if context:
            timeline = context.get("timeline", "")
            if timeline:
                self._set_status(f"Timeline: {timeline}")
        
        # Add system message about page change
        page_tips = {
            'media': "📁 Media Page - I can help you import and organize media.",
            'cut': "✂️ Cut Page - I can help with quick assembly editing.",
            'edit': "🎬 Edit Page - I can help with timeline editing, clips, and effects.",
            'fusion': "✨ Fusion Page - I can help you build node-based effects!",
            'color': "🎨 Color Page - I can help with color grading and looks!",
            'fairlight': "🎵 Fairlight Page - I can help with audio mixing and editing!",
            'deliver': "📤 Deliver Page - I can help with rendering and export."
        }
        
        if page in page_tips:
            self._add_system_message(f"\n{page_tips[page]}\n")
    
    def set_page(self, page: str):
        """Manually set the current page."""
        self.current_page = page
        self._update_page_display(page)
    
    def run(self):
        """Start the chat window event loop."""
        logger.info("Starting chat window")
        self.root.mainloop()
    
    def close(self):
        """Close the chat window."""
        self.root.destroy()


def create_chat_application():
    """Create and configure the complete chat application."""
    from autonomous.chatbot.gemini_client import GeminiClient, is_gemini_available
    from autonomous.chatbot.tool_router import get_tool_router
    from autonomous.chatbot.tool_definitions import get_tool_definitions
    
    # Initialize tool router
    router = get_tool_router()
    connected = router.initialize()
    
    # Create context provider function
    def get_context():
        return router.get_page_context()
    
    # Initialize Gemini client with context awareness
    gemini = None
    if is_gemini_available():
        try:
            gemini = GeminiClient(
                tool_executor=router.execute,
                context_provider=get_context
            )
            gemini.initialize(get_tool_definitions())
        except Exception as e:
            logger.error(f"Failed to initialize Gemini: {e}")
    
    # Create message handler
    def handle_message(message: str) -> str:
        if gemini:
            return gemini.send_message(message)
        else:
            return "Gemini API not available. Please set GEMINI_API_KEY environment variable."
    
    # Create window with context provider
    window = ResolveChatWindow(
        on_send=handle_message,
        context_provider=get_context
    )
    window.set_connected(connected)
    
    # Show initial page context
    if connected:
        try:
            context = get_context()
            page = context.get("page", "unknown")
            window.set_page(page)
        except:
            pass
    
    if not connected:
        window._add_system_message(
            "⚠️ Not connected to DaVinci Resolve.\n"
            "Please ensure DaVinci Resolve is running.\n"
        )
    
    if not is_gemini_available():
        window._add_system_message(
            "⚠️ Gemini API not configured.\n"
            "Set GEMINI_API_KEY environment variable to enable AI features.\n"
        )
    
    return window


def main():
    """Main entry point."""
    try:
        window = create_chat_application()
        window.run()
    except Exception as e:
        logger.error(f"Failed to start chat window: {e}")
        raise


if __name__ == "__main__":
    main()
