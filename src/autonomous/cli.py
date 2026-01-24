"""
CLI entry point for the autonomous cinematic video editor.

Usage:
    python -m src.autonomous.cli edit --timeline AUTO_V1 --render-preset "H.264 Master"
    python -m src.autonomous.cli edit --music path/to/music.mp3 --voice path/to/voice.mp3
    python -m src.autonomous.cli edit --dry-run
    python -m src.autonomous.cli analyze [--bin BIN] [--out work/candidates.json]
    python -m src.autonomous.cli prompts [--candidates work/analysis/candidates.json]
    python -m src.autonomous.cli beats --music path/to/music.wav
    python -m src.autonomous.cli plan --target 30 --pacing fast [--music "..."]
    python -m src.autonomous.cli run-all --variants trailer,balanced,atmo [--music "..."] [--voice "..."] [--execute]
    python -m src.autonomous.cli capabilities
    python -m src.autonomous.cli list-clips
    python -m src.autonomous.cli list-presets
"""

import argparse
import logging
import sys
import json
from pathlib import Path

# Setup path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from autonomous.config import PipelineConfig, load_env_file
from autonomous.auto_editor import AutoEditor, ResolveConnectionError
from autonomous.video_analyzer import VideoAnalyzer, analyze_media_pool_clips
from autonomous.prompt_generator import PromptGenerator, generate_prompt_packs
from autonomous.beat_analyzer import BeatAnalyzer, analyze_music, is_librosa_available
from autonomous.decision_engine import DecisionEngine, VariantConfig
from autonomous.cinematic_pipeline import CinematicPipeline, run_pipeline
from autonomous.skills import generate_capabilities_report


