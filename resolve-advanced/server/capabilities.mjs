/**
 * Optional-capability detection. The published package is pure-JS/MIT with ZERO
 * required native modules or bundled binaries. A few tools need an external tool
 * the user installs themselves:
 *
 * ffmpeg / ffprobe (on PATH) — audio ops (split/trim/convert) + conform frame ops
 * sharp (npm i) — conform.verify brightness-robust frame compare
 * better-sqlite3 (npm i) — fairlight live-project-DB path (the .drp-zip path needs none)
 *
 * We DON'T bundle ffmpeg-static (its FFmpeg binaries are GPL — incompatible with a
 * clean MIT distribution). Resolve users already have ffmpeg, or: `brew install ffmpeg`.
 */

import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const cache = new Map();

function onPath(bin) {
  if (cache.has(bin)) return cache.get(bin);
  let ok = false;
  try {
    const r = spawnSync(bin, ['-version'], { stdio: 'ignore', timeout: 4000 });
    ok = !r.error && (r.status === 0 || r.status === null);
  } catch {
    ok = false;
  }
  cache.set(bin, ok);
  return ok;
}

function nodeModuleAvailable(name) {
  const key = `mod:${name}`;
  if (cache.has(key)) return cache.get(key);
  let ok = false;
  try {
    require.resolve(name);
    ok = true;
  } catch {
    ok = false;
  }
  cache.set(key, ok);
  return ok;
}

export const hasFfmpeg = () => onPath('ffmpeg');
export const hasFfprobe = () => onPath('ffprobe');
export const hasSharp = () => nodeModuleAvailable('sharp');
export const hasBetterSqlite3 = () => nodeModuleAvailable('better-sqlite3');

/** Throw a clear, actionable error if ffmpeg/ffprobe aren't on PATH. */
export function requireFfmpeg() {
  if (!hasFfmpeg() || !hasFfprobe()) {
    throw new Error(
      'This feature needs ffmpeg + ffprobe on your PATH (not bundled — FFmpeg binaries are GPL). ' +
        'Install: macOS `brew install ffmpeg`, Debian/Ubuntu `apt install ffmpeg`, Windows `choco install ffmpeg`.',
    );
  }
}

/** Capability snapshot — what's available + how to enable what isn't. */
export function capabilities() {
  const ff = hasFfmpeg() && hasFfprobe();
  return {
    core: 'always available (pure-JS): drp, drt, drx, offline_ref, editorial, fusion, audio_plan, conform(core)',
    optional: {
      ffmpeg: { available: ff, enables: 'audio (split/trim/convert)', install: 'brew install ffmpeg / apt install ffmpeg' },
      sharp: { available: hasSharp(), enables: 'conform.verify (frame compare)', install: 'npm i sharp' },
      'better-sqlite3': { available: hasBetterSqlite3(), enables: 'fairlight live-project-DB path (zip path needs none)', install: 'npm i better-sqlite3' },
    },
  };
}

/** One-line startup summary to stderr (never stdout — that's the MCP channel). */
export function logCapabilities() {
  const c = capabilities();
  const miss = Object.entries(c.optional)
    .filter(([, v]) => !v.available)
    .map(([k]) => k);
  if (miss.length) {
    process.stderr.write(
      `[davinci-resolve-advanced-mcp] optional features needing setup: ${miss.join(', ')} — call the 'capabilities' tool for install hints.\n`,
    );
  }
}
