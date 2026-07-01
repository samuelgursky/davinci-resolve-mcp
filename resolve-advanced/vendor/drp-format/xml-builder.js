/**
 * DaVinci Resolve Project (DRP) XML Generator Library
 *
 * This library provides functions to generate valid XML structures for DaVinci Resolve
 * project files (.drp). The DRP format is a ZIP archive containing XML files that
 * describe the project settings, media pool, timelines, and color grades.
 *
 * @module drp-generator/xml-builder
 */

const crypto = require('crypto');

// ============================================================================
// CONSTANTS
// ============================================================================

/**
 * Default project settings
 */
const DEFAULT_PROJECT_SETTINGS = {
  timelineFrameRate: 24.0,
  timelineResolutionWidth: 1920,
  timelineResolutionHeight: 1080,
  colorScience: 'DaVinci',
  inputColorSpace: 'Rec.709',
  timelineColorSpace: 'Rec.709',
  outputColorSpace: 'Rec.709',
  inputGamma: 'Gamma 2.4',
  outputGamma: 'Gamma 2.4'
};

/**
 * Frame rate encoding lookup table
 * Maps common frame rates to their hex-encoded double representation
 */
const FRAME_RATE_ENCODINGS = {
  23.976: '286b55e253f83d40',
  24.0: '0000000000003840',
  25.0: '0000000000003940',
  29.97: '286b55e253f93d40',
  30.0: '0000000000003e40',
  50.0: '0000000000004940',
  59.94: '286b55e253f9ed3f',
  60.0: '0000000000004e40'
};

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Generates a DaVinci Resolve-compatible UUID
 * Format: 32 hexadecimal characters (lowercase)
 *
 * @returns {string} UUID string
 *
 * @example
 * generateUUID()
 * // Returns: "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
 */
function generateUUID() {
  return crypto.randomBytes(16).toString('hex');
}

/**
 * Encodes a frame rate value to DaVinci's hex-encoded double format
 *
 * @param {number} fps - Frame rate (frames per second)
 * @returns {string} Hex-encoded frame rate
 *
 * @example
 * encodeFrameRate(24.0)
 * // Returns: "0000000000003840"
 */
function encodeFrameRate(fps) {
  // Check if we have a pre-encoded value
  if (FRAME_RATE_ENCODINGS[fps]) {
    return FRAME_RATE_ENCODINGS[fps];
  }

  // Encode as IEEE 754 double precision (8 bytes, little-endian)
  const buffer = Buffer.allocUnsafe(8);
  buffer.writeDoubleLE(fps, 0);
  return buffer.toString('hex');
}

/**
 * Escapes special XML characters
 *
 * @param {string} str - String to escape
 * @returns {string} XML-safe string
 *
 * @example
 * escapeXml('AT&T <video>')
 * // Returns: "AT&amp;T &lt;video&gt;"
 */
