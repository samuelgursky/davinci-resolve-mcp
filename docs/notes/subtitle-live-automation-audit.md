# Live subtitle automation audit — 2026-10-08

The `feat/subtitle-track-support` branch added useful caption/preset codecs but
routed effect edits only through Project.db. The subsequent full-quit guard was
correct for that database route; it did not establish that a running Resolve
could not apply the same effect through native interchange or its own UI.

## Corrected paths

| Finding | Correction |
|---|---|
| Word Highlight edits exposed only as offline DB actions | Live `timeline_ai.set_subtitle_preset` exports native DRT, changes the exported holder, imports/selects a new revision; original retained |
| Applying an effect required a reference in another user project | Bundle a native holder from synthetic QA with explicit reference settings and no media |
| Subtitle `SetProperty` refusal sent every request to full-quit DB patching | Error now routes effects to the live action; text/timing to live UI or explicit offline maintenance |
| Skills and kernels directed animation work to the offline server | Updated audio/Fusion portable skills, kernels, operating reference, advanced README and subtitle guide |
| Update panel told users to restart Resolve for Python code updates | Instructions now distinguish MCP-server reload from Resolve application restart |
| Granular connection helper launched another instance after scripting failed | Match compound guard: running/unknown process state refuses a second launch |
| Bridge installer prescribed a restart before trying the Scripts menu | Check the installed scripts in the running application first |
| Codec readback could report success before Resolve parsed the composition | Re-export the imported timeline and compare its retained controls; also compare live edit inventory |

Direct DB-write safety guards remain intact. Never patch the database of an
open project, including a project loaded earlier in the same Resolve session.
Native interchange avoids that cache hazard by asking Resolve itself to import
the changed content.

## Evidence and limits

Live validation on Studio 21.1.0.17/Windows exercised the public dispatcher,
applied Word Highlight to a bare subtitle track and verified the imported
controls through native re-export. Seven caption bounds, video/audio bounds and
media IDs matched. Rendered frames showed the requested white/magenta word
phases and a blank caption gap. Incremental colour, size and position edits also
worked, including the user's random-colour demonstration, without a restart.
See [subtitle-track editing](../guides/subtitle-track-editing.md) and the
synthetic-only live acceptance script.

That original acceptance certified Word Highlight and unchanged Lollipop
application, not universal video automation. The subsequent installed-library
expansion discovers presets, captures their native definitions without UI drags,
and maps common literal subtitle font, size, position and text RGBA controls.
Ordinary title text now includes shape/3D/MultiText and supported text modifiers
without flattening their animation. See
[title library automation](../guides/title-library-automation.md) for the test
harness and its measured limits, and the subsequent
[134-preset acceptance record](title-library-acceptance.md), including its
ordinary-title crash/recovery. Unmapped subtitle effect controls and caption
text/timing changes still need observed live UI automation unless another supported
route is available. Current granular-only clients do not expose the new compound
action; use the compound server or the shared Python helper. Installed fonts,
templates, speech models and Resolve build differences remain capabilities to
probe, not assumptions.

Remaining full-quit references under extension-authoring, offline DB maintenance
and crash recovery describe distinct operations. Newly installed Fuses and
some extension categories genuinely have restart requirements. Routine video
edits should use already available tools or native imported compositions rather
than turn extension installation into a repeated step. Do not erase those
constraints to promise "100% automated".

Code already loaded in an MCP process does not automatically change after a
Git update. Reload that server/bridge runtime when needed while preserving the
running Resolve session; reconnect to the existing application. Do not treat a
sandbox's inability to see or script Resolve as evidence that Resolve is closed.

## Validation record

- 169 Python tests in the relevant subtitle, safety, connection, lifecycle,
  dashboard and documentation suites: passed, one skipped. A subsequent focused
  run of 53 tests included the added imported-control-loss regression and passed.
- 28 Node subtitle codec/DB/native-timeline tests passed. The two new native
  timeline tests also passed independently after the readback helper was added.
- Native API parity audit passed (existing undocumented-method advisories only).
- Generated API-limitations, read/write-symmetry and portable-agent assets checked.
- NPM dry-run package inspection confirmed the live bridge, codec helper and
  native reference asset are included.
- Windows test-fixture corrections: ps fixtures now select their intended
  platform, macOS path assertions normalize separators, and dashboard temporary
  SQLite connections close before their directories are removed.

Changes are local on `feat/subtitle-track-support`; no release or publication
was performed. Studio stayed open during the original subtitle acceptance;
the later full-library title test has the interruption documented above.
Existing MCP processes still need to load the
updated Python code to expose the new action; that is separate from restarting
Resolve.
