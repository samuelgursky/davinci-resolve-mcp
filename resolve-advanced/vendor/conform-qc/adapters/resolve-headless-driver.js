'use strict';

/**
 * adapters/resolve-headless-driver.js — the concrete ResolveDriver (spec §3.2,
 * P2) that drives a running (headless) DaVinci Resolve via the Python scripting
 * API (adapters/resolve/driver.py). This is BOTH the cloud render-node impl and
 * the local post-assistant impl — the mechanism (Resolve scripting API) is the
 * same; only the host differs.
 *
 * The conformed source_start is read from TimelineItem.GetLeftOffset() with media
 * OFFLINE (importSourceClips:false) — verified to equal the Oracle across a full
 * reel, so the read-back needs no mounted volumes.
 */

const { spawnSync } = require('child_process');
const path = require('path');
const { ResolveDriver } = require('./resolve-driver');

const DRIVER_PY = path.join(__dirname, 'resolve', 'driver.py');

const DEFAULT_ENV = {
  RESOLVE_SCRIPT_API: '/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting',
  RESOLVE_SCRIPT_LIB: '/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so',
};

function resolveEnv(extra) {
  const env = { ...process.env, ...DEFAULT_ENV, ...(extra || {}) };
  const modules = `${DEFAULT_ENV.RESOLVE_SCRIPT_API}/Modules/`;
  env.PYTHONPATH = env.PYTHONPATH ? `${modules}:${env.PYTHONPATH}` : modules;
  return env;
}

class HeadlessResolveDriver extends ResolveDriver {
  constructor(opts = {}) {
    super();
    this.python = opts.python || 'python3';
    this.project = opts.project || 'conformqc_p2';
    this.env = resolveEnv(opts.env);
    this._lastXml = null;
  }

  _run(args, timeoutMs = 120000) {
    const r = spawnSync(this.python, [DRIVER_PY, ...args], { env: this.env, encoding: 'utf8', timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024 });
    if (r.status !== 0 && !r.stdout) {
      throw new Error(`resolve driver failed: ${(r.stderr || '').slice(-400)}`);
    }
    const line = (r.stdout || '').trim().split('\n').filter(Boolean).pop();
    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch (e) {
      throw new Error(`resolve driver: bad output: ${(r.stdout || '').slice(-400)} / ${(r.stderr || '').slice(-200)}`);
    }
    if (!parsed.ok) throw new Error(`resolve driver: ${parsed.error || 'not ok'}`);
    return parsed;
  }

  /** Is a running Resolve reachable? (for skip-if-absent gating) */
  ping() {
    try {
      return this._run(['ping'], 30000);
    } catch (e) {
      return null;
    }
  }

  async importTimeline(timelinePath) {
    this._lastXml = timelinePath; // import happens together with read-back (one Resolve round-trip)
    return { imported: true, path: timelinePath };
  }

  /** Import the last turnover (media offline) and read GetLeftOffset per clip. */
  async clipWhere(timelinePath) {
    const xml = timelinePath || this._lastXml;
    if (!xml) throw new Error('clipWhere: no timeline imported');
    const res = this._run(['readback', xml, this.project]);
    return res.clips; // [{ seqstart, source_start, name }]
  }

  async authorDrp(timelinePath, outPath) {
    const res = this._run(['export-drp', timelinePath || this._lastXml, outPath, `${this.project}_drp`]);
    return { drpPath: res.drpPath, validArchive: res.validArchive, entryCount: res.entryCount, size: res.size };
  }
}

module.exports = { HeadlessResolveDriver, resolveEnv, DRIVER_PY };
