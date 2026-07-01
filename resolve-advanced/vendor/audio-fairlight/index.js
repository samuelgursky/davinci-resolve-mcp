/**
 * Fairlight Audio Intelligence
 *
 * Audio track planning, coverage analysis, and loudness validation
 * for DaVinci Resolve Fairlight workflows.
 *
 * Provides content-type-specific audio templates (documentary,
 * narrative, podcast, social) and tools to analyze clip coverage,
 * detect gaps/overlaps/silence, and validate loudness targets.
 *
 * @module post-tools/audio-fairlight
 */

/**
 * Audio track channel types recognized by Resolve.
 * @type {Object<string, string>}
 */
const CHANNEL_TYPES = {
  MONO: 'mono',
  STEREO: 'stereo',
  SURROUND_51: '5.1',
  SURROUND_71: '7.1',
  ADAPTIVE: 'adaptive1',
};

/**
 * Audio templates for different content types.
 *
 * Each template defines tracks with name, channel type, and routing.
 * Bus assignments reflect standard Fairlight mixing conventions.
 *
 * @type {Object}
 */
const AUDIO_TEMPLATES = {
  DOCUMENTARY: {
    name: 'Documentary',
    description: 'Interview-driven documentary with natural sound and music',
    tracks: [
      { name: 'DX L',   label: 'Dialogue Left',      channelType: 'mono', bus: 'DX',  role: 'dialogue' },
      { name: 'DX R',   label: 'Dialogue Right',      channelType: 'mono', bus: 'DX',  role: 'dialogue' },
      { name: 'NAT',    label: 'Natural Sound',        channelType: 'stereo', bus: 'NAT', role: 'nat_sound' },
      { name: 'MX',     label: 'Music',                channelType: 'stereo', bus: 'MX',  role: 'music' },
      { name: 'VO',     label: 'Voice Over',           channelType: 'mono',   bus: 'DX',  role: 'voiceover' },
      { name: 'SFX',    label: 'Sound Effects',        channelType: 'stereo', bus: 'FX',  role: 'sfx' },
    ],
    buses: ['DX', 'NAT', 'MX', 'FX', 'MAIN'],
    outputFormat: 'stereo',
  },

  NARRATIVE: {
    name: 'Narrative Feature',
    description: 'Scripted narrative with full surround sound design',
    tracks: [
      { name: 'DX',     label: 'Production Dialogue',  channelType: '5.1',    bus: 'DX',  role: 'dialogue' },
      { name: 'ADR',    label: 'ADR / Loop Group',      channelType: '5.1',    bus: 'DX',  role: 'dialogue' },
      { name: 'FX',     label: 'Sound Effects',         channelType: '5.1',    bus: 'FX',  role: 'sfx' },
      { name: 'BG',     label: 'Backgrounds / Ambience', channelType: '5.1',   bus: 'FX',  role: 'ambience' },
      { name: 'FLY',    label: 'Foley',                 channelType: '5.1',    bus: 'FX',  role: 'foley' },
      { name: 'MX',     label: 'Music Score',           channelType: '5.1',    bus: 'MX',  role: 'music' },
      { name: 'MX2',    label: 'Music Source / Diegetic', channelType: 'stereo', bus: 'MX', role: 'music' },
      { name: 'FG',     label: 'Full Mix Guide',        channelType: 'stereo', bus: 'REF', role: 'guide' },
    ],
    buses: ['DX', 'FX', 'MX', 'REF', 'MAIN'],
    outputFormat: '5.1',
  },

  PODCAST: {
    name: 'Podcast',
    description: 'Multi-host podcast with music beds',
    tracks: [
      { name: 'HOST',   label: 'Host Microphone',      channelType: 'mono',   bus: 'DX',  role: 'dialogue' },
      { name: 'GUEST',  label: 'Guest Microphone',     channelType: 'mono',   bus: 'DX',  role: 'dialogue' },
      { name: 'GUEST2', label: 'Guest 2 Microphone',   channelType: 'mono',   bus: 'DX',  role: 'dialogue' },
      { name: 'MX',     label: 'Music / Beds',         channelType: 'stereo', bus: 'MX',  role: 'music' },
      { name: 'SFX',    label: 'Stingers / SFX',       channelType: 'stereo', bus: 'FX',  role: 'sfx' },
      { name: 'PHONE',  label: 'Phone / Remote',       channelType: 'mono',   bus: 'DX',  role: 'dialogue' },
    ],
    buses: ['DX', 'MX', 'FX', 'MAIN'],
    outputFormat: 'stereo',
  },

  SOCIAL: {
    name: 'Social Media',
    description: 'Quick-turnaround social content',
    tracks: [
      { name: 'MIX',    label: 'Main Mix',             channelType: 'stereo', bus: 'MAIN', role: 'mix' },
      { name: 'VO',     label: 'Voice Over',           channelType: 'mono',   bus: 'DX',   role: 'voiceover' },
      { name: 'MX',     label: 'Music',                channelType: 'stereo', bus: 'MX',   role: 'music' },
    ],
    buses: ['DX', 'MX', 'MAIN'],
    outputFormat: 'stereo',
  },
};

