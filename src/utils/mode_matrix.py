"""The probe catalogue for GUI-vs-headless differencing, and its verdicts.

This is the second attempt. The first (`headless_differential`) compared 238
observations and found zero mode-dependent failures — a result that was true as
far as it went and badly incomplete, because it could not observe the failure
that actually matters. `ProjectManager.SaveProject()` on the never-saved
`Untitled Project` does not *fail* headless; it **never returns**. A harness with
no timeouts cannot record that. It just stops, and its report is whatever it had
managed to write down before it died.

So this module adds the verdict the first one lacked:

    hang — the call did not return within its timeout

and the catalogue is written so every probe carries its own timeout and its own
preconditions. `SaveProject` is not inherently dangerous; it is dangerous *on a
project that has never been saved*. State is part of the probe, not background.

## Why probes are data rather than a script

Each probe is a named unit with a category, a timeout and a body. That shape is
what lets the runner isolate them: results stream out one at a time, so when a
worker dies mid-probe the supervisor knows exactly which one was in flight, marks
it `hang`, and resumes after it. A single linear script cannot be resumed at the
call that killed it.

## Verdicts

Beyond the first module's set:

  - ``hang``            — no return within the timeout, in at least one mode.
  - ``hang_headless``   — returned in the GUI, hung headless. The SaveProject
                          class of bug, and the reason this file exists.
  - ``hang_gui``        — the reverse.

A hang is deliberately NOT folded into "failed". A call that returns False is
survivable and usually recoverable; a call that never returns takes the session
with it and, as measured, degrades the instance afterwards. An agent must treat
them differently, so the report must distinguish them.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

#: Probe outcomes recorded by the worker, before any cross-mode comparison.
OUTCOMES = ("ok", "false", "none", "empty", "raised", "hang", "skipped")

#: How a single probe result maps to "did this work". `false`/`none` are the
#: Resolve API's two ways of saying no; `empty` is a container where the point of
#: the call was to return items.
FAILED_OUTCOMES = frozenset({"false", "none", "raised"})


class Probe:
    """One named, timed, isolated observation.

    `needs` names the fixture attributes the body requires (``project``,
    ``timeline``, ``item``, ``clip``). A probe whose needs are unmet is recorded
    `skipped` with the reason, never silently dropped — an absent row in a
    differential reads as agreement.
    """

    def __init__(
        self,
        name: str,
        category: str,
        body: Callable[[Any], Any],
        *,
        timeout: float = 30.0,
        needs: tuple = (),
        state: str = "scratch",
        destructive: bool = False,
        blocking: bool = False,
        note: str = "",
    ) -> None:
        self.name = name
        self.category = category
        self.body = body
        self.timeout = timeout
        self.needs = needs
        #: Which project must be current: "scratch" (the disposable one) or
        #: "untitled" (Resolve's never-saved default). The second exists because
        #: the only mode-dependent hang found so far only happens there.
        self.state = state
        self.destructive = destructive
        #: Blocks the ENTIRE application, not just the calling client — a modal
        #: with no one to dismiss it. Excluded from sweeps unless asked for by
        #: name, because one of these wedges the machine and costs a force-kill
        #: and a slow restart. Measured: `pm.save_untitled_project` does this in
        #: BOTH modes, so it is not something a mode sweep can route around.
        self.blocking = blocking
        self.note = note

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Probe {self.name} ({self.category}) t={self.timeout}s state={self.state}>"


def classify_outcome(value: Any) -> str:
    """Map a returned value onto an outcome name.

    `empty` is separated from `false`/`none` because an empty list is a real
    answer for some calls (a timeline with no markers) and a failure for others
    (an enumeration that should never be empty). Recording which it was lets the
    comparison stay strict without inventing failures.
    """
    if value is False:
        return "false"
    if value is None:
        return "none"
    if isinstance(value, (list, dict, tuple, str)) and len(value) == 0:
        return "empty"
    return "ok"


VERDICTS = (
    "parity",
    "flaky",
    "hang_headless",
    "hang_gui",
    "headless_degraded",
    "gui_degraded",
    "both_hang",
    "both_failed",
    "divergent",
    "untested",
)

#: Probes whose value legitimately differs between two sequential sweeps because
#: the sweep itself moved app-global state. Compared by outcome only.
#: `app.current_page` is the case: the page is one global setting and the `pages`
#: probes walk all seven of it, so whichever page the sweep happened to end on is
#: read back later. Reporting that every run trains the reader to skim the
#: findings table, which is the one table that must stay worth reading.
ORDER_SENSITIVE = frozenset({"app.current_page"})

#: Verdicts that describe a real mode difference an agent must act on.
ACTIONABLE = ("hang_headless", "hang_gui", "headless_degraded", "gui_degraded", "divergent")


def compare_repeated(name: str, gui_runs: List[Dict[str, Any]],
                     headless_runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare N runs per mode, and refuse to call a flaky probe a difference.

    This exists because a single pass per mode reports noise as findings, and it
    was measured doing exactly that. Across four sweeps, `app.keyframe_mode`
    returned `0` and `None` in BOTH modes depending on the run — a single pair
    would have reported it as `headless_degraded` or `gui_degraded` with equal
    confidence, and the direction it picked was decided by which sweeps happened
    to be compared. `gallery.export_stills` succeeded in the GUI in two sweeps
    and failed in a third.

    So: a probe whose outcomes are not internally consistent *within* a mode
    cannot support any claim about the difference *between* modes. It is reported
    `flaky`, with the observed values, and kept out of the findings table. That
    is a weaker result and the only honest one — and it is information in its own
    right, since a call that is unreliable run to run is one an agent must verify
    rather than trust.
    """
    if not gui_runs or not headless_runs:
        return {"probe": name, "verdict": "untested",
                "reason": f"gui runs={len(gui_runs)}, headless runs={len(headless_runs)}",
                "gui": gui_runs[0] if gui_runs else None,
                "headless": headless_runs[0] if headless_runs else None}

    def signature(runs):
        return {f"{r.get('outcome')}:{r.get('value')}" for r in runs}

    gui_sig, headless_sig = signature(gui_runs), signature(headless_runs)
    unstable = [m for m, sig in (("gui", gui_sig), ("headless", headless_sig)) if len(sig) > 1]
    if unstable:
        return {
            "probe": name, "verdict": "flaky",
            "reason": f"not reproducible within {'/'.join(unstable)} across "
                      f"{len(gui_runs)} GUI and {len(headless_runs)} headless run(s)",
            "gui": gui_runs[-1], "headless": headless_runs[-1],
            "gui_observed": sorted(gui_sig), "headless_observed": sorted(headless_sig),
        }

    verdict = compare_probe(name, gui_runs[-1], headless_runs[-1])
    verdict["runs"] = {"gui": len(gui_runs), "headless": len(headless_runs)}
    return verdict


