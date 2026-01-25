#!/usr/bin/env python3
"""
Gemini Client for Resolve AI Chatbot

Handles communication with Google Gemini API including:
- Function calling for tool execution
- Conversation history management
- System prompt with tool descriptions
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("chatbot.gemini_client")

# Check for Gemini availability
_GEMINI_AVAILABLE = False
try:
    import google.generativeai as genai
    from google.generativeai.types import FunctionDeclaration, Tool
    _GEMINI_AVAILABLE = True
except ImportError:
    logger.warning("google-generativeai not installed")


@dataclass
class Message:
    """A chat message."""
    role: str  # 'user', 'assistant', 'system', 'tool'
    content: str
    tool_calls: List[Dict] = field(default_factory=list)
    tool_results: List[Dict] = field(default_factory=list)


# Base system prompt
BASE_SYSTEM_PROMPT = """You are an AI assistant for DaVinci Resolve Studio 20.
You can control the video editor through function calls.

IMPORTANT RULES:
1. When the user asks to do something, call the appropriate function(s)
2. You can call multiple functions in sequence to complete complex tasks
3. Always confirm what you did after executing functions
4. If something fails, explain the error and suggest alternatives
5. Be conversational and helpful
6. You are PAGE-AWARE - you know which page the user is on and tailor your help accordingly

"""

# Page-specific context prompts
PAGE_CONTEXTS = {
    "media": """
CURRENT PAGE: Media Page
You're helping with media management. Available actions:
- Import media files and folders
- Organize clips into bins
- Preview and manage media pool content
- Set clip metadata and properties

Suggest organizing media into bins, reviewing footage, or importing new files.
""",

    "cut": """
CURRENT PAGE: Cut Page  
You're helping with fast editing. Available actions:
- Quick assembly editing
- Source/timeline navigation
- Fast trimming and cutting
- Review edits rapidly

This page is optimized for speed. Help with rapid assembly edits.
""",

    "edit": """
CURRENT PAGE: Edit Page
You're helping with timeline editing. Available actions:
- Add/remove clips from timeline
- Trim and move clips
- Add transitions and effects
- Add markers and organize timeline
- Timeline management (create, delete, switch)

Help with detailed timeline editing, clip arrangement, and effects.
""",

    "fusion": """
CURRENT PAGE: Fusion Page
You're helping with visual effects and motion graphics. Available actions:
- Create and connect nodes
- Add effects: blur, glow, color correction, masks
- Composite multiple layers
- Create motion graphics and titles
- Keyframe animations

FUSION NODE TIPS:
- MediaIn → brings footage into Fusion
- MediaOut → sends result back to timeline
- Merge → combines two images (background + foreground)
- Transform → move, scale, rotate
- Blur → various blur types
- ColorCorrector → detailed color adjustments
- Text+ → animated text and titles
- Mask → create shape masks
- Tracker → motion tracking

I can help you build node trees for effects. Describe what visual effect you want!
""",

    "color": """
CURRENT PAGE: Color Page
You're helping with color grading. Available actions:
- Apply color presets (netflix, teal-orange, cyberpunk, music-video, moody-dark, vintage, bleach-bypass, documentary)
- Apply LUTs
- Adjust color wheels (lift, gamma, gain, offset)
- Add color correction nodes
- Copy grades between clips
- Power windows and masks
- Curves adjustments

COLOR GRADING TIPS:
- Start with balancing the shot (fix white balance, exposure)
- Use lift/gamma/gain for shadows/midtones/highlights
- Apply a look or LUT for style
- Use Power Windows for selective corrections
- Node structure: Balance → Contrast → Look → Finishing

Tell me what mood or look you want, and I'll help achieve it!
""",

    "fairlight": """
CURRENT PAGE: Fairlight Page
You're helping with audio editing and mixing. Available actions:
- Adjust track volumes and panning
- Add audio effects (EQ, compression, reverb)
- Edit audio clips and crossfades
- Analyze audio for beats and rhythm
- Duck music under voiceover
- Audio automation

AUDIO TIPS:
- Dialogue should be around -12 to -6 dB
- Music bed typically -18 to -24 dB under dialogue
- Use EQ to remove muddy frequencies (200-400 Hz)
- Add light compression to even out levels
- Use limiter on master to prevent clipping

I can help with:
- Mixing dialogue, music, and sound effects
- Creating ducking automation
- Beat detection for music editing
- Audio cleanup and enhancement

What audio task can I help you with?
""",

    "deliver": """
CURRENT PAGE: Deliver Page
You're helping with rendering and export. Available actions:
- Add render jobs to queue
- Configure render settings
- Start/stop rendering
- Export in various formats

