#!/usr/bin/env node
/**
 * Author an interchange timeline (OTIO / EDL / DRT) from a normalized event list.
 *
 * A thin stdin/stdout bridge so the Python server can reach the authoring code that
 * already exists in `resolve-advanced/server/author-interchange.mjs` instead of growing
 * a second implementation of it. Reimplementing OTIO and DRT authoring in Python would
 * mean two writers to keep in agreement, and the one that drifts is always the copy
 * nobody is running.
 *
 * Input (stdin, JSON):
 *   { events: [...], target: "otio"|"edl"|"drt", outputPath: "...", opts: {...} }
 *
 * Output (stdout, JSON): { ok, target, bytes, outputPath, warnings: [...] }
 * On failure: { ok: false, error } and a non-zero exit.
 */

import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

async function main() {
  const raw = await readStdin();
  let request;
  try {
    request = JSON.parse(raw || '{}');
  } catch (error) {
    throw new Error(`could not parse the request as JSON: ${error.message}`);
  }

  const { events, target = 'otio', outputPath, opts = {} } = request;
  if (!Array.isArray(events) || events.length === 0) {
    throw new Error('events must be a non-empty array');
  }
  if (!outputPath) throw new Error('outputPath is required');

  const module = await import(
    path.join(here, '..', 'resolve-advanced', 'server', 'author-interchange.mjs')
  );
  const authored = await module.authorInterchange(events, target, opts);

  const payload = authored.buffer || Buffer.from(authored.content, 'utf8');
  await fs.mkdir(path.dirname(path.resolve(outputPath)), { recursive: true });
  await fs.writeFile(outputPath, payload);

  const warnings = [];
  // An OTIO event with no media timecode origin imports as an EMPTY timeline in Resolve
  // — the file looks fine and nothing appears. Name the events that are guessing rather
  // than letting the caller discover it as a silent no-op.
  const assumed = authored.mediaOriginAssumed || module.otioMediaOriginAssumed(events);
  if (assumed && assumed.length) {
    warnings.push({
      id: 'media_tc_origin_assumed',
      detail:
        `${assumed.length} event(s) carry no media timecode origin, so frame 0 was assumed`,
      remedy:
        'Supply media_start_tc_frame (or an absolute src_tc_frame) per clip. Resolve ' +
        'measures source_range against the media\'s real timecode range, so an event ' +
        'that guesses only imports if the media truly starts at 00:00:00:00 — otherwise ' +
        'the file opens and creates no timeline.',
      events: assumed,
    });
  }
  // A .drt has no per-clip speed field, so a retime cannot ride into one.
  if (authored.flattened && authored.flattened.length) {
    warnings.push({
      id: 'retimes_flattened',
      detail: `${authored.flattened.length} event(s) lost a speed change in the .drt`,
      remedy: 'Author OTIO instead — it carries LinearTimeWarp — or re-apply the retimes by hand.',
      events: authored.flattened,
    });
  }

  process.stdout.write(
    JSON.stringify({
      ok: true,
      target: authored.target,
      outputPath,
      bytes: payload.length,
      eventCount: events.length,
      warnings,
    }),
  );
}

main().catch((error) => {
  process.stdout.write(JSON.stringify({ ok: false, error: String(error.message || error) }));
  process.exit(1);
});
