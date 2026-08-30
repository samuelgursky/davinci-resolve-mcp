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
 * event at the origin. Honesty ledger in the returned report: flattened
 * retimes (the template clip schema has no per-clip speed), dropped
 * transitions (treated as cuts at their boundary), and skipped audio events
 * (cuts carry linked A1 audio from their own source already).
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
  const { sourceMap, timelineName } = opts;
  if (!Array.isArray(events) || !events.length) {
    throw new TypeError('eventsToAssembleSpec: events must be a non-empty array');
  }
  if (!sourceMap || typeof sourceMap !== 'object') {
    throw new TypeError('eventsToAssembleSpec: sourceMap {reel: {mediaFilePath, spec}} is required');
  }
  const ORIGIN = 86400;
  const vids = events.filter((e) => e.track !== 'A' && e.recIn != null && e.recOut != null);
  const audioSkipped = events.length - vids.length;
  if (!vids.length) throw new Error('eventsToAssembleSpec: no video events with record ranges');

  const unmapped = [...new Set(vids.map((e) => e.source).filter((srcName) => !sourceMap[srcName]))];
  if (unmapped.length) {
    throw new Error(
      `eventsToAssembleSpec: unmapped source reel(s): ${unmapped.join(', ')} — ` +
      'every video event needs a sourceMap entry {mediaFilePath, spec}',
    );
  }

  const toTl = (frames, fps) => Math.round((frames * 24) / Math.round(fps || 24));
  const flattenedRetimes = [];
  const droppedTransitions = [];
  const perSource = new Map();
  const placements = [];

  const minRec = Math.min(...vids.map((e) => toTl(e.recIn, e.fps)));
  for (const e of vids) {
    const recIn = ORIGIN + (toTl(e.recIn, e.fps) - minRec);
    const recOut = ORIGIN + (toTl(e.recOut, e.fps) - minRec);
    const durationFrames = recOut - recIn;
    if (durationFrames <= 0) continue;
    if ((e.speed ?? 100) !== 100 || e.reverse) {
      flattenedRetimes.push({ index: e.index, source: e.source, speed: e.speed, reverse: !!e.reverse });
    }
    if (e.transition) {
      droppedTransitions.push({ index: e.index, type: e.transition.type, duration: e.transition.duration });
    }
    const cut = { startFrame: recIn, durationFrames, srcIn: toTl(e.srcIn ?? 0, e.fps) };
    placements.push({ start: recIn, end: recOut, index: e.index });
    if (!perSource.has(e.source)) perSource.set(e.source, []);
    perSource.get(e.source).push(cut);
  }

  placements.sort((a, b) => a.start - b.start);
  for (let i = 1; i < placements.length; i += 1) {
    if (placements[i].start < placements[i - 1].end) {
      throw new Error(
        `eventsToAssembleSpec: events ${placements[i - 1].index} and ${placements[i].index} ` +
        'overlap on the record track after frame conversion — a single V1 cannot hold both. ' +
        'Resolve the overlap upstream (transitions count as cuts at their boundary here).',
      );
    }
  }

  const media = [...perSource.entries()].map(([reel, cuts]) => ({
    mediaFilePath: sourceMap[reel].mediaFilePath,
    spec: sourceMap[reel].spec,
    cuts,
  }));

  return {
    spec: { timelineName, media },
    report: {
      videoEvents: vids.length,
      sources: media.length,
      audioEventsSkipped: audioSkipped,
      flattenedRetimes,
      droppedTransitions,
      origin: ORIGIN,
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
