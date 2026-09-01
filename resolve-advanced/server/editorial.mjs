/**
 * Cluster E — editorial integrity. The turnover interchange (XML/EDL/OTIO) → a normalized
 * edit-event list → a structured CHANGELIST (what moved/retimed/replaced/appeared/vanished) and
 * a per-event CONFORM MANIFEST assert BEFORE grading. This is the north star made real: the
 * changelist drives the frame-QC worklist.
 *
 * TIMING silent-lie discipline (cross-craft review): flattened retime · dropped J/L-cut audio ·
 * framerate/pulldown slip · reverse dropped · transition-handle starvation — THROW/FLAG,
 * skip-not-fake. A conform that silently flattens a speed ramp or drops split-track audio is the
 * timing analogue of a faked grade.
 *
 * Interchange breadth AT INGEST: EDL (CMX3600) + OTIO (JSON) parse natively here; XMEML via a
 * light clipitem parse. AAF is binary — parsed offline via aaf.mjs → pyaaf2 (async, out-of-band);
 * parseInterchange() itself stays PURE and points AAF callers at that async path. Premiere .prproj
 * is a closed binary project — honest refuse with an actionable convert-upstream message.
 *
 * PURE + deterministic (edl/otio/xmeml). No Resolve, no LLM.
 */
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

// ── timecode ───────────────────────────────────────────────────────────
const TC_RE = /^(\d{2}):(\d{2}):(\d{2})[:;](\d{2,3})$/;
export function tcToFrames(tc, fps) {
  const raw = String(tc).trim();
  const m = TC_RE.exec(raw);
  if (!m || !fps) return null;
  const [, h, mm, s, f] = m.map(Number);
  // SMPTE timecode counts NOMINAL frames (base 30 for 29.97, 24 for 23.976) —
  // measured against Resolve's own GetStartFrame (Studio 19.1.3.7). The
  // previous exact-rate product undercounted NTSC by 0.1% (108 frames/hour).
  const nominal = Math.round(fps);
  let frames = (h * 3600 + mm * 60 + s) * nominal + f;
  if (raw.includes(';')) {
    const dropped = Math.round(nominal * 0.0666666667);
    const totalMinutes = h * 60 + mm;
    frames -= dropped * (totalMinutes - Math.floor(totalMinutes / 10));
  }
  return frames;
}
const isTc = (t) => TC_RE.test(t);

/**
 * Normalized edit event. All positions in FRAMES.
 * { index, track, source, srcIn, srcOut, recIn, recOut, speed(%), reverse, transition, fps }
 */
function evt(o) {
  return {
    index: o.index ?? null,
    track: o.track || 'V',
    ...(o.name !== undefined ? { name: o.name } : {}),
    ...(o.color !== undefined ? { color: o.color } : {}),
    ...(o.generatorName !== undefined ? { generatorName: o.generatorName } : {}),
    ...(o.fromCompound !== undefined ? { fromCompound: o.fromCompound } : {}),
    ...(o.compound !== undefined ? { compound: o.compound } : {}),
    source: o.source || 'UNKNOWN',
    srcIn: o.srcIn ?? null,
    srcOut: o.srcOut ?? null,
    recIn: o.recIn ?? null,
    recOut: o.recOut ?? null,
    speed: o.speed ?? 100,
    reverse: o.reverse ?? false,
    transition: o.transition || null,
    ...(o.itemMarkers !== undefined ? { itemMarkers: o.itemMarkers } : {}),
    fps: o.fps ?? null,
  };
}

// ── EDL (CMX3600) ──────────────────────────────────────────────────────
/** Parse a CMX3600 EDL text into normalized events. */
export function parseEDL(text, opts = {}) {
  const fps = opts.fps ?? 24;
  const events = [];
  let pendingSpeed = null; // from an M2 motion line preceding/following the event
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    // Motion (speed) line: M2 <reel> <fps-signed> <srcTC>
    const m2 = /^M2\s+(\S+)\s+(-?\d+(?:\.\d+)?)/.exec(line);
    if (m2) {
      const playFps = Number(m2[2]);
      pendingSpeed = { reel: m2[1], speedPct: fps ? (playFps / fps) * 100 : 100, reverse: playFps < 0 };
      // Attach to the last event with this reel.
      const target = [...events].reverse().find((e) => e.source === m2[1]);
      if (target) {
        target.speed = +Math.abs(pendingSpeed.speedPct).toFixed(2);
        target.reverse = pendingSpeed.reverse;
      }
      continue;
    }
    // Avid-style locators: `* LOC: 01:00:01:12 BLUE marker text` — a marker
    // at an absolute record timecode. Emitted as track 'MARKER' pseudo-events
    // (recIn only) so the assemble bridge can author them; consumers that
    // filter video/audio by track shape ignore them.
    // `* FROM CLIP NAME:` / `* TO CLIP NAME:` comments (E105): Resolve's own
    // EDL writer names every file source by the generic reel AX and carries
    // the real clip name here. TO names the incoming (the last event, a D
    // line's), FROM the outgoing (the event before a transition pair, else
    // the last event). A generic reel (AX/BL-less) takes the clip name as
    // its source so sourceMap and QC key on something real; a specific reel
    // keeps it, with clipName carried alongside.
    const cn = /^\*\s*(FROM|TO)\s+CLIP\s+NAME:\s*(.+?)\s*$/i.exec(line);
    if (cn) {
      const which = cn[1].toUpperCase();
      const clipName = cn[2];
      const last = [...events].reverse().find((e) => e.track !== 'MARKER');
      let target = last;
      if (which === 'FROM' && last && last.transition) {
        const prev = [...events].reverse().find((e) => e !== last && e.track === last.track && e.recOut === last.recIn);
        if (prev) target = prev;
      }
      if (target && !/^(BL|BLACK)$/i.test(String(target.source))) {
        target.clipName = clipName;
        if (/^AX$/i.test(String(target.source))) target.source = clipName;
      }
      continue;
    }
    const loc = /^\*\s*LOC:\s*(\d{2}:\d{2}:\d{2}[:;]\d{2})\s+(\S+)\s*(.*)$/i.exec(line);
    if (loc) {
      events.push(evt({
        index: events.length + 1, track: 'MARKER', source: '',
        recIn: tcToFrames(loc[1], fps), recOut: null,
        name: loc[3].trim() || undefined, color: loc[2], fps,
      }));
      continue;
    }
    const tokens = line.split(/\s+/);
    if (!/^\d+$/.test(tokens[0])) continue; // not an event line
    const tcs = tokens.filter(isTc);
    if (tcs.length < 4) continue;
    const [srcIn, srcOut, recIn, recOut] = tcs.slice(-4);
    const head = tokens.slice(0, tokens.indexOf(tcs[tcs.length - 4]));
    const [eventNum, reel, channel, transition] = head;
    const dur = transition && transition !== 'C' ? Number(head[4]) : 0;
    const chan = String(channel || '');
    const am = /^A(\d+)?$/i.exec(chan);
    const track = am && !/V/i.test(chan) ? (am[1] && am[1] !== '1' ? `A${am[1]}` : 'A') : (/A/i.test(chan) && !/V/i.test(chan) ? 'A' : 'V');
    events.push(
      evt({
        index: Number(eventNum),
        track,
        source: reel,
        srcIn: tcToFrames(srcIn, fps),
        srcOut: tcToFrames(srcOut, fps),
        recIn: tcToFrames(recIn, fps),
        recOut: tcToFrames(recOut, fps),
        // CMX convention: the dissolve/wipe span STARTS at the cut (occupies
        // the first `dur` frames of the incoming event) — matching what
        // Resolve's own EDL importer authors (E61 harvest: Start == the cut).
        transition: transition && transition !== 'C' ? { type: transition, duration: dur || 0, alignment: 'start' } : null,
        fps,
      }),
    );
  }
  return events;
}

