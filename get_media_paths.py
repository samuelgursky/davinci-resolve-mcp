"""
Quick script to get file paths for music and voice from media pool.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from autonomous.config import PipelineConfig, load_env_file
from autonomous.auto_editor import AutoEditor

def main():
    load_env_file()
    config = PipelineConfig.from_env()
    
    editor = AutoEditor(config)
    editor.connect()
    
    clips = editor.get_media_pool_clips()
    
    print("=" * 60)
    print("MEDIA POOL FILE PATHS")
    print("=" * 60)
    
    music_path = None
    voice_path = None
    
    for clip in clips:
        name = clip.get("name", "")
        file_path = clip.get("file_path", "")
        clip_type = clip.get("type", "").lower()
        
        if not file_path:
            continue
        
        # Check for music
        if "PSYBIENT" in name.upper() or ("audio" in clip_type and "music" in name.lower()):
            music_path = file_path
            print(f"\n[MUSIC]")
            print(f"   Name: {name}")
            print(f"   Path: {file_path}")
        
        # Check for voice
        elif "ELEVENLABS" in name.upper() or ("audio" in clip_type and "voice" in name.lower()):
            voice_path = file_path
            print(f"\n[VOICE]")
            print(f"   Name: {name}")
            print(f"   Path: {file_path}")
    
    print("\n" + "=" * 60)
    print("COMMANDS TO RUN:")
    print("=" * 60)
    
    if music_path and voice_path:
        print("\n# 1. Analyze videos:")
        print("python -m src.autonomous.cli analyze")
        
        print("\n# 2. Run VAD on voice:")
        print(f'python -m src.autonomous.cli vad --audio "{voice_path}" --out work/audio/vad.json')
        
        print("\n# 3. Run pipeline:")
        print(f'python -m src.autonomous.cli run-all --variants balanced --music "{music_path}" --vad work/audio/vad.json --target 30')
        
        print("\n# 4. Execute in Resolve (optional):")
        print(f'python -m src.autonomous.cli run-all --variants balanced --music "{music_path}" --vad work/audio/vad.json --target 30 --execute')
    else:
        if not music_path:
            print("\n[WARNING] Music path not found")
        if not voice_path:
            print("\n[WARNING] Voice path not found")
    
    print()

if __name__ == "__main__":
    main()
