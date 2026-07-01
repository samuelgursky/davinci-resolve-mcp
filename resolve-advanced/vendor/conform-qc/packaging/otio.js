'use strict';

/**
 * package/otio.js — OTIO is the INTERNAL CANONICAL timeline (spec §12). Every
 * output format derives from it. Minimal OTIO-shaped JSON (Timeline → track →
 * clips with a source_range start frame); enough to round-trip the conformed
 * source positions, which is what the package must preserve.
 */

/** Conformed timeline -> OTIO JSON document. */
function toOtio(conformed) {
  const seq = conformed.sequence || {};
  return {
    OTIO_SCHEMA: 'Timeline.1',
    name: seq.name || 'conform',
    global_start_time: { value: 0, rate: seq.fps || 24 },
    tracks: {
      OTIO_SCHEMA: 'Stack.1',
      children: [
        {
          OTIO_SCHEMA: 'Track.1',
          kind: 'Video',
          children: conformed.clips.map((c) => ({
            OTIO_SCHEMA: 'Clip.1',
            name: c.source_basename || c.cutId || `clip${c.seqstart}`,
            source_range: {
              OTIO_SCHEMA: 'TimeRange.1',
              start_time: { value: c.sourceFrame, rate: seq.fps || 24 },
              duration: { value: (c.seqend || c.seqstart) - c.seqstart, rate: seq.fps || 24 },
            },
            media_reference: { OTIO_SCHEMA: 'ExternalReference.1', target_url: c.path || null },
            metadata: { conformQc: { sampleFrame: c.sampleFrame, scale: c.scale, seqstart: c.seqstart } },
          })),
        },
      ],
    },
  };
}

/** Read back the source frame per clip from an OTIO document (round-trip check). */
function readOtioSourceFrames(otio) {
  const track = otio.tracks.children[0];
  return track.children.map((c) => ({
    name: c.name,
    seqstart: c.metadata.conformQc.seqstart,
    sourceFrame: c.source_range.start_time.value,
  }));
}

module.exports = { toOtio, readOtioSourceFrames };
