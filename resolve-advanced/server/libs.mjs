/**
 * Bridge: load the vendored CommonJS format libraries from ESM server code.
 *
 * The vendored libs under../vendor/** are CommonJS (require()), scoped to
 * CJS by resolve-advanced/package.json having no "type":"module". The server
 * files are.mjs (ESM) so they can import the ESM MCP SDK. createRequire
 * bridges the two — lazy, so a tool that's never called never loads its lib
 * (and a missing optional dep never crashes startup).
 */

import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

let _drp = null;
let _drt = null;
let _drxParser = null;
let _drxGen = null;
let _drxCdl = null;
let _drxMerger = null;
let _drxCodec = null;
let _nodeLayout = null;
let _audioFairlight = null;
let _fusion = null;

export function drp() {
  if (!_drp) _drp = require('../vendor/drp-format/index.js');
  return _drp;
}
export function drt() {
  if (!_drt) _drt = require('../vendor/drt-format/index.js');
  return _drt;
}
export function drxParser() {
  if (!_drxParser) _drxParser = require('../vendor/drx-codec/drx-parser.js');
  return _drxParser;
}
export function drxGenerator() {
  if (!_drxGen) _drxGen = require('../vendor/drx-codec/drx-generator.js');
  return _drxGen;
}
export function drxCdl() {
  if (!_drxCdl) _drxCdl = require('../vendor/drx-codec/cdl-exporter.js');
  return _drxCdl;
}
export function drxMerger() {
  if (!_drxMerger) _drxMerger = require('../vendor/drx-codec/drx-merger.js');
  return _drxMerger;
}
export function drxCodec() {
  if (!_drxCodec) _drxCodec = require('../vendor/drx-codec/index.js');
  return _drxCodec;
}
export function nodeLayout() {
  if (!_nodeLayout) _nodeLayout = require('../vendor/drx-codec/node-layout.js');
  return _nodeLayout;
}
export function audioFairlight() {
  if (!_audioFairlight) _audioFairlight = require('../vendor/audio-fairlight/index.js');
  return _audioFairlight;
}
export function fusion() {
  if (!_fusion) _fusion = require('../vendor/fusion-codec/composition-generator.js');
  return _fusion;
}
