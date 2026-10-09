# Installed title library acceptance — 2026-10-08/09

Windows Resolve Studio 21.1.0.17, branch `feat/subtitle-track-support`, synthetic
project. Native definitions came from the locally installed factory
`Templates.drfx`; they were not redistributed. Source media was unchanged.

## Final measured result

| Factory category | Applied | Property readback and sampled renders |
|---|---:|---:|
| Ordinary Fusion titles / lower thirds | 111 | 111 passed |
| Static subtitle presets | 18 | 18 passed |
| Animated subtitle presets | 5 | 5 passed |
| Total | 134 | 134 passed after corrections and retests |

Native title insertion used full IDs and checked `TEMPLATE_ID`. Supported
independent text targets received `MCP TEST` through the public title-text action
and scoped Fusion writes. Available literal size/RGB controls were exercised;
connected/expression controls were preserved. Native Deliver captures compared
the same frame before/after and sampled early/late frames. Final title contact
sheets show the requested text. Material/gradient-driven colours are not
certified by dormant RGB readback.

Subtitle tests used the public live action with size, position and text RGB.
Imported revisions preserved edit/media inventory and retained preset/controls
in a native re-export. Two caption word samples rendered visibly, with a blank
gap sample. Grey with Shadow explicitly selected solid fill for its colour test;
the native gradient reference stays recoverable. All 23 subtitle presets passed
without a Resolve application restart.

## Corrections and session failure

- Follow StyledTextFollower base `Text` and PublishText `Value` without flattening
  the owner's connected StyledText input; support sText and Text3D.
- MultiText `TextValueN` inputs are passive list labels. Rendered text uses
  `TextN.StyledText`, ordered by native `TextOrder`. Inspect hidden row input
  handles before writing. A regression test covers this distinction.
- Refuse subtitle RGB edits on gradient/image fills unless the caller explicitly
  requests `textFillMode:"solid"`.
- Persist harness results before restoration and record restoration failure
  when scripting disconnects.

The initial complete matrix inserted every preset. A focused retest stalled and
Studio exited during Two Line Slide while the old MultiText list-label path was
still loaded in that test process. This records the observed sequence, not a
proven exclusive crash cause. Process exit was verified. The same Studio
executable was recovered automatically with no existing Resolve process, and
the original QA timeline restored. No user reopen was needed. Corrected Letterbox
Text, Simple Two Lines, Two Line Slide and Zipper then passed a fresh four-case
native test. The crash prevents claiming an uninterrupted full acceptance run
or universal 100% restart-free automation.

## Evidence and limits

Local scratch reports: `logs/title-library-full/report.json` (134 initial cases),
`logs/title-library-retest/report.json` (interrupted focused run and failure
annotation), `logs/title-library-final-retest/report.json` (four corrected cases
and restoration readback). `logs/title-library-review/index.html` and
`matrix.json` merge the latest result per template, preserve session failures and
link native full-resolution frames. Subtitle contact sheets are labelled detail
crops; individual cases retain native DRT exports. These artifacts are not
shipped vendor templates.

Reproduce using [the library guide](../guides/title-library-automation.md),
`tests/live_title_library_validation.py` on an already-open disposable synthetic
project, and `scripts/title_library_report.py`. Mac remains untested. Scope
excludes third-party packs, basic Text/Scroll generators, every effect-specific
parameter and exhaustive animation frames. Unsupported/connected controls still
require an observed supported route.

The latest relevant Python run passed 120 tests with one skip; the focused
title/subtitle run passed 22 tests. Subtitle Node tests passed 31 cases, including
explicit gradient-fill handling. Generated API limitations, read/write symmetry
and portable-agent assets/rules passed drift checks. The original synthetic
timeline and playhead were restored after the final live test.
Changes remain local; no release or publication was performed.
