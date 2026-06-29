# Palette consolidation + finish the morning items

Run in the Claude Code session in VS Code (acceptEdits). I'm awake and watching, so complete it.
Decision is made: V2 (the current refresh) is the active palette everywhere now. V1 is kept on record,
not deleted.

## Guardrails
- Do NOT call any `davinci-resolve` MCP tool, open or modify any Resolve timeline, or change `.mcp.json`.
- Do NOT run a full render (`render_all.mjs`, `render_alpha.mjs`, Remotion bundle/output). Do NOT touch
  any `*-outreach` folder, `outreach-infra`, `.env*`, the bots, or the VPS.
- Do NOT delete files or push to git.
- You MAY edit the files named below, including ONE code file (`trainlist-graphics/src/theme.ts`),
  because moving trains to V2 is the explicit goal.
- Back up every existing file before you change it (e.g. `theme.ts` -> `theme.ts.2026-06-25.bak`).

## Context you can trust
- `~/Developer/remotion-projects/src/chloe-palette.ts` currently holds Chloé's REFRESHED colours
  (the 2026-06-17 set). Those are V2.
- The OLD colours (V1) are recoverable from `~/Developer/remotion-projects/CLAUDE.md.2026-06-25.bak`
  (roughly gold #F2C94C, teal #4A9EB8, green #4A7A50, orange #E07840, bg #1E1E1E). Read the EXACT values
  from that .bak file; do not trust these approximations.
- Both palettes are the same client's (Chloé's) real brand looks. Keep both. V2 is active.

## TASK 1 — chloe-palette.ts becomes the master, holding V1 + V2
- FIRST, check how the palette is currently imported across `~/Developer/remotion-projects/src`
  (what symbol the components import). You MUST preserve that exact export so current components keep
  working unchanged. Do not rename or remove any existing export.
- In `chloe-palette.ts`, define two clearly named, commented sets:
  - `chloePaletteV1` = the old values (exact hexes read from `CLAUDE.md.2026-06-25.bak`; if V1 had no
    yellow, note that in a comment).
  - `chloePaletteV2` = the current values already in this file (the 2026-06-17 refresh).
- Add `export const activePalette = chloePaletteV2;` with a comment: "Switch the whole brand look by
  changing this one line." Point the previously-used export name at `activePalette` so nothing breaks.
- Net effect for remotion graphics: zero visual change (V2 is already what's in the file). This task is
  pure restructure so both looks are on record and switchable.
- After editing, confirm by reading the importing files that the symbol they use still resolves.
  Do NOT run a render.

## TASK 2 — PROJECT_BRIEF.md: drop hardcoded hexes, fix the project name
- In `~/Developer/remotion-projects/PROJECT_BRIEF.md`: remove the hardcoded palette hexes; replace with a
  pointer line — colours live only in `src/chloe-palette.ts` (active = V2).
- This file is now where the active Resolve project is tracked. Set it to the live project:
  `056_MCS_ALASKA`, timeline `ASSETS`. Fix the "curent" typo wherever it appears.
- In `~/Developer/remotion-projects/CLAUDE.md`: remove the stale project pin ("curent project updated")
  and replace with "active project is tracked in PROJECT_BRIEF.md".

## TASK 3 — Move the trains project to V2
- `~/Developer/trainlist-graphics/src/theme.ts` holds the OLD colours. Back it up, then update its colour
  values to the V2 values (from `chloe-palette.ts`) so trains renders in the refreshed look.
- Keep theme.ts's existing structure; change only the colour values. Do NOT refactor it to import across
  projects (separate project, cross-import is fragile).
- Add a comment in theme.ts: "These mirror chloePaletteV2 in remotion-projects/src/chloe-palette.ts.
  trainlist-graphics is a separate project, so if V2 changes, update here too."
- Flag for me in the report: the next trains render will come out in the new colours. That is intended.

## TASK 4 — Reword the render rule (no real conflict)
- In `~/.claude/CLAUDE.md`, the render rule reads like a contradiction but isn't: `render_all.mjs` reads
  `RENDER_QUEUE.json` and loops, calling `node render_alpha.mjs <id> <output>` per entry. Reword to:
  "render_all.mjs = batch render (the queue); render_alpha.mjs = a single component. They are not in
  conflict." One or two lines.

## FINAL
- Update `~/Desktop/MORNING_DECISIONS.md`: list every file changed and where each `.bak` is. State plainly
  that V2 is now active everywhere, V1 is preserved in chloe-palette.ts, and the only spot that keeps its
  own palette copy is trains' theme.ts (separate project). Note what is still pending my call (the
  marker-legend vs clip-colour question).
- Print a final summary in the session: files changed, backups made, and confirm V2 is active and the
  existing imports still resolve.

Stop when done.
