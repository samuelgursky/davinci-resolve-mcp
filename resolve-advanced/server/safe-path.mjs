// File names built from caller data (clip ids, group and scene names).
//
// A clip id such as "../../x" interpolated into `${outDir}/${id}.drx` writes
// outside outDir (GHSA-c3m4-m58c-4pc7). Values are refused rather than
// rewritten: sanitising "a/b" and "a_b" to the same name would let one clip's
// grade overwrite another's in the same run.
import path from 'node:path';

const SAFE_COMPONENT = /^[A-Za-z0-9 ._-]{1,200}$/;

/** Whether a caller value can be used as part of a file name. */
export function isSafeFileComponent(value) {
  const name = String(value);
  return SAFE_COMPONENT.test(name) && !/^\.+$/.test(name);
}

/**
 * The path of `name` directly inside `dir`, or null when `name` is not a plain
 * file name. `name` is checked as a whole after the caller's parts are joined.
 */
export function fileInside(dir, name) {
  if (!isSafeFileComponent(name)) return null;
  const root = path.resolve(dir);
  const out = path.resolve(root, String(name));
  return path.dirname(out) === root ? out : null;
}

/**
 * Like fileInside, but every caller-supplied part is checked on its own and a
 * refusal throws, naming the field. `parts` maps field name → value.
 */
export function outputFileIn(dir, parts, suffix) {
  for (const [field, value] of Object.entries(parts)) {
    if (!isSafeFileComponent(value)) {
      throw new Error(`${field} ${JSON.stringify(String(value))} is not a safe file name: use letters, digits, spaces, ".", "_" or "-"`);
    }
  }
  const out = fileInside(dir, `${Object.values(parts).map(String).join('_')}${suffix}`);
  if (!out) throw new Error(`output file name for ${Object.keys(parts).join('/')} is not a safe file name`);
  return out;
}
