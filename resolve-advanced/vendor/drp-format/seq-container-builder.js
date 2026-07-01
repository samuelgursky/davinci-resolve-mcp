/**
 * DaVinci Resolve SeqContainer XML Builder
 *
 * Generates SeqContainer XML files for DRP packages.
 * SeqContainers define timeline structure with tracks, clips, and markers.
 *
 * @module seq-container-builder
 */

const { generateUUID, buildXmlElement, encodeFrameRate, encodeInOutPoint } = require('./xml-builder');
const { encodeEffectFiltersBA } = require('./effect-encoder');
const { encodeRichEffectFiltersBA, buildRichFieldsBlob } = require('./rich-title-encoder');

/**
 * Build a complete SeqContainer XML file for DRP
 *
 * @param {Object} timeline - Timeline configuration
 * @param {string} timeline.name - Timeline name
 * @param {Array} timeline.videoTracks - Video track configurations
 * @param {Array} timeline.audioTracks - Audio track configurations
 * @param {Object} options - Additional options
 * @param {number} options.frameRate - Timeline frame rate
 * @param {string} options.startTimecode - Start timecode
 * @param {Array} options.markers - Timeline markers
 * @returns {string} Complete SeqContainer XML
 */
async function buildSeqContainerFile(timeline, options = {}) {
  const {
    frameRate = 24,
    startTimecode = '01:00:00:00',
    markers = [],
    resolution = '1920x1080',
  } = options;

  const containerId = generateUUID();
  const lockableBlobId = generateUUID();

  // Parse resolution
  const [width, height] = resolution.split('x').map(Number);

  // Build video tracks
  const videoTrackElements = (timeline.videoTracks || []).map((track, idx) =>
    buildTrackElement(track, 'video', idx, frameRate)
  );

  // Build Rich title tracks (async — zstd compression)
  const richTitleTrackElements = [];
  if (timeline.richTitleTracks && timeline.richTitleTracks.length > 0) {
    for (const track of timeline.richTitleTracks) {
      const el = await buildRichTitleTrackElement(track, frameRate);
      richTitleTrackElements.push(el);
    }
  }

  // Build audio tracks
  const audioTrackElements = (timeline.audioTracks || []).map((track, idx) =>
    buildTrackElement(track, 'audio', idx, frameRate)
  );

  // Build lockable blob with markers
  const lockableBlob = buildLockableBlobElement(markers, lockableBlobId, frameRate);

  // Calculate start frame from timecode
  const startFrame = timecodeToFrames(startTimecode, frameRate);

  // Combine video tracks: standard video tracks first, then Rich title tracks
  const allVideoTrackElements = [...videoTrackElements, ...richTitleTrackElements];

  const children = [
    buildXmlElement('Name', {}, timeline.name || 'Timeline 1'),
    buildXmlElement('UniqueId', {}, containerId),
    buildXmlElement('StartFrame', {}, String(startFrame)),
    buildXmlElement('StartTC', {}, startTimecode),
    buildXmlElement('FrameRate', {}, encodeFrameRate(frameRate)),
    buildXmlElement('ResolutionWidth', {}, String(width || 1920)),
    buildXmlElement('ResolutionHeight', {}, String(height || 1080)),
    buildXmlElement('VideoTrackVec', {}, allVideoTrackElements),
    buildXmlElement('AudioTrackVec', {}, audioTrackElements),
    buildSubtitleTrackVec(timeline.subtitleTracks, frameRate),
    lockableBlob,
  ];

  const seqContainer = buildXmlElement('Sm2SequenceContainer', { DbId: containerId }, children);

  return `<?xml version="1.0" encoding="UTF-8"?>\n${seqContainer}`;
}

/**
 * Build a track element with clips
 *
 * @param {Object} track - Track configuration
 * @param {string} trackType - 'video' or 'audio'
 * @param {number} trackIndex - Track index
 * @param {number} frameRate - Frame rate
 * @returns {string} Track XML element
 */
