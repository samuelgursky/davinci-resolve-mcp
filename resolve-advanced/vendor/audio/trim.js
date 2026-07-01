/**
 * Audio Trim — 2-pop detection and program trim
 *
 * Detects 1kHz sync pops (2-pop) in audio and trims to program length.
 * Standard: 2-pop is 1 frame of 1kHz tone at exactly -2:00 before FFOA.
 *
 * Dependencies: FFmpeg 5+ (v7.1.1 installed)
 */

const { execFile, spawn } = require('child_process');
const { promisify } = require('util');
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
 * Detect 2-pops (1kHz sync tones) in audio.
 *
 * Uses bandpass filter at 1kHz + envelope follower to find short bursts
 * of 1kHz tone that match 2-pop characteristics.
 *
 * @param {string} inputPath - Path to audio file
 * @param {Object} [options]
 * @param {number} [options.frequency=1000] - Expected tone frequency in Hz
 * @param {number} [options.minDuration=0.02] - Min pop duration in seconds
 * @param {number} [options.maxDuration=0.1] - Max pop duration in seconds
 * @param {number} [options.threshold=-30] - Detection threshold in dBFS
 * @returns {Promise<{pops: Array<{time: number, duration: number, level: number}>, count: number}>}
 */
async function detectPops(inputPath, options = {}) {
  const freq = options.frequency || 1000;
  const minDur = options.minDuration || 0.02;
  const maxDur = options.maxDuration || 0.1;
  const threshold = options.threshold || -30;

  // Bandpass around 1kHz, then detect tone bursts
  const { stderr } = await execFileAsync(ffmpegPath, [
    '-i', inputPath,
    '-af', [
      `bandpass=f=${freq}:width_type=h:w=200`,
      `silencedetect=noise=${threshold}dB:d=${minDur}`,
    ].join(','),
    '-f', 'null', '-',
  ], { maxBuffer: 50 * 1024 * 1024, timeout: 120000 });

  // Parse silence boundaries — the NON-silent regions are our pops
  const starts = [...stderr.matchAll(/silence_end:\s*([\d.]+)/g)].map(m => parseFloat(m[1]));
  const ends = [...stderr.matchAll(/silence_start:\s*([\d.]+)/g)].map(m => parseFloat(m[1]));

  // Get file duration
  const { stdout: probeOut } = await execFileAsync(ffprobePath, [
    '-v', 'quiet', '-show_entries', 'format=duration',
    '-of', 'csv=p=0', inputPath,
  ]);
  const totalDuration = parseFloat(probeOut.trim());

  // Build pop list from non-silent regions
  const pops = [];
  // First non-silent region starts at 0 (if no initial silence) or at first silence_end
  for (let i = 0; i < starts.length; i++) {
    const popStart = starts[i];
    const popEnd = i < ends.length ? ends[i + 1] || totalDuration : totalDuration;
    const popDuration = popEnd - popStart;

    // Filter to likely 2-pops: short bursts within expected duration range
    if (popDuration >= minDur && popDuration <= maxDur) {
      pops.push({
        time: popStart,
        duration: popDuration,
        level: 0, // Could measure RMS but not critical
      });
    }
  }

  return { pops, count: pops.length };
}

/**
 * Trim audio to program length using 2-pop as reference.
 *
 * @param {string} inputPath - Path to input audio
 * @param {string} outputPath - Path for trimmed output
 * @param {Object} options
 * @param {number} [options.startTime] - Start time in seconds (auto-detect from 2-pop if not provided)
 * @param {number} [options.endTime] - End time in seconds
 * @param {number} [options.duration] - Duration in seconds (alternative to endTime)
 * @param {number} [options.fadeIn=0] - Fade-in duration in seconds
 * @param {number} [options.fadeOut=0] - Fade-out duration in seconds
 * @param {number} [options.preRoll=2] - Seconds of pre-roll before 2-pop (default 2s per SMPTE)
 * @param {Function} [options.onProgress] - Progress callback
 * @returns {Promise<{outputPath: string, startTime: number, endTime: number, duration: number, popsDetected: number}>}
 */
async function trim(inputPath, outputPath, options = {}) {
  const { fadeIn = 0, fadeOut = 0, preRoll = 2, onProgress = () => {} } = options;

  onProgress(10);

  let startTime = options.startTime;
  let endTime = options.endTime;
  let popsDetected = 0;

  // Auto-detect from 2-pop if no explicit start/end
  if (startTime === undefined) {
    const { pops } = await detectPops(inputPath);
    popsDetected = pops.length;

    if (pops.length >= 1) {
      // First pop is head 2-pop — program starts preRoll seconds after it
      startTime = pops[0].time + preRoll;
    } else {
      startTime = 0;
    }

    if (pops.length >= 2 && endTime === undefined && !options.duration) {
      // Second pop is tail 2-pop — program ends preRoll seconds before it
      endTime = pops[pops.length - 1].time - preRoll;
    }
  }

  onProgress(40);

  // Build FFmpeg args
  const args = ['-y', '-i', inputPath];

  if (startTime > 0) {
    args.push('-ss', String(startTime));
  }

  if (options.duration) {
    args.push('-t', String(options.duration));
  } else if (endTime !== undefined) {
    args.push('-to', String(endTime));
  }

  // Build filter chain for fades
  const filters = [];
  if (fadeIn > 0) {
    filters.push(`afade=t=in:st=0:d=${fadeIn}`);
  }
  if (fadeOut > 0) {
    const dur = options.duration || (endTime !== undefined ? endTime - startTime : 0);
    if (dur > 0) {
      filters.push(`afade=t=out:st=${dur - fadeOut}:d=${fadeOut}`);
    }
  }

  if (filters.length > 0) {
    args.push('-af', filters.join(','));
  }

  args.push('-c:a', 'pcm_s24le', outputPath);

  onProgress(50);

  await execFileAsync(ffmpegPath, args, { timeout: 300000, maxBuffer: 10 * 1024 * 1024 });

  onProgress(90);

  // Get output duration
  const { stdout: durOut } = await execFileAsync(ffprobePath, [
    '-v', 'quiet', '-show_entries', 'format=duration',
    '-of', 'csv=p=0', outputPath,
  ]);
  const outputDuration = parseFloat(durOut.trim());

  onProgress(100);

  return {
    outputPath,
    startTime,
    endTime: endTime || startTime + outputDuration,
    duration: outputDuration,
    popsDetected,
  };
}

module.exports = {
  detectPops,
  trim,
};
