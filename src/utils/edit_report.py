"""Human-readable reports for edit plans.

Every craft role that touches a cut keeps written artifacts as a primary
deliverable — the assistant editor's ingest log and known-issues list, the
assistant colorist's session-prep summary, the online editor's technical handoff
document, the post supervisor's status report. None of them consider the work
finished when the change is made; it is finished when someone else can see what
was decided.

This tool changes timelines and, until now, said very little about it. A JSON
plan is not a report: `keep_ranges: [...]` with 340 entries tells an editor
nothing, and the rational response to a machine you cannot audit is to re-check
everything by hand — which is exactly the cost the tool was supposed to remove.
One reviewer of the first public tutorial put it plainly after watching an
automated pass: "I feel like at this stage I will be micromanaging Claude's
edits longer than actually doing everything myself."

So the contract is that a plan explains itself:

- **What would change**, in seconds and shots, not frame arrays.
- **Why**, per cut, in the vocabulary an editor already uses.
- **What was deliberately left alone**, which is invisible in the output and is
  the half people distrust most.
- **What could not be checked** — never folded into "fine".
- **What needs a human**, separated from what does not.

Rendered as Markdown because it has to survive being pasted into a Slack
message, an email to a post supervisor, or a review doc, none of which render
JSON.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence


def _plural(count: int, singular: str, plural: Optional[str] = None) -> str:
    """"1 item" / "2 items". A report that cannot count reads as careless."""
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count} {word}"

#: Confidence is reported by several unrelated subsystems — gate calibration,
#: pause classification, false-start heuristics — each with its own vocabulary.
#: A reader does not care which produced it; they care whether to look.
CONFIDENCE_ORDER = {"high": 0, "computed": 0, "medium": 1, "low": 2, "unknown": 3}


def confidence_band(value: Optional[str]) -> str:
    """Normalize a subsystem's confidence word into one of high/medium/low."""
    raw = str(value or "").strip().lower()
    if raw in ("high", "computed", "certain"):
        return "high"
    if raw in ("medium", "moderate", "marginal"):
        return "medium"
    if raw in ("low", "heuristic", "uncertain"):
        return "low"
    return "unknown"


def _fmt_seconds(value: Any) -> str:
    try:
        total = float(value)
    except (TypeError, ValueError):
        return "?"
    if total < 60:
        return f"{total:.1f}s"
    minutes, seconds = divmod(total, 60)
    return f"{int(minutes)}m {seconds:04.1f}s"


def _fmt_tc(frame: Any, fps: float) -> str:
    """Frames → HH:MM:SS:FF. Editors navigate by timecode, not frame counts."""
    try:
        f = int(frame)
    except (TypeError, ValueError):
        return "??:??:??:??"
    rate = int(round(fps)) if fps and fps > 0 else 24
    hours, rem = divmod(f, rate * 3600)
    minutes, rem = divmod(rem, rate * 60)
    seconds, frames = divmod(rem, rate)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def _section(title: str, lines: Sequence[str]) -> List[str]:
    if not lines:
        return []
    return [f"### {title}", "", *lines, ""]


def render_plan_report(plan: Mapping[str, Any], *, max_detail_rows: int = 25) -> str:
    """Render any edit-engine plan as a Markdown report a human can act on.

    Unknown plan kinds still produce a useful report rather than an error — a
    report that refuses to render is worse than a generic one, because the
    fallback is reading raw JSON.
    """
    kind = str(plan.get("kind") or "plan")
    fps = float(plan.get("timeline_fps") or 24.0)
    timeline = plan.get("timeline_name") or "(unnamed timeline)"
    out: List[str] = [f"# {kind.replace('_', ' ').title()} — {timeline}", ""]

    out.extend(_headline(plan, kind, fps))
    out.extend(_changes_section(plan, fps, max_detail_rows))
    out.extend(_left_alone_section(plan))
    out.extend(_unverified_section(plan))
    out.extend(_needs_a_human_section(plan))

    note = plan.get("note")
    if note:
        out.extend(["---", "", str(note), ""])
    return "\n".join(out).rstrip() + "\n"


def _headline(plan: Mapping[str, Any], kind: str, fps: float) -> List[str]:
    bits: List[str] = []
    if plan.get("marker_count") is not None:
        bits.append(
            f"**{plan['marker_count']} markers proposed**, "
            f"{_fmt_seconds(plan.get('total_dead_seconds'))} of dead space total. "
            "Nothing is cut and no marker is written yet."
        )
    if plan.get("lift_count") is not None:
        bits.append(
            f"**{plan['lift_count']} cuts proposed**, "
            f"{_fmt_seconds(plan.get('estimated_removed_seconds'))} removed."
        )
    if plan.get("tightness"):
        bits.append(
            f"Tightness **{plan['tightness']}**"
            + (" (the default — a first assembly is meant to run long)."
               if plan["tightness"] == "generous" else ".")
        )
    return [*bits, ""] if bits else []


