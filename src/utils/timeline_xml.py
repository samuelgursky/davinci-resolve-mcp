"""Sanitize FCP7 (xmeml) / FCPXML timeline interchange files so DaVinci Resolve's
scripting API can import them with media linked.

Resolve's GUI "Load XML" importer tolerates two things that the scripting API's
``MediaPool.ImportTimelineFromFile`` does NOT — either one makes the API abort the
entire import (it returns ``None`` and imports nothing, leaving any timeline it does
create fully offline):

1. **Clipitems whose media file is missing on disk.** The GUI creates an offline
   placeholder and prompts to relink; the API just bails.
2. **Generator clipitems** — slugs / solids / colour mattes such as Premiere's
   "Universal Counting Leader" or "Black Video", which carry a ``<file>`` element
   with no ``<pathurl>``. The API bails on these too.

This module rewrites the XML, removing those offending clipitems while leaving
everything else (cuts, transitions, retimes, filters, every track) byte-for-byte
intact. Because clipitem positions in xmeml are explicit (``<start>``/``<end>``),
removing a clip leaves a gap at the right place rather than shifting the edit. The
result imports through the API with source clips auto-imported and linked, matching
the GUI's behaviour.

Validated live on DaVinci Resolve Studio 21 against Premiere-exported xmeml v4
conform XMLs.
"""

from __future__ import annotations

import os
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

# NOTE: the fuzzy media matcher (formerly src.utils.media_conform) + the conform
# oracle/verify helpers moved to the Node davinci-resolve-advanced MCP, where the
# whole conform/relink/frame-verify surface lives (editorial.match_references +
# conform tools). They are imported LAZILY below only when the opt-in auto-relink
# (search_roots) / visual-verify features are actually used, so plain XML sanitize
# — the default and only critical path — never depends on them.


def _pathurl_to_disk(pathurl: Optional[str]) -> Optional[str]:
    """Convert an xmeml ``<pathurl>`` (file URL) to a local filesystem path."""
    if not pathurl:
        return None
    p = pathurl.strip()
    for prefix in ("file://localhost", "file://"):
        if p.startswith(prefix):
            p = p[len(prefix):]
            break
    return urllib.parse.unquote(p)


def _media_exists(pathurl: Optional[str]) -> bool:
    disk = _pathurl_to_disk(pathurl)
    return bool(disk) and os.path.exists(disk)


def _disk_to_pathurl(disk_path: str) -> str:
    """Build a Premiere-style file URL from a local path (matches xmeml convention)."""
    return "file://localhost" + urllib.parse.quote(disk_path)


def _full_file_elements(seq: ET.Element) -> Dict[str, ET.Element]:
    """Map ``file id`` -> the full ``<file>`` element (the one carrying the pathurl)."""
    out: Dict[str, ET.Element] = {}
    for f in seq.iter("file"):
        fid = f.get("id")
        if fid and len(list(f)) and f.find("pathurl") is not None and fid not in out:
            out[fid] = f
    return out


