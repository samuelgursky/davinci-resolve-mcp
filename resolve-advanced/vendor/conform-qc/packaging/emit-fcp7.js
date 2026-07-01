'use strict';

/**
 * package/emit-fcp7.js — emit FCP7 (xmeml) XML from the conformed timeline.
 *
 * NON-NEGOTIABLE #5: keep <in> and <pproTicksIn> CONSISTENT (Resolve reads the
 * ticks). We always emit ticks = sourceFrame * ticksPerFrame so a re-import
 * reproduces the same source frame. Round-trippable through parse/xmeml-geometry.
 */

const TPF_24 = 10584000000;

function esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
      const url = c.path ? `file://localhost${esc(c.path)}` : '';
      return `      <clipitem id="clipitem-${i + 1}">
        <name>${esc(c.source_basename || `clip${c.seqstart}`)}</name>
        <start>${c.seqstart}</start>
        <end>${c.seqend || c.seqstart}</end>
        <in>${inFrame}</in>
        <out>${inFrame + dur}</out>
        <pproTicksIn>${ticksIn}</pproTicksIn>
        <pproTicksOut>${ticksOut}</pproTicksOut>
        <file id="${fileId}"><name>${esc(c.source_basename || '')}</name><pathurl>${url}</pathurl>
          <media><video><samplecharacteristics><width>${c.srcW || W}</width><height>${c.srcH || H}</height></samplecharacteristics></video></media>
        </file>
        <filter><effect><name>Basic Motion</name><effectid>basic</effectid>
          <parameter><parameterid>scale</parameterid><value>${c.scaleRaw != null ? c.scaleRaw : c.scale != null ? c.scale : 100}</value></parameter>
        </effect></filter>
      </clipitem>`;
    })
    .join('\n');

  return `<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="4">
<sequence id="seq-conform">
  <name>${esc(seq.name || 'conform')}</name>
  <media><video>
    <format><samplecharacteristics><rate><timebase>${fps}</timebase><ntsc>FALSE</ntsc></rate><width>${W}</width><height>${H}</height></samplecharacteristics></format>
    <track>
${clipitems}
    </track>
  </video></media>
</sequence>
</xmeml>`;
}

module.exports = { toFcp7Xml, TPF_24 };