function buildTrackElement(track, trackType, trackIndex, frameRate) {
  const trackId = generateUUID();

  const clipElements = (track.clips || []).map((clip) =>
    buildClipElement(clip, trackType, frameRate)
  );

  const children = [
    buildXmlElement('FieldsBlob', {}, '0000000000000000'),
    buildXmlElement('SubType', {}, '0'),
    buildXmlElement('Flags', {}, '0'),
    buildXmlElement('LayersVec', {}, [buildXmlElement('Items', {}, clipElements)]),
  ];

  const tagName = trackType === 'video' ? 'Sm2TiVideoTrack' : 'Sm2TiAudioTrack';
  return buildXmlElement(tagName, { DbId: trackId }, children);
}

/**
 * Build a clip element
 *
 * @param {Object} clip - Clip data
 * @param {string} trackType - 'video' or 'audio'
 * @param {number} frameRate - Frame rate
 * @returns {string} Clip XML element
 */
function buildClipElement(clip, trackType, frameRate) {
  // Check if this is a compound clip
  if (clip.isCompoundClip || (clip.children && clip.children.length > 0)) {
    return buildCompoundClipXml(clip, { trackType, frameRate });
  }

  const clipId = generateUUID();

  const inPoint = encodeInOutPoint(clip.in || 0);
  const outPoint = encodeInOutPoint((clip.in || 0) + (clip.duration || 0));

  const children = [
    buildXmlElement('Start', {}, String(clip.start || 0)),
    buildXmlElement('Duration', {}, String(clip.duration || 0)),
    buildXmlElement('In', {}, inPoint),
    buildXmlElement('Out', {}, outPoint),
    buildXmlElement('MediaRef', {}, clip.mediaRef || generateUUID()),
    buildXmlElement('MediaFilePath', {}, clip.mediaFilePath || ''),
    buildXmlElement('MediaStartTime', {}, String(clip.mediaStartTime || 0)),
    buildXmlElement('MediaFrameRate', {}, encodeFrameRate(clip.mediaFrameRate || frameRate)),
    buildXmlElement('IsMarkedForCaching', {}, 'false'),
    buildXmlElement('IsForceConformed', {}, 'true'),
  ];

  // Add grade if present
  if (clip.grade?.body) {
    const gradeVersionXml = buildGradeVersionElement(clip.grade);
    children.push(buildXmlElement('pLmVerTable', {}, [gradeVersionXml]));
  }

  const tagName = trackType === 'video' ? 'Sm2TiVideoClip' : 'Sm2TiAudioClip';
  return buildXmlElement(tagName, { DbId: clipId }, children);
}

/**
 * Build a compound clip XML element (Sm2TiCompoundClip)
 *
 * Compound clips contain an inner timeline with their own video/audio tracks.
 * The structure includes:
 * - Start, Duration, In, Out - timeline positioning
 * - InnerTimeline - nested timeline with VideoTrackVec and AudioTrackVec
 *
 * @param {Object} compoundClip - Compound clip data
 * @param {number} compoundClip.start - Timeline start position (frames)
 * @param {number} compoundClip.duration - Clip duration (frames)
 * @param {number} [compoundClip.in=0] - Source in point (frames)
 * @param {Array} compoundClip.children - Array of child clips
 * @param {string} [compoundClip.name] - Compound clip name
 * @param {Object} options - Additional options
 * @param {string} [options.trackType='video'] - Parent track type
 * @param {number} [options.frameRate=24] - Frame rate
 * @returns {string} Sm2TiCompoundClip XML element
 *
 * @example
 * const compoundXml = buildCompoundClipXml({
 *   start: 0,
 *   duration: 500,
 *   in: 0,
 *   children: [
 *     { start: 0, duration: 250, trackType: 'video', mediaFilePath: '/path/clip1.mov' },
 *     { start: 250, duration: 250, trackType: 'video', mediaFilePath: '/path/clip2.mov' }
 *   ]
 * }, { frameRate: 24 });
 */
