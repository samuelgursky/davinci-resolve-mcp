"""Delivery targets — named render intents that also emit their own QC spec.

A delivery target is one definition with three projections:

1. **Resolve render settings** — keys from `_RENDER_SETTING_KEYS`, fed to
   `SetRenderSettings` / `prepare_render_job` on the live Python server.
2. **A QC spec** — the ffprobe-shaped vocabulary `checkDeliverable` consumes on
   the advanced (Node) server, so a rendered file can be verified against the
   same intent that produced it.
3. **A human label/description** for the agent and the control panel.

## Ids are spec-descriptive; platform names are aliases

Platform recommendations drift; container/codec/frame shape does not. So the
canonical ids describe the *deliverable*, and platform names (`youtube`,
`tiktok`, `reels`) are aliases pointing at them. When a platform changes its
guidance you repoint one alias instead of rewriting a target — and no committed
id ever becomes a lie about what it produces.

## Why candidates, not a single codec string

Format and codec are stored as **ordered candidate tuples**, not single strings.
`GetRenderFormats()` returns ``{format -> extension}`` and `GetRenderCodecs()`
returns ``{codec description -> codec name}``, and the exact description strings
vary across Resolve versions, licenses, and installed IO plugins. A target names
every spelling it knows and `select_available()` picks the first that exists in
the live map, so the table survives version drift instead of silently missing.

Nothing here is authoritative about what a given machine supports — availability
is machine, license, and plugin dependent. Resolution happens against the live
matrix at call time, and an unmatched target fails loudly with the available list
rather than guessing.

## What is deliberately NOT encoded

- **Bitrate.** Resolve has no bitrate render-setting key; it exposes only
  `VideoQuality`, whose type and meaning vary per codec (int for some, string
  for others). A portable number is not expressible here, so quality is left at
  the Resolve/format default rather than guessed.
- **`AudioCodec`.** Left unset so Resolve picks the container default, which is
  correct for every target here.

Both omissions follow the module's core rule:

    **The QC spec asserts only what the render settings actually pin.**

Asserting a field the render never controlled produces QC failures that say
nothing about the deliverable — so unset fields are absent from both projections.

## Loudness is a fourth projection, not a QC-spec field

`deliverable_qc` asserts what the *render* pinned. Program loudness is not one of
those things — the mix sets it, not `SetRenderSettings` — so a loudness contract
would violate the rule above if it lived in `to_qc_spec()`. It is a separate
projection, `to_loudness_target()`, feeding the `loudness_qc` action, whose
target vocabulary is `{integrated, integratedTol, truePeakMax, lraMax}`.

A loudness failure therefore means "the mix is wrong", never "the render settings
are wrong", and the two never get confused in one verdict.

**Dialogue-gated standards emit no gradeable `integrated` value.** `loudness_qc`
measures full-program via ebur128; a dialogue-gated spec measures only speech.
Grading one against the other produces a verdict that says nothing reliable, so
the integrated number is carried in `meta` for a human or a dialogue-gated meter
and the emitted target asserts only true peak and LRA — which *are* valid
full-program. That is the same rule as above: assert only what is actually
verifiable.

**No per-target custom numbers yet.** A target names a standard; it cannot carry
a bespoke integrated/tolerance pair (a show bible asking for −24 LKFS ±1 rather
than ATSC's ±2). Free-text loudness on the authored side is already handled by
the advanced server's `spec_from_authored`. If bespoke numbers are needed here,
the standards table is what should grow — not five more fields on every target.

## No shipped target names a loudness standard by default

A ProRes master has no inherent program loudness, and even a broadcast handoff
depends on territory (EBU vs ATSC). Guessing one would assert a number the
deliverable never promised. `loudness_standard` is therefore unset everywhere in
the shipped table and is named explicitly per call, per user override, or per
project. The value here is that the *numbers* are correct and named when someone
does ask for them, instead of being invented at the call site.

## Not every target has a QC projection

Image-sequence targets render *many* files and package targets (IMF, DCP) render
a directory; `deliverable_qc` probes one file. Those targets carry no `qc_codec`
and instead set `qc_skip_reason`, and `to_qc_spec()` returns None for them rather
than emitting a spec that would be checked against an arbitrary single frame.
Every target must have one or the other — a missing QC projection is always
explained, never silent.

## Live-verified against the real matrix

Codec candidates were checked against DaVinci Resolve Studio 19.1.3.7 on
2026-07-27 (20 formats / 271 format-codec pairs). That pass corrected real
mistakes — plain `"DNxHR HQX"` and `"DNxHR 444"` do not exist (the live labels
carry a bit depth: `"DNxHR HQX 10-bit"`), DPX/TIFF codecs are spelled
`"RGB 10 bits"` not `"RGB 10-bit"`, PNG is not a render format at all, and the
`Wave` format exposes **zero** codecs and rejects every codec value passed to
`SetCurrentRenderFormatAndCodec`, so an audio-only WAV target is not expressible
through this API. Availability still varies by version, license, and installed
IO plugins, so resolution remains live.

## ffprobe gotcha encoded here

ffprobe reports `format_name=mov,mp4,m4a,3gp,3g2,mj2` for **both** .mov and .mp4,
and `ffprobe-media.mjs` takes the first token — so `container` is `"mov"` for
both and cannot discriminate them. `video.codec` is the real discriminator.
Verified 2026-07-27 against ffmpeg-generated files.

Storage: these shipped defaults are a Python literal because the npm `files`
glob is `src/**/*.py` — a JSON sidecar under `src/` ships in a git checkout and
silently vanishes on install. User overrides live in `logs/delivery-targets.json`
(see `user_targets_path`); per-project deliverables belong in the project DB.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger("resolve-mcp.delivery-targets")

SCHEMA_VERSION = "2.1"

ENV_USER_TARGETS = "DAVINCI_RESOLVE_MCP_DELIVERY_TARGETS"

#: Grouping for listings/UI only — no behavior attaches to these.
TIERS = ("master", "web", "sequence", "broadcast", "package")

#: What the shipped candidates were checked against. Availability is still
#: machine/license/plugin dependent, so resolution happens live regardless.
VERIFIED_ON = "DaVinci Resolve Studio 19.1.3.7 (2026-07-27, 20 formats / 271 pairs)"


# ── Loudness standards ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class LoudnessStandard:
    """One named program-loudness contract, projected onto `loudness_qc`.

    `integrated` / `tolerance_lu` are the integrated-loudness window;
    `true_peak_max_dbtp` is a ceiling. `lra_max` is None for every standard
    shipped here — none of them mandate a loudness-range cap, and asserting one
    would invent a failure the spec never asked for. A wide LRA is surfaced as
    advice by the projection instead.

    `dialogue_gated` marks a standard whose integrated figure is measured over
    dialogue only. Those emit no gradeable integrated value — see the module
    docstring.
    """

    id: str
    label: str
    integrated: float
    tolerance_lu: float
    true_peak_max_dbtp: float
    lra_max: Optional[float] = None
    dialogue_gated: bool = False
    source: str = ""


#: Advisory threshold. Above this, a mix is unusually dynamic for delivery and
#: worth a human look — but no standard here makes it a failure, so it never is.
LRA_ADVISORY_LU = 20.0

LOUDNESS_STANDARDS: Dict[str, LoudnessStandard] = {
    standard.id: standard
    for standard in (
        LoudnessStandard(
            id="web",
            label="Web / social",
            integrated=-16.0,
            tolerance_lu=2.0,
            true_peak_max_dbtp=-1.0,
            source="Common streaming/social practice: platforms normalise around -16 LUFS, true peak <= -1 dBTP.",
        ),
        LoudnessStandard(
            id="podcast",
            label="Podcast (stereo)",
            integrated=-16.0,
            tolerance_lu=1.5,
            true_peak_max_dbtp=-1.0,
            source="Podcast stereo convention: -16 LUFS +/-1.5 LU, true peak <= -1 dBTP.",
        ),
        LoudnessStandard(
            id="ebu_r128",
            label="EBU R128 broadcast",
            integrated=-23.0,
            tolerance_lu=0.5,
            true_peak_max_dbtp=-1.0,
            source="EBU R128: -23 LUFS +/-0.5 LU, true peak <= -1 dBTP.",
        ),
        LoudnessStandard(
            id="atsc_a85",
            label="ATSC A/85 (US broadcast)",
            integrated=-24.0,
            tolerance_lu=2.0,
            true_peak_max_dbtp=-2.0,
            source="ATSC A/85: -24 LKFS +/-2 LU, true peak <= -2 dBTP.",
        ),
        LoudnessStandard(
            id="ott_dialogue_gated",
            label="OTT dialogue-gated",
            integrated=-27.0,
            tolerance_lu=2.0,
            true_peak_max_dbtp=-2.0,
            dialogue_gated=True,
            source="OTT dialogue-gated delivery: -27 LUFS +/-2 LU over dialogue only, true peak <= -2 dBTP.",
        ),
    )
}


def normalize_loudness_standard(name: Any) -> Optional[str]:
    """Fold a user-supplied standard name to a canonical id, or None if unknown."""
    if not isinstance(name, str):
        return None
    key = name.strip().lower().replace("-", "_").replace(" ", "_")
    return key if key in LOUDNESS_STANDARDS else None


# ── Target model ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DeliveryTarget:
    """One named render intent. `None` on any optional field means "do not pin"."""

    id: str
    label: str
    describe: str
    tier: str

    # Ordered spellings; the first that exists in the live map wins.
    format_candidates: Tuple[str, ...] = ()
    codec_candidates: Tuple[str, ...] = ()

    # ffprobe side. qc_codec None => no single-file QC projection; qc_skip_reason
    # must then say why, so a missing check is always explained rather than silent.
    qc_container: Optional[str] = None
    qc_codec: Optional[str] = None
    qc_audio_codec: Optional[str] = None
    qc_skip_reason: Optional[str] = None

    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None  # None = inherit the timeline's rate
    audio_channels: Optional[int] = None
    audio_sample_rate: Optional[int] = None
    audio_bit_depth: Optional[int] = None
    export_video: bool = True
    export_audio: bool = True
    export_alpha: bool = False

    # Program loudness. An id into LOUDNESS_STANDARDS, or None for "do not pin".
    # Unset on every shipped target — see the module docstring for why.
    loudness_standard: Optional[str] = None

    verified: str = ""
    source: str = ""
    notes: Tuple[str, ...] = ()

    @property
    def format(self) -> str:
        """Preferred format spelling, for display and as the resolution seed."""
        return self.format_candidates[0] if self.format_candidates else ""

    @property
    def codec(self) -> str:
        """Preferred codec spelling, for display and as the resolution seed."""
        return self.codec_candidates[0] if self.codec_candidates else ""

    @property
    def has_qc_projection(self) -> bool:
        return bool(self.qc_codec or self.qc_audio_codec)

    @property
    def loudness(self) -> Optional[LoudnessStandard]:
        """The named standard, or None when the target pins no loudness."""
        if not self.loudness_standard:
            return None
        return LOUDNESS_STANDARDS.get(self.loudness_standard)


# ── Shipped table ───────────────────────────────────────────────────────────

_TIMELINE_NOTE = (
    "Frame size and rate inherit the timeline, so the deliverable matches the cut "
    "rather than a fixed raster."
)
_SEQUENCE_SKIP = "renders an image sequence (many files); deliverable_qc probes one"
_PACKAGE_SKIP = "renders a package directory, not a single file; deliverable_qc probes one"
_SEQUENCE_NOTE = "Per-frame checks are a separate pass from deliverable_qc."
_LABELS_NOTE = (
    "Codec description strings vary by Resolve version/license; candidates cover the "
    "known spellings and resolution happens against the live matrix."
)
_QT = ("QuickTime", "mov")
_MP4 = ("MP4", "mp4")

_VERIFIED = "2026-07-27"
_PRORES_SRC = "Live matrix: QuickTime/ProRes render pairs."
_DNX_SRC = "Live matrix: QuickTime/DNx render pairs; Avid-family mastering codecs."
_WEB_SRC = "Container/codec/raster shape are long-stable web basics; no bitrate is pinned."
_SEQ_SRC = "Live matrix: image-sequence render formats for VFX/finishing handoff."


def _prores(key: str, label_bits: str, codecs: Tuple[str, ...], describe: str, **kw) -> DeliveryTarget:
    return DeliveryTarget(
        id=key,
        label=f"ProRes {label_bits} master",
        describe=describe,
        tier="master",
        format_candidates=_QT,
        codec_candidates=codecs,
        qc_container="mov",
        qc_codec="prores",
        audio_channels=2,
        audio_sample_rate=48000,
        audio_bit_depth=24,
        verified=_VERIFIED,
        source=_PRORES_SRC,
        notes=(_TIMELINE_NOTE, _LABELS_NOTE),
        **kw,
    )


def _dnxhr(key: str, label_bits: str, codecs: Tuple[str, ...], describe: str, **kw) -> DeliveryTarget:
    return DeliveryTarget(
        id=key,
        label=f"DNxHR {label_bits} master",
        describe=describe,
        tier="master",
        format_candidates=_QT,
        codec_candidates=codecs,
        qc_container="mov",
        qc_codec="dnxhd",  # ffprobe reports the DNxHR family as dnxhd
        audio_channels=2,
        audio_sample_rate=48000,
        audio_bit_depth=24,
        verified=_VERIFIED,
        source=_DNX_SRC,
        notes=(_TIMELINE_NOTE, _LABELS_NOTE, "ffprobe reports DNxHR as codec_name=dnxhd."),
        **kw,
    )


def _web(key: str, label: str, codecs: Tuple[str, ...], w: int, h: int, qc_codec: str,
         describe: str, notes: Tuple[str, ...] = ()) -> DeliveryTarget:
    return DeliveryTarget(
        id=key,
        label=label,
        describe=describe,
        tier="web",
        format_candidates=_MP4,
        codec_candidates=codecs,
        qc_container="mov",  # ffprobe first token is "mov" for mp4 too
        qc_codec=qc_codec,
        width=w,
        height=h,
        audio_channels=2,
        audio_sample_rate=48000,
        verified="2026-07-27",
        source=_WEB_SRC,
        notes=notes,
    )


def _sequence(key: str, label: str, formats: Tuple[str, ...], codecs: Tuple[str, ...],
              describe: str, notes: Tuple[str, ...] = ()) -> DeliveryTarget:
    return DeliveryTarget(
        id=key,
        label=label,
        describe=describe,
        tier="sequence",
        format_candidates=formats,
        codec_candidates=codecs,
        export_audio=False,
        qc_skip_reason=_SEQUENCE_SKIP,
        verified=_VERIFIED,
        source=_SEQ_SRC,
        notes=(_SEQUENCE_NOTE, _LABELS_NOTE) + notes,
    )


def _broadcast(key: str, label: str, codecs: Tuple[str, ...], describe: str,
               w: Optional[int] = None, h: Optional[int] = None,
               qc_codec: str = "h264", notes: Tuple[str, ...] = ()) -> DeliveryTarget:
    return DeliveryTarget(
        id=key,
        label=label,
        describe=describe,
        tier="broadcast",
        format_candidates=("MXF OP1A", "mxf_op1a"),
        codec_candidates=codecs,
        qc_container="mxf",
        qc_codec=qc_codec,
        width=w,
        height=h,
        audio_channels=2,
        audio_sample_rate=48000,
        audio_bit_depth=24,
        verified=_VERIFIED,
        source="Live matrix: MXF OP1A broadcast codecs.",
        notes=notes,
    )


def _package(key: str, label: str, formats: Tuple[str, ...], codecs: Tuple[str, ...],
             describe: str, notes: Tuple[str, ...]) -> DeliveryTarget:
    return DeliveryTarget(
        id=key,
        label=label,
        describe=describe,
        tier="package",
        format_candidates=formats,
        codec_candidates=codecs,
        qc_skip_reason=_PACKAGE_SKIP,
        audio_channels=2,
        audio_sample_rate=48000,
        verified=_VERIFIED,
        source="Live matrix: package render formats.",
        notes=notes,
    )


_H264 = ("H.264", "H264")
_H265 = ("H.265", "H265", "HEVC")

DELIVERY_TARGETS: Dict[str, DeliveryTarget] = {
    # ── Mastering: ProRes family ────────────────────────────────────────────
    "prores422proxy_master": _prores(
        "prores422proxy_master", "422 Proxy",
        ("Apple ProRes 422 Proxy", "ProRes422Proxy"),
        "Lightest ProRes tier. Offline/review copies, not a finishing master.",
    ),
    "prores422lt_master": _prores(
        "prores422lt_master", "422 LT",
        ("Apple ProRes 422 LT", "ProRes422LT"),
        "Light ProRes tier. Review and lightweight distribution.",
    ),
    "prores422_master": _prores(
        "prores422_master", "422",
        ("Apple ProRes 422", "ProRes422"),
        "Standard ProRes tier. Common broadcast/agency mezzanine.",
    ),
    "prores422hq_master": _prores(
        "prores422hq_master", "422 HQ",
        ("Apple ProRes 422 HQ", "ProRes422HQ"),
        "The default finishing master for most work. 48 kHz 24-bit stereo.",
    ),
    "prores4444_master": _prores(
        "prores4444_master", "4444",
        ("Apple ProRes 4444", "ProRes4444"),
        "Mastering with an alpha channel, for graphics/VFX handoff.",
        export_alpha=True,
    ),
    "prores4444xq_master": _prores(
        "prores4444xq_master", "4444 XQ",
        ("Apple ProRes 4444 XQ", "ProRes4444XQ"),
        "Highest ProRes tier with alpha. HDR and heavy-grade finishing.",
        export_alpha=True,
    ),
    # ── Mastering: DNxHR family ─────────────────────────────────────────────
    "dnxhr_lb_master": _dnxhr(
        "dnxhr_lb_master", "LB",
        ("DNxHRLB", "Avid DNxHR LB 12-bit", "DNxHR LB"),
        "Low-bandwidth DNxHR. Offline/review, not finishing.",
    ),
    "dnxhr_sq_master": _dnxhr(
        "dnxhr_sq_master", "SQ",
        ("DNxHRSQ", "Avid DNxHR SQ 12-bit", "DNxHR SQ"),
        "Standard-quality DNxHR. Avid-family review and distribution.",
    ),
    "dnxhr_hq_master": _dnxhr(
        "dnxhr_hq_master", "HQ",
        ("DNxHRHQ", "Avid DNxHR HQ 12-bit", "DNxHR HQ"),
        "High-quality 8-bit DNxHR. Common Avid mezzanine.",
    ),
    # Codec IDS proved stable across 19.1.3.7 -> 21.0.4.5 while DESCRIPTIONS did not:
    # every DNx description gained an "Avid " prefix in 21.x, and plain "DNxHR HQX"
    # never existed. So the id leads each candidate list and descriptions follow.
    "dnxhr_hqx_master": _dnxhr(
        "dnxhr_hqx_master", "HQX 10-bit",
        ("DNxHRHQX_10", "Avid DNxHR HQX 10-bit", "DNxHR HQX 10-bit", "DNxHRHQX_12", "DNxHR HQX"),
        "10-bit DNxHR. The DNx tier to use for finishing and HDR.",
    ),
    "dnxhr_444_master": _dnxhr(
        "dnxhr_444_master", "444 12-bit",
        ("DNxHR444_12", "Avid DNxHR 444 12-bit", "DNxHR 444 12-bit", "DNxHR444_10", "DNxHR 444"),
        "4:4:4 12-bit DNxHR. Highest DNx tier for finishing.",
    ),
    "dnxhd_1080p220_10_master": _dnxhr(
        "dnxhd_1080p220_10_master", "HD 1080p 220 10-bit",
        ("DNxHD1080p220_10", "Avid DNxHD 1080p 220/185/175 10-bit", "DNxHD 1080p 220/185/175 10-bit"),
        "HD-era 10-bit DNxHD for Avid finishing at 1920x1080.",
        width=1920,
        height=1080,
    ),
    # ── Web / streaming ─────────────────────────────────────────────────────
    "h264_720p_web": _web(
        "h264_720p_web", "H.264 720p web", _H264, 1280, 720, "h264",
        "Small 1280x720 web deliverable for previews and low-bandwidth use.",
    ),
    "h264_1080p_web": _web(
        "h264_1080p_web", "H.264 1080p web", _H264, 1920, 1080, "h264",
        "General-purpose 1920x1080 web deliverable. The safe default.",
    ),
    "h264_2160p_web": _web(
        "h264_2160p_web", "H.264 2160p web", _H264, 3840, 2160, "h264",
        "UHD 3840x2160 in H.264, for players without reliable H.265 support.",
    ),
    "h265_1080p_web": _web(
        "h265_1080p_web", "H.265 1080p web", _H265, 1920, 1080, "hevc",
        "1920x1080 in H.265 for smaller files where the player supports it.",
        notes=("H.265 availability is license/plugin dependent.",),
    ),
    "h265_2160p_web": _web(
        "h265_2160p_web", "H.265 2160p web", _H265, 3840, 2160, "hevc",
        "UHD 3840x2160 web deliverable. The usual 4K web choice.",
        notes=("H.265 availability is license/plugin dependent.",),
    ),
    "h264_vertical_1080_web": _web(
        "h264_vertical_1080_web", "H.264 1080x1920 vertical", _H264, 1080, 1920, "h264",
        "Full-frame vertical deliverable for short-form/social placements.",
        notes=("Vertical raster only — reframing is an editorial decision, not a render setting.",),
    ),
    "h264_square_1080_web": _web(
        "h264_square_1080_web", "H.264 1080x1080 square", _H264, 1080, 1080, "h264",
        "Square deliverable for feed placements.",
        notes=("Square raster only — reframing is an editorial decision, not a render setting.",),
    ),
    # ── Image sequences (finishing / VFX handoff) ───────────────────────────
    # Live labels are "RGB 10 bits" (plural, spaced), not "RGB 10-bit".
    # PNG is deliberately absent: it is not a Resolve render format.
    "dpx_sequence": _sequence(
        "dpx_sequence", "DPX image sequence", ("DPX", "dpx"),
        ("RGB 10 bits", "RGB10", "RGB 12 bits", "RGB 16 bits"),
        "10-bit DPX frames. The traditional film/finishing interchange.",
    ),
    "exr_sequence": _sequence(
        "exr_sequence", "OpenEXR image sequence", ("EXR", "exr"),
        ("RGB half", "RGBHalf", "RGB half (ZIP)", "RGB float", "RGBFloat"),
        "OpenEXR frames for VFX handoff; carries linear scene-referred data.",
        notes=("Set the project's color management for a scene-linear export before using this.",),
    ),
    "tiff_sequence": _sequence(
        "tiff_sequence", "TIFF image sequence", ("TIFF", "tif"),
        ("RGB 16 bits", "RGB16", "RGB 8 bits"),
        "TIFF frames for stills-oriented or archival handoff.",
    ),
    # ── Broadcast / Avid handoff ────────────────────────────────────────────
    "dnxhr_hq_mxf_opatom": DeliveryTarget(
        id="dnxhr_hq_mxf_opatom",
        label="DNxHR HQ MXF OP-Atom (Avid)",
        describe="Avid-native handoff: MXF OP-Atom essence, DNxHR HQ.",
        tier="broadcast",
        format_candidates=("MXF OP-Atom", "MXF_OP_Atom", "mxf_op_atom"),
        codec_candidates=("DNxHRHQ", "Avid DNxHR HQ 12-bit", "DNxHR HQ"),
        qc_container="mxf",
        qc_codec="dnxhd",
        audio_channels=2,
        audio_sample_rate=48000,
        audio_bit_depth=24,
        verified=_VERIFIED,
        source="Live matrix: MXF OP-Atom + DNxHR HQ (Avid handoff).",
        notes=(
            _TIMELINE_NOTE,
            _LABELS_NOTE,
            "OP-Atom writes separate essence files per track; confirm the layout your Avid expects.",
        ),
    ),
    # No audio-only target: the `Wave` format exposes ZERO codecs and
    # SetCurrentRenderFormatAndCodec('wav', <anything>) is rejected, so an
    # audio-only WAV deliverable is not expressible through this API.
    # Verified against Resolve Studio 19.1.3.7 on 2026-07-27.
    #
    # ── Broadcast (MXF OP1A) ────────────────────────────────────────────────
    "xavc_intra_1080_broadcast": _broadcast(
        "xavc_intra_1080_broadcast", "Sony XAVC Intra 100 1080p",
        ("Sony XAVC Intra CBG 100 1920x1080", "SonyXAVCIC100_1920x1080"),
        "Sony XAVC Intra Class 100 at 1920x1080. Common broadcast delivery.",
        w=1920, h=1080,
    ),
    "xavc_intra_uhd_broadcast": _broadcast(
        "xavc_intra_uhd_broadcast", "Sony XAVC Intra 300 UHD",
        ("Sony XAVC Intra CBG 300 3840x2160", "SonyXAVCIC300_3840x2160"),
        "Sony XAVC Intra Class 300 at 3840x2160 for UHD broadcast delivery.",
        w=3840, h=2160,
    ),
    "avcintra_1080_c100_broadcast": _broadcast(
        "avcintra_1080_c100_broadcast", "AVC-Intra 1080 Class 100",
        ("AVC Intra 1080 Class 100", "PanasonicAVCIntra_1080_C100"),
        "Panasonic AVC-Intra Class 100 at 1080. Broadcast/ENG delivery.",
        w=1920, h=1080,
    ),
    # ── Package formats ─────────────────────────────────────────────────────
    "imf_prores422hq": _package(
        "imf_prores422hq", "IMF package (ProRes 422 HQ)",
        ("IMF", "imf"), ("Apple ProRes 422 HQ", "ProRes422HQ"),
        "IMF package with a ProRes 422 HQ video essence.",
        notes=(
            "IMF is a PACKAGE: composition playlists, per-asset constraints, and supplemental "
            "packages are not expressible as a render target. This selects the format/codec only "
            "— the packaging rules still need a human.",
        ),
    ),
    "dcp_2k_dci": _package(
        "dcp_2k_dci", "DCP 2K DCI",
        ("DCP", "dcp"), ("Kakadu JPEG 2000 2K DCI", "KJP2K_2KDCI"),
        "2K DCI Digital Cinema Package with a Kakadu JPEG 2000 essence.",
        notes=(
            "DCP is a PACKAGE: reels, KDMs, encryption, and CPL/PKL structure are not expressible "
            "as a render target. This selects the format/codec only — the packaging rules still "
            "need a human. easyDCP variants exist on this install too.",
        ),
    ),
}

VALID_TARGETS = frozenset(DELIVERY_TARGETS)

#: Platform names are pointers, not targets. Repoint these when a platform
#: changes its guidance; never bake a platform name into a target id.
TARGET_ALIASES: Dict[str, str] = {
    "youtube": "h264_1080p_web",
    "youtube_1080p": "h264_1080p_web",
    "youtube_4k": "h265_2160p_web",
    "youtube_2160p": "h265_2160p_web",
    "vimeo": "h264_1080p_web",
    "vimeo_1080p": "h264_1080p_web",
    "vimeo_4k": "h265_2160p_web",
    "tiktok": "h264_vertical_1080_web",
    "reels": "h264_vertical_1080_web",
    "shorts": "h264_vertical_1080_web",
    "instagram_feed": "h264_square_1080_web",
    "instagram_reels": "h264_vertical_1080_web",
    "web": "h264_1080p_web",
    "master": "prores422hq_master",
    "prores": "prores422hq_master",
    "prores_master": "prores422hq_master",
    "dnxhr": "dnxhr_hqx_master",
    "dnxhd": "dnxhd_1080p220_10_master",
    "xavc": "xavc_intra_1080_broadcast",
    "broadcast": "xavc_intra_1080_broadcast",
    "imf": "imf_prores422hq",
    "dcp": "dcp_2k_dci",
    "dnx_master": "dnxhr_hqx_master",
    "avid": "dnxhr_hq_mxf_opatom",
    "vfx": "exr_sequence",
}

#: Fields a caller may override per call. Deliberately excludes id/label/tier/
#: verified/source — those describe the shipped definition, not the render.
OVERRIDE_KEYS = frozenset(
    {
        "format_candidates",
        "codec_candidates",
        "width",
        "height",
        "fps",
        "audio_channels",
        "audio_sample_rate",
        "audio_bit_depth",
        "export_video",
        "export_audio",
        "export_alpha",
        "qc_container",
        "qc_codec",
        "qc_audio_codec",
        "loudness_standard",
    }
)

_INT_KEYS = frozenset({"width", "height", "audio_channels", "audio_sample_rate", "audio_bit_depth"})
_BOOL_KEYS = frozenset({"export_video", "export_audio", "export_alpha"})
_TUPLE_KEYS = frozenset({"format_candidates", "codec_candidates"})


# ── Live-matrix resolution ──────────────────────────────────────────────────


def select_available(candidates: Sequence[str], mapping: Any) -> Optional[str]:
    """Pick the first candidate present in a live {description: id} map.

    Returns the resolved **id** (the dict value), or None when no candidate
    matches — which is the signal to fail loudly with the available list rather
    than handing Resolve a name it will reject.
    """
    if not isinstance(mapping, dict) or not mapping:
        return None
    lowered = {str(k).lower(): str(v) for k, v in mapping.items()}
    ids = {str(v).lower(): str(v) for v in mapping.values()}
    for candidate in candidates or ():
        if not isinstance(candidate, str) or not candidate:
            continue
        needle = candidate.lower()
        if needle in lowered:
            return lowered[needle]
        if needle in ids:
            return ids[needle]
    return None


# ── Name resolution ─────────────────────────────────────────────────────────


def normalize_target_name(name: Any) -> Optional[str]:
    """Fold a user-supplied name to a canonical target id, or None if unknown."""
    if not isinstance(name, str):
        return None
    key = name.strip().lower().replace("-", "_").replace(" ", "_")
    if not key:
        return None
    if key in DELIVERY_TARGETS:
        return key
    return TARGET_ALIASES.get(key)


def resolve_target(
    name: Any,
    overrides: Optional[Mapping[str, Any]] = None,
    *,
    extra_targets: Optional[Mapping[str, DeliveryTarget]] = None,
) -> Optional[DeliveryTarget]:
    """Materialize a target by name, with optional per-field overrides.

    Returns None for an unknown name — unlike the cap/tier resolvers, there is no
    sensible default deliverable to fall back to, and silently rendering the
    wrong format is exactly the failure this feature exists to prevent.

    Unknown or un-coercible override keys are skipped with a log line; they never
    raise, and they never change a field the caller did not name.
    """
    canonical = normalize_target_name(name)
    target: Optional[DeliveryTarget] = None
    if extra_targets and isinstance(name, str):
        target = extra_targets.get(name.strip().lower())
    if target is None and canonical:
        target = (extra_targets or {}).get(canonical) or DELIVERY_TARGETS.get(canonical)
    if target is None:
        logger.warning("unknown delivery target: %r", name)
        return None

    if not overrides:
        return target

    patch: Dict[str, Any] = {}
    for key, raw in overrides.items():
        if key not in OVERRIDE_KEYS:
            logger.debug("ignoring unknown delivery-target override: %s", key)
            continue
        if raw is None:
            patch[key] = None
            continue
        try:
            if key in _TUPLE_KEYS:
                items = (raw,) if isinstance(raw, str) else tuple(raw)
                patch[key] = tuple(str(item) for item in items)
            elif key in _INT_KEYS:
                patch[key] = int(raw)
            elif key in _BOOL_KEYS:
                patch[key] = bool(raw)
            elif key == "fps":
                patch[key] = float(raw)
            elif key == "loudness_standard":
                # Validate against the table rather than accepting any string:
                # an unrecognised standard would otherwise ride through as a
                # target that silently emits no loudness projection at all.
                canonical_standard = normalize_loudness_standard(raw)
                if canonical_standard is None:
                    logger.warning(
                        "ignoring unknown loudness standard %r (known: %s)",
                        raw,
                        ", ".join(sorted(LOUDNESS_STANDARDS)),
                    )
                    continue
                patch[key] = canonical_standard
            else:
                patch[key] = str(raw)
        except (TypeError, ValueError):
            logger.warning("ignoring un-coercible delivery-target override %s=%r", key, raw)
    return replace(target, **patch) if patch else target


def list_targets(
    extra_targets: Optional[Mapping[str, DeliveryTarget]] = None,
    *,
    tier: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Introspection payload for the MCP surface and the control panel."""
    merged = dict(DELIVERY_TARGETS)
    merged.update(extra_targets or {})
    return {
        target_id: {
            "id": target.id,
            "label": target.label,
            "describe": target.describe,
            "tier": target.tier,
            "format": target.format,
            "codec": target.codec,
            "format_candidates": list(target.format_candidates),
            "codec_candidates": list(target.codec_candidates),
            "width": target.width,
            "height": target.height,
            "fps": target.fps,
            "export_video": target.export_video,
            "export_audio": target.export_audio,
            "export_alpha": target.export_alpha,
            "has_qc_projection": target.has_qc_projection,
            "qc_skip_reason": target.qc_skip_reason,
            "loudness_standard": target.loudness_standard,
            "verified": target.verified,
            "source": target.source,
            "notes": list(target.notes),
            "aliases": sorted(a for a, t in TARGET_ALIASES.items() if t == target_id),
            "user_defined": target_id not in DELIVERY_TARGETS,
        }
        for target_id, target in sorted(merged.items())
        if tier is None or target.tier == tier
    }


