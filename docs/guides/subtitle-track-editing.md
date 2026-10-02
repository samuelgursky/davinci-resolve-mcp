# Subtitle tracks: captions and animated presets

The advanced server's `project_db` tool edits saved local SQLite projects.
The live server can generate subtitles with `timeline_ai.create_subtitles`,
enumerate their items, read names/bounds and delete items. It cannot edit caption
text, word timings or animation controls through `TimelineItem.SetProperty`.
Such subtitle property writes are now refused before auto-archiving.

There are two independent kinds of subtitle styling:

- `list_subtitle_styles` / `set_subtitle_style` read/edit the basic track
  `EffectFiltersBA` font and position. `styled:false` does **not** mean the
  track has no animation preset.
- `list_subtitle_presets` / `copy_subtitle_preset` operate on the linked Fusion
  holder and composition. `set_subtitle_preset` edits named Word Highlight
  controls inside its nested compressed tool section.

## Required workflow

1. Generate captions in Resolve and save the project. Inspect it with
   `list_captions`, `list_subtitle_presets` and `check_captions`.
2. Preview edits with `dryRun:true`. This reads the saved database; unsaved
   Resolve changes are not visible. Preview IDs for proposed new captions are
   provisional.
3. Save and **fully quit Resolve before writing**. New subtitle write actions
   require `iConfirmProjectClosed:true` and independently inspect running
   processes. Closing only the project is insufficient. Failure to inspect
   processes also refuses the write.
   **Opt-in alternative:** `allowWhileRunningIfNotLoaded:true` accepts a
   running Resolve only when its scripting API reports a *different* loaded
   project than the target (Resolve oversaves only the loaded project). The
   write is refused if the target is loaded or the loaded project cannot be
   read. Experimental: confirm the first use by loading, rendering, saving and
   reloading the target.
4. Apply the edits, then relaunch Resolve (or, with the opt-in, load the
   target project) and inspect/render the result.

Each new subtitle write creates a unique `Project.db.subtitle-<time>-<uuid>.bak`
SQLite snapshot, including committed WAL pages. Edits and readback verification
run in one transaction: a failure rolls everything back. Preserve the returned
backup. To recover, quit Resolve and restore that snapshot using your normal
project-library recovery procedure; do not replace a live database.

`verified:true` means **database readback**, not that Resolve rendered the
change. Writes never touch source media. Shared/unsupported item dependencies,
ambiguous timelines, missing tracks and mismatched schemas are refused.

## Selectors and discovery

Use `projectName` or an explicit `projectDb` path. Discovery searches the
standard Windows `%APPDATA%/Blackmagic Design/DaVinci Resolve/Support`, macOS
Application Support (including the App Store sandbox), and Linux
`~/.local/share/DaVinciResolve` libraries. Both `Resolve Project Library` and
`Resolve Disk Database` layouts are considered. Relocated libraries need an
explicit path; these subtitle actions do not operate on Postgres libraries.

`timeline` is the saved timeline name; `track` is the 1-based subtitle-track
index (default 1). Vector associations determine track order. Duplicate timeline
names require disambiguation in Resolve before editing.