function escapeXml(str) {
  if (typeof str !== 'string') {
    return str;
  }

  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/**
 * Encodes a frame position as an integer
 *
 * @param {number} frame - Frame number
 * @returns {number} Encoded frame position
 */
function encodeFramePosition(frame) {
  return Math.floor(frame);
}

/**
 * Creates an In/Out point string with hex-encoded metadata
 * Format: "frameNumber|hexValue"
 *
 * @param {number} frame - Frame number
 * @param {string} [hexValue='949999999999c93f'] - Hex metadata value
 * @returns {string} In/Out point string
 *
 * @example
 * encodeInOutPoint(2377)
 * // Returns: "2377|949999999999c93f"
 */
function encodeInOutPoint(frame, hexValue = '949999999999c93f') {
  return `${encodeFramePosition(frame)}|${hexValue}`;
}

/**
 * Generates a timestamp in microseconds
 *
 * @returns {number} Timestamp in microseconds
 */
function generateTimestamp() {
  return Date.now() * 1000;
}

/**
 * Creates a minimal FieldsBlob binary structure
 * This is a hex-encoded binary blob containing key-value pairs
 *
 * @param {Object} fields - Key-value pairs to encode
 * @returns {string} Hex-encoded FieldsBlob
 */
function createFieldsBlob(fields = {}) {
  // Simplified implementation - in production, this would encode UTF-16LE strings
  // For now, return a minimal valid blob (version 0, 0 entries)
  const buffer = Buffer.alloc(8);
  buffer.writeUInt32LE(0, 0); // Version
  buffer.writeUInt32LE(0, 4); // Entry count
  return buffer.toString('hex');
}

/**
 * Builds XML element with attributes and children
 *
 * @param {string} tagName - XML element name
 * @param {Object} [attrs={}] - Element attributes
 * @param {string|Array<string>} [children=''] - Child elements or text content
 * @param {boolean} [selfClosing=false] - Whether to use self-closing tag
 * @returns {string} XML element string
 */
function buildXmlElement(tagName, attrs = {}, children = '', selfClosing = false) {
  let xml = `<${tagName}`;

  // Add attributes
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) {
      xml += ` ${key}="${escapeXml(String(value))}"`;
    }
  }

  if (selfClosing && !children) {
    xml += '/>';
  } else {
    xml += '>';

    if (Array.isArray(children)) {
      xml += '\n' + children.map(c => '  ' + c.split('\n').join('\n  ')).join('\n') + '\n';
    } else if (children) {
      xml += escapeXml(String(children));
    }

    xml += `</${tagName}>`;
  }

  return xml;
}

// ============================================================================
// PROJECT XML BUILDERS
// ============================================================================

/**
 * Builds the main project.xml structure
 *
 * @param {Object} settings - Project settings
 * @param {number} [settings.timelineFrameRate=24.0] - Timeline frame rate
 * @param {number} [settings.timelineResolutionWidth=1920] - Timeline width
 * @param {number} [settings.timelineResolutionHeight=1080] - Timeline height
 * @param {string} [settings.colorScience='DaVinci'] - Color science mode
 * @param {string} [settings.inputColorSpace='Rec.709'] - Input color space
 * @param {string} [settings.timelineColorSpace='Rec.709'] - Timeline color space
 * @param {string} [settings.outputColorSpace='Rec.709'] - Output color space
 * @param {string} [settings.inputGamma='Gamma 2.4'] - Input gamma/EOTF
 * @param {string} [settings.outputGamma='Gamma 2.4'] - Output gamma/EOTF
 * @param {string} [settings.projectName='Untitled Project'] - Project name
 * @returns {string} Complete project.xml content
 *
 * @example
 * const projectXml = buildProjectXml({
 *   timelineFrameRate: 24.0,
 *   timelineResolutionWidth: 3840,
 *   timelineResolutionHeight: 2160,
 *   projectName: 'My DRP Project'
 * });
 */
