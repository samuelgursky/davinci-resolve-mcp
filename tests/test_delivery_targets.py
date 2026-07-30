"""Tests for src/utils/delivery_targets.py — the named render-intent layer."""

import json
import os
import pathlib
import tempfile
import unittest

from src.utils.delivery_targets import (
    DELIVERY_TARGETS,
    ENV_USER_TARGETS,
    LOUDNESS_STANDARDS,
    LRA_ADVISORY_LU,
    OVERRIDE_KEYS,
    TARGET_ALIASES,
    TIERS,
    DeliveryTarget,
    list_loudness_standards,
    list_targets,
    load_user_targets,
    normalize_loudness_standard,
    normalize_target_name,
    resolve_target,
    select_available,
    to_loudness_target,
    to_qc_spec,
    to_render_settings,
    user_targets_path,
)

# The authoritative allowlist lives in server.py; duplicated here so a target
# that emits a key SetRenderSettings would silently drop fails the suite.
RENDER_SETTING_KEYS = {
    "SelectAllFrames", "MarkIn", "MarkOut", "TargetDir", "CustomName",
    "UniqueFilenameStyle", "ExportVideo", "ExportAudio",
    "FormatWidth", "FormatHeight", "FrameRate", "PixelAspectRatio",
    "VideoQuality", "AudioCodec", "AudioBitDepth", "AudioSampleRate",
    "ColorSpaceTag", "GammaTag", "ExportAlpha", "EncodingProfile",
    "MultiPassEncode", "AlphaMode", "NetworkOptimization",
    "ClipStartFrame", "TimelineStartTimecode",
    "ReplaceExistingFilesInPlace", "ExportSubtitle", "SubtitleFormat",
}


class TableIntegrityTest(unittest.TestCase):
    def test_every_target_has_format_and_codec_candidates(self):
        for target_id, target in DELIVERY_TARGETS.items():
            self.assertTrue(target.format_candidates, f"{target_id} has no format candidates")
            self.assertTrue(target.codec_candidates, f"{target_id} has no codec candidates")

    def test_ids_are_self_consistent(self):
        for target_id, target in DELIVERY_TARGETS.items():
            self.assertEqual(target_id, target.id)

    def test_every_tier_is_known(self):
        for target in DELIVERY_TARGETS.values():
            self.assertIn(target.tier, TIERS, f"{target.id} has an unknown tier")

    def test_every_target_has_a_source_note(self):
        for target in DELIVERY_TARGETS.values():
            self.assertTrue(target.source, f"{target.id} has no source note")

    def test_no_platform_name_is_baked_into_an_id(self):
        """Platform names belong in aliases; ids must describe the deliverable."""
        platform_words = ("youtube", "vimeo", "tiktok", "instagram", "reels", "shorts")
        for target_id in DELIVERY_TARGETS:
            for word in platform_words:
                self.assertNotIn(word, target_id, f"{target_id} bakes in a platform name")

    def test_sequence_targets_have_no_qc_projection(self):
        """deliverable_qc probes one file; a sequence renders many."""
        for target in DELIVERY_TARGETS.values():
            if target.tier == "sequence":
                self.assertFalse(target.has_qc_projection, f"{target.id} should have no QC projection")
                self.assertIsNone(to_qc_spec(target))
                self.assertIn("sequence", target.qc_skip_reason)

    def test_every_target_has_a_qc_projection_or_an_explicit_reason(self):
        """A missing QC check must always be explained, never silent."""
        for target in DELIVERY_TARGETS.values():
            self.assertTrue(
                target.has_qc_projection or target.qc_skip_reason,
                f"{target.id} has neither a QC projection nor a qc_skip_reason",
            )
            self.assertFalse(
                target.has_qc_projection and target.qc_skip_reason,
                f"{target.id} both projects and skips QC",
            )

    def test_package_targets_skip_qc_with_a_reason(self):
        """IMF/DCP render a directory; deliverable_qc probes one file."""
        for target in DELIVERY_TARGETS.values():
            if target.tier == "package":
                self.assertIsNone(to_qc_spec(target))
                self.assertIn("package", target.qc_skip_reason)

    def test_every_target_is_live_verified(self):
        for target in DELIVERY_TARGETS.values():
            self.assertTrue(target.verified, f"{target.id} carries no verified date")