// ── OTIO (JSON) ────────────────────────────────────────────────────────
/** Parse an OTIO timeline JSON (object or string) into normalized events. */
export function parseOTIO(otio, opts = {}) {
  const doc = typeof otio === 'string' ? JSON.parse(otio) : otio;
  const tracks = (doc.tracks && doc.tracks.children) || [];
  const events = [];
  let idx = 1;
  let vNum = 0;
  let aNum = 0;
  for (const track of tracks) {
    const isAudio = track.kind === 'Audio';
    if (isAudio) aNum += 1; else vNum += 1;
    // First track of each kind keeps the bare letter (compat); higher tracks
    // are numbered ('V2', 'A2', …).
    const kind = isAudio ? (aNum === 1 ? 'A' : `A${aNum}`) : (vNum === 1 ? 'V' : `V${vNum}`);
    // Track-level markers: marked_range is already in track (record) time.
    for (const mk of track.markers || []) {
      const mrStart = (mk.marked_range && mk.marked_range.start_time && mk.marked_range.start_time.value) || 0;
      const mrRate = (mk.marked_range && mk.marked_range.start_time && mk.marked_range.start_time.rate) || opts.fps || 24;
      events.push(evt({
        index: idx++, track: 'MARKER', source: '',
        recIn: mrStart, recOut: null,
        name: mk.name || undefined, color: mk.color || undefined, fps: mrRate,
      }));
    }
    // Walk one track's children into `sink`. Recursive: a nested Stack (a
    // compound clip) walks its inner tracks with a private cursor and is
    // flattened into the parent's record time (E120).
    const walkChildren = (children, kind, sink) => {
    let rec = 0;
    // An OTIO Transition occupies NO record time (like an AAF transition —
    // it overlaps its neighbours); it describes the junction between the
    // previous and NEXT clip. Carry it to the next clip event's transition
    // field so the bridge can author it (type strings like SMPTE_Dissolve
    // map through the same style table as XMEML effectids).
    let pendingTransition = null;
    // Track start counts as black: a Transition with a Gap (or nothing) on
    // one side is a FADE. It routes through the same BL machinery as EDL BL
    // dissolves (E91/E92): a synthetic zero-length BL event materializes the
    // black side, and the bridge authors a real clip↔generator dissolve —
    // empty track renders black anyway, so the growth is render-neutral.
    let atBlack = true;
    const lastRate = () => opts.fps || 24;
    for (const child of children || []) {
      const schema = child.OTIO_SCHEMA || '';
      const dur = (child.source_range && child.source_range.duration && child.source_range.duration.value) || 0;
      const rate = (child.source_range && child.source_range.duration && child.source_range.duration.rate) || opts.fps || 24;
      if (schema.startsWith('Gap')) {
        if (pendingTransition) {
          // Transition then Gap = fade-out into black: attach it to a
          // synthetic BL leg at the junction (the bridge grows it forward).
          sink.push(evt({
            index: idx++, track: kind, source: 'BL',
            recIn: rec, recOut: rec, transition: pendingTransition, fps: lastRate(),
          }));
          pendingTransition = null;
        } else {
          pendingTransition = null; // a mid-timeline gap breaks a junction
        }
        rec += dur;
        atBlack = true;
        continue;
      }
      if (schema.startsWith('Stack')) {
        // NESTED STACK = a compound clip (E120, measured against Resolve's
        // OTIO writer: a compound exports as a Stack inside the track with
        // its own source_range = the trim window into the compound, nested
        // recursively). It was silently DROPPED. Flatten it: walk each inner
        // track of this kind with a private cursor, then translate its
        // events into the parent's record time through the trim window,
        // trimming source frames at the clip's own play rate. Inner tracks
        // beyond the first land on the next lanes up (V2, V3 …).
        const sr = child.source_range || {};
        const winStart = (sr.start_time && sr.start_time.value) || 0;
        const winDur = (sr.duration && sr.duration.value) || 0;
        const wantAudio = /^A/.test(kind);
        const innerTracks = (child.children || []).filter((t) => String(t.OTIO_SCHEMA || '').startsWith('Track') && ((t.kind === 'Audio') === wantAudio));
        const baseLetter = kind.replace(/\d+$/, '');
        const baseNum = parseInt(kind.replace(/\D/g, '') || '1', 10);
        let first = true;
        innerTracks.forEach((it, i) => {
          const label = baseNum + i === 1 ? baseLetter : `${baseLetter}${baseNum + i}`;
          const tmp = [];
          walkChildren(it.children || [], label, tmp);
          for (const e of tmp) {
            if (e.track === 'MARKER') continue;
            const a = e.recIn - winStart, b = e.recOut - winStart;
            const a2 = Math.max(0, a), b2 = Math.min(winDur, b);
            if (b2 <= a2) continue;
            const k = ((e.speed ?? 100) / 100) * (e.reverse ? -1 : 1);
            const flat = {
              ...e, index: idx++, recIn: rec + a2, recOut: rec + b2,
              srcIn: e.srcIn != null ? e.srcIn + (a2 - a) * k : e.srcIn,
              srcOut: e.srcOut != null ? e.srcOut - (b - b2) * k : e.srcOut,
              fromCompound: child.name || 'compound',
            };
            // A transition pending INTO the compound attaches to its first flattened cut.
            if (first && pendingTransition && !flat.transition) flat.transition = pendingTransition;
            first = false;
            sink.push(flat);
          }
        });
        pendingTransition = null;
        atBlack = false;
        rec += winDur;
        continue;
      }
      if (schema.startsWith('Transition')) {
        const inOff = (child.in_offset && child.in_offset.value) || 0;
        const outOff = (child.out_offset && child.out_offset.value) || 0;
        // in_offset = frames BEFORE the cut, out_offset = frames after; the
        // bridge places the span [cut - inOffset, cut + outOffset).
        pendingTransition = { type: String(child.transition_type || 'SMPTE_Dissolve'), duration: inOff + outOff, inOffset: inOff };
        continue;
      }
      if (schema.startsWith('Clip')) {
        if (pendingTransition && atBlack) {
          // Gap (or track start) then Transition then Clip = fade-IN from
          // black — the CMX zero-length-BL form, grown by the bridge.
          sink.push(evt({
            index: idx++, track: kind, source: 'BL',
            recIn: rec, recOut: rec, fps: rate,
          }));
        }
        atBlack = false;
        const startVal = (child.source_range && child.source_range.start_time && child.source_range.start_time.value) || 0;
        // Retime via a LinearTimeWarp effect (time_scalar).
        let speed = 100,
          reverse = false;
        for (const eff of child.effects || []) {
          if (eff.time_scalar != null) {
            speed = +(eff.time_scalar * 100).toFixed(2);
            reverse = eff.time_scalar < 0;
          }
          // OTIO FreezeFrame is a LinearTimeWarp subclass whose time_scalar
          // is 0 by definition — writers commonly omit the field, which
          // read as a plain 100% clip here (E103). Speed 0 authors a freeze.
          if (/^FreezeFrame\b/.test(String(eff.OTIO_SCHEMA || ''))) {
            speed = 0;
            reverse = false;
          }
        }
        const mref = child.media_reference || null;
        const mrefSchema = String((mref && mref.OTIO_SCHEMA) || '');
        const clipName = String(child.name || '');
        // GENERATOR clips (E118): Resolve's OTIO writer emits a Solid Color as
        // a Clip with a NULL media_reference named after the generator
        // (measured E117); OTIO proper uses a GeneratorReference. Neither
        // is a source reel — they walk as BL legs (a colour, when a
        // GeneratorReference carries one, rides along) so the bridge authors
        // a generator instead of refusing the turnover as an unmapped reel.
        const isGeneratorRef = /^GeneratorReference/.test(mrefSchema);
        const isGeneratorClip = isGeneratorRef || ((!mref || /^MissingReference/.test(mrefSchema)) && /solid color|colou?r matte|^black$/i.test(clipName));
        let genColor;
        if (isGeneratorRef && mref.parameters && typeof mref.parameters === 'object') {
          const pc = mref.parameters.color || mref.parameters.Color || mref.parameters.fillcolor || null;
          if (pc && typeof pc === 'object' && pc.r != null) genColor = { r: Number(pc.r) || 0, g: Number(pc.g) || 0, b: Number(pc.b) || 0, a: pc.a != null ? Number(pc.a) : 1 };
          else if (Array.isArray(pc) && pc.length >= 3) genColor = { r: Number(pc[0]) || 0, g: Number(pc[1]) || 0, b: Number(pc[2]) || 0, a: pc.length > 3 ? Number(pc[3]) : 1 };
          if (genColor && genColor.r === 0 && genColor.g === 0 && genColor.b === 0) genColor = undefined;
        }
        const src = isGeneratorClip ? 'BL' : ((mref && (mref.target_url || mref.name)) || clipName || 'UNKNOWN');
        // CLIP markers belong to the ITEM, not the sequence — carried as
        // itemMarkers (frames CLIP-relative) so the bridge authors them as
        // Sm2TiItemLockableBlobs (E80). Track-level markers above remain
        // timeline markers.
        const itemMarkers = [];
        for (const mk of child.markers || []) {
          const mrStart = (mk.marked_range && mk.marked_range.start_time && mk.marked_range.start_time.value) || 0;
          itemMarkers.push({ frame: mrStart - startVal, name: mk.name || undefined, color: mk.color || undefined });
        }
        sink.push(
          evt({
            index: idx++,
            track: kind,
            source: src,
            srcIn: startVal,
            srcOut: startVal + dur,
            recIn: rec,
            recOut: rec + dur,
            speed: Math.abs(speed),
            reverse,
            transition: pendingTransition,
            itemMarkers: itemMarkers.length ? itemMarkers : undefined,
            color: genColor,
            generatorName: isGeneratorClip ? (clipName || (mref && mref.name) || 'Solid Color') : undefined,
            fps: rate,
          }),
        );
        pendingTransition = null;
        rec += dur;
      }
    }
    if (pendingTransition) {
      // Transition as the LAST child = fade-out to the end of the track.
      sink.push(evt({
        index: idx++, track: kind, source: 'BL',
        recIn: rec, recOut: rec, transition: pendingTransition, fps: lastRate(),
      }));
    }
    };
    walkChildren(track.children || [], kind, events);
  }
  return events;
}

// ── XMEML (FCP7 XML) — light clipitem parse ────────────────────────────
/**
 * A generatoritem's `fillcolor` parameter → {r,g,b,a} in 0..1, or null when
 * absent/black (the default Solid Color). FCP7 XML writes 0..255 channels
 * (Premiere Color Matte and Resolve's own export alike).
 */
function xmemlFillColor(g) {
  const params = g && g.effect && g.effect.parameter ? (Array.isArray(g.effect.parameter) ? g.effect.parameter : [g.effect.parameter]) : [];
  for (const pm of params) {
    // Premiere writes the matte colour as `fillcolor`; Resolve's OWN writer
    // emits a Solid Color's colour as the FxPlug input parameter `input_1`
    // (measured E112) — any RGB-valued generator parameter is the colour.
    if (!pm.value || typeof pm.value !== 'object' || pm.value.red == null || pm.value.green == null || pm.value.blue == null) continue;
    const ch = (k) => { const v = Number(pm.value[k]); return Number.isFinite(v) ? Math.max(0, Math.min(255, v)) / 255 : 0; };
    const c = { r: ch('red'), g: ch('green'), b: ch('blue'), a: pm.value.alpha != null ? ch('alpha') : 1 };
    if (c.r === 0 && c.g === 0 && c.b === 0) return null; // black = the default leg
    return c;
  }
  return null;
}

