/**
 * DaVinci Resolve MpFolder XML Builder
 *
 * Generates MpFolder (Media Pool) XML files for DRP packages.
 * Defines the media pool structure with folders and clips.
 *
 * @module mp-folder-builder
 */

const { generateUUID, buildXmlElement, encodeFrameRate } = require('./xml-builder');

/**
 * Folder color tags supported by DaVinci Resolve
 */
const FOLDER_COLORS = {
  NONE: 'FOLDER_COLOR_NONE',
  BLUE: 'FOLDER_COLOR_BLUE',
  CYAN: 'FOLDER_COLOR_CYAN',
  GREEN: 'FOLDER_COLOR_GREEN',
  YELLOW: 'FOLDER_COLOR_YELLOW',
  RED: 'FOLDER_COLOR_RED',
  PINK: 'FOLDER_COLOR_PINK',
  PURPLE: 'FOLDER_COLOR_PURPLE',
  ORANGE: 'FOLDER_COLOR_ORANGE',
};

/**
 * Build a complete MpFolder XML file for DRP
 *
 * @param {Object} mediaPool - Media pool configuration
 * @param {string} mediaPool.name - Root folder name (default: 'Master')
 * @param {Array} mediaPool.clips - Root-level clips
 * @param {Array} mediaPool.folders - Subfolders
 * @returns {string} Complete MpFolder XML
 */
function buildMpFolderFile(mediaPool) {
  const rootId = generateUUID();
  const rootUniqueId = generateUUID();

  // Build subfolders recursively
  const folderElements = (mediaPool.folders || []).map((folder) =>
    buildFolderElement(folder)
  );

  // Build root-level clips
  const clipElements = buildClipElements(mediaPool.clips || []);

  const children = [
    buildXmlElement('Name', {}, mediaPool.name || 'Master'),
    buildXmlElement('UniqueMediaPoolItemId', {}, rootUniqueId),
    buildXmlElement('ColorTag', {}, mediaPool.colorTag || FOLDER_COLORS.NONE),
    buildXmlElement('Folded', {}, mediaPool.folded ? 'true' : 'false'),
    buildXmlElement('FolderVec', {}, folderElements),
    buildXmlElement('MediaVec', {}, clipElements),
  ];

  const mpFolder = buildXmlElement('Sm2MpFolder', { DbId: rootId }, children);

  return `<?xml version="1.0" encoding="UTF-8"?>\n${mpFolder}`;
}

/**
 * Build a folder element with its contents
 *
 * @param {Object} folder - Folder configuration
 * @returns {string} Folder XML element
 */
function buildFolderElement(folder) {
  const folderId = generateUUID();
  const uniqueId = generateUUID();

  // Build subfolders recursively
  const subfolderElements = (folder.subfolders || folder.folders || []).map((sub) =>
    buildFolderElement(sub)
  );

  // Build clips in this folder
  const clipElements = buildClipElements(folder.clips || []);

  const children = [
    buildXmlElement('Name', {}, folder.name || 'Folder'),
    buildXmlElement('UniqueMediaPoolItemId', {}, uniqueId),
    buildXmlElement('ColorTag', {}, folder.colorTag || FOLDER_COLORS.NONE),
    buildXmlElement('Folded', {}, folder.folded ? 'true' : 'false'),
    buildXmlElement('FolderVec', {}, subfolderElements),
    buildXmlElement('MediaVec', {}, clipElements),
  ];

  return buildXmlElement('Sm2MpFolder', { DbId: folderId }, children);
}

/**
 * Build clip elements from array
 */
function buildClipElements(clips) {
  return clips.map((clip) => {
    if (clip.type === 'audio' || clip.trackType === 'audio') {
      return buildAudioClipElement(clip);
    }
    return buildVideoClipElement(clip);
  });
}

/**
 * Build a video clip element
 *
 * @param {Object} clip - Clip data
 * @returns {string} Video clip XML element
 */
