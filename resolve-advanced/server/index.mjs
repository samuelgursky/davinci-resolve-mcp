/**
 * davinci-resolve-advanced-mcp — MCP server (stdio).
 *
 * The "beyond-the-API" sibling to the live Python davinci-resolve-mcp: authors
 * and edits DaVinci Resolve files (.drp/.drt/.drx) with no Resolve running.
 * Runs cloud or local. Tools dispatch on an `action` enum, mirroring the
 * Python server's shape.
 */

// CRITICAL (stdio MCP): stdout is the JSON-RPC channel — any stray write
// corrupts the protocol. Several vendored libs (e.g. drx-generator) use
// console.log for debug output. Redirect the stdout-bound console methods to
// stderr BEFORE anything else loads, so vendored chatter can't break the wire.
for (const m of ['log', 'info', 'debug']) {
  const orig = console[m].bind(console);
  console[m] = (...a) => {
    try {
      process.stderr.write(a.map(String).join(' ') + '\n');
    } catch {
      orig(...a);
    }
  };
}

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';

import { drpTool } from './tools/drp.mjs';
import { drtTool } from './tools/drt.mjs';
import { drxTool } from './tools/drx.mjs';
import { offlineRefTool } from './tools/offline_ref.mjs';
import { fusionTool } from './tools/fusion.mjs';
import { audioPlanTool } from './tools/audio_plan.mjs';
import { fairlightTool } from './tools/fairlight.mjs';
import { audioTool } from './tools/audio.mjs';
import { conformTool } from './tools/conform.mjs';
import { projectDbTool } from './tools/project_db.mjs';
import { projectReadTool } from './tools/project_read.mjs';
import { colorTraceTool } from './tools/color_trace.mjs';
import { capabilitiesTool } from './tools/capabilities.mjs';
import { pipelineTool } from './tools/pipeline.mjs';
import { deliverableTool } from './tools/deliverable.mjs';
import { mediaTool } from './tools/media.mjs';
import { editorialTool } from './tools/editorial.mjs';
import { provenanceTool } from './tools/provenance.mjs';
import { logCapabilities } from './capabilities.mjs';

const TOOLS = [
  drpTool,
  drtTool,
  drxTool,
  offlineRefTool,
  fusionTool,
  audioPlanTool,
  fairlightTool,
  audioTool,
  conformTool,
  projectDbTool,
  projectReadTool,
  colorTraceTool,
  capabilitiesTool,
  pipelineTool,
  deliverableTool,
  mediaTool,
  editorialTool,
  provenanceTool,
];
const NAME = 'davinci-resolve-advanced-mcp';
const VERSION = '0.0.0-dev';

const toContent = (payload) => ({ content: [{ type: 'text', text: JSON.stringify(payload, null, 2) }] });
const toError = (err) => ({
  isError: true,
  content: [{ type: 'text', text: JSON.stringify({ error: err?.message || String(err) }, null, 2) }],
});

export async function startServer() {
  const server = new McpServer({ name: NAME, version: VERSION }, { capabilities: { tools: {} } });

  for (const tool of TOOLS) {
    server.registerTool(
      tool.name,
      {
        description: tool.description,
        inputSchema: {
          action: z.string().describe('Action name within this tool'),
          args: z.object({}).passthrough().optional().describe('Action arguments'),
        },
      },
      async ({ action, args }) => {
        try {
          return toContent(await tool.handler({ action, args: args || {} }));
        } catch (err) {
          return toError(err);
        }
      },
    );
  }

  await server.connect(new StdioServerTransport());
  // stdio MCP servers must never write to stdout (it's the protocol channel).
  process.stderr.write(`[${NAME}] ready — ${TOOLS.length} tools registered\n`);
  logCapabilities();
}
