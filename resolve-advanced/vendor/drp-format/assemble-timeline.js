/**
 * assemble-timeline — build a full, importable Resolve project from a declarative spec by
 * composing the verified primitives (createEmptyProject + placeFusionTitle / placeGenerator /
 * placeTransition). This supersedes the legacy from-spec `buildDRP`, which emits an invented
 * schema Resolve won't import.
 *
 * Spec:
 *   {
 *     timelineName?: string,
 *     elements?: [
 *       { type: 'title',     track, startFrame, durationFrames?, text?, font?, style?, size?,
 *                            color?, vJustify?, hJustify? },
 *       { type: 'generator', track, startFrame, durationFrames?, generatorName? },
 *     ],
 *     transitions?: [ { track, atFrame, durationFrames? } ],  // need two abutting clips at atFrame
 *   }
 *
 * Returns { buffer, timelineName, startFrame }. startFrame is the timeline origin (86400) — place
 * elements at >= it (clips before the origin are dropped by Resolve on import).
 *
 * @module drp-format/assemble-timeline
 */

const { createEmptyProject, addMediaClip, DEFAULT_START_FRAME } = require('./author-project');
const { loadMediaTemplate, transplantMediaElement, insertMediaElement } = require('./media-template-cache');
const JSZip = require('jszip');
const { cutSourceIntoClips } = require('./cut-media');
const { buildConstantSpeedTimemapKeyed, buildFreezeTimemapKeyed } = require('./media-timemap');
const { encodeTimelineMarkersBlob } = require('./timeline-markers-blob');
const { placeSubtitles, parseSrt } = require('./place-subtitles');
const { placeCompound } = require('./place-compound');
const { randomUUID } = require('node:crypto');
const { placeFusionTitle } = require('./place-fusion-title');
const { placeGenerator } = require('./place-generator');
const { placeTransition } = require('./place-transition');

