'use strict';

/**
 * synthetic/generate.js — build a tiny, fully-synthetic, ANONYMIZED portable
 * fixture with KNOWN golden answers (spec/harness: P0-synthetic-fixture).
 *
 * A real turnover.xml + frames are git-ignored client material, so on a
 * fresh clone the parser/comparator tests skip. This generator emits a small
 * crafted XMEML + test-pattern PNGs whose answers we compute by construction, so
 * the WHOLE suite runs client-free. The output is committed under
 * __fixtures__/synthetic/ (it contains no client data), and this generator makes
 * it reproducible. No fabricated "expected" numbers — every golden here is
 * derived from the same math the Oracle implements, encoded once.
 */

const fs = require('fs');
const path = require('path');
const sharp = require('sharp');

const TPF = 10584000000; // ticks/frame @24
const SEQ_W = 1920;
const SEQ_H = 1080;
const SRC_W = 960; // so seqW/srcW = 2.0 (fit = 200%)
const SRC_H = 540;

// ── Clip definitions (inputs) + the answers they imply by construction ────────
// expected_source_start = startoffset + in ; ticks encode in (or 2*in for 50%).
// expected_scale_corrected = scale * srcW / seqW.
const CLIPS = [
  { key: 'normal', start: 0, end: 48, in: 1000, suboff: null, scale: 200, speed: 100,
    center: { h: 0, v: 0 }, rotation: 0, crop: { left: 0, top: 0, right: 0, bottom: 0 } },
  { key: 'subclip', start: 48, end: 96, in: 500, suboff: 2000, scale: 200, speed: 100,
    center: { h: 0, v: 0 }, rotation: 0, crop: { left: 0, top: 0, right: 0, bottom: 0 } },
  { key: 'slowmo', start: 96, end: 144, in: 3000, suboff: null, scale: 200, speed: 200, slow: true,
    center: { h: 0, v: 0 }, rotation: 0, crop: { left: 0, top: 0, right: 0, bottom: 0 } },
  { key: 'reframe', start: 144, end: 192, in: 4000, suboff: null, scale: 250, speed: 100,
    center: { h: 120, v: -60 }, rotation: 5, crop: { left: 10, top: 4, right: 8, bottom: 2 } },
];

function ticksFor(clip) {
  // 50% slow-mo: ticks/tpf = 2*in (the Oracle detects retime here); else ticks/tpf = in.
  const frames = clip.slow ? clip.in * 2 : clip.in;
  return frames * TPF;
}

function expectedSourceStart(clip) {
  return (clip.suboff || 0) + clip.in;
}

function expectedScaleCorrected(clip) {
  return (clip.scale * SRC_W) / SEQ_W;
}

// ── XMEML emission ────────────────────────────────────────────────────────────
function fileDef(id, basename, full) {
  if (!full) return `<file id="${id}"/>`;
  return `<file id="${id}">
  <name>${basename}</name>
  <pathurl>file://localhost/SYNTH/${encodeURIComponent(basename)}</pathurl>
  <media><video><samplecharacteristics>
    <width>${SRC_W}</width><height>${SRC_H}</height>
  </samplecharacteristics></video></media>
</file>`;
}

function clipXml(clip, idx) {
  const fileId = `file-${idx + 1}`;
  const basename = `SYNTH_${clip.key}.mov`;
  // Exercise file-id resolution: the 'normal' clip defines file-1 fully; later
  // clips define their own; we ALSO make 'subclip' reference normal's file by id
  // only when keys match — here each clip has its own file for clarity, but the
  // 'reframe' clip references file-1 self-closing to prove resolution.
  const usesSharedFile = clip.key === 'reframe';
  const effectiveId = usesSharedFile ? 'file-1' : fileId;
  const file = usesSharedFile ? fileDef('file-1', 'SYNTH_normal.mov', false) : fileDef(fileId, basename, true);
  const sub = clip.suboff != null ? `<subclipinfo><startoffset>${clip.suboff}</startoffset></subclipinfo>` : '';
  const timeRemap = clip.speed !== 100
    ? `<filter><effect><name>Time Remap</name><effectid>timeremap</effectid>
        <parameter><parameterid>speed</parameterid><value>${clip.speed}</value></parameter>
        <parameter><parameterid>variablespeed</parameterid><value>0</value></parameter>
      </effect></filter>`
    : '';
  return `<clipitem id="clipitem-${idx + 1}">
  <name>${clip.key}</name>
  <start>${clip.start}</start>
  <end>${clip.end}</end>
  <in>${clip.in}</in>
  <out>${clip.in + (clip.end - clip.start)}</out>
  <pproTicksIn>${ticksFor(clip)}</pproTicksIn>
  <pproTicksOut>${ticksFor(clip) + (clip.end - clip.start) * TPF}</pproTicksOut>
  ${effectiveId === 'file-1' ? file : file}
  ${sub}
  <filter><effect><name>Basic Motion</name><effectid>basic</effectid>
    <parameter><parameterid>scale</parameterid><value>${clip.scale}</value></parameter>
    <parameter><parameterid>rotation</parameterid><value>${clip.rotation}</value></parameter>
    <parameter><parameterid>center</parameterid><value><horiz>${clip.center.h}</horiz><vert>${clip.center.v}</vert></value></parameter>
    <parameter><parameterid>leftcrop</parameterid><value>${clip.crop.left}</value></parameter>
    <parameter><parameterid>topcrop</parameterid><value>${clip.crop.top}</value></parameter>
    <parameter><parameterid>rightcrop</parameterid><value>${clip.crop.right}</value></parameter>
    <parameter><parameterid>bottomcrop</parameterid><value>${clip.crop.bottom}</value></parameter>
  </effect></filter>
  ${timeRemap}
</clipitem>`;
}

