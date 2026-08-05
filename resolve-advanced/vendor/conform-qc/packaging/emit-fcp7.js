'use strict';

/**
 * package/emit-fcp7.js — emit FCP7 (xmeml) XML from the conformed timeline.
 *
 * NON-NEGOTIABLE #5: keep <in> and <pproTicksIn> CONSISTENT (Resolve reads the
 * ticks). We always emit ticks = sourceFrame * ticksPerFrame so a re-import
 * reproduces the same source frame. Round-trippable through parse/xmeml-geometry.
 *
 * Two importer contracts measured against Resolve 19.1.3, both of which fail SILENTLY
 * — a clean-looking XML and a Resolve that does nothing:
 *
 *   1. <pathurl> must be percent-encoded PER SEGMENT. XML-escaping (&amp; &lt; &gt;) is
 *      NOT URL-escaping; the two are different contracts and this file previously
 *      applied only the first. Encoding the whole path in one pass would escape the '/'
 *      separators too, so each segment is encoded and the separators are rejoined.
 *      The Python side of this repo already got this right — see
 *      src/utils/timeline_xml.py _disk_to_pathurl, which uses urllib.parse.quote
 *      (safe='/' by default, i.e. the same per-segment behaviour).
 *
 *      What that actually costs you, measured on 19.1.3 one character at a time, each
 *      as a raw pathurl vs the same path encoded, in a fresh project with an empty pool:
 *
 *          char      raw            encoded
 *          space     links          links
 *          #         links          links
 *          %         NO TIMELINE    links
 *          &         links          links
 *          +         links          links
 *          ?         links          links
 *
 *      So a raw space is survivable on this build — but a literal '%' is not: it makes
 *      an invalid percent-escape, and Resolve rejects THE WHOLE IMPORT over it, not the
 *      one clip, with no error. Encoding is what Resolve's own FCP7 exporter emits
 *      (it writes Media%20Drive), it fixed the fatal case, and it broke none of the
 *      other five — so encode, and do not rely on which characters happen to be
 *      tolerated by the build in front of you.
 *
 *   2. The SEQUENCE needs its own <rate>. Without it Resolve creates no timeline at all —
 *      not a partial one, not an offline one, nothing — however well-formed the clipitems
 *      are. Measured by bisecting this emitter's output against Resolve's own FCP7 export
 *      of the same cut: adding the sequence <rate> alone flipped the import from "no
 *      timeline" to 2 items / 2 linked, and it was the ONLY element that did. <duration>
 *      alone did not. The clipitem-level and file-level <duration>/<rate>/<enabled> that
 *      Resolve's exporter writes turned out not to be required.
 *
 *   3. Every file def needs a <timecode> block MATCHING the media's embedded timecode.
 *      Absent, zero, and wrong all silently reject THE ENTIRE IMPORT — not the one
 *      clip. Every property you would naturally suspect (durations, pathurl form,
 *      track count) is innocent. Because a wrong block is as fatal as no block, this
 *      emitter never guesses one: it writes the block when the clip carries its media's
 *      timecode and reports the clips that do not via fcp7TimecodeCoverage(), rather
 *      than emitting a plausible 00:00:00:00 that kills the import.
 */

const TPF_24 = 10584000000;

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/**
 * A local path → a Premiere-style file URL, percent-encoded PER SEGMENT so the '/'
 * separators survive. `encodeURIComponent` on the whole path would turn them into %2F.
 */
function pathToUrl(p) {
  if (!p) return '';
  return `file://localhost${String(p).split('/').map(encodeURIComponent).join('/')}`;
}

/** Frames dropped per drop-frame minute: 2 at 29.97, 4 at 59.94. */
const dropPerMinute = (fps) => Math.round(Number(fps) / 30) * 2;

/** "HH:MM:SS:FF" (or ";FF" for drop-frame) → absolute frame number. */
function tcToFrames(tc, fps, drop) {
  const m = String(tc).trim().match(/^(\d+):(\d{1,2}):(\d{1,2})[:;](\d{1,2})$/);
  if (!m) return null;
  const [hh, mm, ss, ff] = m.slice(1).map(Number);
  const base = Math.max(1, Math.round(Number(fps) || 24));
  const isDrop = drop != null ? Boolean(drop) : String(tc).includes(';');
  let frames = ((hh * 3600 + mm * 60 + ss) * base) + ff;
  if (isDrop) {
    const totalMinutes = hh * 60 + mm;
    frames -= dropPerMinute(fps) * (totalMinutes - Math.floor(totalMinutes / 10));
  }
  return frames;
}

/** Absolute frame number → "HH:MM:SS:FF" (";FF" when drop-frame). */
function framesToTc(frame, fps, drop) {
  const base = Math.max(1, Math.round(Number(fps) || 24));
  const f = Math.max(0, Math.round(Number(frame) || 0));
  const p2 = (n) => String(n).padStart(2, '0');
  let minutes;
  let rem;
  if (drop) {
    // Drop-frame counts SKIP labels, so the label is recovered by walking ten-minute
    // blocks: the first minute of each block drops nothing, the other nine drop `d`.
    const d = dropPerMinute(fps);
    const perMin = base * 60 - d;
    const perTenMin = perMin * 9 + base * 60;
    minutes = Math.floor(f / perTenMin) * 10;
    rem = f % perTenMin;
    if (rem >= base * 60) {
      rem -= base * 60;
      minutes += 1 + Math.floor(rem / perMin);
      rem = (rem % perMin) + d;
    }
  } else {
    minutes = Math.floor(f / (base * 60));
    rem = f % (base * 60);
  }
  const sep = drop ? ';' : ':';
  return `${p2(Math.floor(minutes / 60))}:${p2(minutes % 60)}:${p2(Math.floor(rem / base))}${sep}${p2(rem % base)}`;
}