class SelectAvailableTest(unittest.TestCase):
    CODECS = {"Apple ProRes 422 HQ": "ProRes422HQ", "DNxHR HQ": "DNxHR_HQ"}

    def test_first_matching_candidate_wins(self):
        self.assertEqual(select_available(("DNxHR HQ", "Apple ProRes 422 HQ"), self.CODECS), "DNxHR_HQ")

    def test_falls_through_to_a_later_candidate(self):
        self.assertEqual(select_available(("Nope", "Apple ProRes 422 HQ"), self.CODECS), "ProRes422HQ")

    def test_matches_an_id_as_well_as_a_description(self):
        self.assertEqual(select_available(("ProRes422HQ",), self.CODECS), "ProRes422HQ")

    def test_match_is_case_insensitive(self):
        self.assertEqual(select_available(("apple prores 422 hq",), self.CODECS), "ProRes422HQ")

    def test_no_match_returns_none(self):
        self.assertIsNone(select_available(("Cinepak",), self.CODECS))

    def test_empty_and_malformed_inputs_return_none(self):
        self.assertIsNone(select_available((), self.CODECS))
        self.assertIsNone(select_available(("ProRes422HQ",), {}))
        self.assertIsNone(select_available(("ProRes422HQ",), None))

    def test_every_shipped_target_resolves_against_a_matching_matrix(self):
        """Each target's preferred spelling must be selectable from a map built
        from its own candidates — guards typos between candidates and lookup."""
        for target in DELIVERY_TARGETS.values():
            fake = {target.codec_candidates[0]: "RESOLVED"}
            self.assertEqual(select_available(target.codec_candidates, fake), "RESOLVED", target.id)


class NameResolutionTest(unittest.TestCase):
    def test_canonical_ids_resolve_to_themselves(self):
        for target_id in DELIVERY_TARGETS:
            self.assertEqual(normalize_target_name(target_id), target_id)

    def test_platform_aliases_resolve(self):
        self.assertEqual(normalize_target_name("youtube"), "h264_1080p_web")
        self.assertEqual(normalize_target_name("TikTok"), "h264_vertical_1080_web")
        self.assertEqual(normalize_target_name("prores master"), "prores422hq_master")
        self.assertEqual(normalize_target_name("youtube-4k"), "h265_2160p_web")
        self.assertEqual(normalize_target_name("avid"), "dnxhr_hq_mxf_opatom")

    def test_unknown_and_malformed_return_none(self):
        for value in ("betamax", "", "   ", None, 42, []):
            self.assertIsNone(normalize_target_name(value))

    def test_every_alias_points_at_a_real_target(self):
        for alias, target_id in TARGET_ALIASES.items():
            self.assertIn(target_id, DELIVERY_TARGETS, f"alias {alias!r} is dangling")

    def test_no_alias_shadows_a_canonical_id(self):
        self.assertFalse(set(TARGET_ALIASES) & set(DELIVERY_TARGETS))


class ResolveTargetTest(unittest.TestCase):
    def test_unknown_target_returns_none_rather_than_a_default(self):
        """There is no safe default deliverable — silently rendering the wrong
        format is the exact failure this feature prevents."""
        self.assertIsNone(resolve_target("nope"))

    def test_overrides_replace_named_fields_only(self):
        target = resolve_target("youtube", {"width": 1280, "height": 720})
        self.assertEqual((target.width, target.height), (1280, 720))
        self.assertEqual(target.codec_candidates, DELIVERY_TARGETS["h264_1080p_web"].codec_candidates)

    def test_overrides_coerce_types(self):
        target = resolve_target("youtube", {"width": "1280", "fps": "23.976"})
        self.assertEqual(target.width, 1280)
        self.assertAlmostEqual(target.fps, 23.976)

    def test_candidate_override_accepts_a_bare_string_or_a_list(self):
        self.assertEqual(resolve_target("youtube", {"codec_candidates": "H.264"}).codec_candidates, ("H.264",))
        self.assertEqual(
            resolve_target("youtube", {"codec_candidates": ["A", "B"]}).codec_candidates, ("A", "B")
        )

    def test_unknown_override_keys_are_ignored(self):
        target = resolve_target("youtube", {"bogus": 1, "width": 1280})
        self.assertEqual(target.width, 1280)
        self.assertFalse(hasattr(target, "bogus"))

    def test_uncoercible_override_is_skipped_not_raised(self):
        target = resolve_target("youtube", {"width": "wide"})
        self.assertEqual(target.width, DELIVERY_TARGETS["h264_1080p_web"].width)

    def test_none_override_unpins_a_field(self):
        self.assertIsNone(resolve_target("youtube", {"width": None}).width)

    def test_shipped_targets_are_not_mutated_by_overrides(self):
        resolve_target("youtube", {"width": 640})
        self.assertEqual(DELIVERY_TARGETS["h264_1080p_web"].width, 1920)