function buildProjectXml(settings = {}) {
  const config = { ...DEFAULT_PROJECT_SETTINGS, ...settings };
  const projectId = generateUUID();
  const timelineId = generateUUID();

  const frameRateHex = encodeFrameRate(config.timelineFrameRate);
  const fieldsBlob = createFieldsBlob({
    ColorScience: config.colorScience,
    InputColorSpace: config.inputColorSpace,
    TimelineColorSpace: config.timelineColorSpace,
    OutputColorSpace: config.outputColorSpace
  });

  // Build project structure
  const children = [
    buildXmlElement('Name', {}, config.projectName || 'Untitled Project'),
    buildXmlElement('UniqueId', {}, projectId),
    buildXmlElement('TimelineFrameRate', {}, frameRateHex),
    buildXmlElement('TimelineResolutionWidth', {}, config.timelineResolutionWidth),
    buildXmlElement('TimelineResolutionHeight', {}, config.timelineResolutionHeight),
    buildXmlElement('ColorScience', {}, config.colorScience),
    buildXmlElement('InputColorSpace', {}, config.inputColorSpace),
    buildXmlElement('TimelineColorSpace', {}, config.timelineColorSpace),
    buildXmlElement('OutputColorSpace', {}, config.outputColorSpace),
    buildXmlElement('InputGamma', {}, config.inputGamma),
    buildXmlElement('OutputGamma', {}, config.outputGamma),
    buildXmlElement('FieldsBlob', {}, fieldsBlob),
    buildXmlElement('CurrentTimeline', {}, timelineId)
  ];

  // P5.2 — optional project-level LUT slots. Only emit when supplied;
  // many projects have no LUTs and the elements should be absent rather
  // than empty. Slot names mirror Resolve XML conventions; if a real
  // Resolve fixture surfaces different names, add them to the parser's
  // recognized-slots list (drp-validator.extractProjectLUTRefs).
  if (config.inputLUT) {
    children.push(buildXmlElement('InputLUT', {}, config.inputLUT));
  }
  if (config.outputLUT) {
    children.push(buildXmlElement('OutputLUT', {}, config.outputLUT));
  }
  if (config.timelineLUT) {
    children.push(buildXmlElement('TimelineLUT', {}, config.timelineLUT));
  }
  if (config.monitorLUT) {
    children.push(buildXmlElement('MonitorLUT', {}, config.monitorLUT));
  }

  const projectXml = buildXmlElement('Sm2Project', { DbId: projectId }, children);

  return `<?xml version="1.0" encoding="UTF-8"?>\n${projectXml}`;
}

// ============================================================================
// SEQUENCE CONTAINER (TIMELINE) BUILDERS
// ============================================================================

/**
 * Builds a timeline clip (Sm2TiVideoClip) element
 *
 * @param {Object} clip - Clip data
 * @param {number} clip.start - Timeline start position (frames)
 * @param {number} clip.duration - Clip duration (frames)
 * @param {number} clip.in - Source in point (frames)
 * @param {number} [clip.out] - Source out point (frames, computed if not provided)
 * @param {string} clip.mediaRef - UUID reference to media pool clip
 * @param {string} clip.mediaFilePath - Path to source media file
 * @param {number} [clip.mediaStartTime=0] - Media start time
 * @param {number} [clip.mediaFrameRate] - Media frame rate (defaults to timeline rate)
 * @param {Object} [clip.grade] - Grade/color correction data
 * @param {boolean} [clip.grade.hasCorrection=false] - Whether clip has color correction
 * @param {string} [clip.grade.body=''] - Hex-encoded grade protobuf data
 * @param {string} [clip.grade.versionName='Version 1'] - Grade version name
 * @returns {string} Sm2TiVideoClip XML element
 *
 * @example
 * const clipXml = buildTimelineClipXml({
 *   start: 86400,
 *   duration: 565,
 *   in: 2377,
 *   mediaRef: 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6',
 *   mediaFilePath: '/path/to/source.mov',
 *   mediaFrameRate: 24.0
 * });
 */