/**
 * The media's embedded start timecode for a clip, as {frame, string, fps, drop} — or
 * null when the clip does not carry it. Accepts either a timecode string (`startTc`)
 * or an absolute frame (`startTcFrame`); when both are present the frame wins and the
 * string is re-derived from it, so the two halves of the emitted block cannot disagree.
 */
function clipTimecode(c, seqFps) {
  const fps = Number(c.startTcFps || c.srcFps || seqFps || 24);
  const drop = Boolean(c.startTcDrop);
  let frame = c.startTcFrame != null ? Math.round(Number(c.startTcFrame)) : null;
  if (frame == null && c.startTc != null) frame = tcToFrames(c.startTc, fps, c.startTcDrop);
  if (frame == null || !Number.isFinite(frame)) return null;
  return { frame, string: framesToTc(frame, fps, drop), fps, drop };
}

/**
 * Which clips will emit a <timecode> block and which will not. A clip missing its
 * media's timecode is not a cosmetic gap: Resolve rejects the WHOLE import over a
 * single absent block, so `missing` being non-empty means this XML will import nothing.
 */
function fcp7TimecodeCoverage(conformed) {
  const seqFps = (conformed.sequence || {}).fps || 24;
  const missing = [];
  let withTimecode = 0;
  (conformed.clips || []).forEach((c, i) => {
    if (clipTimecode(c, seqFps)) withTimecode += 1;
    else missing.push({ index: i, name: c.source_basename || '', path: c.path || '' });
  });
  return {
    total: (conformed.clips || []).length,
    withTimecode,
    missing,
    importable: missing.length === 0,
  };
}

function timecodeBlock(tc, indent) {
  return `\n${indent}<timecode><string>${tc.string}</string><frame>${tc.frame}</frame>`
    + `<displayformat>${tc.drop ? 'DF' : 'NDF'}</displayformat>`
    + `<rate><timebase>${Math.round(tc.fps)}</timebase><ntsc>${Number.isInteger(Number(tc.fps)) ? 'FALSE' : 'TRUE'}</ntsc></rate>`
    + `</timecode>`;
}

function toFcp7Xml(conformed, opts = {}) {
  const seq = conformed.sequence || {};
  const tpf = conformed.ticksPerFrame || opts.ticksPerFrame || TPF_24;
  const W = seq.width || 1920;
  const H = seq.height || 1080;
  const fps = seq.fps || 24;

  const clipitems = conformed.clips
    .map((c, i) => {
      const inFrame = c.sourceFrame;
      const dur = (c.seqend || c.seqstart) - c.seqstart;
      const ticksIn = inFrame * tpf; // CONSISTENT with <in>
      const ticksOut = (inFrame + dur) * tpf;
      const fileId = `file-${i + 1}`;
      const url = pathToUrl(c.path);
      const tc = clipTimecode(c, fps);
      return `      <clipitem id="clipitem-${i + 1}">
        <name>${esc(c.source_basename || `clip${c.seqstart}`)}</name>
        <start>${c.seqstart}</start>
        <end>${c.seqend || c.seqstart}</end>
        <in>${inFrame}</in>
        <out>${inFrame + dur}</out>
        <pproTicksIn>${ticksIn}</pproTicksIn>
        <pproTicksOut>${ticksOut}</pproTicksOut>
        <file id="${fileId}"><name>${esc(c.source_basename || '')}</name><pathurl>${url}</pathurl>${tc ? timecodeBlock(tc, '          ') : ''}
          <media><video><samplecharacteristics><width>${c.srcW || W}</width><height>${c.srcH || H}</height></samplecharacteristics></video></media>
        </file>
        <filter><effect><name>Basic Motion</name><effectid>basic</effectid>
          <parameter><parameterid>scale</parameterid><value>${c.scaleRaw != null ? c.scaleRaw : c.scale != null ? c.scale : 100}</value></parameter>
        </effect></filter>
      </clipitem>`;
    })
    .join('\n');

  const seqDur = conformed.clips.reduce((m, c) => Math.max(m, c.seqend || c.seqstart || 0), 0);
  const seqTc = clipTimecode({
    startTc: seq.startTc, startTcFrame: seq.startTcFrame,
    startTcFps: seq.startTcFps || fps, startTcDrop: seq.startTcDrop,
  }, fps);

  return `<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="4">
<sequence id="seq-conform">
  <name>${esc(seq.name || 'conform')}</name>
  <duration>${seqDur}</duration>
  <rate><timebase>${Math.round(fps)}</timebase><ntsc>${Number.isInteger(Number(fps)) ? 'FALSE' : 'TRUE'}</ntsc></rate>${seqTc ? timecodeBlock(seqTc, '  ') : ''}
  <media><video>
    <format><samplecharacteristics><rate><timebase>${fps}</timebase><ntsc>FALSE</ntsc></rate><width>${W}</width><height>${H}</height></samplecharacteristics></format>
    <track>
${clipitems}
    </track>
  </video></media>
</sequence>
</xmeml>`;
}

module.exports = { toFcp7Xml, fcp7TimecodeCoverage, pathToUrl, tcToFrames, framesToTc, TPF_24 };
