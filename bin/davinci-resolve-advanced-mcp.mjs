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

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const serverEntry = path.resolve(__dirname, '..', 'resolve-advanced', 'server', 'index.mjs');

const { startServer } = await import(pathToFileURL(serverEntry).href);
await startServer();
