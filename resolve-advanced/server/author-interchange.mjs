/**
 * Author an interchange (OTIO / EDL / DRT) FROM a normalized-event list — the write-side of the
 * conform bridge. Its purpose: turn a parsed turnover (esp. .prproj, which Resolve can't import
 * natively) into a format Resolve DOES import, WITHOUT round-tripping through Premiere.
 *
 * OTIO is the default target: it carries gaps, per-clip speed (LinearTimeWarp) and transitions, and
 * round-trips through this repo's own parseOTIO. EDL is CMX3600 (cuts + M2 speed). DRT is authored
 * via the vendored buildDRT (Resolve-native). Editorial timing/structure survives with high
 * fidelity; per-clip effects/color do NOT (the Premiere→Resolve semantic gap, flagged not faked).
 */
import { drt } from './libs.mjs';

const COLOR_MAP = {
  blue: 'Blue', cyan: 'Cyan', green: 'Green', yellow: 'Yellow', red: 'Red',
  pink: 'Pink', purple: 'Purple', magenta: 'Fuchsia', fuchsia: 'Fuchsia',
  rose: 'Rose', lavender: 'Lavender', sky: 'Sky', mint: 'Mint',
  lemon: 'Lemon', sand: 'Sand', cocoa: 'Cocoa', cream: 'Cream',
  orange: 'Sand', white: 'Cream', black: 'Cocoa',
};

const pad = (n, w = 2) => String(Math.max(0, Math.floor(n))).padStart(w, '0');