function buildCompoundClipXml(compoundClip, options = {}) {
  const { trackType = 'video', frameRate = 24 } = options;
  const compoundId = generateUUID();

  const inPoint = encodeInOutPoint(compoundClip.in || 0);
  const outPoint = encodeInOutPoint((compoundClip.in || 0) + (compoundClip.duration || 0));

  // Separate children into video and audio tracks
  const childClips = compoundClip.children || compoundClip.compoundClipChildren || [];
  const videoChildren = childClips.filter(
    (c) => c.trackType === 'video' || !c.trackType
  );
  const audioChildren = childClips.filter((c) => c.trackType === 'audio');

  // Build inner video track elements
  const videoTrackElements = [];
  if (videoChildren.length > 0) {
    const videoClipElements = videoChildren.map((child) =>
      buildInnerClipElement(child, 'video', frameRate)
    );
    const videoTrack = buildXmlElement('Sm2TiVideoTrack', { DbId: generateUUID() }, [
      buildXmlElement('FieldsBlob', {}, '0000000000000000'),
      buildXmlElement('SubType', {}, '0'),
      buildXmlElement('Flags', {}, '0'),
      buildXmlElement('LayersVec', {}, [buildXmlElement('Items', {}, videoClipElements)]),
    ]);
    videoTrackElements.push(videoTrack);
  }

  // Build inner audio track elements
  const audioTrackElements = [];
  if (audioChildren.length > 0) {
    const audioClipElements = audioChildren.map((child) =>
      buildInnerClipElement(child, 'audio', frameRate)
    );
    const audioTrack = buildXmlElement('Sm2TiAudioTrack', { DbId: generateUUID() }, [
      buildXmlElement('FieldsBlob', {}, '0000000000000000'),
      buildXmlElement('SubType', {}, '0'),
      buildXmlElement('Flags', {}, '0'),
      buildXmlElement('LayersVec', {}, [buildXmlElement('Items', {}, audioClipElements)]),
    ]);
    audioTrackElements.push(audioTrack);
  }

  // Build InnerTimeline element
  const innerTimelineChildren = [
    buildXmlElement('VideoTrackVec', {}, videoTrackElements),
    buildXmlElement('AudioTrackVec', {}, audioTrackElements),
  ];
  const innerTimeline = buildXmlElement('InnerTimeline', {}, innerTimelineChildren);

  // Build compound clip children
  const compoundChildren = [
    buildXmlElement('Start', {}, String(compoundClip.start || 0)),
    buildXmlElement('Duration', {}, String(compoundClip.duration || 0)),
    buildXmlElement('In', {}, inPoint),
    buildXmlElement('Out', {}, outPoint),
    innerTimeline,
  ];

  // Add name if present
  if (compoundClip.name || compoundClip.clipName) {
    compoundChildren.unshift(
      buildXmlElement('Name', {}, compoundClip.name || compoundClip.clipName)
    );
  }

  return buildXmlElement('Sm2TiCompoundClip', { DbId: compoundId }, compoundChildren);
}

/**
 * Build an inner clip element for compound clip children
 *
 * @param {Object} clip - Child clip data
 * @param {string} trackType - 'video' or 'audio'
 * @param {number} frameRate - Frame rate
 * @returns {string} Clip XML element
 */
