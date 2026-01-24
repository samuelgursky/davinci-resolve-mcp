"""
Cinematic Pipeline - Orchestrates the full autonomous editing workflow.

Milestone 8 implementation: Multi-variant pipeline.

This is the main entry point that coordinates:
- Video analysis (Milestone 3)
- Beat analysis (Milestone 5)
- Audio ducking (Milestone 6)
- Decision engine / scene selection (Milestone 7)
- Prompt pack generation (Milestone 4)
- Multi-variant generation (Milestone 8)
- Auto-editing in Resolve (Milestone 1)
"""

import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

from .config import PipelineConfig, AudioMode
from .schemas import EditPlan
from .decision_engine import DecisionEngine, VariantConfig, generate_edit_plan
from .prompt_generator import PromptGenerator
from .beat_analyzer import BeatAnalyzer, BeatAnalysis, is_librosa_available
from .audio_processor import AudioProcessor, DuckingConfig, is_ffmpeg_available

logger = logging.getLogger("autonomous.pipeline")


@dataclass
class VariantOutput:
    """Output files for a single variant."""

    variant_name: str
    output_dir: Path

    plan_path: Optional[Path] = None
    suno_prompt_md: Optional[Path] = None
    suno_prompt_json: Optional[Path] = None
    voiceover_md: Optional[Path] = None
    voiceover_json: Optional[Path] = None
    beats_path: Optional[Path] = None
    ducked_music_path: Optional[Path] = None

    success: bool = False
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant_name": self.variant_name,
            "output_dir": str(self.output_dir),
            "plan_path": str(self.plan_path) if self.plan_path else None,
            "suno_prompt_md": str(self.suno_prompt_md) if self.suno_prompt_md else None,
            "suno_prompt_json": str(self.suno_prompt_json) if self.suno_prompt_json else None,
            "voiceover_md": str(self.voiceover_md) if self.voiceover_md else None,
            "voiceover_json": str(self.voiceover_json) if self.voiceover_json else None,
            "beats_path": str(self.beats_path) if self.beats_path else None,
            "ducked_music_path": str(self.ducked_music_path) if self.ducked_music_path else None,
            "success": self.success,
            "errors": self.errors,
        }


@dataclass
class PipelineResult:
    """Result of pipeline execution."""

    success: bool = False
    variants_generated: List[str] = field(default_factory=list)
    variant_outputs: Dict[str, VariantOutput] = field(default_factory=dict)
    timelines_created: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # File paths
    candidates_path: Optional[Path] = None
    beats_path: Optional[Path] = None
    ducked_music_path: Optional[Path] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "variants_generated": self.variants_generated,
            "variant_outputs": {k: v.to_dict() for k, v in self.variant_outputs.items()},
            "timelines_created": self.timelines_created,
            "errors": self.errors,
            "warnings": self.warnings,
            "candidates_path": str(self.candidates_path) if self.candidates_path else None,
            "beats_path": str(self.beats_path) if self.beats_path else None,
            "ducked_music_path": str(self.ducked_music_path) if self.ducked_music_path else None,
        }


