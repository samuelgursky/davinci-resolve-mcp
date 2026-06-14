"""Headless batch-runner CLI for source-safe media analysis.

Drives src.utils.media_analysis_jobs from outside an MCP/chat client so users
can run long batches via cron, CI, or terminal without holding a chat turn
open. The orchestration loop and durable state live in the jobs engine; this
module only handles argv, progress streaming, and exit codes.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from typing import Any, Dict, List, Optional

from src.utils.media_analysis import (
    build_plan,
    detect_capabilities,
    plan_requires_capabilities,
)
from src.utils.media_analysis_jobs import (
    batch_job_status,
    cancel_batch_job,
    create_batch_job_from_paths,
    list_batch_jobs,
    records_from_paths,
    resume_batch_job,
    run_batch_job_slice,
)


EXIT_OK = 0
EXIT_PARTIAL = 2
EXIT_FATAL = 3
EXIT_CANCELED = 130

_TERMINAL_STATUSES = {"completed", "completed_with_errors", "canceled"}

_canceled = False


def _on_sigint(signum, frame):  # noqa: ARG001 - signal handler signature
    global _canceled
    _canceled = True


def _emit(message: str, *, json_mode: bool, payload: Optional[Dict[str, Any]] = None) -> None:
    if json_mode:
        sys.stdout.write(json.dumps(payload or {}, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(message + "\n")
    sys.stdout.flush()


def _build_params(args: argparse.Namespace) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if getattr(args, "depth", None):
        params["depth"] = args.depth
    if getattr(args, "source_trust", None):
        params["source_trust"] = args.source_trust
    if getattr(args, "summary_style", None):
        params["vision"] = {"summary_style": args.summary_style}
        params["analysis_summary_style"] = args.summary_style
    return params


def _exit_for_status(status: Optional[str]) -> int:
    if status == "completed":
        return EXIT_OK
    if status == "completed_with_errors":
        return EXIT_PARTIAL
    if status == "canceled":
        return EXIT_CANCELED
    return EXIT_FATAL


def _drive_to_completion(
    project_root: str,
    job_id: str,
    *,
    max_clips: int,
    max_seconds: Optional[float],
    json_mode: bool,
) -> int:
    signal.signal(signal.SIGINT, _on_sigint)
    while True:
        if _canceled:
            cancel_batch_job(project_root, job_id)
            _emit(
                "Interrupted — job canceled",
                json_mode=json_mode,
                payload={"event": "canceled", "job_id": job_id},
            )
            return EXIT_CANCELED
        slice_result = run_batch_job_slice(
            project_root,
            job_id,
            max_clips=max_clips,
            max_seconds=max_seconds,
        )
        if not slice_result.get("success"):
            _emit(
                f"Slice failed: {slice_result.get('error')}",
                json_mode=json_mode,
                payload={"event": "slice_failed", **slice_result},
            )
            return EXIT_FATAL
        for clip in slice_result.get("processed") or []:
            _emit(
                f"  [{(clip.get('status') or '?'):>9}] #{(clip.get('position') or 0) + 1}"
                + (f" — {clip.get('error')}" if clip.get("error") else ""),
                json_mode=json_mode,
                payload={"event": "clip_done", **clip},
            )
        job_state = slice_result.get("job") or {}
        status = job_state.get("status")
        processed_count = int(slice_result.get("processed_count") or 0)
        if status in _TERMINAL_STATUSES or processed_count == 0:
            final = batch_job_status(
                project_root, job_id, include_clips=False, include_events=False
            )
            counts = final.get("progress", {})
            status = final.get("status")
            _emit(
                f"Done: {status} ({counts.get('done_clips', 0)}/{counts.get('total_clips', 0)})",
                json_mode=json_mode,
                payload={
                    "event": "job_done",
                    "job_id": job_id,
                    "status": status,
                    "progress": counts,
                    "succeeded_clips": final.get("succeeded_clips"),
                    "failed_clips": final.get("failed_clips"),
                    "skipped_clips": final.get("skipped_clips"),
                },
            )
            return _exit_for_status(status)


def _cmd_plan(args: argparse.Namespace) -> int:
    records, warnings = records_from_paths(args.paths, recursive=args.recursive)
    if not records:
        _emit(
            "No analyzable media files found",
            json_mode=args.json,
            payload={"success": False, "error": "no_media", "warnings": warnings},
        )
        return EXIT_FATAL
    params = _build_params(args)
    if args.analysis_root:
        params["analysis_root"] = args.analysis_root
    target = {
        "type": "paths",
        "paths": [r["file_path"] for r in records],
        "recursive": args.recursive,
    }
    plan = build_plan(
        project_name=args.project_name,
        project_id=None,
        records=records,
        target=target,
        params=params,
        capabilities=detect_capabilities(),
    )
    if not plan.get("success"):
        _emit(
            f"Plan failed: {plan.get('error')}",
            json_mode=args.json,
            payload=plan,
        )
        return EXIT_FATAL
    if args.json:
        plan_payload = dict(plan)
        if warnings:
            plan_payload["warnings"] = warnings
        _emit("", json_mode=True, payload=plan_payload)
    else:
        root = (plan.get("output_root") or {}).get("project_root", "?")
        _emit(f"Project root : {root}", json_mode=False)
        _emit(f"Depth        : {plan.get('depth', '?')}", json_mode=False)
        _emit(
            f"Clips        : {plan.get('clip_count', 0)}"
            f" ({plan.get('reusable_clip_count', 0)} reusable)",
            json_mode=False,
        )
        _emit(
            f"Est. seconds : {plan.get('estimated_seconds_after_reuse', '?')}",
            json_mode=False,
        )
        if plan.get("capability_gaps") and plan_requires_capabilities(plan):
            _emit(f"Missing tools: {plan['capability_gaps']}", json_mode=False)
        for w in warnings:
            _emit(f"  warning: {w}", json_mode=False)
    return EXIT_OK


def _cmd_run(args: argparse.Namespace) -> int:
    params = _build_params(args)
    create = create_batch_job_from_paths(
        project_name=args.project_name,
        paths=args.paths,
        analysis_root=args.analysis_root,
        recursive=args.recursive,
        params=params,
        name=args.name,
    )
    if not create.get("success"):
        _emit(
            f"Job creation failed: {create.get('error') or create.get('status')}",
            json_mode=args.json,
            payload=create,
        )
        return EXIT_FATAL
    job = create["job"]
    job_id = job["job_id"]
    project_root = job["project_root"]
    total = (job.get("progress") or {}).get("total_clips", 0)
    _emit(
        f"Created job {job_id}  ({total} clips, root: {project_root})",
        json_mode=args.json,
        payload={
            "event": "job_created",
            "job_id": job_id,
            "project_root": project_root,
            "total_clips": total,
        },
    )
    if args.no_follow:
        return EXIT_OK
    return _drive_to_completion(
        project_root,
        job_id,
        max_clips=args.max_clips,
        max_seconds=args.max_seconds,
        json_mode=args.json,
    )


def _emit_status(payload: Dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        _emit("", json_mode=True, payload=payload)
        return
    if not payload.get("success"):
        _emit(f"Error: {payload.get('error')}", json_mode=False)
        return
    counts = payload.get("progress", {})
    _emit(f"Job          : {payload.get('job_id')}", json_mode=False)
    _emit(
        f"Status       : {payload.get('status')} ({payload.get('phase')})",
        json_mode=False,
    )
    _emit(
        f"Progress     : {counts.get('done_clips', 0)}/{counts.get('total_clips', 0)} ({counts.get('percent', 0)}%)",
        json_mode=False,
    )
    _emit(f"Succeeded    : {payload.get('succeeded_clips')}", json_mode=False)
    _emit(f"Failed       : {payload.get('failed_clips')}", json_mode=False)
    _emit(f"Skipped      : {payload.get('skipped_clips')}", json_mode=False)
    if payload.get("last_error"):
        _emit(f"Last error   : {payload['last_error']}", json_mode=False)


def _cmd_status(args: argparse.Namespace) -> int:
    payload = batch_job_status(args.project_root, args.job_id)
    _emit_status(payload, json_mode=args.json)
    return EXIT_OK if payload.get("success") else EXIT_FATAL


def _cmd_list(args: argparse.Namespace) -> int:
    payload = list_batch_jobs(args.project_root, limit=args.limit)
    if args.json:
        _emit("", json_mode=True, payload=payload)
        return EXIT_OK if payload.get("success") else EXIT_FATAL
    if not payload.get("success"):
        _emit(f"Error: {payload.get('error')}", json_mode=False)
        return EXIT_FATAL
    jobs = payload.get("jobs") or []
    if not jobs:
        _emit("No jobs found", json_mode=False)
        return EXIT_OK
    _emit(f"{'JOB ID':<28} {'STATUS':<22} {'CLIPS':>10}  NAME", json_mode=False)
    for job in jobs:
        counts = job.get("progress", {})
        clip_col = f"{counts.get('done_clips', 0)}/{counts.get('total_clips', 0)}"
        _emit(
            f"{job['job_id']:<28} {job['status']:<22} {clip_col:>10}  {job.get('name', '')}",
            json_mode=False,
        )
    return EXIT_OK


def _cmd_resume(args: argparse.Namespace) -> int:
    resumed = resume_batch_job(args.project_root, args.job_id)
    if not resumed.get("success"):
        _emit(
            f"Resume failed: {resumed.get('error')}",
            json_mode=args.json,
            payload=resumed,
        )
        return EXIT_FATAL
    _emit(
        f"Resumed {args.job_id}",
        json_mode=args.json,
        payload={"event": "resumed", "job_id": args.job_id},
    )
    return _drive_to_completion(
        args.project_root,
        args.job_id,
        max_clips=args.max_clips,
        max_seconds=args.max_seconds,
        json_mode=args.json,
    )


def _cmd_cancel(args: argparse.Namespace) -> int:
    payload = cancel_batch_job(args.project_root, args.job_id)
    _emit_status(payload, json_mode=args.json)
    return EXIT_OK if payload.get("success") else EXIT_FATAL


def _run_spec_action(action: str, params: Dict[str, Any]):
    """Connect to Resolve (auto-launch) and run a project_manager spec action.

    Imported lazily so the analysis commands stay free of the MCP/Resolve import.
    """
    from src.server import get_resolve, _spec_action  # lazy: pulls mcp + resolve

    r = get_resolve()
    if r is None:
        return None
    return _spec_action(r, r.GetProjectManager(), action, params)


def _emit_spec_result(result, *, json_mode: bool) -> int:
    if result is None:
        _emit("Could not connect to DaVinci Resolve.",
              json_mode=json_mode,
              payload={"success": False, "error": "not_connected"})
        return EXIT_FATAL
    if json_mode:
        _emit("", json_mode=True, payload=result)
    err = result.get("error")
    if err:
        _emit(f"Spec error: {err.get('message')}", json_mode=False)
        return EXIT_FATAL
    if "actions" in result:  # plan / diff
        changed = result.get("change_count", 0)
        _emit(f"Project   : {result.get('project')}", json_mode=False)
        _emit(f"Changes   : {changed}", json_mode=False)
        for a in result.get("actions", []):
            if a.get("op") != "noop":
                _emit(f"  [{a['op']:>6}] {a['target']}  {a.get('detail', '')}", json_mode=False)
        return EXIT_OK
    # apply
    failures = result.get("failures") or []
    _emit(f"Applied   : {result.get('applied_count', 0)}", json_mode=False)
    if failures:
        for f in failures:
            _emit(f"  [failed] {f.get('target')}", json_mode=False)
        return EXIT_PARTIAL
    _emit("Done: spec applied", json_mode=False)
    return EXIT_OK


def _cmd_plan_spec(args: argparse.Namespace) -> int:
    result = _run_spec_action("diff_to_spec", {"spec_path": args.spec})
    return _emit_spec_result(result, json_mode=args.json)


def _cmd_apply(args: argparse.Namespace) -> int:
    result = _run_spec_action("apply_spec", {
        "spec_path": args.spec,
        "dry_run": args.dry_run,
        "run_hooks": args.run_hooks,
        "continue_on_error": args.continue_on_error,
    })
    return _emit_spec_result(result, json_mode=args.json)


def _add_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("paths", nargs="+", help="Files or directories to analyze")
    parser.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        default=True,
        help="Do not descend into subdirectories (default: recurse)",
    )
    parser.add_argument(
        "--analysis-root",
        help="Override analysis output root (default ~/Documents/DaVinci Resolve MCP/analysis)",
    )
    parser.add_argument(
        "--project-name",
        default=f"CLI batch {time.strftime('%Y-%m-%d')}",
        help="Project name written into the analysis root layout",
    )
    parser.add_argument(
        "--depth",
        choices=["quick", "standard", "deep", "custom"],
        help="Analysis depth (default: standard)",
    )
    parser.add_argument(
        "--source-trust",
        choices=["auto", "filename", "low", "medium", "high"],
        help="Trust tier hint for the vision pass",
    )
    parser.add_argument(
        "--summary-style",
        choices=["full", "concise", "creative", "technical"],
        help="Narrative tone for clip_summary / shot descriptions",
    )
    parser.add_argument("--name", help="Job display name")


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS keeps the subparser from overwriting a --json passed before the
    # subcommand (its default would otherwise win over the top-level parser).
    # Post-processed in main() so handlers always see a real bool.
    common.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Emit one JSON object per progress event instead of human-readable lines",
    )

    parser = argparse.ArgumentParser(
        prog="davinci-resolve-mcp batch",
        description=(
            "Headless runner for source-safe media analysis. Wraps the same engine "
            "the MCP server uses; durable state lives in <project-root>/jobs.sqlite."
        ),
        parents=[common],
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser(
        "plan",
        help="Dry-run: print what would be analyzed without creating a job",
        parents=[common],
    )
    _add_run_args(p_plan)

    p_run = sub.add_parser(
        "run",
        help="Create a batch job and drive it to completion",
        parents=[common],
    )
    _add_run_args(p_run)
    p_run.add_argument(
        "--max-clips",
        type=int,
        default=1,
        help="Clips processed per slice (default 1, max 25)",
    )
    p_run.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="Optional wall-clock budget per slice (seconds)",
    )
    p_run.add_argument(
        "--no-follow",
        action="store_true",
        help="Create the job and exit immediately instead of looping until done",
    )

    p_status = sub.add_parser("status", help="Inspect a job", parents=[common])
    p_status.add_argument("job_id")
    p_status.add_argument("--project-root", required=True)

    p_list = sub.add_parser(
        "list", help="List jobs under a project root", parents=[common]
    )
    p_list.add_argument("--project-root", required=True)
    p_list.add_argument("--limit", type=int, default=50)

    p_resume = sub.add_parser(
        "resume", help="Resume a queued / canceled job", parents=[common]
    )
    p_resume.add_argument("job_id")
    p_resume.add_argument("--project-root", required=True)
    p_resume.add_argument("--max-clips", type=int, default=1)
    p_resume.add_argument("--max-seconds", type=float, default=None)

    p_cancel = sub.add_parser(
        "cancel", help="Cancel a running job", parents=[common]
    )
    p_cancel.add_argument("job_id")
    p_cancel.add_argument("--project-root", required=True)

    p_plan_spec = sub.add_parser(
        "plan-spec",
        help="Preview drift between a declarative project spec and live Resolve",
        parents=[common],
    )
    p_plan_spec.add_argument("spec", help="Path to project.dvr.yaml (or .json)")

    p_apply = sub.add_parser(
        "apply",
        help="Reconcile the Resolve project toward a declarative spec (idempotent)",
        parents=[common],
    )
    p_apply.add_argument("spec", help="Path to project.dvr.yaml (or .json)")
    p_apply.add_argument("--dry-run", action="store_true",
                         help="Compute the plan without mutating")
    p_apply.add_argument("--run-hooks", action="store_true",
                         help="Execute the spec's before/after shell hooks (opt-in)")
    p_apply.add_argument("--continue-on-error", action="store_true",
                         help="Accumulate failures instead of aborting on the first")

    return parser


_HANDLERS = {
    "plan": _cmd_plan,
    "run": _cmd_run,
    "status": _cmd_status,
    "list": _cmd_list,
    "resume": _cmd_resume,
    "cancel": _cmd_cancel,
    "plan-spec": _cmd_plan_spec,
    "apply": _cmd_apply,
}


def main(argv: Optional[List[str]] = None) -> int:
    from src.utils import actor_identity
    actor_identity.set_instance("batch-cli")
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "json"):
        args.json = False
    return _HANDLERS[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