function buildInnerClipElement(clip, trackType, frameRate) {
  const clipId = generateUUID();

  // Handle different property naming conventions from storage
  const start = clip.start || clip.startFrame || 0;
  const duration = clip.duration || clip.durationFrames || 0;
  const inFrame = clip.in !== undefined ? clip.in : start;
  const mediaPath = clip.mediaFilePath || clip.sourceFile || '';

  const inPoint = encodeInOutPoint(inFrame);
  const outPoint = encodeInOutPoint(inFrame + duration);

  const children = [
    buildXmlElement('Start', {}, String(start)),
    buildXmlElement('Duration', {}, String(duration)),
    buildXmlElement('In', {}, inPoint),
    buildXmlElement('Out', {}, outPoint),
    buildXmlElement('MediaRef', {}, clip.mediaRef || generateUUID()),
    buildXmlElement('MediaFilePath', {}, mediaPath),
    buildXmlElement('MediaStartTime', {}, String(clip.mediaStartTime || 0)),
    buildXmlElement('MediaFrameRate', {}, encodeFrameRate(clip.mediaFrameRate || frameRate)),
    buildXmlElement('IsMarkedForCaching', {}, 'false'),
    buildXmlElement('IsForceConformed', {}, 'true'),
  ];

  // Add clip name if available
  if (clip.clipName || clip.name) {
    children.unshift(buildXmlElement('Name', {}, clip.clipName || clip.name));
  }

  const tagName = trackType === 'video' ? 'Sm2TiVideoClip' : 'Sm2TiAudioClip';
  return buildXmlElement(tagName, { DbId: clipId }, children);
}

/**
 * Build grade version element
 */
function buildGradeVersionElement(grade) {
  const versionId = generateUUID();
  const tableId = generateUUID();

  const versionChildren = [
    buildXmlElement('Name', {}, grade.versionName || 'Version 1'),
    buildXmlElement('HasCorrection', {}, grade.hasCorrection ? 'true' : 'false'),
    buildXmlElement('ImplVersion', {}, '1'),
    buildXmlElement('FlatPassEnabled', {}, 'false'),
    buildXmlElement('RGBAOutputEnabled', {}, 'false'),
  ];

  if (grade.body) {
    versionChildren.push(buildXmlElement('Body', {}, grade.body));
  }

  const version = buildXmlElement('ListMgt::LmVersion', { DbId: versionId }, versionChildren);

  return buildXmlElement('ListMgt::LmVersionTable', { DbId: tableId }, [
    buildXmlElement('VerType', {}, '0'),
    buildXmlElement('pActive', {}, versionId),
    buildXmlElement('Locals', {}, [version]),
  ]);
}

/**
 * Build lockable blob element with markers
 */
function buildLockableBlobElement(markers, blobId, frameRate) {
  // If no markers, return simple empty blob
  if (!markers || markers.length === 0) {
    return buildXmlElement('Sm2SequenceLockableBlob', { DbId: blobId }, [
      buildXmlElement('FieldsBlob', {}, '0000000100000000'),
    ]);
  }

  // Build marker protobuf (simplified - actual markers would need full encoding)
  // For now, return minimal structure that DaVinci can parse
  const fieldsBlobHex = buildMarkersFieldsBlob(markers, frameRate);

  return buildXmlElement('Sm2SequenceLockableBlob', { DbId: blobId }, [
    buildXmlElement('FieldsBlob', {}, fieldsBlobHex),
  ]);
}

/**
 * Build markers FieldsBlob hex string
 * This is a simplified implementation - full marker encoding is complex
 */
function buildMarkersFieldsBlob(markers, frameRate) {
  // Minimal FieldsBlob structure: version (4 bytes) + field count (4 bytes)
  // For full marker support, use marker-encoder.js with ZSTD compression
  return '0000000100000000';
}

/**
 * Convert timecode to frames
 */
function timecodeToFrames(timecode, fps = 24) {
  if (!timecode || typeof timecode !== 'string') return 0;

  const parts = timecode.split(':').map(Number);
  if (parts.length !== 4) return 0;

  const [hh, mm, ss, ff] = parts;
  return hh * 3600 * fps + mm * 60 * fps + ss * fps + ff;
}

// =============================================================================
// SUBTITLE TRACK / CLIP BUILDERS
// =============================================================================

/**
 * Build the SubtitleTrackVec element, handling empty and populated cases.
 *
 * @param {Array} [subtitleTracks] - Array of subtitle track configs
 * @param {number} frameRate - Timeline frame rate
 * @returns {string} SubtitleTrackVec XML element
 */
