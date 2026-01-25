#!/usr/bin/env python3
"""
Clip Analyzer Module for DaVinci Resolve MCP Server

AI-powered clip analysis using Google Gemini or OpenAI.
Inspired by Metafootage project (https://github.com/WDegan/metafootage-davinci-resolve)

Analyzes video clips to generate:
- Cinematic descriptions (action, setting, lighting, camera feel)
- Keywords and tags
- Scene classification
"""

import base64
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("autonomous.clip_analyzer")

# Check for API availability
_GEMINI_AVAILABLE = False
_OPENAI_AVAILABLE = False

try:
    import google.generativeai as genai
    _GEMINI_AVAILABLE = True
except ImportError:
    pass

try:
    import openai
    _OPENAI_AVAILABLE = True
except ImportError:
    pass


@dataclass
class ClipAnalysis:
    """Result of AI clip analysis."""
    clip_name: str
    description: str
    keywords: List[str]
    scene_type: str  # e.g., "action", "dialogue", "establishing", "transition"
    mood: str
    lighting: str
    camera_movement: str
    colors: List[str]
    subjects: List[str]
    analyzed_at: str = field(default_factory=lambda: datetime.now().isoformat())
    model_used: str = ""
    frames_analyzed: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'clip_name': self.clip_name,
            'description': self.description,
            'keywords': self.keywords,
            'scene_type': self.scene_type,
            'mood': self.mood,
            'lighting': self.lighting,
            'camera_movement': self.camera_movement,
            'colors': self.colors,
            'subjects': self.subjects,
            'analyzed_at': self.analyzed_at,
            'model_used': self.model_used,
            'frames_analyzed': self.frames_analyzed
        }
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def extract_frames(
    video_path: str,
    num_frames: int = 5,
    output_dir: Optional[Path] = None
) -> List[Path]:
    """
    Extract representative frames from a video using FFmpeg.
    
    Args:
        video_path: Path to video file
        num_frames: Number of frames to extract (3, 5, or 7 recommended)
        output_dir: Directory to save frames (uses temp dir if None)
    
    Returns:
        List of paths to extracted frame images
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    
    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="clip_frames_"))
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get video duration
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    
    try:
        result = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        duration = float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        logger.warning(f"Could not get duration, using 10s default: {e}")
        duration = 10.0
    
    # Calculate frame timestamps (evenly distributed)
    if num_frames == 1:
        timestamps = [duration / 2]
    else:
        step = duration / (num_frames + 1)
        timestamps = [step * (i + 1) for i in range(num_frames)]
    
    frames = []
    for i, ts in enumerate(timestamps):
        output_path = output_dir / f"frame_{i:02d}.jpg"
        
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(ts),
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",  # High quality JPEG
            str(output_path)
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            if output_path.exists():
                frames.append(output_path)
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to extract frame at {ts}s: {e}")
    
    return frames


def encode_image_base64(image_path: Path) -> str:
    """Encode image to base64 string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_analysis_prompt() -> str:
    """Get the prompt for clip analysis."""
    return """Analyze this video frame(s) for a video editor. Provide:

1. DESCRIPTION: A cinematic description of what's happening (2-3 sentences focusing on action, setting, and visual style)

2. KEYWORDS: 5-10 relevant keywords for searching/organizing

3. SCENE_TYPE: One of: establishing, action, dialogue, transition, montage, close-up, wide-shot, b-roll

4. MOOD: The emotional tone (e.g., tense, joyful, melancholic, energetic, calm)

5. LIGHTING: Describe the lighting (e.g., natural daylight, golden hour, neon, high-key, low-key, dramatic shadows)

6. CAMERA_MOVEMENT: If apparent (e.g., static, pan, tilt, tracking, handheld, drone)

7. COLORS: 3-5 dominant colors in the frame

8. SUBJECTS: Main subjects/objects visible

Respond in JSON format:
{
    "description": "...",
    "keywords": ["...", "..."],
    "scene_type": "...",
    "mood": "...",
    "lighting": "...",
    "camera_movement": "...",
    "colors": ["...", "..."],
    "subjects": ["...", "..."]
}"""


def analyze_with_gemini(
    frames: List[Path],
    api_key: str,
    model: str = "gemini-1.5-flash"
) -> Dict[str, Any]:
    """
    Analyze frames using Google Gemini.
    
    Args:
        frames: List of frame image paths
        api_key: Gemini API key
        model: Model to use (gemini-1.5-flash or gemini-1.5-pro)
    
    Returns:
        Analysis result dictionary
    """
    if not _GEMINI_AVAILABLE:
        raise ImportError("google-generativeai not installed. Run: pip install google-generativeai")
    
    genai.configure(api_key=api_key)
    model_instance = genai.GenerativeModel(model)
    
    # Prepare content with images
    content = [get_analysis_prompt()]
    
    for frame_path in frames:
        with open(frame_path, "rb") as f:
            image_data = f.read()
        content.append({
            "mime_type": "image/jpeg",
            "data": image_data
        })
    
    response = model_instance.generate_content(content)
    
    # Parse JSON from response
    response_text = response.text
    
    # Try to extract JSON from response
    try:
        # Handle markdown code blocks
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0]
        else:
            json_str = response_text
        
        return json.loads(json_str.strip())
    except json.JSONDecodeError:
        logger.warning(f"Could not parse JSON, returning raw response")
        return {
            "description": response_text,
            "keywords": [],
            "scene_type": "unknown",
            "mood": "unknown",
            "lighting": "unknown",
            "camera_movement": "unknown",
            "colors": [],
            "subjects": []
        }


