"""The value space of SetClipColor, and an honest refusal when a name misses.

`SetClipColor(colorName) --> Bool` is documented with `colorName` as a bare
string and no enumerated values anywhere in the scripting reference. The same
reference *does* export a discoverable colour vocabulary — the marker constants
(`resolve.MARKER_ROSE`, `resolve.MARKER_FUCHSIA`, …) — so the only colour names
reachable from the API surface come from the marker palette, and those are
largely the ones `SetClipColor` refuses. Issue #124 named this a decoy
vocabulary, which is exactly right.

Enumerated live on **DaVinci Resolve Studio 19.1.3.7 (macOS, 2026-08-06)**
against both objects that expose the method. Both accept the same 16 names —
the Edit-page clip-colour palette — and refuse everything else with a bare
`False`, including every marker-only name and the empty string.

The five names that overlap the two palettes (Blue, Green, Yellow, Pink,
Purple) are what makes this trap so durable: an agent reasoning from the marker
constants gets five hits out of sixteen and concludes the vocabulary is right.

This set is deliberately NOT enforced. It was measured on one build, and a
future Resolve could extend it; hard-rejecting an unlisted name would turn a
working call into a failure on a build we have not seen. Callers pass the name
through, and when Resolve refuses, the remediation names the measured-valid set.
"""

VERIFIED_ON = "DaVinci Resolve Studio 19.1.3.7 (macOS, 2026-08-06)"

# Accepted by BOTH TimelineItem.SetClipColor and MediaPoolItem.SetClipColor.
CLIP_COLORS = (
    "Orange", "Apricot", "Yellow", "Lime", "Olive", "Green", "Teal", "Navy",
    "Blue", "Purple", "Violet", "Pink", "Tan", "Beige", "Brown", "Chocolate",
)

# Measured refused. Kept explicit because these are the names an agent actually
# reaches for: every one is either a marker constant or a common colour word.
REFUSED_NAMES = (
    "Cyan", "Red", "Fuchsia", "Rose", "Lavender", "Sky", "Mint", "Lemon",
    "Sand", "Cocoa", "Cream", "Apple", "Magenta", "White", "Black", "Gray",
    "Grey", "",
)

# The marker-palette names that are NOT clip colours — the decoy set proper.
MARKER_ONLY_NAMES = (
    "Cyan", "Red", "Fuchsia", "Rose", "Lavender", "Sky", "Mint", "Lemon",
    "Sand", "Cocoa", "Cream",
)


def is_known_clip_color(color) -> bool:
    """True if `color` is in the measured-valid set. Case-sensitive, as Resolve is."""
    return isinstance(color, str) and color in CLIP_COLORS


def clip_color_refusal(color) -> dict:
    """Error payload for a SetClipColor that came back False.

    Separates 'you used a marker name' from 'Resolve refused for another
    reason', because the caller cannot tell them apart from the bare bool.
    """
    marker_decoy = isinstance(color, str) and color in MARKER_ONLY_NAMES
    if marker_decoy:
        reason = (
            f"'{color}' is a MARKER colour, not a clip colour. The scripting "
            "reference enumerates the marker constants and nothing else, so it "
            "is the vocabulary an agent finds first — and SetClipColor refuses "
            "most of it with a bare False."
        )
    elif is_known_clip_color(color):
        reason = (
            f"'{color}' is a valid clip colour on {VERIFIED_ON}, so this refusal "
            "is about the item or the session, not the name. Note that "
            "SetClipColor returns True WITHOUT persisting on generator and title "
            "items — check GetClipColor rather than the bool."
        )
    else:
        reason = (
            f"'{color}' is not in the clip-colour palette. SetClipColor refuses "
            "undocumented names with a bare False and no other signal."
        )
    return {
        "reason": reason,
        "remediation": (
            "Use one of the 16 Edit-page clip colours: "
            + ", ".join(CLIP_COLORS)
            + f". Measured on {VERIFIED_ON}; the set is not enforced here because "
            "a later build could extend it."
        ),
        "state": {
            "requested_color": color,
            "valid_colors": list(CLIP_COLORS),
            "is_marker_only_name": marker_decoy,
            "verified_on": VERIFIED_ON,
        },
    }