export function parseXMEMLEvents(xml, opts = {}) {
  const { XMLParser } = require('fast-xml-parser');
  const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '@_' });
  const doc = parser.parse(xml);
  const events = [];
  let idx = 1;
  const seqRate = opts.fps || 24;
  let currentJunctions = [];
  // Record-order cursor for -1/-1 edge resolution (E107): a clip whose both
  // edges are -1 pairs junctions at or after the previous CLIP's end —
  // generator legs (walked first) never advance it. Without this, two
  // equal-length clips under three centered transitions both resolved to
  // the first junction pair (measured against Resolve's own writer).
  let clipCursor = 0;
  const walk = (node, track, advanceCursor = true) => {
    if (!node) return;
    const items = Array.isArray(node) ? node : [node];
    for (const it of items) {
      const name = it.name || (it.file && it.file.name) || 'UNKNOWN';
      const start0 = Number(it.start);
      const end0 = Number(it.end);
      const inF = Number(it.in);
      const outF = Number(it.out);
      let speed = 100,
        reverse = false;
      // speed via a timeremap/motion filter. EXACT parameter match (E105):
      // Resolve's own FCP7 writer emits `speed` 50 followed by
      // `variablespeed` 0 in the same effect, and a loose /speed/ match let
      // the second overwrite the first — every retime read as a FREEZE.
      const filters = it.filter ? (Array.isArray(it.filter) ? it.filter : [it.filter]) : [];
      for (const fl of filters) {
        const params = fl.effect && fl.effect.parameter ? (Array.isArray(fl.effect.parameter) ? fl.effect.parameter : [fl.effect.parameter]) : [];
        for (const pm of params) {
          const pid = String(pm.parameterid || pm.name || '').trim().toLowerCase();
          if (pid === 'speed' && pm.value != null && typeof pm.value !== 'object') {
            const v = Number(pm.value);
            if (Number.isFinite(v)) { speed = Math.abs(v); reverse = v < 0; }
          } else if (pid === 'reverse' && /^true$/i.test(String(pm.value))) {
            reverse = true;
          }
        }
      }
      // FCP7 `-1` EDGES (E105, measured against Resolve's own FCP7 writer):
      // a clipitem edge under a transitionitem is written as -1 and means
      // "this edge is the adjacent transition's JUNCTION" — the span center
      // for alignment center, its start/end for start-black/end-black.
      // `out - in` is the RECORD duration even under a retime (Resolve
      // writes out = in + record length), which anchors the missing edge.
      let start = start0;
      let end = end0;
      let inAdj = 0;
      const dur = Number.isFinite(inF) && Number.isFinite(outF) ? outF - inF : null;
      const junctions = currentJunctions;
      if (start === -1 && end !== -1 && dur != null) start = end - dur;
      else if (end === -1 && start !== -1 && dur != null) end = start + dur;
      else if (start === -1 && end === -1 && dur != null && junctions.length) {
        const js = junctions.map((j) => j.frame).sort((a, b) => a - b);
        const floor = advanceCursor ? clipCursor : 0;
        const pair = js.find((a) => a >= floor && js.includes(a + dur));
        if (pair != null) { start = pair; end = pair + dur; }
      }
      if (advanceCursor && Number.isFinite(end) && end >= 0) clipCursor = Math.max(clipCursor, end);
      // A -1 START edge's `in` is the source at the OVERLAP start (the
      // clip's material begins under the transition), while the resolved
      // start is the junction — so `in` advances by the same offset to stay
      // record-aligned (measured: srcIn read 12 short without this).
      if (start0 === -1 && Number.isFinite(start)) {
        const j = junctions.find((jj) => jj.frame === start);
        if (j) inAdj = start - j.start;
      }
      if (Number.isFinite(start) && Number.isFinite(end) && start >= 0 && end >= 0) {
        // FCP7 clipitem <marker> children are CLIP markers (frames relative
        // to the clip's own <in>) — routed to item markers like OTIO's (E81).
        const mks = it.marker ? (Array.isArray(it.marker) ? it.marker : [it.marker]) : [];
        const itemMarkers = mks
          .filter((mk) => Number.isFinite(Number(mk.in)))
          .map((mk) => ({ frame: Number(mk.in) - inF, name: mk.name != null ? String(mk.name) : undefined, note: mk.comment != null ? String(mk.comment) : undefined }));
        // Resolve's FCP7 writer flattens a COMPOUND CLIP to one clipitem whose
        // <file> carries an explicitly EMPTY <pathurl> and no inner content
        // (measured E120/E121). Tag it so the bridge can drop it with a
        // reason instead of refusing the whole turnover as an unmapped reel.
        const isCompound = !!(it.file && typeof it.file.pathurl === 'string' && it.file.pathurl.trim() === '' && !it.__genColor && name !== 'BL');
        events.push(evt({ index: idx++, track, source: name, srcIn: Number.isFinite(inF) ? inF + inAdj : inF, srcOut: Number.isFinite(outF) ? outF + inAdj : outF, recIn: start, recOut: end, speed, reverse, itemMarkers: itemMarkers.length ? itemMarkers : undefined, color: it.__genColor || undefined, compound: isCompound ? name : undefined, fps: seqRate }));
      }
    }
  };
  // A track's transitionitems as -1-edge junctions (alignment-dependent frame
  // plus the span), shared by video and audio lanes.
  const trackJunctionsOf = (t) => {
    const tlist = t.transitionitem ? (Array.isArray(t.transitionitem) ? t.transitionitem : [t.transitionitem]) : [];
    return tlist.map((tr) => {
      const s0 = Number(tr.start), e0 = Number(tr.end);
      if (!Number.isFinite(s0) || !Number.isFinite(e0)) return null;
      const al = String(tr.alignment || 'center').toLowerCase();
      const frame = al === 'start-black' || al === 'start' ? s0 : al === 'end-black' || al === 'end' ? e0 : Math.round((s0 + e0) / 2);
      return { frame, start: s0, end: e0 };
    }).filter(Boolean);
  };
  // Attach a track's <transitionitem> siblings to its walked events. Shared
  // by VIDEO and AUDIO tracks (E108): audio cross-fades used to be dropped at
  // parse because only the video walk looked at transitionitems, so an XMEML
  // audio cross-fade never reached the bridge that authors them.
  const attachTransitions = (t, label, before) => {
  // <transitionitem> siblings: attach each to the INCOMING clip event —
    // the one whose record-in falls inside the transition's span. Resolve's
    // OWN XMEML importer writes these as elements that render INERT on
    // 19.1.3 (measured E66: dip AND plain cross dissolve both played the
    // outgoing clip through the window, hard cut at the end), so routing
    // the turnover through assemble_from_interchange authors transitions
    // that actually render where the host importer's do not.
    const titems = t.transitionitem ? (Array.isArray(t.transitionitem) ? t.transitionitem : [t.transitionitem]) : [];
    for (const tr of titems) {
      const s = Number(tr.start), e2 = Number(tr.end);
      if (!Number.isFinite(s) || !Number.isFinite(e2)) continue;
      const effectId = (tr.effect && (tr.effect.effectid || tr.effect.name)) || 'Cross Dissolve';
      const isBLev = (ev) => /^(BL|BLACK)$/i.test(String(ev.source || '').trim());
      const inSpan = (ev) => ev.track === label && ev.recIn > s - 1 && ev.recIn <= e2;
      // Prefer the PICTURE as the incoming: a Solid Color generatoritem in
      // the same span is the fade's black side, not the clip fading in.
      const incoming = events.slice(before).find((ev) => inSpan(ev) && !isBLev(ev)) || events.slice(before).find(inSpan);
      // recStart carries the transitionitem's EXPLICIT record span start
      // (sequence-relative) so the bridge reproduces the editor's actual
      // alignment instead of assuming centered.
      if (incoming) {
        incoming.transition = { type: String(effectId), duration: e2 - s, recStart: s };
        // No clip ENDS inside the span → nothing precedes: a fade-IN from
        // black. Synthesize the zero-length BL leg (E91/E92) so the bridge
        // authors a real black-to-picture dissolve instead of dropping it.
        const outgoing = events.slice(before).find((ev) => ev.track === label && ev !== incoming && ev.recOut > s - 1 && ev.recOut <= e2);
        if (!outgoing) {
          events.push(evt({ index: idx++, track: label, source: 'BL', recIn: incoming.recIn, recOut: incoming.recIn, fps: seqRate }));
        }
      } else {
        // No clip STARTS inside the span: a fade-OUT into black past the
        // last clip. Attach the transition to a synthetic BL leg at the
        // outgoing clip's end (the bridge grows it forward).
        const outgoing = events.slice(before).find((ev) => ev.track === label && ev.recOut > s - 1 && ev.recOut <= e2);
        if (outgoing) {
          events.push(evt({
            index: idx++, track: label, source: 'BL',
            recIn: outgoing.recOut, recOut: outgoing.recOut,
            transition: { type: String(effectId), duration: e2 - s, recStart: s }, fps: seqRate,
          }));
        }
      }
    }
  };
  const seq = doc.xmeml && doc.xmeml.sequence;
  const media = seq && seq.media;
  if (media) {
    const vtracks = media.video && media.video.track ? (Array.isArray(media.video.track) ? media.video.track : [media.video.track]) : [];
    vtracks.forEach((t, vi) => {
      const label = vi === 0 ? 'V' : `V${vi + 1}`;
      const before = events.length;
      // Junctions of this track's transitionitems, for -1 edge resolution.
      currentJunctions = trackJunctionsOf(t);
      // Solid Color / Color Matte generatoritems are GENERATOR legs: black by
      // default (what Resolve writes for a fade's black side), or the
      // `fillcolor` the item declares — Resolve's importer honours it and
      // its writer emits it back (E110, render-measured). They walk as BL
      // events carrying `color` so fades AND fade-to-colour round-trip.
      const gens = t.generatoritem ? (Array.isArray(t.generatoritem) ? t.generatoritem : [t.generatoritem]) : [];
      for (const g of gens) {
        const gname = String(g.name || '');
        const eid = String((g.effect && (g.effect.effectid || g.effect.name)) || '');
        if (!(/solid color|black|colou?r matte/i.test(gname) || /^(solid color|color)$/i.test(eid))) continue;
        walk([{ ...g, name: 'BL', filter: undefined, marker: undefined, __genColor: xmemlFillColor(g) }], label, false);
      }
      clipCursor = 0;
      if (t.clipitem) walk(t.clipitem, label);
      currentJunctions = [];
      attachTransitions(t, label, before);
    });
    // Audio tracks number like OTIO/AAF (A, A2, A3 …) so multi-track audio
    // keeps its lanes instead of collapsing onto A1 (E108), and their
    // transitionitems attach the same way video's do.
    const atracks = media.audio && media.audio.track ? (Array.isArray(media.audio.track) ? media.audio.track : [media.audio.track]) : [];
    atracks.forEach((t, ai) => {
      const label = ai === 0 ? 'A' : `A${ai + 1}`;
      const before = events.length;
      clipCursor = 0;
      // Audio lanes carry -1 edges under their cross-fades exactly like video
      // (Resolve's writer, measured E114: the incoming clip's <in> is the
      // source at the overlap start and needs the junction offset) — the
      // junction list must be THIS lane's, not the last video track's.
      currentJunctions = trackJunctionsOf(t);
      if (t.clipitem) walk(t.clipitem, label);
      currentJunctions = [];
      attachTransitions(t, label, before);
    });
  }
  return events;
}

