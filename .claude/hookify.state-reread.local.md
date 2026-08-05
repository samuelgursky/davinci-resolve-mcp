---
name: state-reread
event: file
pattern: STATE\.md
action: warn
---
STATE.md is written by concurrent sessions. Re-read it immediately before this write, use
Edit not Write, and merge, never clobber. The 2026-07-30 race ate a whole close; the
2026-08-05 audit session hit three mid-write header rewrites in one day.
