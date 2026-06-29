# Overnight context tune-up — MattFrames editing setup

Paste this into the Claude Code session running in VS Code (the `claude` terminal session).
It is safe to run unattended: it only reads and edits text/config files. It never touches
Resolve, renders, or the outreach bots. Run it in acceptEdits mode. There is NO budget cap
for this run — complete every task.

## Your mandate
Make my editing-workflow context files consistent and fill the gaps, but ONLY where the correct
answer is unambiguous from files already on disk. Where a choice needs MY judgement, do NOT guess —
record it in the morning report instead. Back up any existing file before you change it. At the end,
write a single summary report.

## HARD GUARDRAILS — never do any of these
- Do NOT call any `davinci-resolve` MCP tool. Do NOT open, read, or modify any Resolve timeline or
  project. Do NOT change `.mcp.json` — it was fixed and verified working tonight.
- Do NOT run any render (`render_all.mjs`, `render_alpha.mjs`, Remotion, ffmpeg) or any build.
- Do NOT touch anything under any `*-outreach` folder, `outreach-infra`, or any `.env*` file.
  Do NOT run any bot or script. Do NOT SSH or touch the VPS.
- Do NOT delete files, change git remotes, or push to git.
- Only create or edit Markdown / text / config files as described below.
- Prefer the Read / Edit / Write tools over bash so you can run without stopping. If a step would
  need a risky shell command, skip it and note it in the report instead.

## Before editing any existing file
Make a backup copy first, in the same folder, e.g. `CLAUDE.md` -> `CLAUDE.md.2026-06-25.bak`.
Only back up files you are about to change. New files need no backup.

---

## TASK 1 — Make the Chloé palette a single source of truth (highest priority)
- The canonical palette lives ONLY in `~/Developer/remotion-projects/src/chloe-palette.ts`. Read it.
- `~/Developer/remotion-projects/CLAUDE.md` currently hardcodes an OLD palette that is wrong on every
  value (roughly: gold #F2C94C, teal #4A9EB8, green #4A7A50, orange #E07840, bg #1E1E1E, no yellow).
  These stale hexes are the bug: any agent that trusts them ships graphics in last season's colours.
- Replace that palette block in `CLAUDE.md` so it contains NO hex values at all. Instead state plainly:
  the palette is defined only in `src/chloe-palette.ts`; always read colours from that file; never copy
  hex values into this file because they drift. You may list the colour KEYS by name only
  (gold, teal, green, orange, bg, yellow, font), each pointing to "see chloe-palette.ts" — but no hexes.
- Goal: there is exactly one place colours can ever live again.

## TASK 2 — Give trainlist-graphics real starting context
- `~/Developer/trainlist-graphics/` is an active project (own `src/`, own render script) but has no
  `CLAUDE.md`, so an agent starting there is blind.
- First check whether trainlist-graphics has its OWN palette file in its `src/`.
  - If yes: point its colours to that file.
  - If no, and its files confirm it is a Chloé project: point colours to
    `~/Developer/remotion-projects/src/chloe-palette.ts`.
  - If you cannot confirm which palette is correct: do NOT guess. Put the question in the morning
    report and leave colours as a "CONFIRM with Matt" note.
- Create `~/Developer/trainlist-graphics/CLAUDE.md`, modelled on the STRUCTURE of
  `~/Developer/remotion-projects/CLAUDE.md`, but short and pointer-based. Include only facts you can
  verify from this project's own files. Do NOT restate the render command or any marker/clip legend as
  fact here — for those, write "see morning report / confirm with Matt".

## TASK 3 — Relax the cost cap (my explicit instruction)
- In `~/.claude/CLAUDE.md` there is a rule capping cost at about $5 per session. Replace it with this
  nuance: there is NO per-session dollar cap for Claude Code work running on my Max subscription, so run
  tasks to completion; stay cost-conscious ONLY for work that bills the Anthropic API directly (the
  outreach bots and any VPS scripts), where real per-token money applies.
- Leave any "/compact after each batch" habit untouched (that is about context, not cost).

---

## REPORT-ONLY tasks — investigate and write up, but DO NOT change anything
These need my decision. Read, form a view, and write it into the morning report. Edit nothing here.

### A. Render command contradiction
- `~/.claude/CLAUDE.md` contradicts itself: one line says render via `node render_alpha.mjs [ComponentID]`;
  another says `render_all.mjs` is the ONLY path and to never chain `render_alpha.mjs` manually.
- Read both `render_all.mjs` and `render_alpha.mjs` in `~/Developer/remotion-projects` (and
  trainlist-graphics if present) to see what each does and which is current/canonical. Give me your
  evidence-based recommendation for which rule should win. Do not edit the rule.

### B. Active-project pointer
- `~/Developer/remotion-projects/CLAUDE.md` pins the project as "curent project updated" (note the typo).
  The live Resolve project tonight is `056_MCS_ALASKA`, timeline `ASSETS`.
- Ask me: should the active project be tracked in `CLAUDE.md` or in `PROJECT_BRIEF.md`? Flag the typo.
  Do not change it.

### C. Marker legend vs clip-colour triage
- `remotion-projects/CLAUDE.md` lists a MARKER legend (Green=HERO, Blue=BROLL, Yellow=GRAPHIC,
  Red=DELETE/TRIM, Purple=MUSIC). Separately, my clip-colour triage is a DIFFERENT system
  (Apricot=B-roll, Purple=B-roll with usable audio, Uncolored=A-roll, Brown=trash).
- These are two different things (timeline markers vs clip colours). Ask me to confirm both are current,
  and whether the global `CLAUDE.md` should carry both so they are visible when I work outside
  remotion-projects. Do not change either.

### D. hyperframes-projects (optional)
- It has no `CLAUDE.md`. Note it as optional — only worth adding if I actually work there. Do not create
  one now.

### E. MCP "setup issue"
- Do NOT run fixes. Just note that I should run `/doctor` (or `/mcp`) with you in the morning to see what
  the one setup note is; it is most likely the leftover dual-copy path and is cosmetic now that
  `.mcp.json` points at the Developer copy.

---

## FINAL — write the report and summarise
- Write `~/Desktop/MORNING_DECISIONS.md` containing:
  1. Exactly what you changed tonight: every file edited or created, and where the `.bak` backups are.
  2. The decision items A–E above, each with options laid out so I can answer fast.
  3. Anything else stale, duplicated, or risky you noticed while reading (read-only observations).
- Then print a final summary in this session: files changed, backups made, and the path to the report.

That is the whole job. Stop when done.