EXPORT TIPS:
- YouTube: H.264, 1080p or 4K, ~15-20 Mbps
- Social Media: H.264, match platform specs
- Archive: ProRes 422 or DNxHR for quality
- Web: H.264 for compatibility

I can help configure render settings and manage the render queue.
"""
}

# Full capabilities list
CAPABILITIES_PROMPT = """
ALL AVAILABLE TOOLS:

**Project Management:**
- open_project, create_project, save_project, close_project

**Timeline Operations:**
- create_timeline, create_empty_timeline, delete_timeline
- add_marker, add_beat_markers, add_scene_markers
- add_clip_to_timeline, add_clip_from_bin, add_all_bin_clips_to_timeline

**Media Pool:**
- import_media, list_bin_clips, create_bin, get_audio_clip_path, get_video_clip_path

**Color Grading:**
- apply_color_preset, list_color_presets, apply_lut

**Audio:**
- analyze_audio_beats, add_beat_markers, duck_audio_under_voiceover

**Rendering:**
- add_to_render_queue, start_render, clear_render_queue

**Navigation:**
- switch_page (media, cut, edit, fusion, color, fairlight, deliver)
- get_current_page - detect current page
"""


def build_system_prompt(page: str = None, context: dict = None) -> str:
    """
    Build a context-aware system prompt based on current page.
    
    Args:
        page: Current DaVinci Resolve page
        context: Additional context (timeline info, project, etc.)
        
    Returns:
        Complete system prompt string
    """
    prompt_parts = [BASE_SYSTEM_PROMPT]
    
    # Add page-specific context
    if page and page in PAGE_CONTEXTS:
        prompt_parts.append(PAGE_CONTEXTS[page])
    else:
        prompt_parts.append("""