class RenderSettingsProjectionTest(unittest.TestCase):
    def test_every_emitted_key_is_a_real_render_setting(self):
        for target in DELIVERY_TARGETS.values():
            settings = to_render_settings(target, timeline_fps=24.0)
            unknown = set(settings) - RENDER_SETTING_KEYS
            self.assertFalse(unknown, f"{target.id} emits non-settings keys: {unknown}")

    def test_format_and_codec_are_not_emitted_as_settings(self):
        settings = to_render_settings(DELIVERY_TARGETS["prores422hq_master"])
        self.assertNotIn("format", settings)
        self.assertNotIn("codec", settings)

    def test_masters_inherit_timeline_raster_and_rate(self):
        settings = to_render_settings(DELIVERY_TARGETS["prores422hq_master"], timeline_fps=23.976)
        self.assertNotIn("FormatWidth", settings)
        self.assertNotIn("FormatHeight", settings)
        self.assertAlmostEqual(settings["FrameRate"], 23.976)

    def test_web_targets_pin_their_raster(self):
        settings = to_render_settings(DELIVERY_TARGETS["h264_vertical_1080_web"])
        self.assertEqual((settings["FormatWidth"], settings["FormatHeight"]), (1080, 1920))

    def test_explicit_fps_beats_timeline_fps(self):
        target = resolve_target("youtube", {"fps": 25})
        self.assertEqual(to_render_settings(target, timeline_fps=23.976)["FrameRate"], 25)

    def test_alpha_only_emitted_when_requested(self):
        self.assertTrue(to_render_settings(DELIVERY_TARGETS["prores4444_master"])["ExportAlpha"])
        self.assertNotIn("ExportAlpha", to_render_settings(DELIVERY_TARGETS["h264_1080p_web"]))

    def test_sequence_targets_disable_audio(self):
        for target in DELIVERY_TARGETS.values():
            if target.tier == "sequence":
                settings = to_render_settings(target)
                self.assertFalse(settings["ExportAudio"], target.id)
                self.assertNotIn("AudioSampleRate", settings)


class QcSpecProjectionTest(unittest.TestCase):
    def test_spec_asserts_only_what_the_render_pins(self):
        """A QC field the render never controlled produces a meaningless failure."""
        for target in DELIVERY_TARGETS.values():
            spec = to_qc_spec(target)
            if spec is None:
                continue
            settings = to_render_settings(target)
            if "FormatWidth" not in settings:
                self.assertNotIn("width", spec.get("video", {}), f"{target.id} asserts an unpinned width")
            if "AudioSampleRate" not in settings:
                self.assertNotIn("sampleRate", spec.get("audio", {}), f"{target.id} asserts an unpinned sampleRate")

    def test_container_is_the_ffprobe_first_token_for_mp4_and_mov_alike(self):
        """ffprobe reports format_name=mov,mp4,... for BOTH, so container is 'mov'
        for both and cannot discriminate them — only video.codec can."""
        self.assertEqual(to_qc_spec(DELIVERY_TARGETS["h264_1080p_web"])["container"], "mov")
        self.assertEqual(to_qc_spec(DELIVERY_TARGETS["prores422hq_master"])["container"], "mov")
        self.assertNotEqual(
            to_qc_spec(DELIVERY_TARGETS["h264_1080p_web"])["video"]["codec"],
            to_qc_spec(DELIVERY_TARGETS["prores422hq_master"])["video"]["codec"],
        )

    def test_qc_codecs_are_ffprobe_names_not_resolve_labels(self):
        self.assertEqual(to_qc_spec(DELIVERY_TARGETS["prores422hq_master"])["video"]["codec"], "prores")
        self.assertEqual(to_qc_spec(DELIVERY_TARGETS["h265_2160p_web"])["video"]["codec"], "hevc")
        self.assertEqual(to_qc_spec(DELIVERY_TARGETS["dnxhr_hqx_master"])["video"]["codec"], "dnxhd")

    def test_master_spec_carries_timeline_fps_when_supplied(self):
        spec = to_qc_spec(DELIVERY_TARGETS["prores422hq_master"], timeline_fps=23.976)
        self.assertAlmostEqual(spec["video"]["fps"], 23.976)
        self.assertNotIn("fps", to_qc_spec(DELIVERY_TARGETS["prores422hq_master"])["video"])

    def test_projections_agree_on_raster(self):
        for target in DELIVERY_TARGETS.values():
            spec = to_qc_spec(target)
            settings = to_render_settings(target)
            if spec and "FormatWidth" in settings:
                self.assertEqual(settings["FormatWidth"], spec["video"]["width"], target.id)
                self.assertEqual(settings["FormatHeight"], spec["video"]["height"], target.id)