def _cut_rows(plan: Mapping[str, Any], fps: float, limit: int) -> List[str]:
    rows: List[str] = []
    entries: List[Mapping[str, Any]] = list(plan.get("lifts") or []) or list(plan.get("markers") or [])
    if not entries:
        return rows
    rows.append("| At | Length | Confidence | Why |")
    rows.append("|---|---|---|---|")
    ordered = sorted(entries, key=lambda e: e.get("timeline_start_frame") or 0)
    for entry in ordered[:limit]:
        start = entry.get("timeline_start_frame")
        if entry.get("duration_frames") is not None:
            length = float(entry["duration_frames"]) / (fps or 24.0)
        else:
            length = (
                (entry.get("timeline_end_frame") or 0) - (start or 0)
            ) / (fps or 24.0)
        reason = (
            entry.get("rationale")
            or entry.get("note")
            or entry.get("classification_reason")
            or "—"
        )
        band = confidence_band(
            entry.get("confidence")
            or (entry.get("evidence") or {}).get("confidence")
            or "high"
        )
        rows.append(
            f"| `{_fmt_tc(start, fps)}` | {_fmt_seconds(length)} | {band} | "
            f"{str(reason).replace('|', '/').strip()} |"
        )
    if len(ordered) > limit:
        rows.append(f"| … | | | _{len(ordered) - limit} more not shown_ |")
    return rows


def _changes_section(plan: Mapping[str, Any], fps: float, limit: int) -> List[str]:
    return _section("What would change", _cut_rows(plan, fps, limit))


def _left_alone_section(plan: Mapping[str, Any]) -> List[str]:
    """What was deliberately preserved.

    This is the half people distrust, because it is invisible in the output: a
    beat that was correctly kept looks exactly like a beat nobody considered.
    """
    lines: List[str] = []
    preserved = plan.get("preserved") or []
    for item in preserved:
        lines.append(f"- {item}")
    if plan.get("tightness") == "generous":
        lines.append(
            "- Short gaps were left in by design at this tightness. Re-run with "
            "`tightness='balanced'` or `'tight'` to remove more."
        )
    if plan.get("breathing_room_preserved"):
        lines.append(
            f"- {plan['breathing_room_preserved']} pauses after a sentence were kept "
            "as breathing room — the beat that lets a line land."
        )
    return _section("Deliberately left alone", lines)


def _unverified_section(plan: Mapping[str, Any]) -> List[str]:
    """Never fold "could not check" into "checked and fine"."""
    lines: List[str] = []
    for skip in plan.get("skipped") or []:
        name = skip.get("item") or skip.get("clip_id") or "(unnamed)"
        lines.append(f"- **{name}** — {skip.get('reason') or 'not analyzed'}")
    handles = plan.get("handle_report") or {}
    for unver in handles.get("unverified") or []:
        lines.append(
            f"- **{unver.get('clip_id')}** — {unver.get('reason')}"
        )
    if lines:
        lines.append("")
        lines.append(
            "_These were **not** analyzed. That is not the same as clean._"
        )
    return _section("Not verified", lines)


def _needs_a_human_section(plan: Mapping[str, Any]) -> List[str]:
    lines: List[str] = []
    handles = plan.get("handle_report") or {}
    if handles.get("violation_count"):
        lines.append(
            f"- **Handles:** {handles['violation_count']} keep ranges are short of "
            f"media at the join. {handles.get('note', '').strip()}"
        )
    entries = list(plan.get("lifts") or []) + list(plan.get("markers") or [])
    low = [e for e in entries if confidence_band(e.get("confidence")) == "low"]
    if low:
        lines.append(
            f"- **{_plural(len(low), 'low-confidence call')}** — review before accepting."
        )
    marginal = [
        c for c in (plan.get("calibrations") or [])
        if isinstance(c, dict) and c.get("usable") and not c.get("quiet_is_digital_silence")
        and isinstance(c.get("separation_db"), (int, float)) and c["separation_db"] < 18
    ]
    if marginal:
        lines.append(
            f"- **{_plural(len(marginal), 'item')} had speech and room close together**, "
            "so the silence gate is usable but not confident there."
        )
    if plan.get("warning"):
        lines.append(f"- **Warning:** {plan['warning']}")
    return _section("Needs a human", lines)