/**
 * Dispatch by format (SYNC, pure over TEXT). Binary/container formats are handled out-of-band by
 * their own path-based readers — AAF via aaf.mjs `parseAAF` (async, pyaaf2), .prproj via prproj.mjs
 * `parsePrproj` (gunzip+XML), .drt/.drp via drt.mjs `parseDRT` (ZIP). This throws to route callers
 * there rather than faking a parse. Every container format gets a NAMED redirect: falling through
 * to `unknown format` would tell a caller the cluster does not support a format it does support
 * (list_sequences parses .drt/.drp), and an empty parse is indistinguishable downstream from an
 * unsupported one.
 */
export function parseInterchange(format, content, opts = {}) {
  switch (String(format).toLowerCase()) {
    case 'edl':
      return parseEDL(content, opts);
    case 'otio':
      return parseOTIO(content, opts);
    case 'xml':
    case 'xmeml':
    case 'fcp7':
      return parseXMEMLEvents(content, opts);
    case 'aaf':
      throw new Error(
        'parse_interchange: AAF is binary — parse it via the async AAF path (aaf.mjs `parseAAF`, backed by pyaaf2), not the sync parseInterchange().',
      );
    case 'prproj':
      throw new Error(
        'parse_interchange: .prproj is gzip-compressed XML — parse it via the path-based reader (prproj.mjs `parsePrproj`), not the sync parseInterchange().',
      );
    case 'drt':
    case 'drp':
      throw new Error(
        `parse_interchange: .${String(format).toLowerCase()} is a ZIP container — parse it via the async path-based reader (editorial.mjs \`parseDrtEvents(path, {timeline})\` over drt-parser \`parseDRT(path)\`, E139), not the sync parseInterchange(). Entry points: editorial \`parse_interchange({format:'drt', content: PATH})\`, \`list_sequences({path})\` or drt \`parse({drtPath})\`.`,
      );
    default:
      throw new Error(`parse_interchange: unknown format '${format}' (edl|otio|xml|xmeml|fcp7|drt|drp|aaf|prproj)`);
  }
}

// ── DRT → normalized events (E139) ─────────────────────────────────────
/**
 * Normalized events for ONE timeline of a parsed .drt/.drp (drt-parser
 * `parseDRT`), so two Resolve timeline versions diff through
 * turnover_changelist and a DRT re-export verifies like any other format.
 * Measured on a real 19.1.3.7 EXPORT_DRT: a clip's record window is
 * <Start>/<Duration>, its source in-point <In> (EMPTY on audio clips and on
 * generator tails — reported srcInAbsent, never faked to 0 silently), its
 * media <MediaFilePath>; <MediaTimemapBA> tag 0x02 = linear 100%, a keyed
 * Sm2TimeMap decodes to the speed (E140: constant 80% on a real reel's four
 * retimes = Premiere's 80; XMax 60000 + zero slope = freeze; negative = reverse;
 * an unreadable map stays speed null + retimeUnknown) and, on a retime, <In> is
 * RECORD-domain — the event's srcIn is In × speed (E143), with the raw value
 * kept as recordDomainIn;
 * Sm2TiTransition alignment 2 centres on the cut, 3 ends at it. Record
 * positions are sequence-relative (start frame subtracted), like every other
 * parser here; `startFrame` is returned beside the events.
 * @param {object} parsed  parseDRT output
 * @param {{timeline?: string|number}} [opts] pool name or index; default = first `timeline` kind
 */
export function drtEventsFromParsed(parsed, opts = {}) {
  const tls = (parsed && parsed.timelines) || [];
  if (!tls.length) throw new Error('drt events: the archive holds no SeqContainer');
  let tl = null;
  if (typeof opts.timeline === 'number') tl = tls[opts.timeline] || null;
  else if (typeof opts.timeline === 'string' && opts.timeline) tl = tls.find((t) => t.name === opts.timeline) || null;
  else tl = tls.find((t) => t.kind === 'timeline') || tls[0];
  if (!tl) throw new Error(`drt events: no timeline '${opts.timeline}' in [${tls.map((t) => t.name).join(', ')}]`);
  const fps = Number(tl.frameRate) || 24;
  const startFrame = Number.isFinite(Number(tl.startFrame)) ? Number(tl.startFrame) : 0;
  const events = [];
  let index = 1;
  const base = (pth, name) => (pth ? String(pth).split(/[\\/]/).pop() : name);
  const walk = (tracks, prefix) => {
    (tracks || []).forEach((t, i) => {
      const label = i === 0 ? prefix : `${prefix}${i + 1}`;
      const before = events.length;
      const clips = [...(t.clips || [])].filter((c) => Number.isFinite(c.start) && Number.isFinite(c.duration)).sort((a, b) => a.start - b.start);
      for (const c of clips) {
        const srcIn = c.in != null ? c.in : 0;
        const media = c.mediaFilePath || null;
        const isGen = !media && !c.compound;
        // E140: the decoded Sm2TimeMap gives the speed. A ratio becomes the
        // percent every other parser speaks (0.8 → 80); the source OUT follows
        // the record window at that speed (37 record frames × 0.8 = 30 source
        // frames — the same srcOut Premiere wrote for the same cut); a freeze
        // is the zero-speed in==out event the other parsers emit; a map the
        // decoder could not read stays speed/srcOut null + retimeUnknown.
        const tm = c.timemap && typeof c.timemap === 'object' ? c.timemap : null;
        const kind = tm ? tm.kind : (c.timemap === 'curve' ? 'unknown' : 'linear');
        // E143: on a keyed retime Resolve's <In> is RECORD-domain — the map
        // spans the whole source stretched by 1/speed and the clip windows
        // into that (measured live on 19.1.3.7; the bridge writes In =
        // srcIn/speed for exactly this reason). The source frame the clip
        // starts on is In × speed. Reading In as a source frame was wrong by
        // (1/speed − 1) × In: 10,537 frames on a real 80% clip at In 52682.
        // Reverse: the map descends from the source tail, In measures from
        // the END — source start = sourceFrames − In×speed − duration×speed.
        let speed = 100, srcOut = srcIn + c.duration, unknown = false, srcStart = srcIn;
        if (kind === 'freeze') { speed = 0; srcOut = srcIn; }
        else if (kind === 'constant' || kind === 'variable') {
          speed = Math.round(tm.speed * 10000) / 100;
          const span = Math.round(c.duration * tm.speed);
          if (tm.reverse && tm.sourceDurationSec != null) {
            const sourceFrames = Math.round(tm.sourceDurationSec * fps) + 1;
            srcStart = Math.max(0, sourceFrames - Math.round(srcIn * tm.speed) - span);
          } else srcStart = Math.round(srcIn * tm.speed);
          srcOut = srcStart + span;
        }
        else if (kind === 'unknown') { speed = null; srcOut = null; unknown = true; }
        const ev = {
          index: index++, track: label, source: media ? base(media, c.name) : (c.name || 'BL'),
          srcIn: srcStart, srcOut, recIn: c.start - startFrame, recOut: c.start - startFrame + c.duration,
          speed, reverse: Boolean(tm && tm.reverse), transition: null, fps,
        };
        if (media) ev.sourcePath = media;
        if (srcStart !== srcIn) ev.recordDomainIn = srcIn;
        if (c.in == null) ev.srcInAbsent = true;
        if (unknown) ev.retimeUnknown = true;
        if (kind === 'variable') { ev.variableSpeed = true; ev.retimeSegments = tm.segments; }
        if (c.compound) ev.compound = c.compound;
        if (isGen) ev.generatorName = c.name || null;
        events.push(ev);
      }
      for (const tr of t.transitions || []) {
        if (!Number.isFinite(tr.start) || !Number.isFinite(tr.duration)) continue;
        const s0 = tr.start - startFrame, e0 = s0 + tr.duration;
        const lane = events.slice(before).filter((ev) => ev.track === label);
        const incoming = lane.find((ev) => ev.recIn > s0 - 1 && ev.recIn <= e0);
        const outgoing = lane.find((ev) => ev !== incoming && ev.recOut > s0 - 1 && ev.recOut <= e0);
        const transition = { type: String(tr.type || 'Cross Dissolve'), duration: tr.duration, recStart: s0 };
        if (tr.alignment) transition.alignment = tr.alignment;
        if (incoming) {
          incoming.transition = transition;
          if (!outgoing) events.push({ index: index++, track: label, source: 'BL', srcIn: 0, srcOut: 0, recIn: incoming.recIn, recOut: incoming.recIn, speed: 100, reverse: false, transition: null, fps });
        } else if (outgoing) {
          events.push({ index: index++, track: label, source: 'BL', srcIn: 0, srcOut: 0, recIn: outgoing.recOut, recOut: outgoing.recOut, speed: 100, reverse: false, transition, fps });
        }
      }
    });
  };
  walk(tl.videoTracks, 'V');
  walk(tl.audioTracks, 'A');
  return { events, timeline: tl.name, kind: tl.kind || null, fps, startFrame, startTimecode: tl.startTimecode || null };
}

