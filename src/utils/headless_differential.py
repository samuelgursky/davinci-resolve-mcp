"""Differential qualification for headless Resolve: one application, two modes.

`-nogui` is documented in Blackmagic's own scripting README as "the user
interface is disabled. However, the various scripting APIs will continue to work
as expected." That sentence is wrong in ways that cost real sessions: Gallery
still export, for one, fails headless and works in the GUI — a fact this
repository learned the expensive way and recorded in a design note rather than
anywhere an agent would find it.

The problem with "some things don't work headless" as institutional knowledge is
that it is unfalsifiable and unactionable. An agent cannot reason with it. So
this module makes it a *measurement*: run the same probe set against the same
Resolve build twice — once with a UI, once without — and difference the two.
Anything that changes is caused by the mode, because nothing else did.

## Why a differential and not a headless-only run

A headless-only run cannot distinguish "this fails without a UI" from "this
fails, full stop". Both produce False. Only the GUI baseline separates a
mode-dependent failure from a call that was never going to work — and the two
demand opposite things from an agent: the first says *retry with a UI*, the
second says *stop*.

## Verdicts

Each probe or scenario observation lands in exactly one bucket:

  - ``parity``            — identical in both modes. The overwhelming majority.
  - ``headless_degraded`` — worked in the GUI, failed or returned less headless.
                            The findings that matter; these become api_truth
                            entries so agents stop retrying what cannot work.
  - ``gui_degraded``      — worked headless, failed in the GUI. Rare and
                            interesting (modal dialogs block the GUI, not
                            headless), so it is a first-class verdict rather
                            than noise folded into ``divergent``.
  - ``both_failed``       — failed identically in both. Not a headless finding;
                            belongs to the general limitations report.
  - ``divergent``         — both succeeded but returned different values, and
                            the difference is not explained by volatility.
  - ``untested``          — present in one run only, or skipped. Counted and
                            listed, never silently dropped: a coverage gap that
                            renders as a blank cell reads as parity.

## What "the same" has to tolerate

Handles differ between sessions by construction and are normalised to their
shape by `bridge_differential.normalise`. Beyond that, two *sequential* runs of
one machine differ in ways two transports into one live session do not: project
names carry timestamps, temp paths differ, timecodes advance, and the GUI run
leaves the application on whatever page it was on. Those are named in
`SESSION_VARIANT_KEYS` and compared by type. Everything else is compared exactly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from src.utils.bridge_differential import VOLATILE_METHODS

#: Observations that differ between any two sequential runs regardless of mode,
#: because the harness or the clock moved them. Compared by type, not value.
#: Named individually rather than pattern-matched, so the exemption list stays
#: auditable — a regex over "path" or "name" would quietly excuse real findings.
SESSION_VARIANT_KEYS = frozenset({
    "project_name",
    "timeline_name",
    "workspace",
    "output_path",
    "still_path",
    "export_path",
    "elapsed_seconds",
    "startup_seconds",
    "current_timecode",
    "unique_id",
    # Every handle Resolve mints carries a fresh UUID, and the scratch project's
    # name and clip timestamps are stamped by this harness. Comparing them by
    # value produced eleven guaranteed "divergent" rows per run — noise that
    # buries the findings the report exists to surface.
    "GetUniqueId",
    "GetMediaId",
    "GetName",
    "GetClipProperty",
    "GetProjectListInCurrentFolder",
}) | VOLATILE_METHODS

#: Suffix for observations recording a written file's size. Compared as
#: zero-versus-nonzero rather than exactly: whether a file was produced is the
#: capability question, while its exact byte count varies with the timestamped
#: project name baked into every interchange export.
BYTES_SUFFIX = "_bytes"

#: Read-only surface probes whose value legitimately differs between a session
#: with a UI and one without, *without that being a capability difference*.
#: `GetCurrentPage` is the canonical case: headless has no page to be on, so it
#: answers None. That is a true and expected consequence of having no UI, and
#: reporting it as a degradation every run would train the reader to skim.
EXPECTED_MODE_DIFFERENCES = {
    "GetCurrentPage": "Headless has no page; None is correct, not a failure.",
}

VERDICTS = (
    "parity",
    "headless_degraded",
    "gui_degraded",
    "both_failed",
    "divergent",
    "untested",
)


def _is_failure(observation: Any) -> bool:
    """Did this observation represent the call not working?

    Deliberately narrow. `False` and `None` are failures because the Resolve API
    signals failure with exactly those two values across most of its surface, and
    an empty container is a failure for calls whose entire purpose is to return
    items. A zero or an empty string is *not* treated as failure — those are
    legitimate readings (a timeline with no markers, an unset property), and
    counting them would manufacture degradations that do not exist.
    """
    if isinstance(observation, dict):
        # Surface probes report an `outcome` rather than a boolean. A method that
        # raised, that is missing from the object, or whose object could not be
        # reached at all did not work — and which of those three it was matters
        # enough to survive into the finding, so the raw dict is carried along.
        outcome = observation.get("outcome")
        if outcome in ("raised", "absent", "unreachable"):
            return True
        if "error" in observation and observation["error"]:
            return True
        if "ok" in observation:
            return not observation["ok"]
        if "success" in observation:
            return not observation["success"]
        return False
    if observation is None or observation is False:
        return True
    return False


def _shape(value: Any) -> str:
    """Type-level description, for comparing things whose value must differ."""
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    return type(value).__name__


def classify(name: str, gui: Any, headless: Any, *, present_in: Tuple[bool, bool]) -> Dict[str, Any]:
    """One observation, two modes, one verdict."""
    in_gui, in_headless = present_in
    if not (in_gui and in_headless):
        return {
            "name": name,
            "verdict": "untested",
            "reason": "observed in GUI run only" if in_gui else "observed in headless run only",
        }

    gui_failed = _is_failure(gui)
    headless_failed = _is_failure(headless)

    if gui_failed and headless_failed:
        return {"name": name, "verdict": "both_failed", "gui": gui, "headless": headless}
    if headless_failed and not gui_failed:
        return {
            "name": name,
            "verdict": "headless_degraded",
            "gui": gui,
            "headless": headless,
            "reason": "succeeded with a UI, failed without one",
        }
    if gui_failed and not headless_failed:
        return {
            "name": name,
            "verdict": "gui_degraded",
            "gui": gui,
            "headless": headless,
            "reason": "succeeded headless, failed with a UI",
        }

    if name in EXPECTED_MODE_DIFFERENCES:
        return {
            "name": name,
            "verdict": "parity",
            "reason": EXPECTED_MODE_DIFFERENCES[name],
            "gui": gui,
            "headless": headless,
            "expected_difference": True,
        }
    if name.endswith(BYTES_SUFFIX):
        if bool(gui) == bool(headless):
            return {"name": name, "verdict": "parity", "reason": "both wrote a non-empty file"}
        return {
            "name": name,
            "verdict": "headless_degraded" if not headless else "gui_degraded",
            "gui": gui,
            "headless": headless,
            "reason": "one mode wrote a file and the other wrote nothing",
        }
    if name in SESSION_VARIANT_KEYS:
        if _shape(gui) == _shape(headless):
            return {"name": name, "verdict": "parity", "reason": "session-variant; compared by type"}
        return {
            "name": name,
            "verdict": "divergent",
            "gui": _shape(gui),
            "headless": _shape(headless),
            "reason": "session-variant, and even the type differs",
        }

    if gui == headless:
        return {"name": name, "verdict": "parity"}
    return {
        "name": name,
        "verdict": "divergent",
        "gui": gui,
        "headless": headless,
        "reason": "both succeeded, values differ",
    }


def _flatten(report: Dict[str, Any]) -> Dict[str, Any]:
    """`{qualified_name: observation}` from a recorded run.

    Read-only surface probes and scenario observations are namespaced apart so a
    scenario key can never collide with an API method of the same name.
    """
    flat: Dict[str, Any] = {}
    for method, result in (report.get("surface") or {}).items():
        if method.startswith("_"):
            continue
        flat[f"surface::{method}"] = result
    for scenario, payload in (report.get("scenarios") or {}).items():
        if not isinstance(payload, dict):
            flat[f"scenario::{scenario}"] = payload
            continue
        for key, value in payload.items():
            flat[f"{scenario}::{key}"] = value
    return flat


def build_matrix(gui_report: Dict[str, Any], headless_report: Dict[str, Any]) -> Dict[str, Any]:
    """Difference two recorded runs into a capability matrix."""
    gui_flat = _flatten(gui_report)
    headless_flat = _flatten(headless_report)
    names = sorted(set(gui_flat) | set(headless_flat))

    findings: List[Dict[str, Any]] = []
    for name in names:
        # The bare observation name drives the exemption lookups, so
        # `render::output_path` is matched against `output_path`, and
        # `surface::timeline.GetCurrentTimecode` against `GetCurrentTimecode`,
        # rather than against a namespaced key nobody would think to add to the
        # exemption lists.
        bare = name.split("::")[-1].split(".")[-1]
        findings.append(
            classify(
                bare,
                gui_flat.get(name),
                headless_flat.get(name),
                present_in=(name in gui_flat, name in headless_flat),
            )
            | {"key": name}
        )

    counts = {verdict: 0 for verdict in VERDICTS}
    for finding in findings:
        counts[finding["verdict"]] += 1

    return {
        "gui_metadata": gui_report.get("metadata", {}),
        "headless_metadata": headless_report.get("metadata", {}),
        "counts": counts,
        "findings": findings,
    }


def by_group(matrix: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """Verdict counts per scenario (or `surface`), so parity is legible.

    A report that prints "233 parity" and then lists only the failures is asking
    to be read as "everything else was fine", when it could equally mean the
    probe never ran. Breaking the count down by group makes the coverage itself
    reviewable: a scenario that contributed two observations instead of ten is
    visible at a glance.
    """
    groups: Dict[str, Dict[str, int]] = {}
    for finding in matrix["findings"]:
        group = finding["key"].split("::")[0]
        counts = groups.setdefault(group, {verdict: 0 for verdict in VERDICTS})
        counts[finding["verdict"]] += 1
    return groups


def degradations(matrix: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The findings an agent has to act on, in the order they should be read."""
    order = {"headless_degraded": 0, "gui_degraded": 1, "divergent": 2, "untested": 3}
    return sorted(
        (f for f in matrix["findings"] if f["verdict"] in order),
        key=lambda f: (order[f["verdict"]], f["key"]),
    )


