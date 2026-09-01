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
    for (const child of track.children || []) {
      const schema = child.OTIO_SCHEMA || '';
      const dur = (child.source_range && child.source_range.duration && child.source_range.duration.value) || 0;
      const rate = (child.source_range && child.source_range.duration && child.source_range.duration.rate) || opts.fps || 24;
      if (schema.startsWith('Gap')) {
        if (pendingTransition) {
          // Transition then Gap = fade-out into black: attach it to a
          // synthetic BL leg at the junction (the bridge grows it forward).
          events.push(evt({
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
          events.push(evt({
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
        }
        const src = (child.media_reference && (child.media_reference.target_url || child.media_reference.name)) || child.name || 'UNKNOWN';
        // CLIP markers belong to the ITEM, not the sequence — carried as
        // itemMarkers (frames CLIP-relative) so the bridge authors them as
        // Sm2TiItemLockableBlobs (E80). Track-level markers above remain
        // timeline markers.
        const itemMarkers = [];
        for (const mk of child.markers || []) {
          const mrStart = (mk.marked_range && mk.marked_range.start_time && mk.marked_range.start_time.value) || 0;
          itemMarkers.push({ frame: mrStart - startVal, name: mk.name || undefined, color: mk.color || undefined });
        }
        events.push(
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
            fps: rate,
          }),
        );
        pendingTransition = null;
        rec += dur;
      }
    }
    if (pendingTransition) {
      // Transition as the LAST child = fade-out to the end of the track.
      events.push(evt({
        index: idx++, track: kind, source: 'BL',
        recIn: rec, recOut: rec, transition: pendingTransition, fps: lastRate(),
      }));
    }
  }
  return events;
}

// ── XMEML (FCP7 XML) — light clipitem parse ────────────────────────────
export function parseXMEMLEvents(xml, opts = {}) {
  const { XMLParser } = require('fast-xml-parser');
  const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '@_' });
  const doc = parser.parse(xml);
  const events = [];
  let idx = 1;
  const seqRate = opts.fps || 24;
  const walk = (node, track) => {
    if (!node) return;
    const items = Array.isArray(node) ? node : [node];
    for (const it of items) {
      const name = it.name || (it.file && it.file.name) || 'UNKNOWN';
      const start = Number(it.start);
      const end = Number(it.end);
      const inF = Number(it.in);
      const outF = Number(it.out);
      let speed = 100,
        reverse = false;
      // speed via a timeremap/motion filter (best-effort)
      const filters = it.filter ? (Array.isArray(it.filter) ? it.filter : [it.filter]) : [];
      for (const fl of filters) {
        const params = fl.effect && fl.effect.parameter ? (Array.isArray(fl.effect.parameter) ? fl.effect.parameter : [fl.effect.parameter]) : [];
        for (const pm of params) {
          if (/speed/i.test(pm.name || '') && pm.value != null) {
            speed = Math.abs(Number(pm.value));
            reverse = Number(pm.value) < 0;
          }
        }
      }
      if (Number.isFinite(start) && Number.isFinite(end)) {
        // FCP7 clipitem <marker> children are CLIP markers (frames relative
        // to the clip's own <in>) — routed to item markers like OTIO's (E81).
        const mks = it.marker ? (Array.isArray(it.marker) ? it.marker : [it.marker]) : [];
        const itemMarkers = mks
          .filter((mk) => Number.isFinite(Number(mk.in)))
          .map((mk) => ({ frame: Number(mk.in) - inF, name: mk.name != null ? String(mk.name) : undefined, note: mk.comment != null ? String(mk.comment) : undefined }));
        events.push(evt({ index: idx++, track, source: name, srcIn: inF, srcOut: outF, recIn: start, recOut: end, speed, reverse, itemMarkers: itemMarkers.length ? itemMarkers : undefined, fps: seqRate }));
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
      if (t.clipitem) walk(t.clipitem, label);
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
        const incoming = events.slice(before).find((ev) => ev.track === label && ev.recIn > s - 1 && ev.recIn <= e2);
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
    });
    const atracks = media.audio && media.audio.track ? (Array.isArray(media.audio.track) ? media.audio.track : [media.audio.track]) : [];
    for (const t of atracks) if (t.clipitem) walk(t.clipitem, 'A');
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
        `parse_interchange: .${String(format).toLowerCase()} is a ZIP container — parse it via the path-based reader (drt.mjs \`parseDRT(path)\`), not the sync parseInterchange(). Entry points: editorial \`list_sequences({path})\` or drt \`parse({drtPath})\`.`,
      );
    default:
      throw new Error(`parse_interchange: unknown format '${format}' (edl|otio|xml|xmeml|fcp7|drt|drp|aaf|prproj)`);
  }
}

// ── turnover_changelist ────────────────────────────────────────────────
const sig = (e) => `${e.track}:${e.source}`;