/** Path-based DRT/DRP → events (async: ZIP). */
export async function parseDrtEvents(filePath, opts = {}) {
  const { parseDRT } = require('../vendor/drt-format/drt-parser.js');
  return drtEventsFromParsed(await parseDRT(filePath), opts);
}

// ── turnover_changelist ────────────────────────────────────────────────
const sig = (e) => `${e.track}:${e.source}`;
const isBlackSource = (s) => /^(bl|black|solid color)$/i.test(String(s || '').trim());
const isAudioTrack = (t) => /^A\d*$/i.test(String(t || ''));
// A zero-length event is a CARRIER, never a cut: the outgoing marker line of
// a CMX dissolve pair, or the zero-length BL slug every parser synthesizes at
// a fade (E91/E92/E93). It has no picture of its own to be moved/gone/new.
const isCarrier = (e) => e.recIn != null && e.recOut != null && e.recIn === e.recOut;

/**
 * The record SPAN a transition event occupies, derived exactly the way the
 * bridge places it (author-interchange): alignment 'start' → the span begins
 * at the incoming's recIn (CMX start-at-cut / AAF overlap start); OTIO
 * inOffset → that many frames before the cut; XMEML/PrProj recStart → the
 * explicit span start; nothing declared → centered. `junction` is the
 * incoming event's recIn — the same frame verify_roundtrip's fade windows
 * key on.
 * @param {Object} e normalized event carrying `transition`
 */
export function transitionSpan(e) {
  const t = e.transition;
  if (!t || e.recIn == null) return null;
  const d = Math.max(0, Number(t.duration) || 0);
  let pre;
  if (t.alignment === 'start') pre = 0;
  else if (t.inOffset != null) pre = Math.max(0, Math.min(d, Number(t.inOffset) || 0));
  else if (t.recStart != null) pre = Math.max(0, Math.min(d, e.recIn - Number(t.recStart)));
  else pre = Math.floor(d / 2);
  const start = e.recIn - pre;
  return { start, end: start + d, junction: e.recIn, pre, duration: d };
}

/**
 * Every junction in an event list as a transition record: span, type, the
 * OUTGOING event (the same-track neighbour whose extent touches the span
 * start — a CMX carrier line, an abutting clip, or the overlapping AAF
 * predecessor) and the INCOMING (the carrier of the `transition` field), with
 * black on either side classified as a fade. Pure over events.
 * @param {Array} events
 * @returns {Array<{track,type,duration,start,end,junction,pre,outgoing,incoming,fade,incomingEvent,outgoingEvent}>}
 */
export function listTransitions(events) {
  const out = [];
  for (const e of events) {
    if (!e.transition || !(Number(e.transition.duration) > 0)) continue;
    const span = transitionSpan(e);
    if (!span) continue;
    const cands = events.filter((o) => o !== e && o.track === e.track && o.recIn != null && o.recOut != null
      && o.recIn <= span.start && o.recOut >= span.start);
    // The latest-ending toucher is the outgoing: a carrier line sits exactly
    // at the span start, an abutting clip ends there, an AAF predecessor
    // overlaps past it. Prefer a picture over black only when both touch.
    cands.sort((a, b) => (b.recOut - a.recOut) || ((events.indexOf(b)) - events.indexOf(a)));
    let outgoingEvent = cands[0] || null;
    if (!outgoingEvent) {
      // Nothing touches the span start (a pre-rolled fade-in at track start
      // whose span begins before frame 0, or a gap-adjacent junction): the
      // outgoing is whatever last ENDED at or before the junction — the
      // zero-length BL slug the parsers synthesize sits exactly there.
      const before = events.filter((o) => o !== e && o.track === e.track && o.recOut != null && o.recOut <= span.junction);
      before.sort((a, b) => (b.recOut - a.recOut) || (events.indexOf(b) - events.indexOf(a)));
      outgoingEvent = before[0] || null;
    }
    const outgoing = outgoingEvent ? outgoingEvent.source : null;
    const incoming = e.source;
    const fade = isBlackSource(outgoing) ? 'in' : isBlackSource(incoming) ? 'out' : null;
    out.push({
      track: e.track, type: e.transition.type || 'dissolve', duration: span.duration,
      start: span.start, end: span.end, junction: span.junction, pre: span.pre,
      outgoing, incoming, fade, incomingEvent: e, outgoingEvent,
    });
  }
  return out;
}

/**
 * Pair old and new PICTURE/AUDIO events once each: same track+source, closest
 * record position wins, consumed on match (a source used twice at two speeds
 * pairs each instance with its own — never first-row-wins). Carriers and the
 * black legs a transition references never enter the pairing: they are the
 * junction's business (listTransitions), not sources.
 */
function pairEvents(oldEvents, newEvents, recTol = 1) {
  const cutsOf = (events) => {
    const trs = listTransitions(events);
    const fadeBlack = new Set();
    for (const t of trs) {
      if (t.outgoingEvent && isBlackSource(t.outgoingEvent.source)) fadeBlack.add(t.outgoingEvent);
      if (isBlackSource(t.incomingEvent.source)) fadeBlack.add(t.incomingEvent);
    }
    const cuts = [], carriers = [];
    for (const e of events) {
      if (e.track === 'MARKER') continue;
      if (isCarrier(e) || fadeBlack.has(e)) carriers.push(e);
      else cuts.push(e);
    }
    return { cuts, carriers, transitions: trs };
  };
  const o = cutsOf(oldEvents), n = cutsOf(newEvents);
  // Pairing is closest-first GLOBALLY (E138), not first-come in new order:
  // walking new cuts in order let the first new instance of a source consume
  // an old instance 6,000 frames away while the old instance at its own
  // position went unpaired — a subset reel read back as moved + new. Every
  // same-signature (old, new) pair sorts by record distance and is taken
  // once; the result is symmetric under swapping old and new.
  const pool = o.cuts.map((e) => ({ e, used: false, sig: sig(e) }));
  const newSigs = n.cuts.map(sig);
  const cands = [];
  for (let ni = 0; ni < n.cuts.length; ni++) {
    for (let oi = 0; oi < pool.length; oi++) {
      if (pool[oi].sig !== newSigs[ni]) continue;
      cands.push({ oi, ni, d: Math.abs((pool[oi].e.recIn ?? 0) - (n.cuts[ni].recIn ?? 0)) });
    }
  }
  cands.sort((a, b) => a.d - b.d || a.ni - b.ni || a.oi - b.oi);
  const usedNew = new Set();
  const taken = [];
  for (const c of cands) {
    if (pool[c.oi].used || usedNew.has(c.ni)) continue;
    pool[c.oi].used = true; usedNew.add(c.ni);
    taken.push(c);
  }
  taken.sort((a, b) => a.ni - b.ni);
  const pairs = taken.map((c) => ({ oe: pool[c.oi].e, ne: n.cuts[c.ni] }));
  const unmatchedNew = n.cuts.filter((_, i) => !usedNew.has(i));
  const unmatchedOld = pool.filter((p) => !p.used).map((p) => p.e);
  return { pairs, unmatchedOld, unmatchedNew, old: o, new: n, recTol };
}

/**
 * Diff two normalized event lists → a SHAPE verdict (identical|subset|superset|edit, E138)
 * plus per-event {kind: moved|retimed|trimmed|replaced|new|gone}; RELINK-aware (E141):
 * opts.sourceAliases ({from,to} | {pattern,replace}) rename old sources first, a
 * systematic rename is inferred from same-window unpaired cuts (opts.inferAliases
 * !== false) and reported in sourceAliases, and a constant per-source source-window
 * shift witnessed on ≥2 cuts is a TC rebase (sourceTcOffsets), not trims. A cut moved
 * INSIDE an unchanged dissolve span with both source windows sliding by the same delta
 * is one junction_realigned (E142) — a consequence — and two labels of one transition
 * family are a relabel (transitionRelabels), so a picture-identical conform reads
 * shape 'equivalent'.
 * PLUS per-junction {kind: transition_added|transition_dropped|transition_changed}
 * (fade 'in'/'out' or null for a dissolve). Zero-length carrier lines and the
 * black legs that carry fades fold into the junction diff instead of reading
 * as gone/new sources; a dissolve whose duration, type or span shape changed
 * is a change even when both clips stayed put.
 * @param {Array} oldEvents
 * @param {Array} newEvents
 * @param {{recTolerance?:number}} [opts]
 */
// ── RELINK awareness (E141) ────────────────────────────────────────────
// A real offline→online turnover (Premiere REEL_02 → the Resolve conform of
// the same reel) paired 15 of 228 cuts: the offline media was named
// "… 4K-2K … .mov" (proxies) where the online cut used "… 4K … .mov"
// (masters) and ".mp4" became ".mov", so 203 identical cuts read as
// `replaced`; and the masters carry a different timecode base, so the same
// cuts read as `trimmed` by a constant per-source shift. Neither is an edit.
const normalizeAliases = (list) => (Array.isArray(list) ? list : []).map((a) => {
  if (!a || typeof a !== 'object') throw new Error('sourceAliases: each entry is {from,to} or {pattern,replace}');
  if (a.pattern != null) return { pattern: String(a.pattern), replace: String(a.replace ?? ''), re: new RegExp(a.pattern, a.flags || 'g'), inferred: false };
  if (a.from != null && a.to != null) return { from: String(a.from), to: String(a.to), inferred: false };
  throw new Error('sourceAliases: each entry is {from,to} or {pattern,replace}');
});
const aliasSource = (src, aliases) => {
  let s = String(src ?? '');
  for (const a of aliases) {
    if (a.re) s = s.replace(a.re, a.replace);
    else if (s === a.from) s = a.to;
  }
  return s;
};
const applyAliases = (events, aliases) => (aliases.length
  ? events.map((e) => { const s = aliasSource(e.source, aliases); return s === String(e.source ?? '') ? e : { ...e, source: s, aliasedFrom: e.source }; })
  : events);