async function assembleTimeline(spec = {}) {
  const { timelineName, elements = [], transitions = [], media, templateVersion } = spec;
  // Timeline start (frames @24). The start timecode lives in ONE place — the
  // pool timeline clip's MediaExtents [startSeconds, durationSeconds]
  // double-LE pair (measured: patching it imports with the new start TC and
  // renders; no other non-cosmetic copy exists). Clips are absolute frames,
  // so a custom origin just moves the guard.
  const originFrame = spec.startFrame ?? DEFAULT_START_FRAME;
  if (!Number.isInteger(originFrame) || originFrame < 0) throw new TypeError('assembleTimeline: spec.startFrame must be a non-negative integer');
  if (!Array.isArray(elements)) throw new TypeError('assembleTimeline: elements must be an array');
  if (!Array.isArray(transitions)) throw new TypeError('assembleTimeline: transitions must be an array');

  let base;
  let mediaDescriptorState = 'none';
  if (media) {
    // Media authoring: cut one or MORE sources into placements. Every source
    // carries {mediaFilePath, spec, cuts}. Multi-source requires a native
    // media template CAPTURED for every source (capture-once transplant is
    // the only measured way authored media renders); single-source may fall
    // back to descriptor repoint, which imports but usually will not render.
    const sources = Array.isArray(media) ? media : [media];
    if (!sources.length) throw new TypeError('assembleTimeline: media must not be empty');
    const caches = sources.map((src) => loadMediaTemplate(src.mediaFilePath));
    if (sources.length > 1) {
      const missing = sources.filter((src, i) => !caches[i]).map((src) => src.mediaFilePath);
      if (missing.length) {
        throw new Error(
          'assembleTimeline: multi-source authoring requires a captured native media template for EVERY source — ' +
          `missing for: ${missing.join(', ')}. Run media_pool.capture_media_template(path) with Resolve open for each.`,
        );
      }
    }
    const validateCuts = (src, label) => {
      const mediaSpec = src.spec;
      (src.cuts || []).forEach((cut, i) => {
        if (cut.startFrame < originFrame) {
          throw new RangeError(
            `assembleTimeline: ${label}.cuts[${i}].startFrame ${cut.startFrame} is before the timeline origin ${originFrame} — Resolve silently drops it on import`,
          );
        }
        if (mediaSpec && Number.isFinite(mediaSpec.frameCount) && Number.isFinite(mediaSpec.fps)) {
          // srcIn/duration are TIMELINE frames (24fps template); the media's
          // extent converts: frameCount / mediaFps × 24.
          const maxTimelineFrames = Math.floor((mediaSpec.frameCount / mediaSpec.fps) * 24);
          if ((cut.srcIn ?? 0) + cut.durationFrames > maxTimelineFrames) {
            throw new RangeError(
              `assembleTimeline: ${label}.cuts[${i}] reads past the media's end — (srcIn ?? 0) + durationFrames exceeds ${maxTimelineFrames} timeline frames (media ${mediaSpec.frameCount} frames @ ${mediaSpec.fps} fps on the 24fps template timeline)`,
            );
          }
        }
      });
    };
    sources.forEach((src, i) => validateCuts(src, sources.length > 1 ? `media[${i}]` : 'media'));

    base = await addMediaClip({
      mediaFile: sources[0].mediaFilePath, spec: sources[0].spec, timelineName, templateVersion,
    });
    base.startFrame = originFrame;

    // Transplant/insert native pool elements BEFORE cutting, so each cut can
    // reference its source's MediaRef.
    let zip = await JSZip.loadAsync(base.buffer);
    const mpPath = 'MediaPool/Master/MpFolder.xml';
    let mpXml = await zip.file(mpPath).async('string');
    const seqNames = Object.keys(zip.files).filter((n) => /SeqContainer\/.+\.xml$/.test(n) || /\/SeqContainer\d*\.xml$/.test(n));
    const seqXmls = [];
    for (const n of seqNames) seqXmls.push(await zip.file(n).async('string'));
    const mediaRefs = [];
    if (caches[0]) {
      const res = transplantMediaElement(mpXml, seqXmls, caches[0]);
      mpXml = res.mpXml;
      for (let i = 0; i < seqNames.length; i += 1) seqXmls[i] = res.seqXmls[i];
      mediaRefs[0] = caches[0].mediaRef;
      mediaDescriptorState = 'native-transplant';
    } else {
      mediaRefs[0] = null; // donor already points at the repointed entry
      mediaDescriptorState = 'repoint-fallback';
    }
    for (let i = 1; i < sources.length; i += 1) {
      mpXml = insertMediaElement(mpXml, caches[i].poolElement);
      mediaRefs[i] = caches[i].mediaRef;
    }
    zip.file(mpPath, mpXml);
    seqNames.forEach((n, i) => zip.file(n, seqXmls[i]));
    base.buffer = await zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });

    const allCuts = [];
    sources.forEach((src, i) => {
      (src.cuts || []).forEach((cut) => {
        const out = mediaRefs[i] ? { ...cut, mediaRef: mediaRefs[i] } : { ...cut };
        if (caches[i] && caches[i].mediaStartTime) out.mediaStartTime = caches[i].mediaStartTime;
        out.srcMeta = {
          name: src.mediaFilePath.split('/').pop(),
          mediaFilePath: src.mediaFilePath,
          fps: Math.round(src.spec.fps || 24),
          frameCount: src.spec.frameCount,
        };
        // Prefer cloning the source's own CAPTURED timeline clip: it carries
        // every native identity field (FieldsBlob, rate, timemap, TC base)
        // at once. Donor-clone + field rewrites is the fallback for caches
        // captured before clip elements were harvested.
        if (caches[i] && caches[i].videoClipElement) out.donorClipVideo = caches[i].videoClipElement;
        if (caches[i] && caches[i].audioClipElement) out.donorClipAudio = caches[i].audioClipElement;
        if (cut.freeze || cut.speed === 0) {
          // FREEZE frame (r19 keyed map harvested from a live EDL M2 000.0
          // import, E55; render-proven frozen). Holds source frame srcIn for
          // the whole cut. The frozen clip's <In> stays EMPTY; the position
          // rides in the map (seconds domain, XMax 60000 sentinel).
          if (cut.reverse) throw new RangeError('assembleTimeline: cut.freeze cannot combine with reverse');
          const fpsF = Math.round(src.spec.fps || 24);
          out.timemap = buildFreezeTimemapKeyed({
            freezeFrame: cut.srcIn ?? 0, sourceFrames: src.spec.frameCount, fps: fpsF,
            uniqueId: randomUUID(),
          }).toString('hex');
          out.emptyIn = true;
          delete out.freeze;
          delete out.speed;
        } else if (cut.reverse || (cut.speed !== undefined && cut.speed !== 1)) {
          // Constant-speed retime (forward only). The Sm2TimeMap spans the
          // whole source stretched by 1/speed; the clip windows into it with
          // RECORD-domain In/Duration (measured live on 19.1.3.7), so the
          // source-domain srcIn converts by /speed here.
          const speed = cut.speed ?? 1;
          if (!(speed > 0)) throw new RangeError('assembleTimeline: cut.speed must be > 0 (use cut.reverse for backwards)');
          const fps = Math.round(src.spec.fps || 24);
          out.timemap = buildConstantSpeedTimemapKeyed({
            speed, sourceFrames: src.spec.frameCount, fps,
            uniqueId: randomUUID(), reverse: !!cut.reverse,
          }).toString('hex');
          // Record-domain In. Forward: srcIn/speed. Reverse: the clip plays
          // source [srcIn, srcIn + dur*speed) BACKWARDS — the map descends
          // from the source tail, so In measures from the END:
          // (sourceFrames - srcIn - dur*speed)/speed  (measured live: In=0
          // on a reversed full-speed clip reads back source 191→143).
          out.srcIn = cut.reverse
            ? Math.round((src.spec.frameCount - (cut.srcIn ?? 0) - cut.durationFrames * speed) / speed)
            : Math.round((cut.srcIn ?? 0) / speed);
          delete out.speed;
          delete out.reverse;
        }
        allCuts.push(out);
      });
    });
    allCuts.sort((a, b) => a.startFrame - b.startFrame);
    if (allCuts.length) {
      const cutRes = await cutSourceIntoClips(base.buffer, { cuts: allCuts });
      base.buffer = cutRes.buffer;
    }
  } else {
    base = await createEmptyProject({ timelineName, templateVersion });
  }
  const { buffer: baseBuffer, timelineName: tlName, startFrame } = base;
  let buffer = baseBuffer;

  for (const [i, el] of elements.entries()) {
    if (!el || typeof el !== 'object') throw new TypeError(`assembleTimeline: elements[${i}] must be an object`);
    if (el.type === 'title') {
      ({ buffer } = await placeFusionTitle(buffer, {
        trackIndex: el.track, startFrame: el.startFrame, durationFrames: el.durationFrames,
        text: el.text, font: el.font, style: el.style, size: el.size, color: el.color,
        vJustify: el.vJustify, hJustify: el.hJustify, name: el.name, templateVersion,
      }));
    } else if (el.type === 'generator') {
      ({ buffer } = await placeGenerator(buffer, {
        generatorName: el.generatorName, trackIndex: el.track,
        startFrame: el.startFrame, durationFrames: el.durationFrames, templateVersion,
      }));
    } else {
      throw new Error(`assembleTimeline: elements[${i}] unknown type "${el.type}" (title|generator)`);
    }
  }

  for (const [i, tr] of transitions.entries()) {
    if (!tr || typeof tr !== 'object') throw new TypeError(`assembleTimeline: transitions[${i}] must be an object`);
    ({ buffer } = await placeTransition(buffer, {
      track: tr.track, atFrame: tr.atFrame, durationFrames: tr.durationFrames,
      trackType: tr.trackType || 'video',
    }));
  }

  // Pin the PARENT container id BEFORE any compound inserts an inner
  // container: entry listing is name-sorted, so an inner container can
  // alphabetically precede the parent and every later "first container"
  // lookup — the next compound's item, subtitles, markers — then targets
  // the compound's INNER timeline instead (measured: CMP_B landed inside
  // CMP_A; subtitles authored with a compound in the spec vanished into
  // the inner container and the imported timeline had no subtitle track).
  const zipPin = await JSZip.loadAsync(buffer);
  const parentEntryPin = Object.keys(zipPin.files).find((n) => !zipPin.files[n].dir && /SeqContainer\/.+\.xml$/.test(n));
  const parentContainerId = ((await zipPin.file(parentEntryPin).async('string')).match(/<Sm2SequenceContainer DbId="([^"]+)"/) || [])[1];

  // Compound clips: an empty nested timeline is spliced in from the
  // harvested donor shape, then its content is placed with the ORDINARY cuts
  // machinery targeting the inner container (inner origin is FRAME 0).
  // Inner cuts must reference files with captured native templates.
  if (Array.isArray(spec.compounds) && spec.compounds.length) {
    // Pool elements for compound-only sources (files not in spec.media).
    const specFiles = new Set((Array.isArray(media) ? media : media ? [media] : []).map((src) => src.mediaFilePath));
    const insertedExtra = new Set();
    const walkCompoundCuts = (comps) => (comps || []).flatMap((c) => [...(c.cuts || []), ...walkCompoundCuts(c.compounds)]);
    for (const cut of walkCompoundCuts(spec.compounds)) {
      const fp = cut.mediaFilePath;
      if (!fp || specFiles.has(fp) || insertedExtra.has(fp)) continue;
      const cache = loadMediaTemplate(fp);
      if (!cache) continue; // the per-cut refusal below names it properly
      const zipC = await JSZip.loadAsync(buffer);
      const mpP = 'MediaPool/Master/MpFolder.xml';
      zipC.file(mpP, insertMediaElement(await zipC.file(mpP).async('string'), cache.poolElement));
      buffer = await zipC.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
      insertedExtra.add(fp);
    }
    // Recursive: compounds nest (comp.compounds, frames inner-relative like
    // cuts). Depth-2 playback is RENDER-VERIFIED on 19.1.3.7 (E56, white 234
    // through two levels) — the historical depth-2 black was one missing key,
    // SequenceSetup, in the donor template's embedded-sequence blob. Depths
    // beyond 2 compose structurally but are not render-verified.
    const placeTree = async (comp, parentUuid, label) => {
      if (!comp || typeof comp !== 'object') throw new TypeError(`assembleTimeline: ${label} must be an object`);
      const res = await placeCompound(buffer, {
        name: comp.name,
        startFrame: comp.startFrame,
        durationFrames: comp.durationFrames,
        track: comp.track,
        timelineUuid: parentUuid,
      });
      buffer = res.buffer;
      const innerCuts = (comp.cuts || []).map((cut, i) => {
        if (!cut.mediaFilePath) throw new TypeError(`assembleTimeline: ${label}.cuts[${i}].mediaFilePath is required`);
        if (!Number.isInteger(cut.startFrame) || cut.startFrame < 0 || (cut.startFrame + (cut.durationFrames || 0)) > comp.durationFrames) {
          throw new RangeError(`assembleTimeline: ${label}.cuts[${i}] must sit inside [0, ${comp.durationFrames}) — inner frames are 0-based`);
        }
        const cache = loadMediaTemplate(cut.mediaFilePath);
        if (!cache) {
          throw new Error(`assembleTimeline: ${label}.cuts[${i}] — no captured native media template for ${cut.mediaFilePath}. Run media_pool.capture_media_template(path) with Resolve open.`);
        }
        if (!cache.videoClipElement) {
          throw new Error(`assembleTimeline: ${label}.cuts[${i}] — the media template for ${cut.mediaFilePath} predates native clip capture. Re-run media_pool.capture_media_template(path) with Resolve open.`);
        }
        const out = { ...cut, mediaRef: cache.mediaRef };
        delete out.mediaFilePath;
        if (cache.mediaStartTime) out.mediaStartTime = cache.mediaStartTime;
        out.donorClipVideo = cache.videoClipElement;
        if (cache.audioClipElement) out.donorClipAudio = cache.audioClipElement;
        return out;
      });
      if (innerCuts.length) {
        // The inner container has no donor items — clones come from the
        // captured native clip elements, so the template donor is unused.
        const cutRes = await cutSourceIntoClips(buffer, { cuts: innerCuts, timelineUuid: res.innerContainerId });
        buffer = cutRes.buffer;
      }
      for (const [cj, child] of (comp.compounds || []).entries()) {
        if (child && typeof child === 'object' && !Number.isInteger(child.startFrame)) {
          throw new TypeError(`assembleTimeline: ${label}.compounds[${cj}].startFrame must be an integer (INNER frames, 0-based)`);
        }
        await placeTree({ name: child.name || `Compound ${cj + 1}`, ...child }, res.innerContainerId, `${label}.compounds[${cj}]`);
      }
    };
    for (const [ci, comp] of spec.compounds.entries()) {
      await placeTree(
        { ...(comp && typeof comp === 'object' ? comp : {}), name: (comp && comp.name) || `Compound ${ci + 1}` },
        parentContainerId,
        `compounds[${ci}]`,
      );
    }
  }

  // Subtitles: plain Sm2TiGenerator items (text in <Name>, no blobs — the
  // cache law does not apply; the payload is API-visible after import).
  // spec.subtitles frames are timeline-ABSOLUTE; spec.subtitlesSrt is raw SRT
  // text whose cues anchor at the origin.
  let subtitles = Array.isArray(spec.subtitles) ? [...spec.subtitles] : [];
  if (typeof spec.subtitlesSrt === 'string' && spec.subtitlesSrt.length) {
    subtitles.push(...parseSrt(spec.subtitlesSrt, 24).map((c) => ({ ...c, startFrame: c.startFrame + originFrame })));
  }
  if (subtitles.length) {
    for (const sub of subtitles) {
      if (!Number.isInteger(sub.startFrame) || sub.startFrame < originFrame) {
        throw new RangeError(`assembleTimeline: subtitle at frame ${sub.startFrame} is before the timeline origin ${originFrame}`);
      }
    }
    ({ buffer } = await placeSubtitles(buffer, { subtitles, timelineUuid: parentContainerId }));
  }

  if (Array.isArray(spec.markers) && spec.markers.length) {
    // Timeline markers ride in project.xml as a Sm2SequenceLockableBlob whose
    // BlobOwner is the timeline's Sm2Sequence DbId (the uuid every track's
    // <Sequence> references). Encoder byte-exact vs a live 19.1.3.7 export.
    // Marker frames here are TIMELINE-ABSOLUTE for consistency with cuts;
    // the blob stores them start-relative.
    // Resolved against the PINNED parent container — a compound's inner
    // container also matches the "any SeqContainer entry" pattern, and
    // attaching the blob to the inner sequence hides every marker.
    const zipM = await JSZip.loadAsync(buffer);
    const seqNames = Object.keys(zipM.files).filter((n) => !zipM.files[n].dir && /SeqContainer\/.+\.xml$/.test(n));
    let seqXml2 = null;
    for (const n of seqNames) {
      const xmlN = await zipM.file(n).async('string');
      if (xmlN.includes(`<Sm2SequenceContainer DbId="${parentContainerId}"`)) { seqXml2 = xmlN; break; }
    }
    if (!seqXml2) throw new Error('assembleTimeline: pinned parent SeqContainer not found for markers');
    const seqIdM = (seqXml2.match(/<Sequence>([0-9a-f-]{36})<\/Sequence>/) || [])[1];
    if (!seqIdM) throw new Error('assembleTimeline: cannot find the Sm2Sequence id for markers');
    const rel = spec.markers.map((m) => {
      if (!Number.isInteger(m.frame) || m.frame < originFrame) {
        throw new RangeError(`assembleTimeline: marker frame ${m.frame} is before the timeline origin ${originFrame} (frames are timeline-absolute)`);
      }
      return { ...m, frame: m.frame - originFrame };
    });
    const blob = encodeTimelineMarkersBlob(rel);
    let pjX = await zipM.file('project.xml').async('string');
    const setM = pjX.match(/<LocableBlobSet>[\s\S]*?<\/LocableBlobSet>/);
    if (!setM) throw new Error('assembleTimeline: project.xml has no LocableBlobSet to hold markers');
    const el = `<Element>\n     <Sm2SequenceLockableBlob DbId="${randomUUID()}">\n      <FieldsBlob>${blob.toString('hex')}</FieldsBlob>\n      <BlobOwner>${seqIdM}</BlobOwner>\n      <DbSavedTime>0</DbSavedTime>\n     </Sm2SequenceLockableBlob>\n    </Element>\n   `;
    pjX = pjX.replace('</LocableBlobSet>', `${el}</LocableBlobSet>`);
    zipM.file('project.xml', pjX);
    buffer = await zipM.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  }

  if (originFrame !== DEFAULT_START_FRAME) {
    const zipF = await JSZip.loadAsync(buffer);
    const mpP = 'MediaPool/Master/MpFolder.xml';
    let mpF = await zipF.file(mpP).async('string');
    const tlBlocks = mpF.match(/<Sm2MpTimelineClip[\s\S]*?<\/Sm2MpTimelineClip>/g) || [];
    const tlBlock = tlBlocks.find((b) => b.includes(`<Name>${tlName}</Name>`)) || tlBlocks[0];
    if (!tlBlock) throw new Error('assembleTimeline: timeline pool clip not found for startFrame patch');
    const meM = tlBlock.match(/<MediaExtents>([0-9a-fA-F]*)<\/MediaExtents>/);
    if (!meM) throw new Error('assembleTimeline: timeline pool clip has no MediaExtents to patch');
    let maxEnd = originFrame;
    const collect = (arr) => (arr || []).forEach((x) => { const e = (x.startFrame ?? 0) + (x.durationFrames ?? 0); if (e > maxEnd) maxEnd = e; });
    (Array.isArray(media) ? media : media ? [media] : []).forEach((src) => collect(src.cuts));
    collect(elements);
    const me = Buffer.alloc(16);
    me.writeDoubleLE(originFrame / 24, 0);
    me.writeDoubleLE((maxEnd - originFrame) / 24, 8);
    mpF = mpF.replace(tlBlock, tlBlock.replace(meM[0], `<MediaExtents>${me.toString('hex')}</MediaExtents>`));
    zipF.file(mpP, mpF);
    buffer = await zipF.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  }

  return { buffer, timelineName: tlName, startFrame: originFrame, mediaDescriptor: mediaDescriptorState };
}

module.exports = { assembleTimeline };