CURRENT PAGE: Unknown
I'll help you with general DaVinci Resolve tasks. You can switch pages using switch_page.
""")
    
    # Add context information
    if context:
        context_str = "\nCURRENT STATE:\n"
        if context.get("project"):
            context_str += f"- Project: {context['project']}\n"
        if context.get("timeline"):
            context_str += f"- Timeline: {context['timeline']}\n"
        if context.get("video_tracks"):
            context_str += f"- Video Tracks: {context['video_tracks']}\n"
        if context.get("audio_tracks"):
            context_str += f"- Audio Tracks: {context['audio_tracks']}\n"
        prompt_parts.append(context_str)
    
    # Add full capabilities
    prompt_parts.append(CAPABILITIES_PROMPT)
    
    return "\n".join(prompt_parts)


# Default prompt for initialization
SYSTEM_PROMPT = build_system_prompt()


class GeminiClient:
    """Client for Google Gemini API with function calling."""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-1.5-flash",
        tool_executor: Optional[Callable] = None,
        context_provider: Optional[Callable] = None
    ):
        """
        Initialize the Gemini client.
        
        Args:
            api_key: Gemini API key (uses env var if not provided)
            model: Model to use
            tool_executor: Function to call when AI wants to execute a tool
            context_provider: Function that returns current page context dict
        """
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.model_name = model
        self.tool_executor = tool_executor
        self.context_provider = context_provider
        self.conversation_history: List[Message] = []
        self.model = None
        self.chat = None
        self.tool_declarations = None
        self.current_page = None
        
        if not _GEMINI_AVAILABLE:
            raise ImportError("google-generativeai not installed. Run: pip install google-generativeai")
        
        if not self.api_key:
            raise ValueError("No API key provided. Set GEMINI_API_KEY environment variable.")
    
    def initialize(self, tool_definitions: List[Dict] = None):
        """
        Initialize the Gemini model with tools.
        
        Args:
            tool_definitions: List of tool definitions for function calling
        """
        genai.configure(api_key=self.api_key)
        
        # Store tool definitions for later use
        self.tool_declarations = None
        
        # Create function declarations from tool definitions
        if tool_definitions:
            function_declarations = []
            for tool_def in tool_definitions:
                try:
                    fd = FunctionDeclaration(
                        name=tool_def['name'],
                        description=tool_def.get('description', ''),
                        parameters=tool_def.get('parameters', {})
                    )
                    function_declarations.append(fd)
                except Exception as e:
                    logger.warning(f"Failed to create function declaration for {tool_def.get('name')}: {e}")
            
            if function_declarations:
                self.tool_declarations = [Tool(function_declarations=function_declarations)]
        
        # Get initial context
        context = None
        page = None
        if self.context_provider:
            try:
                context = self.context_provider()
                page = context.get("page")
                self.current_page = page
            except Exception as e:
                logger.warning(f"Could not get initial context: {e}")
        
        # Build context-aware system prompt
        system_prompt = build_system_prompt(page, context)
        
        # Create the model
        self.model = genai.GenerativeModel(
            model_name=self.model_name,
            system_instruction=system_prompt,
            tools=self.tool_declarations
        )
        
        # Start a chat session
        self.chat = self.model.start_chat(history=[])
        
        logger.info(f"Initialized Gemini client with model {self.model_name}")
        if tool_definitions:
            logger.info(f"Loaded {len(tool_definitions)} tool definitions")
        if page:
            logger.info(f"Initial page context: {page}")
    
    def update_context(self):
        """
        Update the model with fresh context from DaVinci Resolve.
        Call this before sending messages to ensure page-aware responses.
        """
        if not self.context_provider:
            return
        
        try:
            context = self.context_provider()
            new_page = context.get("page")
            
            # Only rebuild if page changed
            if new_page != self.current_page:
                logger.info(f"Page changed: {self.current_page} -> {new_page}")
                self.current_page = new_page
                
                # Rebuild the model with new context
                system_prompt = build_system_prompt(new_page, context)
                
                self.model = genai.GenerativeModel(
                    model_name=self.model_name,
                    system_instruction=system_prompt,
                    tools=self.tool_declarations
                )
                
                # Preserve conversation history
                self.chat = self.model.start_chat(history=[])
                
        except Exception as e:
            logger.warning(f"Could not update context: {e}")
    
    def send_message(self, user_message: str) -> str:
        """
        Send a message and get a response.
        
        Args:
            user_message: The user's message
            
        Returns:
            The assistant's response text
        """
        if not self.chat:
            raise RuntimeError("Client not initialized. Call initialize() first.")
        
        # Update context before sending (detects page changes)
        self.update_context()
        
        # Add to history
        self.conversation_history.append(Message(role="user", content=user_message))
        
        # Add page context to message if available
        context_prefix = ""
        if self.current_page:
            context_prefix = f"[Currently on {self.current_page.upper()} page] "
        
        try:
            # Send message with context
            full_message = context_prefix + user_message
            response = self.chat.send_message(full_message)
            
            # Process the response
            return self._process_response(response)
            
        except Exception as e:
            error_msg = f"Error communicating with Gemini: {e}"
            logger.error(error_msg)
            return error_msg
    
    def _process_response(self, response) -> str:
        """Process a Gemini response, handling function calls."""
        result_parts = []
        
        for candidate in response.candidates:
            for part in candidate.content.parts:
                # Check for function call
                if hasattr(part, 'function_call') and part.function_call:
                    fc = part.function_call
                    tool_name = fc.name
                    tool_args = dict(fc.args) if fc.args else {}
                    
                    logger.info(f"Function call: {tool_name}({tool_args})")
                    
                    # Execute the tool if we have an executor
                    if self.tool_executor:
                        try:
                            tool_result = self.tool_executor(tool_name, tool_args)
                            result_parts.append(f"[Executed {tool_name}]: {tool_result}")
                            
                            # Send the result back to Gemini for a natural response
                            followup = self.chat.send_message(
                                f"I executed {tool_name} and got this result: {tool_result}. "
                                "Please summarize what happened for the user."
                            )
                            
                            # Get the text from the followup
                            for cand in followup.candidates:
                                for p in cand.content.parts:
                                    if hasattr(p, 'text') and p.text:
                                        result_parts.append(p.text)
                            
                        except Exception as e:
                            error_msg = f"Error executing {tool_name}: {e}"
                            logger.error(error_msg)
                            result_parts.append(error_msg)
                    else:
                        result_parts.append(f"[Would call {tool_name} with {tool_args}]")
                
                # Regular text response
                elif hasattr(part, 'text') and part.text:
                    result_parts.append(part.text)
        
        response_text = "\n".join(result_parts) if result_parts else "I couldn't generate a response."
        
        # Add to history
        self.conversation_history.append(Message(role="assistant", content=response_text))
        
        return response_text
    
    def clear_history(self):
        """Clear the conversation history."""
        self.conversation_history = []
        if self.model:
            self.chat = self.model.start_chat(history=[])
        logger.info("Cleared conversation history")
    
    def get_history(self) -> List[Dict]:
        """Get the conversation history as a list of dicts."""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.conversation_history
        ]


def is_gemini_available() -> bool:
    """Check if Gemini API is available."""
    return _GEMINI_AVAILABLE and bool(
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    )
