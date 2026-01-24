"""
Auto Editor - Core editing operations for DaVinci Resolve.

Milestone 1: Deterministic clip sequencing and rendering.
"""

import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autonomous.config import PipelineConfig
from autonomous.schemas import EditPlan, ClipReference, AudioReference, TimelineSettings

logger = logging.getLogger("autonomous.auto_editor")


class ResolveConnectionError(Exception):
    """Raised when unable to connect to DaVinci Resolve."""
    pass


class AutoEditor:
    """
    Autonomous editor that interfaces with DaVinci Resolve.

    Handles timeline creation, clip placement, audio import, and rendering.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.resolve = None
        self.project = None
        self.media_pool = None
        self._connected = False

    def connect(self) -> bool:
        """
        Connect to DaVinci Resolve.

        Returns True if connected, raises ResolveConnectionError otherwise.
        """
        if self._connected and self.resolve:
            return True

        try:
            # Setup environment and import Resolve scripting
            from utils.platform import setup_environment
            setup_environment()

            import DaVinciResolveScript as dvr_script
            self.resolve = dvr_script.scriptapp("Resolve")

            if not self.resolve:
                raise ResolveConnectionError(
                    "Could not connect to DaVinci Resolve. "
                    "Make sure Resolve is running."
                )

            project_manager = self.resolve.GetProjectManager()
            if not project_manager:
                raise ResolveConnectionError("Failed to get Project Manager")

            self.project = project_manager.GetCurrentProject()
            if not self.project:
                raise ResolveConnectionError("No project currently open in Resolve")

            self.media_pool = self.project.GetMediaPool()
            if not self.media_pool:
                raise ResolveConnectionError("Failed to get Media Pool")

            self._connected = True
            logger.info(f"Connected to project: {self.project.GetName()}")
            return True

        except ImportError as e:
            raise ResolveConnectionError(
                f"Failed to import DaVinci Resolve scripting module: {e}"
            )
        except Exception as e:
            raise ResolveConnectionError(f"Connection error: {e}")

    def disconnect(self) -> None:
        """Disconnect from Resolve."""
        self.resolve = None
        self.project = None
        self.media_pool = None
        self._connected = False

    def get_media_pool_clips(self, bin_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get all clips from media pool.

        Args:
            bin_name: Optional specific bin to get clips from.
                     If None, gets clips from root folder.

        Returns:
            List of clip info dictionaries.
        """
        self.connect()

        root_folder = self.media_pool.GetRootFolder()
        if not root_folder:
            logger.error("Failed to get root folder")
            return []

        # Get target folder
        target_folder = root_folder
        if bin_name:
            folders = root_folder.GetSubFolderList() or []
            for folder in folders:
                if folder and folder.GetName() == bin_name:
                    target_folder = folder
                    break
            else:
                logger.warning(f"Bin '{bin_name}' not found, using root folder")

        clips = target_folder.GetClipList() or []
        clip_info_list = []

        for clip in clips:
            if not clip:
                continue

            props = clip.GetClipProperty() or {}
            clip_info = {
                "name": clip.GetName(),
                "type": props.get("Type", "Unknown"),
                "duration": props.get("Duration", "Unknown"),
                "fps": props.get("FPS", "Unknown"),
                "width": props.get("Resolution Width", props.get("Width")),
                "height": props.get("Resolution Height", props.get("Height")),
                "file_path": props.get("File Path", ""),
                "clip_object": clip,  # Keep reference for later use
            }
            clip_info_list.append(clip_info)

        logger.info(f"Found {len(clip_info_list)} clips in media pool")
        return clip_info_list

    def get_video_clips_only(self, bin_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get only video clips (exclude audio-only files)."""
        all_clips = self.get_media_pool_clips(bin_name)
        video_clips = []

        for clip in all_clips:
            clip_type = clip.get("type", "").lower()
            # Include video, still images; exclude audio-only
            if clip_type in ["video", "still", "video + audio"] or "video" in clip_type:
                video_clips.append(clip)
            elif clip_type not in ["audio"]:
                # Include unknown types that might be video
                if clip.get("width") and clip.get("height"):
                    video_clips.append(clip)

        logger.info(f"Filtered to {len(video_clips)} video clips")
        return video_clips

    def import_media(self, file_path: str) -> Optional[Any]:
        """
        Import a media file into the media pool.

        Returns the imported clip object or None on failure.
        """
        self.connect()

        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return None

        imported = self.media_pool.ImportMedia([file_path])
        if imported and len(imported) > 0:
            logger.info(f"Imported: {os.path.basename(file_path)}")
            return imported[0]
        else:
            logger.error(f"Failed to import: {file_path}")
            return None

    def create_timeline(
        self,
        name: str,
        fps: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> Optional[Any]:
        """
        Create a new empty timeline.

        Returns the timeline object or None on failure.
        """
        self.connect()

        # Check if timeline already exists
        timeline_count = self.project.GetTimelineCount()
        for i in range(1, timeline_count + 1):
            timeline = self.project.GetTimelineByIndex(i)
            if timeline and timeline.GetName() == name:
                logger.warning(f"Timeline '{name}' already exists, using existing")
                self.project.SetCurrentTimeline(timeline)
                return timeline

        # Temporarily set project settings if custom resolution/fps specified
        original_settings = {}
        if fps:
            original_settings["timelineFrameRate"] = self.project.GetSetting("timelineFrameRate")
            self.project.SetSetting("timelineFrameRate", fps)
        if width:
            original_settings["timelineResolutionWidth"] = self.project.GetSetting("timelineResolutionWidth")
            self.project.SetSetting("timelineResolutionWidth", str(width))
        if height:
            original_settings["timelineResolutionHeight"] = self.project.GetSetting("timelineResolutionHeight")
            self.project.SetSetting("timelineResolutionHeight", str(height))

        # Create timeline
        timeline = self.media_pool.CreateEmptyTimeline(name)

        # Restore original settings
        for setting, value in original_settings.items():
            if value:
                self.project.SetSetting(setting, value)

        if timeline:
            self.project.SetCurrentTimeline(timeline)
            logger.info(f"Created timeline: {name}")
            return timeline
        else:
            logger.error(f"Failed to create timeline: {name}")
            return None

    def append_clips_to_timeline(
        self,
        clips: List[Dict[str, Any]],
        timeline: Optional[Any] = None,
    ) -> Tuple[int, int]:
        """
        Append clips to timeline in order.

        Args:
            clips: List of clip info dicts (must have 'clip_object' key)
            timeline: Target timeline (uses current if None)

        Returns:
            Tuple of (successful_count, failed_count)
        """
        self.connect()

        if timeline is None:
            timeline = self.project.GetCurrentTimeline()
            if not timeline:
                logger.error("No current timeline")
                return 0, len(clips)

        success = 0
        failed = 0

        for clip_info in clips:
            clip_obj = clip_info.get("clip_object")
            if not clip_obj:
                logger.warning(f"No clip object for: {clip_info.get('name')}")
                failed += 1
                continue

            result = self.media_pool.AppendToTimeline([clip_obj])
            if result and len(result) > 0:
                logger.debug(f"Appended: {clip_info.get('name')}")
                success += 1
            else:
                logger.warning(f"Failed to append: {clip_info.get('name')}")
                failed += 1

        logger.info(f"Appended {success} clips ({failed} failed)")
        return success, failed

    def add_audio_to_timeline(
        self,
        audio_path: str,
        track: int = 1,
        timeline: Optional[Any] = None,
    ) -> bool:
        """
        Import and add audio file to timeline.

        Args:
            audio_path: Path to audio file
            track: Audio track number (1-based)
            timeline: Target timeline (uses current if None)

        Returns:
            True if successful
        """
        self.connect()

        if timeline is None:
            timeline = self.project.GetCurrentTimeline()
            if not timeline:
                logger.error("No current timeline")
                return False

        # Import the audio file
        audio_clip = self.import_media(audio_path)
        if not audio_clip:
            return False

        # Append to timeline
        result = self.media_pool.AppendToTimeline([audio_clip])
        if result and len(result) > 0:
            logger.info(f"Added audio to timeline: {os.path.basename(audio_path)}")
            return True
        else:
            logger.error(f"Failed to add audio to timeline")
            return False

    def add_to_render_queue(
        self,
        preset_name: str,
        timeline_name: Optional[str] = None,
    ) -> bool:
        """
        Add timeline to render queue with specified preset.

        Returns True if successful.
        """
        self.connect()

        # Switch to deliver page
        self.resolve.OpenPage("deliver")

        timeline = None
        if timeline_name:
            timeline_count = self.project.GetTimelineCount()
            for i in range(1, timeline_count + 1):
                t = self.project.GetTimelineByIndex(i)
                if t and t.GetName() == timeline_name:
                    timeline = t
                    self.project.SetCurrentTimeline(timeline)
                    break
            if not timeline:
                logger.error(f"Timeline not found: {timeline_name}")
                return False
        else:
            timeline = self.project.GetCurrentTimeline()
            timeline_name = timeline.GetName() if timeline else "Unknown"

        # Get render settings interface
        render_settings = self.project.GetRenderSettings()
        if not render_settings:
            logger.error("Failed to get render settings")
            return False

        # Check if preset exists
        project_presets = render_settings.GetRenderPresetList() or []
        system_presets = render_settings.GetSystemPresetList() or []
        all_presets = project_presets + system_presets

        if preset_name not in all_presets:
            logger.error(f"Preset '{preset_name}' not found. Available: {all_presets}")
            return False

        # Apply preset
        if not render_settings.SetRenderSettings({"SelectPreset": preset_name}):
            logger.error(f"Failed to apply preset: {preset_name}")
            return False

        # Add to queue
        result = self.project.AddTimelineToRenderQueue(timeline_name)
        if result:
            logger.info(f"Added '{timeline_name}' to render queue with preset '{preset_name}'")
            return True
        else:
            logger.error("Failed to add to render queue")
            return False

    def start_render(self) -> bool:
        """Start rendering the queue. Returns True if started."""
        self.connect()

        self.resolve.OpenPage("deliver")

        job_list = self.project.GetRenderJobList()
        if not job_list:
            logger.warning("No jobs in render queue")
            return False

        result = self.project.StartRendering()
        if result:
            logger.info(f"Started rendering {len(job_list)} job(s)")
            return True
        else:
            logger.error("Failed to start rendering")
            return False

    def execute_plan(self, plan: EditPlan) -> EditPlan:
        """
        Execute an edit plan in DaVinci Resolve.

        Args:
            plan: The EditPlan to execute

        Returns:
            The plan with updated execution status and log
        """
        plan.log("Starting plan execution")

        try:
            self.connect()
            plan.log(f"Connected to project: {self.project.GetName()}")
            plan.project_name = self.project.GetName()
        except ResolveConnectionError as e:
            plan.log(f"ERROR: {e}")
            return plan

        # Create timeline
        plan.log(f"Creating timeline: {plan.timeline.name}")
        timeline = self.create_timeline(
            name=plan.timeline.name,
            fps=plan.timeline.fps,
            width=plan.timeline.width,
            height=plan.timeline.height,
        )
        if not timeline:
            plan.log("ERROR: Failed to create timeline")
            return plan

        # Get clips from media pool and match with plan
        all_clips = self.get_video_clips_only(self.config.clip_bin_name)
        clip_map = {c["name"]: c for c in all_clips}

        # Sort plan clips by order
        sorted_clips = sorted(plan.clips, key=lambda c: c.order)
        clips_to_append = []

        for clip_ref in sorted_clips:
            if clip_ref.name in clip_map:
                clips_to_append.append(clip_map[clip_ref.name])
            else:
                plan.log(f"WARNING: Clip not found in media pool: {clip_ref.name}")

        # Append clips
        if clips_to_append:
            plan.log(f"Appending {len(clips_to_append)} clips to timeline")
            success, failed = self.append_clips_to_timeline(clips_to_append, timeline)
            plan.log(f"Appended: {success} success, {failed} failed")

        # Add audio tracks
        for audio_ref in plan.audio:
            if audio_ref.source_path and os.path.exists(audio_ref.source_path):
                plan.log(f"Adding audio: {audio_ref.name} to track A{audio_ref.track}")
                if self.add_audio_to_timeline(audio_ref.source_path, audio_ref.track, timeline):
                    plan.log(f"Added audio: {audio_ref.name}")
                else:
                    plan.log(f"WARNING: Failed to add audio: {audio_ref.name}")
            else:
                plan.log(f"WARNING: Audio file not found: {audio_ref.source_path}")

        # Add to render queue if specified
        if plan.render:
            plan.log(f"Adding to render queue with preset: {plan.render.preset_name}")
            if self.add_to_render_queue(plan.render.preset_name, plan.timeline.name):
                plan.log("Added to render queue")
            else:
                plan.log("WARNING: Failed to add to render queue")

        plan.executed = True
        plan.log("Plan execution completed")
        return plan

    def build_plan_from_media_pool(self) -> EditPlan:
        """
        Build an EditPlan from current media pool contents.

        This is the main entry point for Milestone 1.
        """
        self.connect()

        plan = EditPlan()
        plan.description = "Auto-generated from media pool"
        plan.project_name = self.project.GetName()

        # Set timeline settings from config
        plan.timeline = TimelineSettings(
            name=self.config.resolve.default_timeline_name,
            fps=self.config.resolve.timeline_fps,
            width=self.config.resolve.timeline_width,
            height=self.config.resolve.timeline_height,
            start_timecode=self.config.resolve.start_timecode,
        )

        # Get video clips
        video_clips = self.get_video_clips_only(self.config.clip_bin_name)

        # Add clips to plan in order
        for i, clip_info in enumerate(video_clips):
            plan.add_clip(
                name=clip_info["name"],
                source_path=clip_info.get("file_path"),
                order=i,
                track=self.config.resolve.video_track,
                duration_frames=clip_info.get("duration"),
                fps=clip_info.get("fps"),
                width=clip_info.get("width"),
                height=clip_info.get("height"),
            )

        # Add music if provided
        if self.config.music_file_path:
            plan.add_audio(
                name=os.path.basename(self.config.music_file_path),
                source_path=self.config.music_file_path,
                track=self.config.resolve.music_track,
                audio_type="music",
            )

        # Add voiceover if provided
        if self.config.voiceover_file_path:
            plan.add_audio(
                name=os.path.basename(self.config.voiceover_file_path),
                source_path=self.config.voiceover_file_path,
                track=self.config.resolve.voiceover_track,
                audio_type="voiceover",
            )

        # Set render preset
        if self.config.resolve.render_preset_name:
            plan.set_render(
                preset_name=self.config.resolve.render_preset_name,
                output_directory=self.config.resolve.output_directory,
            )

        return plan