def render_matrix_markdown(matrix: Dict[str, Any]) -> str:
    gui_meta = matrix.get("gui_metadata", {})
    headless_meta = matrix.get("headless_metadata", {})
    counts = matrix["counts"]

    lines = [
        "# Headless (-nogui) capability differential",
        "",
        f"- GUI run: {gui_meta.get('recorded_at', 'unknown')} — {gui_meta.get('version', 'unknown')}",
        f"- Headless run: {headless_meta.get('recorded_at', 'unknown')} — {headless_meta.get('version', 'unknown')}",
        "",
        "| verdict | count |",
        "| --- | --- |",
    ]
    for verdict in VERDICTS:
        lines.append(f"| {verdict} | {counts.get(verdict, 0)} |")

    lines += [
        "",
        "## Coverage",
        "",
        "What was actually exercised, so the parity count above is reviewable "
        "rather than merely large.",
        "",
        "| group | observations | parity | headless_degraded | gui_degraded | both_failed | divergent |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for group, counts in sorted(by_group(matrix).items()):
        total = sum(counts.values())
        lines.append(
            f"| {group} | {total} | {counts['parity']} | {counts['headless_degraded']} | "
            f"{counts['gui_degraded']} | {counts['both_failed']} | {counts['divergent']} |"
        )

    acted_on = degradations(matrix)
    lines += ["", "## Findings", ""]
    if not acted_on:
        lines.append("No differences: every observation reached parity.")
        return "\n".join(lines) + "\n"

    lines += ["| observation | verdict | GUI | headless | note |", "| --- | --- | --- | --- | --- |"]
    for finding in acted_on:
        lines.append(
            "| `{key}` | {verdict} | {gui} | {headless} | {reason} |".format(
                key=finding["key"],
                verdict=finding["verdict"],
                gui=_cell(finding.get("gui")),
                headless=_cell(finding.get("headless")),
                reason=finding.get("reason", ""),
            )
        )
    return "\n".join(lines) + "\n"


def _cell(value: Any, limit: int = 60) -> str:
    if value is None:
        return "—"
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"