// Longest-common-subsequence ratio, case-insensitive: 1 = identical names.
function nameSimilarity(a, b) {
  const x = String(a || '').toLowerCase(), y = String(b || '').toLowerCase();
  if (!x.length || !y.length) return 0;
  let prev = new Array(y.length + 1).fill(0);
  for (let i = 1; i <= x.length; i++) {
    const cur = new Array(y.length + 1).fill(0);
    for (let j = 1; j <= y.length; j++) cur[j] = x[i - 1] === y[j - 1] ? prev[j - 1] + 1 : Math.max(prev[j], cur[j - 1]);
    prev = cur;
  }
  return (2 * prev[y.length]) / (x.length + y.length);
}
/**
 * Infer a systematic RENAME from the cuts a first pass could not pair: an
 * unpaired old cut and an unpaired new cut on the same track with the same
 * record window are the same cut under two names. An alias is adopted when
 * the mapping is one-to-one both ways and either recurs (≥2 cuts) or the two
 * names are clearly the same name (LCS similarity ≥ 0.6) — a genuinely
 * different shot dropped into the same window is neither.
 */
function inferSourceAliases(P, recTol) {
  const cands = new Map(); // from -> Map(to -> count)
  const usedNew = new Set();
  for (const oe of P.unmatchedOld) {
    const hit = P.unmatchedNew.find((ne) => !usedNew.has(ne) && ne.track === oe.track
      && Math.abs((ne.recIn ?? 0) - (oe.recIn ?? 0)) <= recTol && Math.abs((ne.recOut ?? 0) - (oe.recOut ?? 0)) <= recTol);
    if (!hit) continue;
    usedNew.add(hit);
    const from = String(oe.source ?? ''), to = String(hit.source ?? '');
    if (from === to) continue;
    if (!cands.has(from)) cands.set(from, new Map());
    cands.get(from).set(to, (cands.get(from).get(to) || 0) + 1);
  }
  const claimed = new Map(); // to -> from
  const out = [];
  for (const [from, tos] of cands) {
    if (tos.size !== 1) continue;
    const [to, count] = [...tos][0];
    if (claimed.has(to) && claimed.get(to) !== from) continue;
    const similarity = Math.round(nameSimilarity(from, to) * 1000) / 1000;
    if (count >= 2 || similarity >= 0.6) { claimed.set(to, from); out.push({ from, to, cuts: count, similarity, inferred: true }); }
  }
  // A 'to' claimed by two different 'from's is ambiguous — drop both.
  const toCounts = new Map(); for (const a of out) toCounts.set(a.to, (toCounts.get(a.to) || 0) + 1);
  return out.filter((a) => toCounts.get(a.to) === 1);
}

export function diffChangelist(oldEvents, newEvents, opts = {}) {
  const explicit = normalizeAliases(opts.sourceAliases);
  let aliases = explicit;
  let result = diffChangelistOnce(applyAliases(oldEvents, aliases), newEvents, opts);
  if (opts.inferAliases !== false) {
    const inferred = inferSourceAliases(result.__P, opts.recTolerance ?? 1);
    if (inferred.length) {
      aliases = [...explicit, ...inferred];
      result = diffChangelistOnce(applyAliases(oldEvents, aliases), newEvents, opts);
    }
  }
  const { __P, ...out } = result;
  out.sourceAliases = aliases.map((a) => (a.re ? { pattern: a.pattern, replace: a.replace, inferred: false } : { from: a.from, to: a.to, inferred: Boolean(a.inferred), ...(a.cuts != null ? { cuts: a.cuts, similarity: a.similarity } : {}) }));
  return out;
}