/**
 * Loudness targets for common delivery specs.
 * @type {Object}
 */
const LOUDNESS_TARGETS = {
  broadcast_us:   { standard: 'ATSC A/85',    targetLUFS: -24, tolerance: 2, truePeakdBTP: -2 },
  broadcast_eu:   { standard: 'EBU R128',     targetLUFS: -23, tolerance: 1, truePeakdBTP: -1 },
  streaming:      { standard: 'Streaming',    targetLUFS: -16, tolerance: 2, truePeakdBTP: -1 },
  cinema:         { standard: 'SMPTE RP 200', targetLUFS: -20, tolerance: 2, truePeakdBTP: -3 },
  podcast:        { standard: 'Podcast',      targetLUFS: -16, tolerance: 2, truePeakdBTP: -1 },
};

/**
 * Select an audio template by content type.
 *
 * @param {string} contentType — 'documentary'|'narrative'|'podcast'|'social'
 * @returns {object} template definition
 */
function selectTemplate(contentType) {
  const key = contentType.toUpperCase().replace(/[\s-]/g, '_');
  const template = AUDIO_TEMPLATES[key];
  if (!template) {
    const available = Object.keys(AUDIO_TEMPLATES).map(k => k.toLowerCase()).join(', ');
    throw new Error(`Unknown content type "${contentType}". Available: ${available}`);
  }
  return JSON.parse(JSON.stringify(template));
}

/**
 * Generate a Fairlight track creation plan from a template.
 *
 * Returns instructions suitable for Resolve timeline track creation:
 * AddTrack('audio', subtype) calls and track naming.
 *
 * @param {object} template — from selectTemplate or AUDIO_TEMPLATES
 * @param {object} [opts]
 * @param {number} [opts.startIndex=1] — first audio track index
 * @returns {object} { tracks: [...], buses: [...], resolveCommands: [...] }
 */
function generateTrackPlan(template, opts = {}) {
  const { startIndex = 1 } = opts;

  const tracks = template.tracks.map((t, i) => ({
    index: startIndex + i,
    name: t.name,
    label: t.label,
    channelType: t.channelType,
    bus: t.bus,
    role: t.role,
    resolveSubtype: t.channelType === '5.1' ? '5.1'
      : t.channelType === '7.1' ? '7.1'
      : t.channelType === 'stereo' ? 'stereo'
      : 'mono',
  }));

  const resolveCommands = tracks.map(t => ({
    action: 'AddTrack',
    args: ['audio', t.resolveSubtype],
    then: { action: 'SetTrackName', args: ['audio', t.index, t.name] },
  }));

  return {
    templateName: template.name,
    outputFormat: template.outputFormat,
    trackCount: tracks.length,
    tracks,
    buses: template.buses,
    resolveCommands,
  };
}

/**
 * Analyze audio clip coverage on a timeline.
 *
 * Detects gaps, overlaps, and silence per track.
 *
 * @param {object[]} clips — [{ trackIndex, trackName, startTime, endTime, hasAudio? }]
 * @param {object} [opts]
 * @param {number} [opts.minGap=0.5] — minimum gap (seconds) to flag
 * @param {number} [opts.timelineStart=0]
 * @param {number} [opts.timelineEnd] — if omitted, derived from last clip
 * @returns {object} { tracks: { [trackName]: { clips, gaps, overlaps, coveragePercent } }, summary }
 */
function analyzeAudioCoverage(clips, opts = {}) {
  const { minGap = 0.5, timelineStart = 0 } = opts;

  // Group by track
  const trackGroups = {};
  for (const clip of clips) {
    const key = clip.trackName || `Track ${clip.trackIndex}`;
    if (!trackGroups[key]) trackGroups[key] = [];
    trackGroups[key].push(clip);
  }

  // Derive timeline end
  let timelineEnd = opts.timelineEnd;
  if (timelineEnd === undefined) {
    timelineEnd = 0;
    for (const clip of clips) {
      if (clip.endTime > timelineEnd) timelineEnd = clip.endTime;
    }
  }

  const totalDuration = timelineEnd - timelineStart;
  const tracks = {};
  let totalGaps = 0;
  let totalOverlaps = 0;

  for (const [trackName, trackClips] of Object.entries(trackGroups)) {
    // Sort by start time
    const sorted = [...trackClips].sort((a, b) => a.startTime - b.startTime);
    const gaps = [];
    const overlaps = [];

    // Check gap before first clip
    if (sorted.length > 0 && sorted[0].startTime - timelineStart > minGap) {
      gaps.push({
        startTime: timelineStart,
        endTime: sorted[0].startTime,
        duration: sorted[0].startTime - timelineStart,
      });
    }

    // Check between clips
    for (let i = 1; i < sorted.length; i++) {
      const prev = sorted[i - 1];
      const curr = sorted[i];

      if (curr.startTime < prev.endTime) {
        // Overlap
        overlaps.push({
          clipA: i - 1,
          clipB: i,
          startTime: curr.startTime,
          endTime: Math.min(prev.endTime, curr.endTime),
          duration: Math.min(prev.endTime, curr.endTime) - curr.startTime,
        });
      } else if (curr.startTime - prev.endTime > minGap) {
        // Gap
        gaps.push({
          startTime: prev.endTime,
          endTime: curr.startTime,
          duration: curr.startTime - prev.endTime,
        });
      }
    }

    // Check gap after last clip
    if (sorted.length > 0) {
      const last = sorted[sorted.length - 1];
      if (timelineEnd - last.endTime > minGap) {
        gaps.push({
          startTime: last.endTime,
          endTime: timelineEnd,
          duration: timelineEnd - last.endTime,
        });
      }
    }

    // Calculate coverage
    let coveredTime = 0;
    const merged = _mergeIntervals(sorted.map(c => [c.startTime, c.endTime]));
    for (const [s, e] of merged) {
      coveredTime += Math.min(e, timelineEnd) - Math.max(s, timelineStart);
    }

    const coveragePercent = totalDuration > 0
      ? Math.round((coveredTime / totalDuration) * 10000) / 100
      : 0;

    totalGaps += gaps.length;
    totalOverlaps += overlaps.length;

    tracks[trackName] = {
      clipCount: sorted.length,
      gaps,
      overlaps,
      coveragePercent,
    };
  }

  return {
    tracks,
    summary: {
      trackCount: Object.keys(tracks).length,
      totalGaps,
      totalOverlaps,
      timelineDuration: totalDuration,
    },
  };
}

