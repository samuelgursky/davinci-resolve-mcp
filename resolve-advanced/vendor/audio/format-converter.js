/**
 * Audio Format Converter — Production-quality audio conversion via FFmpeg
 *
 * Conversion presets for broadcast, web, podcast, DCP, and proxy workflows.
 * Supports sample rate conversion with proper dithering, channel remapping,
 * and metadata preservation.
 *
 * Dependencies: FFmpeg 5+ (already installed — v7.1.1)
 */

const { execFile } = require('child_process');
const { promisify } = require('util');
const fs = require('fs').promises;
const path = require('path');
const os = require('os');

const execFileAsync = promisify(execFile);

// ── Conversion Presets ────────────────────────────────────────────────────

const CONVERSION_PRESETS = {
  'broadcast-wav': {
    name: 'Broadcast WAV (48kHz/24-bit)',
    codec: 'pcm_s24le',
    container: 'wav',
    sampleRate: 48000,
    bitDepth: 24,
    description: 'Standard broadcast delivery format',
  },
  'broadcast-wav-16': {
    name: 'Broadcast WAV (48kHz/16-bit)',
    codec: 'pcm_s16le',
    container: 'wav',
    sampleRate: 48000,
    bitDepth: 16,
    description: 'Legacy broadcast delivery format',
  },
  'cd-wav': {
    name: 'CD Quality WAV (44.1kHz/16-bit)',
    codec: 'pcm_s16le',
    container: 'wav',
    sampleRate: 44100,
    bitDepth: 16,
    description: 'Red Book CD standard',
  },
  'web-aac': {
    name: 'Web AAC (48kHz/192k)',
    codec: 'aac',
    container: 'mp4',
    sampleRate: 48000,
    bitrate: '192k',
    description: 'High-quality web delivery',
  },
  'web-aac-lc': {
    name: 'Web AAC-LC (48kHz/128k)',
    codec: 'aac',
    container: 'mp4',
    sampleRate: 48000,
    bitrate: '128k',
    description: 'Standard web streaming',
  },
  'web-opus': {
    name: 'Web Opus (48kHz/128k)',
    codec: 'libopus',
    container: 'ogg',
    sampleRate: 48000,
    bitrate: '128k',
    description: 'Modern web audio, excellent quality at low bitrate',
  },
  'podcast-mp3': {
    name: 'Podcast MP3 (44.1kHz/192k)',
    codec: 'libmp3lame',
    container: 'mp3',
    sampleRate: 44100,
    bitrate: '192k',
    channels: 2,
    description: 'Standard podcast distribution',
  },
  'podcast-mp3-mono': {
    name: 'Podcast MP3 Mono (44.1kHz/96k)',
    codec: 'libmp3lame',
    container: 'mp3',
    sampleRate: 44100,
    bitrate: '96k',
    channels: 1,
    description: 'Speech-only podcast (smaller file)',
  },
  'dcp-wav': {
    name: 'DCP Audio (48kHz/24-bit 5.1)',
    codec: 'pcm_s24le',
    container: 'wav',
    sampleRate: 48000,
    bitDepth: 24,
    channels: 6,
    description: 'Digital Cinema Package 5.1 surround',
  },
  'proxy-aac': {
    name: 'Proxy AAC (48kHz/128k stereo)',
    codec: 'aac',
    container: 'mp4',
    sampleRate: 48000,
    bitrate: '128k',
    channels: 2,
    description: 'Lightweight proxy for editorial',
  },
  'flac-archive': {
    name: 'FLAC Archive (original rate)',
    codec: 'flac',
    container: 'flac',
    compressionLevel: 8,
    description: 'Lossless archive, maximum compression',
  },
  'flac-standard': {
    name: 'FLAC Standard (original rate)',
    codec: 'flac',
    container: 'flac',
    compressionLevel: 5,
    description: 'Lossless archive, balanced compression/speed',
  },
  'aiff-edit': {
    name: 'AIFF (48kHz/24-bit)',
    codec: 'pcm_s24be',
    container: 'aiff',
    sampleRate: 48000,
    bitDepth: 24,
    description: 'Pro Tools / Logic native format',
  },
};

// ── Container Extensions ──────────────────────────────────────────────────

const CONTAINER_EXTENSIONS = {
  wav: '.wav',
  mp4: '.m4a',
  ogg: '.ogg',
  mp3: '.mp3',
  flac: '.flac',
  aiff: '.aiff',
};

// ── Probe ─────────────────────────────────────────────────────────────────

/**
 * Probe audio file for format details.
 *
 * @param {string} inputPath - Path to audio file
 * @returns {Promise<{codec: string, sampleRate: number, bitDepth: number, channels: number, duration: number, bitrate: number, format: string}>}
 */
async function probeAudio(inputPath) {
  const { stdout } = await execFileAsync('ffprobe', [
    '-v', 'quiet',
    '-print_format', 'json',
    '-show_streams',
    '-show_format',
    inputPath,
  ]);

  const info = JSON.parse(stdout);
  const stream = info.streams?.find(s => s.codec_type === 'audio');
  if (!stream) throw new Error('No audio stream found');

  return {
    codec: stream.codec_name,
    sampleRate: parseInt(stream.sample_rate, 10),
    bitDepth: stream.bits_per_raw_sample ? parseInt(stream.bits_per_raw_sample, 10) : null,
    channels: stream.channels,
    channelLayout: stream.channel_layout || null,
    duration: parseFloat(info.format?.duration || stream.duration || 0),
    bitrate: parseInt(info.format?.bit_rate || stream.bit_rate || 0, 10),
    format: info.format?.format_name,
    size: parseInt(info.format?.size || 0, 10),
  };
}

