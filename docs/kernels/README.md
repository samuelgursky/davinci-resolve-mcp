# Kernel Action Coverage

Kernel actions are MCP workflow actions layered on top of the public DaVinci
Resolve Scripting API. They are tracked separately from API method coverage:
API coverage answers "can MCP reach every Blackmagic method?", while kernel
coverage answers "which higher-level, guarded agent workflows are available?".

Current kernel coverage: **136 actions** across **9 compound MCP tools**.

| Kernel | MCP Tool | Actions |
|--------|----------|---------|
| Media analysis | `media_analysis` | `capabilities`, `install_guidance`, `resolve_output_root`, `plan`, `analyze_file`, `analyze_clip`, `analyze_bin`, `analyze_project`, `detect_sync_events`, `add_sync_event_markers`, `publish_clip_metadata`, `review_timeline_markers`, `summarize`, `get_report`, `build_index`, `index_status`, `query_index`, `start_batch_job`, `run_batch_job_slice`, `batch_job_status`, `list_batch_jobs`, `cancel_batch_job`, `resume_batch_job`, `cleanup_artifacts` |
| Timeline edit | `timeline` | `duplicate_clips`, `copy_clips`, `move_clips`, `copy_range`, `duplicate_range`, `overwrite_range`, `lift_range`, `story_spine_report`, `create_variant_from_ranges`, `bulk_set_item_properties`, `apply_look_to_items`, `thumbnail_contact_sheet`, `marker_thumbnail_review`, `edit_kernel_capabilities`, `probe_edit_kernel_item`, `title_property_scan`, `set_title_text`, `bulk_set_title_text` |
| Media Pool / ingest | `media_pool` | `ingest_capabilities`, `setup_multicam_timeline`, `probe_ingest_item`, `probe_media_pool`, `safe_import_media`, `safe_import_sequence`, `safe_import_folder`, `organize_clips`, `copy_metadata`, `normalize_metadata`, `probe_clip_properties`, `metadata_field_inventory`, `safe_relink`, `safe_unlink`, `link_proxy_checked`, `link_full_resolution_checked`, `set_clip_marks`, `clear_clip_marks`, `copy_clip_annotations`, `media_pool_boundary_report` |
| Render / Deliver | `render` | `render_capabilities`, `probe_render_matrix`, `probe_render_settings`, `validate_render_settings`, `safe_set_render_settings`, `prepare_render_job`, `render_job_lifecycle_probe`, `quick_export_capabilities`, `safe_quick_export`, `export_render_boundary_report` |
| Review annotations | `timeline_markers` | `annotation_capabilities`, `probe_annotations`, `normalize_marker_payload`, `copy_annotations`, `move_annotations`, `sync_marker_custom_data`, `clear_annotations_by_scope`, `export_review_report`, `annotation_boundary_report` |
| Color / Grade | `timeline_item_color` | `grade_capabilities`, `probe_grade_item`, `probe_node_graph`, `safe_set_cdl`, `safe_copy_grade`, `safe_apply_drx`, `safe_export_lut`, `grade_version_snapshot`, `grade_version_restore`, `color_group_capabilities`, `gallery_capabilities`, `grade_boundary_report` |
| Fusion composition | `fusion_comp` | `fusion_graph_capabilities`, `probe_fusion_comp`, `probe_fusion_tool`, `safe_add_tool`, `safe_set_inputs`, `safe_connect_tools`, `fusion_boundary_report` |
| Conform / interchange | `timeline` | `conform_capabilities`, `probe_timeline_structure`, `detect_gaps_overlaps`, `source_range_report`, `export_timeline_checked`, `import_timeline_checked`, `compare_timelines`, `probe_interchange_roundtrip`, `detect_missing_media`, `build_relink_plan`, `conform_boundary_report` |
| Audio / Fairlight | `timeline` | `audio_capabilities`, `probe_audio_item`, `probe_audio_track`, `safe_set_audio_properties`, `audio_mix_capability_report`, `voice_isolation_capabilities`, `audio_mapping_report`, `safe_auto_sync_audio`, `transcription_capabilities`, `subtitle_generation_probe`, `fairlight_boundary_report` |
| Project lifecycle | `project_manager` | `project_capabilities`, `probe_project_lifecycle`, `probe_project_settings`, `safe_project_create`, `safe_project_export`, `safe_project_import`, `safe_project_archive`, `safe_project_restore`, `safe_project_delete`, `safe_set_project_settings`, `project_settings_snapshot`, `database_capabilities`, `safe_set_current_database`, `preset_lifecycle_probe`, `project_boundary_report` |
| Extension authoring | `script_plugin` | `extension_capabilities`, `probe_fuse_lifecycle`, `probe_dctl_lifecycle`, `probe_script_lifecycle`, `safe_install_extension`, `safe_remove_extension`, `refresh_or_restart_required`, `extension_boundary_report` |

Helper-tool details that need more than an action list live in guides. See
[Multicam Setup Helper Guide](../guides/multicam-setup-guide.md) for the
`media_pool.setup_multicam_timeline` helper/API boundary and Resolve UI
conversion steps, and [Media Analysis Guide](../guides/media-analysis-guide.md)
for source-safe 2-pop/slate-clap detection.