function buildSubtitleTrackVec(subtitleTracks, frameRate) {
  if (!subtitleTracks || subtitleTracks.length === 0) {
    return buildXmlElement('SubtitleTrackVec', {}, []);
  }
  const trackElements = subtitleTracks.map(t =>
    buildSubtitleTrackElement(t, frameRate)
  );
  return buildXmlElement('SubtitleTrackVec', {}, trackElements);
}

/**
 * Build a subtitle track element (Sm2TiSubtitleTrack) wrapping Sm2TiGenerator clips.
 *
 * @param {Object} track - Subtitle track config
 * @param {string} [track.name='Subtitle Track 1'] - Track name
 * @param {Array} track.clips - Array of subtitle node configs (from adapter.js)
 * @param {number} frameRate - Timeline frame rate
 * @returns {string} Sm2TiSubtitleTrack XML element
 */
function buildSubtitleTrackElement(track, frameRate) {
  const trackId = generateUUID();

  const clipElements = (track.clips || []).map(node =>
    buildSubtitleClipElement(node, frameRate)
  );

  const children = [
    buildXmlElement('FieldsBlob', {}, '0000000000000000'),
    buildXmlElement('UserDefinedName', {}, track.name || 'Subtitle Track 1'),
    buildXmlElement('Items', {}, clipElements),
  ];

  return buildXmlElement('Sm2TiSubtitleTrack', { DbId: trackId }, children);
}

/**
 * Build a single subtitle clip element (Sm2TiGenerator) for the DRP format.
 * This is the inverse of parseCaptionClip() in drp-parser.js.
 *
 * @param {Object} node - Subtitle node config
 * @param {string} node.text - Subtitle text
 * @param {number} node.startFrame - Start frame on timeline
 * @param {number} node.durationFrames - Duration in frames
 * @param {number} [node.panX=0] - Horizontal position
 * @param {number} [node.panY=-0.38] - Vertical position
 * @param {number} [node.zoomX=1.0] - Horizontal zoom
 * @param {number} [node.zoomY=1.0] - Vertical zoom
 * @param {number} frameRate - Timeline frame rate
 * @returns {string} Sm2TiGenerator XML element
 */
function buildSubtitleClipElement(node, frameRate) {
  const clipId = generateUUID();

  // Build EffectFiltersBA for position — uses the existing effect encoder
  const effectHex = encodeEffectFiltersBA({
    panX: node.panX || 0,
    panY: node.panY != null ? node.panY : -0.38,
    zoomX: node.zoomX || 1.0,
    zoomY: node.zoomY || 1.0,
  });

  const children = [
    buildXmlElement('Name', {}, node.text || ''),
    buildXmlElement('Start', {}, String(node.startFrame || 0)),
    buildXmlElement('Duration', {}, String(node.durationFrames || 0)),
    buildXmlElement('PrettyType', {}, 'Subtitle'),
    buildXmlElement('RenderTextEnabled', {}, 'true'),
    buildXmlElement('EffectFiltersBA', {}, effectHex),
  ];

  return buildXmlElement('Sm2TiGenerator', { DbId: clipId }, children);
}

// =============================================================================
// RICH TITLE (PrettyType=Rich) TRACK / CLIP BUILDERS
// =============================================================================

/**
 * NumLayers FieldsBlob for video tracks.
 * Hex-encoded binary: version=1, 1 entry, key="NumLayers" (UTF-16LE), value=2 (u32LE)
 */
const NUMLAYERS_FIELDS_BLOB =
  '000000010000000100000012004e0075006d004c00610079006500720073000000020000000000';

/**
 * Build a single Rich title clip element (Sm2TiGenerator) for video tracks.
 *
 * Rich titles are the "Title" generator in Resolve's Edit > Titles > Basic Title.
 * Text, font, size, and color are encoded in zstd-compressed protobuf inside EffectFiltersBA.
 *
 * @param {Object} node - Rich title node config
 * @param {string} node.text - Title text content
 * @param {number} node.startFrame - Start frame on timeline
 * @param {number} node.durationFrames - Duration in frames
 * @param {Object} [node.options] - Font/style overrides (passed to encodeRichEffectFiltersBA)
 * @param {number} frameRate - Timeline frame rate
 * @returns {Promise<string>} Sm2TiGenerator XML element
 */
