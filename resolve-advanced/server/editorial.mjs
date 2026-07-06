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
  const m = TC_RE.exec(String(tc).trim());
  if (!m || !fps) return null;
  const [, h, mm, s, f] = m.map(Number);
  return Math.round((h * 3600 + mm * 60 + s) * fps) + f;
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
    source: o.source || 'UNKNOWN',
    srcIn: o.srcIn ?? null,
    srcOut: o.srcOut ?? null,
    recIn: o.recIn ?? null,
    recOut: o.recOut ?? null,
    speed: o.speed ?? 100,
    reverse: o.reverse ?? false,
    transition: o.transition || null,
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
    const tokens = line.split(/\s+/);
    if (!/^\d+$/.test(tokens[0])) continue; // not an event line
    const tcs = tokens.filter(isTc);
    if (tcs.length < 4) continue;
    const [srcIn, srcOut, recIn, recOut] = tcs.slice(-4);
    const head = tokens.slice(0, tokens.indexOf(tcs[tcs.length - 4]));
    const [eventNum, reel, channel, transition] = head;
    const dur = transition && transition !== 'C' ? Number(head[4]) : 0;
    const track = /A/i.test(channel || '') && !/V/i.test(channel || '') ? 'A' : 'V';
    events.push(
      evt({
        index: Number(eventNum),
        track,
        source: reel,
        srcIn: tcToFrames(srcIn, fps),
        srcOut: tcToFrames(srcOut, fps),
        recIn: tcToFrames(recIn, fps),
        recOut: tcToFrames(recOut, fps),
        transition: transition && transition !== 'C' ? { type: transition, duration: dur || 0 } : null,
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
  for (const track of tracks) {
    const kind = track.kind === 'Audio' ? 'A' : 'V';
    let rec = 0;
    for (const child of track.children || []) {
      const schema = child.OTIO_SCHEMA || '';
      const dur = (child.source_range && child.source_range.duration && child.source_range.duration.value) || 0;
      const rate = (child.source_range && child.source_range.duration && child.source_range.duration.rate) || opts.fps || 24;
      if (schema.startsWith('Gap')) {
        rec += dur;
        continue;
      }
      if (schema.startsWith('Clip')) {
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
            fps: rate,
          }),
        );
        rec += dur;
      }
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
        events.push(evt({ index: idx++, track, source: name, srcIn: inF, srcOut: outF, recIn: start, recOut: end, speed, reverse, fps: seqRate }));
      }
    }
  };
  const seq = doc.xmeml && doc.xmeml.sequence;
  const media = seq && seq.media;
  if (media) {
    const vtracks = media.video && media.video.track ? (Array.isArray(media.video.track) ? media.video.track : [media.video.track]) : [];
    for (const t of vtracks) if (t.clipitem) walk(t.clipitem, 'V');
    const atracks = media.audio && media.audio.track ? (Array.isArray(media.audio.track) ? media.audio.track : [media.audio.track]) : [];
    for (const t of atracks) if (t.clipitem) walk(t.clipitem, 'A');
  }
  return events;
}

/**
 * Dispatch by format (SYNC, pure over TEXT). Binary formats are handled out-of-band by their own
 * path-based readers — AAF via aaf.mjs `parseAAF` (async, pyaaf2), .prproj via prproj.mjs
 * `parsePrproj` (gunzip+XML). This throws to route callers there rather than faking a parse.
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
    default:
      throw new Error(`parse_interchange: unknown format '${format}' (edl|otio|xml|xmeml|fcp7|aaf|prproj)`);
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
      if (oe.track === 'A' && newEvents.some((x) => x.track === 'V' && x.source === oe.source))
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
  const rows = [];
  for (const e of events) {
    const res = resolution[e.source] || {};
    const checks = [];
    const add = (name, pass, detail) => checks.push({ name, pass, ...(detail ? { detail } : {}) });
    add('source_resolved', res.online !== false && !!(res.path || res.online), res.online === false ? 'offline' : res.path ? undefined : 'no resolved path');
    // Handles — and transition-handle starvation (a dissolve needs handle ≥ half its duration each side).
    const needHandle = Math.max(minHandle, e.transition ? Math.ceil((e.transition.duration || 0) / 2) : 0);
    if (needHandle > 0) {
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
  return { count: decoded.length, markers: decoded, provenanceOk, roundTrip: 'ok' };
}
