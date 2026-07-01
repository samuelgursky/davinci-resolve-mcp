'use strict';

/**
 * adapters/resolve-driver.js — the ResolveDriver adapter interface (spec §3.2,
 * P2). Import a turnover, read back `clip_where` source_start, author/export a
 * DRP. Pure contract + a deterministic fake; the concrete headless-Resolve and
 * local-bridge impls (which actually drive Resolve) are Tier-3 and BLOCKED off a
 * Resolve machine. Verifying Oracle vs read-back in the REAL tool is P2's job —
 * this interface is what the engine injects.
 */

class ResolveDriver {
  // eslint-disable-next-line class-methods-use-this, no-unused-vars
  async importTimeline(timelinePath, opts) {
    throw new Error('ResolveDriver.importTimeline must be implemented (headless Resolve / local bridge)');
  }

  // eslint-disable-next-line class-methods-use-this, no-unused-vars
  async clipWhere() {
    throw new Error('ResolveDriver.clipWhere must be implemented — returns source_start per clip');
  }

  // eslint-disable-next-line class-methods-use-this, no-unused-vars
  async authorDrp(timeline, outPath) {
    throw new Error('ResolveDriver.authorDrp must be implemented');
  }
}

function isResolveDriver(obj) {
  return !!obj && typeof obj.importTimeline === 'function' && typeof obj.clipWhere === 'function';
}

/**
 * Deterministic fake for tests — no Resolve. Scripted read-back: returns the
 * source_start map it was constructed with, so the Oracle-vs-readback
 * calibration logic can be exercised without the target tool.
 */
class FakeResolveDriver extends ResolveDriver {
  constructor(readback = {}) {
    super();
    this.readback = readback; // { [seqstart]: source_start }
    this.imported = null;
    this.authored = null;
  }

  async importTimeline(timelinePath) {
    this.imported = timelinePath;
    return { imported: true, clips: Object.keys(this.readback).length };
  }

  async clipWhere() {
    return Object.entries(this.readback).map(([seqstart, source_start]) => ({ seqstart: Number(seqstart), source_start }));
  }

  async authorDrp(timeline, outPath) {
    this.authored = outPath;
    return { drpPath: outPath, clips: timeline && timeline.clips ? timeline.clips.length : 0 };
  }
}

module.exports = { ResolveDriver, FakeResolveDriver, isResolveDriver };