/**
 * Merge overlapping intervals.
 * @param {number[][]} intervals — [[start, end], ...]
 * @returns {number[][]}
 */
function _mergeIntervals(intervals) {
  if (intervals.length === 0) return [];
  const sorted = [...intervals].sort((a, b) => a[0] - b[0]);
  const merged = [sorted[0]];

  for (let i = 1; i < sorted.length; i++) {
    const last = merged[merged.length - 1];
    if (sorted[i][0] <= last[1]) {
      last[1] = Math.max(last[1], sorted[i][1]);
    } else {
      merged.push(sorted[i]);
    }
  }

  return merged;
}

/**
 * Validate loudness measurements against a target.
 *
 * @param {object} measurements — { integratedLUFS, truePeakdBTP, shortTermMax?, momentaryMax?, LRA? }
 * @param {number|string} targetLUFS — target in LUFS or a preset key (e.g. 'broadcast_us')
 * @returns {object} { pass, results: [{ check, value, target, pass, message }] }
 */
function checkLoudness(measurements, targetLUFS) {
  let target;

  if (typeof targetLUFS === 'string') {
    const preset = LOUDNESS_TARGETS[targetLUFS.toLowerCase().replace(/[\s-]/g, '_')];
    if (!preset) throw new Error(`Unknown loudness target "${targetLUFS}"`);
    target = preset;
  } else {
    target = { targetLUFS, tolerance: 2, truePeakdBTP: -1 };
  }

  const results = [];
  let allPass = true;

  // Integrated loudness check
  const intDiff = Math.abs(measurements.integratedLUFS - target.targetLUFS);
  const intPass = intDiff <= target.tolerance;
  if (!intPass) allPass = false;

  results.push({
    check: 'integrated_loudness',
    value: measurements.integratedLUFS,
    target: target.targetLUFS,
    tolerance: target.tolerance,
    pass: intPass,
    message: intPass
      ? `Integrated loudness ${measurements.integratedLUFS} LUFS within tolerance`
      : `Integrated loudness ${measurements.integratedLUFS} LUFS outside tolerance (target: ${target.targetLUFS} +/- ${target.tolerance})`,
  });

  // True peak check
  if (measurements.truePeakdBTP !== undefined && target.truePeakdBTP !== undefined) {
    const tpPass = measurements.truePeakdBTP <= target.truePeakdBTP;
    if (!tpPass) allPass = false;

    results.push({
      check: 'true_peak',
      value: measurements.truePeakdBTP,
      target: target.truePeakdBTP,
      pass: tpPass,
      message: tpPass
        ? `True peak ${measurements.truePeakdBTP} dBTP within limit`
        : `True peak ${measurements.truePeakdBTP} dBTP exceeds limit of ${target.truePeakdBTP} dBTP`,
    });
  }

  // LRA check (informational, typical range 5-20 LU)
  if (measurements.LRA !== undefined) {
    const lraWarn = measurements.LRA > 20;
    results.push({
      check: 'loudness_range',
      value: measurements.LRA,
      pass: !lraWarn,
      message: lraWarn
        ? `Loudness range ${measurements.LRA} LU is unusually wide (>20 LU)`
        : `Loudness range ${measurements.LRA} LU is within normal bounds`,
    });
    if (lraWarn) allPass = false;
  }

  return {
    pass: allPass,
    standard: target.standard || 'Custom',
    results,
  };
}

module.exports = {
  AUDIO_TEMPLATES,
  CHANNEL_TYPES,
  LOUDNESS_TARGETS,
  selectTemplate,
  generateTrackPlan,
  analyzeAudioCoverage,
  checkLoudness,
};