function buildVideoClipElement(clip) {
  const clipId = generateUUID();
  const uniqueId = generateUUID();

  const frameRateHex = encodeFrameRate(clip.frameRate || 24);

  const children = [
    buildXmlElement('Name', {}, clip.name || clip.clipName || 'Clip'),
    buildXmlElement('MediaFilePath', {}, clip.filePath || clip.sourceFile || ''),
    buildXmlElement('UniqueMediaPoolItemId', {}, uniqueId),
    buildXmlElement('MediaFrameRate', {}, frameRateHex),
    buildXmlElement('FieldsBlob', {}, '0000000000000000'),
  ];

  // Add optional fields
  if (clip.reelNumber || clip.reelName) {
    children.push(buildXmlElement('MediaReelNumber', {}, clip.reelNumber || clip.reelName));
  }

  if (clip.duration || clip.durationFrames) {
    children.push(buildXmlElement('Duration', {}, String(clip.duration || clip.durationFrames)));
  }

  if (clip.startTimecode) {
    children.push(buildXmlElement('StartTC', {}, clip.startTimecode));
  }

  // Add resolution if available
  if (clip.resolution || (clip.width && clip.height)) {
    const [w, h] = clip.resolution
      ? clip.resolution.split('x').map(Number)
      : [clip.width, clip.height];
    children.push(buildXmlElement('MediaWidth', {}, String(w || 1920)));
    children.push(buildXmlElement('MediaHeight', {}, String(h || 1080)));
  }

  return buildXmlElement('Sm2MpVideoClip', { DbId: clipId }, children);
}

/**
 * Build an audio clip element
 *
 * @param {Object} clip - Clip data
 * @returns {string} Audio clip XML element
 */
function buildAudioClipElement(clip) {
  const clipId = generateUUID();
  const uniqueId = generateUUID();

  const children = [
    buildXmlElement('Name', {}, clip.name || clip.clipName || 'Audio Clip'),
    buildXmlElement('MediaFilePath', {}, clip.filePath || clip.sourceFile || ''),
    buildXmlElement('UniqueMediaPoolItemId', {}, uniqueId),
    buildXmlElement('FieldsBlob', {}, '0000000000000000'),
  ];

  // Add audio-specific fields
  if (clip.sampleRate) {
    children.push(buildXmlElement('SampleRate', {}, String(clip.sampleRate)));
  }

  if (clip.channels || clip.audioChannels) {
    children.push(buildXmlElement('Channels', {}, String(clip.channels || clip.audioChannels)));
  }

  if (clip.duration) {
    children.push(buildXmlElement('Duration', {}, String(clip.duration)));
  }

  return buildXmlElement('Sm2MpAudioClip', { DbId: clipId }, children);
}

/**
 * Build media pool from document line items
 *
 * @param {Array} lineItems - Document line items
 * @param {Object} options - Options
 * @returns {Object} Media pool configuration
 */
function buildMediaPoolFromLineItems(lineItems, options = {}) {
  const { groupByFolder = true, groupByReel = false } = options;

  // Extract unique clips (by source file path)
  const uniqueClips = new Map();

  for (const item of lineItems) {
    if (!item.sourceFile) continue;

    const key = item.sourceFile;
    if (!uniqueClips.has(key)) {
      uniqueClips.set(key, {
        name: item.clipName || key.split('/').pop(),
        filePath: item.sourceFile,
        type: item.trackType || 'video',
        frameRate: item.frameRate || 24,
        resolution: item.resolution,
        reelName: item.reelName,
        codec: item.codec,
        colorSpace: item.colorSpace,
        folder: extractFolderFromPath(item.sourceFile),
      });
    }
  }

  const clips = Array.from(uniqueClips.values());

  // Group clips by folder if requested
  if (groupByFolder) {
    const folderMap = new Map();

    for (const clip of clips) {
      const folder = clip.folder || 'Unsorted';
      if (!folderMap.has(folder)) {
        folderMap.set(folder, []);
      }
      folderMap.get(folder).push(clip);
    }

    const folders = Array.from(folderMap.entries()).map(([name, folderClips]) => ({
      name,
      clips: folderClips,
    }));

    return {
      name: 'Master',
      folders,
      clips: [], // Root clips go in folders
    };
  }

  // Group by reel if requested
  if (groupByReel) {
    const reelMap = new Map();

    for (const clip of clips) {
      const reel = clip.reelName || 'Unidentified';
      if (!reelMap.has(reel)) {
        reelMap.set(reel, []);
      }
      reelMap.get(reel).push(clip);
    }

    const folders = Array.from(reelMap.entries()).map(([name, reelClips]) => ({
      name,
      clips: reelClips,
    }));

    return {
      name: 'Master',
      folders,
      clips: [],
    };
  }

  // No grouping - all clips at root
  return {
    name: 'Master',
    folders: [],
    clips,
  };
}

/**
 * Extract folder name from file path
 */
function extractFolderFromPath(filePath) {
  if (!filePath) return 'Unsorted';

  const parts = filePath.split('/');
  if (parts.length < 2) return 'Unsorted';

  // Return parent folder name
  return parts[parts.length - 2] || 'Unsorted';
}

module.exports = {
  FOLDER_COLORS,
  buildMpFolderFile,
  buildFolderElement,
  buildVideoClipElement,
  buildAudioClipElement,
  buildMediaPoolFromLineItems,
  extractFolderFromPath,
};