def setup_logging(debug: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_edit(args: argparse.Namespace) -> int:
    """Execute the edit command."""
    logger = logging.getLogger("cli.edit")

    # Load config
    config = PipelineConfig.from_env()

    # Override from CLI args
    if args.timeline:
        config.resolve.default_timeline_name = args.timeline
    if args.music:
        config.music_file_path = args.music
    if args.voice:
        config.voiceover_file_path = args.voice
    if args.render_preset:
        config.resolve.render_preset_name = args.render_preset
    if args.bin:
        config.clip_bin_name = args.bin
    if args.fps:
        config.resolve.timeline_fps = args.fps
    if args.width:
        config.resolve.timeline_width = args.width
    if args.height:
        config.resolve.timeline_height = args.height

    config.features.dry_run = args.dry_run

    # Create editor
    editor = AutoEditor(config)

    try:
        # Build plan from media pool
        logger.info("Building edit plan from media pool...")
        plan = editor.build_plan_from_media_pool()

        # Validate plan
        issues = plan.validate()
        if issues:
            logger.error("Plan validation failed:")
            for issue in issues:
                logger.error(f"  - {issue}")
            return 1

        logger.info(f"Plan: {len(plan.clips)} clips, {len(plan.audio)} audio tracks")

        # Dry run mode - just save the plan
        if args.dry_run:
            plan_path = config.plan_path
            plan.save(plan_path)
            logger.info(f"Dry run - plan saved to: {plan_path}")
            print(f"\nPlan saved to: {plan_path}")
            print("\nPlan summary:")
            print(f"  Timeline: {plan.timeline.name}")
            print(f"  Resolution: {plan.timeline.width}x{plan.timeline.height} @ {plan.timeline.fps}fps")
            print(f"  Clips: {len(plan.clips)}")
            for clip in plan.clips:
                print(f"    [{clip.order}] {clip.name}")
            print(f"  Audio tracks: {len(plan.audio)}")
            for audio in plan.audio:
                print(f"    [A{audio.track}] {audio.name} ({audio.audio_type})")
            if plan.render:
                print(f"  Render preset: {plan.render.preset_name}")
            return 0

        # Execute plan
        logger.info("Executing edit plan...")
        plan = editor.execute_plan(plan)

        # Save executed plan
        plan.save(config.plan_path)

        # Print execution log
        print("\n--- Execution Log ---")
        for entry in plan.execution_log:
            print(entry)

        if plan.executed:
            print("\nEdit completed successfully!")
            return 0
        else:
            print("\nEdit completed with errors.")
            return 1

    except ResolveConnectionError as e:
        logger.error(f"Resolve connection error: {e}")
        print(f"\nError: {e}")
        print("Make sure DaVinci Resolve is running and a project is open.")
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        return 1


def cmd_list_clips(args: argparse.Namespace) -> int:
    """List clips in media pool."""
    logger = logging.getLogger("cli.list_clips")

    config = PipelineConfig.from_env()
    if args.bin:
        config.clip_bin_name = args.bin

    editor = AutoEditor(config)

    try:
        clips = editor.get_media_pool_clips(config.clip_bin_name)

        if args.json:
            # Output as JSON (without clip_object)
            output = [{k: v for k, v in c.items() if k != "clip_object"} for c in clips]
            print(json.dumps(output, indent=2))
        else:
            print(f"\nMedia Pool Clips ({len(clips)} total):")
            print("-" * 60)
            for i, clip in enumerate(clips, 1):
                print(f"{i:3}. {clip['name']}")
                print(f"     Type: {clip['type']}, Duration: {clip['duration']}")
                if clip.get('width') and clip.get('height'):
                    print(f"     Resolution: {clip['width']}x{clip['height']}, FPS: {clip['fps']}")

        return 0

    except ResolveConnectionError as e:
        logger.error(f"Resolve connection error: {e}")
        return 1


def cmd_list_presets(args: argparse.Namespace) -> int:
    """List available render presets."""
    logger = logging.getLogger("cli.list_presets")

    config = PipelineConfig.from_env()
    editor = AutoEditor(config)

    try:
        editor.connect()
        editor.resolve.OpenPage("deliver")

        render_settings = editor.project.GetRenderSettings()
        if not render_settings:
            print("Error: Could not get render settings")
            return 1

        project_presets = render_settings.GetRenderPresetList() or []
        system_presets = render_settings.GetSystemPresetList() or []

        if args.json:
            output = {
                "project_presets": project_presets,
                "system_presets": system_presets,
            }
            print(json.dumps(output, indent=2))
        else:
            print("\nRender Presets:")
            print("-" * 40)
            print("\nProject Presets:")
            for preset in project_presets:
                print(f"  - {preset}")
            print("\nSystem Presets:")
            for preset in system_presets:
                print(f"  - {preset}")

        return 0

    except ResolveConnectionError as e:
        logger.error(f"Resolve connection error: {e}")
        return 1


def cmd_render(args: argparse.Namespace) -> int:
    """Start rendering the queue."""
    logger = logging.getLogger("cli.render")

    config = PipelineConfig.from_env()
    editor = AutoEditor(config)

    try:
        if editor.start_render():
            print("Render started.")
            return 0
        else:
            print("Failed to start render. Check if there are jobs in the queue.")
            return 1

    except ResolveConnectionError as e:
        logger.error(f"Resolve connection error: {e}")
        return 1


def cmd_analyze(args: argparse.Namespace) -> int:
    """Analyze media pool clips and generate candidates.json."""
    logger = logging.getLogger("cli.analyze")

    config = PipelineConfig.from_env()
    if args.bin:
        config.clip_bin_name = args.bin

    # Determine output path
    output_path = Path(args.out) if args.out else config.candidates_path

    editor = AutoEditor(config)

    try:
        # Connect and get clips from media pool (NOT timeline)
        logger.info("Connecting to DaVinci Resolve...")
        editor.connect()

        logger.info(f"Getting clips from media pool" + (f" (bin: {args.bin})" if args.bin else ""))
        clips = editor.get_media_pool_clips(config.clip_bin_name)

        if not clips:
            print("No clips found in media pool.")
            return 1

        # Filter to video clips only
        video_clips = []
        for clip in clips:
            clip_type = clip.get("type", "").lower()
            # Include video types
            if "video" in clip_type or "still" in clip_type:
                video_clips.append({
                    "name": clip["name"],
                    "file_path": clip.get("file_path", ""),
                })
            elif clip.get("width") and clip.get("height"):
                # Has resolution = probably video
                video_clips.append({
                    "name": clip["name"],
                    "file_path": clip.get("file_path", ""),
                })

        if not video_clips:
            print("No video clips found in media pool.")
            return 1

        logger.info(f"Found {len(video_clips)} video clips to analyze")

        # Create analyzer with transcription disabled by default
        enable_transcription = args.transcribe if hasattr(args, 'transcribe') else False

        try:
            report = analyze_media_pool_clips(
                clips=video_clips,
                output_path=output_path,
                enable_transcription=enable_transcription,
                work_dir=config.work_dir / "analysis",
            )
        except ImportError as e:
            # Transcription requested but faster-whisper not installed
            logger.error(str(e))
            print(f"\nError: {e}")
            return 1

        # Print summary
        print(f"\n{'='*60}")
        print("ANALYSIS COMPLETE")
        print(f"{'='*60}")
        print(f"Output: {output_path}")
        print(f"\nSummary:")
        print(f"  Total clips: {report.summary.get('total_clips', 0)}")
        print(f"  Total duration: {report.summary.get('total_duration_sec', 0):.1f}s")
        print(f"  Total scenes: {report.summary.get('total_scenes', 0)}")
        print(f"  Clips with audio: {report.summary.get('clips_with_audio', 0)}")
        if report.summary.get('average_motion_score') is not None:
            print(f"  Average motion score: {report.summary['average_motion_score']:.3f}")
        print(f"  Analysis methods: {', '.join(report.summary.get('analysis_methods_used', []))}")
        print(f"  Motion methods: {', '.join(report.summary.get('motion_methods_used', []))}")

        # Show first 2 clips in detail
        print(f"\n{'='*60}")
        print("SAMPLE CLIPS (first 2)")
        print(f"{'='*60}")

        for i, clip in enumerate(report.clips[:2]):
            print(f"\n[{i+1}] {clip.clip_name}")
            print(f"    Path: {clip.file_path}")
            print(f"    Duration: {clip.duration_sec:.2f}s | FPS: {clip.fps} | {clip.width}x{clip.height}")
            print(f"    Has audio: {clip.has_audio}")
            print(f"    Scenes: {len(clip.scenes)} (method: {clip.analysis_method})")

            # Show first 3 scenes
            for scene in clip.scenes[:3]:
                motion_str = f"{scene.motion_score:.3f}" if scene.motion_score is not None else "N/A"
                print(f"      - Scene {scene.index}: {scene.start_sec:.2f}s - {scene.end_sec:.2f}s "
                      f"(motion: {motion_str})")

            if len(clip.scenes) > 3:
                print(f"      ... and {len(clip.scenes) - 3} more scenes")

            if clip.warnings:
                print(f"    Warnings: {clip.warnings}")

        if len(report.clips) > 2:
            print(f"\n... and {len(report.clips) - 2} more clips (see {output_path})")

        return 0

    except ResolveConnectionError as e:
        logger.error(f"Resolve connection error: {e}")
        print(f"\nError: {e}")
        print("Make sure DaVinci Resolve is running and a project is open.")
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(f"\nError: {e}")
        return 1


def cmd_prompts(args: argparse.Namespace) -> int:
    """Generate prompt packs from analysis."""
    logger = logging.getLogger("cli.prompts")

    config = PipelineConfig.from_env()

    # Determine candidates path
    candidates_path = Path(args.candidates) if args.candidates else config.candidates_path

    if not candidates_path.exists():
        print(f"\nError: Candidates file not found: {candidates_path}")
        print("Run 'analyze' command first to generate candidates.json")
        return 1

    # Determine output directory
    output_dir = Path(args.out) if args.out else config.work_dir / "prompts"

    try:
        logger.info(f"Loading analysis from: {candidates_path}")

        # Create generator
        generator = PromptGenerator(work_dir=config.work_dir)

        # Load candidates
        candidates = generator.load_candidates(candidates_path)

        # Generate prompts with optional style override
        style_override = args.style if hasattr(args, 'style') and args.style else None

        music_prompt = generator.generate_music_prompt(candidates, style_override)
        voiceover_script = generator.generate_voiceover_script(candidates)

        # Save prompts
        paths = generator.save_prompts(music_prompt, voiceover_script, output_dir)

        # Print summary
        print(f"\n{'='*60}")
        print("PROMPT PACKS GENERATED")
        print(f"{'='*60}")
        print(f"\nOutput directory: {output_dir}")

        print("\n## Music Prompt (Suno)")
        print(f"   Files: suno_prompt.md, suno_prompt.json")
        print(f"   Style: {music_prompt.style}")
        print(f"   Mood: {music_prompt.mood}")
        print(f"   Energy: {music_prompt.energy_level}")
        print(f"   BPM Range: {music_prompt.bpm_min}-{music_prompt.bpm_max}")
        print(f"   Duration: {music_prompt.duration_sec:.1f}s")
        print(f"\n   Quick prompt:")
        print(f"   {music_prompt.suno_prompt[:100]}...")

        print("\n## Voiceover Script")
        print(f"   Files: voiceover_script.md, voiceover_script.json")
        print(f"   Voice Style: {voiceover_script.voice_style}")
        print(f"   Pace: {voiceover_script.pace}")
        print(f"   Tone: {voiceover_script.tone}")
        print(f"   Sections: {len(voiceover_script.sections)}")

        print(f"\n{'='*60}")
        print("Next steps:")
        print("  1. Open suno_prompt.md and copy the prompt to Suno AI")
        print("  2. Open voiceover_script.md and edit the script")
        print("  3. Use ElevenLabs or your preferred TTS for voiceover")
        print(f"{'='*60}")

        return 0

    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        print(f"\nError: {e}")
        return 1
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(f"\nError: {e}")
        return 1


def cmd_beats(args: argparse.Namespace) -> int:
    """Analyze music file for beats and BPM."""
    logger = logging.getLogger("cli.beats")

    if not args.music:
        print("Error: --music is required")
        return 1

    music_path = Path(args.music)
    if not music_path.exists():
        print(f"Error: Music file not found: {music_path}")
        return 1

    # Check librosa availability
    if not is_librosa_available():
        print("Error: librosa is not installed")
        print("Install with: pip install librosa")
        return 1

    config = PipelineConfig.from_env()

    # Determine output path
    output_path = Path(args.out) if args.out else config.beats_path

    try:
        logger.info(f"Analyzing beats: {music_path}")

        result = analyze_music(str(music_path), output_path)

        if result is None:
            print("Error: Beat analysis failed")
            return 1

        # Print summary
        print(f"\n{'='*60}")
        print("BEAT ANALYSIS COMPLETE")
        print(f"{'='*60}")
        print(f"Output: {output_path}")
        print(f"\nResults:")
        print(f"  BPM: {result.bpm:.1f}")
        if result.bpm_confidence:
            print(f"  Confidence: {result.bpm_confidence:.2f}")
        print(f"  Duration: {result.duration_sec:.1f}s")
        print(f"  Beats detected: {len(result.beats_sec)}")
        print(f"  Downbeats: {len(result.downbeats_sec)}")

        # Show first few beats
        if result.beats_sec:
            print(f"\n  First 10 beats: {', '.join(f'{b:.2f}s' for b in result.beats_sec[:10])}")
            if len(result.beats_sec) > 10:
                print(f"  ... and {len(result.beats_sec) - 10} more")

        return 0

    except Exception as e:
        logger.exception(f"Beat analysis failed: {e}")
        print(f"\nError: {e}")
        return 1


def cmd_plan(args: argparse.Namespace) -> int:
    """Generate an edit plan using the decision engine."""
    logger = logging.getLogger("cli.plan")

    config = PipelineConfig.from_env()

    # Check candidates exist
    candidates_path = Path(args.candidates) if args.candidates else config.candidates_path
    if not candidates_path.exists():
        print(f"Error: Candidates not found: {candidates_path}")
        print("Run 'analyze' command first")
        return 1

    # Determine output path
    output_path = Path(args.out) if args.out else config.plan_path

    try:
        logger.info(f"Loading candidates from: {candidates_path}")

        # Create decision engine
        engine = DecisionEngine(work_dir=config.work_dir)
        candidates = engine.load_candidates(candidates_path)

        # Analyze beats if music provided
        beats = None
        if args.music and config.features.beat_sync_enabled:
            if is_librosa_available():
                logger.info(f"Analyzing beats: {args.music}")
                beats_result = analyze_music(args.music, config.beats_path)
                if beats_result:
                    beats = beats_result
                    logger.info(f"Beat sync enabled: {beats.bpm:.1f} BPM, {len(beats.beats_sec)} beats")
            else:
                logger.warning("librosa not installed - beat sync disabled")

        # Get variant config
        variant = args.variant or "balanced"
        target_duration = args.target or config.features.target_duration_sec

        if variant == "trailer":
            variant_config = VariantConfig.trailer(target_duration)
        elif variant in ("atmo", "atmospheric"):
            variant_config = VariantConfig.atmospheric(target_duration)
        else:
            variant_config = VariantConfig.balanced(target_duration)

        # Apply beat sync settings
        variant_config.beat_sync_enabled = config.features.beat_sync_enabled and beats is not None
        variant_config.beat_snap_tolerance_sec = config.features.beat_snap_tolerance_sec

        # Generate plan
        logger.info(f"Generating {variant} plan, target {target_duration}s")
        plan = engine.generate_plan(
            candidates=candidates,
            config=variant_config,
            beats=beats,
            timeline_name=args.timeline,
        )

        # Save plan
        plan.save(output_path)

        # Print summary
        print(f"\n{'='*60}")
        print("EDIT PLAN GENERATED")
        print(f"{'='*60}")
        print(f"Output: {output_path}")
        print(f"\nPlan Summary:")
        print(f"  Variant: {variant}")
        print(f"  Timeline: {plan.timeline.name}")
        print(f"  Target duration: {target_duration}s")
        print(f"  Clips selected: {len(plan.clips)}")
        if beats:
            print(f"  Beat sync: Enabled ({beats.bpm:.1f} BPM)")
        else:
            print(f"  Beat sync: Disabled")

        # Show clips
        print(f"\nClips:")
        total_frames = 0
        for clip in plan.clips:
            frames = clip.duration_frames or 0
            total_frames += frames
            print(f"  [{clip.order}] {clip.name} ({frames} frames)")

        fps = 24.0
        actual_duration = total_frames / fps
        print(f"\nActual duration: {actual_duration:.1f}s")

        return 0

    except Exception as e:
        logger.exception(f"Plan generation failed: {e}")
        print(f"\nError: {e}")
        return 1


def cmd_run_all(args: argparse.Namespace) -> int:
    """Run the full multi-variant pipeline."""
    logger = logging.getLogger("cli.run_all")

    config = PipelineConfig.from_env()

    # Check candidates exist
    if not config.candidates_path.exists():
        print(f"Error: Candidates not found: {config.candidates_path}")
        print("Run 'analyze' command first")
        return 1

    # Parse variants
    variants = []
    if args.variants:
        variants = [v.strip() for v in args.variants.split(",")]
    else:
        variants = config.features.default_variants.split(",")

    # Ducking settings
    if args.no_ducking:
        config.features.ducking_enabled = False
    if args.ducking_db:
        config.features.ducking_db = args.ducking_db
    if args.voice_start:
        config.features.voice_start_sec = args.voice_start

    try:
        logger.info(f"Running pipeline for variants: {variants}")

        result = run_pipeline(
            variants=variants,
            music_path=args.music,
            voice_path=args.voice,
            execute=args.execute,
            target_duration_sec=args.target,
        )

        # Print summary
        print(f"\n{'='*60}")
        print("PIPELINE COMPLETE" if result.success else "PIPELINE FAILED")
        print(f"{'='*60}")

        if result.variants_generated:
            print(f"\nVariants generated: {', '.join(result.variants_generated)}")
            print(f"\nOutput directories:")
            for name, output in result.variant_outputs.items():
                if output.success:
                    print(f"\n  {name}/")
                    if output.plan_path:
                        print(f"    plan.json")
                    if output.suno_prompt_md:
                        print(f"    prompts/suno_prompt.md")
                        print(f"    prompts/suno_prompt.json")
                    if output.voiceover_md:
                        print(f"    prompts/voiceover_script.md")
                        print(f"    prompts/voiceover_script.json")
                    if output.beats_path:
                        print(f"    beats.json")
                    if output.ducked_music_path:
                        print(f"    music_ducked.wav")

        if result.beats_path:
            print(f"\nBeat analysis: {result.beats_path}")

        if result.ducked_music_path:
            print(f"Ducked music: {result.ducked_music_path}")

        if result.timelines_created:
            print(f"\nTimelines created: {', '.join(result.timelines_created)}")

        if result.errors:
            print(f"\nErrors:")
            for err in result.errors:
                print(f"  - {err}")

        if not args.execute:
            print(f"\n{'='*60}")
            print("Plans generated. Run with --execute to create timelines in Resolve.")
            print(f"{'='*60}")

        return 0 if result.success else 1

    except Exception as e:
        logger.exception(f"Pipeline failed: {e}")
        print(f"\nError: {e}")
        return 1


def cmd_capabilities(args: argparse.Namespace) -> int:
    """Print capabilities report for all DaVinci Resolve MCP skills."""
    logger = logging.getLogger("cli.capabilities")

    try:
        report = generate_capabilities_report()
        print(report)
        return 0

    except Exception as e:
        logger.exception(f"Failed to generate capabilities report: {e}")
        print(f"\nError: {e}")
        return 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Autonomous Cinematic Video Editor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # edit command
    edit_parser = subparsers.add_parser("edit", help="Create and execute an edit plan")
    edit_parser.add_argument("--timeline", "-t", help="Timeline name (default: AUTO_V1)")
    edit_parser.add_argument("--music", "-m", help="Path to music file for A1")
    edit_parser.add_argument("--voice", "-v", help="Path to voiceover file for A2")
    edit_parser.add_argument("--render-preset", "-r", help="Render preset name")
    edit_parser.add_argument("--bin", "-b", help="Media pool bin to use")
    edit_parser.add_argument("--fps", help="Timeline frame rate")
    edit_parser.add_argument("--width", type=int, help="Timeline width")
    edit_parser.add_argument("--height", type=int, help="Timeline height")
    edit_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate plan without executing (saves to work/plans/plan.json)",
    )

    # list-clips command
    list_clips_parser = subparsers.add_parser("list-clips", help="List media pool clips")
    list_clips_parser.add_argument("--bin", "-b", help="Specific bin to list")
    list_clips_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # list-presets command
    list_presets_parser = subparsers.add_parser("list-presets", help="List render presets")
    list_presets_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # render command
    render_parser = subparsers.add_parser("render", help="Start rendering the queue")

    # analyze command
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze media pool clips and generate candidates.json"
    )
    analyze_parser.add_argument("--bin", "-b", help="Specific media pool bin to analyze")
    analyze_parser.add_argument(
        "--out", "-o",
        default=None,
        help="Output path for candidates.json (default: work/candidates.json)"
    )
    analyze_parser.add_argument(
        "--transcribe",
        action="store_true",
        help="Enable audio transcription (requires faster-whisper)"
    )

    # prompts command
    prompts_parser = subparsers.add_parser(
        "prompts",
        help="Generate music and voiceover prompt packs from analysis"
    )
    prompts_parser.add_argument(
        "--candidates", "-c",
        default=None,
        help="Path to candidates.json (default: work/analysis/candidates.json)"
    )
    prompts_parser.add_argument(
        "--out", "-o",
        default=None,
        help="Output directory for prompt files (default: work/prompts)"
    )
    prompts_parser.add_argument(
        "--style", "-s",
        default=None,
        help="Override music style (e.g., 'electronic ambient', 'orchestral epic')"
    )

    # beats command (Milestone 5)
    beats_parser = subparsers.add_parser(
        "beats",
        help="Analyze music file for beats and BPM"
    )
    beats_parser.add_argument(
        "--music", "-m",
        required=True,
        help="Path to music file (WAV, MP3, etc.)"
    )
    beats_parser.add_argument(
        "--out", "-o",
        default=None,
        help="Output path for beats.json (default: work/audio/beats.json)"
    )

    # plan command (Milestone 7)
    plan_parser = subparsers.add_parser(
        "plan",
        help="Generate an edit plan using the decision engine"
    )
    plan_parser.add_argument(
        "--candidates", "-c",
        default=None,
        help="Path to candidates.json (default: work/analysis/candidates.json)"
    )
    plan_parser.add_argument(
        "--out", "-o",
        default=None,
        help="Output path for plan.json (default: work/plans/plan.json)"
    )
    plan_parser.add_argument(
        "--variant", "-V",
        default="balanced",
        choices=["trailer", "balanced", "atmo", "atmospheric"],
        help="Variant type (default: balanced)"
    )
    plan_parser.add_argument(
        "--target", "-t",
        type=float,
        default=None,
        help="Target duration in seconds (default: 60)"
    )
    plan_parser.add_argument(
        "--music", "-m",
        default=None,
        help="Path to music file for beat sync"
    )
    plan_parser.add_argument(
        "--timeline",
        default=None,
        help="Timeline name override"
    )

    # run-all command (Milestone 8)
    run_all_parser = subparsers.add_parser(
        "run-all",
        help="Run the full multi-variant pipeline"
    )
    run_all_parser.add_argument(
        "--variants",
        default=None,
        help="Comma-separated variant names (default: trailer,balanced,atmo)"
    )
    run_all_parser.add_argument(
        "--music", "-m",
        default=None,
        help="Path to music file"
    )
    run_all_parser.add_argument(
        "--voice", "-v",
        default=None,
        help="Path to voiceover file"
    )
    run_all_parser.add_argument(
        "--target", "-t",
        type=float,
        default=None,
        help="Target duration in seconds"
    )
    run_all_parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute plans in Resolve (create timelines)"
    )
    run_all_parser.add_argument(
        "--no-ducking",
        action="store_true",
        help="Disable audio ducking"
    )
    run_all_parser.add_argument(
        "--ducking-db",
        type=float,
        default=None,
        help="Ducking amount in dB (default: -12)"
    )
    run_all_parser.add_argument(
        "--voice-start",
        type=float,
        default=None,
        help="Voice start offset in seconds"
    )

    # capabilities command
    capabilities_parser = subparsers.add_parser(
        "capabilities",
        help="Show MCP capabilities report for all DaVinci Resolve pages"
    )

    args = parser.parse_args()
    setup_logging(args.debug)

    # Load .env file
    load_env_file()

    if args.command == "edit":
        return cmd_edit(args)
    elif args.command == "list-clips":
        return cmd_list_clips(args)
    elif args.command == "list-presets":
        return cmd_list_presets(args)
    elif args.command == "render":
        return cmd_render(args)
    elif args.command == "analyze":
        return cmd_analyze(args)
    elif args.command == "prompts":
        return cmd_prompts(args)
    elif args.command == "beats":
        return cmd_beats(args)
    elif args.command == "plan":
        return cmd_plan(args)
    elif args.command == "run-all":
        return cmd_run_all(args)
    elif args.command == "capabilities":
        return cmd_capabilities(args)
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