async function buildRichTitleClipElement(node, frameRate) {
  const clipId = generateUUID();

  // Build EffectFiltersBA with Rich title protobuf (zstd-compressed)
  const effectHex = await encodeRichEffectFiltersBA(node.text, node.options || {});

  // Build per-clip FieldsBlob
  const fieldsHex = buildRichFieldsBlob();

  const children = [
    buildXmlElement('FieldsBlob', {}, fieldsHex),
    buildXmlElement('PrettyType', {}, 'Rich'),
    buildXmlElement('Name', {}, 'Rich'),
    buildXmlElement('Start', {}, String(node.startFrame || 0)),
    buildXmlElement('Duration', {}, String(node.durationFrames || 0)),
    buildXmlElement('LinkedItemSync', {}, 'false'),
    buildXmlElement('WasDisbanded', {}, 'false'),
    buildXmlElement('MarkersBA', {}, ''),
    buildXmlElement('UiMemento', {}, '0'),
    buildXmlElement('Flags', {}, '0'),
    buildXmlElement('PriorityIndex', {}, '0'),
    buildXmlElement('EffectFiltersBA', {}, effectHex),
    buildXmlElement('ImportExportMetadataBA', {}, ''),
    buildXmlElement('RenderTextEnabled', {}, 'true'),
    buildXmlElement('RenderTextGanged', {}, 'true'),
    buildXmlElement('RenderTextPrefixed', {}, 'true'),
    buildXmlElement('In', {}, encodeInOutPoint(0)),
  ];

  return buildXmlElement('Sm2TiGenerator', { DbId: clipId }, children);
}

/**
 * Build a Rich title track element (Sm2TiTrack Type=0) for the video track vector.
 *
 * Rich title clips live on standard video tracks, not subtitle tracks.
 *
 * @param {Object} track - Track config
 * @param {string} [track.name] - Track name (optional)
 * @param {Array} track.clips - Array of Rich title node configs
 * @param {number} frameRate - Timeline frame rate
 * @returns {Promise<string>} Sm2TiTrack XML element (Type=0 video)
 */
async function buildRichTitleTrackElement(track, frameRate) {
  const trackId = generateUUID();

  // Build all clip elements (async due to zstd compression)
  const clipElements = [];
  for (const node of (track.clips || [])) {
    const el = await buildRichTitleClipElement(node, frameRate);
    clipElements.push(el);
  }

  const children = [
    buildXmlElement('FieldsBlob', {}, NUMLAYERS_FIELDS_BLOB),
    buildXmlElement('SubType', {}, '0'),
    buildXmlElement('Flags', {}, '0'),
    buildXmlElement('LayersVec', {}, [buildXmlElement('Items', {}, clipElements)]),
  ];

  return buildXmlElement('Sm2TiTrack', { DbId: trackId }, children);
}

/**
 * Build multiple SeqContainer files for a project with multiple timelines
 */
async function buildSeqContainerFiles(timelines, options = {}) {
  const results = [];
  for (const [idx, timeline] of timelines.entries()) {
    const content = await buildSeqContainerFile(timeline, {
      ...options,
      frameRate: timeline.frameRate || options.frameRate || 24,
      startTimecode: timeline.startTimecode || options.startTimecode || '01:00:00:00',
      markers: timeline.markers || options.markers || [],
    });
    results.push({ filename: `SeqContainer${idx + 1}.xml`, content });
  }
  return results;
}

module.exports = {
  buildSeqContainerFile,
  buildSeqContainerFiles,
  buildTrackElement,
  buildClipElement,
  buildCompoundClipXml,
  buildInnerClipElement,
  buildLockableBlobElement,
  buildSubtitleTrackElement,
  buildSubtitleClipElement,
  buildRichTitleClipElement,
  buildRichTitleTrackElement,
  timecodeToFrames,
};
