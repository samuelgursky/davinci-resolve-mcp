/**
 * capabilities tool — report which optional features are available and how to
 * enable the rest. The core (file/grade/editorial/fusion/conform-core) is always
 * available (pure-JS); a few features need user-installed ffmpeg/sharp/better-sqlite3.
 */

import { capabilities } from '../capabilities.mjs';

export const capabilitiesTool = {
  name: 'capabilities',
  description:
    'Report available vs. setup-needed features. The core is pure-JS (always works); audio needs ffmpeg on PATH, conform.verify needs sharp, fairlight DB path needs better-sqlite3. Action: get.',
  async handler() {
    return capabilities();
  },
};