function diffChangelistOnce(oldEvents, newEvents, opts = {}) {
  const recTol = opts.recTolerance ?? 1;
  const changes = [];
  // COMPOUND FORMS (E124): a compound is one collapsed item in an XML cut
  // (`compound`) and its flattened inner cuts in an OTIO cut (`fromCompound`).
  // The same compound in both forms is not a replacement plus a gone cut —
  // it is reported once as compound_collapsed / compound_expanded and its
  // cuts leave the pairing.
  const skipOld = new Set(), skipNew = new Set();
  const sameName = (a, b) => String(a || '').toLowerCase() === String(b || '').toLowerCase();
  for (const ne of newEvents) {
    if (!ne.compound) continue;
    const inner = oldEvents.filter((oe) => oe.fromCompound && sameName(oe.fromCompound, ne.compound) && oe.track === ne.track && oe.recIn < ne.recOut && oe.recOut > ne.recIn);
    if (!inner.length) continue;
    inner.forEach((oe) => skipOld.add(oe)); skipNew.add(ne);
    changes.push({ kind: 'compound_collapsed', name: ne.compound, track: ne.track, oldRecIn: Math.min(...inner.map((o) => o.recIn)), newRecIn: ne.recIn, innerCuts: inner.length });
  }
  for (const oe of oldEvents) {
    if (!oe.compound || skipOld.has(oe)) continue;
    const inner = newEvents.filter((ne) => ne.fromCompound && sameName(ne.fromCompound, oe.compound) && ne.track === oe.track && ne.recIn < oe.recOut && ne.recOut > oe.recIn);
    if (!inner.length) continue;
    inner.forEach((ne) => skipNew.add(ne)); skipOld.add(oe);
    changes.push({ kind: 'compound_expanded', name: oe.compound, track: oe.track, oldRecIn: oe.recIn, newRecIn: Math.min(...inner.map((n) => n.recIn)), innerCuts: inner.length });
  }
  const P = pairEvents(oldEvents.filter((e) => !skipOld.has(e)), newEvents.filter((e) => !skipNew.has(e)), recTol);

  // TC REBASE (E141): when every differing cut of a source shifts its source
  // window by the SAME amount in and out, the media was relinked to a copy
  // with a different timecode base (offline proxies at 0, masters at their
  // camera TC) — not N trims. A shift witnessed on ≥2 cuts of a source is
  // that source's offset; the compare below reads old through it, and a cut
  // that still differs is a real trim on top of the rebase.
  const shiftTally = new Map(), differing = new Map();
  for (const { oe, ne } of P.pairs) {
    if ([oe.srcIn, oe.srcOut, ne.srcIn, ne.srcOut].some((v) => v == null)) continue;
    const dIn = ne.srcIn - oe.srcIn, dOut = ne.srcOut - oe.srcOut;
    if (dIn === 0 && dOut === 0) continue;
    const key = String(ne.source ?? '');
    differing.set(key, (differing.get(key) || 0) + 1);
    if (dIn === 0 || dIn !== dOut) continue;
    if (!shiftTally.has(key)) shiftTally.set(key, new Map());
    shiftTally.get(key).set(dIn, (shiftTally.get(key).get(dIn) || 0) + 1);
  }
  // A rebase is the source's DOMINANT story: the same shift on ≥2 cuts AND
  // on more than half of the cuts whose windows differ at all. A source whose
  // cuts each shift by a different amount (an eye-matched re-conform onto
  // other media — measured: two of seven cuts happened to share a shift) is
  // trims, not a base change.
  const tcOffsets = new Map();
  for (const [source, tally] of shiftTally) {
    const [offset, cuts] = [...tally].sort((a, b) => b[1] - a[1])[0];
    if (cuts >= 2 && cuts > (differing.get(source) || 0) / 2) tcOffsets.set(source, { source, offset, cuts, rebased: 0 });
  }

  const retained = [];
  for (const { oe, ne } of P.pairs) {
    const deltas = {};
    let kind = 'unchanged';
    const tc = tcOffsets.get(String(ne.source ?? ''));
    const off = tc ? tc.offset : 0;
    const oIn = oe.srcIn == null ? null : oe.srcIn + off, oOut = oe.srcOut == null ? null : oe.srcOut + off;
    if (Math.abs((oe.speed ?? 100) - (ne.speed ?? 100)) > 0.01 || Boolean(oe.reverse) !== Boolean(ne.reverse)) {
      kind = 'retimed';
      deltas.speed = { old: oe.speed, new: ne.speed };
      if (Boolean(oe.reverse) !== Boolean(ne.reverse)) deltas.reverse = { old: oe.reverse, new: ne.reverse };
    } else if (Math.abs((oe.recIn ?? 0) - (ne.recIn ?? 0)) > recTol) {
      kind = 'moved';
      deltas.recIn = { old: oe.recIn, new: ne.recIn };
    } else if ((oIn ?? null) !== (ne.srcIn ?? null) || (oOut ?? null) !== (ne.srcOut ?? null)) {
      kind = 'trimmed';
      deltas.src = { old: [oIn, oOut], new: [ne.srcIn, ne.srcOut], ...(off ? { tcOffset: off, oldBeforeRebase: [oe.srcIn, oe.srcOut] } : {}) };
    } else if (off && ((oe.srcIn ?? null) !== (ne.srcIn ?? null))) {
      tc.rebased += 1;
    }
    if (kind !== 'unchanged') changes.push({ kind, source: ne.source, track: ne.track, oldRecIn: oe.recIn, newRecIn: ne.recIn, deltas });
    else retained.push(ne);
  }
  for (const ne of P.unmatchedNew) changes.push({ kind: 'new', source: ne.source, track: ne.track, newRecIn: ne.recIn, newRecOut: ne.recOut });
  // Unconsumed old events → gone (unless a 'new' at the same rec position → replaced).
  for (const oe of P.unmatchedOld) {
    const replacement = changes.find((c) => c.kind === 'new' && c.track === oe.track && Math.abs((c.newRecIn ?? 0) - (oe.recIn ?? 0)) <= recTol);
    if (replacement) {
      replacement.kind = 'replaced';
      replacement.oldSource = oe.source;
      replacement.oldRecIn = oe.recIn;
    } else {
      changes.push({ kind: 'gone', source: oe.source, track: oe.track, oldRecIn: oe.recIn, oldRecOut: oe.recOut });
    }
  }

  // JUNCTION REALIGN (E142): a cut that moved INSIDE an unchanged dissolve
  // span, with the incoming's source in and the outgoing's source out
  // sliding by the same amount, shows the identical picture — the dissolve
  // covers the same record frames from the same media either way. Premiere
  // keeps a fractional alignment (its cut sat 12 frames into a 46-frame
  // span); Resolve's conform re-centred it (23). Measured on a real reel: 9
  // of 10 residual 'moved' cuts were this, the tenth a real edit (its span
  // moved too). Fold each into one junction_realigned — a consequence, not
  // an edit — and let the junction diff read the pre-roll change as the
  // same fact.
  const realigned = new Set();
  const pairAtIn = (recIn, track) => P.pairs.find((pr) => pr.oe.track === track && pr.oe.recIn === recIn);
  const pairAtOut = (recOut, track) => P.pairs.find((pr) => pr.oe.track === track && pr.oe.recOut === recOut);
  for (const ot of P.old.transitions) {
    const nt = P.new.transitions.find((t) => t.track === ot.track && Math.abs(t.start - ot.start) <= recTol && Math.abs(t.end - ot.end) <= recTol);
    if (!nt) continue;
    const delta = nt.junction - ot.junction;
    if (!delta) continue;
    const inc = pairAtIn(ot.junction, ot.track), out = pairAtOut(ot.junction, ot.track);
    if (!inc || inc.ne.recIn !== nt.junction) continue;
    // The source slides by the cut delta at the clip's speed (a retimed
    // incoming at 80% slides 6 source frames for an 8-frame cut move —
    // measured on the reel's V3 fade-in); a TC-rebased outgoing is read
    // through its offset.
    const slide = (ev) => Math.round(delta * ((ev.speed ?? 100) / 100));
    const near = (a, b) => a != null && b != null && Math.abs(a - b) <= 1;
    const offOf = (ev) => (tcOffsets.get(String(ev.source ?? '')) ? tcOffsets.get(String(ev.source ?? '')).offset : 0);
    const incOk = near(inc.ne.srcIn - (inc.oe.srcIn + offOf(inc.ne)), slide(inc.ne)) && near(inc.ne.srcOut, inc.oe.srcOut + offOf(inc.ne));
    const outOk = !out || (out.ne.recOut === nt.junction
      && near(out.ne.srcOut - (out.oe.srcOut + offOf(out.ne)), slide(out.ne))
      && near(out.ne.srcIn, out.oe.srcIn == null ? null : out.oe.srcIn + offOf(out.ne)));
    if (!incOk || !outOk) continue;
    const isMoveOfInc = (c) => c.kind === 'moved' && c.track === ot.track && c.oldRecIn === inc.oe.recIn && c.newRecIn === inc.ne.recIn;
    const isTrimOfOut = (c) => out && c.kind === 'trimmed' && c.track === ot.track && c.oldRecIn === out.oe.recIn && c.newRecIn === out.ne.recIn;
    const before = changes.length;
    for (let i = changes.length - 1; i >= 0; i--) if (isMoveOfInc(changes[i]) || isTrimOfOut(changes[i])) changes.splice(i, 1);
    if (changes.length === before && !P.pairs.includes(inc)) continue;
    realigned.add(`${nt.track}|${nt.junction}`);
    // Both sides show the same picture: they are retained cuts, not edits.
    for (const pr of [inc, out]) if (pr && !retained.includes(pr.ne)) retained.push(pr.ne);
    changes.push({
      kind: 'junction_realigned', track: ot.track, oldRecIn: ot.junction, newRecIn: nt.junction, delta,
      span: [nt.start, nt.end], outgoing: nt.outgoing, incoming: nt.incoming, type: nt.type, duration: nt.duration,
    });
  }

  // Junction diff: a transition is identified by what it joins (track,
  // outgoing, incoming, fade side) and pairs with the closest junction; only
  // its SHAPE (duration / type / pre-roll) makes a change — a junction that
  // travelled with its clips is the clips' move, already reported. Two
  // labels for one effect family ("Cross Dissolve (Legacy)" in Premiere,
  // "Cross Dissolve" in Resolve — E142) are a relabel, not a change.
  const typeFamily = (t) => String(t ?? '').toLowerCase().replace(/\(legacy\)/g, '').replace(/^(video|audio)\s+/, '').replace(/\s+/g, ' ').trim();
  const relabels = [];
  const tKey = (t) => `${t.track}|${t.outgoing ?? ''}|${t.incoming}|${t.fade ?? 'x'}`;
  const tPool = P.old.transitions.map((t) => ({ t, used: false }));
  const tDesc = (t) => ({ track: t.track, outgoing: t.outgoing, incoming: t.incoming, fade: t.fade, type: t.type, duration: t.duration });
  for (const nt of P.new.transitions) {
    const cands = tPool.filter((p) => !p.used && tKey(p.t) === tKey(nt));
    if (!cands.length) {
      changes.push({ kind: 'transition_added', ...tDesc(nt), newRecIn: nt.junction, newSpan: [nt.start, nt.end] });
      continue;
    }
    cands.sort((a, b) => Math.abs(a.t.junction - nt.junction) - Math.abs(b.t.junction - nt.junction));
    cands[0].used = true;
    const ot = cands[0].t;
    const deltas = {};
    if (ot.duration !== nt.duration) deltas.duration = { old: ot.duration, new: nt.duration };
    if (String(ot.type) !== String(nt.type)) {
      if (typeFamily(ot.type) === typeFamily(nt.type)) relabels.push({ track: nt.track, junction: nt.junction, old: ot.type, new: nt.type });
      else deltas.type = { old: ot.type, new: nt.type };
    }
    if (ot.pre !== nt.pre && !realigned.has(`${nt.track}|${nt.junction}`)) deltas.pre = { old: ot.pre, new: nt.pre };
    if (Object.keys(deltas).length) {
      changes.push({
        kind: 'transition_changed', ...tDesc(nt), oldRecIn: ot.junction, newRecIn: nt.junction,
        oldSpan: [ot.start, ot.end], newSpan: [nt.start, nt.end], deltas,
      });
    }
  }
  for (const p of tPool.filter((x) => !x.used)) {
    changes.push({ kind: 'transition_dropped', ...tDesc(p.t), oldRecIn: p.t.junction, oldSpan: [p.t.start, p.t.end] });
  }

  const counts = {};
  for (const c of changes) counts[c.kind] = (counts[c.kind] || 0) + 1;
  changes.sort((a, b) => (a.newRecIn ?? a.oldRecIn ?? 0) - (b.newRecIn ?? b.oldRecIn ?? 0));

  // SHAPE (E138): a real Premiere auto-save of a locked reel kept 3 of its
  // 335 cuts — byte-identical at their record positions — and deleted the
  // rest (a patch/selects reel). Per-event kinds read that as 332 'gone';
  // it is a sparse SUBSET of the same cut with nothing edited. The verdict
  // names the relationship so a reader never mistakes a subset for a
  // re-cut: identical | subset (new ⊂ old) | superset (old ⊂ new) | edit.
  // A transition that vanished because both cuts it joined vanished (or
  // appeared with the cuts it joins) is a consequence, not an edit.
  const touches = (kind, junction, track) => changes.some((c) => c.kind === kind && c.track === track
    && ((kind === 'gone' ? [c.oldRecIn, c.oldRecOut] : [c.newRecIn, c.newRecOut]).some((v) => Math.abs((v ?? -1e9) - junction) <= recTol)));
  const consequential = (c) => c.kind === 'junction_realigned'
    || (c.kind === 'transition_dropped' && touches('gone', c.oldRecIn, c.track))
    || (c.kind === 'transition_added' && touches('new', c.newRecIn, c.track));
  const edits = changes.filter((c) => c.kind !== 'gone' && c.kind !== 'new' && !consequential(c)).length;
  const gone = counts.gone || 0, added = counts.new || 0;
  const oldCuts = P.old.cuts.length + skipOld.size, newCuts = P.new.cuts.length + skipNew.size;
  let shape = 'edit';
  if (!changes.length) shape = 'identical';
  else if (!edits && !gone && !added) shape = 'equivalent';
  else if (!edits && gone && !added && retained.length) shape = 'subset';
  else if (!edits && added && !gone && retained.length) shape = 'superset';
  const shapeInfo = { shape, retained: retained.length, oldCuts, newCuts };
  if (shape === 'equivalent') shapeInfo.note = `same picture: ${counts.junction_realigned || 0} junction(s) re-aligned inside unchanged dissolves${relabels.length ? `, ${relabels.length} transition label(s) differ` : ''} — nothing edited`;
  if (shape === 'subset' || shape === 'superset') {
    const of = shape === 'subset' ? oldCuts : newCuts;
    shapeInfo.sparse = retained.length / Math.max(1, of) < 0.5;
    shapeInfo.retainedWindows = retained.slice(0, 200).map((e) => ({ track: e.track, source: e.source, recIn: e.recIn, recOut: e.recOut }));
    shapeInfo.note = shape === 'subset'
      ? `new keeps ${retained.length} of ${oldCuts} cuts unchanged in place and nothing else — a patch/selects reel of the same cut, not ${gone} deletions`
      : `old is ${retained.length} of the new cut's ${newCuts} cuts, unchanged in place — the rest is the new cut's additions, not ${added} edits to old`;
  }
  return {
    changes, counts, changedCount: changes.length,
    transitions: { old: P.old.transitions.length, new: P.new.transitions.length },
    carriersFolded: { old: P.old.carriers.length, new: P.new.carriers.length },
    ...shapeInfo,
    sourceTcOffsets: [...tcOffsets.values()].map((t) => ({ source: t.source, offset: t.offset, cuts: t.cuts, rebased: t.rebased })),
    transitionRelabels: relabels.slice(0, 200),
    gate: 'review',
    __P: P,
  };
}

