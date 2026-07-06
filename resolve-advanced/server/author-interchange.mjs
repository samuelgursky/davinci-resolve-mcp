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
 * Build an OTIO timeline doc (plain object) from normalized events. Inserts gaps so record
 * positions are exact; emits LinearTimeWarp for speed/reverse and Transition items where present.
 */
export function eventsToOTIO(events, opts = {}) {
  const fps = opts.fps || events.find((e) => e.fps)?.fps || 24;
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
          source_range: { OTIO_SCHEMA: 'TimeRange.1', duration: { OTIO_SCHEMA: 'RationalTime.1', value: recIn - rec, rate: fps } },
        });
        rec = recIn;
      }
      const recDur = (e.recOut ?? recIn) - recIn;
      const clip = {
        OTIO_SCHEMA: 'Clip.1',
        name: e.source || 'UNKNOWN',
        source_range: {
          OTIO_SCHEMA: 'TimeRange.1',
          start_time: { OTIO_SCHEMA: 'RationalTime.1', value: e.srcIn ?? 0, rate: e.fps || fps },
          duration: { OTIO_SCHEMA: 'RationalTime.1', value: recDur, rate: e.fps || fps },
        },
        media_reference: { OTIO_SCHEMA: 'ExternalReference.1', target_url: e.source || '' },
        effects: [],
        markers: [],
      };
      if ((e.speed ?? 100) !== 100 || e.reverse) {
        clip.effects.push({ OTIO_SCHEMA: 'LinearTimeWarp.1', name: 'Speed', time_scalar: (e.reverse ? -1 : 1) * ((e.speed ?? 100) / 100) });
      }
      if (e.transition) {
        children.push({
          OTIO_SCHEMA: 'Transition.1',
          transition_type: 'SMPTE_Dissolve',
          in_offset: { OTIO_SCHEMA: 'RationalTime.1', value: Math.ceil((e.transition.duration || 0) / 2), rate: fps },
          out_offset: { OTIO_SCHEMA: 'RationalTime.1', value: Math.floor((e.transition.duration || 0) / 2), rate: fps },
        });
      }
      children.push(clip);
      rec = recIn + recDur;
    }
    tracks.push({ OTIO_SCHEMA: 'Track.1', name: `${kind[0]}1`, kind, children });
  }
  return { OTIO_SCHEMA: 'Timeline.1', name: opts.name || 'Conformed', tracks: { OTIO_SCHEMA: 'Stack.1', name: 'tracks', children: tracks } };
}

/** Build a CMX3600 EDL string (cuts + M2 speed). Video events only, per EDL convention. */
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
 */
export async function authorInterchange(events, target, opts = {}) {
  const t = String(target || 'otio').toLowerCase();
  if (t === 'otio') {
    const doc = eventsToOTIO(events, opts);
    return { target: 'otio', content: JSON.stringify(doc, null, 2), doc };
  }
  if (t === 'edl') {
    return { target: 'edl', content: eventsToEDL(events, opts) };
  }
  if (t === 'drt') {
    const spec = eventsToDrtSpec(events, opts);
    const buf = await drt().buildDRT(spec);
    return { target: 'drt', spec, buffer: buf, bytes: buf.length };
  }
  throw new Error(`authorInterchange: unknown target '${target}' (otio|edl|drt)`);
}
