"""Live validation for the issue #70 AutoSyncAudio settings fix.

Connects to a running DaVinci Resolve and confirms, against the REAL resolve
handle (not a FakeResolve), that:
  - the live handle actually exposes the AUDIO_SYNC_* constants the fix relies on,
  - human-readable settings (method="waveform", channel="auto") resolve to those
    live enum keys/values, and
  - unsupported keys (group_id, primary_clip_id) are dropped and reported as
    ignored_settings instead of being forwarded into AutoSyncAudio.

Read-only: it never calls AutoSyncAudio, so no media or project state is touched.

Run:
  venv/bin/python tests/live_auto_sync_settings_check.py
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

    # 1. The live handle must expose the constants the fix resolves against.
    for name in ("AUDIO_SYNC_MODE", "AUDIO_SYNC_WAVEFORM", "AUDIO_SYNC_TIMECODE",
                 "AUDIO_SYNC_CHANNEL_NUMBER", "AUDIO_SYNC_CHANNEL_AUTOMATIC"):
        if not hasattr(resolve, name):
            failures.append(f"live resolve handle missing {name}")
    mode_key = getattr(resolve, "AUDIO_SYNC_MODE", None)
    waveform_val = getattr(resolve, "AUDIO_SYNC_WAVEFORM", None)
    auto_val = getattr(resolve, "AUDIO_SYNC_CHANNEL_AUTOMATIC", None)
    chan_key = getattr(resolve, "AUDIO_SYNC_CHANNEL_NUMBER", None)
    print(f"AUDIO_SYNC_MODE={mode_key!r} AUDIO_SYNC_WAVEFORM={waveform_val!r} "
          f"AUDIO_SYNC_CHANNEL_AUTOMATIC={auto_val!r}")

    # 2. The exact issue-#70 payload must resolve `method` and drop junk keys.
    payload = {"group_id": "test", "method": "waveform", "primary_clip_id": "id1",
               "channel": "auto"}
    normalized, ignored = s._normalize_auto_sync_settings(dict(payload), resolve)
    print(f"normalized={normalized!r}")
    print(f"ignored_settings={ignored!r}")

    if normalized.get(mode_key) != waveform_val:
        failures.append(
            f"mode did not resolve to live waveform enum: {normalized.get(mode_key)!r} != {waveform_val!r}"
        )
    if normalized.get(chan_key) != auto_val:
        failures.append(
            f"channel did not resolve to live automatic enum: {normalized.get(chan_key)!r} != {auto_val!r}"
        )
    # No raw human-readable strings should survive into the settings dict.
    if "waveform" in normalized.values():
        failures.append("raw 'waveform' string leaked into normalized settings")
    if ignored != ["group_id", "primary_clip_id"]:
        failures.append(f"unexpected ignored_settings: {ignored!r}")
    for junk in ("group_id", "primary_clip_id", "method", "channel"):
        if junk in normalized:
            failures.append(f"junk key {junk!r} was forwarded into settings")

    if failures:
        print("\nFAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nPASS: live enum resolution + ignored-key dropping verified (issue #70)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
