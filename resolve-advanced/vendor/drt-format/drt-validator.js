/**
 * DRT validator — structural integrity check.
 *
 * Returns { valid: bool, errors: [{ code, path?, message }] } per the
 * harness's documented contract. Does NOT depend on drp-format's
 * drp-validator (broken `safe-archive` require).
 *
 * Validation rules:
 *   - zip-open       must open as a valid zip
 *   - no-seq         at least one SeqContainer*.xml entry present
 *   - has-project    DRT must NOT have project.xml (DRP-vs-DRT signal)
 *   - seq-schema     each SeqContainer XML has <Sm2SequenceContainer>
 *                    root with required scalar fields (Name, FrameRate)
 *   - orphan-media   any <MediaFilePath> referenced should not also be
 *                    empty; we DO NOT yet check fs existence (path
 *                    resolution is consumer territory)
 *
 * @module drt-format/drt-validator
 */

const fs = require('node:fs/promises');
const JSZip = require('jszip');

async function validateDRT(drtPathOrBuffer) {
  const errors = [];

  let buf;
  if (Buffer.isBuffer(drtPathOrBuffer)) {
    buf = drtPathOrBuffer;
  } else if (typeof drtPathOrBuffer === 'string') {
    try {
      buf = await fs.readFile(drtPathOrBuffer);
    } catch (e) {
      return { valid: false, errors: [{ code: 'read-failed', message: e.message }] };
    }
  } else {
    return { valid: false, errors: [{ code: 'bad-input', message: 'expected a string path or a Buffer' }] };
  }

  let zip;
  try {
    zip = await JSZip.loadAsync(buf);
  } catch (e) {
    return { valid: false, errors: [{ code: 'zip-open', message: `failed to open zip: ${e.message}` }] };
  }

  const seqEntries = [];
  let hasProject = false;
  zip.forEach((p, e) => {
    if (e.dir) return;
    // Match both tool-authored SeqContainer<N>.xml and real Resolve SeqContainer/<uuid>.xml.
    if (/(^|\/)SeqContainer(\d*\.xml|\/[^/]+\.xml)$/.test(p)) seqEntries.push(p);
    if (/(^|\/)project\.xml$/.test(p)) hasProject = true;
  });

  if (seqEntries.length === 0) {
    errors.push({ code: 'no-seq', message: 'DRT must contain at least one SeqContainer*.xml' });
  }

  if (hasProject) {
    errors.push({
      code: 'has-project',
      message: 'DRT must NOT contain project.xml (use parseDRP for a DRP archive)',
    });
  }

  for (const p of seqEntries) {
    const xml = await zip.file(p).async('string');
    if (!/<Sm2SequenceContainer\b/.test(xml)) {
      errors.push({ code: 'seq-schema', path: p, message: 'missing <Sm2SequenceContainer> root' });
      continue;
    }
    if (!/<Name>[\s\S]*?<\/Name>/.test(xml)) {
      errors.push({ code: 'seq-schema', path: p, message: 'missing required <Name> field' });
    }
    if (!/<FrameRate>[\s\S]*?<\/FrameRate>/.test(xml)) {
      errors.push({ code: 'seq-schema', path: p, message: 'missing required <FrameRate> field' });
    }
    // Orphan-media: empty MediaFilePath strings.
    const mfpRe = /<MediaFilePath>([\s\S]*?)<\/MediaFilePath>/g;
    let m;
    let emptyCount = 0;
    while ((m = mfpRe.exec(xml)) !== null) {
      if (m[1].trim() === '') emptyCount += 1;
    }
    if (emptyCount > 0) {
      errors.push({
        code: 'orphan-media',
        path: p,
        message: `${emptyCount} clip(s) reference empty MediaFilePath`,
      });
    }
  }

  return { valid: errors.length === 0, errors };
}

module.exports = { validateDRT };