class CinematicPipeline:
    """
    Orchestrates the full autonomous cinematic editing pipeline.

    Workflow:
    1. Load candidates.json (from prior analyze command)
    2. Analyze music for beats (if provided, Milestone 5)
    3. Create ducked music (if music + voice provided, Milestone 6)
    4. For each variant (Milestone 8):
       a. Generate edit plan with decision engine (Milestone 7)
       b. Apply beat snapping (Milestone 5)
       c. Generate prompt packs (Milestone 4)
       d. Save all outputs to work/variants/<name>/
    5. Optionally execute in Resolve (if --execute)
    """

    VARIANT_PRESETS = {
        "trailer": VariantConfig.trailer,
        "balanced": VariantConfig.balanced,
        "atmo": VariantConfig.atmospheric,
        "atmospheric": VariantConfig.atmospheric,
    }

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig.from_env()

        # Components
        self.decision_engine = DecisionEngine(work_dir=self.config.work_dir)
        self.prompt_generator = PromptGenerator(work_dir=self.config.work_dir)
        self.beat_analyzer = BeatAnalyzer() if is_librosa_available() else None
        self.audio_processor = AudioProcessor(work_dir=self.config.work_dir / "audio")

        # State
        self.candidates: Optional[Dict[str, Any]] = None
        self.beats: Optional[BeatAnalysis] = None
        self.ducked_music_path: Optional[Path] = None

    def run_all(
        self,
        variants: List[str] = None,
        music_path: Optional[str] = None,
        voice_path: Optional[str] = None,
        execute: bool = False,
        target_duration_sec: Optional[float] = None,
    ) -> PipelineResult:
        """
        Run the full multi-variant pipeline.

        Args:
            variants: List of variant names (trailer/balanced/atmo)
            music_path: Optional path to music file
            voice_path: Optional path to voiceover file
            execute: If True, create timelines in Resolve
            target_duration_sec: Optional target duration override

        Returns:
            PipelineResult with all outputs
        """
        result = PipelineResult()

        # Default variants
        if not variants:
            variants = self.config.features.default_variants.split(",")

        logger.info(f"Running pipeline for variants: {variants}")

        try:
            # Step 1: Load candidates
            candidates_path = self.config.candidates_path
            if not candidates_path.exists():
                result.errors.append(f"Candidates not found: {candidates_path}")
                result.errors.append("Run 'analyze' command first")
                return result

            self.candidates = self.decision_engine.load_candidates(candidates_path)
            result.candidates_path = candidates_path
            logger.info(f"Loaded candidates from: {candidates_path}")

            # Step 2: Analyze music for beats (Milestone 5)
            if music_path and self.config.features.beat_sync_enabled:
                self.beats = self._analyze_beats(music_path)
                if self.beats:
                    result.beats_path = self.config.beats_path

            # Step 3: Create ducked music (Milestone 6)
            if music_path and voice_path and self.config.features.ducking_enabled:
                self.ducked_music_path = self._create_ducked_music(music_path, voice_path)
                if self.ducked_music_path:
                    result.ducked_music_path = self.ducked_music_path

            # Step 4: Generate each variant
            for variant_name in variants:
                variant_name = variant_name.strip().lower()
                logger.info(f"Generating variant: {variant_name}")

                variant_output = self._generate_variant(
                    variant_name=variant_name,
                    target_duration_sec=target_duration_sec,
                )

                result.variant_outputs[variant_name] = variant_output

                if variant_output.success:
                    result.variants_generated.append(variant_name)
                else:
                    result.errors.extend(variant_output.errors)

            # Step 5: Execute in Resolve (if requested)
            if execute and result.variants_generated:
                timelines = self._execute_variants(result.variants_generated)
                result.timelines_created = timelines

            result.success = len(result.variants_generated) > 0

        except FileNotFoundError as e:
            result.errors.append(str(e))
            logger.error(f"Pipeline failed: {e}")
        except Exception as e:
            result.errors.append(f"Unexpected error: {e}")
            logger.exception(f"Pipeline failed: {e}")

        return result

    def _analyze_beats(self, music_path: str) -> Optional[BeatAnalysis]:
        """Analyze music file for beats."""
        if not self.beat_analyzer:
            logger.warning("librosa not available - beat sync disabled")
            return None

        if not Path(music_path).exists():
            logger.warning(f"Music file not found: {music_path}")
            return None

        try:
            logger.info(f"Analyzing beats: {music_path}")
            beats = self.beat_analyzer.analyze(music_path)

            if beats:
                beats.save(self.config.beats_path)
                logger.info(f"Beats saved: {len(beats.beats_sec)} beats, {beats.bpm:.1f} BPM")

            return beats

        except Exception as e:
            logger.warning(f"Beat analysis failed: {e}")
            return None

    def _create_ducked_music(
        self,
        music_path: str,
        voice_path: str,
    ) -> Optional[Path]:
        """Create ducked music file."""
        if not is_ffmpeg_available():
            logger.warning("ffmpeg not available - ducking disabled")
            return None

        if not Path(music_path).exists() or not Path(voice_path).exists():
            logger.warning("Music or voice file not found")
            return None

        try:
            logger.info("Creating ducked music...")

            config = DuckingConfig(
                ducking_db=self.config.features.ducking_db,
                voice_start_sec=self.config.features.voice_start_sec,
            )

            result = self.audio_processor.create_ducked_music(
                music_path=music_path,
                voice_path=voice_path,
                output_path=str(self.config.ducked_music_path),
                config=config,
            )

            if result.success:
                logger.info(f"Ducked music created: {result.output_path}")
                return Path(result.output_path)
            else:
                logger.warning(f"Ducking failed: {result.error_message}")
                return None

        except Exception as e:
            logger.warning(f"Ducking failed: {e}")
            return None

    def _generate_variant(
        self,
        variant_name: str,
        target_duration_sec: Optional[float] = None,
    ) -> VariantOutput:
        """Generate a single variant."""
        # Create variant output directory
        variant_dir = self.config.variant_dir(variant_name)
        variant_dir.mkdir(parents=True, exist_ok=True)

        output = VariantOutput(
            variant_name=variant_name,
            output_dir=variant_dir,
        )

        try:
            # Get variant config
            config_factory = self.VARIANT_PRESETS.get(variant_name)
            if not config_factory:
                output.errors.append(f"Unknown variant: {variant_name}")
                return output

            # Build config with optional duration override
            duration = target_duration_sec or self.config.features.target_duration_sec
            variant_config = config_factory(duration)

            # Apply beat sync settings from config
            variant_config.beat_sync_enabled = self.config.features.beat_sync_enabled
            variant_config.beat_snap_tolerance_sec = self.config.features.beat_snap_tolerance_sec
            variant_config.beat_prefer_downbeats = self.config.features.beat_prefer_downbeats

            # Generate edit plan with decision engine
            plan = self.decision_engine.generate_plan(
                candidates=self.candidates,
                config=variant_config,
                beats=self.beats,
                timeline_name=f"AUTO_{variant_name.upper()}",
            )

            # Save plan
            plan_path = variant_dir / "plan.json"
            plan.save(plan_path)
            output.plan_path = plan_path

            # Generate prompt packs
            prompts_dir = variant_dir / "prompts"
            prompts_dir.mkdir(exist_ok=True)

            # Generate music prompt
            music_prompt = self.prompt_generator.generate_music_prompt(self.candidates)
            music_prompt.duration_sec = duration  # Match variant duration

            suno_md = prompts_dir / "suno_prompt.md"
            suno_json = prompts_dir / "suno_prompt.json"

            with open(suno_md, "w", encoding="utf-8") as f:
                f.write(music_prompt.to_markdown())
            output.suno_prompt_md = suno_md

            with open(suno_json, "w", encoding="utf-8") as f:
                f.write(music_prompt.to_json())
            output.suno_prompt_json = suno_json

            # Generate voiceover script
            voiceover = self.prompt_generator.generate_voiceover_script(self.candidates)

            vo_md = prompts_dir / "voiceover_script.md"
            vo_json = prompts_dir / "voiceover_script.json"

            with open(vo_md, "w", encoding="utf-8") as f:
                f.write(voiceover.to_markdown())
            output.voiceover_md = vo_md

            with open(vo_json, "w", encoding="utf-8") as f:
                f.write(voiceover.to_json())
            output.voiceover_json = vo_json

            # Copy beats if available
            if self.beats:
                beats_copy = variant_dir / "beats.json"
                self.beats.save(beats_copy)
                output.beats_path = beats_copy

            # Copy ducked music if available
            if self.ducked_music_path and self.ducked_music_path.exists():
                ducked_copy = variant_dir / "music_ducked.wav"
                shutil.copy2(self.ducked_music_path, ducked_copy)
                output.ducked_music_path = ducked_copy

            output.success = True
            logger.info(f"Variant {variant_name} generated: {variant_dir}")

        except Exception as e:
            output.errors.append(f"Failed to generate {variant_name}: {e}")
            logger.exception(f"Variant {variant_name} failed: {e}")

        return output

    def _execute_variants(self, variants: List[str]) -> List[str]:
        """Execute variants in Resolve (create timelines)."""
        timelines_created = []

        try:
            # Import here to avoid import errors when Resolve not running
            from .auto_editor import AutoEditor, ResolveConnectionError

            editor = AutoEditor(self.config)
            editor.connect()

            for variant_name in variants:
                variant_dir = self.config.variant_dir(variant_name)
                plan_path = variant_dir / "plan.json"

                if not plan_path.exists():
                    logger.warning(f"No plan found for {variant_name}")
                    continue

                try:
                    plan = EditPlan.load(plan_path)
                    executed_plan = editor.execute_plan(plan)

                    # Save updated plan with execution log
                    executed_plan.save(plan_path)

                    if executed_plan.executed:
                        timelines_created.append(executed_plan.timeline.name)
                        logger.info(f"Created timeline: {executed_plan.timeline.name}")

                except Exception as e:
                    logger.error(f"Failed to execute {variant_name}: {e}")

        except ImportError:
            logger.error("Could not import AutoEditor")
        except Exception as e:
            logger.error(f"Execution failed: {e}")

        return timelines_created

    def generate_plan(
        self,
        variant: str = "balanced",
        target_duration_sec: Optional[float] = None,
        music_path: Optional[str] = None,
    ) -> Optional[EditPlan]:
        """
        Generate a single edit plan.

        Convenience method for `plan` CLI command.
        """
        # Load candidates
        if not self.config.candidates_path.exists():
            logger.error("Candidates not found. Run 'analyze' first.")
            return None

        self.candidates = self.decision_engine.load_candidates()

        # Analyze beats if music provided
        if music_path and self.config.features.beat_sync_enabled:
            self.beats = self._analyze_beats(music_path)

        # Get variant config
        config_factory = self.VARIANT_PRESETS.get(variant.lower())
        if not config_factory:
            logger.error(f"Unknown variant: {variant}")
            return None

        duration = target_duration_sec or self.config.features.target_duration_sec
        variant_config = config_factory(duration)

        # Apply beat sync settings
        variant_config.beat_sync_enabled = self.config.features.beat_sync_enabled
        variant_config.beat_snap_tolerance_sec = self.config.features.beat_snap_tolerance_sec

        # Generate plan
        plan = self.decision_engine.generate_plan(
            candidates=self.candidates,
            config=variant_config,
            beats=self.beats,
        )

        return plan


def run_pipeline(
    variants: List[str] = None,
    music_path: Optional[str] = None,
    voice_path: Optional[str] = None,
    execute: bool = False,
    target_duration_sec: Optional[float] = None,
) -> PipelineResult:
    """
    Convenience function to run the full pipeline.

    Args:
        variants: List of variant names
        music_path: Optional music file path
        voice_path: Optional voiceover file path
        execute: If True, create timelines in Resolve
        target_duration_sec: Optional target duration

    Returns:
        PipelineResult
    """
    pipeline = CinematicPipeline()
    return pipeline.run_all(
        variants=variants,
        music_path=music_path,
        voice_path=voice_path,
        execute=execute,
        target_duration_sec=target_duration_sec,
    )
