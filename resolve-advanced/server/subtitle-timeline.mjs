/** Edit exported native timelines, never the open Project.db. */
import fs from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { createRequire } from 'node:module';
import JSZip from 'jszip';
import { subtitleSchemas, planCaptionEdit } from './subtitle-db.mjs';
const require = createRequire(import.meta.url);
const { decodePreset, setPresetInputs } = require('../vendor/drp-format/subtitle-preset.js');
const { decodeCaption } = require('../vendor/drp-format/subtitle-captions.js');
const REFERENCES = { 'Word Highlight': 'word-highlight-track.xml', Lollipop: 'lollipop-track.xml' };

async function readTimeline(path) {
  const zip = await JSZip.loadAsync(await fs.readFile(path));
  const entries = Object.keys(zip.files).filter(n => /^SeqContainer\/[^/]+\.xml$/.test(n));
  if (entries.length !== 1 || !zip.file('project.xml')) throw new Error('Expected a native single-timeline DRT export');
  const entry = entries[0], xml = await zip.file(entry).async('string');
  return { zip, entry, xml };
}
function selectedTrack(xml, index) {
  const vec = /<SubtitleTrackVec>([\s\S]*?)<\/SubtitleTrackVec>/.exec(xml);
  if (!vec) throw new Error('No subtitle tracks in exported timeline');
  const tracks = [...vec[1].matchAll(/<Sm2TiTrack\b[^>]*>[\s\S]*?<\/Sm2TiTrack>/g)];
  if (!Number.isInteger(index) || index < 1 || !tracks[index - 1]) throw new Error('Subtitle track index out of range');
  const match = tracks[index - 1];
  return { text: match[0], offset: vec.index + vec[0].indexOf(vec[1]) + match.index };
}
function holder(track) {
  const match = /<FusionCompHolderItems>([\s\S]*?)<\/FusionCompHolderItems>/.exec(track);
  if (!match || !match[1].trim()) return null;
  const comps = [...match[1].matchAll(/<CompositionBA>([0-9a-fA-F]+)<\/CompositionBA>/g)];
  if (comps.length !== 1) throw new Error('Expected exactly one subtitle preset composition');
  return { text: match[0], hex: comps[0][1], decoded: decodePreset(Buffer.from(comps[0][1], 'hex')) };
}
function freshIds(xml) {
  const ids = new Map([...xml.matchAll(/\bDbId="([0-9a-f-]{36})"/gi)].map(m => [m[1], randomUUID()]));
  // Only IDs owned by the sequence are changed; media references stay intact.
  return xml.replace(/[0-9a-f-]{36}/gi, id => ids.get(id) || id);
}
export async function inspectSubtitleTimeline({ source, track = 1 }) {
  const exported = await readTimeline(source);
  const current = holder(selectedTrack(exported.xml, track).text);
  if (!current) throw new Error('No animation preset on subtitle track');
  return current.decoded;
}
export async function editSubtitleTimeline({ source, output, track = 1, inputs = {}, preset, preset_reference, reference_track = 1, title_reference, template_id }) {
  // Reuse the DB codec's exact input validation, without invoking a DB action.
  const parsed = subtitleSchemas.set_subtitle_preset.parse({ timeline: 'export', track, inputs });
  if (preset != null && !Object.hasOwn(REFERENCES, preset) && !title_reference) throw new Error('Unsupported subtitle preset');
  if (!Object.keys(parsed.inputs).length && !preset_reference && !preset && !title_reference) throw new Error('Supply inputs, preset, or preset_reference');
  if (source === output || preset_reference === output || title_reference === output) throw new Error('Output must be a new file');
  const exported = await readTimeline(source), target = selectedTrack(exported.xml, track);
  const before = holder(target.text);
  let chosen = before;
  if (preset && Object.hasOwn(REFERENCES, preset) && !title_reference) chosen = holder(await fs.readFile(new URL(`../assets/${REFERENCES[preset]}`, import.meta.url), 'utf8'));
  if (preset_reference) chosen = holder(selectedTrack((await readTimeline(preset_reference)).xml, reference_track).text);
  if (title_reference) {
    if (!template_id?.startsWith('Templates/Edit/Titles/Subtitles/')) throw new Error('Native title reference must identify a subtitle template');
    const native = await readTimeline(title_reference);
    const matches = [...native.xml.matchAll(/<CompositionBA>([0-9a-fA-F]+)<\/CompositionBA>/g)]
      .map(m => ({ hex: m[1], decoded: decodePreset(Buffer.from(m[1], 'hex')) }))
      .filter(m => m.decoded.templateId === template_id);
    if (matches.length !== 1) throw new Error('Native title reference must contain exactly one matching composition');
    const scaffold = before ?? holder(await fs.readFile(new URL('../assets/lollipop-track.xml', import.meta.url), 'utf8'));
    chosen = { ...matches[0], text: scaffold.text.replace(scaffold.hex, () => matches[0].hex) };
  }
  if (!chosen) throw new Error('No animation preset: supply a native preset_reference DRT or apply Word Highlight through the live Effects UI');
  const patched = Object.keys(parsed.inputs).length
    ? setPresetInputs(Buffer.from(chosen.hex, 'hex'), parsed.inputs) : Buffer.from(chosen.hex, 'hex');
  const section = freshIds(chosen.text.replace(chosen.hex, () => patched.toString('hex')));
  let text;
  if (before) text = target.text.replace(before.text, () => section);
  else if (/<FusionCompHolderItems\s*\/>/.test(target.text)) text = target.text.replace(/<FusionCompHolderItems\s*\/>/, () => section);
  else throw new Error('Unsupported track: missing FusionCompHolderItems field');
  const xml = exported.xml.slice(0, target.offset) + text + exported.xml.slice(target.offset + target.text.length);
  // Resolve remaps timeline identity on import. Keep cross-entry sequence
  // references intact; remapping only SeqContainer loses subtitle tracks.
  exported.zip.file(exported.entry, xml);
  const buffer = await exported.zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' });
  await fs.writeFile(output, buffer, { flag: 'wx' });
  const decoded = decodePreset(patched);
  return { output, templateId: chosen.decoded.templateId, before: before?.decoded.inputs ?? null, after: decoded.inputs,
    editableInputs: decoded.editableInputs,
    verification: 'exported_preset_readback', restart_required: false };
}

