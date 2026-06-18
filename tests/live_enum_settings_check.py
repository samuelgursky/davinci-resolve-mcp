"""Live validation for the #70-follow-up enum-settings fixes.

Confirms, against a running DaVinci Resolve, that the live `resolve` handle
exposes the enum constants the CreateSubtitlesFromAudio and CloudProject
normalizers resolve against, and that human-readable settings resolve to those
live enum keys/values with unknown keys dropped.

Read-only: never calls CreateSubtitlesFromAudio or any CloudProject method.

Run:
  PYTHONPATH=. venv/bin/python tests/live_enum_settings_check.py
"""
import sys

import src.server as s


def main() -> int:
    resolve = s.get_resolve()
    if resolve is None:
        print("FAIL: could not connect to a running DaVinci Resolve")
        return 1
    print(f"Connected: {resolve.GetProductName()} {resolve.GetVersionString()}")
    failures = []

    # --- Subtitles -----------------------------------------------------------
    for name in ("SUBTITLE_LANGUAGE", "SUBTITLE_CAPTION_PRESET", "SUBTITLE_LINE_BREAK",
                 "SUBTITLE_CHARS_PER_LINE", "SUBTITLE_GAP", "AUTO_CAPTION_KOREAN",
                 "AUTO_CAPTION_NETFLIX", "AUTO_CAPTION_LINE_DOUBLE"):
        if not hasattr(resolve, name):
            failures.append(f"live handle missing subtitle const {name}")
    sub_norm, sub_ignored = s._normalize_auto_caption_settings(
        {"language": "korean", "preset": "netflix", "chars_per_line": 999,
         "group_id": "junk"}, resolve)
    print(f"subtitle normalized={sub_norm!r} ignored={sub_ignored!r}")
    if sub_norm.get(getattr(resolve, "SUBTITLE_LANGUAGE", None)) != getattr(resolve, "AUTO_CAPTION_KOREAN", None):
        failures.append("subtitle language did not resolve to live AUTO_CAPTION_KOREAN")
    if sub_norm.get(getattr(resolve, "SUBTITLE_CHARS_PER_LINE", None)) != 60:
        failures.append("subtitle chars_per_line not clamped to 60")
    if "korean" in [str(v).lower() for v in sub_norm.values()]:
        failures.append("raw 'korean' string leaked into subtitle settings")
    if sub_ignored != ["group_id"]:
        failures.append(f"unexpected subtitle ignored: {sub_ignored!r}")

    # --- CloudProject --------------------------------------------------------
    cloud_consts = ("CLOUD_SETTING_PROJECT_NAME", "CLOUD_SETTING_SYNC_MODE",
                    "CLOUD_SYNC_PROXY_ONLY")
    missing_cloud = [c for c in cloud_consts if not hasattr(resolve, c)]
    if missing_cloud:
        # Cloud constants may be absent on some installs — report, don't hard-fail.
        print(f"NOTE: live handle missing cloud consts {missing_cloud} (cloud features?)")
    else:
        cl_norm, cl_ignored = s._normalize_cloud_settings(
            {"project_name": "LiveCheck", "sync_mode": "proxy_only", "bogus": 1}, resolve)
        print(f"cloud normalized={cl_norm!r} ignored={cl_ignored!r}")
        if cl_norm.get(getattr(resolve, "CLOUD_SETTING_SYNC_MODE")) != getattr(resolve, "CLOUD_SYNC_PROXY_ONLY"):
            failures.append("cloud sync_mode did not resolve to live CLOUD_SYNC_PROXY_ONLY")
        if cl_norm.get(getattr(resolve, "CLOUD_SETTING_PROJECT_NAME")) != "LiveCheck":
            failures.append("cloud project_name not keyed to CLOUD_SETTING_PROJECT_NAME")
        if cl_ignored != ["bogus"]:
            failures.append(f"unexpected cloud ignored: {cl_ignored!r}")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS: live subtitle + cloud enum resolution verified (#70 follow-up)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
