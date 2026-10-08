# Subtitle tracks: captions and animated presets

## Live effects: keep Resolve open

For routine video changes, use the live server's
`timeline_ai(action="set_subtitle_preset", params={...})`. Do not route subtitle
effect changes to `project_db` or ask the user to quit/relaunch Resolve.

```json
{
  "action":"set_subtitle_preset",
  "params":{
    "track":1, "preset":"Word Highlight",
    "inputs":{
      "font":"Segoe UI", "fontStyle":"Black", "size":0.065,
      "position":[0.5,0.4], "textRed":1, "textGreen":1, "textBlue":1,
      "highlightRed":1, "highlightGreen":1, "highlightBlue":0,
      "outlineEnabled":1, "outlineRed":0, "outlineGreen":0,
      "outlineBlue":0, "thickness":0.1
    }
  }
}
```

This exports the current native DRT, edits only its subtitle Fusion holder,
then imports and selects a new timeline revision. The original timeline and
export remain recoverable. It never edits the open database, changes source
media or requires an application restart. `dry_run:true` prepares the exported
revision without importing it. Omit `preset` to incrementally adjust the
current Word Highlight instead of replacing it. `preset_reference` can name
another native DRT, with `reference_track` selecting its subtitle track.
`revision_name` is optional and must be unique in the current project.

`preset:"Word Highlight"` applies a bundled native holder exported from the
synthetic Studio 21.1.0.17 acceptance project. Its reference settings are Segoe
UI Black, size 0.055, centred position, white text, yellow highlight, black
outline and thickness 0.1; these are reference settings, not claims about UI
defaults. Explicit `inputs` override them. No reference footage is bundled.
`preset:"Lollipop"` applies the bundled native Lollipop. Other installed subtitle
presets are discovered from the local `Templates.drfx`, captured by the running
Resolve as a native title in an isolated temporary timeline, then applied to the
subtitle track through native interchange. The temporary capture is removed
after restoring the original timeline; the original edit remains recoverable.
No additional vendor template files are redistributed. Use
`timeline_ai(action="list_title_presets")` to discover names, full template IDs
and categories. Supply `templates_archive` for a nonstandard installation.
Full IDs disambiguate names such as the ordinary and animated `Statement`.

All subtitle templates with the inspected `Template = TextPlus` layout accept
the common literal `font`, `fontStyle`, `size`, `position`, `textRed`, `textGreen`,
`textBlue`, and `textAlpha` controls. Highlight and outline mappings remain
specific to Word Highlight. Connected/animated controls, different layouts and
unmapped effect controls are refused. Do not guess their meanings. The live
matrix is documented in [title library automation](title-library-automation.md).
An alternate `preset_reference` can copy another decodable native holder.
For an unbundled installed preset, a mutation-free dry run needs an existing
`preset_reference`: discovering its native definition otherwise needs a temporary
live title. `dry_run` never creates that temporary timeline.

For gradient/image text fills (observed in Grey with Shadow), solid RGB inputs
are dormant. The writer refuses a colour edit that would only change those
invisible values. Pass `inputs.textFillMode:"solid"` explicitly to replace the
fill mode, then supply the desired text RGBA. The stored gradient is retained,
and the original timeline/reference remains recoverable. Font, size and position
edits can preserve the gradient by omitting text colour inputs. Readback reports
the effective `textFillMode`; absent Type1 uses the observed TextPlus solid default.

The handler checks live track counts, item names/bounds and Media Pool media IDs
against the original, then re-exports the imported timeline through Resolve and
verifies that it retained the preset controls before selecting the revision. A failed import/check
restores the previous active timeline and reports the retained failed revision.
Resolve re-export readback plus edit inventory is not render verification: inspect rendered
frames at word boundaries and across caption gaps. Native DRT import was tested
on Studio 21.1.0.17/Windows without quitting Resolve. Changing sequence IDs in
only the sequence XML loses subtitle tracks; cross-entry references must remain
intact. Resolve remaps timeline IDs itself on import.

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

## Offline database workflow (explicit maintenance only)

The following full-quit requirement belongs to direct database writes, not
live effect automation. Keep the guard: bypassing it can lose edits. Caption
text/word-timing DB writes still use this offline workflow; for restart-free
caption corrections use the live Resolve UI. A generic `SetProperty` refusal
does not establish that all subtitle workflows require a restart.

1. Generate captions in Resolve and save the project. Inspect it with
   `list_captions`, `list_subtitle_presets` and `check_captions`.
2. Preview edits with `dryRun:true`. This reads the saved database; unsaved
   Resolve changes are not visible. Preview IDs for proposed new captions are
   provisional.
3. Save and **fully quit Resolve before writing**. New subtitle write actions
   require `iConfirmProjectClosed:true` and independently inspect running
   processes. Closing only the project is insufficient. Failure to inspect
   processes also refuses the write. Loading a *different* project is not
   enough either: measured on Studio 19.1.3.7, a project loaded earlier in the
   session is served from memory when it is loaded again, so a disk write to
   it is not shown, and saving after editing the same rows overwrites it.