// ── Conversion ────────────────────────────────────────────────────────────

/**
 * Convert audio to a different format.
 *
 * @param {string} inputPath - Path to input audio file
 * @param {string} outputPath - Path for output file (auto-extension if null)
 * @param {Object} [options]
 * @param {string} [options.preset] - Preset name from CONVERSION_PRESETS
 * @param {string} [options.codec] - Override codec
 * @param {number} [options.sampleRate] - Override sample rate
 * @param {number} [options.channels] - Override channel count
 * @param {string} [options.bitrate] - Override bitrate (for lossy codecs)
 * @param {boolean} [options.dither=true] - Apply dithering when reducing bit depth
 * @param {boolean} [options.preserveMetadata=true] - Copy metadata from input
 * @param {Function} [options.onProgress] - Progress callback
 * @returns {Promise<{outputPath: string, inputInfo: Object, outputInfo: Object, preset: string}>}
 */
async function convert(inputPath, outputPath, options = {}) {
  const onProgress = options.onProgress || (() => {});

  onProgress(5);

  // Get input info
  const inputInfo = await probeAudio(inputPath);

  // Resolve preset
  const presetName = options.preset || 'broadcast-wav';
  const preset = CONVERSION_PRESETS[presetName] || CONVERSION_PRESETS['broadcast-wav'];

  // Merge options over preset
  const codec = options.codec || preset.codec;
  const sampleRate = options.sampleRate || preset.sampleRate || inputInfo.sampleRate;
  const channels = options.channels || preset.channels || inputInfo.channels;
  const bitrate = options.bitrate || preset.bitrate;
  const dither = options.dither !== false;
  const preserveMetadata = options.preserveMetadata !== false;

  // Auto-generate output path if not provided
  if (!outputPath) {
    const ext = CONTAINER_EXTENSIONS[preset.container] || '.wav';
    outputPath = inputPath.replace(/\.[^.]+$/, `_${presetName}${ext}`);
  }

  onProgress(10);

  // Build FFmpeg args
  const args = ['-y', '-i', inputPath];

  // Codec
  args.push('-acodec', codec);

  // Sample rate with proper resampling
  if (sampleRate !== inputInfo.sampleRate) {
    args.push('-ar', String(sampleRate));
    // Use high-quality resampling
    args.push('-af', `aresample=resampler=soxr:precision=28:dither_method=triangular`);
  } else if (dither && preset.bitDepth && inputInfo.bitDepth && preset.bitDepth < inputInfo.bitDepth) {
    // Apply dithering when reducing bit depth without sample rate change
    args.push('-af', 'aresample=dither_method=triangular');
  }

  // Channels
  if (channels !== inputInfo.channels) {
    args.push('-ac', String(channels));
  }

  // Bitrate (for lossy codecs)
  if (bitrate) {
    args.push('-b:a', bitrate);
  }

  // FLAC compression level
  if (preset.compressionLevel !== undefined) {
    args.push('-compression_level', String(preset.compressionLevel));
  }

  // Metadata
  if (preserveMetadata) {
    args.push('-map_metadata', '0');
  } else {
    args.push('-map_metadata', '-1');
  }

  args.push(outputPath);

  onProgress(20);

  // Run conversion
  await execFileAsync('ffmpeg', args, {
    timeout: 300000, // 5 min
    maxBuffer: 10 * 1024 * 1024,
  });

  onProgress(90);

  // Verify output
  const outputInfo = await probeAudio(outputPath);

  onProgress(100);

  return {
    outputPath,
    inputInfo,
    outputInfo,
    preset: presetName,
  };
}

/**
 * Batch convert multiple files to the same preset.
 *
 * @param {string[]} inputPaths - Array of input file paths
 * @param {string} outputDir - Output directory
 * @param {Object} [options] - Same options as convert()
 * @returns {Promise<Array<{inputPath: string, outputPath: string, success: boolean, error?: string}>>}
 */
async function batchConvert(inputPaths, outputDir, options = {}) {
  await fs.mkdir(outputDir, { recursive: true });

  const presetName = options.preset || 'broadcast-wav';
  const preset = CONVERSION_PRESETS[presetName] || CONVERSION_PRESETS['broadcast-wav'];
  const ext = CONTAINER_EXTENSIONS[preset.container] || '.wav';

  const results = [];
  for (let i = 0; i < inputPaths.length; i++) {
    const inputPath = inputPaths[i];
    const baseName = path.basename(inputPath, path.extname(inputPath));
    const outputPath = path.join(outputDir, `${baseName}${ext}`);

    try {
      const result = await convert(inputPath, outputPath, {
        ...options,
        onProgress: (pct) => {
          if (options.onProgress) {
            const overall = Math.round(((i + pct / 100) / inputPaths.length) * 100);
            options.onProgress(overall);
          }
        },
      });
      results.push({ inputPath, outputPath: result.outputPath, success: true });
    } catch (err) {
      results.push({ inputPath, outputPath, success: false, error: err.message });
    }
  }

  return results;
}

module.exports = {
  CONVERSION_PRESETS,
  CONTAINER_EXTENSIONS,
  probeAudio,
  convert,
  batchConvert,
};
