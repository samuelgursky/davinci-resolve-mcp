'use strict';

/**
 * ops/verify.js — the end-to-end VERIFY pass (spec §5, P1). READ-ONLY: it
 * derives, compares, and reports; it writes nothing and mutates no input.
 *
 * Pipeline per cut:
 *   Oracle.derive (source frame + sample frame + scale + transform)
 *     → if a reference is available: compare derived-vs-reference (content-identity)
 *         → ADVISORY VISION (§8.1): on borderline / stubborn / alignment cuts,
 *           consult the injected VisionValidator and reconcile (it may raise a
 *           flag → REVIEW, never override the deterministic verdict)
 *     → else Tier C: MATH-VERIFIED (Oracle-consistent, no picture proof)
 *   → report entry
 *
 * All IO is injected (adapters): referenceProvider, frameSampler, visionValidator.
 * With none injected it still produces a Tier-C math-verified report.
 */

const oracle = require('../oracle');
const compare = require('../compare');
const advisory = require('../compare/advisory');
const report = require('../report');

/**
 * @param {{sequence:object, ticksPerFrame:number, clips:object[]}} model
 * @param {object} opts {
 *   target?, oracleVersion?, runAt?, thresholds?,
 *   referenceProvider?(clip)->{referencePath,derivedPath,tier,mode,label,context,proposeOnlyRepair}|null,
 *   visionValidator?  (injected VisionValidator; advisory only),
 *   cutId?(clip)->string
 * }
 * @returns {Promise<object>} the QC report
 */
async function verify(model, opts = {}) {
  if (!model || !model.sequence || !Array.isArray(model.clips)) {
    throw new Error('verify: model must be { sequence, ticksPerFrame, clips[] }');
  }
  const ctx = { ticksPerFrame: model.ticksPerFrame, sequenceWidth: model.sequence.width };
  const rep = report.makeReport({
    target: opts.target || 'resolve',
    oracleVersion: opts.oracleVersion || '1',
    tier: opts.tier || null,
    runAt: opts.runAt != null ? opts.runAt : null,
  });
  const cutIdOf = opts.cutId || ((c) => `seq${c.seqstart}`);

  for (const clip of model.clips) {
    const d = oracle.derive(clip, ctx);
    const cut = {
      cutId: cutIdOf(clip),
      seqstart: clip.seqstart,
      derivedSourceFrame: d.derivedSourceFrame,
      derivedSampleFrame: d.derivedSampleFrame,
      scale: d.derivedScaleCorrected,
      retimed: d.retimed,
      hasReference: false,
      tier: 'C',
      status: 'MATH-VERIFIED',
    };

    const ref = opts.referenceProvider ? await opts.referenceProvider(clip) : null;
    if (ref && ref.referencePath && ref.derivedPath) {
      const mode = ref.mode || 'content-identity';
      const det = await compare.compareFrames(ref.referencePath, ref.derivedPath, {
        mode,
        thresholds: opts.thresholds,
      });
      cut.hasReference = true;
      cut.tier = ref.tier || 'B';
      cut.status = det.verdict;
      cut.refScore = det.structure;
      cut.offset = det.offset;
      cut.identity = ref.identity || null; // Tier A (OCR) / Tier B (sidecar) source identity

      // ── Advisory vision escalation (§8.1) — only where the metric is weakest,
      //    and only if a VisionValidator is injected. Advisory can raise a flag
      //    (→ REVIEW) but never override the deterministic verdict.
      const consult = advisory.shouldConsultVision(
        { verdict: det.verdict, structure: det.structure },
        { mode, proposeOnlyRepair: ref.proposeOnlyRepair, thresholds: opts.thresholds },
      );
      if (opts.visionValidator && consult) {
        const adv = await opts.visionValidator.validate(ref.referencePath, ref.derivedPath, {
          mode,
          label: ref.label,
          context: ref.context,
        });
        const rec = advisory.reconcile({ verdict: det.verdict, structure: det.structure }, adv);
        cut.status = rec.verdict;
        cut.advisory = rec.advisory;
        cut.escalated = rec.escalated;
        cut.finalAction = rec.finalAction;
        cut.visionConsulted = true;
      } else {
        cut.visionConsulted = false;
      }
    }

    report.addCut(rep, cut);
  }
  return rep;
}

module.exports = { verify };