// ── TIMING silent-lie guards ───────────────────────────────────────────
/**
 * Detect timing lies between an old (locked-cut) and new (conformed) event list.
 * Pairs events the same way the changelist does (closest record position,
 * consumed once) so a source cut twice at two speeds is compared instance to
 * instance — never the second old against the first new.
 * @returns {{flags:Array<{kind, source, detail}>}}
 */
export function timingGuards(oldEvents, newEvents) {
  const flags = [];
  const P = pairEvents(oldEvents, newEvents);
  for (const oe of P.unmatchedOld) {
    // A dropped audio event where its video sibling survives → dropped J/L-cut audio.
    if (isAudioTrack(oe.track) && P.new.cuts.some((x) => !isAudioTrack(x.track) && x.track !== 'MARKER' && x.source === oe.source))
      flags.push({ kind: 'dropped_split_audio', source: oe.source, track: oe.track, detail: `audio event (${oe.track}) gone but video sibling present (J/L-cut lost)` });
  }
  for (const { oe, ne } of P.pairs) {
    // Flattened retime: a speed ramp/change flattened to 100%.
    if ((oe.speed ?? 100) !== 100 && (ne.speed ?? 100) === 100)
      flags.push({ kind: 'flattened_retime', source: oe.source, recIn: oe.recIn, detail: `speed ${oe.speed}% → 100% (retime lost)` });
    // Reverse dropped.
    if (oe.reverse && !ne.reverse) flags.push({ kind: 'reverse_dropped', source: oe.source, recIn: oe.recIn, detail: 'reversed clip conformed forward' });
    // Framerate/pulldown slip.
    if (oe.fps && ne.fps && oe.fps !== ne.fps) flags.push({ kind: 'framerate_slip', source: oe.source, recIn: oe.recIn, detail: `fps ${oe.fps} → ${ne.fps}` });
  }
  // A fade or dissolve the conform lost is a timing lie too: the picture
  // edges stay put while the blend at the junction silently hard-cuts.
  const tKey = (t) => `${t.track}|${t.outgoing ?? ''}|${t.incoming}|${t.fade ?? 'x'}`;
  const newKeys = P.new.transitions.map(tKey);
  for (const ot of P.old.transitions) {
    const i = newKeys.indexOf(tKey(ot));
    if (i >= 0) { newKeys.splice(i, 1); continue; }
    flags.push({
      kind: 'transition_dropped', source: ot.incoming, track: ot.track, recIn: ot.junction,
      detail: ot.fade ? `fade-${ot.fade} (${ot.duration}f) at ${ot.junction} lost` : `${ot.outgoing}→${ot.incoming} dissolve (${ot.duration}f) at ${ot.junction} lost`,
    });
  }
  return { flags, flagged: flags.length > 0 };
}

// ── conform_manifest ───────────────────────────────────────────────────
/**
 * Per-event conform assert before grading. PURE over events + a resolution map.
 * @param {Array} events normalized events
 * @param {Object} resolution source → { online?, path?, handleIn?, handleOut?, tcBase?, reverse?, speed? }
 * @param {{minHandle?:number, expectTcBase?:string}} [opts]
 */
export function conformManifest(events, resolution = {}, opts = {}) {
  const minHandle = opts.minHandle ?? 0;
  const isBLsrc = (s) => /^(BL|BLACK)$/i.test(String(s || '').trim());
  const rows = [];
  for (const e of events) {
    const res = resolution[e.source] || {};
    const checks = [];
    const add = (name, pass, detail) => checks.push({ name, pass, ...(detail ? { detail } : {}) });
    // BL/BLACK is the EDL's built-in black source: it needs no resolution
    // entry (it conforms as a Solid Color generator, E91), and its side of a
    // fade needs no handles (a generator extends freely). A fade-out's
    // outgoing tail requirement belongs to the PICTURE source, checked on
    // this BL event against the abutting predecessor.
    if (isBLsrc(e.source)) {
      add('source_resolved', true, 'built-in black (BL) — conforms as a Solid Color generator, no source needed');
      if (e.transition && (e.transition.duration || 0) > 0) {
        const half = Math.ceil(e.transition.duration / 2);
        const prev = events.find((o) => o !== e && o.track === e.track && o.recOut === e.recIn && !isBLsrc(o.source));
        if (prev) {
          const pres = resolution[prev.source] || {};
          const ok = (pres.handleOut ?? 0) >= half;
          add('handles', ok, ok
            ? `fade-out: ${prev.source} carries the outgoing tail`
            : `fade-out to black: outgoing ${prev.source} needs tail ≥${half}; has ${pres.handleOut ?? 0}`);
        }
      }
      const blPass = checks.every((c) => c.pass);
      rows.push({ index: e.index, source: e.source, track: e.track, pass: blPass, checks });
      continue;
    }
    if (e.compound && !(res.path || res.online)) {
      // A compound clipitem (Resolve's XML writer collapses a compound to one
      // media-less item, E121) has no flat source unless the resolution maps
      // its name to a flattened file — say so instead of "no resolved path".
      add('source_resolved', false, `compound clip "${e.compound}" — the XML carries no inner content; map its name to a flattened media file, or turn over as OTIO (nested Stacks flatten)`);
      rows.push({ index: e.index, source: e.source, track: e.track, pass: false, compound: e.compound, checks });
      continue;
    }
    add('source_resolved', res.online !== false && !!(res.path || res.online), res.online === false ? 'offline' : res.path ? undefined : 'no resolved path');
    // Handles — and transition-handle starvation (a dissolve needs handle ≥ half its duration each side).
    const needHandle = Math.max(minHandle, e.transition ? Math.ceil((e.transition.duration || 0) / 2) : 0);
    const fadeInFromBlack = e.transition
      && events.some((o) => o !== e && o.track === e.track && o.recOut === e.recIn && isBLsrc(o.source));
    if (e.transition && fadeInFromBlack) {
      // Fade from black: the boundary shift trims the picture head inside
      // its own material — neither side needs handle media (E91, measured).
      add('handles', true, 'fade from black — no handles needed (the black side extends freely)');
    } else if (needHandle > 0) {
      const ok = (res.handleIn ?? 0) >= needHandle && (res.handleOut ?? 0) >= needHandle;
      add(
        'handles',
        ok,
        ok ? undefined : `need ≥${needHandle} (transition ${e.transition ? e.transition.duration : 0}); have ${res.handleIn ?? 0}/${res.handleOut ?? 0}`,
      );
    }
    // Retime preserved (if the event carries a non-100 speed, the resolution must carry it too).
    if ((e.speed ?? 100) !== 100)
      add('retime_preserved', res.speed == null || Math.abs(res.speed - e.speed) < 0.5, `event ${e.speed}% vs resolved ${res.speed ?? 'n/a'}`);
    // Reverse preserved.
    if (e.reverse) add('reverse_preserved', res.reverse !== false, res.reverse === false ? 'resolved forward' : undefined);
    // TC-base matched.
    if (opts.expectTcBase != null && res.tcBase != null)
      add('tc_base', String(res.tcBase) === String(opts.expectTcBase), `${res.tcBase} vs ${opts.expectTcBase}`);
    const pass = checks.every((c) => c.pass);
    rows.push({ index: e.index, source: e.source, track: e.track, pass, checks });
  }
  const failed = rows.filter((r) => !r.pass);
  return { pass: failed.length === 0, eventCount: rows.length, failedCount: failed.length, rows, failed: failed.map((r) => r.source), gate: 'review' };
}

// ── marker_roundtrip ───────────────────────────────────────────────────
/**
 * Round-trip markers/notes with provenance tags. Normalizes a marker set, stamps provenance,
 * and asserts the set survives encode→decode non-empty (skip-not-fake).
 * @param {Array<{frame:number, name?:string, note?:string, color?:string, source?:string}>} markers
 * @param {{provenanceTag?:string}} [opts]
 */
export function markerRoundtrip(markers, opts = {}) {
  const tag = opts.provenanceTag || 'AUTO:marker_roundtrip';
  const normalized = markers.map((m, i) => ({
    frame: Number(m.frame),
    name: m.name || `Marker ${i + 1}`,
    note: m.note || '',
    color: m.color || 'Blue',
    provenance: m.source ? `${tag} ← ${m.source}` : tag,
  }));
  // Encode → decode (JSON is the interchange; a real EDL/marker export mirrors this shape).
  const encoded = JSON.stringify(normalized);
  const decoded = JSON.parse(encoded);
  if (markers.length && decoded.length !== markers.length)
    throw new Error(`marker_roundtrip: ${markers.length} in, ${decoded.length} out — round-trip dropped markers`);
  const provenanceOk = decoded.every((m) => typeof m.provenance === 'string' && m.provenance.length);
  if (markers.length && !provenanceOk) throw new Error('marker_roundtrip: a marker lost its provenance tag');
  // Binary round-trip through the REAL Sm2SequenceLockableBlob codec
  // (byte-exact vs a live export): provenance rides in customData, so an
  // authored .drt carries it. Colors outside the measured 16 refuse there —
  // markerRoundtrip normalizes to 'Blue' above, so this cannot throw for
  // valid input; if it ever does, that IS the failed round-trip.
  let blobRoundTrip = 'skipped (no markers)';
  if (normalized.length) {
    const { encodeTimelineMarkersBlob, decodeTimelineMarkersBlob } = require('../vendor/drp-format/timeline-markers-blob.js');
    const back = decodeTimelineMarkersBlob(encodeTimelineMarkersBlob(normalized.map((m) => ({
      frame: m.frame, color: m.color, name: m.name, note: m.note, customData: m.provenance,
    }))));
    if (back.length !== normalized.length) throw new Error(`marker_roundtrip: blob codec ${normalized.length} in, ${back.length} out`);
    if (!back.every((m) => m.customData && m.customData.length)) throw new Error('marker_roundtrip: provenance lost in the blob codec');
    blobRoundTrip = 'ok';
  }
  return { count: decoded.length, markers: decoded, provenanceOk, roundTrip: 'ok', blobRoundTrip };
}
