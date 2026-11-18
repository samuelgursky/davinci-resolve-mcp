---
name: house-style
description: The editorial and finishing preferences this project's work is judged against — cut rhythm, shot selection, delivery conventions, and the corrections that have already been given. Load before assembling, restructuring, or refining any cut so the same note does not have to be given twice.
user-invocable: false
---

# House Style

The craft guides in `docs/guides/` describe editing in general. This file
describes **how this editor wants it done** — the accumulated, specific
corrections that would otherwise have to be repeated every session.

Read it before any edit task. Append to it whenever a correction is given.

## The capture protocol

This file is only worth what gets written into it. When the user corrects an
editorial decision — rejects a cut, changes a shot choice, adjusts a duration,
says "not like that" — do not just fix it. Fix it, then add the rule here.

A useful entry has three parts:

- **The rule**, stated as an instruction, not an observation.
- **Why**, in the user's terms — what it was in service of.
- **The trap**, if there is one: what makes it easy to get wrong.

Write rules that are falsifiable. "Cut on motion" is a rule; "make it feel
dynamic" is not. If a correction is one-off and situational, it does not belong
here — this file is for what generalizes.

When an entry turns out to be wrong or too broad, edit it. A stale rule
confidently followed is worse than no rule.

---

## Pacing and rhythm

<!-- Hold lengths, when to cut early, what "too long" means for this material. -->

_Not yet captured._

## Shot selection

<!-- What earns a place in the cut; what gets dropped even when it's a good shot. -->

_Not yet captured._

## Cut points

<!-- Cut on motion vs on rest, handles, how much air before and after a beat. -->

_Not yet captured._

## Structure and openings

<!-- How a piece starts, what the first frames have to do, how it lands. -->

_Not yet captured._

## Rejected by default

Things not to add unless explicitly asked. Seeded from the rough-cut deliverable
contract in the `resolve-rough-cut` skill, which exists because this work gets
thrown away:

- Titles, captions, and text cards
- Transitions (an assembly is hard cuts)
- Effects and speed ramps
- Music beds
- Grading on a cut that was asked for as an assembly

## Delivery conventions

<!-- Aspect ratios, timeline naming, versioning, where renders go. -->

### Word-by-word subtitles: split the existing cards, do not re-transcribe

When word-for-word captions are asked for and a subtitle track already exists,
split those cards into one word each. Do not run `CreateSubtitlesFromAudio`
again to get word-level timing.

**Why:** the existing track is the transcript that has already been read and
lived with. Re-transcribing throws that away and returns a different wording,
including different mistakes, for no gain the editor asked for.

**The trap:** Resolve's API cannot write subtitle items — `CreateSubtitlesFromAudio`
is the only path that creates them, and it always transcribes. So splitting has
to leave the tool: build an SRT and let the editor import it (File > Import >
Subtitle). Offering "regenerate with chars-per-line = 1" as the convenient route
is offering to discard the transcript.

**Timing:** divide each card's own span between its words by character length,
so the speech timing the card already carries is never stretched or shifted.
Hold each word at least 3 frames (120 ms) or it cannot be read; take the extra
frames from the longest words in the same gapless run, so the run's start and
end stay put.

### Motion graphics: native Fusion, and full-frame

When a spoken statement is illustrated with motion graphics, build it as a
**native Fusion comp**, not as a pre-rendered PNG sequence, and let it take the
**whole 9:16 frame** as a cutaway rather than sitting as an overlay over the
speaker.

**Why:** a Fusion comp stays editable in Resolve after handover — a baked
sequence has to be re-rendered and re-imported for every change. And in vertical
format a graphic that shares the frame with a talking head gets too small to
read in the seconds it is on screen; the audio carries the speaker while the
picture does the explaining.

**The trap:** `Insert*IntoTimeline` cannot choose a track, so a comp built this
way lands on V1 and cannot be moved. Build the comp on its own timeline (set
that timeline to 1080x1920 — it inherits the project's 1920x1080 otherwise),
then place THAT timeline's media pool item with `AppendToTimeline` clipInfo
`trackIndex`/`recordFrame`. Everything stays editable through the nesting.

---

## Where personal grading taste lives

Colour and look preferences are **not** kept here — this file travels with the
repository. Grading taste lives in the user-level `colorist-assistant` skill and
in persistent memory. Load those for look selection, grade transfer, and the
Resolve API traps around them.

If any entry below would be specific to one person rather than to this project's
work, it belongs in the user-level skill instead, and this file should be
gitignored rather than committed.
