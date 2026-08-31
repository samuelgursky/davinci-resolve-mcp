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
import path from 'node:path';

// Node floor (package.json engines: >=20.9), enforced at STARTUP rather than
// discovered per-feature: under an old Node the pure-JS tools limp along
// while native-dep paths (better-sqlite3: project_read, fairlight DB actions,
// offline_ref live linking) die with a cryptic NODE_MODULE_VERSION mismatch —
// measured live under nvm's v18.20.8, which is exactly what a bare "node"
// command in an MCP registration resolves to on a machine whose shell
// default lags. Silent degradation is this repo's least favorite failure
// mode; refuse loudly with the fix instead.
const [major, minor] = process.versions.node.split('.').map(Number);
if (major < 20 || (major === 20 && minor < 9)) {
  process.stderr.write(
    `[davinci-resolve-advanced-mcp] Node ${process.versions.node} is below the ` +
    `supported floor (>=20.9). This process was started by: ${process.execPath}\n` +
    `Fix: point the MCP registration's command at a Node >=20.9 binary ` +
    `(e.g. the absolute path from \`nvm which 20\`), or update the default ` +
    `node on PATH. Re-running install.py also rewrites client configs with ` +
    `an absolute, version-checked node path.\n`,
  );
  process.exit(1);
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const serverEntry = path.resolve(__dirname, '..', 'resolve-advanced', 'server', 'index.mjs');

const { startServer } = await import(pathToFileURL(serverEntry).href);
await startServer();
