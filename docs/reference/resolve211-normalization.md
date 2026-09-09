# Native Resolve 21.1 audio normalization

Compound `timeline normalize_audio_level` and granular
`normalize_timeline_audio_level` take explicit audio timeline `item_ids` and
optional `options`. IDs are resolved on the current timeline's audio tracks,
with no implicit linked-item expansion. Missing/duplicate IDs and malformed
options are refused before the native write. Native false stays success:false.

All NormalizeAudioOptions fields are supported:

- normalizationMode: native name from get_normalize_audio_modes.
- targetLevel: finite dBFS number, for example -6.
- targetLoudness: finite LKFS number, for example -23.
- setLevelMode: NORMALIZE_AUDIO_SET_LEVEL_RELATIVE or
  NORMALIZE_AUDIO_SET_LEVEL_INDEPENDENT, or an integral native constant value.

Names resolve against the live Resolve object. Unknown option keys, invalid
named constants, booleans in numeric fields and non-finite values are rejected.
Omitted options stay omitted; Resolve supplies its native defaults. Mode names
are passed through rather than hard-coded into a stale list. Use the existing
mode reader for the current build. The wrapper does not invent range clamps or
turn a refused native normalization into success.

The action has a 21.1 callable-method floor, entries in both destructive/risk
tables (MEDIUM), destructive granular annotations, and explicit compound dry-run
refusal. Normalization changes project clip gain, not source audio files.

## Contributor audio evidence

Contributor-validated on macOS Studio 21.1.0.14 in a disposable project using
997 Hz synthetic stereo tones, with one source 12 dB quieter than the other.
Both actual community interfaces produced byte-identical decoded PCM per case.
Independent FFmpeg measurements of exported 24-bit/48 kHz WAVs:

| Requested case | Measured output |
|---|---|
| Sample Peak Program, relative, target -6 dBFS | Two clip segments peak -6.0/-18.0 dBFS; 12 dB difference preserved |
| Sample Peak Program, independent, target -6 dBFS | Both segments peak -6.0 dBFS |
| EBU R128, target -23 LKFS, peak setting-1 dBFS | Integrated -22.9 LUFS, within 0.1 LU of requested target |

These are exported-audio measurements, not just gain readback. They do not prove
all normalization modes, true-peak limiting on difficult signals, long-program
loudness, multichannel bus behavior, or different source formats.

`tests/live_resolve211_normalization.py OUTPUT_DIR` requires disposable project
Codex Normalization Validation 20260909 at 24 fps, with tone.wav and quiet.wav.
The script creates timelines/renders and saves that project. Generate fixtures
without production media:

```sh
ffmpeg -f lavfi -i 'sine=frequency=997:sample_rate=48000:duration=4' \
  -af 'pan=stereo|c0=c0|c1=c0' -c:a pcm_s24le tone.wav
ffmpeg -i tone.wav -af volume=-12dB -c:a pcm_s24le quiet.wav
```

Measure each four-second segment with volumedetect and the loudness case with
ebur128. Compare full decoded PCM between interfaces. Pure tones are deliberate
meter fixtures; this does not substitute for representative-program QA.
