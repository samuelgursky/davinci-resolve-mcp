#!/usr/bin/env node
/**
 * davinci-resolve-advanced-mcp — entry point.
 *
 * The Node, beyond-the-API sibling bin to davinci-resolve-mcp. Authors/edits
 * DaVinci Resolve files (.drp/.drt/.drx) offline — no Resolve, cloud or local.
 *
 * Boots the stdio MCP server in resolve-advanced/server. (During dev the
 * vendored libs + deps live under resolve-advanced/; Phase 4 promotes deps to
 * the repo root for the published package.)
 */

import { fileURLToPath, pathToFileURL } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.resolve(__dirname, '..');
const packageJson = JSON.parse(fs.readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
const version = packageJson.version || '0.0.0-dev';

function usage() {
  return `DaVinci Resolve Advanced MCP ${version}

Usage:
  davinci-resolve-advanced-mcp
  davinci-resolve-advanced-mcp --version
  davinci-resolve-advanced-mcp --help
  davinci-resolve-advanced-mcp --node-check   (which Node the server would run under)

Starts the offline DaVinci Resolve advanced MCP server over stdio.
`;
}

const command = process.argv[2];
if (command === '--help' || command === '-h' || command === 'help') {
  process.stdout.write(usage());
  process.exit(0);
}
if (command === '--version' || command === '-v' || command === 'version') {
  process.stdout.write(`${version}\n`);
  process.exit(0);
}

// Node floor (package.json engines: >=20.9), enforced at STARTUP rather than
// discovered per-feature: under an old Node the pure-JS tools limp along
// while native-dep paths (better-sqlite3: project_read, fairlight DB actions,
// offline_ref live linking) die with a cryptic NODE_MODULE_VERSION mismatch —
// measured live under nvm's v18.20.8, which is exactly what a bare "node"
// command in an MCP registration resolves to on a machine whose shell
// default lags. Silent degradation is this repo's least favorite failure
// mode; refuse loudly with the fix instead.
//
// Self-heal (2026-09-09, after the registration landed on v18 for the second
// time): before refusing, look for a Node >=20.9 on this machine (an explicit
// DAVINCI_RESOLVE_NODE, nvm's versions dir newest-first, Homebrew/system
// paths), re-exec this launcher under it with the same stdio, and say so on
// stderr. The registration can then point at any node and still come up.
// DAVINCI_RESOLVE_ADVANCED_ASSUME_NODE fakes the running version (tests);
// DAVINCI_RESOLVE_ADVANCED_NO_NODE_SEARCH=1 limits the search to the explicit
// override; the re-exec marks itself so a bad replacement cannot loop.
const runningNode = process.env.DAVINCI_RESOLVE_ADVANCED_ASSUME_NODE || process.versions.node;
const [major, minor] = runningNode.split('.').map(Number);
if (major < 20 || (major === 20 && minor < 9)) {
  const refusal = (extra = '') =>
    `[davinci-resolve-advanced-mcp] Node ${runningNode} is below the ` +
    `supported floor (>=20.9). This process was started by: ${process.execPath}\n` +
    `Fix: point the MCP registration's command at a Node >=20.9 binary ` +
    `(e.g. the absolute path from \`nvm which 20\`), or update the default ` +
    `node on PATH. Re-running install.py also rewrites client configs with ` +
    `an absolute, version-checked node path.\n${extra}`;
  let picked = null;
  const probed = [];
  if (!process.env.DAVINCI_RESOLVE_ADVANCED_REEXEC) {
    try {
      // Sibling module; a managed install that only received this file falls
      // through to the plain refusal instead of dying on the import.
      const floor = await import(pathToFileURL(path.join(__dirname, 'node-floor.mjs')).href);
      const candidates = process.env.DAVINCI_RESOLVE_ADVANCED_NO_NODE_SEARCH
        ? [process.env.DAVINCI_RESOLVE_NODE].filter(Boolean)
        : floor.candidateNodeBinaries();
      picked = floor.findReplacementNode({ candidates, probed });
    } catch (err) {
      probed.push({
        path: '(search unavailable)',
        version: null,
        error: String(err && err.message ? err.message : err),
      });
    }
  }
  if (picked) {
    process.stderr.write(
      `[davinci-resolve-advanced-mcp] Node ${runningNode} is below the supported floor (>=20.9); ` +
        `re-executing under ${picked.path} (Node ${picked.version}). ` +
        `Point the MCP registration's command at that path to skip this step.\n`,
    );
    const { spawnSync } = await import('node:child_process');
    const child = spawnSync(picked.path, [fileURLToPath(import.meta.url), ...process.argv.slice(2)], {
      stdio: 'inherit',
      env: {
        ...process.env,
        DAVINCI_RESOLVE_ADVANCED_REEXEC: '1',
        DAVINCI_RESOLVE_ADVANCED_ASSUME_NODE: '',
      },
    });
    process.exit(child.status === null ? 1 : child.status);
  }
  const probedLine = probed.length
    ? `No usable replacement found; probed: ${probed.map((p) => `${p.path} (${p.version || (p.error ? p.error : 'not node')})`).join(', ')}\n`
    : '';
  process.stderr.write(refusal(probedLine));
  process.exit(1);
}

// After the floor: reports the Node the server actually runs under, including
// a self-heal re-exec — the answer to "which node is the registration using?"
if (command === '--node-check') {
  process.stdout.write(
    `${JSON.stringify({ node: process.versions.node, execPath: process.execPath, reexec: process.env.DAVINCI_RESOLVE_ADVANCED_REEXEC === '1' })}\n`,
  );
  process.exit(0);
}

const advancedRoot = path.resolve(packageRoot, 'resolve-advanced');
const serverEntry = path.join(advancedRoot, 'server', 'index.mjs');

// Preflight, for the same reason as the Node floor above: a managed install
// that never received resolve-advanced/ (or its deps) otherwise dies with a
// bare ERR_MODULE_NOT_FOUND before the MCP handshake, and the client reports
// only "subprocess closed stdout before responding" — a stack trace with no
// fix in it. Issue #179. Say what is missing and how to repair it.
function missingRuntimePieces() {
  if (!fs.existsSync(serverEntry)) {
    return { what: `the advanced server tree (${serverEntry} is missing)` };
  }
  let required = [];
  try {
    const manifest = JSON.parse(fs.readFileSync(path.join(advancedRoot, 'package.json'), 'utf8'));
    required = Object.keys(manifest.dependencies || {});
  } catch {
    return {
      what: `resolve-advanced/package.json (cannot tell which deps are required)`,
    };
  }
  const modulesDir = path.join(advancedRoot, 'node_modules');
  const missing = required.filter((dep) => !fs.existsSync(path.join(modulesDir, ...dep.split('/'))));
  // Deps may also be hoisted above the package (an npm/npx install puts them in
  // a parent node_modules), so an empty local node_modules is not conclusive —
  // only report deps the resolver genuinely cannot see.
  const unresolvable = missing.filter((dep) => {
    try {
      import.meta.resolve(dep);
      return false;
    } catch {
      return true;
    }
  });
  return unresolvable.length ? { what: `dependencies: ${unresolvable.join(', ')}` } : null;
}

const gap = missingRuntimePieces();
if (gap) {
  process.stderr.write(
    `[davinci-resolve-advanced-mcp] cannot start: ${gap.what}.\n` +
      `This install is at ${packageRoot}.\n` +
      `Fix: run \`npx davinci-resolve-mcp setup\` to repair the managed install ` +
      `(it syncs resolve-advanced/ and installs its Node dependencies), or run the ` +
      `server straight from the package with ` +
      `\`npx -y --package davinci-resolve-mcp davinci-resolve-advanced-mcp\`.\n`,
  );
  process.exit(1);
}

const { startServer } = await import(pathToFileURL(serverEntry).href);
await startServer();