function buildTimelineClipXml(clip) {
  const clipId = generateUUID();
  const versionTableId = generateUUID();
  const versionId = generateUUID();

  const inPoint = encodeInOutPoint(clip.in);
  const outPoint = clip.out !== undefined
    ? encodeInOutPoint(clip.out)
    : encodeInOutPoint(clip.in + clip.duration);

  const mediaFrameRate = clip.mediaFrameRate
    ? encodeFrameRate(clip.mediaFrameRate)
    : encodeFrameRate(DEFAULT_PROJECT_SETTINGS.timelineFrameRate);

  const children = [
    buildXmlElement('Start', {}, encodeFramePosition(clip.start)),
    buildXmlElement('Duration', {}, encodeFramePosition(clip.duration)),
    buildXmlElement('In', {}, inPoint),
    buildXmlElement('Out', {}, outPoint),
    buildXmlElement('MediaRef', {}, clip.mediaRef),
    buildXmlElement('MediaFilePath', {}, clip.mediaFilePath),
    buildXmlElement('MediaStartTime', {}, clip.mediaStartTime || 0),
    buildXmlElement('MediaFrameRate', {}, mediaFrameRate),
    buildXmlElement('IsMarkedForCaching', {}, 'false'),
    buildXmlElement('IsForceConformed', {}, 'true')
  ];

  // Add grade version table if grade data is provided
  if (clip.grade) {
    const gradeVersionXml = buildGradeVersionXml({
      versionId,
      versionName: clip.grade.versionName || 'Version 1',
      hasCorrection: clip.grade.hasCorrection || false,
      body: clip.grade.body || ''
    });

    const versionTableXml = buildXmlElement(
      'ListMgt::LmVersionTable',
      { DbId: versionTableId },
      [
        buildXmlElement('VerType', {}, '0'),
        buildXmlElement('pActive', {}, versionId),
        buildXmlElement('Locals', {}, [gradeVersionXml])
      ]
    );

    children.push(buildXmlElement('pLmVerTable', {}, [versionTableXml]));
  }

  return buildXmlElement('Sm2TiVideoClip', { DbId: clipId }, children);
}

/**
 * Builds a grade version (ListMgt::LmVersion) element
 *
 * @param {Object} version - Grade version data
 * @param {string} version.versionId - UUID for this version
 * @param {string} [version.versionName='Version 1'] - Version name
 * @param {boolean} [version.hasCorrection=false] - Whether version has corrections
 * @param {string} [version.body=''] - Hex-encoded protobuf grade data
 * @param {number} [version.implVersion=1] - Implementation version
 * @param {boolean} [version.flatPassEnabled=false] - Flat pass enabled
 * @param {boolean} [version.rgbaOutputEnabled=false] - RGBA output enabled
 * @returns {string} ListMgt::LmVersion XML element
 */
function buildGradeVersionXml(version) {
  const children = [
    buildXmlElement('Name', {}, version.versionName || 'Version 1'),
    buildXmlElement('HasCorrection', {}, version.hasCorrection ? 'true' : 'false'),
    buildXmlElement('ImplVersion', {}, version.implVersion || 1),
    buildXmlElement('FlatPassEnabled', {}, version.flatPassEnabled ? 'true' : 'false'),
    buildXmlElement('RGBAOutputEnabled', {}, version.rgbaOutputEnabled ? 'true' : 'false')
  ];

  // Only add Body if there's actual grade data
  if (version.body) {
    children.push(buildXmlElement('Body', {}, version.body));
  }

  return buildXmlElement('ListMgt::LmVersion', { DbId: version.versionId }, children);
}

/**
 * Builds a track (Sm2TiTrack) element
 *
 * @param {Object} track - Track data
 * @param {Array<Object>} [track.clips=[]] - Array of clip objects
 * @param {number} [track.subType=0] - Track subtype
 * @param {number} [track.flags=0] - Track flags
 * @returns {string} Sm2TiTrack XML element
 */
function buildTrackXml(track) {
  const trackId = generateUUID();
  const fieldsBlob = createFieldsBlob();

  const clipElements = (track.clips || []).map(clip => buildTimelineClipXml(clip));

  const children = [
    buildXmlElement('FieldsBlob', {}, fieldsBlob),
    buildXmlElement('SubType', {}, track.subType || 0),
    buildXmlElement('Flags', {}, track.flags || 0),
    buildXmlElement('LayersVec', {}, [
      buildXmlElement('Items', {}, clipElements)
    ])
  ];

  return buildXmlElement('Sm2TiTrack', { DbId: trackId }, children);
}

