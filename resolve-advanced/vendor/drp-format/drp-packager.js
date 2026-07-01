/**
 * DaVinci Resolve Project Packager
 * Creates DRP files (ZIP archives) with proper structure
 */

const JSZip = require('jszip');
const { buildSeqContainerFile } = require('./seq-container-builder');
const { buildMpFolderFile } = require('./mp-folder-builder');

/**
 * Package timeline data into a DRP file
 * @param {string} projectXML - Project XML content
 * @param {Object} options - Additional options
 * @returns {Promise<Buffer>} DRP file as buffer
 */
async function packageDRP(projectXML, options = {}) {
  const {
    projectName = 'Untitled Project',
    includeMetadata = true
  } = options;

  const zip = new JSZip();

  // Add project.xml (required)
  zip.file('project.xml', projectXML);

  // Add metadata file if requested
  if (includeMetadata) {
    const metadata = {
      projectName,
      exportedAt: new Date().toISOString(),
      exportedBy: 'Bradford Operations',
      version: '1.0'
    };
    zip.file('metadata.json', JSON.stringify(metadata, null, 2));
  }

  // Generate ZIP buffer
  const buffer = await zip.generateAsync({
    type: 'nodebuffer',
    compression: 'DEFLATE',
    compressionOptions: {
      level: 6
    }
  });

  return buffer;
}

/**
 * Package a complete DRP file with all required components
 *
 * @param {Object} options - DRP configuration
 * @param {string} options.projectXml - Project XML content
 * @param {Array} options.timelines - Timeline configurations
 * @param {Object} options.mediaPool - Media pool configuration
 * @param {Object} options.metadata - Additional metadata
 * @returns {Promise<Buffer>} Complete DRP file as buffer
 */
async function packageFullDRP(options) {
  const {
    projectXml,
    timelines = [],
    mediaPool = null,
    metadata = {},
    includeProjectXml = true,
  } = options;

  const zip = new JSZip();

  // Add root project.xml (required for DRP, omitted for DRT).
  if (includeProjectXml) {
    if (!projectXml) {
      throw new Error('packageFullDRP: projectXml is required when includeProjectXml is true');
    }
    zip.file('project.xml', projectXml);
  }

  // Add metadata file
  if (Object.keys(metadata).length > 0) {
    zip.file('metadata.json', JSON.stringify({
      ...metadata,
      exportedAt: metadata.exportedAt || new Date().toISOString(),
      exportedFrom: 'Bradford Operations',
    }, null, 2));
  }

  // Create Primary1 folder for timeline data
  const primary = zip.folder('Primary1');

  // Add SeqContainer files for each timeline
  for (const [idx, timeline] of timelines.entries()) {
    const seqContainerXml = await buildSeqContainerFile(timeline, {
      frameRate: timeline.frameRate || 24,
      startTimecode: timeline.startTimecode || '01:00:00:00',
      markers: timeline.markers || [],
      resolution: timeline.resolution || '1920x1080',
    });
    primary.file(`SeqContainer${idx + 1}.xml`, seqContainerXml);
  }

  // Add MpFolder if media pool is provided
  if (mediaPool) {
    const mpFolderXml = buildMpFolderFile(mediaPool);
    primary.file('MpFolder.xml', mpFolderXml);
  }

  // Generate ZIP buffer with DEFLATE compression
  const buffer = await zip.generateAsync({
    type: 'nodebuffer',
    compression: 'DEFLATE',
    compressionOptions: {
      level: 6,
    },
  });

  return buffer;
}

/**
 * Validate DRP structure before packaging
 *
 * @param {Object} options - DRP configuration to validate
 * @returns {Array} Array of validation errors (empty if valid)
 */
function validateDRPConfig(options) {
  const errors = [];

  // projectXml is only required when we'll actually include it. DRT
  // builds pass includeProjectXml: false and don't supply one.
  if (options.includeProjectXml !== false && !options.projectXml) {
    errors.push('project.xml content is required');
  }

  if (!options.timelines || options.timelines.length === 0) {
    errors.push('At least one timeline is required');
  }

  // Validate each timeline
  options.timelines?.forEach((timeline, tlIdx) => {
    if (!timeline.name) {
      errors.push(`Timeline ${tlIdx}: name is required`);
    }

    // Validate clips in tracks
    timeline.videoTracks?.forEach((track, trackIdx) => {
      track.clips?.forEach((clip, clipIdx) => {
        if (clip.start === undefined) {
          errors.push(`Timeline ${tlIdx} Video Track ${trackIdx} Clip ${clipIdx}: start position required`);
        }
        if (clip.duration === undefined) {
          errors.push(`Timeline ${tlIdx} Video Track ${trackIdx} Clip ${clipIdx}: duration required`);
        }
      });
    });
  });

  return errors;
}

/**
 * Validate DRP structure
 */
function validateDRPStructure(buffer) {
  // Check ZIP magic bytes (PK)
  if (!Buffer.isBuffer(buffer) || buffer.length < 4) {
    return { valid: false, error: 'Invalid buffer' };
  }

  if (buffer[0] !== 0x50 || buffer[1] !== 0x4B) {
    return { valid: false, error: 'Not a ZIP file' };
  }

  return { valid: true };
}

/**
 * Get DRP file size estimate
 */
function estimateDRPSize(clipCount, hasGrades = false) {
  // Base size: ~10KB for project structure
  let size = 10 * 1024;

  // Per clip: ~1KB base + grades if present
  size += clipCount * 1024;

  if (hasGrades) {
    // Grade data: ~2-5KB per graded clip (estimate 50% graded)
    size += (clipCount * 0.5) * 3 * 1024;
  }

  return size;
}

module.exports = {
  packageDRP,
  packageFullDRP,
  validateDRPConfig,
  validateDRPStructure,
  estimateDRPSize,
};