def build_repeated_matrix(gui_stores: List[Dict[str, Dict[str, Any]]],
                          headless_stores: List[Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
    names = sorted({n for store in gui_stores + headless_stores for n in store})
    findings = [
        compare_repeated(n,
                         [s[n] for s in gui_stores if n in s],
                         [s[n] for s in headless_stores if n in s])
        for n in names
    ]
    counts = {v: 0 for v in VERDICTS}
    for f in findings:
        counts[f["verdict"]] += 1
    return {"counts": counts, "findings": findings, "probe_count": len(names),
            "runs": {"gui": len(gui_stores), "headless": len(headless_stores)}}


def compare_probe(name: str, gui: Optional[Dict[str, Any]], headless: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Two recorded probe results, one verdict."""
    if gui is None or headless is None:
        return {
            "probe": name,
            "verdict": "untested",
            "reason": "recorded in one mode only",
            "gui": gui,
            "headless": headless,
        }

    g_out, h_out = gui.get("outcome"), headless.get("outcome")
    if "skipped" in (g_out, h_out):
        return {"probe": name, "verdict": "untested",
                "reason": gui.get("detail") or headless.get("detail") or "skipped",
                "gui": gui, "headless": headless}

    # Hangs first and separately: a call that never returns is a different
    # problem from one that returns False, and collapsing them would hide the
    # only class of bug this harness was built to find.
    if g_out == "hang" and h_out == "hang":
        return {"probe": name, "verdict": "both_hang", "gui": gui, "headless": headless}
    if h_out == "hang":
        return {"probe": name, "verdict": "hang_headless", "gui": gui, "headless": headless,
                "reason": "returned with a UI, never returned without one"}
    if g_out == "hang":
        return {"probe": name, "verdict": "hang_gui", "gui": gui, "headless": headless,
                "reason": "returned headless, never returned with a UI"}

    g_failed, h_failed = g_out in FAILED_OUTCOMES, h_out in FAILED_OUTCOMES
    if g_failed and h_failed:
        return {"probe": name, "verdict": "both_failed", "gui": gui, "headless": headless}
    if h_failed:
        return {"probe": name, "verdict": "headless_degraded", "gui": gui, "headless": headless,
                "reason": "succeeded with a UI, failed without one"}
    if g_failed:
        return {"probe": name, "verdict": "gui_degraded", "gui": gui, "headless": headless,
                "reason": "succeeded headless, failed with a UI"}

    if name in ORDER_SENSITIVE:
        return {"probe": name, "verdict": "parity", "gui": gui, "headless": headless,
                "reason": "app-global state the sweep itself moves; compared by outcome only"}
    if gui.get("value") == headless.get("value"):
        return {"probe": name, "verdict": "parity", "gui": gui, "headless": headless}
    return {"probe": name, "verdict": "divergent", "gui": gui, "headless": headless,
            "reason": "both returned, values differ"}


def build_matrix(gui: Dict[str, Dict[str, Any]], headless: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    names = sorted(set(gui) | set(headless))
    findings = [compare_probe(n, gui.get(n), headless.get(n)) for n in names]
    counts = {v: 0 for v in VERDICTS}
    for f in findings:
        counts[f["verdict"]] += 1
    return {"counts": counts, "findings": findings, "probe_count": len(names)}


def actionable(matrix: Dict[str, Any]) -> List[Dict[str, Any]]:
    order = {v: i for i, v in enumerate(ACTIONABLE)}
    return sorted(
        (f for f in matrix["findings"] if f["verdict"] in order),
        key=lambda f: (order[f["verdict"]], f["probe"]),
    )


def render_markdown(matrix: Dict[str, Any], *, title: str = "GUI vs headless probe matrix") -> str:
    counts = matrix["counts"]
    runs = matrix.get("runs")
    header = f"{matrix['probe_count']} probes"
    if runs:
        header += f", {runs['gui']} GUI run(s) x {runs['headless']} headless run(s)"
    lines = [f"# {title}", "", header + ".", "",
             "| verdict | count |", "| --- | --- |"]
    for v in VERDICTS:
        lines.append(f"| {v} | {counts.get(v, 0)} |")

    by_cat: Dict[str, Dict[str, int]] = {}
    for f in matrix["findings"]:
        cat = (f.get("gui") or f.get("headless") or {}).get("category", "?")
        by_cat.setdefault(cat, {v: 0 for v in VERDICTS})[f["verdict"]] += 1
    lines += ["", "## Coverage by category", "",
              "| category | probes | parity | hang_headless | headless_degraded | gui_degraded | divergent | untested |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for cat, c in sorted(by_cat.items()):
        lines.append(
            f"| {cat} | {sum(c.values())} | {c['parity']} | {c['hang_headless']} | "
            f"{c['headless_degraded']} | {c['gui_degraded']} | {c['divergent']} | {c['untested']} |"
        )

    flaky = [f for f in matrix["findings"] if f["verdict"] == "flaky"]
    if flaky:
        lines += ["", "## Not reproducible (excluded from findings)", "",
                  "These returned different things run-to-run *within* a single mode, so they "
                  "cannot support a claim about the difference between modes. Listed because "
                  "an unreliable call is itself something an agent must verify rather than trust.",
                  "", "| probe | observed in GUI | observed headless |", "| --- | --- | --- |"]
        for f in flaky:
            lines.append("| `{p}` | {g} | {h} |".format(
                p=f["probe"],
                g="; ".join(str(x)[:40] for x in f.get("gui_observed", [])),
                h="; ".join(str(x)[:40] for x in f.get("headless_observed", []))))

    acted = actionable(matrix)
    lines += ["", "## Mode-dependent findings", ""]
    if not acted:
        lines.append("None: every probe that ran in both modes agreed.")
        return "\n".join(lines) + "\n"
    lines += [
        "> **Re-verify every row below in isolation before believing it.** Probes run in "
        "catalogue order against one shared fixture, so a probe near the end has ~90 "
        "destructive probes' worth of accumulated state behind it, and the two modes can "
        "drift apart for reasons that have nothing to do with the mode. Measured: five "
        "findings here — nested timelines, clip linking, take selectors, multi-job queues "
        "and render presets — all reproduced as mode differences in a full sweep and all "
        "came out **identical** when re-run with `--only`. Isolation is the test:",
        "",
        "> ```",
        "> python scripts/mode_matrix.py run --mode gui      --out iso_gui.jsonl  --only <probe>",
        "> python scripts/mode_matrix.py run --mode headless --out iso_hl.jsonl   --only <probe>",
        "> ```",
        "",
    ]
    lines += ["| probe | verdict | GUI | headless | note |", "| --- | --- | --- | --- | --- |"]
    for f in acted:
        lines.append("| `{p}` | {v} | {g} | {h} | {r} |".format(
            p=f["probe"], v=f["verdict"],
            g=_cell(f.get("gui")), h=_cell(f.get("headless")), r=f.get("reason", "")))
    return "\n".join(lines) + "\n"


def _cell(result: Optional[Dict[str, Any]], limit: int = 46) -> str:
    if not result:
        return "—"
    out = result.get("outcome")
    value = result.get("value")
    text = out if value in (None, "") else f"{out}: {value}"
    text = str(text).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"
