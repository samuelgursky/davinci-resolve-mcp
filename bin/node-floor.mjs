/**
 * Node-floor self-heal for the advanced launcher.
 *
 * The advanced server needs Node >=20.9 (sharp's own floor; better-sqlite3 is
 * a native module built for one ABI). The failure that keeps recurring is not
 * the floor — it is the MCP registration's `command` landing on an old nvm
 * binary (v18.20.8 on this machine, twice) because a GUI app rewrote the
 * config or a shell whose default lags ran the installer. Refusing with the
 * fix printed is right, but a launcher that can SEE a suitable Node on the
 * same machine should use it: find one, re-exec under it, and say so.
 *
 * Pure functions here so the search and the version rule are unit-testable
 * without spawning anything; the launcher wires them to real probes.
 */

import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

export const NODE_FLOOR = { major: 20, minor: 9 };

/** '20.19.0' → true, 'v18.20.8' → false, garbage → false. */
export function meetsFloor(version, floor = NODE_FLOOR) {
  const m = String(version || '').match(/^v?(\d+)\.(\d+)/);
  if (!m) return false;
  const [major, minor] = [Number(m[1]), Number(m[2])];
  return major > floor.major || (major === floor.major && minor >= floor.minor);
}

/** Numeric sort key for a version string; unparsable → [0,0,0]. */
function versionKey(v) {
  const m = String(v || '').match(/^v?(\d+)\.(\d+)\.(\d+)/);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : [0, 0, 0];
}
const byVersionDesc = (a, b) => {
  const ka = versionKey(a);
  const kb = versionKey(b);
  for (let i = 0; i < 3; i += 1) if (ka[i] !== kb[i]) return kb[i] - ka[i];
  return 0;
};

/**
 * Where a Node >=20.9 might live on this machine, best first:
 *   1. DAVINCI_RESOLVE_NODE (an explicit operator choice)
 *   2. nvm's versions dir ($NVM_DIR or ~/.nvm), newest version first
 *   3. Homebrew / system / Windows default install paths
 * The current executable is excluded — it is the one that failed.
 */
export function candidateNodeBinaries({
  env = process.env,
  home = env.HOME || env.USERPROFILE || '',
  platform = process.platform,
  execPath = process.execPath,
  exists = fs.existsSync,
  readdir = (d) => fs.readdirSync(d),
} = {}) {
  const out = [];
  const push = (p) => {
    if (p && p !== execPath && !out.includes(p)) out.push(p);
  };
  // The explicit override is honored as given — even when it names the very
  // binary that started us (a faked-version test, or an operator re-pointing
  // the registration and forgetting to restart).
  if (env.DAVINCI_RESOLVE_NODE) out.push(env.DAVINCI_RESOLVE_NODE);
  const nvmDir = env.NVM_DIR || (home ? path.join(home, '.nvm') : '');
  const versionsDir = nvmDir ? path.join(nvmDir, 'versions', 'node') : '';
  if (versionsDir && exists(versionsDir)) {
    let entries = [];
    try {
      entries = readdir(versionsDir);
    } catch {
      entries = [];
    }
    for (const v of [...entries].sort(byVersionDesc)) {
      push(platform === 'win32' ? path.join(versionsDir, v, 'node.exe') : path.join(versionsDir, v, 'bin', 'node'));
    }
  }
  if (platform === 'win32') {
    for (const p of [
      env.ProgramFiles ? path.join(env.ProgramFiles, 'nodejs', 'node.exe') : '',
      env.LOCALAPPDATA ? path.join(env.LOCALAPPDATA, 'Programs', 'nodejs', 'node.exe') : '',
    ])
      push(p);
  } else {
    for (const p of ['/opt/homebrew/bin/node', '/usr/local/bin/node', '/usr/bin/node', '/snap/bin/node']) push(p);
  }
  return out.filter((p) => exists(p));
}

/** Ask a binary for its Node version; null when it does not run or is not Node. */
export function probeNodeVersion(binary, run = spawnSync) {
  try {
    const r = run(binary, ['-p', 'process.versions.node'], {
      encoding: 'utf8',
      timeout: 5000,
    });
    if (r.status !== 0) return null;
    const v = String(r.stdout || '').trim();
    return /^\d+\.\d+\.\d+/.test(v) ? v : null;
  } catch {
    return null;
  }
}

/**
 * First candidate whose probed version meets the floor → {path, version}, or
 * null. `probed` collects every attempt for the refusal message.
 */
export function findReplacementNode({ candidates, probe = probeNodeVersion, floor = NODE_FLOOR, probed = [] } = {}) {
  for (const p of candidates || []) {
    const version = probe(p);
    probed.push({ path: p, version });
    if (version && meetsFloor(version, floor)) return { path: p, version };
  }
  return null;
}