#: Audit payloads that are not edit plans — they carry criteria and/or graded
#: findings rather than cuts. Rendered by `render_audit_report`.
AUDIT_KINDS = ("rule_of_six_audit", "conform_lint", "sound_density_audit", "setup_sheet")


def render_audit_report(audit: Mapping[str, Any]) -> str:
    """Render an audit as Markdown — criteria, findings, and what was not checked.

    Audits differ from plans in that they propose no change, so the sections
    differ too: there is no "what would change", and the load-bearing part is
    what the audit *could not* look at. That section is mandatory here for the
    same reason it is everywhere else in this codebase — a reader who cannot see
    the gaps will read a short report as a clean one.
    """
    kind = str(audit.get("kind") or "audit")
    title = kind.replace("_", " ").title()
    where = audit.get("timeline_name") or audit.get("media_path") or ""
    out: List[str] = [f"# {title}" + (f" — {where}" if where else ""), ""]

    coverage = audit.get("coverage") or {}
    if coverage.get("statement"):
        out += [f"**{coverage['statement']}**", ""]

    criteria = audit.get("criteria") or []
    if criteria:
        out += ["### Criteria", "", "| Weight | State | Criterion | |", "|---|---|---|---|"]
        for row in criteria:
            out.append(
                f"| {float(row.get('weight', 0)) * 100:.0f}% | `{row.get('state')}` | "
                f"{str(row.get('label') or row.get('criterion')).split(' — ')[0]} | "
                f"{str(row.get('detail') or '').replace('|', '/')} |"
            )
        out.append("")

    findings = audit.get("findings") or []
    if findings:
        out += ["### Findings", ""]
        for finding in findings:
            head = finding.get("summary") or finding.get("code") or "finding"
            tag = finding.get("severity") or finding.get("criterion") or ""
            out.append(f"- **{head}**" + (f" _({tag})_" if tag else ""))
            if finding.get("detail"):
                out.append(f"  {finding['detail']}")
        out.append("")

    out += _audit_not_checked(audit)

    for key, heading in (("threshold_provenance", "Threshold"),
                         ("method", "Method"),
                         ("grouping_basis", "Grouping"),
                         ("source_caveat", "Source"),
                         ("ordering", "Ordering")):
        if audit.get(key):
            out += [f"_{heading}: {audit[key]}_", ""]

    if audit.get("note"):
        out += ["---", "", str(audit["note"]), ""]
    return "\n".join(out).rstrip() + "\n"


def _audit_not_checked(audit: Mapping[str, Any]) -> List[str]:
    """Everything the audit did not or could not look at. Never optional."""
    lines: List[str] = []
    for entry in audit.get("not_checked") or []:
        lines.append(f"- {entry}")
    for entry in audit.get("unanalyzed") or audit.get("unusable") or []:
        if isinstance(entry, Mapping):
            lines.append(f"- **{entry.get('clip') or entry.get('item')}** — {entry.get('reason')}")
        else:
            lines.append(f"- {entry}")
    not_implemented = [
        r for r in (audit.get("criteria") or []) if r.get("state") == "NOT_IMPLEMENTED"
    ]
    if not_implemented:
        lines.append(
            "- Criteria not computed by this build: "
            + ", ".join(str(r["criterion"]) for r in not_implemented)
        )
    if not lines:
        return []
    lines.append("")
    lines.append("_Not looked at is not the same as clean._")
    return _section("Not checked", lines)


def render_any(payload: Mapping[str, Any], *, max_detail_rows: int = 25) -> str:
    """Render a plan or an audit, whichever this is."""
    if str(payload.get("kind") or "") in AUDIT_KINDS or payload.get("criteria"):
        return render_audit_report(payload)
    return render_plan_report(payload, max_detail_rows=max_detail_rows)


def summarize_for_chat(plan: Mapping[str, Any]) -> str:
    """One-line summary for a chat reply, where a full report is too much."""
    kind = str(plan.get("kind") or "plan").replace("_", " ")
    if plan.get("marker_count") is not None:
        head = (
            f"{plan['marker_count']} dead-space markers proposed "
            f"({_fmt_seconds(plan.get('total_dead_seconds'))} total)"
        )
    elif plan.get("lift_count") is not None:
        head = (
            f"{plan['lift_count']} cuts proposed "
            f"({_fmt_seconds(plan.get('estimated_removed_seconds'))} removed)"
        )
    else:
        head = kind
    caveats: List[str] = []
    if plan.get("skipped"):
        caveats.append(f"{_plural(len(plan['skipped']), 'item')} not analyzed")
    handles = plan.get("handle_report") or {}
    if handles.get("violation_count"):
        caveats.append(f"{handles['violation_count']} short of handles")
    return head + (f" — {', '.join(caveats)}" if caveats else "")
