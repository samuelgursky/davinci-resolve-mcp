'use strict';

/**
 * packaging/relink.js — produce a RELINK package: rewrite a turnover's media
 * pathurls to their real resolved locations via the media index (exact basename,
 * then fuzzy true-source for moved/renamed media). This is the §9 true-source
 * search applied to the whole turnover — turns an offline turnover into a
 * grade-ready, relinked timeline. Pure (string rewrite + injected MediaIndex).
 */

function decode(s) {
  try {
    return decodeURIComponent(s);
  } catch (e) {
    return s;
  }
}

/**
 * @param {string} xml         the turnover XMEML
 * @param {MediaIndex} mediaIndex
 * @param {object} opts        { minScore }
 * @returns {{ xml, resolved:[{base,path,how}], unresolved:string[] }}
 */
function resolvePathurls(xml, mediaIndex, opts = {}) {
  const minScore = opts.minScore != null ? opts.minScore : 0.55;
  const resolved = [];
  const unresolved = [];
  const out = xml.replace(/<pathurl>file:\/\/localhost([^<]+)<\/pathurl>/g, (m, enc) => {
    const base = decode(enc).split('/').pop();
    let real = mediaIndex.byBasename(base);
    let how = 'exact';
    if (!real) {
      const f = mediaIndex.findTrueSource(base, { minScore });
      if (f) {
        real = f.path;
        how = `fuzzy:${f.score.toFixed(2)}`;
      }
    }
    if (!real) {
      unresolved.push(base);
      return m;
    }
    resolved.push({ base, path: real, how });
    return `<pathurl>file://localhost${encodeURI(real)}</pathurl>`;
  });
  return { xml: out, resolved, unresolved };
}

module.exports = { resolvePathurls };