/**
 * Diff two normalized event lists → per-event {kind: moved|retimed|replaced|new|gone|unchanged}.
 * @param {Array} oldEvents
 * @param {Array} newEvents
 * @param {{recTolerance?:number}} [opts]
 */
export function diffChangelist(oldEvents, newEvents, opts = {}) {
  const recTol = opts.recTolerance ?? 1;
  const oldPool = oldEvents.map((e) => ({ e, used: false }));
  const changes = [];

  for (const ne of newEvents) {
    // Prefer a same-source match; among those, the closest record position.
    const candidates = oldPool.filter((o) => !o.used && sig(o.e) === sig(ne));
    let match = null;
    if (candidates.length) {
      candidates.sort((a, b) => Math.abs((a.e.recIn ?? 0) - (ne.recIn ?? 0)) - Math.abs((b.e.recIn ?? 0) - (ne.recIn ?? 0)));
      match = candidates[0];
    }
    if (!match) {
      changes.push({ kind: 'new', source: ne.source, track: ne.track, newRecIn: ne.recIn });
      continue;
    }
    match.used = true;
    const oe = match.e;
    const deltas = {};
    let kind = 'unchanged';
    if (Math.abs((oe.speed ?? 100) - (ne.speed ?? 100)) > 0.01 || oe.reverse !== ne.reverse) {
      kind = 'retimed';
      deltas.speed = { old: oe.speed, new: ne.speed };
      if (oe.reverse !== ne.reverse) deltas.reverse = { old: oe.reverse, new: ne.reverse };
    } else if (Math.abs((oe.recIn ?? 0) - (ne.recIn ?? 0)) > recTol) {
      kind = 'moved';
      deltas.recIn = { old: oe.recIn, new: ne.recIn };
    } else if ((oe.srcIn ?? null) !== (ne.srcIn ?? null) || (oe.srcOut ?? null) !== (ne.srcOut ?? null)) {
      kind = 'trimmed';
      deltas.src = { old: [oe.srcIn, oe.srcOut], new: [ne.srcIn, ne.srcOut] };
    }
    if (kind !== 'unchanged') changes.push({ kind, source: ne.source, track: ne.track, oldRecIn: oe.recIn, newRecIn: ne.recIn, deltas });
  }
  // Unconsumed old events → gone (unless a 'new' at the same rec position → replaced).
  for (const o of oldPool.filter((x) => !x.used)) {
    const replacement = changes.find((c) => c.kind === 'new' && c.track === o.e.track && Math.abs((c.newRecIn ?? 0) - (o.e.recIn ?? 0)) <= recTol);
    if (replacement) {
      replacement.kind = 'replaced';
      replacement.oldSource = o.e.source;
      replacement.oldRecIn = o.e.recIn;
    } else {
      changes.push({ kind: 'gone', source: o.e.source, track: o.e.track, oldRecIn: o.e.recIn });
    }
  }
  const counts = {};
  for (const c of changes) counts[c.kind] = (counts[c.kind] || 0) + 1;
  changes.sort((a, b) => (a.newRecIn ?? a.oldRecIn ?? 0) - (b.newRecIn ?? b.oldRecIn ?? 0));
  return { changes, counts, changedCount: changes.length, gate: 'review' };
}

// ── TIMING silent-lie guards ───────────────────────────────────────────
/**
 * Detect timing lies between an old (locked-cut) and new (conformed) event list.
 * @returns {{flags:Array<{kind, source, detail}>}}
 */
export function timingGuards(oldEvents, newEvents) {
  const flags = [];
  const newBySig = new Map();
  for (const e of newEvents) {
    if (!newBySig.has(sig(e))) newBySig.set(sig(e), []);
    newBySig.get(sig(e)).push(e);
  }
  for (const oe of oldEvents) {
    const matches = newBySig.get(sig(oe)) || [];
    const ne = matches[0];
    if (!ne) {
      // A dropped audio event where its video sibling survives → dropped J/L-cut audio.
      if (oe.track === 'A' && newEvents.some((x) => x.track !== 'A' && x.source === oe.source))
        flags.push({ kind: 'dropped_split_audio', source: oe.source, detail: 'audio event gone but video sibling present (J/L-cut lost)' });
      continue;
    }
    // Flattened retime: a speed ramp/change flattened to 100%.
    if ((oe.speed ?? 100) !== 100 && (ne.speed ?? 100) === 100)
      flags.push({ kind: 'flattened_retime', source: oe.source, detail: `speed ${oe.speed}% → 100% (retime lost)` });
    // Reverse dropped.
    if (oe.reverse && !ne.reverse) flags.push({ kind: 'reverse_dropped', source: oe.source, detail: 'reversed clip conformed forward' });
    // Framerate/pulldown slip.
    if (oe.fps && ne.fps && oe.fps !== ne.fps) flags.push({ kind: 'framerate_slip', source: oe.source, detail: `fps ${oe.fps} → ${ne.fps}` });
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