/**
 * Builds a complete sequence container (timeline) XML file
 *
 * @param {Object} timeline - Timeline data
 * @param {string} [timeline.name='Timeline 1'] - Timeline name
 * @param {Array<Object>} [timeline.videoTracks=[]] - Array of video track objects
 * @param {Array<Object>} [timeline.audioTracks=[]] - Array of audio track objects
 * @param {Array<Object>} [timeline.subtitleTracks=[]] - Array of subtitle track objects
 * @returns {string} Complete sequence container XML content
 *
 * @example
 * const timelineXml = buildSeqContainerXml({
 *   name: 'Main Timeline',
 *   videoTracks: [{
 *     clips: [{
 *       start: 0,
 *       duration: 240,
 *       in: 0,
 *       mediaRef: 'abc123...',
 *       mediaFilePath: '/path/to/clip.mov'
 *     }]
 *   }]
 * });
 */
function buildSeqContainerXml(timeline) {
  const containerId = generateUUID();

  const videoTrackElements = (timeline.videoTracks || []).map(track => buildTrackXml(track));
  const audioTrackElements = (timeline.audioTracks || []).map(track => buildTrackXml(track));
  const subtitleTrackElements = (timeline.subtitleTracks || []).map(track => buildTrackXml(track));

  const children = [
    buildXmlElement('Name', {}, timeline.name || 'Timeline 1'),
    buildXmlElement('VideoTrackVec', {}, videoTrackElements),
    buildXmlElement('AudioTrackVec', {}, audioTrackElements),
    buildXmlElement('SubtitleTrackVec', {}, subtitleTrackElements)
  ];

  const containerXml = buildXmlElement('Sm2SequenceContainer', { DbId: containerId }, children);

  return `<?xml version="1.0" encoding="UTF-8"?>\n${containerXml}`;
}

// ============================================================================
// MEDIA POOL BUILDERS
// ============================================================================

/**
 * Builds a media pool video clip (Sm2MpVideoClip) element
 *
 * @param {Object} clip - Clip data
 * @param {string} clip.name - Clip name (usually filename)
 * @param {string} clip.filePath - Full path to media file
 * @param {number} [clip.frameRate] - Frame rate
 * @param {string} [clip.reelNumber=''] - Reel/tape number
 * @param {string} [clip.thumbnail=''] - Base64 or hex-encoded JPEG thumbnail
 * @returns {string} Sm2MpVideoClip XML element
 *
 * @example
 * const clipXml = buildMediaPoolVideoClipXml({
 *   name: 'shot_001.mov',
 *   filePath: '/media/footage/shot_001.mov',
 *   frameRate: 24.0,
 *   reelNumber: 'A001'
 * });
 */
function buildMediaPoolVideoClipXml(clip) {
  const clipId = generateUUID();
  const uniqueId = generateUUID();

  const frameRateHex = clip.frameRate
    ? encodeFrameRate(clip.frameRate)
    : encodeFrameRate(DEFAULT_PROJECT_SETTINGS.timelineFrameRate);

  const fieldsBlob = createFieldsBlob();

  const children = [
    buildXmlElement('Name', {}, clip.name),
    buildXmlElement('MediaFilePath', {}, clip.filePath),
    buildXmlElement('UniqueMediaPoolItemId', {}, uniqueId),
    buildXmlElement('MediaFrameRate', {}, frameRateHex),
    buildXmlElement('FieldsBlob', {}, fieldsBlob)
  ];

  if (clip.reelNumber) {
    children.push(buildXmlElement('MediaReelNumber', {}, clip.reelNumber));
  }

  if (clip.thumbnail) {
    const thumbnailXml = buildXmlElement('BtThumnail', {}, [
      buildXmlElement('Buffer', {}, clip.thumbnail)
    ]);
    children.push(buildXmlElement('Thumbnail', {}, [thumbnailXml]));
  }

  return buildXmlElement('Sm2MpVideoClip', { DbId: clipId }, children);
}

/**
 * Builds a media pool audio clip (Sm2MpAudioClip) element
 *
 * @param {Object} clip - Clip data
 * @param {string} clip.name - Clip name
 * @param {string} clip.filePath - Full path to media file
 * @returns {string} Sm2MpAudioClip XML element
 */
