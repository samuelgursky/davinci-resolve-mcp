# Test Pipeline Steps

Follow these steps to test the cinematic pipeline with your media pool items.

## Step 1: Analyze Video Clips

This creates `work/analysis/candidates.json` from your video clips:

```bash
python -m src.autonomous.cli analyze
```

This will analyze all video clips in your media pool and generate candidates.json.

## Step 2: Get File Paths for Music and Voice

You need the file paths for your music and voice tracks. Run this to see file paths:

```bash
python -m src.autonomous.cli list-clips --json
```

Look for:
- Music: "RICH BITCH PSYBIENT 2.wav" - note the `file_path`
- Voice: "ElevenLabs_2026-01-07T16_10_19__s0_v3.wav" - note the `file_path`

## Step 3: Run VAD on Voice (Optional but Recommended)

If you want segment-aware ducking, run VAD on your voice file:

```bash
python -m src.autonomous.cli vad --audio "PATH_TO_VOICE_FILE" --out work/audio/vad.json
```

Replace `PATH_TO_VOICE_FILE` with the actual file path from Step 2.

## Step 4: Run the Full Pipeline

Run the pipeline with your music and voice:

```bash
# With VAD (segment-aware ducking):
python -m src.autonomous.cli run-all --variants balanced --music "PATH_TO_MUSIC" --vad work/audio/vad.json --target 30

# OR without VAD (simple ducking):
python -m src.autonomous.cli run-all --variants balanced --music "PATH_TO_MUSIC" --voice "PATH_TO_VOICE" --target 30
```

Replace the paths with actual file paths from Step 2.

## Step 5: Execute in Resolve (Optional)

To actually create timelines in Resolve, add `--execute`:

```bash
python -m src.autonomous.cli run-all --variants balanced --music "PATH_TO_MUSIC" --vad work/audio/vad.json --target 30 --execute
```

## Quick Test (All Steps Combined)

If you want to test with just the balanced variant and a 30-second target:

```bash
# 1. Analyze
python -m src.autonomous.cli analyze

# 2. Get paths (run this in Python to extract paths automatically)
python -c "
from autonomous.config import PipelineConfig, load_env_file
from autonomous.auto_editor import AutoEditor
load_env_file()
config = PipelineConfig.from_env()
editor = AutoEditor(config)
editor.connect()
clips = editor.get_media_pool_clips()
for clip in clips:
    name = clip.get('name', '')
    path = clip.get('file_path', '')
    if 'PSYBIENT' in name or 'ElevenLabs' in name:
        print(f'{name}: {path}')
"

# 3. Run VAD (use the voice path from step 2)
python -m src.autonomous.cli vad --audio "VOICE_PATH_HERE" --out work/audio/vad.json

# 4. Run pipeline (use paths from step 2)
python -m src.autonomous.cli run-all --variants balanced --music "MUSIC_PATH_HERE" --vad work/audio/vad.json --target 30
```

## Output Locations

- Candidates: `work/analysis/candidates.json`
- VAD: `work/audio/vad.json`
- Variants: `work/variants/balanced/`
  - `plan.json` - Edit plan
  - `prompts/suno_prompt.md` - Music prompt
  - `prompts/voiceover_script.md` - Voiceover script
  - `music_ducked.wav` - Ducked music (if ducking enabled)