# ── Projections ─────────────────────────────────────────────────────────────


def to_render_settings(target: DeliveryTarget, *, timeline_fps: Optional[float] = None) -> Dict[str, Any]:
    """Project a target onto Resolve `SetRenderSettings` keys.

    Only pinned fields are emitted, so unset dimensions keep Resolve's own
    defaults instead of being forced to a guessed value. Every key here is a
    member of `_RENDER_SETTING_KEYS`; format/codec are NOT settings and are
    applied separately via `SetCurrentRenderFormatAndCodec`.
    """
    settings: Dict[str, Any] = {
        "ExportVideo": target.export_video,
        "ExportAudio": target.export_audio,
    }
    if target.export_video:
        if target.width is not None:
            settings["FormatWidth"] = target.width
        if target.height is not None:
            settings["FormatHeight"] = target.height
        fps = target.fps if target.fps is not None else timeline_fps
        if fps is not None:
            settings["FrameRate"] = fps
        if target.export_alpha:
            settings["ExportAlpha"] = True
    if target.export_audio:
        if target.audio_sample_rate is not None:
            settings["AudioSampleRate"] = target.audio_sample_rate
        if target.audio_bit_depth is not None:
            settings["AudioBitDepth"] = target.audio_bit_depth
    return settings


def to_qc_spec(
    target: DeliveryTarget, *, timeline_fps: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    """Project a target onto the `checkDeliverable` spec vocabulary (ffprobe-shaped).

    Returns None when the target has no single-file QC projection (image
    sequences render many files; `deliverable_qc` probes one).

    Asserts only what `to_render_settings` actually pins — a field the render
    never controlled would produce a QC failure that says nothing about the
    deliverable. `container` is the ffprobe first-token value, which is "mov" for
    mp4 and mov alike; `video.codec` is what discriminates them.
    """
    if not target.has_qc_projection:
        return None

    spec: Dict[str, Any] = {}
    if target.qc_container:
        spec["container"] = target.qc_container

    if target.export_video and target.qc_codec:
        video: Dict[str, Any] = {"codec": target.qc_codec}
        if target.width is not None:
            video["width"] = target.width
        if target.height is not None:
            video["height"] = target.height
        fps = target.fps if target.fps is not None else timeline_fps
        if fps is not None:
            video["fps"] = fps
        spec["video"] = video

    if target.export_audio:
        audio: Dict[str, Any] = {}
        if target.qc_audio_codec:
            audio["codec"] = target.qc_audio_codec
        if target.audio_channels is not None:
            audio["channels"] = target.audio_channels
        if target.audio_sample_rate is not None:
            audio["sampleRate"] = target.audio_sample_rate
        if target.audio_bit_depth is not None:
            audio["bitDepth"] = target.audio_bit_depth
        if audio:
            spec["audio"] = audio

    return spec or None


def to_loudness_target(target: DeliveryTarget) -> Optional[Dict[str, Any]]:
    """Project a target onto the `loudness_qc` target vocabulary.

    Returns None when the target pins no loudness — most do not, and an absent
    contract must stay absent rather than becoming a guessed one.

    Shape::

        {"target": {"integrated": -23.0, "integratedTol": 0.5,
                    "truePeakMax": -1.0},
         "meta": {"standard": "ebu_r128", ...}}

    `target` is handed straight to `loudness_qc`; `meta` is for the human-facing
    verdict. They are separated so nothing in `meta` can ever be mistaken for a
    gradeable assertion.

    A dialogue-gated standard emits **no** `integrated` key: `loudness_qc`
    measures full-program via ebur128, and grading a dialogue-gated number
    against a full-program measurement produces a pass/fail that means nothing.
    The figure travels in `meta.dialogue_gated_integrated_lufs` for a human or a
    properly gated meter, and only true peak is asserted.

    No `lraMax` is emitted: no standard here mandates one. `meta.lra_advisory_lu`
    carries the threshold above which a mix is worth a look, as advice.
    """
    standard = target.loudness
    if standard is None:
        return None
    if not target.export_audio:
        return None

    assertions: Dict[str, Any] = {"truePeakMax": standard.true_peak_max_dbtp}
    meta: Dict[str, Any] = {
        "standard": standard.id,
        "label": standard.label,
        "source": standard.source,
        "dialogue_gated": standard.dialogue_gated,
        "lra_advisory_lu": LRA_ADVISORY_LU,
    }

    if standard.dialogue_gated:
        meta["measurement_basis"] = "dialogue_gated"
        meta["dialogue_gated_integrated_lufs"] = standard.integrated
        meta["dialogue_gated_tolerance_lu"] = standard.tolerance_lu
        meta["integrated_not_asserted_reason"] = (
            "loudness_qc measures full-program loudness; this standard is measured over "
            "dialogue only. Verify the integrated figure with a dialogue-gated meter — a "
            "full-program pass or fail against it would not mean anything."
        )
    else:
        meta["measurement_basis"] = "full_program"
        assertions["integrated"] = standard.integrated
        assertions["integratedTol"] = standard.tolerance_lu

    if standard.lra_max is not None:
        assertions["lraMax"] = standard.lra_max

    return {"target": assertions, "meta": meta}


def list_loudness_standards() -> Dict[str, Dict[str, Any]]:
    """Introspection payload so an agent names a standard instead of inventing one."""
    return {
        standard.id: {
            "id": standard.id,
            "label": standard.label,
            "integrated_lufs": standard.integrated,
            "tolerance_lu": standard.tolerance_lu,
            "true_peak_max_dbtp": standard.true_peak_max_dbtp,
            "lra_max": standard.lra_max,
            "dialogue_gated": standard.dialogue_gated,
            "source": standard.source,
        }
        for standard in sorted(LOUDNESS_STANDARDS.values(), key=lambda s: s.id)
    }


# ── User overrides ──────────────────────────────────────────────────────────


def user_targets_path(project_dir: os.PathLike[str] | str, env: Optional[Mapping[str, str]] = None) -> Path:
    """Path to the user's delivery-target override file."""
    values = os.environ if env is None else env
    override = values.get(ENV_USER_TARGETS)
    if override:
        return Path(override).expanduser()
    return Path(project_dir) / "logs" / "delivery-targets.json"


def _as_candidates(raw: Any) -> Tuple[str, ...]:
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, (list, tuple)):
        return tuple(str(item) for item in raw if item)
    return ()