SQLite uses `better-sqlite3` when its native binding loads, otherwise
[`node:sqlite`](https://nodejs.org/docs/latest-v24.x/api/sqlite.html) on a suitable
Node runtime (22.13+ recommended; tested here on 24.14.1). Zstd reads use native
`node:zlib` when available and otherwise `fzstd`. Caption writes emit the raw
`0x80` envelope, avoiding a native compression dependency.

## Captions

```json
{"action":"list_captions","args":{"projectName":"My Project","timeline":"Reel"}}
```

Results contain `fps`, `timeUnit:"timeline_frames"` and `captions` with
`id`, `text`, `start`, `end`, `words:[{text,start,end}]`, `originalWords`,
`anchor` and any `decodeIssues`. Bounds are absolute timeline frames, with
exclusive ends. Word frames may be fractional because storage uses 60 ticks
per second. Caption starts/ends must be nonnegative integer frames.

Current words come from protobuf fields 14/15/16; original AI words from
18/19/20. Field 21 is a frame anchor. The decoder accounts for a caption moved
after that anchor was written. `Name` is only a fallback: UI text edits can
leave it stale, and can produce inconsistent word intervals. No assumption is
made that saving in Resolve will repair those intervals.

```json
{
  "action":"write_captions",
  "args":{
    "projectName":"My Project", "timeline":"Reel", "dryRun":true,
    "replace":[{
      "id":"<caption-id>", "text":"Hello world", "start":108000, "end":108060,
      "words":[{"text":"Hello","start":108000,"end":108030},
               {"text":"world","start":108030,"end":108060}]
    }],
    "add":[{
      "text":"Welcome", "start":108090, "end":108120,
      "words":[{"text":"Welcome","start":108090,"end":108120}]
    }],
    "delete":["<another-caption-id>"]
  }
}
```

For a write, replace `dryRun:true` with `iConfirmProjectClosed:true` after
quitting Resolve. `replace` supplies complete caption content/timing, not a
partial patch. Text must equal trimmed words joined with spaces. New captions
clone a caption already on that track (optionally `templateCaptionId`) to
preserve the unknown schema fields; adding to a completely empty track is
currently refused. Replacements preserve original AI words and unknown fields;
additions clear inherited AI history and markers. `Items` associations are
re-indexed by time without modifying `FusionCompHolderItems`.

Invalid word intervals, gaps, overlaps, conflicting IDs, or captions that
overlap are rejected. Boundaries are quantised to 60 Hz before verification;
a word that becomes zero length after rounding is also rejected. Existing
untouched captions are reported by QC rather than silently retimed.

`check_captions` takes the same selectors and optional `maxCharacters` (24 by
default). It reports gaps, invalid/missing timings, overlaps, out-of-bounds
words, decode count mismatches and long lines. The character limit is a
heuristic for vertical captions, **not** a pixel-width calculation: font,
size and position determine actual clipping. It never rewrites timing.

## Animated preset copying and controls

```json
{
  "action":"copy_subtitle_preset",
  "args":{
    "sourceProject":"Reference", "sourceTimeline":"Reel", "sourceTrack":1,
    "projectName":"My Project", "timeline":"Reel", "track":1,
    "replace":false, "dryRun":true,
    "inputs":{
      "font":"Open Sans", "fontStyle":"Semibold", "size":0.08,
      "position":[0.5,0.3],
      "textRed":1, "textGreen":1, "textBlue":1, "textAlpha":1,
      "highlightRed":1, "highlightGreen":0.8, "highlightBlue":0,
      "outlineEnabled":1, "outlineRed":0, "outlineGreen":0, "outlineBlue":0,
      "thickness":0.03
    }
  }
}
```

`sourceProjectDb` can replace `sourceProject`. For compatibility with the
workflow brief, `source_project`, `source_timeline`, `target_project` and
`target_timeline` alias those project/timeline selectors; `project` aliases
`projectName`. Do not pass an alias and its canonical selector together.

Copying clones the holder, its track association and its composition with new
UUIDs. An occupied destination requires `replace:true`; the source is unchanged.
Omit `inputs` to copy the preset bytes unchanged. To adjust an existing preset,
use `set_subtitle_preset` with target selectors and `inputs`.

Colour channels are 0–1, `outlineEnabled` is 0 or 1, `size` is Fusion's
normalised text size (not points), `position` is Fusion Center `[x,y]`, and
`thickness` is the template's HOutlineThickness value. Parameter editing is
restricted to the inspected Word Highlight template and literal Template
TextPlus inputs. Connected/animated inputs and unsupported layouts are refused.
Missing input values in the listing mean Resolve/template defaults, not zero.
Other supported composition envelopes can be cloned unchanged, but cannot have
their parameter meanings guessed. Preset holder Duration is preserved from the
reference (observed 150); it is not extended to caption-track length.

## Evidence and outstanding live acceptance

On 2026-10-02 a read-only probe on Studio 21.1.0.17/Windows confirmed the API
boundary on an 11-caption timeline. Saved local project inspection confirmed
the caption encoding and Word Highlight's nested zlib inputs. Synthetic tests
exercise both codecs, cloning, transactional rollback, frame-rate arithmetic,
guard refusal, backup readback and preservation of unrelated tracks.

The writer has **not yet passed the complete automated render acceptance**.
The initial opt-in Windows harness `tests/live_subtitle_roundtrip.py` run on
Studio 21.1.0.17 generated twenty synthetic captions. Preset/control edits,
corrected text, caption addition/deletion and subsequent save survived reopening,
but all 403 expected caption frames were black in the BurnIn render.

The failed render prompted a codec regression fix: adding absent controls after
a final input without a trailing comma produced invalid Lua. The writer now
prepends comma-terminated inputs, and a regression fixture covers the missing
separator. A fresh synthetic-only reopen and BurnIn render is required to verify
the fix; earlier manual viewer checks do not establish every-frame correctness.

That live run also exposed Resolve's association constraints: DbIndex must be
nonnegative and its composite primary key uses ON CONFLICT REPLACE. The writer
now rebuilds only the selected track's Items vector within the transaction,
avoiding both rejected temporary indices and lost neighbours during reordering.
The regression fixture includes those constraints.

Before releasing it, use a disposable project and synthetic speech/media:
generate subtitles, apply Word Highlight with explicit colours, correct two
captions, add one and delete one, reopen Resolve, then render with
`ExportSubtitle:true, SubtitleFormat:"BurnIn"`. Inspect rendered frames across
every word boundary and at the frame edges. Readback alone cannot establish
visible highlighting, absence of blank frames, or safe margins.

Also still unverified: holder Duration semantics, per-caption preset rows,
whether/when UI edits are retimed on save, and SRT import preserving word
timings on 21.1. A previously reported ImportMedia(SRT)+AppendToTimeline route
on 21.0.4.5 is not evidence that SRT carries word timings on another build.
Repeat the probe and render test after Resolve updates.