function buildXml() {
  const clipitems = CLIPS.map(clipXml).join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>
<xmeml version="4">
<sequence id="seq-synth">
  <name>SYNTH_REEL</name>
  <media><video>
    <format><samplecharacteristics>
      <rate><timebase>24</timebase><ntsc>FALSE</ntsc></rate>
      <width>${SEQ_W}</width><height>${SEQ_H}</height>
    </samplecharacteristics></format>
    <track>
${clipitems}
    </track>
  </video></media>
</sequence>
</xmeml>`;
}

// ── Frame (PNG) emission ──────────────────────────────────────────────────────
const FW = 384;
const FH = 216;

function patternBase(x, y) {
  // A structured "scene": gradients + edges + sinusoids. 0..1.
  const g = 0.4 + 0.3 * (x / FW);
  const s = 0.15 * Math.sin(x * 0.10) * Math.cos(y * 0.08);
  const block = x > FW * 0.55 && x < FW * 0.8 && y > FH * 0.3 && y < FH * 0.75 ? 0.2 : 0;
  return Math.max(0, Math.min(1, g + s + block));
}

function patternOther(x, y) {
  // A clearly different scene (for the WRONG case).
  const r = Math.hypot(x - FW * 0.5, y - FH * 0.5) / (FW * 0.5);
  return Math.max(0, Math.min(1, 0.7 - 0.5 * r + 0.2 * Math.sin(y * 0.2)));
}

function withBurnIn(val, x, y) {
  // Simulated burn-ins: bright top-center TC box + bottom strip.
  const fx = x / FW;
  const fy = y / FH;
  if (fy >= 0.92) return 0.95;
  if (fy >= 0.07 && fy <= 0.17 && fx >= 0.36 && fx <= 0.64) return 0.95;
  return val;
}

function renderRaw(fn) {
  const buf = Buffer.alloc(FW * FH);
  for (let y = 0; y < FH; y++) {
    for (let x = 0; x < FW; x++) {
      buf[y * FW + x] = Math.round(fn(x, y) * 255);
    }
  }
  return buf;
}

async function writePng(buf, file) {
  await sharp(buf, { raw: { width: FW, height: FH, channels: 1 } }).png().toFile(file);
}

async function generateAll(outDir) {
  fs.mkdirSync(outDir, { recursive: true });
  const framesDir = path.join(outDir, 'frames');
  fs.mkdirSync(framesDir, { recursive: true });

  // XML + oracle golden
  fs.writeFileSync(path.join(outDir, 'turnover.synth.xml'), buildXml());
  const oracle = {
    sequence: { name: 'SYNTH_REEL', width: SEQ_W, height: SEQ_H, fps: 24 },
    ticksPerFrame: TPF,
    clipCount: CLIPS.length,
    clips: CLIPS.map((c) => ({
      key: c.key,
      seqstart: c.start,
      xml_in: c.in,
      is_subclip: c.suboff != null,
      subclip_startoffset: c.suboff || 0,
      pproTicksIn: ticksFor(c),
      scale_premiere: c.scale,
      speed: c.speed,
      center: c.center,
      rotation: c.rotation,
      crop: c.crop,
      srcW: SRC_W,
      srcH: SRC_H,
      expected_source_start: expectedSourceStart(c),
      expected_sample_frame: (c.suboff || 0) + (c.slow ? c.in * 2 : c.in),
      expected_scale_corrected: expectedScaleCorrected(c),
    })),
  };
  fs.writeFileSync(path.join(outDir, 'golden_oracle.synth.json'), JSON.stringify(oracle, null, 1));

  // Frames: match (same), dark-trap (ref darkened), wrong (different)
  const base = renderRaw(patternBase);
  const baseBurn = renderRaw((x, y) => withBurnIn(patternBase(x, y), x, y));
  const baseDarkBurn = renderRaw((x, y) => withBurnIn(patternBase(x, y) * 0.22, x, y));
  const other = renderRaw(patternOther);
  const otherBurn = renderRaw((x, y) => withBurnIn(patternOther(x, y), x, y));

  await writePng(baseBurn, path.join(framesDir, 'match__reference.png'));
  await writePng(base, path.join(framesDir, 'match__derived.png'));
  await writePng(baseDarkBurn, path.join(framesDir, 'darktrap__reference.png'));
  await writePng(base, path.join(framesDir, 'darktrap__derived.png'));
  await writePng(otherBurn, path.join(framesDir, 'wrong__reference.png'));
  await writePng(base, path.join(framesDir, 'wrong__derived.png'));

  const compare = {
    note: 'Synthetic, client-free. darktrap reference is darkened 0.22x — brightness-robust metric must still MATCH.',
    cases: [
      { label: 'match', expected_verdict: 'MATCH', reference: 'frames/match__reference.png', derived: 'frames/match__derived.png' },
      { label: 'darktrap', expected_verdict: 'MATCH', reference: 'frames/darktrap__reference.png', derived: 'frames/darktrap__derived.png' },
      { label: 'wrong', expected_verdict: 'WRONG', reference: 'frames/wrong__reference.png', derived: 'frames/wrong__derived.png' },
    ],
  };
  fs.writeFileSync(path.join(outDir, 'golden_compare.synth.json'), JSON.stringify(compare, null, 1));

  return { outDir, clips: CLIPS.length };
}

module.exports = { generateAll, buildXml, CLIPS, TPF, SEQ_W, SRC_W };

if (require.main === module) {
  const out = path.join(__dirname, '..', '__fixtures__', 'synthetic');
  generateAll(out).then((r) => {
    // eslint-disable-next-line no-console
    console.log(`synthetic fixture written to ${r.outDir} (${r.clips} clips + frames)`);
  });
}
