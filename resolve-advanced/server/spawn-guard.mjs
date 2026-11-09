/**
 * spawn-guard.mjs — what a tool caller may and may not choose about a child process.
 *
 * A caller picks DATA: which media file to probe, which database to back up.
 * A caller never picks the PROGRAM. Several helpers take the binary to run as
 * an option (`ffmpegPath`, `opts.ffprobe`, `pg.pgDumpPath`, …) so tests and the
 * operator can point them at a specific install, and because tool arguments
 * are `passthrough()`, any handler that forwarded its arguments wholesale let a
 * prompt-injected agent name an arbitrary executable (GHSA-h2fm-rcfg-jch9).
 *
 * Two rules, enforced here:
 *
 *  1. `assertNoBinaryOverrides(args)` runs at the tool dispatcher, before any
 *     handler, and refuses a string under any binary-selecting key at any
 *     depth. The operator selects binaries through PATH or the environment
 *     (`binaryFromEnv`). `test/spawn-guard.test.mjs` scans the source for every
 *     option that falls back to a bare binary name, so a new one that is not in
 *     BINARY_OVERRIDE_KEYS fails the suite rather than reopening the hole.
 *
 *  2. `assertNotOption(value)` refuses a caller path that a child would parse
 *     as an option. A file named `-report` handed to ffprobe positionally is an
 *     option, not a file. Apply it wherever a caller path lands in a positional
 *     slot of an argv.
 */

/** Option names that select which executable a helper spawns. */
export const BINARY_OVERRIDE_KEYS = Object.freeze([
  'ffmpeg',
  'ffprobe',
  'ffmpegPath',
  'ffprobePath',
  'pgDumpPath',
  'findPath',
  'python',
]);

const KEY_SET = new Set(BINARY_OVERRIDE_KEYS);
const MAX_DEPTH = 64;

/**
 * Throw if `args` carries a caller-chosen executable anywhere in its tree.
 *
 * Only a STRING under one of the keys is refused: that is the shape a binary
 * path takes. An object under `ffprobe` (a probe result echoed back by a
 * caller) is data and passes.
 */
export function assertNoBinaryOverrides(args, where = 'args') {
  const visit = (value, trail, depth) => {
    if (depth > MAX_DEPTH || value === null || typeof value !== 'object') return;
    if (Array.isArray(value)) {
      value.forEach((item, index) => visit(item, `${trail}[${index}]`, depth + 1));
      return;
    }
    for (const [key, child] of Object.entries(value)) {
      const here = `${trail}.${key}`;
      if (KEY_SET.has(key) && typeof child === 'string') {
        const error = new Error(
          `${here}: a tool call cannot choose which program the server runs. ` +
            'Put the binary on PATH, or set it in the server environment ' +
            '(RESOLVE_ADVANCED_PG_DUMP for pg_dump), then retry without this key.',
        );
        error.code = 'BINARY_OVERRIDE_REFUSED';
        throw error;
      }
      visit(child, here, depth + 1);
    }
  };
  visit(args, where, 0);
}

/**
 * Throw if a caller-supplied path would be parsed as an option by the child.
 * Returns the value unchanged so it can wrap an argv element inline.
 */
export function assertNotOption(value, label = 'path') {
  if (typeof value !== 'string' || !value.length) {
    throw new Error(`${label} must be a non-empty string`);
  }
  if (value.startsWith('-')) {
    const error = new Error(
      `${label} '${value}' starts with '-', so the program would read it as an option. ` +
        'Pass it as an absolute path or prefix it with ./',
    );
    error.code = 'OPTION_LIKE_PATH_REFUSED';
    throw error;
  }
  return value;
}

/** The operator's choice of binary from the environment, else the bare name (PATH). */
export function binaryFromEnv(envName, fallback) {
  const chosen = process.env[envName];
  return typeof chosen === 'string' && chosen.trim() ? chosen.trim() : fallback;
}