4. Apply the edits, then relaunch Resolve and inspect/render the result.

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
Node runtime (22.16+ or 23.8+, which provide `node:sqlite` `backup()`; tested on
24.14.1 and 22.22.3). Zstd reads use native
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
based on common literal Template TextPlus inputs for subtitle templates;
highlight and outline controls are specific to Word Highlight.
Connected/animated inputs and unsupported layouts are refused.
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

On 2026-10-06, a synthetic-only caption edit → full quit → database write →
relaunch → BurnIn render acceptance passed on Studio 21.1.0.17 / Windows.
Seven generated captions were edited through the actual `project_db` handler:
six replacements, one deletion and one addition, with explicit word boundaries.
A fresh native Word Highlight preset was created in the disposable project;
no personal project or media was used as a preset reference.

The 21-second 1080x1920 / 30 fps render contained 630 frames. All 420 caption
frames contained text, all seven word transitions matched the written timings,
and no caption pixels touched the frame edges or appeared in the gaps. The
rendered text was visually inspected for all seven captions in both highlight
states. Resolve's live text/bounds and saved word timing readback also matched.
The original frame check did not assert base text colour. The maintainer's
[acceptance review](https://github.com/samuelgursky/davinci-resolve-mcp/pull/273#issuecomment-6048433383)
found that the non-highlighted word remained pale yellow. The codec now targets
TextPlus shading inputs (`Red1`, `Green1`, `Blue1`, `Alpha1`) rather than the
macro's `Clone` controls. On 2026-10-08, the original track's Inspector confirmed
`#ffeb85` text. A fresh native Word Highlight, configured through Resolve's UI
with `#ffffff` text and `#ffff00` highlight, rendered white. After a full quit,
the corrected MCP write and relaunch also rendered white with Segoe UI Black,
centred position and black outline at thickness 0.1.

Both new 1080x1920 renders passed checks on all 630 decoded frames: all 420
caption frames had white base text and yellow highlighting, with exact word
transitions and no text in the gaps or at the frame edges. Bright fill pixels
were measured independently per word, and the original render failed the new
white-text assertion on all 420 caption frames. All seven captions were also
visually reviewed in both highlight states; the pixel check is not OCR. Selected
frame PNGs retain the full render resolution. Generated frames and reports are
kept outside the repository. The earlier green-pixel live harness was removed
because its pass flag did not establish word timing or text colour.

The earlier failed synthetic render prompted a codec regression fix: inserting
absent controls after a final input without a trailing comma produced invalid
Lua. The writer now prepends comma-terminated inputs, and a regression fixture
covers the missing separator. The new acceptance run exercises this path.

That live run also exposed Resolve's association constraints: DbIndex must be
nonnegative and its composite primary key uses ON CONFLICT REPLACE. The writer
now rebuilds only the selected track's Items vector within the transaction,
avoiding both rejected temporary indices and lost neighbours during reordering.
The regression fixture includes those constraints.

To repeat acceptance, use a disposable project and synthetic speech/media:
generate subtitles, apply Word Highlight with explicit colours, correct two
captions, add one and delete one, reopen Resolve, then render with
`ExportSubtitle:true, SubtitleFormat:"BurnIn"`. Inspect rendered frames across
every word boundary and at the frame edges. Readback alone cannot establish
visible highlighting, absence of blank frames, or safe margins. Assert the
non-highlighted text colour separately from the highlighted word, check every
decoded frame against the written word intervals, and check the caption gaps.
Review the rendered words visually too: pixel colour checks are not OCR.

Also still unverified: holder Duration semantics, per-caption preset rows,
whether/when UI edits are retimed on save, and SRT import preserving word
timings on 21.1. A previously reported ImportMedia(SRT)+AppendToTimeline route
on 21.0.4.5 is not evidence that SRT carries word timings on another build.
Repeat the probe and render test after Resolve updates.

## Restart-free acceptance (2026-10-08)

`tests/live_subtitle_preset_validation.py` exercised the actual Python
`timeline_ai.set_subtitle_preset` dispatcher on Studio 21.1.0.17/Windows in the
disposable synthetic QA project, without launching, quitting or reopening
Resolve. It removed the animation holder from an exported synthetic timeline,
imported that bare-caption timeline, then applied the bundled Word Highlight.
The live action verified seven captions and the video/audio bounds/media IDs,
and native re-export retained the requested white text and magenta highlight.

Three full-resolution 1080x1920 Resolve-rendered frames were visually inspected:
at 108200 the first word was magenta and the second white; at 108220 those
colours swapped; frame 108180 in the caption gap was black. This proves those
sampled frames, not every frame or other templates/builds. The harness restores
the previous timeline, playhead and page. Earlier live runs also demonstrated
incremental colour, size and position edits, followed by a random-colour change
requested as a demonstration. Random colours are not the bundled defaults.

A subsequent Lollipop test on the same running Studio session applied the
effect through the native UI, then through the updated MCP action using the
bundled reference. Resolve's re-export confirmed
`Templates/Edit/Titles/Subtitles/Animated/Lollipop`; a rendered frame showed its
native yellow text and orange outline. No application restart was needed.
This Windows acceptance does not establish Mac compatibility; repeat it there.
