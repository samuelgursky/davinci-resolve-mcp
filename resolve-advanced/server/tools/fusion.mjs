/**
 * fusion tool — declarative Fusion composition (.comp) authoring (offline).
 *
 * generate — spec →.comp text (optionally written to outputPath)
 * generate_from_template — named template + params →.comp
 * list_templates — available built-in templates
 * to_api_calls — spec → equivalent davinci-resolve-mcp Fusion API calls
 */

import fs from 'node:fs/promises';
import { z } from 'zod';
import { fusion } from '../libs.mjs';

const generateSchema = z.object({
  spec: z.object({}).passthrough().describe('Composition spec: { nodes, connections,... }'),
  outputPath: z.string().optional().describe('If set, write the.comp here'),
});
const fromTemplateSchema = z.object({
  templateName: z.string(),
  params: z.object({}).passthrough().optional(),
  outputPath: z.string().optional(),
});
const toApiSchema = z.object({ spec: z.object({}).passthrough() });

function asText(out) {
  return typeof out === 'string' ? out : out?.comp || out?.content || out?.text || JSON.stringify(out);
}

export const fusionTool = {
  name: 'fusion',
  description:
    'Declarative Fusion composition (.comp) authoring — offline, no Resolve required. Actions: generate, generate_from_template, list_templates, to_api_calls.',
  async handler({ action, args }) {
    const fx = fusion();
    if (action === 'generate') {
      const p = generateSchema.parse(args);
      const out = fx.generateComp(p.spec);
      const text = asText(out);
      if (p.outputPath) {
        await fs.writeFile(p.outputPath, text);
        return { outputPath: p.outputPath, bytes: Buffer.byteLength(text) };
      }
      return { comp: text };
    }
    if (action === 'generate_from_template') {
      const p = fromTemplateSchema.parse(args);
      const out = fx.generateFromTemplate(p.templateName, p.params || {});
      const text = asText(out);
      if (p.outputPath) {
        await fs.writeFile(p.outputPath, text);
        return { outputPath: p.outputPath, bytes: Buffer.byteLength(text) };
      }
      return { comp: text };
    }
    if (action === 'list_templates') {
      return { templates: fx.listTemplates() };
    }
    if (action === 'to_api_calls') {
      const p = toApiSchema.parse(args);
      return { apiCalls: fx.specToApiCalls(p.spec) };
    }
    throw new Error(`Unknown fusion action: ${action}`);
  },
};