function buildMediaPoolAudioClipXml(clip) {
  const clipId = generateUUID();
  const uniqueId = generateUUID();
  const fieldsBlob = createFieldsBlob();

  const children = [
    buildXmlElement('Name', {}, clip.name),
    buildXmlElement('MediaFilePath', {}, clip.filePath),
    buildXmlElement('UniqueMediaPoolItemId', {}, uniqueId),
    buildXmlElement('FieldsBlob', {}, fieldsBlob)
  ];

  return buildXmlElement('Sm2MpAudioClip', { DbId: clipId }, children);
}

/**
 * Builds a media pool folder (Sm2MpFolder) element
 *
 * @param {Object} folder - Folder data
 * @param {string} folder.name - Folder name
 * @param {string} [folder.parentId=''] - Parent folder UUID
 * @param {Array<Object>} [folder.videoClips=[]] - Array of video clip objects
 * @param {Array<Object>} [folder.audioClips=[]] - Array of audio clip objects
 * @param {string} [folder.colorTag='FOLDER_COLOR_NONE'] - Folder color tag
 * @param {boolean} [folder.folded=false] - Whether folder is collapsed
 * @returns {string} Sm2MpFolder XML element
 */
function buildMediaPoolFolderXml(folder) {
  const folderId = generateUUID();
  const uniqueId = generateUUID();

  const children = [
    buildXmlElement('Name', {}, folder.name),
    buildXmlElement('UniqueMediaPoolItemId', {}, uniqueId),
    buildXmlElement('ColorTag', {}, folder.colorTag || 'FOLDER_COLOR_NONE'),
    buildXmlElement('Folded', {}, folder.folded ? 'true' : 'false')
  ];

  if (folder.parentId) {
    children.push(buildXmlElement('MpFolder', {}, folder.parentId));
  }

  // Add media clips
  const mediaElements = [];

  (folder.videoClips || []).forEach(clip => {
    mediaElements.push(buildMediaPoolVideoClipXml(clip));
  });

  (folder.audioClips || []).forEach(clip => {
    mediaElements.push(buildMediaPoolAudioClipXml(clip));
  });

  if (mediaElements.length > 0) {
    children.push(buildXmlElement('MediaVec', {}, mediaElements));
  } else {
    children.push(buildXmlElement('MediaVec', {}, '', true));
  }

  return buildXmlElement('Sm2MpFolder', { DbId: folderId }, children);
}

/**
 * Builds a complete media pool XML file (MpFolder.xml)
 *
 * @param {Object} pool - Media pool data
 * @param {string} [pool.name='Master'] - Root folder name
 * @param {Array<Object>} [pool.videoClips=[]] - Array of video clip objects
 * @param {Array<Object>} [pool.audioClips=[]] - Array of audio clip objects
 * @param {Array<Object>} [pool.subfolders=[]] - Array of subfolder objects
 * @returns {string} Complete MpFolder.xml content
 *
 * @example
 * const mediaPoolXml = buildMediaPoolXml({
 *   name: 'Master',
 *   videoClips: [
 *     { name: 'clip1.mov', filePath: '/path/clip1.mov', frameRate: 24.0 },
 *     { name: 'clip2.mov', filePath: '/path/clip2.mov', frameRate: 24.0 }
 *   ]
 * });
 */
function buildMediaPoolXml(pool) {
  const folderXml = buildMediaPoolFolderXml({
    name: pool.name || 'Master',
    videoClips: pool.videoClips || [],
    audioClips: pool.audioClips || [],
    colorTag: pool.colorTag,
    folded: pool.folded
  });

  return `<?xml version="1.0" encoding="UTF-8"?>\n${folderXml}`;
}

// ============================================================================
// ADVANCED BUILDERS
// ============================================================================

/**
 * Creates a minimal neutral grade body (protobuf)
 * This generates a basic uncompressed grade with default settings
 *
 * @param {number} [width=1920] - Frame width
 * @param {number} [height=1080] - Frame height
 * @returns {string} Hex-encoded grade protobuf
 */