def _relink_missing_files(seq: ET.Element, file_elems: Dict[str, ET.Element],
                          search_roots: List[str], min_confidence: float,
                          scan_caps: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Fuzzy-match every missing file definition against on-disk candidates and
    rewrite its ``<pathurl>`` in place when a unique confident match is found.

    Returns {relinked, ambiguous, scan} for the report. Mutates ``seq``.
    """
    missing_refs: List[Dict[str, str]] = []
    ref_to_fid: Dict[int, str] = {}
    for fid, elem in file_elems.items():
        purl = elem.findtext("pathurl")
        if purl is None or _media_exists(purl):
            continue
        disk = _pathurl_to_disk(purl)
        name = os.path.basename(disk) if disk else (elem.findtext("name") or "")
        stem, ext = os.path.splitext(name)
        ref = {"name": name, "basename": stem, "ext": ext, "reel": None, "_old": disk}
        ref_to_fid[id(ref)] = fid
        missing_refs.append(ref)

    if not missing_refs:
        return {"relinked": [], "ambiguous": [], "scan": None}

    try:
        from src.utils.media_conform import match_references, scan_candidates
    except ImportError as e:
        raise RuntimeError(
            "Auto-relink (search_roots) needs the media-conform matcher, which now "
            "lives in the davinci-resolve-advanced MCP (use its `editorial` "
            "match_references + `conform` tools). Omit search_roots for plain XML "
            "sanitize, which needs nothing extra."
        ) from e

    caps = scan_caps or {}
    scan = scan_candidates(search_roots, **caps)
    conform = match_references(missing_refs, scan["candidates"])

    relinked: List[Dict[str, Any]] = []
    ambiguous: List[Dict[str, Any]] = []
    for ref, item in zip(missing_refs, conform["items"]):
        fid = ref_to_fid[id(ref)]
        if item["status"] == "matched" and item["confidence"] >= min_confidence:
            new_path = item["assetId"]
            elem = file_elems[fid]
            pe = elem.find("pathurl")
            old_url = pe.text
            pe.text = _disk_to_pathurl(new_path)
            relinked.append({"name": ref["name"], "old_path": ref["_old"],
                             "new_path": new_path, "method": item["method"],
                             "confidence": item["confidence"],
                             "_fid": fid, "_old_url": old_url})
        elif item["status"] == "ambiguous":
            ambiguous.append({"name": ref["name"], "old_path": ref["_old"],
                              "candidates": item.get("assetIds", []),
                              "method": item["method"]})

    return {"relinked": relinked, "ambiguous": ambiguous,
            "scan": {"scanned": scan["scanned"], "truncated": scan["truncated"],
                     "roots_missing": scan["roots_missing"]}}


def _verify_relinks(file_elems: Dict[str, ET.Element], relinked: List[Dict[str, Any]],
                    src_path: str, reference_movie: Optional[str], threshold: float,
                    sampler=None) -> Dict[str, Any]:
    """Visually verify each proposed relink and VETO (revert) the WRONG ones.

    Per the flag-never-auto-apply rule: a relink that frame-matches its reference is
    confirmed (``verified``); one that conflicts is reverted to its original (offline)
    path and reported under ``flagged`` for human review; one with no available
    reference stays relinked but ``unverified``. Mutates the file elements on veto.
    """
    try:
        from src.utils import conform_oracle, conform_verify
    except ImportError as e:
        raise RuntimeError(
            "Visual relink-verify (verify_visually/reference_movie) needs the conform "
            "oracle + comparator, which now live in the davinci-resolve-advanced MCP "
            "(`conform` tool). Run sanitize/relink without visual verify to skip it."
        ) from e

    parsed = conform_oracle.parse_clips(src_path)
    ctx = {"fps": parsed["fps"], "sequence_width": parsed["sequence_width"]}
    # representative clip per original disk path (prefer non-retimed, valid record range)
    rep: Dict[str, Dict[str, Any]] = {}
    for c in parsed["clips"]:
        dp = c.get("disk_path")
        if not dp:
            continue
        o = conform_oracle.derive(c, ctx)
        score = (0 if o["retimed"] else 2) + (1 if (c.get("rec_start") or -1) >= 0 else 0)
        cur = rep.get(dp)
        if cur is None or score > cur["_score"]:
            rep[dp] = {"clip": c, "oracle": o, "_score": score}

    verified: List[Dict[str, Any]] = []
    flagged: List[Dict[str, Any]] = []
    unverified: List[Dict[str, Any]] = []
    kept: List[Dict[str, Any]] = []
    for entry in relinked:
        info = rep.get(entry["old_path"])
        if info is None:
            unverified.append(entry)
            kept.append(entry)
            continue
        reference = conform_verify.build_reference(
            info["clip"], info["oracle"],
            reference_movie=reference_movie, media_exists=_media_exists)
        if reference is None:
            unverified.append(entry)
            kept.append(entry)
            continue
        res = conform_verify.verify_proposal(
            reference, entry["new_path"],
            reference.get("candidate_frame", info["oracle"]["sample_frame"]),
            parsed["fps"], threshold=threshold, sampler=sampler)
        verdict = res.get("verdict")
        rec = {**entry, "structure": res.get("structure"),
               "reference_kind": res.get("reference_kind")}
        if verdict == "MATCH":
            verified.append(rec)
            kept.append(rec)
        elif verdict == "WRONG":
            # veto: revert pathurl so the clip falls back to missing -> dropped + flagged
            elem = file_elems.get(entry["_fid"])
            if elem is not None and entry.get("_old_url") is not None:
                elem.find("pathurl").text = entry["_old_url"]
            flagged.append(rec)
        else:  # UNREADABLE / no comparison
            unverified.append(rec)
            kept.append(rec)
    return {"relinked": kept, "verified": verified, "flagged": flagged,
            "unverified": unverified}


def _build_file_map(seq: ET.Element) -> Dict[str, str]:
    """Map ``file id`` -> ``pathurl`` from full ``<file>`` definitions.

    Premiere defines a ``<file>`` fully on first use, then references it by id
    (``<file id="file-37"/>``). We need the full definitions to resolve the
    pathurl of a reference-only clipitem.
    """
    file_map: Dict[str, str] = {}
    for f in seq.iter("file"):
        fid = f.get("id")
        if not fid:
            continue
        # A full definition has child elements and a pathurl; a bare reference does not.
        if len(list(f)) and f.find("pathurl") is not None:
            file_map[fid] = f.findtext("pathurl")
    return file_map


def _clip_pathurl(clipitem: ET.Element, file_map: Dict[str, str]) -> Optional[str]:
    fref = clipitem.find("file")
    if fref is None:
        return None
    inline = fref.findtext("pathurl")
    if inline:
        return inline
    fid = fref.get("id")
    return file_map.get(fid) if fid else None


def analyze_timeline_xml(path: str) -> Dict[str, Any]:
    """Inspect a timeline XML without modifying it.

    Returns a report dict describing how many clipitems would be kept vs. removed
    (missing media / generators). Pure parsing — does not touch Resolve.
    """
    with open(path, "r", encoding="utf-8-sig") as fh:
        raw = fh.read()
    root = ET.fromstring(raw)
    seq = root.find("sequence")
    if seq is None:
        raise ValueError("No <sequence> element found; not an FCP7 xmeml timeline")
    file_map = _build_file_map(seq)

    kept = 0
    missing: List[Dict[str, str]] = []
    generators: List[Dict[str, str]] = []
    total = 0
    for media in seq.findall("media"):
        for av in list(media):  # <video> / <audio>
            track_type = av.tag
            for track in av.findall("track"):
                for ci in track.findall("clipitem"):
                    total += 1
                    fref = ci.find("file")
                    name = ci.findtext("name") or "(unnamed)"
                    if fref is None:
                        generators.append({"name": name, "track_type": track_type,
                                           "reason": "no-file"})
                        continue
                    pathurl = _clip_pathurl(ci, file_map)
                    if pathurl is None:
                        generators.append({"name": name, "track_type": track_type,
                                           "reason": "no-pathurl"})
                    elif not _media_exists(pathurl):
                        missing.append({"name": name, "track_type": track_type,
                                        "path": _pathurl_to_disk(pathurl)})
                    else:
                        kept += 1

    seq_name = seq.findtext("name") or os.path.splitext(os.path.basename(path))[0]
    return {
        "timeline_name": seq_name,
        "clip_total": total,
        "kept": kept,
        "missing_media": missing,
        "missing_media_count": len(missing),
        "generators": generators,
        "generator_count": len(generators),
        "needs_sanitize": bool(missing or generators),
    }


def sanitize_timeline_xml(path: str, out_dir: Optional[str] = None,
                          search_roots: Optional[List[str]] = None,
                          min_confidence: float = 0.7,
                          scan_caps: Optional[Dict[str, Any]] = None,
                          verify_visually: bool = False,
                          reference_movie: Optional[str] = None,
                          verify_threshold: float = 0.90,
                          verify_sampler=None) -> Dict[str, Any]:
    """Write a sanitized copy of the timeline XML to a temp file.

    Removes clipitems that reference missing media or are generators (no pathurl),
    preserving everything else. Returns ``{temp_path, report}`` where ``report`` is
    the same shape as :func:`analyze_timeline_xml` plus ``output_path``.

    When ``search_roots`` is given, each clip whose media is missing at its
    original path is first fuzzy-matched (layered exact/ext-agnostic/normalized/reel +
    IDF true-source via :mod:`src.utils.media_conform`) against media files found under
    those roots; a unique match at/above ``min_confidence`` rewrites the clip's
    ``<pathurl>`` so it relinks instead of being dropped.

    When ``verify_visually`` is set (or a ``reference_movie`` is given), each proposed
    relink is frame-checked against a reference (the reference movie at the clip's
    record position, else the offline proxy at the original path) using the
    brightness-robust SSIM-structure metric. A relink that conflicts is VETOED —
    reverted to its original path and reported under ``flagged`` for human review,
    never silently applied. Clips that still cannot be resolved (and generators) are
    removed. ``scan_caps`` overrides the candidate-scan bounds.
    """
    with open(path, "r", encoding="utf-8-sig") as fh:
        raw = fh.read()
    root = ET.fromstring(raw)
    seq = root.find("sequence")
    if seq is None:
        raise ValueError("No <sequence> element found; not an FCP7 xmeml timeline")

    relink = {"relinked": [], "ambiguous": [], "scan": None}
    verify = None
    if search_roots:
        file_elems = _full_file_elements(seq)
        relink = _relink_missing_files(seq, file_elems, search_roots,
                                       min_confidence, scan_caps)
        if (verify_visually or reference_movie) and relink["relinked"]:
            verify = _verify_relinks(file_elems, relink["relinked"], path,
                                     reference_movie, verify_threshold, verify_sampler)
            relink["relinked"] = verify["relinked"]

    file_map = _build_file_map(seq)

    kept = 0
    missing: List[Dict[str, str]] = []
    generators: List[Dict[str, str]] = []
    total = 0
    for media in seq.findall("media"):
        for av in list(media):
            track_type = av.tag
            for track in av.findall("track"):
                for ci in list(track.findall("clipitem")):
                    total += 1
                    name = ci.findtext("name") or "(unnamed)"
                    fref = ci.find("file")
                    if fref is None:
                        generators.append({"name": name, "track_type": track_type,
                                           "reason": "no-file"})
                        track.remove(ci)
                        continue
                    pathurl = _clip_pathurl(ci, file_map)
                    if pathurl is None:
                        generators.append({"name": name, "track_type": track_type,
                                           "reason": "no-pathurl"})
                        track.remove(ci)
                    elif not _media_exists(pathurl):
                        missing.append({"name": name, "track_type": track_type,
                                        "path": _pathurl_to_disk(pathurl)})
                        track.remove(ci)
                    else:
                        kept += 1

    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="mcp_xml_import_")
    else:
        os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(out_dir, f"{base}.sanitized.xml")
    body = ET.tostring(root, encoding="unicode")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n')
        fh.write(body)
        fh.write("\n")

    def _clean(entries):
        return [{k: v for k, v in e.items() if not k.startswith("_")} for e in entries]

    seq_name = seq.findtext("name") or base
    report = {
        "output_path": out_path,
        "timeline_name": seq_name,
        "clip_total": total,
        "kept": kept,
        "removed_total": len(missing) + len(generators),
        "missing_media": missing,
        "missing_media_count": len(missing),
        "generators": generators,
        "generator_count": len(generators),
        "relinked": _clean(relink["relinked"]),
        "relinked_count": len(relink["relinked"]),
        "ambiguous": relink["ambiguous"],
        "ambiguous_count": len(relink["ambiguous"]),
        "scan": relink["scan"],
    }
    if verify is not None:
        report["verified_count"] = len(verify["verified"])
        report["flagged"] = _clean(verify["flagged"])
        report["flagged_count"] = len(verify["flagged"])
        report["unverified_count"] = len(verify["unverified"])
    return report
