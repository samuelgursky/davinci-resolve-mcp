/**
 * AAF (.aaf) offline reader — the honest bridge for `parse_interchange` / `list_sequences`.
 *
 * AAF is a binary Structured-Storage container; no pure-JS reader is trustworthy, so we shell
 * out to `aaf_probe.py` (pure-Python `aaf2`/pyaaf2). This keeps the honest-refuse philosophy:
 *   - real parse when pyaaf2 is available,
 *   - a CLEAR, actionable error otherwise (never a fake/empty parse).
 *
 * The live import path does NOT use this — Resolve reads AAF natively via
 * timeline.import_timeline_checked. This is only for the offline picker+preview.
 */
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const PROBE = fileURLToPath(new URL('./aaf_probe.py', import.meta.url));

/** python interpreter — overridable for environments/tests (must have `aaf2` importable). */
function pythonCmd() {
  if (process.env.AAF_PROBE_PYTHON) return process.env.AAF_PROBE_PYTHON;
  if (process.env.PYTHON) return process.env.PYTHON;
  // The repo venv carries pyaaf2; a bare python3 usually does not. Prefer it
  // when present so the tool path works without env plumbing.
  const venvPy = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'venv', 'bin', 'python');
  if (existsSync(venvPy)) return venvPy;
  return 'python3';
}

const REMEDIATION =
  'Install the offline AAF reader (`pip install pyaaf2`) to preview AAF without Resolve, ' +
  'OR convert to OTIO/EDL/FCP7-XML upstream, OR import it live via timeline.import_timeline_checked ' +
  '(Resolve reads AAF natively).';

function runProbe(aafPath) {
  return new Promise((resolve, reject) => {
    let child;
    try {
      child = spawn(pythonCmd(), [PROBE, aafPath]);
    } catch (e) {
      reject(new Error(`AAF offline preview needs Python + pyaaf2, but Python could not start (${e.message}). ${REMEDIATION}`));
      return;
    }
    let out = '';
    let err = '';
    child.stdout.on('data', (d) => (out += d));
    child.stderr.on('data', (d) => (err += d));
    child.on('error', (e) => {
      // ENOENT etc. — python not found.
      reject(new Error(`AAF offline preview needs Python + pyaaf2, but '${pythonCmd()}' could not start (${e.message}). ${REMEDIATION}`));
    });
    child.on('close', (code) => {
      if (code === 0) {
        try {
          resolve(JSON.parse(out));
        } catch (e) {
          reject(new Error(`AAF probe returned unreadable output: ${e.message}`));
        }
        return;
      }
      if (code === 3 || /AAF_PROBE_NO_PYAAF2/.test(err)) {
        reject(new Error(`AAF offline preview needs the pure-Python 'aaf2' package (pyaaf2), which is not installed. ${REMEDIATION}`));
        return;
      }
      if (code === 4 || /AAF_PROBE_UNREADABLE/.test(err)) {
        const detail = (err.match(/AAF_PROBE_UNREADABLE:\s*(.*)/) || [, err.trim()])[1];
        reject(new Error(`AAF could not be read: ${detail || 'unreadable or not a valid AAF file'}.`));
        return;
      }
      reject(new Error(`AAF probe failed (exit ${code}): ${err.trim() || 'unknown error'}. ${REMEDIATION}`));
    });
  });
}

/** Resolve the AAF path from the tool's `content`/`path` arg (AAF is binary — must be a path). */
export function resolveAafPath(contentOrPath) {
  const p = typeof contentOrPath === 'string' ? contentOrPath.trim() : '';
  if (!p) {
    throw new Error('AAF is a binary format — pass the .aaf file PATH as `content` (or `path`), not inline bytes/text.');
  }
  if (!existsSync(p)) {
    throw new Error(`AAF path does not exist: ${p}`);
  }
  return path.resolve(p);
}

/**
 * Per-sequence summary WITHOUT its events — the picker row, plus the sequence-level facts
 * a conform needs before it places anything.
 *
 * `startTimecode`/`startFrame` are carried deliberately: an AAF that starts at 00:59:50:00
 * built against Resolve's default 01:00:00:00 start puts every clip ten seconds out, and
 * the misalignment only shows up against a linked picture reference. They are null (not
 * absent) when the AAF has no timecode slot — an explicit "no start timecode here" rather
 * than a guess. `startFrame` is expressed at `startTimecodeFps`.
 */
function sequenceSummary(s) {
  const out = {
    id: String(s.id),
    name: String(s.name),
    eventCount: Number(s.eventCount || 0),
    startTimecode: s.startTimecode ?? null,
    startFrame: s.startFrame ?? null,
    startTimecodeFps: s.startTimecodeFps ?? null,
    startTimecodeDrop: s.startTimecodeDrop ?? null,
  };
  if (s.unhandled && Object.keys(s.unhandled).length) out.unhandled = s.unhandled;
  return out;
}

/**
 * Parse an AAF into a FLAT normalized-event list (mirrors parseEDL/parseOTIO/parseXMEML output),
 * concatenating every top-level sequence. Use listAafSequences() when you need per-sequence split,
 * or parseAafDocument() when you also need the sequence-level start timecode.
 * @param {string} contentOrPath absolute .aaf path
 * @returns {Promise<Array>} normalized events
 */
export async function parseAAF(contentOrPath) {
  return (await parseAafDocument(contentOrPath)).events;
}

/**
 * Parse an AAF into flat events PLUS the per-sequence summaries they came from.
 *
 * parseAAF() flattens every sequence into one event list, which drops the sequence-level
 * start timecode with it — so a caller that needs to know where the timeline starts had
 * to re-run the probe. This returns both from a single probe run.
 * @param {string} contentOrPath absolute .aaf path
 * @returns {Promise<{events: Array, sequences: Array}>}
 */
export async function parseAafDocument(contentOrPath) {
  const aafPath = resolveAafPath(contentOrPath);
  const { sequences } = await runProbe(aafPath);
  const events = [];
  for (const seq of sequences || []) for (const ev of seq.events || []) events.push(ev);
  // Summaries PLUS each sequence's own events — the assemble picker needs
  // per-sequence events without a second probe run.
  return { events, sequences: (sequences || []).map((sq) => ({ ...sequenceSummary(sq), events: sq.events || [] })) };
}

/**
 * Enumerate the sequences inside an AAF for the picker.
 *
 * `unhandled` is carried through deliberately: a structural miss in the probe
 * (a component class it cannot walk) otherwise looks identical to a genuinely
 * empty timeline, and the caller would gate on a successful parse and conform
 * nothing. A NestedScope — Avid's multi-layer video stack — used to land in
 * exactly that hole: eventCount 0 alongside ok:true. Absent means clean.
 * @param {string} contentOrPath absolute .aaf path
 * @returns {Promise<Array<{id:string,name:string,eventCount:number,startTimecode:?string,startFrame:?number,unhandled?:Object}>>}
 */
export async function listAafSequences(contentOrPath) {
  const aafPath = resolveAafPath(contentOrPath);
  const { sequences } = await runProbe(aafPath);
  return (sequences || []).map(sequenceSummary);
}