function createNeutralGradeBody(width = 1920, height = 1080) {
  // This is a simplified implementation
  // In production, you'd use a proper protobuf encoder
  // Header pattern: 800a2d = uncompressed, 45-byte payload
  const header = '800a2d';

  // Field 2 (version = 1): tag 0x10, value 0x01
  const field2 = '1001';

  // Field 3 (nested message with resolution data)
  // This is simplified - real implementation would encode all fields
  const field3Tag = '1a';
  const field3Length = '22'; // 34 bytes

  // Encode width and height as varints
  const widthVarint = encodeVarint(width);
  const heightVarint = encodeVarint(height);

  // Unity value (1.0 as float): 0000803f
  const unity = '0d0000803f';

  const field3Data = `08${widthVarint}10${heightVarint}${unity}`;

  // Timestamp (Field 12)
  const timestamp = generateTimestamp();
  const timestampVarint = encodeVarint(timestamp);
  const field12 = `60${timestampVarint}`;

  return header + field2 + field3Tag + field3Length + field3Data + field12;
}

/**
 * Encodes a number as a protobuf varint
 *
 * @param {number} value - Number to encode
 * @returns {string} Hex-encoded varint
 */
function encodeVarint(value) {
  const bytes = [];
  while (value > 127) {
    bytes.push((value & 127) | 128);
    value >>>= 7;
  }
  bytes.push(value & 127);
  return Buffer.from(bytes).toString('hex');
}

/**
 * Builds a transition element (Sm2TiTransition)
 *
 * @param {Object} transition - Transition data
 * @param {string} [transition.type='Cross Dissolve'] - Transition type
 * @param {number} transition.start - Timeline start position
 * @param {number} transition.duration - Transition duration in frames
 * @param {number} [transition.alignmentType=1] - Alignment type (0=start, 1=center, 2=end)
 * @returns {string} Sm2TiTransition XML element
 */
function buildTransitionXml(transition) {
  const transitionId = generateUUID();

  const children = [
    buildXmlElement('PrettyType', {}, transition.type || 'Cross Dissolve'),
    buildXmlElement('Start', {}, encodeFramePosition(transition.start)),
    buildXmlElement('Duration', {}, encodeFramePosition(transition.duration)),
    buildXmlElement('AlignmentType', {}, transition.alignmentType || 1)
  ];

  return buildXmlElement('Sm2TiTransition', { DbId: transitionId }, children);
}

/**
 * Builds a Gallery.xml file structure
 *
 * @param {Object} gallery - Gallery data
 * @param {Array<Object>} [gallery.stills=[]] - Array of still objects
 * @returns {string} Complete Gallery.xml content
 */
function buildGalleryXml(gallery) {
  const galleryId = generateUUID();

  const children = [
    buildXmlElement('Name', {}, 'Gallery'),
    buildXmlElement('Stills', {}, '', true)
  ];

  const galleryXml = buildXmlElement('Sm2Gallery', { DbId: galleryId }, children);

  return `<?xml version="1.0" encoding="UTF-8"?>\n${galleryXml}`;
}

// ============================================================================
// EXPORTS
// ============================================================================

module.exports = {
  // Helper functions
  generateUUID,
  encodeFrameRate,
  escapeXml,
  encodeFramePosition,
  encodeInOutPoint,
  generateTimestamp,
  createFieldsBlob,
  buildXmlElement,

  // Project builders
  buildProjectXml,

  // Sequence/Timeline builders
  buildSeqContainerXml,
  buildTrackXml,
  buildTimelineClipXml,
  buildGradeVersionXml,
  buildTransitionXml,

  // Media pool builders
  buildMediaPoolXml,
  buildMediaPoolFolderXml,
  buildMediaPoolVideoClipXml,
  buildMediaPoolAudioClipXml,

  // Advanced builders
  createNeutralGradeBody,
  encodeVarint,
  buildGalleryXml,

  // Constants
  DEFAULT_PROJECT_SETTINGS,
  FRAME_RATE_ENCODINGS
};
