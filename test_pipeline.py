"""
Test script to run the cinematic pipeline with media pool items.

This script:
1. Lists clips to identify videos, music, and voice
2. Analyzes video clips to create candidates.json
3. Extracts file paths for music and voice from media pool
4. Runs VAD on voice audio
5. Runs the full pipeline with all variants
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from autonomous.config import PipelineConfig, load_env_file
from autonomous.auto_editor import AutoEditor
from autonomous.cinematic_pipeline import CinematicPipeline

def main():
    # Load config
    load_env_file()
    config = PipelineConfig.from_env()
    
    # Connect to Resolve
    editor = AutoEditor(config)
    editor.connect()
    
    print("=" * 60)
    print("CINEMATIC PIPELINE TEST")
    print("=" * 60)
    
    # Step 1: Get all clips
    print("\n[1] Getting clips from media pool...")
    all_clips = editor.get_media_pool_clips()
    
    # Separate videos, music, and voice
    video_clips = []
    music_path = None
    voice_path = None
    
    for clip in all_clips:
        clip_type = clip.get("type", "").lower()
        file_path = clip.get("file_path", "")
        name = clip.get("name", "")
        
        # Check if it's a video
        if "video" in clip_type or (clip.get("width") and clip.get("height")):
            video_clips.append({"name": name, "file_path": file_path})
        
        # Check if it's music (look for music keywords or .wav/.mp3)
        elif "audio" in clip_type and file_path:
            if "music" in name.lower() or "psybient" in name.lower():
                music_path = file_path
                print(f"   Found music: {name}")
            elif "elevenlabs" in name.lower() or "voice" in name.lower():
                voice_path = file_path
                print(f"   Found voice: {name}")
    
    print(f"   Found {len(video_clips)} video clips")
    
    if not video_clips:
        print("ERROR: No video clips found!")
        return 1
    
    if not music_path:
        print("WARNING: No music track found in media pool")
    if not voice_path:
        print("WARNING: No voice audio found in media pool")
    
    # Step 2: Analyze video clips
    print("\n[2] Analyzing video clips...")
    from autonomous.video_analyzer import analyze_media_pool_clips
    
    try:
        report = analyze_media_pool_clips(
            clips=video_clips,
            output_path=config.candidates_path,
            enable_transcription=False,
            work_dir=config.work_dir / "analysis",
        )
        print(f"   Analysis complete: {len(report.clips)} clips analyzed")
        print(f"   Output: {config.candidates_path}")
    except Exception as e:
        print(f"   ERROR: Analysis failed: {e}")
        return 1
    
    # Step 3: Run VAD on voice if available
    vad_json_path = None
    if voice_path and Path(voice_path).exists():
        print("\n[3] Running VAD on voice audio...")
        from autonomous.analysis.vad import detect_speech_segments, write_vad_json, vad_summary
        
        try:
            segments = detect_speech_segments(audio_path=voice_path, aggressiveness=2)
            summary = vad_summary(segments, None)
            vad_json_path = config.work_dir / "audio" / "vad.json"
            vad_json_path.parent.mkdir(parents=True, exist_ok=True)
            write_vad_json(summary, str(vad_json_path))
            print(f"   VAD complete: {len(segments)} segments detected")
            print(f"   Output: {vad_json_path}")
        except Exception as e:
            print(f"   WARNING: VAD failed: {e}")
            vad_json_path = None
    
    # Step 4: Run pipeline
    print("\n[4] Running cinematic pipeline...")
    pipeline = CinematicPipeline(config)
    
    result = pipeline.run_all(
        variants=["balanced"],  # Start with just balanced variant
        music_path=music_path,
        voice_path=voice_path if not vad_json_path else None,
        vad_json_path=str(vad_json_path) if vad_json_path else None,
        execute=False,  # Don't execute yet, just generate plans
        target_duration_sec=30.0,
    )
    
    # Print results
    print("\n" + "=" * 60)
    print("PIPELINE RESULTS")
    print("=" * 60)
    
    if result.success:
        print(f"✓ Success! Generated {len(result.variants_generated)} variants")
        for variant_name in result.variants_generated:
            output = result.variant_outputs.get(variant_name)
            if output:
                print(f"\n  Variant: {variant_name}")
                print(f"    Output dir: {output.output_dir}")
                if output.plan_path:
                    print(f"    Plan: {output.plan_path}")
                if output.ducked_music_path:
                    print(f"    Ducked music: {output.ducked_music_path}")
    else:
        print("✗ Pipeline failed")
        for error in result.errors:
            print(f"  ERROR: {error}")
    
    if result.warnings:
        print("\nWarnings:")
        for warning in result.warnings:
            print(f"  WARNING: {warning}")
    
    print("\n" + "=" * 60)
    print("Next steps:")
    print("  1. Review the generated plans in work/variants/")
    print("  2. Run with --execute to create timelines in Resolve")
    print("=" * 60)
    
    return 0 if result.success else 1

if __name__ == "__main__":
    sys.exit(main())
