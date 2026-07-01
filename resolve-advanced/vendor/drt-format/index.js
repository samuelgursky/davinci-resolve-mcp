/**
 * drt-format — DaVinci Resolve DRT (Timeline) format
 *
 * DRT is a zip archive with SeqContainer*.xml + (optionally) MpFolder*.xml
 * entries, no project.xml. It's what Resolve produces when you export a
 * single timeline without dragging the entire project shell along.
 *
 * Same on-disk schema as DRP for the timeline parts; the surface here
 * reuses the drp-format builder/parser primitives via delegation, so
 * downstream consumers can use one mental model for both formats.
 *
 * @module drt-format
 */

const drtParser = require('./drt-parser');
const drtBuilder = require('./drt-builder');
const drtValidator = require('./drt-validator');

module.exports = {
  parseDRT: drtParser.parseDRT,
  buildDRT: drtBuilder.buildDRT,
  validateDRT: drtValidator.validateDRT,
  // Canonical SeqContainer-entry matcher (both tool-authored SeqContainer<N>.xml and
  // real Resolve SeqContainer/<uuid>.xml). Shared so callers don't re-inline the regex.
  listSeqContainerEntries: drtParser.listSeqContainerEntries,

  // Resolve version registry + retargeting (re-stamp to a target Resolve version).
  // The registry + re-stamp core are universal across DRT/DRP/DRX (same version stamp);
  // each format has a wrapper: retargetDRT/DRP (zip), retargetDRX (single XML), retarget (auto).
  resolveVersions: require('./resolve-versions'),
  retargetDRT: require('./resolve-versions').retargetDRT,
  retargetDRP: require('./resolve-versions').retargetDRP,
  retargetDRX: require('./resolve-versions').retargetDRX,
  retarget: require('./resolve-versions').retarget,
  // Capability layer: timeline gate (DRT/DRP) + domain bridge to color (DRX).
  capabilities: require('./capabilities'),
  capabilityDomains: require('./capability-domains'),
  // Schema fingerprint/diff — populates the capability map from real exports (any format).
  schemaFingerprint: require('./schema-fingerprint'),

  // Module re-exports for callers that want the lower-level surface.
  parser: drtParser,
  builder: drtBuilder,
  validator: drtValidator,
};
