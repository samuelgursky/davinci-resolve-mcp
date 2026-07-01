/**
 * Safe Archive Entry Validation
 *
 * SECURITY: classic "ZIP slip" — an archive entry named `../../etc/passwd` or
 * `/etc/passwd` will, on naive extractors, write outside the destination tree.
 * Modern unzip (6.0-26+) and adm-zip (0.5.10+) refuse this, but we still own
 * upstream validation so a renamed entry can't poison object/Map keys via
 * prototype pollution either.
 */

const path = require('path');

/**
 * True if an archive entry name is safe to write or use as a key.
 *
 * Rejects:
 *  - absolute paths (Unix `/foo`, Windows `C:\foo` or `\\foo`)
 *  - any segment equal to `..`
 *  - any segment equal to `__proto__`, `constructor`, or `prototype`
 *    (these collide with JS prototype access if used as object keys)
 *  - null bytes
 *  - empty names
 */
function isSafeArchiveEntryName(entryName) {
  if (typeof entryName !== 'string' || entryName.length === 0) return false;
  if (entryName.includes('\0')) return false;
  if (path.isAbsolute(entryName)) return false;
  // Windows-style absolute or UNC
  if (/^[A-Za-z]:[\\/]/.test(entryName) || entryName.startsWith('\\\\')) return false;

  const segments = entryName.split(/[\\/]/);
  for (const seg of segments) {
    if (seg === '..') return false;
    if (seg === '__proto__' || seg === 'constructor' || seg === 'prototype') return false;
  }
  return true;
}

/**
 * True if `resolvedPath` resolves inside `destDir`. Use after joining the
 * entry name to the destination directory to defend against escape via
 * symlinks or unusual path normalization quirks.
 */
function isContainedIn(resolvedPath, destDir) {
  const abs = path.resolve(resolvedPath);
  const baseAbs = path.resolve(destDir);
  const baseWithSep = baseAbs.endsWith(path.sep) ? baseAbs : baseAbs + path.sep;
  return abs === baseAbs || abs.startsWith(baseWithSep);
}

module.exports = {
  isSafeArchiveEntryName,
  isContainedIn,
};
