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
  return process.env.AAF_PROBE_PYTHON || process.env.PYTHON || 'python3';
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
 * Parse an AAF into a FLAT normalized-event list (mirrors parseEDL/parseOTIO/parseXMEML output),
 * concatenating every top-level sequence. Use listAafSequences() when you need per-sequence split.
 * @param {string} contentOrPath absolute .aaf path
 * @returns {Promise<Array>} normalized events
 */
export async function parseAAF(contentOrPath) {
  const aafPath = resolveAafPath(contentOrPath);
  const { sequences } = await runProbe(aafPath);
  const events = [];
  for (const seq of sequences || []) for (const ev of seq.events || []) events.push(ev);
  return events;
}

/**
 * Enumerate the sequences inside an AAF for the picker.
 * @param {string} contentOrPath absolute .aaf path
 * @returns {Promise<Array<{id:string,name:string,eventCount:number}>>}
 */
export async function listAafSequences(contentOrPath) {
  const aafPath = resolveAafPath(contentOrPath);
  const { sequences } = await runProbe(aafPath);
  return (sequences || []).map((s) => ({ id: String(s.id), name: String(s.name), eventCount: Number(s.eventCount || 0) }));
}