def load_user_targets(path: os.PathLike[str] | str) -> Dict[str, DeliveryTarget]:
    """Load user-defined targets, skipping malformed entries rather than failing.

    A broken entry must not take out the shipped set — the user still needs to
    render. Each skipped entry is logged with its reason. An absent or
    unparseable file yields {}.

    File shape::

        {"targets": {"<id>": {"format": "QuickTime" | ["QuickTime", "mov"],
                              "codec": "DNxHR HQ", "width": 1920, ...}}}
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("could not read delivery targets from %s: %s", path, exc)
        return {}

    if not isinstance(payload, dict):
        logger.warning("delivery targets file %s is not an object; ignoring", path)
        return {}
    raw_targets = payload.get("targets")
    if not isinstance(raw_targets, dict):
        logger.warning("delivery targets file %s has no 'targets' object; ignoring", path)
        return {}

    loaded: Dict[str, DeliveryTarget] = {}
    for target_id, body in raw_targets.items():
        if not isinstance(target_id, str) or not target_id.strip():
            logger.warning("skipping delivery target with a non-string id")
            continue
        if not isinstance(body, dict):
            logger.warning("skipping delivery target %r: entry is not an object", target_id)
            continue
        key = target_id.strip().lower()
        formats = _as_candidates(body.get("format_candidates") or body.get("format"))
        codecs = _as_candidates(body.get("codec_candidates") or body.get("codec"))
        missing = [n for n, v in (("format", formats), ("codec", codecs)) if not v]
        if missing:
            logger.warning("skipping delivery target %r: missing %s", target_id, ", ".join(missing))
            continue
        tier = str(body.get("tier") or "master")
        if tier not in TIERS:
            logger.warning("delivery target %r has unknown tier %r; treating as 'master'", target_id, tier)
            tier = "master"
        base = DeliveryTarget(
            id=key,
            label=str(body.get("label") or key),
            describe=str(body.get("describe") or ""),
            tier=tier,
            format_candidates=formats,
            codec_candidates=codecs,
            qc_container=body.get("qc_container") or None,
            qc_codec=body.get("qc_codec") or None,
            qc_audio_codec=body.get("qc_audio_codec") or None,
            verified=str(body.get("verified") or ""),
            source=str(body.get("source") or "user-defined"),
        )
        # Route the numeric/boolean fields through the same coercion the MCP
        # override path uses, so a user file and a per-call override behave
        # identically (e.g. "1080" as a string still lands as an int).
        overrides = {k: v for k, v in body.items() if k in OVERRIDE_KEYS}
        loaded[key] = resolve_target(key, overrides, extra_targets={key: base}) or base
    return loaded
