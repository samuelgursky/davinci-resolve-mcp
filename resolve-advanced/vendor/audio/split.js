/**
 * Audio Split — Split audio at silence, timecodes, or fixed intervals
 *
 * Modes:
 *   silence — detect silence gaps and split at each one
 *   timecodes — split at specific timecodes (user-provided)
 *   interval — split at fixed intervals (e.g., every 30 minutes)
 *
 * Dependencies: FFmpeg 5+ (v7.1.1 installed)
 */

const { execFile } = require('child_process');
const { promisify } = require('util');
const fs = require('fs').promises;
const path = require('path');
const os = require('os');

const execFileAsync = promisify(execFile);

let ffmpegPath = 'ffmpeg';
let ffprobePath = 'ffprobe';
try {
  ffmpegPath = require('ffmpeg-static');
  ffprobePath = require('ffprobe-static').path;
} catch {}

/**
 * Get audio duration.
 */
async function getDuration(inputPath) {
  const { stdout } = await execFileAsync(ffprobePath, [
    '-v', 'quiet', '-show_entries', 'format=duration',
    '-of', 'csv=p=0', inputPath,
  ]);
  return parseFloat(stdout.trim());
}

/**
 * Detect silence gaps for splitting.
 */
async function detectSilencePoints(inputPath, options = {}) {
  const threshold = options.threshold || -40;
  const minDuration = options.minDuration || 1.0;

  const { stderr } = await execFileAsync(ffmpegPath, [
    '-i', inputPath,
    '-af', `silencedetect=noise=${threshold}dB:d=${minDuration}`,
    '-f', 'null', '-',
  ], { maxBuffer: 50 * 1024 * 1024, timeout: 120000 });

  const starts = [...stderr.matchAll(/silence_start:\s*([\d.]+)/g)].map(m => parseFloat(m[1]));
  const ends = [...stderr.matchAll(/silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)/g)];

  const splitPoints = [];
  for (let i = 0; i < ends.length; i++) {
    const silenceEnd = parseFloat(ends[i][1]);
    const silenceStart = starts[i] !== undefined ? starts[i] : silenceEnd;
    // Split at the midpoint of each silence gap
    const midpoint = (silenceStart + silenceEnd) / 2;
    splitPoints.push(midpoint);
  }

  return splitPoints;
}

/**
 * Split an audio file into segments.
 *
 * @param {string} inputPath - Path to input audio
 * @param {string} outputDir - Directory for output segments
 * @param {Object} options
 * @param {string} [options.mode='silence'] - Split mode: 'silence', 'timecodes', 'interval'
 * @param {number[]} [options.timecodes] - Split points in seconds (for 'timecodes' mode)
 * @param {number} [options.interval] - Interval in seconds (for 'interval' mode)
 * @param {number} [options.silenceThreshold=-40] - Silence threshold in dBFS
 * @param {number} [options.silenceMinDuration=1.0] - Min silence duration in seconds
 * @param {string} [options.prefix] - Output filename prefix
 * @param {string} [options.codec='pcm_s24le'] - Output codec
 * @param {Function} [options.onProgress] - Progress callback
 * @returns {Promise<{segments: Array<{index: number, path: string, start: number, end: number, duration: number}>, count: number}>}
 */
async function split(inputPath, outputDir, options = {}) {
  const {
    mode = 'silence',
    timecodes,
    interval,
    silenceThreshold = -40,
    silenceMinDuration = 1.0,
    codec = 'pcm_s24le',
    onProgress = () => {},
  } = options;

  await fs.mkdir(outputDir, { recursive: true });

  const baseName = options.prefix || path.basename(inputPath, path.extname(inputPath));
  const ext = codec.startsWith('pcm_') ? '.wav' : '.flac';

  onProgress(10);

  const totalDuration = await getDuration(inputPath);

  // Determine split points
  let splitPoints = [];

  if (mode === 'silence') {
    splitPoints = await detectSilencePoints(inputPath, {
      threshold: silenceThreshold,
      minDuration: silenceMinDuration,
    });
  } else if (mode === 'timecodes') {
    if (!timecodes || timecodes.length === 0) {
      throw new Error('timecodes required for timecodes mode');
    }
    splitPoints = [...timecodes].sort((a, b) => a - b);
  } else if (mode === 'interval') {
    if (!interval || interval <= 0) {
      throw new Error('interval required for interval mode');
    }
    for (let t = interval; t < totalDuration; t += interval) {
      splitPoints.push(t);
    }
  } else {
    throw new Error(`Unknown mode: ${mode}`);
  }

  onProgress(30);

  // Build segment boundaries
  const boundaries = [0, ...splitPoints, totalDuration];
  const segments = [];

  for (let i = 0; i < boundaries.length - 1; i++) {
    const start = boundaries[i];
    const end = boundaries[i + 1];
    const duration = end - start;

    if (duration < 0.1) continue; // Skip tiny segments

    const segPath = path.join(outputDir, `${baseName}_${String(i + 1).padStart(3, '0')}${ext}`);

    await execFileAsync(ffmpegPath, [
      '-y', '-i', inputPath,
      '-ss', String(start),
      '-t', String(duration),
      '-c:a', codec,
      segPath,
    ], { timeout: 120000, maxBuffer: 10 * 1024 * 1024 });

    segments.push({
      index: i + 1,
      path: segPath,
      start,
      end,
      duration,
    });

    onProgress(30 + Math.round((i / (boundaries.length - 1)) * 60));
  }

  onProgress(100);

  return {
    segments,
    count: segments.length,
    totalDuration,
    mode,
  };
}

module.exports = {
  split,
  detectSilencePoints,
};