def analyze_with_openai(
    frames: List[Path],
    api_key: str,
    model: str = "gpt-4o-mini"
) -> Dict[str, Any]:
    """
    Analyze frames using OpenAI GPT-4 Vision.
    
    Args:
        frames: List of frame image paths
        api_key: OpenAI API key
        model: Model to use (gpt-4o, gpt-4o-mini, gpt-4-turbo)
    
    Returns:
        Analysis result dictionary
    """
    if not _OPENAI_AVAILABLE:
        raise ImportError("openai not installed. Run: pip install openai")
    
    client = openai.OpenAI(api_key=api_key)
    
    # Build message content with images
    content = [{"type": "text", "text": get_analysis_prompt()}]
    
    for frame_path in frames:
        base64_image = encode_image_base64(frame_path)
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{base64_image}",
                "detail": "low"  # Use low detail to reduce cost
            }
        })
    
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=1000
    )
    
    response_text = response.choices[0].message.content
    
    # Parse JSON from response
    try:
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0]
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0]
        else:
            json_str = response_text
        
        return json.loads(json_str.strip())
    except json.JSONDecodeError:
        logger.warning(f"Could not parse JSON, returning raw response")
        return {
            "description": response_text,
            "keywords": [],
            "scene_type": "unknown",
            "mood": "unknown",
            "lighting": "unknown",
            "camera_movement": "unknown",
            "colors": [],
            "subjects": []
        }


def analyze_clip(
    video_path: str,
    clip_name: str = None,
    num_frames: int = 5,
    provider: str = "gemini",
    api_key: str = None,
    model: str = None
) -> Optional[ClipAnalysis]:
    """
    Analyze a video clip using AI.
    
    Args:
        video_path: Path to video file
        clip_name: Name of the clip (uses filename if None)
        num_frames: Number of frames to extract (3, 5, or 7)
        provider: AI provider - 'gemini' or 'openai'
        api_key: API key (uses environment variable if None)
        model: Model to use (uses default for provider if None)
    
    Returns:
        ClipAnalysis object or None if analysis fails
    """
    video_path = Path(video_path)
    if not video_path.exists():
        logger.error(f"Video not found: {video_path}")
        return None
    
    if clip_name is None:
        clip_name = video_path.name
    
    # Get API key from environment if not provided
    if api_key is None:
        if provider == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        elif provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY")
    
    if not api_key:
        logger.error(f"No API key provided for {provider}")
        return None
    
    # Set default models
    if model is None:
        model = "gemini-1.5-flash" if provider == "gemini" else "gpt-4o-mini"
    
    try:
        # Extract frames
        logger.info(f"Extracting {num_frames} frames from: {video_path}")
        with tempfile.TemporaryDirectory() as td:
            frames = extract_frames(video_path, num_frames, Path(td))
            
            if not frames:
                logger.error("No frames extracted")
                return None
            
            logger.info(f"Analyzing {len(frames)} frames with {provider}/{model}")
            
            # Analyze with chosen provider
            if provider == "gemini":
                result = analyze_with_gemini(frames, api_key, model)
            elif provider == "openai":
                result = analyze_with_openai(frames, api_key, model)
            else:
                logger.error(f"Unknown provider: {provider}")
                return None
        
        return ClipAnalysis(
            clip_name=clip_name,
            description=result.get("description", ""),
            keywords=result.get("keywords", []),
            scene_type=result.get("scene_type", "unknown"),
            mood=result.get("mood", "unknown"),
            lighting=result.get("lighting", "unknown"),
            camera_movement=result.get("camera_movement", "unknown"),
            colors=result.get("colors", []),
            subjects=result.get("subjects", []),
            model_used=f"{provider}/{model}",
            frames_analyzed=len(frames)
        )
        
    except Exception as e:
        logger.error(f"Clip analysis failed: {e}")
        return None


def is_gemini_available() -> bool:
    """Check if Gemini API is available."""
    return _GEMINI_AVAILABLE and bool(
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    )


def is_openai_available() -> bool:
    """Check if OpenAI API is available."""
    return _OPENAI_AVAILABLE and bool(os.environ.get("OPENAI_API_KEY"))