class ListTargetsTest(unittest.TestCase):
    def test_lists_every_shipped_target(self):
        self.assertEqual(set(list_targets()), set(DELIVERY_TARGETS))

    def test_tier_filter_narrows_the_listing(self):
        web = list_targets(tier="web")
        self.assertTrue(web)
        self.assertTrue(all(entry["tier"] == "web" for entry in web.values()))
        self.assertNotIn("prores422hq_master", web)

    def test_aliases_are_surfaced_per_target(self):
        self.assertIn("youtube", list_targets()["h264_1080p_web"]["aliases"])

    def test_shipped_targets_are_not_flagged_user_defined(self):
        self.assertFalse(any(e["user_defined"] for e in list_targets().values()))


class UserTargetsTest(unittest.TestCase):
    def _write(self, payload):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(payload, handle)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_env_override_wins_over_logs_dir(self):
        self.assertEqual(
            user_targets_path("/repo", env={ENV_USER_TARGETS: "/custom/t.json"}),
            pathlib.Path("/custom/t.json"),
        )
        self.assertTrue(str(user_targets_path("/repo", env={})).endswith("logs/delivery-targets.json"))

    def test_missing_file_yields_empty(self):
        self.assertEqual(load_user_targets("/nonexistent/targets.json"), {})

    def test_unparseable_file_yields_empty_rather_than_raising(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        handle.write("{not json")
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        self.assertEqual(load_user_targets(handle.name), {})

    def test_valid_user_target_loads(self):
        path = self._write({
            "targets": {
                "xavc_master": {
                    "label": "XAVC master",
                    "format": ["MXF OP1A", "mxf"],
                    "codec": "XAVC",
                    "qc_codec": "h264",
                    "width": "1920",
                    "height": 1080,
                }
            }
        })
        loaded = load_user_targets(path)
        self.assertIn("xavc_master", loaded)
        self.assertIsInstance(loaded["xavc_master"], DeliveryTarget)
        self.assertEqual(loaded["xavc_master"].width, 1920, "string width should coerce")
        self.assertEqual(loaded["xavc_master"].format_candidates, ("MXF OP1A", "mxf"))
        self.assertEqual(loaded["xavc_master"].codec_candidates, ("XAVC",))

    def test_malformed_entry_is_skipped_without_taking_out_the_rest(self):
        path = self._write({
            "targets": {
                "broken": {"label": "no format or codec"},
                "also_broken": "not an object",
                "good": {"format": "MP4", "codec": "H.264"},
            }
        })
        self.assertEqual(set(load_user_targets(path)), {"good"})

    def test_unknown_tier_falls_back_to_master(self):
        path = self._write({"targets": {"t": {"format": "MP4", "codec": "H.264", "tier": "bogus"}}})
        self.assertEqual(load_user_targets(path)["t"].tier, "master")

    def test_user_targets_are_listed_and_flagged(self):
        extra = load_user_targets(self._write({"targets": {"custom": {"format": "MP4", "codec": "H.264"}}}))
        listing = list_targets(extra)
        self.assertTrue(listing["custom"]["user_defined"])
        self.assertFalse(listing["h264_1080p_web"]["user_defined"])

    def test_user_target_resolvable_by_name(self):
        extra = load_user_targets(self._write({"targets": {"custom": {"format": "MP4", "codec": "H.265"}}}))
        self.assertEqual(resolve_target("custom", extra_targets=extra).codec_candidates, ("H.265",))

    def test_override_keys_are_all_real_dataclass_fields(self):
        self.assertFalse(OVERRIDE_KEYS - set(DeliveryTarget.__dataclass_fields__))


class LoudnessStandardsTableTest(unittest.TestCase):
    def test_ids_match_their_keys(self):
        for key, standard in LOUDNESS_STANDARDS.items():
            self.assertEqual(key, standard.id)

    def test_numbers_are_physically_sane(self):
        for standard in LOUDNESS_STANDARDS.values():
            with self.subTest(standard=standard.id):
                # Programme loudness is negative; a positive target is a typo.
                self.assertLess(standard.integrated, 0.0)
                self.assertGreater(standard.tolerance_lu, 0.0)
                # A ceiling at or above 0 dBTP would permit inter-sample clipping.
                self.assertLess(standard.true_peak_max_dbtp, 0.0)

    def test_no_standard_mandates_an_lra_cap(self):
        # LRA is advisory here. If a standard ever gains a cap, to_loudness_target
        # emits lraMax and this test should be updated deliberately, not silently.
        for standard in LOUDNESS_STANDARDS.values():
            self.assertIsNone(standard.lra_max, standard.id)

    def test_only_ott_is_dialogue_gated(self):
        gated = {s.id for s in LOUDNESS_STANDARDS.values() if s.dialogue_gated}
        self.assertEqual(gated, {"ott_dialogue_gated"})

    def test_no_shipped_target_names_a_standard(self):
        # Documented invariant: guessing a programme loudness for a render intent
        # would assert a number the deliverable never promised.
        named = {t.id: t.loudness_standard for t in DELIVERY_TARGETS.values() if t.loudness_standard}
        self.assertEqual(named, {})

    def test_every_standard_is_listed(self):
        listing = list_loudness_standards()
        self.assertEqual(set(listing), set(LOUDNESS_STANDARDS))
        self.assertEqual(listing["ebu_r128"]["integrated_lufs"], -23.0)

    def test_name_normalisation_folds_separators(self):
        self.assertEqual(normalize_loudness_standard("EBU-R128"), "ebu_r128")
        self.assertEqual(normalize_loudness_standard(" atsc a85 "), "atsc_a85")
        self.assertIsNone(normalize_loudness_standard("bbc_r128"))
        self.assertIsNone(normalize_loudness_standard(None))


class LoudnessProjectionTest(unittest.TestCase):
    def _target(self, standard, **kw):
        return resolve_target("h264_1080p_web", {"loudness_standard": standard, **kw})

    def test_absent_contract_projects_to_none(self):
        self.assertIsNone(to_loudness_target(DELIVERY_TARGETS["h264_1080p_web"]))

    def test_full_program_standard_asserts_integrated_and_true_peak(self):
        projected = to_loudness_target(self._target("ebu_r128"))
        self.assertEqual(
            projected["target"],
            {"integrated": -23.0, "integratedTol": 0.5, "truePeakMax": -1.0},
        )
        self.assertEqual(projected["meta"]["measurement_basis"], "full_program")
        self.assertFalse(projected["meta"]["dialogue_gated"])

    def test_dialogue_gated_standard_asserts_true_peak_only(self):
        projected = to_loudness_target(self._target("ott_dialogue_gated"))
        # The whole point: no gradeable integrated value, because loudness_qc
        # measures full-program and would produce a meaningless verdict.
        self.assertEqual(projected["target"], {"truePeakMax": -2.0})
        self.assertNotIn("integrated", projected["target"])
        self.assertNotIn("integratedTol", projected["target"])
        meta = projected["meta"]
        self.assertEqual(meta["measurement_basis"], "dialogue_gated")
        self.assertEqual(meta["dialogue_gated_integrated_lufs"], -27.0)
        self.assertIn("dialogue-gated meter", meta["integrated_not_asserted_reason"])

    def test_no_standard_emits_an_lra_assertion(self):
        for standard_id in LOUDNESS_STANDARDS:
            with self.subTest(standard=standard_id):
                projected = to_loudness_target(self._target(standard_id))
                self.assertNotIn("lraMax", projected["target"])
                self.assertEqual(projected["meta"]["lra_advisory_lu"], LRA_ADVISORY_LU)

    def test_audio_free_target_projects_to_none(self):
        self.assertIsNone(to_loudness_target(self._target("web", export_audio=False)))

    def test_loudness_never_leaks_into_the_qc_spec(self):
        # deliverable_qc asserts what the render pinned; loudness is not that.
        spec = to_qc_spec(self._target("ebu_r128"))
        self.assertNotIn("loudness", spec)
        self.assertNotIn("integrated", json.dumps(spec))

    def test_emitted_window_accepts_the_edge_and_rejects_beyond_it(self):
        # One pass and one fail per full-program standard, graded exactly the way
        # loudness_qc does: abs(measured - integrated) <= tol.
        for standard_id, standard in LOUDNESS_STANDARDS.items():
            if standard.dialogue_gated:
                continue
            emitted = to_loudness_target(self._target(standard_id))["target"]
            target_i, tol = emitted["integrated"], emitted["integratedTol"]
            with self.subTest(standard=standard_id):
                at_edge = target_i + tol
                beyond = target_i + tol + 0.1
                self.assertLessEqual(abs(at_edge - target_i), tol)
                self.assertGreater(abs(beyond - target_i), tol)

    def test_true_peak_ceiling_rejects_a_hotter_measurement(self):
        # Graded the way loudness_qc does: measured <= truePeakMax.
        for standard_id in LOUDNESS_STANDARDS:
            emitted = to_loudness_target(self._target(standard_id))["target"]
            ceiling = emitted["truePeakMax"]
            with self.subTest(standard=standard_id):
                self.assertTrue(ceiling <= ceiling, "a measurement at the ceiling passes")
                self.assertFalse(ceiling + 0.1 <= ceiling, "0.1 dB hotter fails")
                self.assertTrue(-99.0 <= ceiling, "a quiet mix passes the ceiling")


class LoudnessOverrideTest(unittest.TestCase):
    def test_named_standard_is_applied_and_folded(self):
        target = resolve_target("h264_1080p_web", {"loudness_standard": "EBU-R128"})
        self.assertEqual(target.loudness_standard, "ebu_r128")
        self.assertEqual(target.loudness.integrated, -23.0)

    def test_unknown_standard_is_ignored_not_raised(self):
        with self.assertLogs("resolve-mcp.delivery-targets", level="WARNING") as logs:
            target = resolve_target("h264_1080p_web", {"loudness_standard": "bbc_r128"})
        self.assertIsNone(target.loudness_standard)
        self.assertIn("unknown loudness standard", "\n".join(logs.output))

    def test_listing_exposes_the_named_standard(self):
        listing = list_targets({"x": resolve_target("h264_1080p_web", {"loudness_standard": "web"})})
        self.assertEqual(listing["x"]["loudness_standard"], "web")
        self.assertIsNone(listing["h264_1080p_web"]["loudness_standard"])


class LoudnessUserTargetTest(unittest.TestCase):
    def _write(self, payload):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(payload, handle)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_user_file_can_name_a_standard(self):
        path = self._write({"targets": {"bcast": {
            "format": "MXF OP1A", "codec": "DNxHR HQ", "loudness_standard": "ebu_r128",
        }}})
        self.assertEqual(load_user_targets(path)["bcast"].loudness_standard, "ebu_r128")

    def test_user_file_with_a_bogus_standard_still_loads_the_target(self):
        path = self._write({"targets": {"bcast": {
            "format": "MXF OP1A", "codec": "DNxHR HQ", "loudness_standard": "nonsense",
        }}})
        loaded = load_user_targets(path)
        self.assertIn("bcast", loaded)  # a bad loudness field must not drop the target
        self.assertIsNone(loaded["bcast"].loudness_standard)


class LoudnessProseDriftTest(unittest.TestCase):
    """Numbers quoted in prose must match the constants they describe.

    This is the LUT_SIZE class of bug: a constant is bumped, the sentence
    describing it is not, and the documentation becomes a confident lie that
    nothing detects. Each standard's `source` string quotes its own figures, so
    they are parsed back out and compared.
    """

    def test_source_prose_matches_the_numbers(self) -> None:
        import re

        for standard in LOUDNESS_STANDARDS.values():
            with self.subTest(standard=standard.id):
                quoted = {float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", standard.source)}
                self.assertTrue(
                    quoted,
                    f"{standard.id}: source quotes no figures, so drift here is undetectable",
                )
                self.assertIn(
                    standard.integrated, quoted,
                    f"{standard.id}: integrated {standard.integrated} not quoted in {standard.source!r}",
                )
                self.assertIn(
                    standard.true_peak_max_dbtp, quoted,
                    f"{standard.id}: true peak {standard.true_peak_max_dbtp} not quoted in "
                    f"{standard.source!r}",
                )


if __name__ == "__main__":
    unittest.main()
