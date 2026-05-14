# Resolve Editorial Decision Guide

This guide is the project-owned editorial context for the DaVinci Resolve MCP.
Use it when analysis moves from "what is in the media?" to "what should the edit
do next?" It is deliberately self-contained so the MCP does not depend on any
personal or external skill library.

## Core Priorities

Editorial decisions should serve this order:

1. Emotion and story
2. Clarity of thought or action
3. Rhythm and timing
4. Eye trace and screen geography
5. Continuity and technical polish
6. Coverage variety

Good coverage is useful only when it helps the viewer understand, feel, or
anticipate something. When those goals conflict, keep the moment that carries
the clearest emotional or narrative charge.

## Analysis Memory

Before running new analysis or suggesting edits, inspect what the active project
already knows:

- `media_analysis(action="summarize")`
- `media_analysis(action="get_report")` for known manifests or clip reports
- `timeline(action="probe_timeline_structure")`
- `timeline(action="story_spine_report")`
- `timeline(action="source_range_report")`
- `timeline_markers(action="get_all")`
- `media_analysis(action="review_timeline_markers")` when marker imagery matters

Reuse existing reports unless they are stale, incomplete, or missing a modality
the user explicitly needs. A new request for edit advice is not automatically a
reason to re-run visual analysis if the prior report already has current
technical data, motion/keyframe evidence, and useful visual descriptions.

## Frame Choice

Find the decisive frame, not just the technically clean frame. Useful cut points
often occur when a face changes intention, a hand completes a thought, a gaze
lands, a movement resolves, or the audience has received the needed information.

For dialogue and reaction:

- Prefer the reaction when it carries the meaning.
- Let sound lead picture when the incoming idea needs setup.
- Let picture lead sound when surprise, reveal, or anticipation matters.
- Avoid cutting away before a thought has landed unless compression is the
  point.

For movement:

- Cut on completed or motivated motion.
- Use motion peaks as candidates, then verify the frame visually.
- Treat scene detection and variance as guardrails, not the editor.

## Sound First

For interviews, dialogue, comedy, and short-form editorial, build the audio spine
before chasing visual variety:

- Premise: what the viewer needs to understand first
- Setup: the pressure, context, or contrast
- Turn: the new idea, contradiction, reveal, or escalation
- Button: the final image, line, beat, or release

When trimming, preserve complete thoughts and clean transitions in breath,
tone, and room sound. Visual cutaways can hide picture edits, but they cannot
fix a broken idea.

## Finished-Video Guardrails

When analyzing an already-finished video, do not treat every detected cut as an
edit instruction. Use black frames, flash frames, scene-change clusters, silence,
and motion spikes to find regions that need verification.

Finished-video analysis should produce:

- Likely scene or section boundaries
- Ranges to avoid because of black, flash, silence, or corrupt frames
- Audio-led story beats
- Visual evidence at markers and cut points
- Questions where the image contradicts the label or transcript

## Marker And Contact-Sheet Review

Markers are memory, not truth. When a marker name, note, or beat label matters,
verify it against a Resolve-rendered frame:

- Generate a marker contact sheet.
- Compare each label with the visible frame.
- Rename, move, or downgrade markers that do not match the image.
- Keep marker notes concrete enough that another editor can act on them.

Use contact sheets for orientation and review. `analyze_media` defaults to
chat-context vision for visual/editorial analysis when the MCP client supports
sampling; pass `include_visuals=false` for a no-visual run. Use direct assistant
inspection when the user provides or requests specific still/contact-sheet
review.

## Edit Variant Safety

Before making or changing a timeline variant:

- Check timeline start frame and timecode; many Resolve timelines start at
  `01:00:00:00`, often frame `108000` at 30 fps.
- Prefer dry runs for range-based operations.
- Keep source media untouched.
- Use positioned appends and explicit source ranges.

After changing a variant:

- Run `timeline(action="detect_gaps_overlaps")`.
- Run `timeline(action="source_range_report")`.
- Review thumbnails at important markers and cut points.
- Confirm the audio spine still reads.

## Response Shape

When reporting analysis back to the user, make it editor-usable:

- What was analyzed
- Whether prior analysis was reused or refreshed
- Technical warnings that affect editing
- Motion and variance summary
- Visual content and best moments
- Transcript or sound notes
- Avoid ranges
- Concrete next actions

Avoid overclaiming from sparse evidence. If the tool only sampled a few frames,
say so and recommend the specific next verification step.