/** frames → CMX timecode at fps (non-drop). */
export function framesToTc(frames, fps) {
  const f = Math.max(0, Math.round(Number(frames) || 0));
  const r = Math.max(1, Math.round(fps || 24));
  const ff = f % r;
  const s = Math.floor(f / r);
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}:${pad(ff)}`;
}

const byTrack = (events) => {
  const groups = { V: [], A: [] };
  for (const e of events) groups[e.track === 'A' ? 'A' : 'V'].push(e);
  for (const k of Object.keys(groups)) groups[k].sort((a, b) => (a.recIn ?? 0) - (b.recIn ?? 0));
  return groups;
};

/**
 * Events whose media timecode ORIGIN had to be assumed as 0 when authoring OTIO. Resolve
 * measures a clip's source_range against the media's real timecode range, so an event with
 * no origin only imports if its media genuinely starts at 00:00:00:00 — otherwise the file
 * looks fine and Resolve creates no timeline. Supply `mediaStartTcFrame` (or an absolute
 * `srcTcFrame`) per event to clear it. Always an array, empty when every event carried one.
 */
export function otioMediaOriginAssumed(events) {
  const out = [];
  (events || []).forEach((e, index) => {
    if (e.srcTcFrame != null || e.mediaStartTcFrame != null || e.startTcFrame != null) return;
    out.push({
      index,
      recIn: e.recIn ?? 0,
      srcIn: e.srcIn ?? 0,
      source: e.source || '',
      reason: 'no media timecode origin — assumed 00:00:00:00; Resolve rejects the import if the media starts elsewhere',
    });
  });
  return out;
}

const rt = (value, rate) => ({ OTIO_SCHEMA: 'RationalTime.1', rate: Number(rate), value: Number(value) });
const tr = (start, duration, rate) => ({ OTIO_SCHEMA: 'TimeRange.1', duration: rt(duration, rate), start_time: rt(start, rate) });
const basename = (p) => String(p || '').split('/').pop() || 'UNKNOWN';

/**
 * Build an OTIO timeline doc (plain object) from normalized events. Inserts gaps so record
 * positions are exact; emits LinearTimeWarp for speed/reverse and Transition items where present.
 *
 * The emitted shape mirrors what Resolve's own EXPORT_OTIO writes, because Resolve's importer
 * is far pickier than the OTIO spec. Measured on 19.1.3: a Resolve-authored .otio re-imports
 * through MediaPool.ImportTimelineFromFile (3 items, 3 linked) while the shape this function
 * used to emit produced NO TIMELINE — same project, same session, same three online media
 * files. So the scripting API imports OTIO fine; what it rejects is a document that is valid
 * OTIO but not Resolve-shaped. The parts that matter:
 *
 *   - `Clip.2` with a `media_references` MAP + `active_media_reference_key`, not `Clip.1`
 *     with a singular `media_reference`. This is the one that most looks like a free choice
 *     and is not.
 *   - `available_range` on the external reference, and a clip `name` that is the media
 *     BASENAME rather than its full path.
 *   - SOURCE FRAMES ARE TIMECODE-ABSOLUTE. This is the one that decides the import. The
 *     media used to measure this carries an embedded start TC of 01:00:00:00, so Resolve
 *     writes its `available_range` starting at frame 86400 and the clip's `source_range`
 *     at 86400 too. Emitting the same cut with 0-based source offsets — the natural
 *     reading of "source in point" — produced NO TIMELINE, because frame 0 is outside the
 *     media's real range. Bisected: 0-based fails and absolute succeeds whether or not the
 *     stack/track `source_range` is null, so it is the frame origin that matters and not
 *     the surrounding shape. Same lesson as srcIn being fragment-relative on consolidated
 *     media: a source position means nothing without the origin it is measured from.
 *   - `enabled: true` on stack, tracks and clips; `metadata` objects present (Resolve stamps
 *     its own `Resolve_OTIO` block and reads the tracks' back).
 *   - `global_start_time` on the timeline, and track names in Resolve's own form ("Video 1").
 *
 * Give the media's TC origin per event as `mediaStartTcFrame` (or an already-absolute
 * `srcTcFrame`). Without it this falls back to a 0 origin, which only imports when the media
 * really does start at 00:00:00:00 — so the events that had to be assumed are reported back
 * in `mediaOriginAssumed` rather than silently producing a file that imports as nothing.
 *
 * Handy inverse: this repo's parseOTIO still reads what we emit, so the bridge round-trips.
 */
export function eventsToOTIO(events, opts = {}) {
  const fps = opts.fps || events.find((e) => e.fps)?.fps || 24;
  const startFrame = opts.startFrame ?? opts.globalStartFrame ?? 0;
  const groups = byTrack(events);
  const tracks = [];
  for (const [kind, list] of [
    ['Video', groups.V],
    ['Audio', groups.A],
  ]) {
    if (!list.length) continue;
    const children = [];
    let rec = 0;
    for (const e of list) {
      const recIn = e.recIn ?? rec;
      if (recIn > rec) {
        children.push({
          OTIO_SCHEMA: 'Gap.1',
          metadata: {},
          source_range: { OTIO_SCHEMA: 'TimeRange.1', duration: rt(recIn - rec, fps), start_time: rt(0, fps) },
          effects: [],
          markers: [],
          enabled: true,
        });
        rec = recIn;
      }
      const recDur = (e.recOut ?? recIn) - recIn;
      const clipFps = e.fps || fps;
      const srcIn = e.srcIn ?? 0;
      // The media's timecode origin. srcTcFrame (already absolute) wins; otherwise the
      // media start TC plus the in-point. A 0 origin is an ASSUMPTION, and it is recorded.
      const mediaStart = e.mediaStartTcFrame ?? e.startTcFrame ?? null;
      const srcStart = e.srcTcFrame ?? (mediaStart ?? 0) + srcIn;
      const availStart = e.srcTcFrame != null ? e.srcTcFrame - srcIn : (mediaStart ?? 0);
      const clip = {
        OTIO_SCHEMA: 'Clip.2',
        metadata: {},
        name: basename(e.source),
        source_range: tr(srcStart, recDur, clipFps),
        effects: [],
        markers: [],
        enabled: true,
        media_references: {
          DEFAULT_MEDIA: {
            OTIO_SCHEMA: 'ExternalReference.1',
            metadata: {},
            name: basename(e.source),
            // Resolve writes a BARE path here, not a file:// URL.
            target_url: e.source || '',
            available_range: tr(availStart, e.mediaDuration ?? e.srcAvailDuration ?? Math.max(recDur, srcIn + recDur), clipFps),
            available_image_bounds: null,
          },
        },
        active_media_reference_key: 'DEFAULT_MEDIA',
      };
      if ((e.speed ?? 100) !== 100 || e.reverse) {
        clip.effects.push({ OTIO_SCHEMA: 'LinearTimeWarp.1', name: 'Speed', metadata: {}, effect_name: 'LinearTimeWarp', time_scalar: (e.reverse ? -1 : 1) * ((e.speed ?? 100) / 100) });
      }
      if (e.transition) {
        children.push({
          OTIO_SCHEMA: 'Transition.1',
          metadata: {},
          name: 'Cross Dissolve',
          transition_type: 'SMPTE_Dissolve',
          in_offset: rt(Math.ceil((e.transition.duration || 0) / 2), fps),
          out_offset: rt(Math.floor((e.transition.duration || 0) / 2), fps),
        });
      }
      children.push(clip);
      rec = recIn + recDur;
    }
    tracks.push({
      OTIO_SCHEMA: 'Track.1',
      metadata: {},
      name: `${kind} 1`,
      source_range: tr(0, rec, fps),
      effects: [],
      markers: [],
      enabled: true,
      children,
      kind,
    });
  }
  const stackDur = tracks.reduce((m, t) => Math.max(m, t.source_range.duration.value), 0);
  return {
    OTIO_SCHEMA: 'Timeline.1',
    metadata: {},
    name: opts.name || 'Conformed',
    global_start_time: rt(startFrame, fps),
    tracks: {
      OTIO_SCHEMA: 'Stack.1',
      metadata: {},
      name: 'tracks',
      source_range: tr(0, stackDur, fps),
      effects: [],
      markers: [],
      enabled: true,
      children: tracks,
    },
  };
}

/** Build a CMX3600 EDL string (cuts + M2 speed). Video events only, per EDL convention. */
/**
 * eventsToAssembleSpec — normalized interchange events → drt.assemble media spec.
 *
 * The coast-to-coast bridge: parseInterchange's events (EDL/AAF/OTIO/XML)
 * become an importable, RENDERING native .drt via assembleTimeline's
 * transplant path. Frame math: event frames are NOMINAL-base at the event's
 * fps (v2.104.6 convention, measured against Resolve); the assemble template
 * timeline runs 24fps with origin 86400, so rec/src frames convert as
 * round(frames × 24 / nominalFps). Placement anchors the EARLIEST video
 * event at the origin. Honesty ledger in the returned report: authored
 * retimes (constant speed forward AND reverse, and zero-speed FREEZES — all
 * AUTHORED as real Sm2TimeMaps, r19 keyed form, readback/render-verified;
 * freezes render-proven frozen via freezedetect, E55/E56), authored vs
 * dropped transitions (cross-dissolves are AUTHORED when the predecessor
 * abuts the cut and both sides have handle media — render-verified on
 * 19.1.3.7; otherwise dropped with the reason, as a cut at the boundary),
 * and audio: A-track events are AUTHORED as audioOnly cuts on their own
 * audio tracks (render-verified; the template carries 8 Fairlight-valid
 * audio tracks) — their presence suppresses the A1 convenience mirror.
 *
 * @param {Array} events - normalized events (parseInterchange shape)
 * @param {object} opts
 * @param {Object<string,{mediaFilePath:string, spec:object}>} opts.sourceMap -
 *   event.source (reel) → media file + spec. Every VIDEO event's source must
 *   be mapped; unmapped reels refuse with the reel names listed.
 * @param {string} [opts.timelineName]
 * @returns {{spec: object, report: object}}
 */
export function eventsToAssembleSpec(events, opts = {}) {
  const { sourceMap, timelineName, preserveStartTimecode = false } = opts;
  if (!Array.isArray(events) || !events.length) {
    throw new TypeError('eventsToAssembleSpec: events must be a non-empty array');
  }
  if (!sourceMap || typeof sourceMap !== 'object') {
    throw new TypeError('eventsToAssembleSpec: sourceMap {reel: {mediaFilePath, spec}} is required');
  }
  const DEFAULT_ORIGIN = 86400;
  const isAudio = (t) => /^A\d*$/.test(String(t || ''));
  const isMarker = (t) => t === 'MARKER';
  const vids = events.filter((e) => !isAudio(e.track) && !isMarker(e.track) && e.recIn != null && e.recOut != null);
  // AAF exports one event per audio CHANNEL — a stereo/dual-mono clip arrives
  // as identical A-track legs (measured on a Resolve 19 rich export: every
  // audio event duplicated). Merge exact duplicates (same track/source/range)
  // so they place once instead of refusing as a same-track overlap.
  const audsRaw = events.filter((e) => isAudio(e.track) && e.recIn != null && e.recOut != null);
  const seenAud = new Set();
  const auds = [];
  let audioChannelLegsMerged = 0;
  for (const e of audsRaw) {
    const k = `${e.track}|${e.source}|${e.recIn}|${e.recOut}|${e.srcIn}`;
    if (seenAud.has(k)) { audioChannelLegsMerged += 1; continue; }
    seenAud.add(k);
    auds.push(e);
  }
  const markerEvents = events.filter((e) => isMarker(e.track) && e.recIn != null);
  const audioSkipped = events.length - vids.length - audsRaw.length - markerEvents.length;
  if (!vids.length) throw new Error('eventsToAssembleSpec: no video events with record ranges');

  // BL/BLACK reels are the EDL's built-in black source — they never need a
  // sourceMap entry. Video BL legs author as Solid Color generator elements
  // (Resolve's own EDL importer creates exactly that for the slug — but DROPS
  // the fade dissolves around it, measured E91); audio BL legs are silence,
  // which an empty track already is.
  const isBL = (srcName) => /^(BL|BLACK)$/i.test(String(srcName || '').trim());
  const unmapped = [...new Set([...vids, ...auds].map((e) => e.source).filter((srcName) => !isBL(srcName) && !sourceMap[srcName]))];
  if (unmapped.length) {
    throw new Error(
      `eventsToAssembleSpec: unmapped source reel(s): ${unmapped.join(', ')} — ` +
      'every video event needs a sourceMap entry {mediaFilePath, spec}',
    );
  }

  const toTl = (frames, fps) => Math.round((frames * 24) / Math.round(fps || 24));
  // 'V'/'V1' → 1, 'V2' → 2, … (parsers number video tracks; EDL is single-V).
  const trackNum = (t) => { const m = /^V(\d+)?$/.exec(String(t || 'V')); return m ? (m[1] ? parseInt(m[1], 10) : 1) : 1; };
  const flattenedRetimes = [];
  const authoredRetimes = [];
  const droppedTransitions = [];
  const transitionCandidates = [];
  const perSource = new Map();
  const placements = [];

  // Default: anchor the earliest event at the template origin (86400).
  // preserveStartTimecode keeps the interchange's ABSOLUTE record positions —
  // the assembled timeline starts at the turnover's real first record frame
  // (MediaExtents start-TC patch, measured: imports with the new start TC and
  // renders). AAF conforms need this: build at THAT start, not 01:00:00:00.
  const minRecRaw = Math.min(...vids.map((e) => toTl(e.recIn, e.fps)));
  const minRec = preserveStartTimecode ? 0 : minRecRaw;
  const ORIGIN = preserveStartTimecode ? 0 : DEFAULT_ORIGIN;
  const startFrame = preserveStartTimecode ? minRecRaw : DEFAULT_ORIGIN;
  const blackLegs = [];
  for (const e of vids) {
    const recIn = ORIGIN + (toTl(e.recIn, e.fps) - minRec);
    const recOut = ORIGIN + (toTl(e.recOut, e.fps) - minRec);
    const durationFrames = recOut - recIn;
    const vTrackEarly = trackNum(e.track);
    if (isBL(e.source)) {
      // BL leg → Solid Color generator element (renders black; the authored
      // clip↔generator dissolve render-verified E91: luma ramps 124→16
      // through the junction). ZERO-length BL is kept as a placement so a
      // fade-in's boundary-shift can GROW it — the CMX fade-in form is a
      // zero-length BL cut followed by a D event, and a single-sided
      // transition refuses to import (measured E91), so the shift is the
      // only authorable shape.
      if (durationFrames < 0) continue;
      const el = { type: 'generator', generatorName: 'Solid Color', track: vTrackEarly, startFrame: recIn, durationFrames, srcIn: 0 };
      blackLegs.push(el);
      if (e.transition) {
        let d = Math.max(2, toTl(e.transition.duration || 0, e.fps) || 2);
        d += d % 2;
        let pre = Math.floor(d / 2);
        if (e.transition.alignment === 'start') pre = 0;
        else if (e.transition.inOffset != null) pre = Math.min(d, Math.max(0, toTl(e.transition.inOffset, e.fps)));
        else if (e.transition.recStart != null) {
          const spanStartAbs = ORIGIN + (toTl(e.transition.recStart, e.fps) - minRec);
          pre = Math.min(d, Math.max(0, recIn - spanStartAbs));
        }
        transitionCandidates.push({
          atFrame: recIn, durationFrames: d, track: vTrackEarly, pre,
          explicitSpan: e.transition.alignment != null || e.transition.inOffset != null || e.transition.recStart != null,
          index: e.index, type: e.transition.type, rawDuration: e.transition.duration,
          source: e.source, srcIn: Infinity, incomingCutRef: el, cutPoint: e.transition.cutPoint,
        });
      }
      placements.push({ start: recIn, end: recOut, index: e.index, source: e.source, srcIn: Infinity, durationFrames, track: vTrackEarly, cutRef: el });
      continue;
    }
    if (durationFrames <= 0) continue;
    const vTrack = vTrackEarly;
    const cut = { startFrame: recIn, durationFrames, srcIn: toTl(e.srcIn ?? 0, e.fps), ...(vTrack > 1 ? { track: vTrack } : {}) };
    // CLIP markers from the turnover (OTIO clip markers, XMEML clipitem
    // <marker>s) become ITEM markers on the cut (frames clip-relative,
    // nominal→timeline converted; anything landing outside the cut is
    // dropped rather than refused — a marker on trimmed-away material).
    if (Array.isArray(e.itemMarkers) && e.itemMarkers.length) {
      const ims = e.itemMarkers
        .map((m) => ({
          frame: Math.round(toTl(m.frame ?? 0, e.fps)),
          color: COLOR_MAP[String(m.color || '').toLowerCase()] || 'Blue',
          ...(m.name ? { name: m.name } : {}),
          ...(m.note ? { note: m.note } : {}),
        }))
        .filter((m) => m.frame >= 0 && m.frame < durationFrames);
      if (ims.length) cut.markers = ims;
    }
    if ((e.speed ?? 100) !== 100 || e.reverse) {
      const spd = Math.abs(e.speed ?? 100);
      if (!(spd > 0)) {
        // FREEZE (EDL M2 000.0 / zero-speed OTIO warp): authored as the real
        // freeze Sm2TimeMap harvested live in E55 — holds srcIn for the
        // whole cut (render-proven frozen via freezedetect on 19.1.3.7).
        cut.freeze = true;
        authoredRetimes.push({ index: e.index, source: e.source, speed: 0, freeze: true });
      } else {
        // Constant speed, forward or reverse: authored as a real Sm2TimeMap
        // on the cut (r19 keyed form; readback/render-verified on 19.1.3.7 —
        // reverse reads back source 71→23 for a srcIn-24 dur-48 cut). Audio
        // for retimed cuts is video-only downstream.
        if (spd !== 100) cut.speed = spd / 100;
        if (e.reverse) cut.reverse = true;
        authoredRetimes.push({ index: e.index, source: e.source, speed: spd, ...(e.reverse ? { reverse: true } : {}) });
      }
    }
    if (e.transition) {
      // A dissolve INTO this event, at its record-in boundary. Whether it can
      // be authored (abutting predecessor + handles both sides) is decided
      // after all placements are known.
      let d = Math.max(2, toTl(e.transition.duration || 0, e.fps) || 2);
      d += d % 2; // even duration keeps every alignment on whole frames
      // Span geometry per format (E73): `pre` = frames of the span BEFORE
      // the cut. EDL: 0 (CMX start-at-cut — matches what Resolve's own EDL
      // importer authors, E61 harvest); OTIO: the explicit in_offset; XMEML:
      // derived from the transitionitem's own record start; no info: centered.
      let pre = Math.floor(d / 2);
      if (e.transition.alignment === 'start') pre = 0;
      else if (e.transition.inOffset != null) pre = Math.min(d, Math.max(0, toTl(e.transition.inOffset, e.fps)));
      else if (e.transition.recStart != null) {
        const spanStartAbs = ORIGIN + (toTl(e.transition.recStart, e.fps) - minRec);
        pre = Math.min(d, Math.max(0, recIn - spanStartAbs));
      }
      transitionCandidates.push({
        atFrame: recIn, durationFrames: d, track: vTrack, pre,
        explicitSpan: e.transition.alignment != null || e.transition.inOffset != null || e.transition.recStart != null,
        index: e.index, type: e.transition.type, rawDuration: e.transition.duration,
        source: e.source, srcIn: cut.srcIn, incomingCutRef: cut, cutPoint: e.transition.cutPoint,
      });
    }
    placements.push({ start: recIn, end: recOut, index: e.index, source: e.source, srcIn: cut.srcIn, durationFrames, track: vTrack, cutRef: cut });
    if (!perSource.has(e.source)) perSource.set(e.source, []);
    perSource.get(e.source).push(cut);
  }

  // Audio events become explicit audioOnly cuts on their own audio tracks —
  // this SUPPRESSES the convenience A1 mirror downstream (explicit audio
  // wins). Render-verified on 19.1.3.7: an offline A3 cut plays at the
  // native control level through the captured 8-audio-track template's
  // Fairlight strips. Retimed audio is not authored (no audio timemap yet).
  const audioTrackNum = (t) => { const m = /^A(\d+)?$/.exec(String(t)); return m && m[1] ? parseInt(m[1], 10) : 1; };
  const audioPlacements = [];
  const audioRetimesSkipped = [];
  const audioTransCandidates = [];
  let audioBlackLegsSkipped = 0;
  for (const e of auds) {
    if (isBL(e.source)) {
      // Audio BL = silence, which an empty track already is. A fade to/from
      // it has no authorable form (no silence source to cross-fade against);
      // the level steps at the cut instead of ramping — stated, not silent.
      audioBlackLegsSkipped += 1;
      if (e.transition) {
        droppedTransitions.push({
          index: e.index, type: e.transition.type, duration: e.transition.duration, trackType: 'audio',
          reason: 'audio fade to/from BL (silence) — no silence source to cross-fade against; the level steps at the cut',
        });
      }
      continue;
    }
    const recIn = ORIGIN + (toTl(e.recIn, e.fps) - minRec);
    const recOut = ORIGIN + (toTl(e.recOut, e.fps) - minRec);
    const durationFrames = recOut - recIn;
    if (durationFrames <= 0) continue;
    if ((e.speed ?? 100) !== 100 || e.reverse) {
      audioRetimesSkipped.push({ index: e.index, source: e.source, speed: e.speed, reverse: !!e.reverse, reason: 'audio retime not authorable — the audio engine ignores the clip timemap (measured: reads back retimed, renders 100%); played at 100%' });
    }
    const track = audioTrackNum(e.track);
    const cut = { startFrame: recIn, durationFrames, srcIn: toTl(e.srcIn ?? 0, e.fps), audioOnly: true, track };
    if (e.transition) {
      let d = Math.max(2, toTl(e.transition.duration || 0, e.fps) || 2);
      d += d % 2;
      let pre = Math.floor(d / 2);
      if (e.transition.alignment === 'start') pre = 0;
      else if (e.transition.inOffset != null) pre = Math.min(d, Math.max(0, toTl(e.transition.inOffset, e.fps)));
      else if (e.transition.recStart != null) {
        const spanStartAbs = ORIGIN + (toTl(e.transition.recStart, e.fps) - minRec);
        pre = Math.min(d, Math.max(0, recIn - spanStartAbs));
      }
      audioTransCandidates.push({
        atFrame: recIn, durationFrames: d, track, pre,
        explicitSpan: e.transition.alignment != null || e.transition.inOffset != null || e.transition.recStart != null,
        index: e.index, type: e.transition.type, rawDuration: e.transition.duration,
        source: e.source, srcIn: cut.srcIn, incomingCutRef: cut, cutPoint: e.transition.cutPoint,
      });
    }
    audioPlacements.push({ start: recIn, end: recOut, index: e.index, track, source: e.source, srcIn: cut.srcIn, durationFrames, cutRef: cut });
    if (!perSource.has(e.source)) perSource.set(e.source, []);
    perSource.get(e.source).push(cut);
  }
  // AAF overlap reconciliation (E93): an AAF Transition CONSUMES record time
  // — the incoming component starts `duration` frames before the outgoing
  // ends, so the walker legitimately emits OVERLAPPING events with the
  // transition on the incoming (alignment 'start' at the overlap start).
  // Trim the outgoing's tail to the overlap start before the overlap gates:
  // the boundary-shift below then re-extends it to the cut point, which is
  // exactly the AAF notional-cut semantics (CutPoint, centered by default).
  // Without this the overlap gate threw and NO AAF dissolve could conform.
  const reconcileAafOverlap = (cands, pls) => {
    for (const c of cands) {
      if (!c.explicitSpan || c.pre !== 0) continue;
      const prev = pls.find((pl) => pl.track === c.track && pl.start < c.atFrame && pl.end > c.atFrame && pl.end - c.atFrame <= c.durationFrames);
      if (!prev) continue;
      const o = prev.end - c.atFrame;
      if (prev.durationFrames <= o) continue; // degenerate: leave for the drop paths
      prev.end -= o;
      prev.durationFrames -= o;
      prev.cutRef.durationFrames -= o;
    }
  };
  reconcileAafOverlap(transitionCandidates, placements);
  reconcileAafOverlap(audioTransCandidates, audioPlacements);

  audioPlacements.sort((a, b) => a.start - b.start);
  const audByTrack = new Map();
  for (const pl of audioPlacements) {
    if (!audByTrack.has(pl.track)) audByTrack.set(pl.track, []);
    audByTrack.get(pl.track).push(pl);
  }
  for (const [trk, pls] of audByTrack) {
    for (let i = 1; i < pls.length; i += 1) {
      if (pls[i].start < pls[i - 1].end) {
        throw new Error(
          `eventsToAssembleSpec: audio events ${pls[i - 1].index} and ${pls[i].index} ` +
          `overlap on audio track ${trk} after frame conversion — one track cannot hold both.`);
      }
    }
  }

  // Overlap is judged PER VIDEO TRACK — V2 stacking over V1 is legitimate
  // conform geometry (render-verified: an upper-track clip covers the lower).
  // end-tiebreak keeps a zero-length BL placement AHEAD of the picture leg
  // that starts at the same frame (fade-in form) — start-only sorting would
  // read them as an overlap.
  placements.sort((a, b) => a.start - b.start || a.end - b.end);
  const byTrack = new Map();
  for (const pl of placements) {
    if (!byTrack.has(pl.track)) byTrack.set(pl.track, []);
    byTrack.get(pl.track).push(pl);
  }
  for (const [trk, pls] of byTrack) {
    for (let i = 1; i < pls.length; i += 1) {
      if (pls[i].start < pls[i - 1].end) {
        throw new Error(
          `eventsToAssembleSpec: events ${pls[i - 1].index} and ${pls[i].index} ` +
          `overlap on video track ${trk} after frame conversion — one track cannot hold both. ` +
          'Resolve the overlap upstream (transitions count as cuts at their boundary here).',
        );
      }
    }
  }

  // Reel aliasing: multiple reels legitimately map to ONE file (Avid mob
  // names vs tape names, re-linked dailies). Group by mediaFilePath so the
  // assembly sees one source per FILE, not per reel.
  const byFile = new Map();
  for (const [reel, cuts] of perSource.entries()) {
    const fp = sourceMap[reel].mediaFilePath;
    if (!byFile.has(fp)) byFile.set(fp, { mediaFilePath: fp, spec: sourceMap[reel].spec, cuts: [] });
    byFile.get(fp).cuts.push(...cuts);
  }
  const media = [...byFile.values()];

  // Author cross-dissolves where the geometry allows it (render-verified on
  // 19.1.3.7: an offline Sm2TiTransition over transplanted cross-source media
  // blends 124→181.6→234 at the cut — transitions carry no Fusion comp, so
  // the byte-keyed comp-cache law does not apply). A candidate is authorable
  // when a predecessor ends EXACTLY at its cut and both sides have handle
  // media for the centered span; anything else stays in droppedTransitions
  // with the reason.
  const transitions = [];
  for (const c of transitionCandidates) {
    const prev = placements.find((pl) => pl.track === c.track && pl.end === c.atFrame);
    if (!prev) {
      droppedTransitions.push({ index: c.index, type: c.type, duration: c.rawDuration, reason: 'no abutting predecessor at the cut' });
      continue;
    }
    // Handle math follows the actual span: `pre` frames before the cut need
    // incoming pre-roll (srcIn >= pre); `post` frames after need outgoing
    // tail media. A start-at-cut EDL dissolve needs NO incoming handle and a
    // FULL-duration outgoing tail.
    const pre = c.pre ?? c.durationFrames / 2;
    const post = c.durationFrames - pre;
    // OTIO/XMEML fades (E92): a zero-length BL leg MATERIALIZES to cover its
    // side of the span whenever the boundary shift alone won't grow it —
    // empty track renders black, so growth beyond the picture is
    // render-neutral, and placeTransition needs a physical item on each side
    // of the junction. (The CMX pre===0 form grows through the shift below.)
    if (isBL(prev.source) && prev.cutRef.durationFrames === 0 && pre > 0) {
      prev.cutRef.startFrame -= pre;
      prev.cutRef.durationFrames += pre;
      prev.start -= pre;
    }
    if (isBL(c.source) && c.incomingCutRef.durationFrames === 0 && post > 0) {
      c.incomingCutRef.durationFrames += post;
    }
    // A BL side has infinite handles: a Solid Color generator extends freely
    // in both directions (srcIn is already Infinity on BL candidates).
    const bHandle = c.srcIn >= pre;
    const aSpec = sourceMap[prev.source] && sourceMap[prev.source].spec;
    const aFrames = aSpec && Number(aSpec.frameCount);
    const aHandle = isBL(prev.source)
      ? true
      : (Number.isFinite(aFrames) ? prev.srcIn + prev.durationFrames + post <= aFrames : false);
    if (!bHandle || !aHandle) {
      droppedTransitions.push({
        index: c.index, type: c.type, duration: c.rawDuration,
        reason: `insufficient handles for a ${c.durationFrames}f dissolve spanning [cut-${pre}, cut+${post})` +
          `${bHandle ? '' : ` (incoming srcIn < ${pre})`}${aHandle ? '' : ` (outgoing tail media < ${post})`}`,
      });
      continue;
    }
    // Style mapping (all render-verified E61/E67/E68, midpoint-fingerprinted):
    // EDL W-codes and XMEML wipe effectids → the single wipe style Resolve's
    // own EDL importer maps every W-code to; XMEML dissolve-family effectids
    // → their PrettyType styles; anything unrecognized → plain dissolve
    // (never dropped — a blend at the right junction beats a hard cut).
    const raw = String(c.type || '');
    let kind = 'dissolve';
    if (/^W\d*/i.test(raw) || /wipe/i.test(raw)) kind = 'wipe';
    else if (/dip to color/i.test(raw)) kind = 'dip';
    else if (/non-additive/i.test(raw)) kind = 'non-additive';
    else if (/additive/i.test(raw)) kind = 'additive';
    else if (/fade to color/i.test(raw)) kind = 'dip'; // fade-to-color is erratic on the skeleton (measured); dip is the verified fade-to-black-and-back
    else if (/smooth cut/i.test(raw)) kind = 'smooth-cut';
    // EDGE LAW (E73, measured): the clip boundary must sit STRICTLY INSIDE
    // the transition span — an edge-aligned span (Start == boundary) renders
    // INERT. Resolve's own EDL importer solves the CMX start-at-cut case by
    // MOVING the cut half the duration and centering; reproduce exactly that:
    // extend the outgoing clip, trim the incoming head (source stays
    // aligned), and keep the RENDERED span [cut-pre, cut-pre+d) unchanged.
    let atFrame = c.atFrame;
    const spanStartAbs = c.atFrame - pre;
    if (c.explicitSpan && (pre === 0 || pre === c.durationFrames)) {
      // AAF CutPoint: the notional cut's offset within the overlap — shift
      // the reshaped boundary there when given (clamped strictly inside the
      // span, the edge law), else center.
      const cp = Number.isInteger(c.cutPoint) ? Math.min(c.durationFrames - 1, Math.max(1, c.cutPoint)) : c.durationFrames / 2;
      const shift = (pre === 0 ? 1 : -1) * cp;
      // The shift must leave BOTH legs with positive duration — a leg
      // shorter than the boundary shift cannot host its half of the span
      // (and a zero-length survivor would re-create the inert edge form).
      if (c.incomingCutRef.durationFrames - shift <= 0 || prev.cutRef.durationFrames + shift <= 0) {
        droppedTransitions.push({
          index: c.index, type: c.type, duration: c.rawDuration,
          reason: `a leg is shorter than the ${Math.abs(shift)}f boundary shift the edge-aligned span requires`,
        });
        continue;
      }
      prev.cutRef.durationFrames += shift;
      c.incomingCutRef.startFrame += shift;
      c.incomingCutRef.srcIn += shift;
      c.incomingCutRef.durationFrames -= shift;
      prev.end += shift;
      atFrame += shift;
    }
    transitions.push({
      track: c.track, atFrame, durationFrames: c.durationFrames,
      ...(kind === 'dissolve' ? {} : { type: kind }),
      ...(c.explicitSpan ? { startFrame: spanStartAbs } : {}),
    });
  }
  // Audio cross-fades, same geometry rules (render-verified on 19.1.3.7 via
  // the harvested cross-fade template: the highpass RMS ramps, not steps).
  for (const c of audioTransCandidates) {
    const prev = audioPlacements.find((pl) => pl.track === c.track && pl.end === c.atFrame);
    if (!prev) {
      droppedTransitions.push({ index: c.index, type: c.type, duration: c.rawDuration, trackType: 'audio', reason: 'no abutting predecessor at the cut' });
      continue;
    }
    const pre = c.pre ?? c.durationFrames / 2;
    const post = c.durationFrames - pre;
    const bHandle = c.srcIn >= pre;
    const aSpec = sourceMap[prev.source] && sourceMap[prev.source].spec;
    const aFrames = aSpec && Number(aSpec.frameCount);
    const aHandle = Number.isFinite(aFrames) ? prev.srcIn + prev.durationFrames + post <= aFrames : false;
    if (!bHandle || !aHandle) {
      droppedTransitions.push({
        index: c.index, type: c.type, duration: c.rawDuration, trackType: 'audio',
        reason: `insufficient handles for a ${c.durationFrames}f cross-fade spanning [cut-${pre}, cut+${post})` +
          `${bHandle ? '' : ` (incoming srcIn < ${pre})`}${aHandle ? '' : ` (outgoing tail media < ${post})`}`,
      });
      continue;
    }
    let atFrame = c.atFrame;
    const spanStartAbs = c.atFrame - pre;
    if (c.explicitSpan && (pre === 0 || pre === c.durationFrames)) {
      // AAF CutPoint: the notional cut's offset within the overlap — shift
      // the reshaped boundary there when given (clamped strictly inside the
      // span, the edge law), else center.
      const cp = Number.isInteger(c.cutPoint) ? Math.min(c.durationFrames - 1, Math.max(1, c.cutPoint)) : c.durationFrames / 2;
      const shift = (pre === 0 ? 1 : -1) * cp;
      prev.cutRef.durationFrames += shift;
      c.incomingCutRef.startFrame += shift;
      c.incomingCutRef.srcIn += shift;
      c.incomingCutRef.durationFrames -= shift;
      prev.end += shift;
      atFrame += shift;
    }
    transitions.push({
      track: c.track, atFrame, durationFrames: c.durationFrames, trackType: 'audio',
      ...(c.explicitSpan ? { startFrame: spanStartAbs } : {}),
    });
  }

  // Turnover markers (EDL * LOC: locators, OTIO Marker objects) → authored
  // timeline markers. Interchange colors map to the measured Resolve names;
  // unknown colors fall back to Blue. Frames are timeline-absolute like cuts.
  const markers = markerEvents
    .map((e) => ({
      frame: ORIGIN + (toTl(e.recIn, e.fps) - minRec),
      color: COLOR_MAP[String(e.color || '').toLowerCase()] || 'Blue',
      ...(e.name ? { name: e.name } : {}),
    }))
    .filter((m) => m.frame >= (preserveStartTimecode ? startFrame : DEFAULT_ORIGIN));

  // BL legs with surviving extent (a fade-in's zero-length slug GROWS through
  // the boundary shift; one that never met a dissolve stays zero and drops
  // out). srcIn was only scaffolding for the shift math — strip it.
  const elements = blackLegs
    .filter((el) => el.durationFrames > 0)
    .map(({ srcIn: _srcIn, ...rest }) => rest);

  return {
    spec: { timelineName, media, ...(preserveStartTimecode ? { startFrame } : {}), ...(markers.length ? { markers } : {}), ...(transitions.length ? { transitions } : {}), ...(elements.length ? { elements } : {}) },
    report: {
      videoEvents: vids.length,
      sources: media.length,
      audioEventsSkipped: audioSkipped,
      authoredMarkers: markers.length,
      audioChannelLegsMerged,
      authoredAudioEvents: audioPlacements.length,
      audioRetimesSkipped,
      ...(elements.length || audioBlackLegsSkipped ? {
        blackLegs: { authoredGenerators: elements.length, audioSilenceLegsSkipped: audioBlackLegsSkipped },
      } : {}),
      upperTrackCutsVideoOnly: placements.filter((pl) => pl.track > 1 && !isBL(pl.source)).length,
      flattenedRetimes,
      authoredRetimes,
      authoredTransitions: transitions,
      droppedTransitions,
      origin: startFrame,
    },
  };
}

export function eventsToEDL(events, opts = {}) {
  const fps = opts.fps || events.find((e) => e.fps)?.fps || 24;
  const vids = events.filter((e) => e.track !== 'A').sort((a, b) => (a.recIn ?? 0) - (b.recIn ?? 0));
  const lines = [`TITLE: ${opts.name || 'CONFORMED'}`, 'FCM: NON-DROP FRAME'];
  vids.forEach((e, i) => {
    const num = pad(i + 1, 3);
    const reel =
      String(e.source || 'AX')
        .replace(/\.[^.]+$/, '')
        .replace(/[^A-Za-z0-9]/g, '')
        .slice(0, 8)
        .toUpperCase() || 'AX';
    lines.push(
      `${num}  ${reel} V     C        ${framesToTc(e.srcIn, fps)} ${framesToTc(e.srcOut, fps)} ${framesToTc(e.recIn, fps)} ${framesToTc(e.recOut, fps)}`,
    );
    if ((e.speed ?? 100) !== 100 || e.reverse) {
      const play = (e.reverse ? -1 : 1) * (fps * ((e.speed ?? 100) / 100));
      lines.push(`M2   ${reel}       ${play.toFixed(1)}             ${framesToTc(e.srcIn, fps)}`);
    }
  });
  return lines.join('\n') + '\n';
}

const isRetimed = (e) => (e.speed ?? 100) !== 100 || Boolean(e.reverse);

/**
 * Which events lose their retime on the DRT target. The DRT clip schema
 * (vendor/drp-format/seq-container-builder.js) carries start / duration / in /
 * mediaFilePath / mediaStartTime / mediaFrameRate and nothing else — there is no per-clip
 * speed field to write a retime into, so a retimed event lands at 100% forward. OTIO
 * (LinearTimeWarp) and EDL (M2) do carry it; only DRT flattens.
 *
 * Reporting it is this cluster's skip-not-fake contract: a flattened retime that nobody is
 * told about is a timeline the caller believes is conformed and is not. `index` is the
 * event's position in the ORIGINAL events array, so a caller can map straight back.
 */
export function drtFlattenedRetimes(events) {
  const out = [];
  (events || []).forEach((e, index) => {
    if (!isRetimed(e)) return;
    out.push({
      index,
      recIn: e.recIn ?? 0,
      speed: e.speed ?? 100,
      reverse: Boolean(e.reverse),
      source: e.source || '',
      reason: 'DRT clip schema has no per-clip speed field — retime flattened to 100% forward',
    });
  });
  return out;
}

/** Build a buildDRT spec (Resolve-native .drt) from normalized events. */
export function eventsToDrtSpec(events, opts = {}) {
  const fps = opts.fps || events.find((e) => e.fps)?.fps || 24;
  const groups = byTrack(events);
  const mkTrack = (list) => ({
    clips: list.map((e) => ({ start: e.recIn ?? 0, duration: (e.recOut ?? 0) - (e.recIn ?? 0), in: e.srcIn ?? 0, mediaFilePath: e.source || '' })),
  });
  return {
    timelines: [
      {
        name: opts.name || 'Conformed',
        frameRate: fps,
        startTimecode: opts.startTimecode || '01:00:00:00',
        resolution: opts.resolution || '1920x1080',
        videoTracks: groups.V.length ? [mkTrack(groups.V)] : [],
        audioTracks: groups.A.length ? [mkTrack(groups.A)] : [],
      },
    ],
    metadata: { source: 'author-interchange', ...(opts.metadata || {}) },
  };
}

/**
 * Author `events` into `target` interchange. Returns { target, content?, spec?, bytes? }.
 * For 'drt', when outputPath is given the .drt bytes are written; otherwise the spec is returned.
 * The 'drt' target additionally returns `flattened` — ALWAYS an array, empty when the cut
 * carries no retimes, so a caller can tell "none to lose" from "this build is too old to say".
 */
export async function authorInterchange(events, target, opts = {}) {
  const t = String(target || 'otio').toLowerCase();
  if (t === 'otio') {
    const doc = eventsToOTIO(events, opts);
    return { target: 'otio', content: JSON.stringify(doc, null, 2), doc, mediaOriginAssumed: otioMediaOriginAssumed(events) };
  }
  if (t === 'edl') {
    return { target: 'edl', content: eventsToEDL(events, opts) };
  }
  if (t === 'drt') {
    const spec = eventsToDrtSpec(events, opts);
    const buf = await drt().buildDRT(spec);
    return { target: 'drt', spec, buffer: buf, bytes: buf.length, flattened: drtFlattenedRetimes(events) };
  }
  throw new Error(`authorInterchange: unknown target '${target}' (otio|edl|drt)`);
}

/**
 * verifyRoundtrip — assert that a re-EXPORT of an authored timeline matches
 * the interchange it was built from, normalizing the three cross-format
 * conventions measured on a live AAF→assemble→import→OTIO-export loop
 * (19.1.3.7):
 *   1. track labels: first tracks read 'V'/'A' in one format, 'V1'/'A1' in
 *      the other — canonicalized to the numbered form;
 *   2. source names: AAF mob name vs file basename ('rt_source_1' vs
 *      'rt_source_1.mov') — compared after stripping the extension,
 *      case-insensitively;
 *   3. source frames: Resolve's OTIO export is TIMECODE-ABSOLUTE while
 *      event lists are usually source-relative — a CONSTANT per-source
 *      offset is fitted from the first pair and every other pair must agree
 *      (the offset itself is reported, e.g. 86400 for a 01:00:00:00 source).
 * Record positions are min-anchored per side. Video events only (audio
 * channel legs merge by design).
 *
 * @returns {{pass:boolean, pairs:number, srcOffsets:Object, mismatches:Array}}
 */
export function verifyRoundtrip(inputEvents, exportedEvents, opts = {}) {
  const recTol = opts.recTol ?? 1;
  const srcTol = opts.srcTol ?? 1;
  const canonTrack = (t) => {
    const m = /^([VA])(\d+)?$/.exec(String(t || ''));
    return m ? `${m[1]}${m[2] || '1'}` : String(t);
  };
  // Basename + extension-stripped + case-folded: an OTIO turnover names
  // sources by target_url PATH while Resolve's re-export names them by file
  // basename (measured E100) — same file, different spelling.
  const canonSource = (x) => String(x || '').split(/[\\/]/).pop().replace(/\.[^.]+$/, '').toLowerCase();
  // Reel/tape aliases: an EDL names sources by REEL (CUTSRC) while the
  // re-export names them by file basename (cut_src) — the sourceMap that
  // drove the assemble is the authority linking the two. Keys and values
  // canonicalize exactly like event sources.
  const aliases = {};
  for (const [k, v] of Object.entries(opts.sourceAliases || {})) aliases[canonSource(k)] = canonSource(v);
  const mapSource = (s) => aliases[s] ?? s;
  // recOut > recIn: an EDL dissolve writes a ZERO-duration outgoing leg
  // before the D event — a pairing placeholder, never a rendered clip, and
  // no export reproduces it.
  const vids = (evts) => evts.filter((e) => /^V\d*$/.test(String(e.track)) && e.recIn != null && e.recOut != null && e.recOut > e.recIn);
  const audsOf = (evts) => evts.filter((e) => /^A\d*$/.test(String(e.track)) && e.recIn != null && e.recOut != null && e.recOut > e.recIn);
  const anchorOfSide = (evts) => {
    const v = vids(evts);
    if (v.length) return Math.min(...v.map((e) => e.recIn));
    const au = audsOf(evts);
    return au.length ? Math.min(...au.map((e) => e.recIn)) : 0;
  };
  const norm = (evts, pick = vids) => {
    const v = pick(evts);
    if (!v.length) return [];
    const off = anchorOfSide(evts);
    return v
      .map((e) => ({ track: canonTrack(e.track), source: mapSource(canonSource(e.source)), recIn: e.recIn - off, recOut: e.recOut - off, srcIn: e.srcIn ?? 0, speed: e.speed ?? 100, reverse: Boolean(e.reverse) }))
      .sort((a, b) => a.track.localeCompare(b.track) || a.recIn - b.recIn);
  };
  // FADES (E94): BL legs on the input side and the Solid Color generators a
  // fade conform authors for them are the same thing — BLACK. Black segments
  // are synthesized filler whose extents follow from the picture boundaries,
  // so the pairwise compare runs over PICTURE legs only; black is counted
  // informationally. And a fade's boundary-shift legitimately moves a
  // picture edge by up to the transition duration (matching Resolve's own
  // start-at-cut reshaping), so an edge within an input junction's fade
  // window is excused — and reported, not silently absorbed.
  const isBlackSeg = (e) => /^(bl|black|solid color)$/.test(e.source);
  const inAnchor = anchorOfSide(inputEvents);
  const junctionsFor = (trackRe) => inputEvents
    .filter((e) => trackRe.test(String(e.track)) && e.recIn != null && e.transition && e.transition.duration > 0)
    .map((e) => ({ frame: e.recIn - inAnchor, d: e.transition.duration }));
  const fadeReshapedBoundaries = [];
  const mismatches = [];
  const srcOffsets = {};
  const comparePairs = (a, b, junctions, trackType) => {
    const tt = trackType === 'audio' ? { trackType: 'audio' } : {};
    const inFadeWindow = (edgeIn, edgeExp) => junctions.some(
      (j) => Math.abs(edgeIn - j.frame) <= j.d && Math.abs(edgeExp - edgeIn) <= j.d,
    );
    if (a.length !== b.length) mismatches.push({ kind: 'count', ...tt, input: a.length, exported: b.length });
    const n = Math.min(a.length, b.length);
    for (let i = 0; i < n; i += 1) {
      const x = a[i], y = b[i];
      if (x.track !== y.track) { mismatches.push({ kind: 'track', ...tt, at: i, input: x.track, exported: y.track }); continue; }
      if (x.source !== y.source) { mismatches.push({ kind: 'source', ...tt, at: i, input: x.source, exported: y.source }); continue; }
      const inBad = Math.abs(x.recIn - y.recIn) > recTol;
      const outBad = Math.abs(x.recOut - y.recOut) > recTol;
      if (inBad || outBad) {
        const inExcused = !inBad || inFadeWindow(x.recIn, y.recIn);
        const outExcused = !outBad || inFadeWindow(x.recOut, y.recOut);
        if (inExcused && outExcused) {
          fadeReshapedBoundaries.push({ at: i, ...tt, source: x.source, input: [x.recIn, x.recOut], exported: [y.recIn, y.recOut] });
        } else {
          mismatches.push({ kind: 'record', ...tt, at: i, input: [x.recIn, x.recOut], exported: [y.recIn, y.recOut] });
          continue;
        }
      }
      // RETIMES (E95): a conform that lost its retime is a wrong timeline
      // that record/source geometry alone cannot catch (the record extent is
      // unchanged; only the playback rate is). Resolve's EXPORT_OTIO carries
      // an authored Sm2TimeMap back as LinearTimeWarp (measured live: 50%
      // in → time_scalar 0.5 out), so a speed/reverse mismatch is real drift.
      if (Math.abs((x.speed ?? 100) - (y.speed ?? 100)) > 0.5 || x.reverse !== y.reverse) {
        mismatches.push({
          kind: 'retime', ...tt, at: i, source: x.source,
          input: { speed: x.speed, reverse: x.reverse },
          exported: { speed: y.speed, reverse: y.reverse },
        });
        continue;
      }
      // A fade-reshaped head trims record AND source together (source stays
      // record-aligned), so the per-source constant offset is fitted net of
      // the record shift — otherwise a source cut both plain and faded would
      // read as a source-frames drift.
      const off = (y.srcIn - (y.recIn - x.recIn)) - x.srcIn;
      if (srcOffsets[x.source] === undefined) srcOffsets[x.source] = off;
      else if (Math.abs(off - srcOffsets[x.source]) > srcTol) {
        mismatches.push({ kind: 'source-frames', ...tt, at: i, source: x.source, expectedOffset: srcOffsets[x.source], gotOffset: off });
      }
    }
    return n;
  };

  const a0 = norm(inputEvents);
  const b0 = norm(exportedEvents);
  const a = a0.filter((e) => !isBlackSeg(e));
  const b = b0.filter((e) => !isBlackSeg(e));
  const blackSegments = { input: a0.length - a.length, exported: b0.length - b.length };
  const n = comparePairs(a, b, junctionsFor(/^V\d*$/), 'video');

  // AUDIO (E97): compared only when the INPUT declares audio events — a
  // video-only turnover legitimately re-exports with audio (the A1
  // convenience mirror), which is reported informationally, never failed.
  // AAF channel legs dedupe (same track/source/range arrives once per
  // channel); BL/silence legs merge out like video black.
  const dedupeAud = (list) => {
    const seen = new Set();
    return list.filter((e) => {
      const k = `${e.track}|${e.source}|${e.recIn}|${e.recOut}|${e.srcIn}`;
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    });
  };
  const aa = dedupeAud(norm(inputEvents, audsOf).filter((e) => !isBlackSeg(e)));
  const ba = dedupeAud(norm(exportedEvents, audsOf).filter((e) => !isBlackSeg(e)));
  let audio;
  if (aa.length) {
    audio = { input: aa.length, exported: ba.length, compared: true };
    comparePairs(aa, ba, junctionsFor(/^A\d*$/), 'audio');
  } else if (ba.length) {
    audio = { input: 0, exported: ba.length, compared: false, note: 'export-only audio (A1 convenience mirror) — not compared' };
  }
  // MARKERS (E88): compare track-'MARKER' pseudo-events, min-anchored to
  // each side's own VIDEO record origin like everything else. When the
  // re-export carries NO markers at all while the input has them, that is
  // reported as markersNotInExport rather than failed — several export
  // formats drop markers wholesale, and a missing capability is not a
  // conform drift. When both sides carry markers, they compare strictly.
  const mks = (evts, anchor) => evts
    .filter((e) => String(e.track) === 'MARKER' && e.recIn != null)
    .map((e) => ({ frame: e.recIn - anchor, name: e.name || '' }))
    .sort((x, y) => x.frame - y.frame);
  const anchorOf = (evts) => {
    const v = vids(evts);
    return v.length ? Math.min(...v.map((e) => e.recIn)) : 0;
  };
  const am = mks(inputEvents, anchorOf(inputEvents));
  const bm = mks(exportedEvents, anchorOf(exportedEvents));
  const markers = { input: am.length, exported: bm.length, mismatches: [] };
  let markersNotInExport = false;
  if (am.length && !bm.length) {
    markersNotInExport = true;
  } else {
    if (am.length !== bm.length) markers.mismatches.push({ kind: 'marker-count', input: am.length, exported: bm.length });
    for (let i = 0; i < Math.min(am.length, bm.length); i += 1) {
      if (Math.abs(am[i].frame - bm[i].frame) > recTol) {
        markers.mismatches.push({ kind: 'marker-frame', at: i, input: am[i].frame, exported: bm[i].frame });
      } else if (am[i].name && bm[i].name && am[i].name !== bm[i].name) {
        markers.mismatches.push({ kind: 'marker-name', at: i, input: am[i].name, exported: bm[i].name });
      }
    }
    mismatches.push(...markers.mismatches);
  }
  return {
    pass: mismatches.length === 0, pairs: n, srcOffsets, mismatches, markers,
    ...(markersNotInExport ? { markersNotInExport } : {}),
    ...(blackSegments.input || blackSegments.exported ? { blackSegments } : {}),
    ...(fadeReshapedBoundaries.length ? { fadeReshapedBoundaries } : {}),
    ...(audio ? { audio } : {}),
  };
}
