/**
 * Public library surface (A0) — the importable API of the Resolve-advanced engine, so a
 * downstream application can `import { … } from 'davinci-resolve-advanced-mcp'` instead of
 * only spawning the stdio MCP server: downstream consumers depend on THIS upstream package.
 * The MCP server is a thin shell over these same exports.
 *
 * Grouping: codec (offline .drp/.drt/.drx) · grading (deterministic compute cores) ·
 * pipeline (DB-as-truth foundation) · tools (MCP tool handlers) · mcp (stdio server entry).
 * Publish name/registry is a separate, parked decision — this just makes the boundary
 * explicit and testable under the current package.
 */

// ── codec — offline DaVinci file formats (no Resolve) ──────────────────────────
export * as codec from './libs.mjs';

// ── grading — deterministic, local compute cores (the C-tier catalog) ──────────
export { measureMeanRGB, generateAssertedGainDRX, computeLevels } from './exposure-level.mjs';
export { isSkin, measureSkinMeanRGB, computeSkinMatch } from './skin-match.mjs';
export { measureToneRGB, computeShotMatch } from './shot-match.mjs';
export { measurePatchMeanRGB, computeWhiteBalanceMatch } from './white-balance-match.mjs';
export { measureBWPoints, generateAssertedAffineDRX, computeContrastNormalize } from './contrast-normalize.mjs';
export { measureLegal, computeGamutLegal } from './gamut-legal.mjs';
export { scopeRead, SKIN_LINE_DEG } from './scope-read.mjs';
export { measureMeanStd, computeMatchToReference } from './match-to-reference.mjs';
export { measureSaturation, computeSaturationMatch } from './saturation-match.mjs';
export { measureBlackPoint, computeBlackBalance } from './black-balance.mjs';
export { measureLumaCDF, computeToneCurve, computeToneCurveTransfer } from './tone-curve-transfer.mjs';
export { provenanceLabel, provenanceRecord, parseProvenanceLabel, isAutoLabel, gist, TOOL_VERSIONS } from './node-provenance.mjs';
export { deriveIntentTags, shouldExcludeFromNeutralize, INTENT_EXCLUDE_TAGS } from './shot-intent.mjs';
export { verifyGrade } from './verify-grade.mjs';
export { extractFrames, probeStream, assessColorspace, resolvePosition } from './extract-frames.mjs';
export { importCDL } from './cdl-io.mjs';
export { transferGrade } from './grade-transfer.mjs';
export { authorLook, carryLook } from './season-look.mjs';
export { applyLut, extractBodyHex } from './lut-apply.mjs';
export { injectNodeLut } from './grade-body-patch.mjs';
export { scaleParam, listGroupNames, decodeGroupGrades, readProjectXml, groupSegment, groupBodies } from './group-grade-read.mjs';

// ── pipeline — DB-as-truth foundation (canonical DB, compile, readback, runner) ─
export * as projectDb from './project-db.mjs';
export { deepMerge, validateResolved, resolveDeliverableInherits, compileSpecs, loadYamlDir } from './spec-compile.mjs';
export { getByPath, recordReadback, detectDrift, reconcile, driftReport } from './readback.mjs';
export { planRun, executeStage, runAll, approveGate, markStageApplied, rerunStage, resumeRun } from './runner.mjs';
export { descriptorSchema, CATALOG, getDescriptor, listCatalog, STAGE_PLAN } from './tool-catalog.mjs';
export { APPLY_CONTRACT, toApplyContract } from './runner-apply-contract.mjs';

// ── tools — MCP tool handlers (programmatic dispatch: tool.handler({action, args})) ─
export { drpTool } from './tools/drp.mjs';
export { drtTool } from './tools/drt.mjs';
export { drxTool } from './tools/drx.mjs';
export { conformTool } from './tools/conform.mjs';
export { colorTraceTool } from './tools/color_trace.mjs';
export { offlineRefTool } from './tools/offline_ref.mjs';
export { fusionTool } from './tools/fusion.mjs';
export { audioTool } from './tools/audio.mjs';
export { audioPlanTool } from './tools/audio_plan.mjs';
export { fairlightTool } from './tools/fairlight.mjs';
export { projectDbTool } from './tools/project_db.mjs';
export { projectReadTool } from './tools/project_read.mjs';
export { capabilitiesTool } from './tools/capabilities.mjs';
export { pipelineTool } from './tools/pipeline.mjs';
export { deliverableTool } from './tools/deliverable.mjs';

// ── deliverable QC (Cluster D) — compute cores ─────────────────────────
export { checkDeliverable, deliverableQc, loudnessQc, parseEbur128, reframeBlankingCheck, conformCompleteness, reDeliveryDiff, compareRenders } from './deliverable-qc.mjs';
export { buildManifest, reconcileManifest, checksumFile } from './render-manifest.mjs';
export { expandDeliverable, ENTITY_DEFAULTS } from './deliverable-entities.mjs';
export { probeMedia, ratio } from './ffprobe-media.mjs';

// ── media front-end (Cluster M) — compute cores ────────────────────────
export { mediaTool } from './tools/media.mjs';
export { sealFiles, verifyFiles, findDupesByHash, ingestVerify, relinkManifest, renamePlan, reelNormalize, projectHygiene, turnoverPackage } from './media-ops.mjs';
export { mediaInventory, syncByTC, tcToFrames, framesToTc } from './media-inventory.mjs';

// ── editorial integrity (Cluster E) — compute cores ────────────────────
export { editorialTool } from './tools/editorial.mjs';
export { parseEDL, parseOTIO, parseXMEMLEvents, parseInterchange, diffChangelist, timingGuards, conformManifest, markerRoundtrip } from './editorial.mjs';

// ── provenance / audit (Cluster P) — compute cores ─────────────────────
export { provenanceTool } from './tools/provenance.mjs';
export { galleryLineage, makeStillLabel, validateStillLabel, gradeProvenance, cdlExport, cdlDiff, revisionHistory, episodeReport } from './provenance-audit.mjs';

// ── mcp — the stdio server entry (the thin shell over the above) ───────────────
export { startServer } from './index.mjs';