// Caption items: same FieldsBlob codec as Project.db write_captions, but on the exported DRT.
const xmlEscape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const xmlUnescape = (s) => s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, '&');
const tag = (xml, name) => {
  const m = new RegExp(`<${name}>([^<]*)</${name}>|<${name}/>`).exec(xml);
  if (!m) throw new Error(`caption item missing ${name}`);
  return m[1] ?? '';
};
const setTag = (xml, name, value) => xml.replace(new RegExp(`<${name}>[^<]*</${name}>|<${name}/>`), () => `<${name}>${value}</${name}>`);
async function sequenceFps(zip, track) {
  const sequence = /<Sequence>([0-9a-f-]{36})<\/Sequence>/i.exec(track)?.[1];
  if (!sequence) throw new Error('subtitle track has no sequence reference');
  for (const name of Object.keys(zip.files).filter((n) => n.endsWith('.xml'))) {
    const xml = await zip.file(name).async('string'), at = xml.indexOf(`<Sm2Sequence DbId="${sequence}">`);
    if (at < 0) continue;
    const hex = /<FrameRate>([0-9a-fA-F]{32})<\/FrameRate>/.exec(xml.slice(at, xml.indexOf('</Sm2Sequence>', at)))?.[1];
    const fps = hex ? Buffer.from(hex, 'hex').readDoubleLE(0) : NaN;
    if (!Number.isFinite(fps) || fps < 1 || fps > 240) throw new Error('unsupported timeline FrameRate encoding');
    return fps;
  }
  throw new Error('timeline sequence not found in export');
}
function captionItems(track, fps) {
  const m = /<Items>([\s\S]*?)<\/Items>|<Items\/>/.exec(track);
  if (!m) throw new Error('Unsupported track: missing Items field');
  const inner = m[1] ?? '';
  const elements = [...inner.matchAll(/<Element>\s*<Sm2TiGenerator DbId="([0-9a-f-]{36})">[\s\S]*?<\/Sm2TiGenerator>\s*<\/Element>/gi)];
  // Anything besides plain subtitle generators would be dropped by the rebuild below.
  if (elements.reduce((rest, e) => rest.replace(e[0], ''), inner).trim()) throw new Error('unsupported item on subtitle track');
  // Resolve issues fresh DbIds on every export, so a caption's id is its start frame
  // (captions on a track never overlap); DbIds are only carried in the XML.
  const items = elements.map(([text, dbId]) => {
    if (tag(text, 'PrettyType') !== 'Subtitle') throw new Error('unsupported item on subtitle track');
    if (/<CompositionTable>/.test(text)) throw new Error('per-caption Fusion compositions are not supported');
    const start = Number(tag(text, 'Start')), duration = Number(tag(text, 'Duration'));
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(duration)) throw new Error('invalid caption frame columns');
    const blob = Buffer.from(tag(text, 'FieldsBlob'), 'hex');
    return { text, dbId, blob, decoded: { id: String(start), ...decodeCaption(blob, { name: xmlUnescape(tag(text, 'Name')), start, end: start + duration, fps }) } };
  });
  return { items, field: m, separator: /^\s*/.exec(inner)[0] || '\n' };
}
async function readCaptions(source, track) {
  const exported = await readTimeline(source), target = selectedTrack(exported.xml, track);
  const fps = await sequenceFps(exported.zip, target.text);
  return { exported, target, fps, ...captionItems(target.text, fps) };
}
export async function inspectCaptionTimeline({ source, track = 1 }) {
  const { fps, items } = await readCaptions(source, track);
  return { track, fps, timeUnit: 'timeline_frames', captions: items.map((c) => c.decoded) };
}
export async function editCaptionTimeline({ source, output, track = 1, add = [], replace = [], delete: remove = [], templateCaptionId }) {
  const p = subtitleSchemas.write_captions.parse({ timeline: 'export', track, add, replace, delete: remove, templateCaptionId });
  if (source === output) throw new Error('Output must be a new file');
  const { exported, target, fps, items, field, separator } = await readCaptions(source, track);
  const { byId, template, staged, final } = planCaptionEdit(items, p, fps);
  const stagedById = new Map(staged.map((s) => [s.decoded.id, s]));
  const elements = final.map((c) => {
    const s = stagedById.get(c.id);
    if (!s) return byId.get(c.id).text;
    let text = s.fresh ? template.text.replace(template.dbId, () => randomUUID()) : s.base.text;
    if (s.fresh) text = text.replace(/<(MarkersBA|RenderCacheBA|ImportExportMetadataBA)>[\s\S]*?<\/\1>/g, '<$1/>');
    text = setTag(text, 'FieldsBlob', s.blob.toString('hex'));
    text = setTag(text, 'Name', xmlEscape(` ${s.caption.text}`));
    text = setTag(text, 'Start', String(s.caption.start));
    return setTag(text, 'Duration', String(s.caption.end - s.caption.start));
  });
  const trackText = target.text.slice(0, field.index) + `<Items>${separator}${elements.join(separator)}${separator}</Items>`
    + target.text.slice(field.index + field[0].length);
  exported.zip.file(exported.entry, exported.xml.slice(0, target.offset) + trackText + exported.xml.slice(target.offset + target.text.length));
  await fs.writeFile(output, await exported.zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE' }), { flag: 'wx' });
  return { output, track, fps, added: staged.filter((s) => s.fresh).map((s) => String(s.caption.start)), replaced: p.replace.map((c) => c.id),
    deleted: p.delete, captions: final.map((c) => ({ ...c, id: String(c.start) })),
    verification: 'exported_caption_readback', restart_required: false };
}
