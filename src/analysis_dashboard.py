#!/usr/bin/env python3
"""Local dashboard for single-user media analysis batch jobs."""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from src.utils.media_analysis import (
    _write_json as _atomic_write_json,
    analysis_index_status,
    analysis_root_coverage,
    build_analysis_index,
    detect_capabilities,
    query_analysis_index,
    resolve_output_root,
    clip_directory_hash,
    load_clip_index,
    stable_clip_directory,
    stable_clip_match_hashes,
)
from src.utils.media_analysis_jobs import (
    MEDIA_EXTENSIONS,
    batch_job_status,
    cancel_batch_job,
    create_batch_job_from_paths,
    list_batch_jobs,
    project_root_for_dashboard,
    resume_batch_job,
    run_batch_job_slice,
)
from src.utils.platform import setup_environment
from src.utils.analysis_memory import read_panel_state, write_panel_state
from src.utils import brain_edits as _brain_edits
from src.utils import timeline_versioning as _timeline_versioning
from src.utils import timeline_brain_db as _timeline_brain_db


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DaVinci Resolve MCP</title>
  <style>
    :root {
      color-scheme: dark;

      /* Bradford Operations core tokens */
      --bg-base: #1a1a1a;
      --bg-elevated-1: #242424;
      --bg-elevated-2: #2d2d2d;
      --bg-elevated-3: #333333;
      --bg-hover: #3a3a3a;
      --bg-active: #404040;
      --text-primary: #e8e8e8;
      --text-secondary: #a0a0a0;
      --text-tertiary: #666666;
      --accent-brand: #1E90FF;
      --accent-brand-hover: #4A9EFF;
      --accent-brand-pressed: #0066CC;
      --accent-brand-muted: rgba(30, 144, 255, 0.15);
      --accent-brand-subtle: rgba(30, 144, 255, 0.08);
      --accent-success: #22c55e;
      --accent-success-muted: rgba(34, 197, 94, 0.15);
      --accent-warning: #f59e0b;
      --accent-warning-muted: rgba(245, 158, 11, 0.15);
      --accent-error: #ef4444;
      --accent-error-muted: rgba(239, 68, 68, 0.15);
      --accent-ai: #a855f7;
      --border-subtle: #333333;
      --border-default: #404040;
      --border-strong: #505050;
      --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      --space-1: 4px;
      --space-2: 8px;
      --space-3: 12px;
      --space-4: 16px;
      --space-5: 20px;
      --space-6: 24px;
      --space-8: 32px;
      --radius-sm: 4px;
      --radius-md: 8px;
      --radius-pill: 9999px;

      /* Lab-style module tokens */
      --lab-workspace-bg: #0A0A0A;
      --lab-workspace-letterbox: #000000;
      --lab-panel-bg: #141312;
      --lab-panel-header: #1A1918;
      --lab-panel-elevated: #1E1D1C;
      --lab-accent-primary: var(--accent-brand);
      --lab-playhead: var(--accent-brand);

      /* Bradford Operations density tokens */
      --ops-text-label: 12px;
      --ops-text-body: 14px;
      --ops-text-ui: 14px;
      --ops-text-heading: 18px;
      --ops-text-title: 24px;
      --ops-leading-tight: 1.3;
      --ops-leading-normal: 1.55;
      --ops-weight-ui: 500;
      --ops-weight-heading: 600;

      font-family: var(--font-sans);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background:
        linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px) 0 0 / 44px 44px,
        linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px) 0 0 / 44px 44px,
        linear-gradient(180deg, var(--lab-workspace-bg), var(--bg-base) 58%, #111111);
      color: var(--text-primary);
      font-size: var(--ops-text-body);
      line-height: var(--ops-leading-normal);
      -webkit-user-select: none;
      user-select: none;
    }
    button, input, textarea, select { font: inherit; }
    button {
      border: 1px solid color-mix(in srgb, var(--accent-brand) 45%, transparent);
      background: var(--accent-brand);
      color: #ffffff;
      min-height: 34px;
      padding: 0 var(--space-4);
      border-radius: var(--radius-sm);
      cursor: pointer;
      font-size: var(--ops-text-ui);
      font-weight: var(--ops-weight-ui);
      -webkit-user-select: none;
      user-select: none;
      transition: background 150ms ease, border-color 150ms ease, color 150ms ease, transform 100ms ease;
    }
    button:hover {
      background: var(--accent-brand-hover);
      border-color: var(--accent-brand-hover);
    }
    button:active { transform: translateY(1px); }
    button:focus-visible,
    input:focus-visible,
    textarea:focus-visible,
    select:focus-visible {
      outline: 0;
      box-shadow: 0 0 0 1px var(--accent-brand), 0 0 0 4px rgba(30, 144, 255, 0.18);
    }
    button.secondary {
      background: var(--bg-elevated-2);
      border-color: var(--border-default);
      color: var(--text-primary);
    }
    button.secondary:hover {
      background: var(--bg-hover);
      border-color: var(--border-strong);
    }
    button.danger {
      background: color-mix(in srgb, var(--accent-error) 88%, #000000);
      border-color: color-mix(in srgb, var(--accent-error) 60%, transparent);
    }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    .action-menu {
      position: relative;
      display: inline-flex;
    }
    .action-menu-trigger {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }
    .action-menu-chevron {
      width: 12px;
      height: 12px;
      transition: transform 150ms ease;
    }
    .action-menu.open .action-menu-chevron {
      transform: translateY(1px) rotate(180deg);
    }
    .action-dropdown {
      position: absolute;
      top: calc(100% + 8px);
      right: 0;
      display: none;
      min-width: 230px;
      max-height: 60vh;
      overflow-y: auto;
      padding: var(--space-2);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: color-mix(in srgb, var(--bg-base) 96%, #000000);
      box-shadow: 0 16px 36px rgba(0,0,0,0.36);
      z-index: 1004;
    }
    .action-menu.open .action-dropdown {
      display: grid;
      gap: var(--space-1);
    }
    .action-dropdown button {
      display: flex;
      width: 100%;
      justify-content: flex-start;
      border-color: transparent;
      background: transparent;
      color: var(--text-secondary);
      text-align: left;
      padding: 0 var(--space-3);
    }
    .action-dropdown button:hover {
      background: var(--bg-elevated-2);
      border-color: var(--border-default);
      color: var(--text-primary);
    }
    .action-dropdown-label {
      padding: var(--space-2) var(--space-3) 0;
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--text-tertiary);
      pointer-events: none;
    }
    .action-dropdown-empty {
      padding: var(--space-2) var(--space-3);
      font-size: 12px;
      color: var(--text-tertiary);
      pointer-events: none;
    }
    .lab-navbar {
      height: 48px;
      min-height: 48px;
      border-bottom: 1px solid var(--bg-elevated-3);
      background: var(--bg-base);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-4);
      padding: 0 var(--space-4);
      position: fixed;
      inset: 0 0 auto 0;
      z-index: 1002;
    }
    h1, h2, h3, p { margin: 0; }
    h1 {
      font-size: var(--ops-text-title);
      font-weight: var(--ops-weight-heading);
      letter-spacing: 0;
      line-height: var(--ops-leading-tight);
    }
    h2 {
      color: var(--text-primary);
      font-size: var(--ops-text-label);
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
      border-bottom: 1px solid var(--border-default);
      padding-bottom: var(--space-3);
      margin-bottom: var(--space-4);
    }
    small { color: var(--text-secondary); }
    .nav-left {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      min-width: 0;
      flex: 1;
    }
    .wordmark {
      display: inline-flex;
      align-items: baseline;
      gap: 6px;
      color: #ffffff;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 0.5px;
      line-height: 1;
      white-space: nowrap;
    }
    .home-wordmark {
      border: 0;
      background: transparent;
      min-height: auto;
      padding: 0;
      border-radius: 0;
      cursor: pointer;
    }
    .home-wordmark:hover {
      background: transparent;
      color: #ffffff;
    }
    .home-wordmark:active { transform: none; }
    .wordmark-accent { color: var(--accent-brand); }
    .project-context {
      min-width: 170px;
      max-width: 260px;
    }
    .project-context select {
      min-height: 32px;
      height: 32px;
      padding: 0 var(--space-3);
      background: var(--bg-elevated-1);
      border-color: var(--border-default);
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      font-weight: 600;
    }
    .project-filter {
      min-width: 260px;
      max-width: 360px;
    }
    .project-filter input {
      min-height: 32px;
      height: 32px;
      font-size: var(--ops-text-label);
    }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: var(--space-5);
      background: rgba(0, 0, 0, 0.62);
      z-index: 1200;
    }
    .modal-backdrop.open {
      display: flex;
    }
    .modal-card {
      width: min(520px, 100%);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      background: color-mix(in srgb, var(--bg-base) 94%, #000000);
      box-shadow: 0 24px 64px rgba(0,0,0,0.48);
      padding: var(--space-5);
    }
    .modal-kicker {
      color: var(--accent-brand-hover);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      margin-bottom: var(--space-2);
    }
    .modal-card h3 {
      color: var(--text-primary);
      font-size: 18px;
      font-weight: 700;
      line-height: 1.3;
      margin-bottom: var(--space-3);
    }
    .modal-body {
      color: var(--text-secondary);
      line-height: 1.55;
      margin-bottom: var(--space-4);
    }
    .modal-detail {
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      background: var(--lab-workspace-letterbox);
      padding: var(--space-3);
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      margin-bottom: var(--space-5);
    }
    .modal-actions {
      display: flex;
      justify-content: flex-end;
      gap: var(--space-2);
      flex-wrap: wrap;
    }
    .nav-breadcrumb {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      color: var(--text-secondary);
      min-width: 0;
      font-size: 13px;
      font-weight: 600;
    }
    .breadcrumb-icon,
    .nav-breadcrumb-sep {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      color: var(--text-tertiary);
      flex: 0 0 auto;
    }
    .breadcrumb-icon {
      color: var(--accent-brand-hover);
    }
    .breadcrumb-icon svg,
    .nav-breadcrumb-sep svg {
      width: 12px;
      height: 12px;
    }
    .nav-breadcrumb-sep {
      color: var(--text-tertiary);
    }
    .nav-breadcrumb-sep--root {
      font-size: 16px;
      font-weight: 400;
      color: var(--border-strong);
      width: auto;
      padding: 0 2px;
    }
    .nav-breadcrumb-current {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .breadcrumb-trail {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
    }
    .breadcrumb-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      color: var(--text-secondary);
      font-size: 13px;
      font-weight: 600;
    }
    .breadcrumb-item-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 16px;
      height: 16px;
      color: var(--accent-brand-hover);
      flex: 0 0 auto;
    }
    .breadcrumb-item-icon svg {
      width: 13px;
      height: 13px;
    }
    .brand-row {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      margin-bottom: var(--space-2);
    }
    .brand-kicker {
      color: var(--accent-brand-hover);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .brand-sep { color: var(--text-tertiary); }
    .brand-context {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      font-weight: 600;
      text-transform: uppercase;
    }
    .subhead {
      margin-top: var(--space-2);
      color: var(--text-secondary);
      max-width: 760px;
      line-height: 1.45;
    }
    .credit {
      margin-top: var(--space-2);
      color: var(--text-tertiary);
      font-size: var(--ops-text-label);
    }
    .credit strong {
      color: var(--text-secondary);
      font-weight: 600;
    }
    a {
      color: inherit;
      text-decoration: none;
      -webkit-user-select: none;
      user-select: none;
    }
    .credit a,
    .lab-footer a {
      color: var(--text-secondary);
      font-weight: 600;
      text-decoration: underline;
      text-decoration-color: color-mix(in srgb, var(--accent-brand) 45%, transparent);
      text-underline-offset: 3px;
      transition: color 150ms ease, text-decoration-color 150ms ease;
    }
    .credit a:hover,
    .lab-footer a:hover {
      color: var(--accent-brand-hover);
      text-decoration-color: var(--accent-brand-hover);
    }
    .control-tabs {
      display: flex;
      gap: var(--space-2);
      justify-content: center;
      min-width: 0;
      flex: 0 1 auto;
    }
    .control-nav-item {
      position: relative;
      display: inline-flex;
    }
    .control-tab {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 32px;
      padding: 0 var(--space-3);
      background: transparent;
      border-color: transparent;
      color: var(--text-secondary);
      white-space: nowrap;
    }
    .control-tab.has-menu {
      padding-right: var(--space-2);
    }
    .tab-chevron {
      display: inline-flex;
      width: 12px;
      height: 12px;
      color: var(--text-tertiary);
      transition: transform 150ms ease, color 150ms ease;
    }
    .tab-chevron svg {
      width: 12px;
      height: 12px;
    }
    .control-tab:hover {
      background: var(--bg-elevated-2);
      border-color: var(--border-default);
      color: var(--text-primary);
    }
    .control-tab.active {
      background: var(--accent-brand-muted);
      border-color: color-mix(in srgb, var(--accent-brand) 45%, transparent);
      color: #ffffff;
    }
    .control-tab.active .tab-chevron,
    .control-nav-item.open .tab-chevron {
      color: var(--accent-brand-hover);
      transform: translateY(1px);
    }
    .nav-dropdown {
      position: absolute;
      top: calc(100% + 8px);
      right: 0;
      min-width: 220px;
      display: none;
      padding: var(--space-2);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: color-mix(in srgb, var(--bg-base) 96%, #000000);
      box-shadow: 0 16px 36px rgba(0,0,0,0.36);
      z-index: 1005;
    }
    .control-nav-item.open .nav-dropdown {
      display: grid;
      gap: var(--space-1);
    }
    .nav-dropdown-item {
      min-height: 34px;
      width: 100%;
      justify-content: flex-start;
      gap: var(--space-2);
      border-color: transparent;
      background: transparent;
      color: var(--text-secondary);
      text-align: left;
      padding: 0 var(--space-3);
    }
    .nav-dropdown-item:hover,
    .nav-dropdown-item.active {
      background: var(--bg-elevated-2);
      border-color: var(--border-default);
      color: var(--text-primary);
    }
    .nav-dropdown-item.active {
      color: #ffffff;
      box-shadow: inset 3px 0 0 var(--accent-brand);
    }
    .nav-dropdown-icon {
      display: none;
      width: 14px;
      height: 14px;
      color: var(--accent-brand-hover);
      flex: 0 0 auto;
    }
    .nav-dropdown-icon svg {
      width: 14px;
      height: 14px;
    }
    .nav-links {
      display: flex;
      justify-content: flex-end;
      align-items: center;
      gap: var(--space-2);
      min-width: 0;
    }
    .version-badge {
      position: relative;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 0 10px;
      min-height: 32px;
      border-radius: var(--radius-pill);
      background: var(--accent-brand-subtle);
      border: 1px solid rgba(30, 144, 255, 0.25);
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.02em;
      cursor: pointer;
      transition: background 150ms ease, border-color 150ms ease, color 150ms ease;
    }
    .version-badge:hover {
      background: var(--accent-brand-muted);
      border-color: var(--accent-brand);
      color: var(--accent-brand-hover);
    }
    .version-badge .version-label {
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--accent-brand-hover);
      font-size: 10px;
    }
    .version-badge .version-number {
      color: var(--text-primary);
    }
    .version-badge .version-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: transparent;
      flex: 0 0 7px;
      transition: background 200ms ease;
    }
    .version-badge.has-update {
      background: var(--accent-warning-muted);
      border-color: rgba(245, 158, 11, 0.45);
    }
    .version-badge.has-update .version-dot {
      background: var(--accent-warning);
      box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.15);
    }
    .version-badge.has-update .version-number {
      color: var(--accent-warning);
    }
    .modal-command {
      display: block;
      padding: 10px var(--space-3);
      background: var(--bg-elevated-1);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--text-primary);
      overflow-wrap: anywhere;
    }
    .nav-link,
    .external-link {
      border: 1px solid var(--border-default);
      background: var(--bg-elevated-1);
      border-radius: var(--radius-sm);
      color: var(--text-secondary);
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-height: 32px;
      padding: 0 var(--space-3);
      font-size: var(--ops-text-label);
      font-weight: 600;
      transition: background 150ms ease, border-color 150ms ease, color 150ms ease;
    }
    .nav-link:hover,
    .external-link:hover {
      background: var(--bg-hover);
      border-color: var(--border-strong);
      color: var(--accent-brand-hover);
    }
    .github-icon-link {
      border: 1px solid var(--border-default);
      background: var(--bg-elevated-1);
      border-radius: var(--radius-sm);
      color: var(--text-secondary);
      display: inline-flex;
      align-items: center;
      width: 34px;
      min-width: 34px;
      min-height: 32px;
      justify-content: center;
      padding: 0;
      text-decoration: none;
      transition: background 150ms ease, border-color 150ms ease, color 150ms ease;
    }
    .github-icon-link:hover {
      background: var(--bg-hover);
      border-color: var(--border-strong);
      color: var(--accent-brand-hover);
    }
    .external-link.github-icon-link {
      width: 40px;
      min-width: 40px;
      min-height: 38px;
    }
    .github-icon {
      width: 17px;
      height: 17px;
      flex: 0 0 auto;
      color: currentColor;
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    .lab-footer a.github-icon-link {
      color: var(--text-secondary);
      text-decoration: none;
    }
    .pill {
      border: 1px solid var(--border-default);
      background: var(--bg-elevated-1);
      border-radius: var(--radius-pill);
      padding: 5px 9px;
      color: var(--text-secondary);
      white-space: nowrap;
      font-size: var(--ops-text-label);
      font-family: var(--font-mono);
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    main {
      display: grid;
      grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
      gap: var(--space-4);
      padding: calc(48px + var(--space-4)) var(--space-4) calc(52px + var(--space-4));
      max-width: 1500px;
      margin: 0 auto;
    }
    .panel { display: none; }
    .panel.active { display: grid; }
    .panel.control-grid {
      grid-template-columns: repeat(12, minmax(0, 1fr));
      align-items: start;
    }
    .panel.control-grid > section { grid-column: span 6; }
    .panel.control-grid > section.span-12 { grid-column: span 12; }
    .panel.control-grid > section.span-8 { grid-column: span 8; }
    .panel.control-grid > section.span-4 { grid-column: span 4; }
    .panel.control-grid > .span-12 { grid-column: span 12; }
    .panel.control-grid > .span-8 { grid-column: span 8; }
    .panel.control-grid > .span-4 { grid-column: span 4; }
    .subpage { display: none; }
    .subpage.active { display: block; }
    .subpage-grid {
      display: grid;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      gap: var(--space-4);
      align-items: start;
    }
    .subpage-grid > section { grid-column: span 6; }
    .subpage-grid > section.span-12 { grid-column: span 12; }
    .subpage-grid > section.span-8 { grid-column: span 8; }
    .subpage-grid > section.span-4 { grid-column: span 4; }
    section {
      background: color-mix(in srgb, var(--lab-panel-bg) 94%, var(--bg-elevated-1));
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      padding: var(--space-4);
      box-shadow: 0 18px 42px rgba(0,0,0,0.24);
      min-width: 0;
    }
    .stack { display: grid; gap: var(--space-4); align-content: start; }
    .stack.compact { gap: var(--space-2); }
    label {
      display: grid;
      gap: 6px;
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      font-weight: 500;
    }
    .field-help,
    .section-copy,
    .settings-subtitle {
      color: var(--text-tertiary);
      font-size: 11px;
      font-weight: 400;
      line-height: 1.45;
      max-width: 68ch;
    }
    input, textarea, select {
      width: 100%;
      border: 1px solid var(--border-default);
      background: var(--lab-workspace-letterbox);
      color: var(--text-primary);
      border-radius: var(--radius-sm);
      min-height: 38px;
      padding: var(--space-2) var(--space-3);
      transition: border-color 150ms ease, background 150ms ease, box-shadow 150ms ease;
    }
    input, textarea {
      -webkit-user-select: text;
      user-select: text;
    }
    input:hover, textarea:hover, select:hover {
      border-color: var(--border-strong);
      background: #0f0f0f;
    }
    input::placeholder, textarea::placeholder { color: var(--text-tertiary); }
    select {
      appearance: auto;
      color-scheme: dark;
    }
    textarea {
      min-height: 118px;
      resize: vertical;
      line-height: 1.4;
      font-family: var(--font-mono);
      font-size: 12px;
    }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-3); }
    .controls { display: flex; gap: var(--space-2); flex-wrap: wrap; align-items: center; }
    .checkbox {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      flex-wrap: wrap;
    }
    .checkbox input {
      width: auto;
      min-height: auto;
      accent-color: var(--accent-brand);
    }
    .checkbox .field-help {
      flex: 1 0 100%;
      padding-left: 22px;
    }
    .jobs {
      display: grid;
      gap: var(--space-3);
      margin-top: var(--space-3);
    }
    .job {
      border: 1px solid var(--border-default);
      background: var(--lab-panel-elevated);
      border-radius: var(--radius-md);
      padding: var(--space-3);
      display: grid;
      gap: var(--space-3);
      cursor: pointer;
      transition: background 150ms ease, border-color 150ms ease;
    }
    .job:hover {
      background: var(--bg-elevated-2);
      border-color: var(--border-strong);
    }
    .job.active {
      border-color: var(--accent-brand);
      background: color-mix(in srgb, var(--accent-brand) 10%, var(--lab-panel-elevated));
      box-shadow: inset 3px 0 0 var(--accent-brand);
    }
    .job-top {
      display: flex;
      justify-content: space-between;
      gap: var(--space-3);
      align-items: start;
    }
    .job-title { font-weight: 700; word-break: break-word; }
    .badge {
      border: 1px solid var(--border-default);
      border-radius: var(--radius-pill);
      padding: 3px 8px;
      font-size: 11px;
      color: var(--text-secondary);
      white-space: nowrap;
      font-family: var(--font-mono);
    }
    .badge.completed, .badge.completed_with_errors { color: var(--accent-success); border-color: color-mix(in srgb, var(--accent-success) 45%, transparent); background: var(--accent-success-muted); }
    .badge.failed, .badge.canceled { color: #fca5a5; border-color: color-mix(in srgb, var(--accent-error) 45%, transparent); background: var(--accent-error-muted); }
    .badge.running { color: var(--accent-brand-hover); border-color: color-mix(in srgb, var(--accent-brand) 45%, transparent); background: var(--accent-brand-muted); }
    .badge.ready { color: var(--accent-success); border-color: color-mix(in srgb, var(--accent-success) 45%, transparent); background: var(--accent-success-muted); }
    .badge.missing { color: #fca5a5; border-color: color-mix(in srgb, var(--accent-error) 45%, transparent); background: var(--accent-error-muted); }
    .meter {
      height: 10px;
      border: 1px solid var(--border-default);
      background: var(--lab-workspace-letterbox);
      border-radius: var(--radius-pill);
      overflow: hidden;
    }
    .meter > span {
      display: block;
      height: 100%;
      width: 0;
      background: linear-gradient(90deg, var(--accent-brand-pressed), var(--accent-brand-hover));
      transition: width 240ms ease;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: var(--space-3);
      margin: var(--space-3) 0;
    }
    .metric {
      border: 1px solid var(--border-default);
      background: var(--bg-elevated-1);
      border-radius: var(--radius-md);
      padding: var(--space-3);
    }
    .metric b {
      display: block;
      color: var(--text-primary);
      font-size: 24px;
      line-height: 1;
      margin-bottom: 5px;
    }
    .metric span { color: var(--text-secondary); font-size: var(--ops-text-label); }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      overflow-wrap: anywhere;
    }
    th, td {
      border-bottom: 1px solid var(--border-subtle);
      padding: var(--space-2) 6px;
      text-align: left;
      vertical-align: top;
    }
    th { color: var(--text-secondary); font-weight: 600; }
    .split {
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(280px, 0.9fr);
      gap: var(--space-4);
      align-items: start;
    }
    .console {
      background: var(--lab-workspace-letterbox);
      color: #d6d6d6;
      border-radius: var(--radius-md);
      min-height: 220px;
      padding: var(--space-3);
      overflow: auto;
      font: 12px/1.45 var(--font-mono);
      border: 1px solid var(--border-default);
    }
    .result {
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      padding: var(--space-3);
      background: var(--lab-panel-elevated);
      display: grid;
      gap: var(--space-1);
    }
    .result b { color: var(--text-primary); }
    .result small { color: var(--accent-brand-hover); font-family: var(--font-mono); }
    .empty {
      padding: var(--space-5);
      border: 1px dashed var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--text-secondary);
      text-align: center;
      background: rgba(255,255,255,0.02);
    }
    .section-top {
      display: flex;
      justify-content: space-between;
      gap: var(--space-3);
      align-items: start;
      border-bottom: 1px solid var(--border-default);
      padding-bottom: var(--space-3);
      margin-bottom: var(--space-4);
    }
    .section-top h2 {
      border-bottom: 0;
      padding-bottom: 0;
      margin-bottom: 0;
    }
    .section-meta {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      font-family: var(--font-mono);
      text-align: right;
    }
    .section-top > div:first-child .section-meta {
      text-align: left;
      margin-top: var(--space-2);
    }
    .section-copy {
      margin: calc(-1 * var(--space-2)) 0 var(--space-4);
      max-width: 76ch;
    }
    .section-top .section-copy { margin: var(--space-2) 0 0; }
    .overview-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: var(--space-3);
    }
    .metric-card {
      border: 1px solid var(--border-default);
      background: var(--lab-panel-elevated);
      border-radius: var(--radius-md);
      padding: var(--space-4);
      min-width: 0;
    }
    .metric-card span {
      display: block;
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      font-weight: 600;
      margin-bottom: var(--space-2);
    }
    .metric-card b {
      display: block;
      color: var(--text-primary);
      font-size: 26px;
      line-height: 1.1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .metric-card small {
      display: block;
      margin-top: var(--space-2);
      min-height: 18px;
    }
    .info-list {
      display: grid;
      gap: var(--space-2);
    }
    .info-row {
      display: grid;
      grid-template-columns: minmax(110px, 0.35fr) minmax(0, 1fr);
      gap: var(--space-3);
      border-bottom: 1px solid var(--border-subtle);
      padding: 10px 0;
      min-width: 0;
    }
    .info-row:last-child { border-bottom: 0; }
    .info-row span {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      font-weight: 600;
    }
    .info-row b {
      color: var(--text-primary);
      font-weight: 500;
      overflow-wrap: anywhere;
      display: inline-flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-2);
    }
    .info-row span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .info-row-icon {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 14px;
      height: 14px;
      color: var(--text-tertiary);
    }
    .info-row-icon svg {
      width: 14px;
      height: 14px;
    }
    .info-row-meter {
      flex: 1 1 100px;
      min-width: 80px;
      max-width: 160px;
      height: 4px;
      background: var(--bg-elevated-1);
      border-radius: var(--radius-pill);
      overflow: hidden;
    }
    .info-row-meter > span {
      display: block;
      height: 100%;
      background: var(--accent-brand);
      border-radius: inherit;
      transition: width 240ms ease;
    }
    .info-row.has-pill b {
      justify-content: flex-start;
    }
    /* ─── Status pills (reused across diagnostics + overview) ─────────── */
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 3px 10px;
      border-radius: var(--radius-pill);
      font-size: 11px;
      font-weight: 600;
      line-height: 1;
      letter-spacing: 0.02em;
      text-transform: uppercase;
      white-space: nowrap;
      border: 1px solid transparent;
    }
    .status-pill::before {
      content: '';
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: currentColor;
      flex: 0 0 6px;
    }
    .status-pill.pill-ok {
      background: var(--accent-success-muted);
      color: var(--accent-success);
      border-color: rgba(34, 197, 94, 0.35);
    }
    .status-pill.pill-warn {
      background: var(--accent-warning-muted);
      color: var(--accent-warning);
      border-color: rgba(245, 158, 11, 0.35);
    }
    .status-pill.pill-err {
      background: var(--accent-error-muted);
      color: var(--accent-error);
      border-color: rgba(239, 68, 68, 0.4);
    }
    .status-pill.pill-info {
      background: var(--accent-brand-muted);
      color: var(--accent-brand-hover);
      border-color: rgba(30, 144, 255, 0.35);
    }
    .status-pill.pill-mute {
      background: rgba(160, 160, 160, 0.08);
      color: var(--text-secondary);
      border-color: var(--border-default);
    }
    /* ─── Diagnostic cards ────────────────────────────────────────────── */
    .diag-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: var(--space-3);
      margin-top: var(--space-3);
    }
    .diag-card {
      background: var(--lab-panel-elevated);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      padding: var(--space-4);
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      min-width: 0;
    }
    .diag-card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-2);
    }
    .diag-card-title {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      color: var(--text-primary);
      font-size: var(--ops-text-body);
      font-weight: 600;
    }
    .diag-card-title svg {
      width: 16px;
      height: 16px;
      color: var(--text-secondary);
    }
    .diag-card-rows {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .diag-row {
      display: grid;
      grid-template-columns: minmax(80px, 0.4fr) minmax(0, 1fr);
      gap: var(--space-3);
      align-items: baseline;
      font-size: 12.5px;
    }
    .diag-row .diag-label {
      color: var(--text-secondary);
      font-weight: 600;
      letter-spacing: 0.01em;
    }
    .diag-row .diag-value {
      color: var(--text-primary);
      overflow-wrap: anywhere;
    }
    .diag-row .diag-value.muted {
      color: var(--text-tertiary);
    }
    .diag-card-footer {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-2);
      margin-top: auto;
      padding-top: var(--space-2);
      border-top: 1px solid var(--border-subtle);
      color: var(--text-tertiary);
      font-size: 11px;
    }
    .pill-legend {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
      margin-top: var(--space-4);
      padding: var(--space-3) var(--space-4);
      border: 1px dashed var(--border-default);
      border-radius: var(--radius-md);
      color: var(--text-tertiary);
      font-size: 11px;
    }
    .pill-legend-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    /* Path field with inline browse button */
    .path-field {
      display: flex;
      gap: var(--space-2);
      align-items: stretch;
    }
    .path-field input {
      flex: 1 1 auto;
      min-width: 0;
    }
    .path-field .path-browse {
      flex: 0 0 auto;
      white-space: nowrap;
    }
    .path-recent {
      margin-top: 6px;
      width: 100%;
    }
    /* Tool chips (denser than legacy tool-row) */
    .tool-chip-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: var(--space-2);
      margin-top: var(--space-3);
    }
    .tool-chip {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      padding: 10px var(--space-3);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: var(--lab-panel-elevated);
      min-width: 0;
    }
    .tool-chip-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-2);
      min-width: 0;
    }
    .tool-chip-name {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .tool-chip-name strong {
      color: var(--text-primary);
      font-size: 12.5px;
      font-weight: 600;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .tool-chip-name small {
      color: var(--text-tertiary);
      font-size: 10.5px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .tool-chip-install {
      display: flex;
      flex-direction: column;
      gap: 6px;
      border-top: 1px dashed var(--border-default);
      padding-top: 8px;
      margin-top: 2px;
    }
    .tool-chip-cmd {
      display: block;
      font-family: var(--ops-font-mono, ui-monospace, SFMono-Regular, monospace);
      font-size: 11px;
      color: var(--text-secondary);
      background: var(--bg-elevated-2);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      padding: 6px 8px;
      overflow-x: auto;
      white-space: nowrap;
    }
    .tool-chip-note {
      color: var(--text-tertiary);
      font-size: 10.5px;
      line-height: 1.35;
    }
    .tool-chip-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .tool-chip-actions .btn-mini {
      min-height: 26px;
      padding: 0 10px;
      font-size: 11px;
      font-weight: 500;
      border-radius: var(--radius-sm);
      background: var(--bg-elevated-2);
      border: 1px solid var(--border-default);
      color: var(--text-primary);
    }
    .tool-chip-actions .btn-mini:hover {
      background: var(--bg-hover);
      border-color: var(--border-strong);
    }
    .tool-chip-actions .btn-mini.primary {
      background: var(--accent-brand);
      border-color: color-mix(in srgb, var(--accent-brand) 45%, transparent);
      color: #ffffff;
    }
    .tool-chip-actions .btn-mini.primary:hover {
      background: var(--accent-brand-hover);
      border-color: var(--accent-brand-hover);
    }
    .tool-chip-status {
      font-size: 10.5px;
      color: var(--text-tertiary);
      min-height: 14px;
    }
    /* ─── Readiness card (coverage_report rollup) ─────────────────────── */
    .readiness-card {
      margin: var(--space-4) 0;
      padding: var(--space-3) var(--space-4);
      border: 1px solid var(--border-default);
      background: var(--lab-panel-elevated);
      border-radius: var(--radius-md);
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
    }
    .readiness-card-header {
      display: flex;
      align-items: center;
      gap: var(--space-3);
    }
    .readiness-title {
      font-weight: 600;
      color: var(--text-primary);
      letter-spacing: 0.02em;
      text-transform: uppercase;
      font-size: 11px;
    }
    .readiness-evidence {
      flex: 1;
      color: var(--text-secondary);
      font-size: 13px;
      line-height: 1.4;
    }
    .readiness-summary-row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
    }
    .readiness-stat {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 84px;
      padding: var(--space-2) var(--space-3);
      border-radius: var(--radius-sm);
      background: var(--bg-subtle);
    }
    .readiness-stat .stat-value {
      font-size: 22px;
      font-weight: 600;
      color: var(--text-primary);
    }
    .readiness-stat .stat-label {
      font-size: 10.5px;
      color: var(--text-tertiary);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .readiness-stat.warn .stat-value { color: var(--accent-warn, #d18b00); }
    .readiness-stat.danger .stat-value { color: var(--accent-danger, #d24c4c); }
    .readiness-stat.good .stat-value { color: var(--accent-success, #4caf50); }
    .readiness-details {
      color: var(--text-tertiary);
      font-size: 11.5px;
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
    }
    .readiness-details .chip {
      padding: 2px 8px;
      border-radius: 999px;
      background: var(--bg-subtle);
      color: var(--text-secondary);
    }
    /* ─── V2 Review surface ───────────────────────────────────────────── */
    .review-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: var(--space-4);
      margin-top: var(--space-4);
    }
    .review-clip-card {
      position: relative;
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      border: 1px solid var(--border-default);
      background: var(--lab-panel-elevated);
      border-radius: var(--radius-md);
      padding: var(--space-3);
      cursor: pointer;
      transition: border-color 150ms ease, transform 100ms ease, background 150ms ease, box-shadow 150ms ease;
      min-width: 0;
    }
    .review-clip-card:hover {
      border-color: var(--accent-brand);
      background: var(--bg-hover);
    }
    .review-clip-card:active { transform: translateY(1px); }
    .review-clip-card.is-selected {
      border-color: var(--accent-brand);
      box-shadow: 0 0 0 1px var(--accent-brand) inset;
      background: var(--accent-brand-subtle);
    }
    .review-card-select {
      position: absolute;
      top: 8px;
      left: 8px;
      width: 22px;
      height: 22px;
      min-height: 22px;
      padding: 0;
      border-radius: 4px;
      border: 1px solid var(--border-strong);
      background: rgba(20, 19, 18, 0.7);
      backdrop-filter: blur(4px);
      color: var(--text-primary);
      opacity: 0;
      transition: opacity 120ms ease, border-color 120ms ease, background 120ms ease;
      z-index: 2;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .review-clip-card:hover .review-card-select,
    .review-clip-card.is-selected .review-card-select,
    .review-clip-card:focus-within .review-card-select { opacity: 1; }
    .review-card-select .select-box {
      width: 14px;
      height: 14px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .review-card-select .select-box svg {
      width: 14px;
      height: 14px;
      color: var(--accent-brand);
    }
    .review-clip-card.is-selected .review-card-select {
      background: var(--accent-brand);
      border-color: var(--accent-brand);
    }
    .review-clip-card.is-selected .review-card-select .select-box svg {
      color: #fff;
    }
    .bin-selection-toolbar {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      margin-left: var(--space-3);
    }
    .context-menu {
      position: absolute;
      z-index: 200;
      min-width: 220px;
      padding: 6px;
      background: var(--lab-panel-elevated);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      box-shadow: 0 16px 40px rgba(0, 0, 0, 0.55);
      display: flex;
      flex-direction: column;
      gap: 2px;
      font-size: 13px;
    }
    .context-menu-header {
      padding: 6px 10px;
      color: var(--text-tertiary);
      font-size: 11px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      border-bottom: 1px solid var(--border-subtle);
      margin-bottom: 4px;
    }
    .context-menu-item {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      background: transparent;
      border: 1px solid transparent;
      border-radius: var(--radius-sm);
      color: var(--text-primary);
      text-align: left;
      cursor: pointer;
      min-height: 30px;
      transition: background 100ms ease, color 100ms ease, border-color 100ms ease;
    }
    .context-menu-item:hover,
    .context-menu-item:focus { background: var(--bg-hover); outline: none; }
    .context-menu-item[disabled] { opacity: 0.4; cursor: not-allowed; }
    .context-menu-item .shortcut {
      margin-left: auto;
      color: var(--text-tertiary);
      font-size: 11px;
      font-family: var(--font-mono);
    }
    .context-menu-divider {
      height: 1px;
      background: var(--border-subtle);
      margin: 4px 0;
    }
    .context-menu-sub {
      display: flex;
      flex-direction: column;
      gap: 2px;
      padding: 6px 10px;
      border: 1px dashed var(--border-default);
      border-radius: var(--radius-sm);
      margin: 4px 6px;
    }
    .context-menu-sub label {
      color: var(--text-secondary);
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.03em;
      text-transform: uppercase;
    }
    .context-menu-sub .star-row { display: inline-flex; gap: 2px; }
    .context-menu-sub .star-row button {
      width: 22px;
      height: 22px;
      min-height: 22px;
      padding: 0;
      border-radius: var(--radius-sm);
      background: transparent;
      border: 1px solid var(--border-default);
      color: var(--text-secondary);
    }
    .context-menu-sub .star-row button.filled {
      color: var(--accent-warning);
      border-color: var(--accent-warning);
    }
    .context-menu-sub input[type="text"] {
      width: 100%;
      min-height: 28px;
      padding: 4px 8px;
      background: var(--bg-elevated-1);
      border: 1px solid var(--border-default);
      color: var(--text-primary);
      border-radius: var(--radius-sm);
    }
    .context-menu-status {
      padding: 6px 10px;
      color: var(--text-tertiary);
      font-size: 11px;
    }
    #reviewBinSummary {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      flex-wrap: wrap;
    }
    .review-thumb {
      width: 100%;
      aspect-ratio: 16 / 9;
      background: var(--lab-workspace-letterbox);
      border-radius: var(--radius-sm);
      object-fit: cover;
      display: block;
    }
    .review-thumb.placeholder {
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--text-tertiary);
      font-size: var(--ops-text-label);
    }
    .review-clip-card-name {
      font-weight: 600;
      color: var(--text-primary);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .review-clip-card-meta {
      display: flex;
      gap: var(--space-2);
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      flex-wrap: wrap;
    }
    .review-chip {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 8px;
      border-radius: var(--radius-pill);
      background: var(--bg-elevated-2);
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      font-weight: 500;
    }
    .review-chip.select-high { background: var(--accent-success-muted); color: var(--accent-success); }
    .review-chip.select-medium { background: var(--accent-warning-muted); color: var(--accent-warning); }
    .review-chip.select-low { background: var(--accent-error-muted); color: var(--accent-error); }
    .review-clip-card-oneliner {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      display: -webkit-box;
      -webkit-line-clamp: 2;
      line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .review-clip-header {
      display: flex;
      gap: var(--space-3);
      align-items: baseline;
      flex-wrap: wrap;
      margin-top: var(--space-2);
    }
    .review-clip-header .name {
      font-size: var(--ops-text-heading);
      font-weight: 600;
      color: var(--text-primary);
    }
    .review-clip-header .meta {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
    }
    .review-clip-header .actions {
      margin-left: auto;
      display: flex;
      gap: var(--space-2);
    }
    .review-clip-summary {
      margin-top: var(--space-3);
      color: var(--text-primary);
      line-height: var(--ops-leading-normal);
    }
    .review-clip-tags {
      display: flex;
      gap: var(--space-1);
      flex-wrap: wrap;
      margin-top: var(--space-3);
    }
    .review-analysis-blocks {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      margin-top: var(--space-5);
    }
    .review-analysis-block {
      background: var(--lab-panel-elevated);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      padding: var(--space-4);
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      min-width: 0;
    }
    .review-analysis-block .block-title {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      font-weight: 700;
      letter-spacing: 0.03em;
      text-transform: uppercase;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-2);
    }
    .review-analysis-block .block-row {
      display: grid;
      grid-template-columns: minmax(96px, 0.42fr) minmax(0, 1fr);
      gap: var(--space-2) var(--space-3);
      align-items: baseline;
      font-size: 12.5px;
      line-height: 1.45;
    }
    .review-analysis-block .block-row .label {
      color: var(--text-secondary);
      font-weight: 600;
    }
    .review-analysis-block .block-row .value {
      color: var(--text-primary);
      overflow-wrap: anywhere;
    }
    .review-analysis-block .chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .review-analysis-block .review-chip {
      font-size: 11px;
      padding: 2px 8px;
    }
    .review-analysis-block .block-empty {
      color: var(--text-tertiary);
      font-size: 12px;
      font-style: italic;
    }
    .review-analysis-block ul.block-list {
      margin: 0;
      padding-left: 16px;
      color: var(--text-primary);
      font-size: 12.5px;
      line-height: 1.5;
    }
    .review-analysis-block ul.block-list li {
      margin-bottom: 2px;
    }
    .review-shot-strip-wrap {
      margin-top: var(--space-5);
      border-top: 1px solid var(--border-subtle);
      padding-top: var(--space-4);
    }
    .review-shot-strip-label,
    .review-shot-frames-label {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      font-weight: 700;
      text-transform: uppercase;
      margin-bottom: var(--space-2);
    }
    .review-shot-strip {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
      gap: var(--space-2);
      padding-bottom: var(--space-2);
    }
    .review-shot-strip .review-shot-strip-card {
      cursor: pointer;
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      padding: 6px;
      background: var(--lab-panel-elevated);
      transition: border-color 150ms ease;
      min-width: 0;
    }
    .review-shot-strip-card:hover { border-color: var(--accent-brand); }
    .review-shot-strip-card .label {
      display: flex;
      justify-content: space-between;
      font-size: var(--ops-text-label);
      margin-top: 4px;
      color: var(--text-secondary);
    }
    .review-shot-strip-card .role { color: var(--text-tertiary); }
    .review-cross-shot {
      margin-top: var(--space-5);
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
    }
    .review-transcript-search-row {
      margin-top: var(--space-3);
      margin-bottom: var(--space-3);
    }
    .review-transcript-search-row input {
      width: 100%;
      min-height: 36px;
      padding: 0 var(--space-3);
    }
    .review-transcript-body {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .review-transcript-segment {
      display: grid;
      grid-template-columns: 92px 1fr auto;
      gap: var(--space-3);
      padding: 10px var(--space-3);
      align-items: baseline;
      background: var(--lab-panel-elevated);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      transition: border-color 150ms ease, background 150ms ease;
      scroll-margin-top: 96px;
    }
    .review-transcript-segment:hover {
      border-color: var(--accent-brand);
    }
    .review-transcript-segment.is-match {
      border-color: var(--accent-warning);
      background: rgba(245, 158, 11, 0.06);
    }
    .review-transcript-segment .tc {
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-tertiary);
    }
    .review-transcript-segment .text {
      color: var(--text-primary);
      line-height: 1.55;
      font-size: 13px;
      overflow-wrap: anywhere;
    }
    .review-transcript-segment .actions {
      display: inline-flex;
      gap: 6px;
      opacity: 0;
      transition: opacity 150ms ease;
    }
    .review-transcript-segment:hover .actions,
    .review-transcript-segment:focus-within .actions { opacity: 1; }
    .review-transcript-segment .actions button {
      font-size: 11px;
      padding: 2px 8px;
      min-height: 22px;
    }
    .review-transcript-segment .transcript-segment-body {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
    }
    .review-transcript-segment.editing {
      background: rgba(245, 158, 11, 0.04);
      border-color: rgba(245, 158, 11, 0.35);
    }
    .transcript-edit-actions { opacity: 1 !important; }
    .transcript-words {
      display: flex;
      flex-wrap: wrap;
      gap: 2px 4px;
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-tertiary);
      line-height: 1.5;
    }
    .transcript-words.editable {
      display: block;
      font-family: var(--font-sans);
      font-size: 13px;
      color: var(--text-primary);
      line-height: 1.6;
      padding: 8px 10px;
      background: var(--bg-elevated-1);
      border: 1px solid var(--accent-warning);
      border-radius: var(--radius-sm);
      outline: none;
      box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.18);
    }
    .transcript-words.editable .transcript-word {
      cursor: text;
      background: transparent;
      color: var(--text-primary);
      font-family: var(--font-sans);
      font-size: 13px;
      padding: 0 2px;
    }
    .transcript-words.editable .transcript-word:hover { background: transparent; }
    .segment-text-edit {
      width: 100%;
      min-height: 56px;
      resize: vertical;
      font-family: var(--font-sans);
      font-size: 13px;
      line-height: 1.5;
      padding: 8px 10px;
      background: var(--bg-elevated-1);
      border: 1px solid var(--accent-warning);
      border-radius: var(--radius-sm);
      color: var(--text-primary);
      outline: none;
    }
    .segment-text-edit:focus { box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.18); }
    .segment-text-hint {
      color: var(--text-tertiary);
      font-size: 11px;
      margin-top: 4px;
      font-style: italic;
    }
    .segment-edit-btn { opacity: 0; transition: opacity 120ms ease; }
    .review-transcript-segment:hover .segment-edit-btn,
    .review-transcript-segment:focus-within .segment-edit-btn { opacity: 1; }
    .transcript-word {
      padding: 1px 4px;
      border-radius: 3px;
      cursor: pointer;
      transition: background 100ms ease, color 100ms ease;
    }
    .transcript-word:hover {
      background: var(--accent-brand-muted);
      color: var(--accent-brand-hover);
    }
    .transcript-word.selected {
      background: var(--accent-warning-muted);
      color: var(--accent-warning);
      box-shadow: inset 0 -1px 0 var(--accent-warning);
    }
    .combined-shots {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-top: 8px;
    }
    .combined-shot-row {
      display: grid;
      grid-template-columns: 140px 1fr;
      gap: var(--space-3);
      padding: 10px var(--space-3);
      background: var(--lab-panel-elevated);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
    }
    .combined-shot-row .tc {
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--text-tertiary);
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .combined-shot-row .tc .tc-end { color: var(--border-strong); }
    .combined-shot-row .body .src {
      color: var(--text-secondary);
      font-size: 11px;
      margin-bottom: 4px;
    }
    .combined-shot-row .body .src a {
      color: var(--accent-brand-hover);
      text-decoration: none;
    }
    .combined-shot-row .body .desc {
      color: var(--text-primary);
      font-size: 13px;
      line-height: 1.5;
    }
    .review-shot-header {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-3);
      align-items: baseline;
      margin-top: var(--space-2);
    }
    .review-shot-header .name {
      font-size: var(--ops-text-heading);
      font-weight: 600;
    }
    .review-shot-header .meta {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
    }
    .review-shot-header .actions {
      margin-left: auto;
      display: flex;
      gap: var(--space-2);
    }
    .review-shot-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
      gap: var(--space-5);
      margin-top: var(--space-4);
    }
    @media (max-width: 980px) {
      .review-shot-grid { grid-template-columns: 1fr; }
    }
    .review-shot-fields .group {
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: var(--space-3);
      margin-bottom: var(--space-3);
      background: var(--lab-panel-elevated);
    }
    .review-shot-fields .group-title {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      font-weight: 700;
      text-transform: uppercase;
      margin-bottom: var(--space-2);
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .review-shot-fields .conf {
      padding: 1px 6px;
      border-radius: var(--radius-pill);
      font-size: 11px;
      letter-spacing: 0.04em;
    }
    .review-shot-fields .conf.high { background: var(--accent-success-muted); color: var(--accent-success); }
    .review-shot-fields .conf.medium { background: var(--accent-warning-muted); color: var(--accent-warning); }
    .review-shot-fields .conf.low { background: var(--accent-error-muted); color: var(--accent-error); }
    .review-shot-fields .field {
      display: grid;
      grid-template-columns: minmax(120px, 0.4fr) minmax(0, 1fr);
      gap: var(--space-3);
      padding: 6px 0;
      border-bottom: 1px solid var(--border-subtle);
    }
    .review-shot-fields .field:last-child { border-bottom: 0; }
    .review-shot-fields .field .label {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      font-weight: 600;
    }
    .review-shot-fields .field .value {
      color: var(--text-primary);
      overflow-wrap: anywhere;
    }
    .review-shot-fields .field.edited .value::after {
      content: " (human-edited)";
      color: var(--accent-ai);
      font-size: var(--ops-text-label);
    }
    .review-shot-fields .field input,
    .review-shot-fields .field select,
    .review-shot-fields .field textarea {
      width: 100%;
      background: var(--bg-elevated-1);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      color: var(--text-primary);
      padding: 4px 8px;
    }
    .review-shot-fields .field-actions {
      display: flex;
      gap: var(--space-2);
      margin-top: var(--space-3);
    }
    .review-shot-frame-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
      gap: var(--space-2);
    }
    .review-shot-frame-card {
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-sm);
      padding: 4px;
      background: var(--lab-panel-elevated);
    }
    .review-shot-frame-card .label {
      font-size: var(--ops-text-label);
      color: var(--text-secondary);
      display: flex;
      justify-content: space-between;
      margin-top: 4px;
    }
    .review-shot-frame-card.peak { border-color: var(--accent-brand); }
    .review-bin-summary {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      margin-bottom: var(--space-3);
    }
    .review-bin-filters {
      display: flex;
      gap: var(--space-2);
      align-items: center;
      margin-bottom: var(--space-3);
      flex-wrap: wrap;
    }
    .review-semantic-toggle {
      display: inline-flex;
      gap: 6px;
      align-items: center;
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      white-space: nowrap;
    }
    .review-entities {
      margin-bottom: var(--space-3);
      padding: var(--space-2) var(--space-3);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
    }
    .review-entities-title {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      margin-bottom: 6px;
    }
    .review-entities-chips {
      display: flex;
      gap: var(--space-2);
      flex-wrap: wrap;
    }
    .review-bin-filters input[type="search"] {
      flex: 1 1 280px;
      min-width: 200px;
      background: var(--bg-elevated-1);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      color: var(--text-primary);
      padding: 6px 10px;
      min-height: 34px;
    }
    .review-bin-filters select {
      background: var(--bg-elevated-1);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      color: var(--text-primary);
      padding: 6px 10px;
      min-height: 34px;
    }
    .review-view-toggle {
      display: inline-flex;
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      overflow: hidden;
    }
    .review-view-toggle button {
      background: var(--bg-elevated-2);
      border: 0;
      color: var(--text-secondary);
      padding: 0 var(--space-3);
      min-height: 34px;
      cursor: pointer;
      border-radius: 0;
    }
    .review-view-toggle button.active {
      background: var(--accent-brand-muted);
      color: var(--accent-brand);
    }
    .review-list {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
    }
    .review-list .review-clip-card {
      flex-direction: row;
      align-items: center;
      padding: var(--space-2);
    }
    .review-list .review-thumb {
      width: 160px;
      flex: 0 0 160px;
      aspect-ratio: 16 / 9;
    }
    .review-list .review-clip-card-name { flex: 1 1 auto; }
    .review-list .review-clip-card-meta { flex-shrink: 0; }
    .review-list .review-clip-card-oneliner { flex: 2 1 0; }

    /* ─── C6 Timeline history view ──────────────────────────────────── */
    .history-layout {
      display: grid;
      grid-template-columns: 280px 1fr;
      gap: var(--space-3);
      align-items: start;
    }
    .history-sidebar {
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: var(--lab-panel-elevated);
      padding: var(--space-2);
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      max-height: 70vh;
      overflow-y: auto;
    }
    .history-sidebar-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-2);
      font-size: var(--text-sm);
    }
    .history-timeline-list {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
    }
    .history-timeline-row {
      cursor: pointer;
      padding: var(--space-1) var(--space-2);
      border-radius: var(--radius-sm);
      border: 1px solid transparent;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: var(--space-2);
      font-size: var(--text-sm);
    }
    .history-timeline-row:hover { background: var(--bg-muted); }
    .history-timeline-row.is-selected {
      border-color: var(--accent-primary);
      background: var(--bg-muted);
    }
    .history-timeline-row .name { font-weight: 500; }
    .history-timeline-row .count {
      font-size: var(--text-xs);
      color: var(--text-muted);
    }
    .history-archive-now {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
      margin-top: auto;
      padding-top: var(--space-2);
      border-top: 1px solid var(--border-default);
    }
    .history-archive-now button { width: 100%; }
    .history-archive-now input {
      width: 100%;
      padding: var(--space-1) var(--space-2);
      border: 1px solid var(--border-default);
      background: var(--bg-base);
      color: var(--text-primary);
      border-radius: var(--radius-sm);
      font-size: var(--text-xs);
    }
    .history-detail {
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: var(--lab-panel-elevated);
      padding: var(--space-3);
      min-height: 300px;
    }
    .history-detail-header {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: var(--space-2);
      margin-bottom: var(--space-3);
      padding-bottom: var(--space-2);
      border-bottom: 1px solid var(--border-default);
    }
    .history-detail-header .timeline-name {
      font-size: var(--text-base);
      font-weight: 600;
    }
    .history-detail-body {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    .history-version-card {
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      padding: var(--space-2);
      background: var(--bg-base);
      display: grid;
      grid-template-columns: 160px 1fr;
      gap: var(--space-3);
    }
    .history-version-card .thumb {
      aspect-ratio: 16/9;
      background: var(--bg-muted);
      border-radius: var(--radius-sm);
      overflow: hidden;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--text-muted);
      font-size: var(--text-xs);
    }
    .history-version-card .thumb img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .history-version-card .body {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      min-width: 0;
    }
    .history-version-card .version-row {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      justify-content: space-between;
    }
    .history-version-card .version-label {
      font-size: var(--text-sm);
      font-weight: 600;
    }
    .history-version-card .archived-name {
      font-size: var(--text-xs);
      color: var(--text-muted);
      font-family: var(--font-mono);
    }
    .history-version-card .timestamp {
      font-size: var(--text-xs);
      color: var(--text-muted);
    }
    .history-version-card .reason {
      font-size: var(--text-xs);
      color: var(--text-muted);
      font-style: italic;
    }
    .history-version-card .drt-collapsed {
      font-size: var(--text-xs);
      color: var(--accent-warning);
    }
    .history-edits-table {
      width: 100%;
      border-collapse: collapse;
      font-size: var(--text-xs);
    }
    .history-edits-table th, .history-edits-table td {
      padding: var(--space-1) var(--space-2);
      border-bottom: 1px solid var(--border-default);
      text-align: left;
      vertical-align: top;
    }
    .history-edits-table th { color: var(--text-muted); font-weight: 500; }
    .history-edits-table .edit-type {
      font-family: var(--font-mono);
      color: var(--text-primary);
    }
    .history-edits-table .metric { color: var(--text-muted); }
    .history-edits-table .delta-pos { color: var(--accent-success); }
    .history-edits-table .delta-neg { color: var(--accent-error); }
    .history-edits-table .delta-zero { color: var(--text-muted); }
    .history-rollback-btn {
      background: var(--accent-warning-muted);
      color: var(--accent-warning);
      border: 1px solid var(--accent-warning);
      padding: var(--space-1) var(--space-2);
      border-radius: var(--radius-sm);
      cursor: pointer;
      font-size: var(--text-xs);
    }
    .history-rollback-btn:hover { background: var(--accent-warning); color: var(--bg-base); }

    /* ─── Edit-engine plan browser ──────────────────────────────────── */
    .plans-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-3);
      margin-bottom: var(--space-3);
    }
    .plans-toolbar .section-meta { margin-left: var(--space-2); }
    .plans-list { display: grid; gap: var(--space-2); }
    .plan-row {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      padding: var(--space-2) var(--space-3);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: var(--lab-panel-elevated, var(--bg-base));
      cursor: pointer;
    }
    .plan-row:hover { background: var(--bg-muted); }
    .plan-row.is-corrupt {
      cursor: default;
      border-color: var(--accent-warning);
      background: var(--accent-warning-muted);
    }
    .plan-row .summary { flex: 1; min-width: 0; }
    .plan-row .saved-at { color: var(--text-muted); font-size: var(--text-xs); white-space: nowrap; }
    .plan-chip {
      display: inline-block;
      padding: 1px var(--space-2);
      border-radius: var(--radius-sm);
      font-size: var(--text-xs);
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      border: 1px solid var(--border-default);
      color: var(--text-secondary);
      white-space: nowrap;
    }
    .plan-chip.kind-selects { color: var(--accent-success); border-color: var(--accent-success); }
    .plan-chip.kind-tighten { color: var(--accent-warning); border-color: var(--accent-warning); }
    .plan-chip.kind-swap { color: var(--accent-info, var(--text-secondary)); border-color: currentColor; }
    .plan-chip.executed { color: var(--text-muted); text-transform: none; letter-spacing: 0; }
    .plan-chip.corrupt { color: var(--accent-warning); border-color: var(--accent-warning); }
    .plan-detail-header {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: var(--space-2);
      margin-bottom: var(--space-3);
    }
    .plan-detail-header .timeline-name { font-weight: 600; font-size: var(--text-md); }
    .plan-detail-body { display: grid; gap: var(--space-3); }
    .plan-section {
      padding: var(--space-3);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: var(--lab-panel-elevated, var(--bg-base));
    }
    .plan-section > strong { display: block; margin-bottom: var(--space-2); }
    .plan-decision-card {
      display: flex;
      gap: var(--space-3);
      padding: var(--space-2) 0;
      border-bottom: 1px solid var(--border-default);
    }
    .plan-decision-card:last-child { border-bottom: none; }
    .plan-decision-card .review-thumb { width: 120px; height: 68px; object-fit: cover; border-radius: var(--radius-sm); flex: none; }
    .plan-decision-card .review-thumb.placeholder {
      display: flex; align-items: center; justify-content: center;
      background: var(--bg-muted); color: var(--text-muted); font-size: var(--text-xs);
    }
    .plan-decision-card .body { flex: 1; min-width: 0; display: grid; gap: 2px; align-content: start; }
    .plan-decision-card .title-row { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
    .plan-decision-card .rationale { color: var(--text-secondary); font-size: var(--text-xs); }
    .plan-decision-card .meta { color: var(--text-muted); font-size: var(--text-xs); }

    /* ─── Analysis caps preferences widget ──────────────────────────── */
    .caps-section {
      margin-top: var(--space-4);
      padding: var(--space-3);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: var(--lab-panel-elevated, var(--bg-base));
    }
    .caps-section + .caps-section { margin-top: var(--space-3); }
    .caps-section-head {
      display: flex;
      flex-direction: column;
      gap: 2px;
      margin-bottom: var(--space-2);
    }
    .caps-section-title {
      font-size: var(--text-sm);
      font-weight: 600;
      color: var(--text-primary);
    }
    .caps-section-hint {
      font-size: var(--text-xs);
      color: var(--text-muted);
    }
    .ai-op-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-3);
      grid-column: 1 / -1;
      margin: var(--space-1) 0;
    }
    .ai-op-btn {
      padding: 6px 14px;
      border-radius: var(--radius-sm, 6px);
      border: 1px solid var(--border, rgba(255,255,255,0.18));
      background: var(--accent, #3b82f6);
      color: #fff;
      font-size: var(--text-sm, 13px);
      cursor: pointer;
    }
    .ai-op-btn:hover { filter: brightness(1.08); }
    .ai-op-btn:disabled { opacity: 0.4; cursor: not-allowed; filter: none; }
    .ai-op-btn.ghost { background: transparent; color: var(--text, inherit); }
    .ai-op-btn.danger { background: #b4452f; }
    .ai-caps-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: var(--space-2);
      margin-top: var(--space-2);
    }
    .ai-caps-item {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: var(--text-xs);
    }
    .ai-caps-dot { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto; }
    .ai-caps-dot.on { background: #34a853; }
    .ai-caps-dot.off { background: rgba(255,255,255,0.25); }
    .ai-caps-extra { opacity: 0.6; }
    .ai-console-result {
      white-space: pre-wrap;
      font-family: var(--mono, ui-monospace, monospace);
      max-height: 240px;
      overflow: auto;
    }
    .ai-console-result.ok { color: var(--text, inherit); }
    .ai-console-result.err { color: #e06c5a; }
    .caps-section-subtitle {
      font-size: var(--text-xs);
      color: var(--text-muted);
      margin-top: var(--space-2);
      margin-bottom: var(--space-1);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    /* Preset cards */
    .caps-preset-cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: var(--space-2);
    }
    .caps-preset-card {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
      padding: var(--space-2) var(--space-3);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      background: var(--bg-base);
      cursor: pointer;
      text-align: left;
      transition: border-color 150ms ease, background 150ms ease, transform 150ms ease;
      color: inherit;
      font: inherit;
    }
    .caps-preset-card:hover {
      border-color: var(--accent-primary);
      background: var(--bg-muted);
    }
    .caps-preset-card.is-active {
      border-color: var(--accent-primary);
      background: var(--accent-primary-muted, rgba(64, 156, 255, 0.12));
      box-shadow: 0 0 0 1px var(--accent-primary) inset;
    }
    .caps-preset-card-head {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
    }
    .caps-preset-card-name {
      font-size: var(--text-sm);
      font-weight: 600;
      text-transform: capitalize;
    }
    .caps-preset-card-badge {
      font-size: 10px;
      color: var(--accent-primary);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .caps-preset-card-tag {
      font-size: var(--text-xs);
      color: var(--text-muted);
    }
    .caps-preset-card-stats {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 2px var(--space-1);
      font-size: 11px;
      font-family: var(--font-mono);
      color: var(--text-muted);
    }
    .caps-preset-card-stats .stat-label { color: var(--text-muted); }
    .caps-preset-card-stats .stat-value { color: var(--text-primary); text-align: right; }
    .caps-preset-card.is-active .stat-value { color: var(--accent-primary); }

    /* Gauges */
    .caps-usage-block {
      padding: 0;
      background: transparent;
      border: 0;
    }
    .caps-usage-gauges {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: var(--space-2);
    }
    .caps-gauge {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: var(--space-2);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      background: var(--bg-base);
    }
    .caps-gauge-row {
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: var(--space-1);
    }
    .caps-gauge-label {
      font-size: 11px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .caps-gauge-bar {
      height: 6px;
      background: var(--bg-muted);
      border-radius: 3px;
      overflow: hidden;
    }
    .caps-gauge-fill {
      display: block;
      height: 100%;
      width: 0%;
      background: var(--accent-success);
      transition: width 200ms ease, background 200ms ease;
    }
    .caps-gauge[data-state="warn"] .caps-gauge-fill { background: var(--accent-warning); }
    .caps-gauge[data-state="over"] .caps-gauge-fill { background: var(--accent-error); }
    .caps-gauge-numbers {
      font-size: 11px;
      font-family: var(--font-mono);
      color: var(--text-primary);
    }

    /* Advanced overrides */
    .caps-advanced > summary,
    .caps-inspector-block > summary {
      cursor: pointer;
      display: flex;
      flex-direction: column;
      gap: 2px;
      list-style: none;
      padding: 0;
      margin: 0 0 var(--space-2);
    }
    .caps-advanced > summary::-webkit-details-marker,
    .caps-inspector-block > summary::-webkit-details-marker { display: none; }
    .caps-advanced > summary::before,
    .caps-inspector-block > summary::before {
      content: '▸';
      display: inline-block;
      margin-right: var(--space-1);
      color: var(--text-muted);
      transition: transform 120ms ease;
    }
    .caps-advanced[open] > summary::before,
    .caps-inspector-block[open] > summary::before { transform: rotate(90deg); }
    .caps-override-grid input {
      width: 100%;
      padding: var(--space-1) var(--space-2);
      border: 1px solid var(--border-default);
      background: var(--bg-base);
      color: var(--text-primary);
      border-radius: var(--radius-sm);
      font-size: var(--text-xs);
      font-family: var(--font-mono);
    }
    .caps-override-grid input::placeholder {
      color: var(--text-muted);
      opacity: 0.7;
      font-style: italic;
    }

    /* Safety subsection */
    .safety-strict-block {
      margin-top: var(--space-3);
      padding-top: var(--space-2);
      border-top: 1px dashed var(--border-default);
    }
    .safety-strict-title {
      font-size: var(--text-xs);
      color: var(--text-muted);
      margin-bottom: var(--space-1);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .safety-strict-note {
      font-size: var(--text-xs);
      color: var(--text-muted);
      margin-top: var(--space-2);
      line-height: 1.5;
    }

    /* ─── Caps history chart + inspector + refusals ──────────────── */
    .caps-history-block { margin-top: var(--space-3); }
    .caps-history-title {
      font-size: var(--text-xs);
      color: var(--text-muted);
      margin-bottom: var(--space-1);
    }
    .caps-history-chart {
      border: 1px solid var(--border-default);
      background: var(--bg-base);
      border-radius: var(--radius-sm);
      padding: var(--space-2);
      min-height: 100px;
      font-size: var(--text-xs);
      color: var(--text-muted);
    }
    .caps-history-chart svg { width: 100%; height: 100px; display: block; }
    .caps-history-chart .axis { stroke: var(--border-default); stroke-width: 0.5; }
    .caps-history-chart .line { stroke: var(--accent-primary); stroke-width: 1.5; fill: none; }
    .caps-history-chart .point { fill: var(--accent-primary); }
    .caps-history-chart .label { fill: var(--text-muted); font-size: 9px; }

    .caps-inspector { margin-top: var(--space-3); }
    .caps-inspector-row {
      display: flex;
      gap: var(--space-2);
      align-items: end;
      flex-wrap: wrap;
    }
    .caps-inspector-row label { flex: 1 1 200px; }
    .caps-inspector-row input {
      width: 100%;
      padding: var(--space-1) var(--space-2);
      border: 1px solid var(--border-default);
      background: var(--bg-base);
      color: var(--text-primary);
      border-radius: var(--radius-sm);
      font-size: var(--text-xs);
      font-family: var(--font-mono);
    }
    .caps-inspect-result {
      margin-top: var(--space-2);
      font-size: var(--text-xs);
      font-family: var(--font-mono);
      padding: var(--space-2);
      background: var(--bg-base);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      min-height: 30px;
      color: var(--text-muted);
    }
    .caps-inspect-result.has-data { color: var(--text-primary); }

    .caps-refusals { margin-top: var(--space-3); }
    .caps-refusals summary {
      cursor: pointer;
      font-size: var(--text-sm);
      color: var(--text-muted);
      padding: var(--space-1) 0;
    }
    .caps-refusals-list {
      font-size: var(--text-xs);
      font-family: var(--font-mono);
      padding: var(--space-2);
      background: var(--bg-base);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      max-height: 240px;
      overflow-y: auto;
    }
    .caps-refusal-row {
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: var(--space-2);
      padding: var(--space-1) 0;
      border-bottom: 1px solid var(--border-default);
    }
    .caps-refusal-row:last-child { border-bottom: 0; }
    .caps-refusal-row .reason { color: var(--accent-error); }
    .caps-refusal-row .when { color: var(--text-muted); }

    /* ─── Safety subpage ────────────────────────────────────────── */
    .checkbox-row {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
    }
    .checkbox-row .hint {
      font-size: var(--text-xs);
      color: var(--text-muted);
      margin-left: 24px;
    }
    .strict-actions-list {
      list-style: none;
      padding: 0;
      margin: var(--space-2) 0;
    }
    .strict-actions-list li {
      padding: var(--space-1) var(--space-2);
      background: var(--bg-base);
      border-left: 3px solid var(--accent-warning);
      border-radius: var(--radius-sm);
      margin-bottom: var(--space-1);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }

    /* ─── Updates subpage rebuild ───────────────────────────────── */
    .restart-banner {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: var(--space-3);
      padding: var(--space-2) var(--space-3);
      background: var(--accent-warning-muted);
      color: var(--accent-warning);
      border: 1px solid var(--accent-warning);
      border-radius: var(--radius-sm);
      margin-bottom: var(--space-3);
    }
    .restart-banner-text strong { display: block; }
    .restart-banner-text span {
      font-size: var(--text-xs);
      opacity: 0.8;
    }
    .update-actions-block { margin-top: var(--space-2); }
    .update-status-badge {
      display: inline-block;
      padding: var(--space-1) var(--space-2);
      background: var(--bg-muted);
      border-radius: var(--radius-sm);
      font-size: var(--text-xs);
      margin-bottom: var(--space-2);
    }
    .update-status-badge[data-status="update_available"] {
      background: var(--accent-warning-muted);
      color: var(--accent-warning);
    }
    .update-status-badge[data-status="up_to_date"] {
      background: var(--accent-success-muted);
      color: var(--accent-success);
    }
    .update-action-row {
      display: flex;
      gap: var(--space-2);
      align-items: center;
      flex-wrap: wrap;
    }
    .checkbox-inline {
      display: inline-flex;
      gap: var(--space-1);
      align-items: center;
      font-size: var(--text-sm);
    }
    .update-result {
      margin-top: var(--space-2);
      padding: var(--space-2);
      font-size: var(--text-xs);
      font-family: var(--font-mono);
      background: var(--bg-base);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      max-height: 240px;
      overflow-y: auto;
      white-space: pre-wrap;
    }
    .update-result:empty { display: none; }
    .update-history-table {
      font-size: var(--text-xs);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      overflow: hidden;
    }
    .update-history-row {
      display: grid;
      grid-template-columns: 140px 90px 1fr 1fr 100px auto;
      gap: var(--space-2);
      padding: var(--space-1) var(--space-2);
      border-bottom: 1px solid var(--border-default);
      align-items: center;
    }
    .update-history-row:last-child { border-bottom: 0; }
    .update-history-row.header {
      background: var(--bg-muted);
      color: var(--text-muted);
      text-transform: uppercase;
      font-size: 10px;
      letter-spacing: 0.04em;
    }
    .update-history-row .kind { font-family: var(--font-mono); }
    .update-history-row .status-ok { color: var(--accent-success); }
    .update-history-row .status-fail { color: var(--accent-error); }
    .update-history-row .integrity-ok { color: var(--accent-success); }
    .update-history-row .integrity-bad { color: var(--accent-error); }
    .update-history-row .integrity-unknown { color: var(--text-muted); }

    /* ─── Run scoping bar ──────────────────────────────────────── */
    .run-scope-bar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: var(--space-3);
      padding: var(--space-2);
      background: var(--lab-panel-elevated);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      margin-bottom: var(--space-2);
    }
    .run-scope-status {
      display: flex;
      gap: var(--space-2);
      align-items: center;
      font-size: var(--text-sm);
    }
    .run-scope-indicator {
      font-family: var(--font-mono);
      padding: 2px var(--space-2);
      border-radius: var(--radius-sm);
      background: var(--bg-muted);
      color: var(--text-muted);
    }
    .run-scope-indicator.active {
      background: var(--accent-success-muted);
      color: var(--accent-success);
    }
    .run-scope-actions {
      display: flex;
      gap: var(--space-2);
      align-items: center;
    }
    .run-scope-actions input {
      padding: var(--space-1) var(--space-2);
      border: 1px solid var(--border-default);
      background: var(--bg-base);
      color: var(--text-primary);
      border-radius: var(--radius-sm);
      font-size: var(--text-xs);
      min-width: 220px;
    }
    .history-sidebar-section {
      margin-top: var(--space-2);
      padding-top: var(--space-2);
      border-top: 1px solid var(--border-default);
    }
    .history-recent-runs {
      font-size: var(--text-xs);
      color: var(--text-muted);
      max-height: 200px;
      overflow-y: auto;
    }
    .history-recent-run-row {
      padding: var(--space-1) var(--space-2);
      margin-bottom: 2px;
      background: var(--bg-base);
      border-radius: var(--radius-sm);
    }

    /* ─── History diff view ────────────────────────────────────── */
    .history-diff-view {
      margin-top: var(--space-3);
      padding: var(--space-3);
      background: var(--lab-panel-elevated);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
    }
    .history-diff-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: var(--space-2);
    }
    .history-diff-section {
      margin-top: var(--space-2);
      padding: var(--space-2);
      background: var(--bg-base);
      border-radius: var(--radius-sm);
    }
    .history-diff-section.added { border-left: 3px solid var(--accent-success); }
    .history-diff-section.removed { border-left: 3px solid var(--accent-error); }
    .history-diff-section.moved { border-left: 3px solid var(--accent-warning); }
    .history-diff-section h4 {
      margin: 0 0 var(--space-1) 0;
      font-size: var(--text-sm);
    }
    .history-diff-section ul {
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      margin: 0;
      padding-left: var(--space-3);
    }

    .history-version-card .diff-against {
      font-size: var(--text-xs);
      padding: var(--space-1);
      border: 1px solid var(--border-default);
      background: var(--bg-base);
      border-radius: var(--radius-sm);
    }

    /* ─── Media Pool History (was: Provenance) ─────────────────── */
    .mpc-toolbar {
      display: flex;
      flex-wrap: wrap;
      align-items: end;
      gap: var(--space-2);
      margin-top: var(--space-2);
      margin-bottom: var(--space-2);
    }
    .mpc-toolbar-field {
      display: flex;
      flex-direction: column;
      gap: 2px;
      font-size: var(--text-xs);
      color: var(--text-muted);
    }
    .mpc-toolbar-field select,
    .mpc-toolbar-field input {
      padding: var(--space-1) var(--space-2);
      border: 1px solid var(--border-default);
      background: var(--bg-base);
      color: var(--text-primary);
      border-radius: var(--radius-sm);
      font-size: var(--text-xs);
      min-width: 160px;
    }
    .mpc-toolbar-field input { font-family: var(--font-mono); min-width: 100px; }
    .mpc-toolbar-toggle {
      display: flex;
      align-items: center;
      gap: var(--space-1);
      font-size: var(--text-xs);
      color: var(--text-primary);
      padding-bottom: 4px;
    }
    .mpc-meta {
      flex: 1;
      text-align: right;
      font-size: var(--text-xs);
      color: var(--text-muted);
      padding-bottom: 4px;
    }
    .mpc-table {
      font-size: var(--text-xs);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      overflow: hidden;
      margin-top: var(--space-2);
    }
    .mpc-row {
      display: grid;
      grid-template-columns: 150px 170px 1fr 120px 110px;
      gap: var(--space-2);
      padding: var(--space-1) var(--space-2);
      border-bottom: 1px solid var(--border-default);
      align-items: center;
    }
    .mpc-row:last-child { border-bottom: 0; }
    .mpc-row:hover:not(.header):not(.group) { background: var(--bg-muted); }
    .mpc-row.header {
      background: var(--bg-muted);
      color: var(--text-muted);
      text-transform: uppercase;
      font-size: 10px;
      letter-spacing: 0.04em;
    }
    .mpc-row.group {
      grid-template-columns: 1fr auto;
      background: var(--bg-muted);
      font-weight: 600;
      color: var(--text-primary);
      font-size: var(--text-xs);
    }
    .mpc-row.group .group-count {
      font-size: 10px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .mpc-row .action-name {
      font-family: var(--font-mono);
      color: var(--accent-primary);
    }
    .mpc-row .target-cell {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }
    .mpc-row .target-cell .target-name {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .mpc-row .target-cell .target-id {
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--text-muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .mpc-row .clip-link {
      color: var(--accent-primary);
      cursor: pointer;
      text-decoration: none;
    }
    .mpc-row .clip-link:hover { text-decoration: underline; }
    .mpc-row .run-id {
      font-family: var(--font-mono);
      color: var(--text-muted);
      font-size: 10px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .review-search-results {
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
    }
    .review-search-card {
      display: grid;
      grid-template-columns: 160px 1fr auto;
      gap: var(--space-3);
      padding: var(--space-2);
      border: 1px solid var(--border-default);
      background: var(--lab-panel-elevated);
      border-radius: var(--radius-md);
      cursor: pointer;
      align-items: center;
      transition: border-color 150ms ease, background 150ms ease;
    }
    .review-search-card:hover {
      border-color: var(--accent-brand);
      background: var(--bg-hover);
    }
    .review-search-card .thumb {
      width: 160px;
      aspect-ratio: 16 / 9;
      background: var(--lab-workspace-letterbox);
      border-radius: var(--radius-sm);
      object-fit: cover;
      display: block;
    }
    .review-search-card .meta-row {
      display: flex;
      gap: var(--space-2);
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      align-items: center;
    }
    .review-search-card .meta-row .type {
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-weight: 600;
    }
    .review-search-card .tc {
      font-family: var(--font-mono);
      color: var(--accent-brand);
    }
    .review-search-card .clip-name {
      font-weight: 600;
      color: var(--text-primary);
    }
    .review-search-card .summary {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      display: -webkit-box;
      -webkit-line-clamp: 2;
      line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .review-search-card .summary mark.search-hit,
    mark.search-hit {
      background: var(--accent-warning-muted);
      color: var(--text-primary);
      padding: 0 3px;
      border-radius: 3px;
      font-weight: 600;
      box-shadow: inset 0 -1px 0 var(--accent-warning);
    }
    .review-rating-row {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      margin-top: var(--space-2);
      flex-wrap: wrap;
    }
    .review-stars {
      position: relative;
      display: inline-flex;
      gap: 4px;
      user-select: none;
      height: 26px;
    }
    .review-stars .star {
      position: relative;
      width: 26px;
      height: 26px;
      display: inline-block;
    }
    .review-stars .star .bg,
    .review-stars .star .fg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
    }
    .review-stars .star .bg path { fill: var(--text-tertiary); }
    .review-stars .star .fg {
      clip-path: inset(0 100% 0 0);
    }
    .review-stars .star .fg path { fill: var(--accent-brand); }
    .review-stars .hit {
      position: absolute;
      top: 0;
      width: 50%;
      height: 100%;
      cursor: pointer;
      z-index: 2;
    }
    .review-stars .hit.left { left: 0; }
    .review-stars .hit.right { left: 50%; }
    .review-rating-value {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      min-width: 32px;
    }
    .review-rating-clear {
      background: transparent;
      border: 0;
      color: var(--text-tertiary);
      cursor: pointer;
      padding: 2px 4px;
      min-height: 0;
      font-size: var(--ops-text-label);
    }
    .review-rating-clear:hover {
      color: var(--accent-error);
      background: transparent;
      border-color: transparent;
    }
    .review-notes-row {
      margin-top: var(--space-3);
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
    }
    .review-notes-row .label {
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
      font-weight: 700;
      text-transform: uppercase;
    }
    .review-notes-row textarea {
      background: var(--bg-elevated-1);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-sm);
      color: var(--text-primary);
      padding: 8px 10px;
      min-height: 60px;
      font: inherit;
      resize: vertical;
    }
    .review-notes-row .controls {
      display: flex;
      gap: var(--space-2);
      align-items: center;
    }
    .review-notes-row .saved {
      color: var(--accent-success);
      font-size: var(--ops-text-label);
      transition: opacity 600ms ease;
    }

    .tool-grid,
    .doc-grid {
      display: grid;
      gap: var(--space-3);
    }
    .doc-reader-layout {
      display: grid;
      grid-template-columns: minmax(220px, 0.28fr) minmax(0, 1fr);
      gap: var(--space-4);
      align-items: start;
    }
    #panel-docs:not(.doc-detail) .docs-detail-only { display: none; }
    #panel-docs:not(.doc-detail) .doc-reader-layout {
      grid-template-columns: minmax(240px, 360px) minmax(0, 1fr);
    }
    #panel-docs.doc-detail .docs-overview-summary,
    #panel-docs.doc-detail .docs-overview-only { display: none; }
    .docs-overview-summary {
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: var(--lab-panel-elevated);
      padding: var(--space-4);
      color: var(--text-secondary);
      min-height: 180px;
    }
    .doc-tools {
      display: grid;
      gap: var(--space-3);
      align-content: start;
    }
    .doc-tool-group {
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: var(--lab-panel-elevated);
      padding: var(--space-3);
      display: grid;
      gap: var(--space-2);
    }
    .doc-tool-title {
      color: var(--text-secondary);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .doc-filter {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      color: var(--text-secondary);
      font-size: var(--ops-text-label);
    }
    .doc-filter input {
      width: auto;
      min-height: auto;
      accent-color: var(--accent-brand);
    }
    .doc-section-nav {
      display: grid;
      gap: 4px;
    }
    .doc-section-nav.collapsed .doc-section-link.is-hidden { display: none; }
    .doc-section-toggle {
      min-height: 26px;
      padding: 0 var(--space-2);
      margin-top: var(--space-1);
      background: transparent;
      border: 1px dashed var(--border-default);
      color: var(--text-tertiary);
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.02em;
      cursor: pointer;
      border-radius: var(--radius-sm);
    }
    .doc-section-toggle:hover {
      color: var(--accent-brand-hover);
      border-color: var(--accent-brand);
    }
    .doc-section-link {
      min-height: 28px;
      justify-content: flex-start;
      text-align: left;
      padding: 0 var(--space-2);
      background: transparent;
      border-color: transparent;
      color: var(--text-secondary);
      font-size: 11px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .doc-section-link:hover {
      background: var(--bg-elevated-2);
      border-color: var(--border-default);
      color: var(--text-primary);
    }
    .doc-list {
      display: grid;
      gap: var(--space-2);
    }
    .doc-select {
      min-height: 38px;
      text-align: left;
      justify-content: flex-start;
      background: var(--lab-panel-elevated);
      border-color: var(--border-default);
      color: var(--text-primary);
    }
    .doc-select.active {
      background: var(--accent-brand-muted);
      border-color: color-mix(in srgb, var(--accent-brand) 45%, transparent);
      box-shadow: inset 3px 0 0 var(--accent-brand);
    }
    .doc-reader {
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: var(--lab-workspace-letterbox);
      min-height: 420px;
      max-height: calc(100vh - 230px);
      overflow: auto;
      padding: var(--space-5);
      color: var(--text-secondary);
    }
    .doc-reader h1,
    .doc-reader h2,
    .doc-reader h3 {
      color: var(--text-primary);
      text-transform: none;
      border-bottom: 1px solid var(--border-default);
      padding-bottom: var(--space-2);
      margin: var(--space-5) 0 var(--space-3);
      line-height: 1.25;
      scroll-margin-top: 26px;
    }
    .doc-reader h1:first-child,
    .doc-reader h2:first-child,
    .doc-reader h3:first-child { margin-top: 0; }
    .doc-reader h1 { font-size: 22px; }
    .doc-reader h2 { font-size: 17px; }
    .doc-reader h3 { font-size: 14px; }
    .doc-reader p {
      margin: 0 0 var(--space-3);
      max-width: 84ch;
    }
    .doc-reader pre {
      margin: var(--space-3) 0;
      padding: var(--space-3);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: #050505;
      overflow: auto;
      font: 12px/1.45 var(--font-mono);
      color: #d6d6d6;
    }
    .doc-badges {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      margin: 0 0 var(--space-3);
    }
    .doc-badges a,
    .doc-badges span {
      display: inline-flex;
      align-items: center;
      min-height: 20px;
    }
    .doc-badges img,
    .doc-image img {
      display: block;
      max-width: 100%;
      height: auto;
    }
    .doc-badges img {
      height: 20px;
      width: auto;
      border-radius: 3px;
    }
    .doc-image {
      margin: 0 0 var(--space-3);
    }
    .doc-reader code {
      font-family: var(--font-mono);
      color: var(--text-primary);
    }
    .doc-reader table {
      margin: var(--space-3) 0;
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      overflow: hidden;
      display: block;
      max-width: 100%;
      background: #050505;
    }
    .doc-reader th,
    .doc-reader td {
      padding: 7px 9px;
      border-bottom: 1px solid var(--border-subtle);
    }
    .doc-bullet {
      position: relative;
      margin: 0 0 var(--space-2) 18px;
      max-width: 84ch;
    }
    .doc-block.hidden { display: none; }
    .repo-inline {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      flex-wrap: wrap;
    }
    .repo-url {
      color: var(--accent-brand-hover);
      font-family: var(--font-mono);
      font-size: var(--ops-text-label);
      text-decoration: underline;
      text-decoration-color: color-mix(in srgb, var(--accent-brand) 50%, transparent);
      text-underline-offset: 3px;
    }
    .settings-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      column-gap: var(--space-5);
      row-gap: var(--space-5);
    }
    .settings-grid label {
      min-width: 0;
      align-content: start;
    }
    .settings-actions {
      margin-top: var(--space-4);
      display: flex;
      gap: var(--space-2);
      flex-wrap: wrap;
    }
    .settings-group {
      display: grid;
      gap: var(--space-4);
      margin-top: var(--space-5);
    }
    .settings-group:first-of-type { margin-top: 0; }
    .settings-subhead {
      color: var(--text-primary);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      border-bottom: 1px solid var(--border-default);
      padding-bottom: var(--space-2);
      margin-bottom: var(--space-2);
    }
    .settings-subtitle {
      margin: 0 0 var(--space-5);
    }
    .settings-textarea {
      min-height: 84px;
    }
    .marker-limit-control {
      display: grid;
      grid-template-columns: minmax(130px, 0.8fr) minmax(96px, 0.45fr);
      gap: var(--space-2);
      align-items: center;
    }
    .marker-limit-control input:disabled {
      opacity: 0.48;
      color: var(--text-tertiary);
    }
    .token-field {
      align-content: start;
    }
    .token-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: var(--space-2);
      padding: var(--space-2);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: var(--lab-workspace-letterbox);
      min-height: 84px;
    }
    .token-pill {
      display: inline-flex;
      align-items: center;
      width: 100%;
      min-height: 34px;
      padding: 0 var(--space-2);
      border-radius: var(--radius-sm);
      border-color: var(--border-default);
      background: var(--bg-elevated-1);
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 11px;
      white-space: nowrap;
      justify-content: center;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .token-pill.active {
      border-color: color-mix(in srgb, var(--accent-brand) 50%, transparent);
      background: var(--accent-brand-muted);
      color: var(--text-primary);
    }
    .token-pill:not(.active) {
      opacity: 0.68;
    }
    .token-pill:hover {
      border-color: var(--accent-brand-hover);
      background: var(--bg-hover);
      color: var(--text-primary);
    }
    .token-count {
      color: var(--text-tertiary);
      font: 11px/1.4 var(--font-mono);
    }
    .settings-status {
      color: var(--text-tertiary);
      font: 11px/1.4 var(--font-mono);
      margin-top: var(--space-3);
      min-height: 16px;
    }
    .doc-bullet::before {
      content: "";
      position: absolute;
      left: -13px;
      top: 0.72em;
      width: 4px;
      height: 4px;
      border-radius: 50%;
      background: var(--accent-brand);
    }
    .doc-source {
      margin-top: var(--space-3);
      color: var(--text-tertiary);
      font: 11px/1.4 var(--font-mono);
      overflow-wrap: anywhere;
    }
    .tool-row,
    .doc-link {
      border: 1px solid var(--border-default);
      background: var(--lab-panel-elevated);
      border-radius: var(--radius-md);
      padding: var(--space-3);
      display: flex;
      justify-content: space-between;
      gap: var(--space-3);
      align-items: center;
      min-width: 0;
    }
    .doc-link {
      color: var(--text-primary);
      transition: background 150ms ease, border-color 150ms ease, color 150ms ease;
    }
    .doc-link:hover {
      background: var(--bg-elevated-2);
      border-color: var(--border-strong);
      color: var(--accent-brand-hover);
    }
    .tool-row strong,
    .doc-link strong {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .tool-row .badge {
      max-width: min(58vw, 680px);
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .helper-copy {
      color: var(--text-secondary);
      margin-bottom: var(--space-4);
      max-width: 760px;
    }
    .media-summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: var(--space-2);
      margin-bottom: var(--space-3);
    }
    .media-stat {
      border: 1px solid var(--border-default);
      background: var(--bg-elevated-1);
      border-radius: var(--radius-md);
      padding: var(--space-2);
      min-width: 0;
    }
    .media-stat b {
      display: block;
      color: var(--text-primary);
      font-size: 18px;
      line-height: 1.1;
    }
    .media-stat span {
      color: var(--text-secondary);
      font-size: 11px;
    }
    .media-table-wrap {
      max-height: 280px;
      overflow: auto;
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
      background: var(--lab-workspace-letterbox);
    }
    .media-table-wrap table {
      min-width: 760px;
    }
    .filter-row {
      display: grid;
      grid-template-columns: minmax(180px, 1.6fr) minmax(140px, 1fr) minmax(120px, 0.9fr) minmax(120px, 0.8fr) minmax(140px, 0.9fr) minmax(110px, 0.6fr);
      gap: var(--space-2);
      margin-bottom: var(--space-3);
      align-items: end;
    }
    .filter-row input,
    .filter-row select {
      min-height: 34px;
      font-size: var(--ops-text-label);
    }
    .media-action-bar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-3);
      margin-top: var(--space-4);
      padding: var(--space-3) var(--space-4);
      background: var(--lab-panel-elevated);
      border: 1px solid var(--border-default);
      border-radius: var(--radius-md);
    }
    .media-action-status {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      min-width: 0;
    }
    .media-action-hint {
      color: var(--text-secondary);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .media-action-bar .controls {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
    }
    .poll-status {
      color: var(--text-tertiary);
      font-family: var(--font-mono);
      font-size: 11px;
      margin-top: var(--space-2);
    }
    .status-cell {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      white-space: nowrap;
    }
    .status-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--text-tertiary);
      box-shadow: 0 0 0 3px rgba(255,255,255,0.04);
    }
    .status-dot.online,
    .status-dot.analyzable,
    .status-dot.analyzed,
    .status-dot.succeeded,
    .status-dot.skipped {
      background: var(--accent-success);
    }
    .status-dot.missing_file,
    .status-dot.offline,
    .status-dot.failed {
      background: var(--accent-error);
    }
    .status-dot.no_path,
    .status-dot.not_analyzable,
    .status-dot.pending,
    .status-dot.queued {
      background: var(--accent-warning);
    }
    .status-dot.running {
      background: var(--accent-brand-hover);
    }
    .media-path {
      color: var(--text-secondary);
      font-family: var(--font-mono);
      font-size: 11px;
    }
    .clip-select {
      width: auto;
      min-height: auto;
      accent-color: var(--accent-brand);
    }
    .copy-status {
      color: var(--accent-success);
      font: 12px/1.4 var(--font-mono);
      min-height: 18px;
    }
    .lab-footer {
      height: 52px;
      min-height: 52px;
      background: var(--bg-base);
      border-top: 1px solid rgba(255, 255, 255, 0.06);
      color: var(--text-tertiary);
      font-size: var(--ops-text-label);
      display: grid;
      grid-template-columns: minmax(260px, 1fr) minmax(420px, 1.35fr) minmax(260px, 1fr);
      align-items: center;
      gap: var(--space-5);
      padding: 0 var(--space-4);
      position: fixed;
      inset: auto 0 0 0;
      z-index: 1002;
    }
    .footer-credit,
    .footer-links,
    .footer-notice {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .footer-credit,
    .footer-links { white-space: nowrap; }
    .footer-credit {
      justify-self: start;
    }
    .footer-notice {
      color: var(--text-tertiary);
      text-align: center;
      font-weight: 400;
      font-size: 10px;
      line-height: 1.2;
      justify-self: center;
      max-width: 720px;
    }
    .footer-links {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: var(--space-3);
      text-align: right;
      justify-self: end;
    }
    .footer-open-source {
      color: var(--text-secondary);
      font-size: 10px;
      line-height: 1.25;
      font-weight: 500;
      white-space: nowrap;
    }
    footer strong { color: var(--text-secondary); font-weight: 600; }
    ::selection {
      background: var(--accent-brand-muted);
      color: var(--text-primary);
    }
    @media (max-width: 980px) {
      main, .split, .panel.control-grid { grid-template-columns: 1fr; }
      .lab-navbar { padding: 0 var(--space-3); }
      .nav-breadcrumb { display: none; }
      .control-tabs {
        order: 3;
        flex: 1 0 100%;
        overflow-x: auto;
        justify-content: flex-start;
        padding-bottom: 2px;
      }
      .control-tabs select { max-width: 150px; min-width: 110px; }
      .lab-navbar {
        height: 88px;
        flex-wrap: wrap;
        align-content: center;
      }
      .nav-links { margin-left: auto; }
      .wordmark { font-size: 18px; }
      main { padding: calc(88px + var(--space-3)) var(--space-3) calc(112px + var(--space-3)); }
      .panel.control-grid > section,
      .panel.control-grid > section.span-12,
      .panel.control-grid > section.span-8,
      .panel.control-grid > section.span-4,
      .panel.control-grid > .span-12,
      .panel.control-grid > .span-8,
      .panel.control-grid > .span-4,
      .subpage-grid > section,
      .subpage-grid > section.span-12,
      .subpage-grid > section.span-8,
      .subpage-grid > section.span-4 { grid-column: auto; }
      .overview-grid { grid-template-columns: 1fr 1fr; }
      .metrics { grid-template-columns: 1fr 1fr; }
      .media-summary { grid-template-columns: 1fr 1fr; }
      .section-top { display: grid; }
      .section-meta { text-align: left; }
      .filter-row { grid-template-columns: 1fr; }
      .lab-footer {
        height: 112px;
        grid-template-columns: 1fr;
        justify-items: center;
        gap: 2px;
        padding: var(--space-2) var(--space-3);
        text-align: center;
      }
      .footer-links {
        justify-content: center;
        text-align: center;
      }
      .footer-open-source {
        white-space: normal;
      }
      .subpage-grid { grid-template-columns: 1fr; }
      .doc-reader-layout { grid-template-columns: 1fr; }
      .doc-reader { max-height: none; }
      .settings-grid { grid-template-columns: 1fr; }
    }
    @media (max-width: 620px) {
      .overview-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body data-theme="studio" data-tier="operations">
  <header class="lab-navbar">
    <div class="nav-left">
      <h1><button class="wordmark home-wordmark" data-panel-target="overview" aria-label="Open Overview"><span>DaVinci Resolve</span><span class="wordmark-accent">MCP</span></button></h1>
      <div class="nav-breadcrumb" aria-label="Breadcrumb">
        <span class="nav-breadcrumb-sep nav-breadcrumb-sep--root" aria-hidden="true">/</span>
        <span class="breadcrumb-trail" id="breadcrumbTrail">
          <span class="nav-breadcrumb-current">Overview</span>
        </span>
      </div>
    </div>
    <nav class="control-tabs" aria-label="Control panel sections">
      <button class="control-tab active" data-panel-target="overview">Overview</button>
      <div class="control-nav-item">
        <button class="control-tab has-menu" data-panel-target="analysis">Media <span class="tab-chevron" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"></path></svg></span></button>
        <div class="nav-dropdown" role="menu" aria-label="Analysis pages">
          <button class="nav-dropdown-item" data-panel-target="analysis" data-subpage-target="media" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="m7 15 3-3 2 2 4-5 1 2"></path></svg></span>Inventory</button>
          <button class="nav-dropdown-item" data-panel-target="analysis" data-subpage-target="review" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="14" rx="2"></rect><circle cx="9" cy="10" r="2"></circle><path d="m21 17-5-5-9 9"></path></svg></span>Review</button>
          <button class="nav-dropdown-item" id="navHistoryItem" data-panel-target="analysis" data-subpage-target="review" data-review-view="history" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path><path d="M3 3v5h5"></path><path d="M12 7v5l4 2"></path></svg></span>History</button>
          <button class="nav-dropdown-item" id="navPlansItem" data-panel-target="analysis" data-subpage-target="review" data-review-view="plans" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="8" y="2" width="8" height="4" rx="1"></rect><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path><path d="M9 12h6"></path><path d="M9 16h6"></path></svg></span>Edit Plans</button>
        </div>
      </div>
      <button class="control-tab" data-panel-target="aiconsole">AI Console</button>
      <div class="control-nav-item">
        <button class="control-tab has-menu" data-panel-target="diagnostics">Setup <span class="tab-chevron" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"></path></svg></span></button>
        <div class="nav-dropdown" role="menu" aria-label="Diagnostic pages">
          <button class="nav-dropdown-item" data-panel-target="diagnostics" data-subpage-target="resolve" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4"></path><path d="M12 18v4"></path><path d="m4.93 4.93 2.83 2.83"></path><path d="m16.24 16.24 2.83 2.83"></path><path d="M2 12h4"></path><path d="M18 12h4"></path><path d="m4.93 19.07 2.83-2.83"></path><path d="m16.24 7.76 2.83-2.83"></path></svg></span>Resolve</button>
          <button class="nav-dropdown-item" data-panel-target="diagnostics" data-subpage-target="mcp" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7v10l8 5 8-5V7l-8-5z"></path><path d="m4 7 8 5 8-5"></path><path d="M12 12v10"></path></svg></span>MCP</button>
          <button class="nav-dropdown-item" data-panel-target="diagnostics" data-subpage-target="storage" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5"></path><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"></path></svg></span>Storage</button>
          <button class="nav-dropdown-item" data-panel-target="diagnostics" data-subpage-target="tools" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l2.1-2.1a6 6 0 0 1-7.6 7.6l-4 4a2.1 2.1 0 0 1-3-3l4-4a6 6 0 0 1 7.6-7.6z"></path></svg></span>Tools</button>
          <button class="nav-dropdown-item" data-panel-target="diagnostics" data-subpage-target="media-pool-history" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12h18"></path><path d="M3 6h18"></path><path d="M3 18h18"></path></svg></span>Media Pool History</button>
        </div>
      </div>
      <div class="control-nav-item">
        <button class="control-tab has-menu" data-panel-target="docs">Docs <span class="tab-chevron" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"></path></svg></span></button>
        <div class="nav-dropdown" role="menu" aria-label="Documentation pages">
          <button class="nav-dropdown-item" data-panel-target="docs" data-subpage-target="readme" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5z"></path></svg></span>README</button>
          <button class="nav-dropdown-item" data-panel-target="docs" data-subpage-target="release-notes" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3"></path><circle cx="12" cy="12" r="9"></circle></svg></span>Release Notes</button>
          <button class="nav-dropdown-item" data-panel-target="docs" data-subpage-target="analysis-guide" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18h6"></path><path d="M10 22h4"></path><path d="M12 2a7 7 0 0 0-4 12c.65.55 1 1.35 1 2h6c0-.65.35-1.45 1-2A7 7 0 0 0 12 2z"></path></svg></span>Media Analysis Guide</button>
          <button class="nav-dropdown-item" data-panel-target="docs" data-subpage-target="agent-skill" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8V4H8"></path><rect x="4" y="12" width="16" height="8" rx="2"></rect><path d="M2 14h2"></path><path d="M20 14h2"></path><path d="M15 13v2"></path><path d="M9 13v2"></path></svg></span>Agent Skill</button>
        </div>
      </div>
      <div class="control-nav-item">
        <button class="control-tab has-menu" data-panel-target="preferences">Preferences <span class="tab-chevron" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"></path></svg></span></button>
        <div class="nav-dropdown" role="menu" aria-label="Preference pages">
          <button class="nav-dropdown-item" data-panel-target="preferences" data-subpage-target="analysis" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"></path><path d="m19 9-5 5-4-4-3 3"></path></svg></span>Analysis</button>
          <button class="nav-dropdown-item" data-panel-target="preferences" data-subpage-target="caps" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"></circle><path d="M12 3v9l6 3"></path></svg></span>Caps + Safety</button>
          <button class="nav-dropdown-item" data-panel-target="preferences" data-subpage-target="metadata" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 7h-9"></path><path d="M14 17H5"></path><circle cx="17" cy="17" r="3"></circle><circle cx="7" cy="7" r="3"></circle></svg></span>Metadata And Markers</button>
          <button class="nav-dropdown-item" data-panel-target="preferences" data-subpage-target="paths" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7h5l2 3h11v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path></svg></span>Paths And Workflow</button>
          <button class="nav-dropdown-item" data-panel-target="preferences" data-subpage-target="updates" role="menuitem"><span class="nav-dropdown-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-2.64-6.36"></path><path d="M21 3v6h-6"></path></svg></span>MCP Updates</button>
        </div>
      </div>
      <div class="project-context">
        <select id="projectContextSelect" aria-label="Project context">
          <option value="">Loading project contexts</option>
        </select>
      </div>
    </nav>
    <div class="nav-links">
      <button id="versionBadge" class="version-badge" type="button" aria-label="MCP version and updates" title="MCP version">
        <span class="version-label">MCP</span>
        <span class="version-number" id="versionNumber">…</span>
        <span class="version-dot" id="versionDot" aria-hidden="true"></span>
      </button>
      <a class="nav-link github-icon-link" href="https://github.com/samuelgursky/davinci-resolve-mcp" target="_blank" rel="noreferrer" aria-label="GitHub Repository" title="GitHub Repository">
        <svg class="github-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.4 5.4 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"></path>
          <path d="M9 18c-4.51 2-5-2-7-2"></path>
        </svg>
        <span class="sr-only">GitHub Repository</span>
      </a>
    </div>
  </header>

  <main id="panel-overview" class="panel control-grid active">
    <section class="span-12">
      <div class="section-top">
        <div>
          <h2>Overview</h2>
          <div class="section-meta" id="overviewUpdated">Waiting for first refresh</div>
        </div>
        <div class="controls">
          <button id="overviewRefresh">Refresh All</button>
          <button class="secondary" data-panel-target="analysis" data-subpage-target="media">Open Analysis</button>
        </div>
      </div>
      <div class="overview-grid">
        <div class="metric-card">
          <span>Active Project</span>
          <b id="overviewProject">Checking</b>
          <small id="overviewResolveStatus">Resolve connection pending</small>
        </div>
        <div class="metric-card">
          <span>Source Clips</span>
          <b id="overviewClipCount">0</b>
          <small id="overviewClipStatus">Source clips only</small>
        </div>
        <div class="metric-card">
          <span>Sequences</span>
          <b id="overviewSequenceCount">0</b>
          <small id="overviewSequenceStatus">Read-only context</small>
        </div>
        <div class="metric-card">
          <span>Media Status</span>
          <b id="overviewMediaStatus">Checking</b>
          <small id="overviewMediaStatusDetail">Inventory pending</small>
        </div>
      </div>
      <div class="info-list" id="overviewStatusList" style="margin-top:16px">
        <div class="empty">Waiting for Resolve media inventory.</div>
      </div>
    </section>
  </main>

  <main id="panel-projects" class="panel control-grid">
    <section class="span-12">
      <div class="section-top">
        <div>
          <h2>Resolve Projects</h2>
          <div class="section-meta" id="projectsUpdated">Open the full database view to inspect projects outside the current Project Manager folder.</div>
        </div>
        <div class="controls">
          <button id="projectsRefresh">Refresh Projects</button>
        </div>
      </div>
      <div class="overview-grid">
        <div class="metric-card">
          <span>Current Project</span>
          <b id="projectsCurrentProject">Checking</b>
          <small id="projectsCurrentFolder">Current folder pending</small>
        </div>
        <div class="metric-card">
          <span>Open Projects</span>
          <b id="projectsOpenCount">0</b>
          <small>Shown in the project dropdown</small>
        </div>
        <div class="metric-card">
          <span>Database Projects</span>
          <b id="projectsAllCount">0</b>
          <small id="projectsDatabaseName">Database pending</small>
        </div>
        <div class="metric-card">
          <span>Analysis Contexts</span>
          <b id="projectsContextCount">0</b>
          <small>Existing local reports and indexes</small>
        </div>
      </div>
    </section>

    <section class="span-12">
      <div class="section-top">
        <div>
          <h2>All Database Projects</h2>
          <div class="section-copy">This view walks Resolve Project Manager folders read-only, then uses confirmation before loading a different project in Resolve.</div>
        </div>
        <label class="project-filter">
          Filter
          <input id="projectFilterText" type="search" placeholder="project or folder">
        </label>
      </div>
      <div id="allProjectsBody" class="empty">Open Projects to scan the current Resolve database.</div>
    </section>
  </main>

  <main id="panel-analysis" class="panel control-grid">
    <section class="span-12 subpage active" data-subpage-scope="analysis" data-subpage="media">
        <div class="section-top">
          <div>
            <h2>Inventory</h2>
            <p class="section-copy">Resolve media is inventoried read-only and filtered to source clips so timelines, compounds, titles, and generated items stay out of analysis queues.</p>
            <div class="section-meta" id="resolveProject">Resolve connection pending</div>
            <div class="copy-status" id="copyPromptStatus"></div>
          </div>
          <div class="controls">
            <button class="secondary" id="refreshMediaBtn">Refresh Clips</button>
          </div>
        </div>
        <div class="filter-row">
          <label>Find <input id="mediaFilterText" placeholder="clip, bin, path, or type"></label>
          <label>Bin
            <select id="mediaBinFilter">
              <option value="">All bins</option>
            </select>
          </label>
          <label>Media type
            <select id="mediaTypeFilter">
              <option value="">All types</option>
            </select>
          </label>
          <label>Clip status
            <select id="mediaStatusFilter">
              <option value="clips" selected>clips</option>
              <option value="analyzable">analysis ready</option>
              <option value="online">online</option>
              <option value="missing">missing/offline</option>
            </select>
          </label>
          <label>Analysis status
            <select id="analysisStatusFilter">
              <option value="all">all</option>
              <option value="not_analyzed">not analyzed</option>
              <option value="analyzed">analyzed</option>
              <option value="active">queued/running</option>
              <option value="failed">failed</option>
            </select>
          </label>
          <label>Poll
            <select id="mediaPollInterval">
              <option value="0">off</option>
              <option value="5000">5s</option>
              <option value="15000" selected>15s</option>
              <option value="30000">30s</option>
              <option value="60000">60s</option>
            </select>
          </label>
        </div>
        <label class="checkbox"><input id="autoPollMedia" type="checkbox" checked> Auto refresh Resolve clips</label>
        <div class="poll-status" id="mediaPollStatus">waiting for first refresh</div>
        <div id="resolveMediaBody" class="empty">Checking Resolve media pool.</div>
        <div class="media-action-bar">
          <div class="media-action-status">
            <span class="status-pill pill-info" id="mediaSelectedCount">0 selected</span>
            <span class="media-action-hint" id="mediaSelectedHint">No analyzable clips chosen yet.</span>
          </div>
          <div class="controls">
            <button class="secondary" id="selectReadyMediaBtn" disabled>Select Ready Clips</button>
            <div class="action-menu" id="mediaAnalyzeMenu">
              <button id="mediaAnalyzeMenuBtn" class="action-menu-trigger" data-action-menu-trigger="mediaAnalyzeMenu" aria-haspopup="menu" aria-expanded="false" disabled>Analyze <svg class="action-menu-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg></button>
              <div class="action-dropdown" role="menu" aria-label="Analyze actions">
                <button id="copyPromptFromMediaBtn" type="button" role="menuitem" disabled>Copy Prompt</button>
                <div id="mediaAnalyzeClientItems" data-client-menu="analyze">
                  <div class="action-dropdown-empty">Scanning installed clients…</div>
                </div>
              </div>
            </div>
          </div>
        </div>
    </section>

    <section class="span-12 subpage" data-subpage-scope="analysis" data-subpage="review">
      <div class="section-top">
        <div>
          <h2>Review</h2>
          <div class="section-meta" id="reviewMeta">Bin overview · click a clip to drill into shot detail.</div>
        </div>
        <div class="controls" id="reviewControls">
          <button class="secondary" id="reviewRefreshBtn">Refresh</button>
          <button class="secondary" id="reviewHistoryBtn" title="Timeline edit history">History</button>
          <button class="secondary" id="reviewBackBtn" style="display:none">← Back</button>
        </div>
      </div>
      <div id="reviewBinView">
        <div id="reviewReadinessCard" class="readiness-card" hidden>
          <div class="readiness-card-header">
            <span class="readiness-title">Project readiness</span>
            <span id="readinessEvidenceBase" class="readiness-evidence"></span>
          </div>
          <div id="readinessSummaryRow" class="readiness-summary-row"></div>
          <div id="readinessDetails" class="readiness-details"></div>
        </div>
        <div class="review-bin-filters">
          <input id="reviewSearchInput" type="search" placeholder="Search clips, summaries, tags, transcripts…" autocomplete="off">
          <label id="reviewSemanticToggle" class="review-semantic-toggle" style="display:none" title="Search by meaning using local text embeddings instead of exact words.">
            <input id="reviewSemanticCheckbox" type="checkbox"> Semantic
          </label>
          <select id="reviewBinFilter" aria-label="Filter by bin">
            <option value="">All bins</option>
          </select>
          <div class="review-view-toggle" role="tablist" aria-label="View mode">
            <button id="reviewViewGridBtn" class="active" data-view-mode="grid" type="button">Grid</button>
            <button id="reviewViewListBtn" data-view-mode="list" type="button">List</button>
          </div>
        </div>
        <div id="reviewBinSummary" class="review-bin-summary">Loading analyzed clips…</div>
        <div id="reviewEntitiesCard" class="review-entities" style="display:none"></div>
        <div id="reviewBinGrid" class="review-grid"></div>
        <div id="reviewSearchResults" class="review-search-results" style="display:none"></div>
      </div>
      <div id="reviewClipView" style="display:none">
        <div id="reviewClipHeader" class="review-clip-header"></div>
        <div id="reviewClipRating"></div>
        <div id="reviewClipSummary" class="review-clip-summary"></div>
        <div id="reviewClipTags" class="review-clip-tags"></div>
        <div id="reviewClipNotes"></div>
        <div class="review-shot-strip-wrap">
          <div class="review-shot-strip-label">Shots</div>
          <div id="reviewShotStrip" class="review-shot-strip"></div>
        </div>
        <div id="reviewClipAnalysisBlocks" class="review-analysis-blocks"></div>
        <div id="reviewClipCrossShot" class="review-cross-shot"></div>
      </div>
      <div id="reviewShotView" style="display:none">
        <div id="reviewShotHeader" class="review-shot-header"></div>
        <div id="reviewShotRating"></div>
        <div id="reviewShotNotes"></div>
        <div class="review-shot-grid">
          <div class="review-shot-fields" id="reviewShotFields"></div>
          <div class="review-shot-frames">
            <div class="review-shot-frames-label">Frames</div>
            <div id="reviewShotFrames" class="review-shot-frame-grid"></div>
          </div>
        </div>
      </div>
      <div id="reviewTranscriptView" style="display:none">
        <div id="reviewTranscriptHeader" class="review-shot-header"></div>
        <div id="reviewTranscriptMeta" class="section-meta"></div>
        <div class="review-transcript-search-row">
          <input id="reviewTranscriptFilter" type="search" placeholder="Filter transcript segments…" autocomplete="off">
        </div>
        <div id="reviewTranscriptBody" class="review-transcript-body">
          <div class="empty">Loading transcript…</div>
        </div>
      </div>
      <div id="reviewCombinedView" style="display:none">
        <div id="reviewCombinedHeader" class="review-shot-header"></div>
        <div id="reviewCombinedMeta" class="section-meta"></div>
        <div id="reviewCombinedBody">
          <div class="empty">Loading combined review…</div>
        </div>
      </div>
      <div id="reviewHistoryView" style="display:none">
        <div id="runScopeBar" class="run-scope-bar">
          <div class="run-scope-status">
            <span class="run-scope-label">Active run:</span>
            <span id="runScopeIndicator" class="run-scope-indicator none">none</span>
          </div>
          <div class="run-scope-actions">
            <input id="runScopeLabel" type="text" placeholder="run label (e.g. 'rough cut tighten')">
            <button id="runBeginBtn" type="button">Begin run</button>
            <button id="runEndBtn" class="secondary" type="button">End run</button>
          </div>
        </div>
        <div class="history-layout">
          <aside class="history-sidebar">
            <div class="history-sidebar-header">
              <strong>Timelines</strong>
              <button id="historyRefreshBtn" class="secondary" type="button">Refresh</button>
            </div>
            <div id="historyTimelineList" class="history-timeline-list">
              <div class="empty">Loading…</div>
            </div>
            <div class="history-archive-now">
              <button id="historyArchiveCurrentBtn" type="button">Archive current timeline</button>
              <input id="historyArchiveReason" type="text" placeholder="reason (optional)">
            </div>
            <div class="history-sidebar-section">
              <strong>Recent runs</strong>
              <div id="historyRecentRuns" class="history-recent-runs">loading…</div>
            </div>
          </aside>
          <section class="history-detail">
            <div id="historyDetailHeader" class="history-detail-header">
              <span class="empty">Select a timeline.</span>
            </div>
            <div id="historyDetailBody" class="history-detail-body"></div>
            <div id="historyDiffView" class="history-diff-view" hidden>
              <div class="history-diff-header">
                <strong>Structural diff</strong>
                <button id="historyDiffCloseBtn" class="secondary" type="button">Close</button>
              </div>
              <div id="historyDiffBody"></div>
            </div>
          </section>
        </div>
      </div>
      <div id="reviewPlansView" style="display:none">
        <div class="plans-toolbar">
          <div>
            <strong>Edit plans</strong>
            <span class="section-meta">Dry-run plans saved by the edit engine — review here, execute from chat.</span>
          </div>
          <button id="plansRefreshBtn" class="secondary" type="button">Refresh</button>
        </div>
        <div id="plansListBody" class="plans-list"><div class="empty">Loading…</div></div>
      </div>
      <div id="reviewPlanView" style="display:none">
        <div id="planDetailHeader" class="plan-detail-header"></div>
        <div id="planDetailBody" class="plan-detail-body"></div>
      </div>
    </section>
  </main>

  <main id="panel-aiconsole" class="panel control-grid">
    <section class="span-12">
      <div class="section-top">
        <div>
          <h2>Resolve 21 AI Console</h2>
          <p class="section-sub">Run Resolve's local AI operations on the current Media Pool folder or a specific clip. These run on Resolve's GPU/AI engine — the analysis and slate ops are safe and reversible; <strong>motion-deblur</strong> and <strong>speech generation</strong> create new media files and ask for confirmation first. Source media is never modified. Every run is recorded in the <em>Resolve 21 AI ops</em> ledger (Preferences → Caps + Safety).</p>
        </div>
      </div>

      <div id="aiConsoleCaps" class="caps-section" style="margin-top:12px;">
        <div class="caps-section-hint">Checking which AI methods this Resolve build exposes…</div>
      </div>

      <div class="caps-section" style="margin-top:12px;">
        <div class="caps-section-head"><div class="caps-section-title">Governance</div>
          <div class="caps-section-hint">Per-session limits for the two media-creating ops (deblur, speech). In <strong>Advisory</strong> mode you're warned in the confirm dialog but never blocked; in <strong>Enforce</strong> mode an over-tier run is refused until you raise the tier, relax the mode, or consciously override. Pick the tier that matches the job.</div></div>
        <div id="aiGovTiers" class="caps-preset-cards" role="radiogroup" aria-label="AI governance tier"></div>
        <div class="review-view-toggle" id="aiGovMode" role="radiogroup" aria-label="Governance mode" style="margin-top:10px;">
          <button type="button" data-gov-mode="advisory">Advisory</button>
          <button type="button" data-gov-mode="enforce">Enforce</button>
        </div>
        <div id="aiGovUsage" class="caps-usage-gauges" style="margin-top:10px;"></div>
      </div>

      <div class="caps-section" style="margin-top:12px;">
        <div class="caps-section-head"><div class="caps-section-title">Target</div>
          <div class="caps-section-hint">Folder ops run on the current Media Pool folder in Resolve. Choose <em>Specific clip</em> and paste a clip id (from <code>media_pool.get_clips</code>) to target one clip.</div></div>
        <div class="settings-grid">
          <label class="checkbox-row"><input type="radio" name="aiTarget" value="folder" checked><span>Current folder</span></label>
          <label class="checkbox-row"><input type="radio" name="aiTarget" value="clip"><span>Specific clip</span></label>
          <label>Clip id <input id="aiClipId" type="text" placeholder="(clip UniqueId)"></label>
        </div>
      </div>

      <div class="caps-section" style="margin-top:12px;">
        <div class="caps-section-head"><div class="caps-section-title">Analysis</div>
          <div class="caps-section-hint">Safe, reversible. IntelliSearch and Slate require their AI Extras (Extras Download Manager).</div></div>
        <div class="settings-grid">
          <div class="ai-op-row"><button class="ai-op-btn" data-ai-op="perform_audio_classification">Classify audio</button>
            <button class="ai-op-btn ghost" data-ai-op="clear_audio_classification">Clear classification</button></div>
          <div class="ai-op-row">
            <button class="ai-op-btn" data-ai-op="analyze_for_intellisearch">IntelliSearch</button>
            <label class="checkbox-row"><input id="aiIdentifyFaces" type="checkbox"><span>Identify faces</span></label>
            <label class="checkbox-row"><input id="aiBetterMode" type="checkbox"><span>Better mode</span></label>
          </div>
          <div class="ai-op-row">
            <button class="ai-op-btn" data-ai-op="analyze_for_slate">Analyze for slate</button>
            <label>Marker <select id="aiSlateColor"></select></label>
          </div>
          <div class="ai-op-row">
            <button class="ai-op-btn" data-ai-op="transcribe_audio">Transcribe</button>
            <label class="checkbox-row"><input id="aiSpeakerDetection" type="checkbox"><span>Speaker detection</span></label>
            <button class="ai-op-btn ghost" data-ai-op="clear_transcription">Clear transcription</button>
          </div>
        </div>
      </div>

      <div class="caps-section" style="margin-top:12px;">
        <div class="caps-section-head"><div class="caps-section-title">Motion deblur</div>
          <div class="caps-section-hint">Renders new deblurred media. Creates files; asks for confirmation. Leave fields blank for Resolve defaults.</div></div>
        <div class="settings-grid">
          <label>Format <input id="aiDeblurFormat" type="text" placeholder="mov"></label>
          <label>Codec <input id="aiDeblurCodec" type="text" placeholder="ProRes422"></label>
          <label class="checkbox-row"><input id="aiDeblurExtreme" type="checkbox"><span>Extreme mode</span></label>
          <label class="checkbox-row"><input id="aiDeblurMarkInOut" type="checkbox"><span>Use mark in/out</span></label>
          <label class="checkbox-row"><input id="aiDeblurSourceRes" type="checkbox"><span>Render at source res</span></label>
          <div class="ai-op-row"><button class="ai-op-btn danger" data-ai-op="remove_motion_blur">Remove motion blur</button></div>
        </div>
      </div>

      <div class="caps-section" style="margin-top:12px;">
        <div class="caps-section-head"><div class="caps-section-title">Speech generator</div>
          <div class="caps-section-hint">AI text-to-speech. Requires the AI Speech Generator Extra. Creates a new audio item; asks for confirmation.</div></div>
        <div class="settings-grid">
          <label style="grid-column:1/-1;">Text <textarea id="aiSpeechText" rows="2" placeholder="Text to synthesize"></textarea></label>
          <label>Voice model <input id="aiSpeechVoice" type="text" placeholder="Female 1"></label>
          <label>Speed <input id="aiSpeechSpeed" type="number" placeholder="(default)"></label>
          <label>Pitch <input id="aiSpeechPitch" type="number" placeholder="(default)"></label>
          <label>Variation <input id="aiSpeechVariation" type="number" placeholder="(default)"></label>
          <label class="checkbox-row"><input id="aiSpeechAddTimeline" type="checkbox"><span>Add to timeline</span></label>
          <label>Timecode <input id="aiSpeechTimecode" type="text" placeholder="01:00:00:00"></label>
          <label>Audio track <input id="aiSpeechTrack" type="number" placeholder="(default)"></label>
          <div class="ai-op-row"><button class="ai-op-btn danger" data-ai-op="generate_speech">Generate speech</button></div>
        </div>
      </div>

      <div class="caps-section" style="margin-top:12px;">
        <div class="caps-section-head"><div class="caps-section-title">Session</div>
          <div class="caps-section-hint">Quiet Resolve's background tasks for this session before heavy work. Resets on restart.</div></div>
        <div class="ai-op-row"><button class="ai-op-btn ghost" data-ai-op="disable_background_tasks">Disable background tasks</button></div>
      </div>

      <div class="caps-section" style="margin-top:12px;">
        <div class="caps-section-head"><div class="caps-section-title">Result</div></div>
        <div id="aiConsoleResult" class="ai-console-result caps-section-hint">No op run yet.</div>
      </div>
    </section>
  </main>

  <main id="panel-diagnostics" class="panel control-grid">
    <section class="span-12 subpage active" data-subpage-scope="diagnostics" data-subpage="resolve">
      <h2>Resolve</h2>
      <p class="section-copy">Current read-only Resolve connection, product/version, project inventory, and any warnings from the media pool probe.</p>
      <div class="diag-grid" id="diagnosticsResolve">
        <div class="empty">Resolve diagnostics pending.</div>
      </div>
      <div class="pill-legend" aria-label="Status legend">
        <span class="pill-legend-item"><span class="status-pill pill-ok">OK</span> Healthy</span>
        <span class="pill-legend-item"><span class="status-pill pill-warn">Warn</span> Needs attention</span>
        <span class="pill-legend-item"><span class="status-pill pill-err">Error</span> Action required</span>
        <span class="pill-legend-item"><span class="status-pill pill-mute">Idle</span> Not yet probed</span>
      </div>
    </section>

    <section class="span-12 subpage" data-subpage-scope="diagnostics" data-subpage="mcp">
      <h2>MCP</h2>
      <p class="section-copy">DaVinci Resolve MCP server identity, detected Resolve scripting paths, and per-client install status for every supported harness (Claude Desktop, Claude Code, Cursor, VS Code, Windsurf, Cline, Roo Code, Zed, Continue, Antigravity).</p>
      <div class="diag-grid" id="diagnosticsMcpServer">
        <div class="empty">MCP diagnostics pending.</div>
      </div>
      <div class="settings-subhead" style="margin-top:24px">Clients</div>
      <p class="settings-subtitle">Install writes a managed <code>davinci-resolve</code> entry into the client's MCP config file. Remove reverses it. Existing entries in the file are preserved.</p>
      <div class="diag-grid" id="diagnosticsMcpClients">
        <div class="empty">Scanning clients…</div>
      </div>
      <div class="copy-status" id="mcpInstallStatus"></div>
    </section>

    <section class="span-12 subpage" data-subpage-scope="diagnostics" data-subpage="storage">
      <h2>Analysis Storage</h2>
      <p class="section-copy">Project analysis paths used for reports, the durable job database, and the local search index.</p>
      <div class="diag-grid" id="diagnosticsStorage">
        <div class="empty">Storage diagnostics pending.</div>
      </div>
    </section>

    <section class="span-12 subpage" data-subpage-scope="diagnostics" data-subpage="tools">
      <h2>Tools</h2>
      <p class="section-copy">Runtime helpers detected by the dashboard. Missing tools may reduce technical metadata or media probing depth.</p>
      <div class="tool-chip-grid" id="diagnosticsTools">
        <div class="empty">Tool diagnostics pending.</div>
      </div>
    </section>

    <section class="span-12 subpage" data-subpage-scope="diagnostics" data-subpage="media-pool-history">
      <h2>Media Pool History</h2>
      <p class="section-copy">Provenance log for destructive media-pool operations — deletes, replaces, relinks. Each row captures the action, the target clip or folder, the analysis run that triggered it, and the initiator. Kept separate from timeline <code>brain_edits</code> because the addressable entity is a media pool item, not a timeline.</p>
      <div class="mpc-toolbar">
        <label class="mpc-toolbar-field">Action
          <select id="mpcActionFilter">
            <option value="">all actions</option>
          </select>
        </label>
        <label class="mpc-toolbar-field">Limit
          <input id="mpcLimit" type="number" min="10" max="500" value="50">
        </label>
        <label class="mpc-toolbar-toggle">
          <input id="mpcGroupByClip" type="checkbox">
          <span>Group by target</span>
        </label>
        <button id="mpcRefreshBtn" class="secondary" type="button">Refresh</button>
        <span id="mpcMeta" class="mpc-meta"></span>
      </div>
      <div id="mpcTable" class="mpc-table">loading…</div>
    </section>
  </main>

  <main id="panel-docs" class="panel control-grid">
    <section class="span-12">
      <h2>Reference</h2>
      <div class="doc-reader-layout">
        <div class="doc-tools">
          <div class="doc-tool-group">
            <div class="doc-tool-title">Sections</div>
            <div class="doc-section-nav" id="docSectionNav">
              <div class="empty">Load a document.</div>
            </div>
          </div>
          <div class="doc-tool-group">
            <div class="doc-tool-title">Markdown</div>
            <label class="doc-filter"><input type="checkbox" data-md-filter="heading" checked> Headings</label>
            <label class="doc-filter"><input type="checkbox" data-md-filter="text" checked> Text</label>
            <label class="doc-filter"><input type="checkbox" data-md-filter="list" checked> Lists</label>
            <label class="doc-filter"><input type="checkbox" data-md-filter="code" checked> Code</label>
            <label class="doc-filter"><input type="checkbox" data-md-filter="table" checked> Tables</label>
            <label class="doc-filter"><input type="checkbox" data-md-filter="image" checked> Images</label>
          </div>
        </div>
        <div>
          <div class="section-meta" id="docMeta">Loading README</div>
          <article class="doc-reader" id="docReader">
            <div class="empty">Choose a document.</div>
          </article>
          <div class="doc-source" id="docSource"></div>
        </div>
      </div>
    </section>
  </main>

  <main id="panel-preferences" class="panel control-grid">
    <section class="span-12">
      <div class="section-top">
        <div>
          <h2>Server Defaults</h2>
          <p class="section-copy">These preferences are server-wide defaults for this local MCP install. Dashboard convenience settings stay in this browser.</p>
          <div class="section-meta" id="setupPrefsStatus">Loading setup defaults</div>
        </div>
        <div class="controls">
          <button id="savePrefsBtn">Save Defaults</button>
          <button class="secondary" id="refreshPrefsBtn">Refresh</button>
          <button class="secondary" id="resetPrefsBtn">Reset Defaults</button>
        </div>
      </div>
      <div class="settings-status" id="prefSaveStatus"></div>
    </section>

    <section class="span-12 subpage active" data-subpage-scope="preferences" data-subpage="analysis">
        <div class="settings-subhead">Analysis</div>
        <p class="settings-subtitle">Defaults used when agents run analysis or publish analysis-backed outputs without specifying every option.</p>
        <div class="settings-grid">
          <label>Vision default
            <select id="prefVisionDefault">
              <option value="on">on</option>
              <option value="off">off</option>
              <option value="technical_only">technical only</option>
              <option value="ask">ask</option>
            </select>
          </label>
          <label>Transcription default
            <select id="prefTranscriptionDefault">
              <option value="no">no</option>
              <option value="yes">yes</option>
              <option value="ask">ask</option>
            </select>
          </label>
          <label>Slate detection
            <select id="prefSlateDetectionDefault">
              <option value="ask">ask</option>
              <option value="yes">yes</option>
              <option value="no">no</option>
            </select>
          </label>
          <label>Source trust
            <select id="prefSourceTrust">
              <option value="auto">auto · conservative-by-default</option>
              <option value="filename">filename · use clip filename as corroborating evidence</option>
              <option value="low">low · frames only, aggressive hedging</option>
              <option value="medium">medium · frames + filename + cultural recognition</option>
              <option value="high">high · trusted archival source, confident claims</option>
            </select>
          </label>
          <label>Default analysis depth
            <select id="prefDepth">
              <option value="quick">quick</option>
              <option value="standard" selected>standard</option>
              <option value="deep">deep</option>
            </select>
          </label>
          <label>Default sample frames <input id="prefFrames" type="number" min="0" max="48" value="8"></label>
          <label>Frame sampling mode
            <select id="prefSamplingMode" onchange="updateSamplingModeHint()">
              <option value="ask">ask · choose on first analysis</option>
              <option value="fixed">Economy · flat frames, cheapest &amp; most predictable</option>
              <option value="per_minute">Balanced · frames scale with duration (linear cost)</option>
              <option value="adaptive_capped">Thorough · content-aware, bounded cost (recommended)</option>
              <option value="adaptive">Thorough (uncapped) · content-aware, up to 512 frames</option>
            </select>
          </label>
          <small class="pref-hint" id="samplingModeHint" style="display:block;margin:-4px 0 8px;opacity:0.75;"></small>
          <div class="pref-inline-row" style="display:flex;gap:10px;flex-wrap:wrap;">
            <label>Frames / minute <input id="prefSamplingRate" type="number" min="0.1" step="0.5" value="4" oninput="updateSamplingModeHint()"></label>
            <label>Frame floor <input id="prefSamplingFloor" type="number" min="1" value="3" oninput="updateSamplingModeHint()"></label>
            <label>Frame ceiling <input id="prefSamplingCeiling" type="number" min="1" value="80" oninput="updateSamplingModeHint()"></label>
          </div>
          <label>Persistence
            <select id="prefAnalysisPersistence">
              <option value="session_only">session only</option>
              <option value="keep_reports">keep reports</option>
              <option value="keep_artifacts">keep artifacts</option>
            </select>
          </label>
          <label>Summary style
            <select id="prefAnalysisSummaryStyle">
              <option value="full">full · everything the model can say</option>
              <option value="concise">concise · short, structured highlights</option>
              <option value="creative">creative · vibes, intent, editorial reads</option>
              <option value="technical">technical · camera, exposure, QC focus</option>
            </select>
          </label>
          <label>Report format
            <select id="prefReportFormat">
              <option value="compact">compact</option>
              <option value="full">full</option>
              <option value="machine_readable">machine readable</option>
            </select>
          </label>
        </div>
    </section>

    <section class="span-12 subpage" data-subpage-scope="preferences" data-subpage="caps">
        <div class="settings-subhead">Caps + Safety</div>
        <p class="settings-subtitle">Token + frame budgets for analysis, plus safety rails for destructive edits. Usage is tracked per project in <code>_soul/timeline_brain.sqlite</code>.</p>

        <div class="caps-section">
          <div class="caps-section-head">
            <div class="caps-section-title">Budget preset</div>
            <div class="caps-section-hint">Pick the preset that matches the job. Override individual fields below if needed.</div>
          </div>
          <div id="capsPresetCards" class="caps-preset-cards" role="radiogroup" aria-label="Analysis caps preset">
            <!-- cards rendered by JS -->
          </div>
          <input id="prefCapsPreset" type="hidden" value="standard">
        </div>

        <div class="caps-section">
          <div class="caps-section-head">
            <div class="caps-section-title">Vision token usage</div>
            <div class="caps-section-hint">Live consumption against the active caps. Green = comfortable, amber = approaching, red = at or over budget.</div>
          </div>
          <div id="capsUsageBlock" class="caps-usage-block">
            <div id="capsUsageGauges" class="caps-usage-gauges">
              <div class="caps-gauge" data-scope="clip">
                <div class="caps-gauge-row">
                  <span class="caps-gauge-label">Per&#8209;clip</span>
                  <span class="caps-gauge-numbers">—</span>
                </div>
                <div class="caps-gauge-bar"><span class="caps-gauge-fill"></span></div>
              </div>
              <div class="caps-gauge" data-scope="job">
                <div class="caps-gauge-row">
                  <span class="caps-gauge-label">Per&#8209;job</span>
                  <span class="caps-gauge-numbers">—</span>
                </div>
                <div class="caps-gauge-bar"><span class="caps-gauge-fill"></span></div>
              </div>
              <div class="caps-gauge" data-scope="day">
                <div class="caps-gauge-row">
                  <span class="caps-gauge-label">Today</span>
                  <span class="caps-gauge-numbers">—</span>
                </div>
                <div class="caps-gauge-bar"><span class="caps-gauge-fill"></span></div>
              </div>
            </div>
            <div class="caps-history-block">
              <div class="caps-history-title">Daily vision-token usage (last 30 days)</div>
              <div id="capsHistoryChart" class="caps-history-chart">loading…</div>
            </div>
          </div>
        </div>

        <div class="caps-section">
          <div class="caps-section-head">
            <div class="caps-section-title">Resolve 21 AI ops</div>
            <div class="caps-section-hint">Local Resolve AI operations (audio classification, IntelliSearch, slate, motion-deblur, speech). These run on Resolve's GPU/AI engine and do <strong>not</strong> consume the Claude analysis token budget above — tracked here for invocations, time, and files created.</div>
          </div>
          <div id="resolveAiOpsBlock" class="caps-usage-block">
            <div id="resolveAiOpsSummary" class="caps-section-hint">loading…</div>
            <table id="resolveAiOpsTable" class="resolve-ai-ops-table" style="display:none; width:100%; border-collapse:collapse; margin-top:8px; font-size:12px;">
              <thead><tr style="text-align:left; opacity:0.7;">
                <th style="padding:4px 6px;">Op</th><th style="padding:4px 6px;">Runs</th>
                <th style="padding:4px 6px;">OK</th><th style="padding:4px 6px;">Time</th>
                <th style="padding:4px 6px;">Files</th><th style="padding:4px 6px;">Created</th>
              </tr></thead>
              <tbody id="resolveAiOpsRows"></tbody>
            </table>
            <div id="resolveAiOpsRecent"></div>
          </div>
        </div>

        <div class="caps-section">
          <div class="caps-section-head">
            <div class="caps-section-title">Safety</div>
            <div class="caps-section-hint">Auto-archive timelines before destructive edits and refuse high-blast-radius ops when archive fails.</div>
          </div>
          <div class="settings-grid">
            <label class="checkbox-row">
              <input id="prefAutoSaveAfterArchive" type="checkbox">
              <span>Auto-save Resolve project after each archive</span>
              <small class="hint">When on, <code>project.SaveProject()</code> fires after every version-on-mutate archive. Protects against Resolve crashes losing history.</small>
            </label>
          </div>
          <div class="safety-strict-block">
            <div class="safety-strict-title">Strict mode — always on for:</div>
            <ul class="strict-actions-list">
              <li><code>timeline.delete_timelines</code></li>
              <li><code>timeline.delete_track</code></li>
              <li><code>timeline.delete_clips</code> with <code>ripple=true</code></li>
            </ul>
            <p class="safety-strict-note">Strict mode REFUSES the underlying call if the pre-mutation archive can't be created. Other destructive ops degrade silently — pass <code>strict=true</code> in any action's params to opt in to refusal for that call.</p>
          </div>
        </div>

        <details class="caps-section caps-advanced">
          <summary>
            <span class="caps-section-title">Advanced — per-field overrides</span>
            <span class="caps-section-hint">Leave blank to use the preset value shown in the placeholder. Type a number or <code>unlimited</code> to override.</span>
          </summary>
          <div class="settings-grid caps-override-grid">
            <label>Response chars <input id="capsOvResponseChars" type="text" placeholder="(preset)" data-cap-key="response_chars"></label>
            <label>Vision tokens / clip <input id="capsOvVisionClip" type="text" placeholder="(preset)" data-cap-key="vision_tokens_per_clip"></label>
            <label>Frames / clip <input id="capsOvFramesClip" type="text" placeholder="(preset)" data-cap-key="frames_per_clip"></label>
            <label>Vision tokens / job <input id="capsOvVisionJob" type="text" placeholder="(preset)" data-cap-key="vision_tokens_per_job"></label>
            <label>Vision tokens / day <input id="capsOvVisionDay" type="text" placeholder="(preset)" data-cap-key="vision_tokens_per_day"></label>
            <label>Wall clock seconds / call <input id="capsOvWallClock" type="text" placeholder="(preset)" data-cap-key="wall_clock_seconds_per_call"></label>
            <label>Max frame dimension (px) <input id="capsOvFrameDim" type="text" placeholder="(preset)" data-cap-key="max_frame_dim_pixels"></label>
          </div>
        </details>

        <details class="caps-section caps-inspector-block">
          <summary>
            <span class="caps-section-title">Inspector &amp; debug</span>
            <span class="caps-section-hint">Look up usage for a specific clip or batch, browse refusals, or reset today's day-scope rollup.</span>
          </summary>
          <div class="caps-inspector">
            <div class="caps-inspector-row">
              <label>Clip id <input id="capsInspectClipId" type="text" placeholder="abc123"></label>
              <label>or Job id <input id="capsInspectJobId" type="text" placeholder="batch_xyz"></label>
              <button id="capsInspectBtn" type="button">Look up</button>
              <button id="capsResetDayBtn" class="secondary" type="button" title="Delete today's day-scope usage rows (admin)">Reset today's usage</button>
            </div>
            <div id="capsInspectResult" class="caps-inspect-result">enter a clip_id or job_id and press Look up</div>
          </div>
          <div class="caps-refusals">
            <div class="caps-section-subtitle">Recent caps refusals</div>
            <div id="capsRefusalsList" class="caps-refusals-list">loading…</div>
          </div>
        </details>
    </section>

    <section class="span-12 subpage" data-subpage-scope="preferences" data-subpage="metadata">
        <div class="settings-subhead">Metadata And Markers</div>
        <p class="settings-subtitle">Controls for Resolve metadata writes and source-time marker suggestions. Source media remains read-only.</p>
        <div class="settings-grid">
          <label>Timed markers
            <select id="prefTimedMarkersDefault">
              <option value="ask">ask</option>
              <option value="yes">yes</option>
              <option value="no">no</option>
            </select>
          </label>
          <label>Overwrite policy
            <select id="prefMetadataOverwritePolicy">
              <option value="preserve_human">preserve human</option>
              <option value="fill_empty">fill empty</option>
              <option value="overwrite_owned_blocks">overwrite owned blocks</option>
              <option value="overwrite_all">overwrite all</option>
            </select>
          </label>
          <label>Max markers per clip
            <div class="marker-limit-control">
              <select id="prefMaxTimedMarkersMode">
                <option value="limited">limited</option>
                <option value="unlimited">unlimited</option>
              </select>
              <input id="prefMaxTimedMarkers" type="number" min="1" max="250" value="12">
            </div>
          </label>
          <label>Marker custom data
            <select id="prefMarkerCustomData">
              <option value="namespaced">namespaced</option>
              <option value="minimal">minimal</option>
            </select>
          </label>
          <label class="token-field">Metadata fields
            <div id="prefMetadataFieldPills" class="token-grid" role="group" aria-label="Metadata fields"></div>
            <input id="prefMetadataFields" type="hidden">
            <span class="token-count" id="prefMetadataFieldCount"></span>
          </label>
          <label class="token-field">Marker types
            <div id="prefTimedMarkerTypePills" class="token-grid" role="group" aria-label="Marker types"></div>
            <input id="prefTimedMarkerTypes" type="hidden">
            <span class="token-count" id="prefTimedMarkerTypeCount"></span>
          </label>
          <label>Marker colors <textarea id="prefTimedMarkerColors" class="settings-textarea" spellcheck="false"></textarea></label>
          <div class="stack">
            <label class="checkbox"><input id="prefIncludeConfidenceScores" type="checkbox"> Include confidence scores</label>
            <label class="checkbox"><input id="prefIncludeSourceTimeNotes" type="checkbox"> Include source time notes</label>
            <label class="checkbox"><input id="prefAskBeforeMetadataPublish" type="checkbox"> Ask before metadata publish</label>
            <label class="checkbox"><input id="prefDryRunFirstDefault" type="checkbox"> Dry run first</label>
          </div>
        </div>
    </section>

    <section class="span-12 subpage" data-subpage-scope="preferences" data-subpage="paths">
        <div class="settings-subhead">Paths And Workflow</div>
        <p class="settings-subtitle">Optional locations and Resolve navigation behavior after operations complete.</p>
        <div class="settings-grid">
          <label>Preferred analysis root
            <div class="path-field">
              <input id="prefPreferredAnalysisRoot" placeholder="Default project analysis root">
              <button type="button" class="secondary path-browse" data-browse-target="prefPreferredAnalysisRoot">Browse…</button>
            </div>
            <select class="path-recent" data-recent-target="prefPreferredAnalysisRoot" aria-label="Recent project roots">
              <option value="">Recent project roots…</option>
            </select>
          </label>
          <label>Generated media folder
            <div class="path-field">
              <input id="prefPreferredGeneratedMediaFolder" placeholder="Default generated media folder">
              <button type="button" class="secondary path-browse" data-browse-target="prefPreferredGeneratedMediaFolder">Browse…</button>
            </div>
          </label>
          <label>Inventory limit
            <input id="prefInventoryLimit" type="number" min="1" max="10000" placeholder="Default 500">
          </label>
          <label>Inventory exclude bins (comma separated)
            <input id="prefInventoryExcludeBins" type="text" placeholder="None — index every folder">
          </label>
          <label>Post-operation page
            <select id="prefPostOperationPage">
              <option value="stay_put">stay put</option>
              <option value="media">media</option>
              <option value="cut">cut</option>
              <option value="edit">edit</option>
              <option value="fusion">fusion</option>
              <option value="color">color</option>
              <option value="fairlight">fairlight</option>
              <option value="deliver">deliver</option>
            </select>
          </label>
        </div>
        <div class="settings-subhead" style="margin-top:24px">Where files live</div>
        <p class="settings-subtitle">Locations the dashboard uses for server defaults and browser-local preferences. Read-only diagnostics.</p>
        <div class="diag-grid" id="preferencesStorage">
          <div class="empty">Loading preference storage.</div>
        </div>
    </section>

    <section class="span-12 subpage" data-subpage-scope="preferences" data-subpage="updates">
        <div id="restartNeededBanner" class="restart-banner" hidden>
          <div class="restart-banner-text">
            <strong>MCP server restart needed</strong>
            <span id="restartBannerDetail"></span>
          </div>
          <div class="restart-banner-actions">
            <button id="restartBannerAck" class="secondary" type="button">Got it</button>
          </div>
        </div>
        <div class="settings-subhead">MCP Updates</div>
        <p class="settings-subtitle">Server-wide update-check behavior for the MCP package. Checks are best-effort and should not block startup.</p>
        <div class="settings-grid">
          <label>Update policy
            <select id="prefUpdateMode">
              <option value="prompt">prompt</option>
              <option value="notify">notify</option>
              <option value="auto">auto</option>
              <option value="never">never</option>
            </select>
          </label>
          <label>Channel
            <select id="prefUpdateChannel">
              <option value="stable">stable</option>
              <option value="beta">beta</option>
              <option value="dev">dev</option>
            </select>
          </label>
          <label>Check interval hours <input id="prefUpdateIntervalHours" type="number" min="0.1" step="0.1" value="24"></label>
          <label>Snooze hours <input id="prefUpdateSnoozeHours" type="number" min="0.1" step="0.1" value="24"></label>
        </div>

        <div class="update-actions-block">
          <div class="settings-subhead" style="margin-top:24px">Apply update</div>
          <div id="updateStatusBadge" class="update-status-badge">Loading status…</div>
          <div class="update-action-row">
            <button id="updatePreviewBtn" class="secondary" type="button">Preview release notes</button>
            <label class="checkbox-inline">
              <input id="updateStashCheckbox" type="checkbox">
              <span>Stash local changes if dirty</span>
            </label>
            <label class="checkbox-inline">
              <input id="updateForceJobsCheckbox" type="checkbox">
              <span>Override active-job lock</span>
            </label>
            <button id="updateApplyBtn" type="button">Apply update</button>
            <button id="updateRollbackBtn" class="secondary" type="button">Rollback last update</button>
          </div>
          <div id="updateActionResult" class="update-result"></div>
        </div>

        <div class="settings-subhead" style="margin-top:24px">Update history</div>
        <div id="updateHistoryTable" class="update-history-table">loading…</div>
    </section>

  </main>
  <div class="modal-backdrop" id="projectSwitchModal" role="dialog" aria-modal="true" aria-labelledby="projectSwitchTitle" aria-describedby="projectSwitchBody">
    <div class="modal-card">
      <div class="modal-kicker">Resolve Project Switch</div>
      <h3 id="projectSwitchTitle">Change Active Project?</h3>
      <p class="modal-body" id="projectSwitchBody">This will load the selected project in DaVinci Resolve and scope the control panel to that project.</p>
      <div class="modal-detail" id="projectSwitchDetail">Search, jobs, logs, diagnostics, and index status will refresh after the switch.</div>
      <div class="modal-actions">
        <button class="secondary" id="projectSwitchCancel" type="button">Cancel</button>
        <button id="projectSwitchConfirm" type="button">Load Project</button>
      </div>
    </div>
  </div>
  <div class="modal-backdrop" id="confirmModal" role="dialog" aria-modal="true" aria-labelledby="confirmModalTitle" aria-describedby="confirmModalBody">
    <div class="modal-card">
      <div class="modal-kicker" id="confirmModalKicker">Confirm</div>
      <h3 id="confirmModalTitle">Are you sure?</h3>
      <p class="modal-body" id="confirmModalBody"></p>
      <div class="modal-detail" id="confirmModalDetail"></div>
      <div class="modal-actions">
        <button class="secondary" id="confirmModalCancel" type="button">Cancel</button>
        <button id="confirmModalConfirm" type="button">OK</button>
      </div>
    </div>
  </div>
  <div class="modal-backdrop" id="updateModal" role="dialog" aria-modal="true" aria-labelledby="updateModalTitle" aria-describedby="updateModalBody">
    <div class="modal-card">
      <div class="modal-kicker" id="updateModalKicker">MCP Version</div>
      <h3 id="updateModalTitle">DaVinci Resolve MCP</h3>
      <p class="modal-body" id="updateModalBody">Loading version information…</p>
      <div class="modal-detail" id="updateModalDetail"></div>
      <div class="modal-detail" id="updateModalCommand" style="display:none">
        <div class="settings-subtitle" style="margin-bottom:6px">Update command</div>
        <code id="updateModalCommandText" class="modal-command"></code>
      </div>
      <div class="modal-actions">
        <a id="updateModalReleaseLink" class="secondary" href="https://github.com/samuelgursky/davinci-resolve-mcp/releases" target="_blank" rel="noreferrer" style="display:none">Release notes</a>
        <button class="secondary" id="updateModalCancel" type="button">Close</button>
        <button class="secondary" id="updateModalCopy" type="button" style="display:none">Copy Command</button>
        <button id="updateModalApply" type="button" style="display:none">Update Now</button>
      </div>
    </div>
  </div>
  <footer class="lab-footer">
    <div class="footer-credit">Developed by <a href="https://www.samuelgursky.com" target="_blank" rel="noreferrer">Samuel Gursky</a> for <a href="https://www.bradfordoperations.com" target="_blank" rel="noreferrer">Bradford Operations</a></div>
    <div class="footer-notice">DaVinci Resolve is a trademark of Blackmagic Design Pty Ltd. Bradford Operations is not affiliated with, endorsed by, or sponsored by Blackmagic Design. All third-party trademarks are the property of their respective owners.</div>
    <div class="footer-links">
      <span class="footer-open-source">Open source. Patches, features, and community contributions welcome.</span>
      <a class="github-icon-link" href="https://github.com/samuelgursky/davinci-resolve-mcp" target="_blank" rel="noreferrer" aria-label="GitHub Repository" title="GitHub Repository">
        <svg class="github-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.4 5.4 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4"></path>
          <path d="M9 18c-4.51 2-5-2-7-2"></path>
        </svg>
        <span class="sr-only">GitHub Repository</span>
      </a>
    </div>
  </footer>

  <script>
    const state = {
      boot: null,
      projects: null,
      allProjects: null,
      activeContext: null,
      resolveMedia: null,
      resolveMediaStale: false,
      mediaETag: null,
      mediaPollTimer: null,
      mediaRefreshing: false,
      mediaLastRefresh: null,
      indexStatus: null,
      selectedClipIds: new Set(),
      clipSelectionTouched: false,
      setupDefaults: null,
      setupSchema: null,
      projectDialogCleanup: null,
      activePanel: 'overview',
      activeDoc: 'readme',
      activeSubpages: {
        analysis: 'media',
        diagnostics: 'resolve',
        docs: 'readme',
        preferences: 'analysis',
      },
      review: {
        view: 'bin',           // 'bin' | 'clip' | 'shot'
        clipList: null,        // last /api/clips response
        currentClipId: null,
        currentClipData: null, // last /api/clips/<id> response
        currentShotIndex: null,
        currentShotData: null,
        currentTranscriptData: null,
        currentTranscriptSegmentIndex: null,
        transcriptFilter: '',
        // Per-segment edit: only one segment edits at a time.
        editingSegmentDraftIndex: null,
        transcriptRegenerating: false,
        editingShot: false,
        panelStateTimer: null,
        lastPanelStateAt: null,
        searchQuery: '',
        searchTimer: null,
        searchResults: null,
        binFilter: '',
        viewMode: 'grid',      // 'grid' | 'list'
        selectedBinClipIds: new Set(), // clip_ids selected in the bin grid
        selectionAnchor: null,         // clip_id used as range-selection anchor
        contextMenu: null,             // currently-open context menu element
        bulkBusy: false,
      },
    };
    const $ = (id) => document.getElementById(id);
    const VIEW_ALL_PROJECTS_VALUE = '__view_all_projects__';
    const PANEL_LABELS = {
      overview: 'Overview',
      analysis: 'Media',
      aiconsole: 'AI Console',
      diagnostics: 'Setup',
      projects: 'Projects',
      docs: 'Docs',
      preferences: 'Preferences',
    };
    const PANEL_ICONS = {
      overview: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>',
      analysis: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"></path><path d="m19 9-5 5-4-4-3 3"></path></svg>',
      aiconsole: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8V4H8"></path><rect x="4" y="12" width="16" height="8" rx="2"></rect><path d="M2 14h2"></path><path d="M20 14h2"></path><path d="M15 13v2"></path><path d="M9 13v2"></path></svg>',
      diagnostics: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l2.1-2.1a6 6 0 0 1-7.6 7.6l-4 4a2.1 2.1 0 0 1-3-3l4-4a6 6 0 0 1 7.6-7.6z"></path></svg>',
      projects: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h5l2 3h11v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><path d="M7 7V5a2 2 0 0 1 2-2h3l2 2h3a2 2 0 0 1 2 2v3"></path></svg>',
      docs: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5z"></path></svg>',
      preferences: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.52a2 2 0 0 1-1 1.72l-.15.1a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.38a2 2 0 0 0-.73-2.73l-.15-.1a2 2 0 0 1-1-1.72v-.52a2 2 0 0 1 1-1.72l.15-.1a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"></path><circle cx="12" cy="12" r="3"></circle></svg>',
    };
    const DOC_LABELS = {
      readme: 'README',
      'release-notes': 'Release Notes',
      'analysis-guide': 'Media Analysis Guide',
      'agent-skill': 'Agent Skill',
    };
    const SUBPAGE_LABELS = {
      analysis: {
        media: 'Inventory',
        review: 'Review',
      },
      diagnostics: {
        resolve: 'Resolve',
        mcp: 'MCP',
        storage: 'Storage',
        tools: 'Tools',
        'media-pool-history': 'Media Pool History',
      },
      docs: DOC_LABELS,
      preferences: {
        analysis: 'Analysis',
        caps: 'Caps + Safety',
        metadata: 'Metadata And Markers',
        paths: 'Paths And Workflow',
        updates: 'MCP Updates',
      },
    };
    const DEFAULT_SUBPAGES = {
      analysis: 'media',
      diagnostics: 'resolve',
      docs: 'readme',
      preferences: 'analysis',
    };
    const SUBPAGE_ICONS = {
      review: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="14" rx="2"></rect><circle cx="9" cy="10" r="2"></circle><path d="m21 17-5-5-9 9"></path></svg>',
      media: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="m7 15 3-3 2 2 4-5 1 2"></path></svg>',
      search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"></circle><path d="m21 21-4.3-4.3"></path></svg>',
      resolve: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4"></path><path d="M12 18v4"></path><path d="M2 12h4"></path><path d="M18 12h4"></path><circle cx="12" cy="12" r="3"></circle></svg>',
      mcp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7v10l8 5 8-5V7l-8-5z"></path><path d="m4 7 8 5 8-5"></path><path d="M12 12v10"></path></svg>',
      storage: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5"></path><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"></path></svg>',
      tools: PANEL_ICONS.diagnostics,
      readme: PANEL_ICONS.docs,
      'analysis-guide': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18h6"></path><path d="M10 22h4"></path><path d="M12 2a7 7 0 0 0-4 12c.65.55 1 1.35 1 2h6c0-.65.35-1.45 1-2A7 7 0 0 0 12 2z"></path></svg>',
      'release-notes': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8v4l3 3"></path><circle cx="12" cy="12" r="9"></circle></svg>',
      'agent-skill': '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 8V4H8"></path><rect x="4" y="12" width="16" height="8" rx="2"></rect><path d="M2 14h2"></path><path d="M20 14h2"></path><path d="M15 13v2"></path><path d="M9 13v2"></path></svg>',
      metadata: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 7h-9"></path><path d="M14 17H5"></path><circle cx="17" cy="17" r="3"></circle><circle cx="7" cy="7" r="3"></circle></svg>',
      paths: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7h5l2 3h11v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path></svg>',
      updates: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-2.64-6.36"></path><path d="M21 3v6h-6"></path></svg>',
      dashboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"></rect><path d="M3 9h18"></path><path d="M9 21V9"></path></svg>',
    };
    const METADATA_FIELD_CANDIDATES = [
      'Description',
      'Comments',
      'Keywords',
      'People',
      'Scene',
      'Shot',
      'Take',
      'Camera #',
      'Roll Card #',
      'Good Take',
      'Location',
      'Notes',
    ];
    const DEFAULT_PREFS = {
      autoPoll: true,
      pollInterval: '15000',
    };
    const PREFERENCE_HELP = {
      prefVisionDefault: 'Controls whether visual frame analysis is used by default when an operation supports it.',
      prefTranscriptionDefault: 'Sets the default answer for transcript generation on audio-bearing clips.',
      prefSlateDetectionDefault: 'Controls whether slate detection should run or ask before adding slate-informed context.',
      prefSamplingMode: 'Chooses how many frames each clip gets for visual analysis: Economy (flat), Balanced (scales with duration), or Thorough (content-aware, bounded). Drives both coverage and token cost.',
      prefSamplingRate: 'Frames sampled per minute in Balanced mode (also seeds Thorough on short clips).',
      prefSamplingFloor: 'Minimum frames per clip for duration/content-scaled modes.',
      prefSamplingCeiling: 'Maximum frames per clip for Balanced and Thorough modes (the Thorough per-clip cap).',
      prefAnalysisPersistence: 'Chooses whether analysis artifacts stay session-only or keep reusable reports and frames.',
      prefAnalysisSummaryStyle: 'Tunes the language of generated summaries for editorial, QC, producer, or full-detail review.',
      prefReportFormat: 'Chooses compact readable reports, full reports, or machine-readable output for downstream agents.',
      prefTimedMarkersDefault: 'Sets the default answer for writing source-time analysis notes as Resolve clip markers.',
      prefMetadataOverwritePolicy: 'Controls how analysis text interacts with existing human-entered Resolve metadata.',
      prefMaxTimedMarkersMode: 'Limited caps marker suggestions per clip. Unlimited stores 0 and does not truncate marker candidates.',
      prefMarkerCustomData: 'Namespaced custom data keeps provenance richer; minimal keeps Resolve marker payloads smaller.',
      prefMetadataFieldPills: 'Enabled fields receive analysis metadata when publishing is confirmed.',
      prefTimedMarkerTypePills: 'Enabled marker types decide which source-time moments can become Resolve markers.',
      prefTimedMarkerColors: 'JSON map from marker type to Resolve marker color.',
      prefIncludeConfidenceScores: 'Adds model or detector confidence values where analysis provides them.',
      prefIncludeSourceTimeNotes: 'Includes source time references in generated metadata and marker notes.',
      prefAskBeforeMetadataPublish: 'Keeps metadata writes behind an explicit confirmation step by default.',
      prefDryRunFirstDefault: 'Prefers a preview pass before committing metadata or marker changes.',
      prefPreferredAnalysisRoot: 'Optional absolute path for analysis databases and reports. Empty uses the project analysis root.',
      prefPreferredGeneratedMediaFolder: 'Optional folder for generated sidecars or scratch outputs when a workflow needs them.',
      prefInventoryLimit: 'Maximum number of clips to index during the Media Pool inventory walk (1–10000).',
      prefInventoryExcludeBins: 'Comma-separated folder names to skip entirely during the inventory walk. Empty indexes every folder.',
      prefPostOperationPage: 'Resolve page to open after an operation completes, or stay put.',
      prefUpdateMode: 'Controls update checks for the MCP package.',
      prefUpdateIntervalHours: 'Minimum time between best-effort release checks.',
      prefUpdateSnoozeHours: 'How long snoozed update notices stay quiet.',
      prefDepth: 'Default analysis depth applied to MCP analysis prompts.',
      prefFrames: 'Default number of sample frames to inspect per clip for visual analysis.',
      prefSourceTrust: 'Default trust level for non-frame context (filename, cultural recognition). Auto keeps conservative-by-default hedging.',
    };

    async function api(path, options = {}) {
      const res = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
      });
      const payload = await res.json();
      if (!res.ok || payload.success === false) {
        throw new Error(payload.error || res.statusText);
      }
      return payload;
    }

    function setText(id, value) {
      const el = $(id);
      if (el) el.textContent = value;
    }

    function setHtml(id, value) {
      const el = $(id);
      if (el) el.innerHTML = value;
    }

    function subpageFor(panelName, requested) {
      const pages = SUBPAGE_LABELS[panelName];
      if (!pages) return null;
      if (requested && pages[requested]) return requested;
      const current = state.activeSubpages[panelName];
      if (current && pages[current]) return current;
      return DEFAULT_SUBPAGES[panelName] || Object.keys(pages)[0] || null;
    }

    function setPanel(panelName, options = {}) {
      const next = PANEL_LABELS[panelName] ? panelName : 'overview';
      const subpage = subpageFor(next, options.subpage || options.subpageTarget);
      state.activePanel = next;
      if (subpage) {
        state.activeSubpages[next] = subpage;
      }
      if (next === 'docs' && subpage) {
        state.activeDoc = subpage;
      }
      document.querySelectorAll('.panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === `panel-${next}`);
      });
      document.querySelectorAll('.control-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.panelTarget === next);
      });
      renderSubpage(next, subpage);
      renderBreadcrumb();
      if (options.updateHash !== false) {
        updateRouteHash(next, subpage);
      }
      if (next === 'preferences') {
        syncPreferencesPanel();
        refreshSetupDefaults().catch(alertError);
      }
      if (next === 'aiconsole') {
        initAiConsole();
      }
      if (next === 'docs' && subpage) {
        loadDoc(subpage, { updateHash: false }).catch(alertError);
      }
      if (next === 'projects' && !state.allProjects) {
        refreshAllProjects().catch(alertError);
      }
      if (next === 'analysis' && subpage === 'review') {
        ensureReviewPanelStateTimer();
        if (!state.review.clipList) {
          refreshReviewBin().catch(alertError);
        } else {
          renderReviewView();
        }
        pollPanelStateOnce().catch(() => {});
      }
    }

    function renderSubpage(panelName, subpage) {
      document.querySelectorAll(`[data-subpage-scope="${panelName}"]`).forEach(el => {
        el.classList.toggle('active', el.dataset.subpage === subpage);
      });
      document.querySelectorAll('.nav-dropdown-item').forEach(item => {
        const active = item.dataset.panelTarget === panelName && item.dataset.subpageTarget === subpage;
        item.classList.toggle('active', active);
        if (active) {
          item.setAttribute('aria-current', 'page');
        } else {
          item.removeAttribute('aria-current');
        }
      });
    }

    function breadcrumbSeparator() {
      return `<span class="nav-breadcrumb-sep" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="m9 18 6-6-6-6"></path>
        </svg>
      </span>`;
    }

    function breadcrumbMarkup({ label, icon }) {
      const iconMarkup = `<span class="breadcrumb-item-icon" aria-hidden="true">${icon || ''}</span>`;
      const textMarkup = `<span class="nav-breadcrumb-current">${escapeHtml(label)}</span>`;
      return `<span class="breadcrumb-item">${iconMarkup}${textMarkup}</span>`;
    }

    function renderBreadcrumb() {
      const trail = $('breadcrumbTrail');
      if (!trail) return;
      const panel = state.activePanel;
      const subpage = state.activeSubpages[panel];
      const crumbs = [{
        label: PANEL_LABELS[panel] || 'Overview',
        icon: PANEL_ICONS[panel] || PANEL_ICONS.overview,
        current: !subpage,
      }];
      if (subpage && SUBPAGE_LABELS[panel]?.[subpage]) {
        crumbs.push({
          label: SUBPAGE_LABELS[panel][subpage],
          icon: SUBPAGE_ICONS[subpage] || PANEL_ICONS[panel],
          current: true,
        });
      }
      trail.innerHTML = crumbs.map((crumb, index) => {
        const separator = index === 0 ? '' : breadcrumbSeparator();
        return `${separator}${breadcrumbMarkup(crumb)}`;
      }).join('');
    }

    function updateRouteHash(panelName, subpage, extra) {
      const next = PANEL_LABELS[panelName] ? panelName : 'overview';
      let hash;
      if (subpage && SUBPAGE_LABELS[next]?.[subpage]) {
        hash = `#${next}/${encodeURIComponent(subpage)}`;
      } else {
        hash = `#${next}`;
      }
      if (extra) hash += extra;
      if (window.location.hash !== hash) {
        history.replaceState(null, '', hash);
      }
    }

    function buildReviewRouteExtra() {
      const r = state.review;
      if (r.view === 'shot' && r.currentClipId && r.currentShotIndex != null) {
        return `/clip/${encodeURIComponent(r.currentClipId)}/shot/${r.currentShotIndex}`;
      }
      if (r.view === 'transcript' && r.currentClipId) {
        return `/clip/${encodeURIComponent(r.currentClipId)}/transcript`;
      }
      if (r.view === 'clip' && r.currentClipId) {
        return `/clip/${encodeURIComponent(r.currentClipId)}`;
      }
      if (r.view === 'combined' && Array.isArray(r.combinedClipIds) && r.combinedClipIds.length) {
        return `/combined/${r.combinedClipIds.map(encodeURIComponent).join(',')}`;
      }
      if (r.view === 'plan' && state.plans?.currentPlanId) {
        return `/plans/${encodeURIComponent(state.plans.currentPlanId)}`;
      }
      if (r.view === 'plans') return '/plans';
      return '';
    }

    function refreshReviewHash() {
      updateRouteHash('analysis', 'review', buildReviewRouteExtra());
    }

    function applyInitialRoute() {
      const route = window.location.hash.replace(/^#/, '').split('/');
      const panelName = PANEL_LABELS[route[0]] ? route[0] : 'overview';
      const requestedSubpage = decodeURIComponent(route[1] || '');
      const subpage = subpageFor(panelName, requestedSubpage);
      setPanel(panelName, { subpage, updateHash: false });
      // Deep links: #analysis/review/clip/<id>[/shot/<n>|/transcript]
      if (panelName === 'analysis' && subpage === 'review' && route[2] === 'clip' && route[3]) {
        const clipId = decodeURIComponent(route[3]);
        if (route[4] === 'shot' && route[5] != null) {
          const shotIndex = Number(route[5]);
          openClipDetail(clipId, { writePanelState: false, pushHash: false })
            .then(() => openShotDetail(shotIndex, { writePanelState: false, pushHash: false }))
            .catch(alertError);
        } else if (route[4] === 'transcript') {
          openTranscript(clipId, { writePanelState: false, pushHash: false }).catch(alertError);
        } else {
          openClipDetail(clipId, { writePanelState: false, pushHash: false }).catch(alertError);
        }
      }
      if (panelName === 'analysis' && subpage === 'review' && route[2] === 'history') {
        reviewSetView('history');
        refreshHistoryTimelines().catch(alertError);
      }
      // Deep links: #analysis/review/plans[/<plan_id>]
      if (panelName === 'analysis' && subpage === 'review' && route[2] === 'plans') {
        if (route[3]) {
          openEditPlan(decodeURIComponent(route[3]), { pushHash: false }).catch(alertError);
        } else {
          reviewSetView('plans', { pushHash: false });
          refreshEditPlans().catch(alertError);
        }
      }
      // Deep links: #analysis/review/combined/<id1,id2,...>
      if (panelName === 'analysis' && subpage === 'review' && route[2] === 'combined' && route[3]) {
        const ids = decodeURIComponent(route[3]).split(',').filter(Boolean);
        if (ids.length) openCombinedReview(ids, { pushHash: false }).catch(alertError);
      }
    }

    function renderInfoRows(id, rows) {
      setHtml(id, rows.map(row => {
        const value = row.value == null || row.value === '' ? 'Unavailable' : row.value;
        const iconHtml = row.icon ? `<span class="info-row-icon" aria-hidden="true">${row.icon}</span>` : '';
        const valueHtml = row.html ? value : escapeHtml(String(value));
        const pillHtml = row.pill ? statusPill(row.pill.tone, row.pill.label) : '';
        const meter = row.meter ? `<div class="info-row-meter"><span style="width:${Math.max(0, Math.min(100, Number(row.meter.percent) || 0))}%"></span></div>` : '';
        return `<div class="info-row${row.pill ? ' has-pill' : ''}">
          <span>${iconHtml}${escapeHtml(row.label)}</span>
          <b>${valueHtml}${pillHtml}${meter}</b>
        </div>`;
      }).join(''));
    }

    function sourceClips() {
      return (state.resolveMedia?.clips || []).filter(clip => clip.source_clip);
    }

    function sequenceCount(media) {
      const counts = media?.counts || {};
      if (counts.sequences != null) return Number(counts.sequences || 0);
      return (media?.clips || []).filter(clip => {
        const mediaType = String(clip.media_type || '').toLowerCase();
        return mediaType.includes('sequence') || mediaType.includes('timeline');
      }).length;
    }

    function indexSummary() {
      const status = state.indexStatus;
      if (!status) return { label: 'Checking', detail: 'Index status pending', tone: 'pill-mute', exists: false };
      if (!status.exists) return { label: 'Not built', detail: 'Search unavailable until built', tone: 'pill-warn', exists: false };
      const clips = Number(status.counts?.clips || 0);
      return {
        label: clips > 0 ? `${clips} indexed` : 'Empty',
        detail: `${clipLabel(clips)} indexed · ${formatBytes(status.size_bytes || 0)}`,
        tone: clips > 0 ? 'pill-ok' : 'pill-warn',
        exists: true,
      };
    }

    function renderOverview() {
      const media = state.resolveMedia;
      const counts = media?.counts || {};
      const clips = sourceClips();
      const hiddenRecords = Math.max(0, Number(counts.total || 0) - Number(counts.source_clips || clips.length));
      const sequences = sequenceCount(media);
      // Connection state comes from the /api/boot handshake, which returns as soon
      // as the Resolve bridge is reachable — independent of the media inventory,
      // which can take a long time to probe network source media. inventoryPending
      // means Resolve is live but /api/resolve/media hasn't returned yet.
      const bootResolve = state.boot?.resolve || {};
      const resolveConnected = bootResolve.available === true || !!media?.resolve_available;
      const inventoryPending = resolveConnected && !media;
      const projectName = state.activeContext?.project_name || media?.project?.name || state.boot?.project_name || 'Resolve project';
      const resolveProject = media?.project?.name || (resolveConnected ? 'Loading project…' : 'No Resolve project');
      let resolveStatus;
      if (media?.resolve_available) {
        resolveStatus = `Resolve: ${resolveProject} · read-only`;
      } else if (inventoryPending) {
        resolveStatus = 'Resolve connected · loading inventory…';
      } else if (resolveConnected) {
        resolveStatus = media?.status || media?.error || 'Resolve connected';
      } else {
        resolveStatus = media?.status || bootResolve.error || 'Connection pending';
      }
      const index = indexSummary();
      const readyClips = clips.filter(clip => clip.analyzable).length;
      const analyzedClips = clips.filter(clip => ['analyzed', 'succeeded', 'skipped'].includes(String(clip.analysis_status || ''))).length;
      const onlineClips = clips.filter(clip => String(clip.status || '') === 'online').length;
      const missingClips = clips.filter(clip => ['missing_file', 'offline'].includes(String(clip.status || ''))).length;
      const mediaStatusLabel = media?.resolve_available ? `${onlineClips} online` : (inventoryPending ? 'Loading…' : 'Unavailable');
      const mediaStatusDetail = media?.resolve_available
        ? `${missingClips} missing/offline · ${hiddenRecords} non-source records`
        : (inventoryPending ? 'Reading Media Pool inventory…' : (media?.error || media?.status || 'Resolve inventory pending'));

      setText('overviewUpdated', `Updated ${new Date().toLocaleTimeString()}`);
      setText('overviewProject', projectName);
      setText('overviewResolveStatus', resolveStatus);
      setText('overviewClipCount', String(clips.length));
      setText('overviewClipStatus', `${readyClips} ready · ${analyzedClips} analyzed`);
      setText('overviewSequenceCount', String(sequences));
      setText('overviewSequenceStatus', sequences ? 'Read-only Resolve sequences' : 'No sequences detected');
      setText('overviewMediaStatus', mediaStatusLabel);
      setText('overviewMediaStatusDetail', mediaStatusDetail);

      if (!media?.resolve_available) {
        const emptyMsg = inventoryPending
          ? 'Resolve connected — loading Media Pool inventory…'
          : (media?.error || 'Open Resolve with a project loaded to inspect clips.');
        setHtml('overviewStatusList', `<div class="empty">${escapeHtml(emptyMsg)}</div>`);
      } else {
        const ICONS = {
          project: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h5l2 3h11v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
          clips: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m7 15 3-3 2 2 4-5 1 2"/></svg>',
          sequences: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18"/><path d="M9 4v16"/></svg>',
          status: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
          analysis: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>',
          search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
          safety: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
        };
        const clipsTone = readyClips > 0 ? 'pill-ok' : 'pill-warn';
        const mediaTone = missingClips === 0 ? 'pill-ok' : (missingClips < clips.length / 4 ? 'pill-warn' : 'pill-err');
        const analyzedPct = clips.length ? Math.round((analyzedClips / clips.length) * 100) : 0;
        const analysisTone = analyzedPct >= 90 ? 'pill-ok' : (analyzedPct > 0 ? 'pill-info' : 'pill-mute');

        renderInfoRows('overviewStatusList', [
          { label: 'Resolve project', value: resolveProject, icon: ICONS.project, pill: { tone: 'pill-ok', label: 'Read-only' } },
          { label: 'Source clips', value: `${clipLabel(clips.length)} · ${readyClips} ready`, icon: ICONS.clips, pill: { tone: clipsTone, label: `${readyClips} ready` } },
          { label: 'Sequences', value: sequences ? `${sequences} timeline${sequences === 1 ? '' : 's'} detected (read-only)` : 'No timelines detected', icon: ICONS.sequences },
          { label: 'Clip media status', value: `${onlineClips} online · ${missingClips} missing/offline`, icon: ICONS.status, pill: { tone: mediaTone, label: missingClips ? `${missingClips} missing` : 'All online' } },
          { label: 'Analysis progress', value: `${analyzedClips} of ${clips.length} analyzed (${analyzedPct}%)`, icon: ICONS.analysis, pill: { tone: analysisTone, label: `${analyzedPct}%` }, meter: { percent: analyzedPct } },
          { label: 'Search index', value: index.detail, icon: ICONS.search, pill: { tone: index.tone, label: index.label } },
          { label: 'Safety', value: 'Source media is read-only; outputs stay in the active project analysis root.', icon: ICONS.safety, pill: { tone: 'pill-ok', label: 'Read-only' } },
        ]);
        if (!clips.length) {
          const list = $('overviewStatusList');
          if (list) list.insertAdjacentHTML('afterbegin', chatPromptCard(
            'This project has no source clips yet. Import media in Resolve, then ask your assistant to take it from there:',
            'Look at my current Resolve project, inventory the media, and analyze the source clips.'
          ));
        }
      }
    }

    function statusPill(tone, label) {
      const cls = ['pill-ok', 'pill-warn', 'pill-err', 'pill-info', 'pill-mute'].includes(tone) ? tone : 'pill-mute';
      return `<span class="status-pill ${cls}">${escapeHtml(label)}</span>`;
    }
    function diagRow(label, value, opts = {}) {
      const mutedClass = opts.muted ? ' muted' : '';
      const valHtml = opts.html ? value : escapeHtml(String(value ?? '—'));
      return `<div class="diag-row"><span class="diag-label">${escapeHtml(label)}</span><span class="diag-value${mutedClass}">${valHtml}</span></div>`;
    }
    const DIAG_ICONS = {
      connection: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.55a11 11 0 0 1 14.08 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><line x1="12" y1="20" x2="12" y2="20"/></svg>',
      project: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h5l2 3h11v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
      inventory: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18"/><path d="M8 5v14"/></svg>',
      root: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h5l2 3h11v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
      index: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
      database: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4.03 3 9 3s9-1.34 9-3"/></svg>',
    };
    function renderDiagnostics() {
      const media = state.resolveMedia;
      const counts = media?.counts || {};
      const clips = sourceClips();
      const hiddenRecords = Math.max(0, Number(counts.total || 0) - Number(counts.source_clips || clips.length));
      const index = indexSummary();
      const resolveInfo = state.boot?.resolve || {};
      const warnings = media?.warnings || [];
      // The boot handshake establishes the connection; media inventory loads after.
      const handshake = resolveInfo.available === true;
      const resolveOnline = !!media?.resolve_available || handshake;
      const inventoryPending = handshake && !media;
      const offline = (media || resolveInfo.error) && !resolveOnline;
      const resolveTone = resolveOnline ? 'pill-ok' : (offline ? 'pill-err' : 'pill-mute');
      const resolveLabel = resolveOnline ? 'Connected' : (offline ? 'Offline' : 'Pending');

      const connectionCard = `
        <div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.connection}Connection</div>
            ${statusPill(resolveTone, resolveLabel)}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Product', resolveInfo.product || (resolveOnline ? 'DaVinci Resolve' : 'Unavailable'), { muted: !resolveOnline })}
            ${diagRow('Version', resolveInfo.version_string || '—', { muted: !resolveInfo.version_string })}
            ${diagRow('Active page', resolveInfo.page || '—', { muted: !resolveInfo.page })}
            ${diagRow('Status', inventoryPending ? 'Read-only API live · loading inventory…' : (resolveOnline ? 'Read-only API live' : (media?.error || resolveInfo.error || media?.status || 'Waiting for handshake')))}
          </div>
        </div>`;

      const projectName = media?.project?.name || state.activeContext?.project_name || 'Unavailable';
      const projectTone = media?.project?.name ? 'pill-ok' : 'pill-mute';
      const warnTone = warnings.length ? 'pill-warn' : 'pill-ok';
      const projectCard = `
        <div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.project}Project</div>
            ${statusPill(projectTone, projectName === 'Unavailable' ? 'None' : 'Loaded')}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Name', projectName, { muted: projectName === 'Unavailable' })}
            ${diagRow('Project ID', state.activeContext?.project_id || '—', { muted: !state.activeContext?.project_id })}
            ${diagRow('Warnings', `${warnings.length} ${warnings.length === 1 ? 'warning' : 'warnings'}`, { html: false })}
          </div>
          <div class="diag-card-footer">
            <span>${warnings.length ? statusPill(warnTone, 'Inspect') : ''}</span>
            <span>${warnings.length ? escapeHtml(warnings.slice(0, 2).join(' · ')) : 'No warnings'}</span>
          </div>
        </div>`;

      const totalRecords = Number(counts.total ?? 0);
      const sourceCount = Number(counts.source_clips ?? clips.length ?? 0);
      const inventoryTone = totalRecords > 0 ? 'pill-ok' : 'pill-mute';
      const inventoryCard = `
        <div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.inventory}Inventory</div>
            ${statusPill(inventoryTone, totalRecords ? `${sourceCount} clips` : 'Empty')}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Total records', totalRecords)}
            ${diagRow('Source clips', sourceCount)}
            ${diagRow('Hidden', hiddenRecords)}
            ${diagRow('Sequences', counts.sequences ?? 0)}
          </div>
        </div>`;

      setHtml('diagnosticsResolve', connectionCard + projectCard + inventoryCard);

      // ── Storage cards ────────────────────────────────────────────────
      const analysisRoot = state.activeContext?.project_root || state.boot?.project_root || media?.project_root || '';
      const rootTone = analysisRoot ? 'pill-ok' : 'pill-mute';
      const indexTone = index.tone || (index.exists ? 'pill-ok' : 'pill-warn');
      const indexLabel = index.label || (index.exists ? 'Indexed' : 'Not built');
      const storageCards = [
        `<div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.root}Analysis root</div>
            ${statusPill(rootTone, analysisRoot ? 'Active' : 'Pending')}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Path', analysisRoot || '—', { muted: !analysisRoot })}
            ${diagRow('Base root', state.boot?.output_root?.base_root || '—', { muted: !state.boot?.output_root?.base_root })}
          </div>
        </div>`,
        `<div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.index}Search index</div>
            ${statusPill(indexTone, indexLabel)}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Detail', index.detail)}
            ${diagRow('Database', analysisRoot ? `${analysisRoot}/index.sqlite` : 'Pending', { muted: !analysisRoot })}
          </div>
        </div>`,
        `<div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.database}Jobs database</div>
            ${statusPill(analysisRoot ? 'pill-ok' : 'pill-mute', analysisRoot ? 'Ready' : 'Pending')}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Path', analysisRoot ? `${analysisRoot}/jobs.sqlite` : 'Pending', { muted: !analysisRoot })}
          </div>
        </div>`,
      ];
      setHtml('diagnosticsStorage', storageCards.join(''));

      // ── Tool chips ───────────────────────────────────────────────────
      const tools = state.boot?.capabilities?.tools || {};
      const names = Object.keys(tools);
      if (!names.length) {
        setHtml('diagnosticsTools', '<div class="empty">No tool capability data yet.</div>');
        return;
      }
      setHtml('diagnosticsTools', names.map(name => {
        const tool = tools[name] || {};
        const ready = !!tool.available;
        const tone = ready ? 'pill-ok' : 'pill-warn';
        const subline = tool.version ? `v${escapeHtml(String(tool.version).replace(/^v/, ''))}` : (tool.path ? escapeHtml(tool.path) : (ready ? 'available' : 'missing'));
        const install = tool.install || null;
        const cmd = install && install.command ? install.command : '';
        const note = install && (install.requirement_note || install.notes) ? (install.requirement_note || install.notes) : '';
        const canInstall = !ready && !!cmd && (install ? install.requirement_met !== false : true);
        const statusId = `toolStatus_${cssToken(name)}`;
        const installBlock = (!ready && install) ? `
          <div class="tool-chip-install">
            ${cmd ? `<code class="tool-chip-cmd" id="toolCmd_${cssToken(name)}">${escapeHtml(cmd)}</code>` : ''}
            ${note ? `<div class="tool-chip-note">${escapeHtml(note)}</div>` : ''}
            <div class="tool-chip-actions">
              ${canInstall ? `<button class="btn-mini" type="button" onclick="copyInstallCommand('${escapeAttribute(name)}')">Copy command</button>` : ''}
              <div class="action-menu">
                <button class="btn-mini primary action-menu-trigger" type="button" data-action-menu-trigger="tool" aria-haspopup="menu" aria-expanded="false" onclick="event.stopPropagation(); closeNavDropdowns(); toggleActionMenu(this)">Ask <svg class="action-menu-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"></path></svg></button>
                <div class="action-dropdown" role="menu" aria-label="Ask AI to install ${escapeAttribute(name)}">
                  ${renderClientMenuItems('ask', { toolName: name })}
                </div>
              </div>
              <button class="btn-mini" type="button" onclick="recheckCapabilities()">Recheck</button>
            </div>
            <div class="tool-chip-status" id="${statusId}"></div>
          </div>
        ` : '';
        return `<div class="tool-chip">
          <div class="tool-chip-row">
            <div class="tool-chip-name">
              <strong>${escapeHtml(name)}</strong>
              <small>${subline}</small>
            </div>
            ${statusPill(tone, ready ? 'Ready' : 'Missing')}
          </div>
          ${installBlock}
        </div>`;
      }).join(''));

      renderMcpDiagnostics();
    }

    function renderMcpDiagnostics() {
      const serverEl = $('diagnosticsMcpServer');
      const clientsEl = $('diagnosticsMcpClients');
      if (!serverEl || !clientsEl) return;
      const data = state.mcpStatus;
      if (!data) {
        serverEl.innerHTML = '<div class="empty">Loading MCP diagnostics…</div>';
        clientsEl.innerHTML = '<div class="empty">Scanning clients…</div>';
        return;
      }
      if (!data.success) {
        serverEl.innerHTML = `<div class="empty">${escapeHtml(data.error || 'MCP diagnostics unavailable')}</div>`;
        clientsEl.innerHTML = '';
        return;
      }
      const server = data.server || {};
      const apiOk = !!server.resolve_api_detected;
      const libOk = !!server.resolve_lib_detected;
      const pyOk = !!server.python_path;
      const serverOk = pyOk && apiOk && libOk && !!server.server_path;
      const serverCard = `
        <div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.connection}MCP Server</div>
            ${statusPill(serverOk ? 'pill-ok' : 'pill-warn', serverOk ? 'Ready' : 'Needs setup')}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Version', server.version || '—')}
            ${diagRow('Python', server.python_path || 'Not found', { muted: !server.python_path })}
            ${diagRow('Server script', server.server_path || 'Not found', { muted: !server.server_path })}
          </div>
        </div>`;
      const resolveCard = `
        <div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.project}Resolve scripting paths</div>
            ${statusPill(apiOk && libOk ? 'pill-ok' : 'pill-warn', apiOk && libOk ? 'Detected' : 'Missing')}
          </div>
          <div class="diag-card-rows">
            ${diagRow('API path', server.resolve_api_path || 'Not detected — open Resolve once', { muted: !apiOk })}
            ${diagRow('Library', server.resolve_lib_path || 'Not detected', { muted: !libOk })}
          </div>
          <div class="diag-card-footer">
            <span>${apiOk && libOk ? 'Auto-detected from standard install paths' : 'Install via install.py if paths cannot be detected'}</span>
          </div>
        </div>`;
      const tr = data.transport || { networked: false, mode: 'stdio (local)' };
      const trPill = tr.networked
        ? (tr.loopback ? statusPill('pill-ok', 'Networked · loopback')
                       : statusPill('pill-warn', 'Networked · EXPOSED'))
        : statusPill('pill-ok', 'Local (stdio)');
      const transportCard = `
        <div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.connection}Transport</div>
            ${trPill}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Mode', tr.mode || 'stdio (local)')}
            ${tr.networked ? diagRow('URL', tr.url || '—') : ''}
            ${tr.networked ? diagRow('Auth', tr.has_token ? 'Bearer token required' : 'NONE') : ''}
            ${tr.networked && tr.token ? diagRow('Token', tr.token) : ''}
          </div>
          <div class="diag-card-footer">
            <span>${tr.networked
              ? (tr.loopback ? 'Reachable on this machine only; every request needs the bearer token.'
                             : 'WARNING: bound to a non-loopback host — exposed on the network.')
              : 'Default. Networked access is opt-in (launch with --transport sse|streamable-http).'}</span>
            <button class="secondary transport-toggle-btn" data-transport-action="${tr.networked ? 'stop' : 'start'}">
              ${tr.networked ? 'Stop networked' : 'Start networked'}</button>
          </div>
        </div>`;
      setHtml('diagnosticsMcpServer', serverCard + resolveCard + transportCard);
      serverEl.querySelectorAll('.transport-toggle-btn').forEach(btn => {
        btn.addEventListener('click', () => toggleTransport(btn.dataset.transportAction, btn).catch(alertError));
      });

      const clients = data.clients || [];
      if (!clients.length) {
        clientsEl.innerHTML = '<div class="empty">No client registry loaded.</div>';
        return;
      }
      clientsEl.innerHTML = clients.map(client => {
        let tone = 'pill-mute';
        let pillLabel = 'Not configured';
        if (!client.available) { tone = 'pill-mute'; pillLabel = 'Unavailable here'; }
        else if (client.installed) { tone = 'pill-ok'; pillLabel = 'Installed'; }
        else { tone = 'pill-warn'; pillLabel = 'Not configured'; }
        const canInstall = !!client.available && serverOk;
        const canRemove = !!client.available && !!client.installed;
        return `<div class="diag-card" data-client-id="${escapeAttribute(client.id)}">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.database}${escapeHtml(client.name)}</div>
            ${statusPill(tone, pillLabel)}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Notes', client.notes || '—', { muted: !client.notes })}
            ${diagRow('Config', client.config_path || 'Not available on this OS', { muted: !client.available })}
          </div>
          <div class="diag-card-footer">
            <span style="color: var(--text-tertiary)">${client.available ? '' : 'Skipped'}</span>
            <span class="controls">
              <button class="secondary mcp-install-btn" data-client-id="${escapeAttribute(client.id)}" ${canInstall ? '' : 'disabled'}>${client.installed ? 'Reinstall' : 'Install'}</button>
              <button class="secondary mcp-remove-btn" data-client-id="${escapeAttribute(client.id)}" ${canRemove ? '' : 'disabled'}>Remove</button>
            </span>
          </div>
        </div>`;
      }).join('');

      clientsEl.querySelectorAll('.mcp-install-btn').forEach(btn => {
        btn.addEventListener('click', () => mcpInstall(btn.dataset.clientId, btn).catch(alertError));
      });
      clientsEl.querySelectorAll('.mcp-remove-btn').forEach(btn => {
        btn.addEventListener('click', () => mcpUninstall(btn.dataset.clientId, btn).catch(alertError));
      });
    }

    async function refreshMcpStatus() {
      try {
        const payload = await api('/api/mcp/status');
        state.mcpStatus = payload || null;
      } catch (error) {
        state.mcpStatus = { success: false, error: error?.message || String(error) };
      }
      // renderDiagnostics() rebuilds tool chips (whose Ask dropdowns read
      // mcpStatus at chip-render time) and internally calls
      // renderMcpDiagnostics() for the server+clients cards.
      renderDiagnostics();
      renderAnalyzeMenu();
    }

    async function mcpInstall(clientId, btn) {
      if (!clientId) return;
      const original = btn?.textContent;
      if (btn) { btn.disabled = true; btn.textContent = 'Installing…'; }
      setText('mcpInstallStatus', '');
      try {
        const result = await api('/api/mcp/install', { method: 'POST', body: JSON.stringify({ client_id: clientId }) });
        if (result.success) {
          setText('mcpInstallStatus', `Installed: ${result.message || clientId}. Restart the client to pick up the new server.`);
        } else {
          setText('mcpInstallStatus', `Install failed (${clientId}): ${result.error || 'unknown error'}`);
        }
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = original || 'Install'; }
        await refreshMcpStatus();
      }
    }

    async function mcpUninstall(clientId, btn) {
      if (!clientId) return;
      const proceed = await brandedConfirm({
        kicker: 'MCP Client',
        title: `Remove davinci-resolve from ${clientId}?`,
        body: `This removes the managed entry from the client's MCP config file. Other MCP servers in the same file are preserved.`,
        confirmLabel: 'Remove',
        cancelLabel: 'Keep',
        tone: 'danger',
      });
      if (!proceed) return;
      const original = btn?.textContent;
      if (btn) { btn.disabled = true; btn.textContent = 'Removing…'; }
      setText('mcpInstallStatus', '');
      try {
        const result = await api('/api/mcp/uninstall', { method: 'POST', body: JSON.stringify({ client_id: clientId }) });
        setText('mcpInstallStatus', result.success ? (result.message || `Removed from ${clientId}.`) : `Remove failed (${clientId}): ${result.error || 'unknown error'}`);
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = original || 'Remove'; }
        await refreshMcpStatus();
      }
    }

    async function toggleTransport(action, btn) {
      if (action === 'start') {
        const proceed = await brandedConfirm({
          kicker: 'MCP Transport',
          title: 'Start networked transport?',
          body: 'Starts a second MCP server instance over streamable-http, bound to loopback (127.0.0.1) and protected by a bearer token. Local stdio is unaffected. The connection URL + token will appear here.',
          confirmLabel: 'Start',
          cancelLabel: 'Cancel',
        });
        if (!proceed) return;
      }
      const original = btn?.textContent;
      if (btn) { btn.disabled = true; btn.textContent = action === 'start' ? 'Starting…' : 'Stopping…'; }
      try {
        const ep = action === 'start' ? '/api/mcp/transport/start' : '/api/mcp/transport/stop';
        await api(ep, { method: 'POST', body: '{}' });
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = original; }
        await refreshMcpStatus();
      }
    }

    function renderControlPanels() {
      renderOverview();
      renderDiagnostics();
      renderProjects();
      refreshRecentRootsDropdown();
    }

    function refreshRecentRootsDropdown() {
      const roots = state.projects?.related_project_roots || state.boot?.related_project_roots || [];
      document.querySelectorAll('.path-recent').forEach(select => {
        const target = select.dataset.recentTarget;
        const currentValue = $(target)?.value || '';
        const options = ['<option value="">Recent project roots…</option>']
          .concat((roots || []).map(root => `<option value="${escapeHtml(root)}"${root === currentValue ? ' selected' : ''}>${escapeHtml(root)}</option>`));
        select.innerHTML = options.join('');
      });
    }

    function setAnalyzeClientButtonsEnabled(enabled) {
      document.querySelectorAll('[data-analyze-client]').forEach(b => {
        b.disabled = !enabled;
      });
    }

    function renderResolveMedia(payload) {
      const body = $('resolveMediaBody');
      const project = $('resolveProject');
      const selectBtn = $('selectReadyMediaBtn');
      const analyzeBtn = $('mediaAnalyzeMenuBtn');
      const copyBtn = $('copyPromptFromMediaBtn');
      state.resolveMedia = payload;
      selectBtn.disabled = true;
      analyzeBtn.disabled = true;
      copyBtn.disabled = true;
      setAnalyzeClientButtonsEnabled(false);

      if (!payload?.resolve_available) {
        project.textContent = payload?.status || 'Resolve unavailable';
        body.className = 'empty';
        body.textContent = payload?.error || 'Open a Resolve project to see media pool availability.';
        updateMediaPollStatus();
        renderControlPanels();
        return;
      }

      const allClips = payload.clips || [];
      refreshMediaFacetDropdowns(allClips);
      const clips = filteredResolveClips(allClips);
      const projectLabel = payload.project?.name || 'Current Resolve project';
      const visibleCounts = summarizeVisibleClips(clips);
      project.textContent = `${projectLabel} · ${clipLabel(clips.length)}`;
      const hasAnalyzableClips = clips.some(clip => clip.analyzable);
      selectBtn.disabled = !hasAnalyzableClips;
      analyzeBtn.disabled = !hasAnalyzableClips;
      copyBtn.disabled = !hasAnalyzableClips;
      setAnalyzeClientButtonsEnabled(hasAnalyzableClips);
      if (!allClips.length) {
        body.className = 'empty';
        body.innerHTML = chatPromptCard(
          'The Media Pool has no source clips yet. Import media in Resolve, then ask your assistant to inventory and analyze it:',
          'Look at my current Resolve project, inventory the media, and analyze the source clips.'
        );
        updateMediaPollStatus();
        renderControlPanels();
        return;
      }
      body.className = '';
      const rows = clips.map((clip, index) => {
        // The server normalizes 'succeeded'/'skipped' → 'analyzed' whenever the
        // report exists on disk. If we still see 'succeeded' or 'skipped' here,
        // the report path didn't resolve, so render the raw value verbatim.
        const analysisStatus = clip.analysis_status || 'not analyzed';
        const jobStatus = clip.job_status || '';
        const analysisTitle = jobStatus && jobStatus !== analysisStatus
          ? `Job state: ${jobStatus}`
          : '';
        const readyLabel = clip.analyzable ? 'analyzable' : 'not analyzable';
        const clipId = clip.clip_id || '';
        const checked = clipId && (state.selectedClipIds.has(clipId) || (!state.clipSelectionTouched && clip.analyzable));
        const disabled = !clip.analyzable || !clipId;
        return `<tr>
          <td>${index + 1}</td>
          <td><input class="clip-select" type="checkbox" data-clip-id="${escapeAttribute(clipId)}"${checked ? ' checked' : ''}${disabled ? ' disabled' : ''}></td>
          <td>
            <b>${escapeHtml(clip.clip_name || 'Untitled')}</b>
            <div class="media-path">${escapeHtml(clip.bin_path || '')}</div>
          </td>
          <td>
            <span class="status-cell"><span class="status-dot ${cssToken(readyLabel)}"></span>${escapeHtml(readyLabel)}</span>
            <div class="media-path">${escapeHtml(clip.analyzable_reason || '')}</div>
          </td>
          <td><span class="status-cell"><span class="status-dot ${cssToken(clip.status || 'unknown')}"></span>${escapeHtml(clip.status || 'unknown')}</span></td>
          <td${analysisTitle ? ` title="${escapeAttribute(analysisTitle)}"` : ''}><span class="status-cell"><span class="status-dot ${cssToken(analysisStatus)}"></span>${escapeHtml(analysisStatus)}</span></td>
          <td class="media-path">${escapeHtml(clip.file_path || 'No file path exposed')}</td>
        </tr>`;
      }).join('');
      body.innerHTML = `
        <div class="media-summary">
          <div class="media-stat"><b>${visibleCounts.clips}</b><span>${visibleCounts.clips === 1 ? 'clip' : 'clips'}</span></div>
          <div class="media-stat"><b>${visibleCounts.online}</b><span>online</span></div>
          <div class="media-stat"><b>${visibleCounts.missing}</b><span>missing</span></div>
          <div class="media-stat"><b>${visibleCounts.analyzed}</b><span>analyzed</span></div>
        </div>
        ${payload.truncated ? `<div class="empty" style="margin-bottom:12px">Showing first ${allClips.length} Resolve records before clip filtering. Use analysis jobs for full long-form progress.</div>` : ''}
        <div class="media-table-wrap">
          <table>
            <thead><tr><th>#</th><th></th><th>Clip</th><th>Ready</th><th>Media</th><th>Analysis</th><th>Path</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="7">No clips match the current filters.</td></tr>'}</tbody>
          </table>
        </div>`;
      body.querySelectorAll('[data-clip-id]').forEach(input => {
        input.addEventListener('change', () => {
          if (input.checked) {
            state.selectedClipIds.add(input.dataset.clipId);
          } else {
            state.selectedClipIds.delete(input.dataset.clipId);
          }
          state.clipSelectionTouched = true;
          updatePromptSummary();
        });
      });
      updateMediaPollStatus();
      updatePromptSummary();
      renderControlPanels();
    }

    function mediaFilterValues() {
      return {
        text: $('mediaFilterText').value.trim().toLowerCase(),
        bin: $('mediaBinFilter')?.value || '',
        mediaType: $('mediaTypeFilter')?.value || '',
        mediaStatus: $('mediaStatusFilter').value,
        analysisStatus: $('analysisStatusFilter').value,
      };
    }

    function filteredResolveClips(clips) {
      const filters = mediaFilterValues();
      return clips.filter(clip => {
        const haystack = [
          clip.clip_name,
          clip.bin_path,
          clip.file_path,
          clip.media_type,
          clip.resolve_status,
          clip.analysis_status,
          clip.analyzable_reason,
        ].map(value => String(value || '').toLowerCase()).join(' ');
        if (filters.text && !haystack.includes(filters.text)) return false;

        if (filters.bin && String(clip.bin_path || '') !== filters.bin) return false;
        if (filters.mediaType && String(clip.media_type || '') !== filters.mediaType) return false;

        const mediaStatus = String(clip.status || 'unknown');
        if (filters.mediaStatus === 'clips' && !clip.source_clip) return false;
        if (filters.mediaStatus === 'analyzable' && !clip.analyzable) return false;
        if (filters.mediaStatus === 'online' && (!clip.source_clip || mediaStatus !== 'online')) return false;
        if (filters.mediaStatus === 'missing' && (!clip.source_clip || !['missing_file', 'offline'].includes(mediaStatus))) return false;

        const analysisStatus = String(clip.analysis_status || 'not analyzed');
        if (filters.analysisStatus === 'not_analyzed' && analysisStatus !== 'not analyzed') return false;
        if (filters.analysisStatus === 'analyzed' && !['analyzed', 'succeeded', 'skipped'].includes(analysisStatus)) return false;
        if (filters.analysisStatus === 'active' && !['queued', 'running', 'pending'].includes(analysisStatus)) return false;
        if (filters.analysisStatus === 'failed' && analysisStatus !== 'failed') return false;
        return true;
      });
    }

    function refreshMediaFacetDropdowns(allClips) {
      const facets = { bins: new Set(), types: new Set() };
      (allClips || []).forEach(clip => {
        if (clip.bin_path) facets.bins.add(String(clip.bin_path));
        if (clip.media_type) facets.types.add(String(clip.media_type));
      });
      const populate = (id, values, placeholder) => {
        const select = $(id);
        if (!select) return;
        const current = select.value;
        const sorted = Array.from(values).sort((a, b) => a.localeCompare(b));
        const options = [`<option value="">${placeholder}</option>`].concat(
          sorted.map(v => `<option value="${escapeAttribute(v)}"${v === current ? ' selected' : ''}>${escapeHtml(v)}</option>`)
        );
        select.innerHTML = options.join('');
        // Preserve current selection if still valid; otherwise reset.
        if (current && !sorted.includes(current)) select.value = '';
      };
      populate('mediaBinFilter', facets.bins, 'All bins');
      populate('mediaTypeFilter', facets.types, 'All types');
    }

    function updateSelectedMediaCounter() {
      const countEl = $('mediaSelectedCount');
      const hintEl = $('mediaSelectedHint');
      if (!countEl || !hintEl) return;
      const candidates = promptCandidateClips();
      const selected = selectedPromptClips();
      const count = selected.length;
      countEl.textContent = `${count} selected`;
      countEl.classList.toggle('pill-info', count > 0);
      countEl.classList.toggle('pill-mute', count === 0);
      if (!candidates.length) {
        hintEl.textContent = 'No analyzable clips in view.';
      } else if (!state.clipSelectionTouched) {
        hintEl.textContent = `Auto: all ${candidates.length} analyzable clip${candidates.length === 1 ? '' : 's'} included.`;
      } else if (count === 0) {
        hintEl.textContent = 'Select clips with the checkboxes to enable Analyze.';
      } else {
        hintEl.textContent = `${count} of ${candidates.length} analyzable clip${candidates.length === 1 ? '' : 's'} chosen.`;
      }
    }

    function summarizeVisibleClips(clips) {
      return clips.reduce((acc, clip) => {
        acc.clips += 1;
        const mediaStatus = String(clip.status || 'unknown');
        const analysisStatus = String(clip.analysis_status || 'not analyzed');
        if (mediaStatus === 'online') acc.online += 1;
        if (['missing_file', 'offline'].includes(mediaStatus)) acc.missing += 1;
        if (['analyzed', 'succeeded', 'skipped'].includes(analysisStatus)) acc.analyzed += 1;
        return acc;
      }, { clips: 0, online: 0, missing: 0, analyzed: 0 });
    }

    function clipLabel(count) {
      return `${count} ${count === 1 ? 'clip' : 'clips'}`;
    }

    async function refreshProjectContexts() {
      const payload = await api('/api/projects');
      state.projects = payload;
      state.activeContext = payload.active || state.activeContext;
      renderProjectContextSelect();
      renderProjects();
      updatePromptSummary();
      renderControlPanels();
    }

    async function refreshAllProjects() {
      setText('projectsUpdated', 'Scanning Resolve project database');
      const payload = await api('/api/projects/all');
      state.allProjects = payload;
      renderProjects();
    }

    function renderProjectContextSelect() {
      const select = $('projectContextSelect');
      if (!select) return;
      const contexts = (state.projects?.contexts || [])
        .filter(context => context.active || context.resolve_current);
      const activeRoot = state.activeContext?.project_root;
      const options = contexts.map(context => {
        const label = context.project_name || 'Project';
        const selected = context.project_root === activeRoot ? ' selected' : '';
        const disabled = context.can_load_resolve === false ? ' disabled' : '';
        return `<option value="${escapeAttribute(context.project_root)}"${selected}${disabled}>${escapeHtml(label)}</option>`;
      });
      options.push(`<option value="${VIEW_ALL_PROJECTS_VALUE}">View All Projects</option>`);
      if (!contexts.length) {
        options.unshift('<option value="" selected disabled>No open Resolve project</option>');
        select.innerHTML = options.join('');
        select.disabled = false;
        return;
      }
      select.innerHTML = options.join('');
      select.disabled = false;
    }

    function renderProjects() {
      const openContexts = (state.projects?.contexts || []).filter(context => context.active || context.resolve_current);
      const localContexts = (state.projects?.contexts || []).filter(context => context.can_load_resolve === false);
      const allPayload = state.allProjects;
      const allProjects = allPayload?.projects || [];
      const activeName = state.activeContext?.project_name || state.projects?.current_resolve_project?.project_name || 'No project';
      const currentFolder = state.projects?.resolve_projects?.folder || allPayload?.current_folder || 'Current folder pending';
      const database = allPayload?.database || state.projects?.resolve_projects?.database || {};
      const databaseName = database.DbName || database.db_name || database.name || 'Current Resolve database';

      setText('projectsCurrentProject', activeName);
      setText('projectsCurrentFolder', `Folder: ${currentFolder || 'Root'}`);
      setText('projectsOpenCount', String(openContexts.length || (activeName !== 'No project' ? 1 : 0)));
      setText('projectsAllCount', allPayload ? String(allProjects.length) : 'Not scanned');
      setText('projectsDatabaseName', databaseName);
      setText('projectsContextCount', String(localContexts.length));
      if (allPayload) {
        const stamp = new Date().toLocaleTimeString();
        const warning = allPayload.warning ? ` · ${allPayload.warning}` : '';
        setText('projectsUpdated', `Updated ${stamp}${warning}`);
      }

      const body = $('allProjectsBody');
      if (!body) return;
      if (!allPayload) {
        body.className = 'empty';
        body.textContent = 'Open Projects to scan the current Resolve database.';
        return;
      }
      if (!allPayload.available) {
        body.className = 'empty';
        body.textContent = allPayload.error || 'Resolve project database unavailable.';
        return;
      }
      const filter = String($('projectFilterText')?.value || '').trim().toLowerCase();
      const rows = allProjects
        .filter(project => {
          if (!filter) return true;
          return [project.project_name, project.folder_label, project.database_label]
            .map(value => String(value || '').toLowerCase())
            .join(' ')
            .includes(filter);
        })
        .map(project => {
          const active = project.active ? '<span class="badge ready">active</span>' : '';
          const folderPath = escapeAttribute(JSON.stringify(project.folder_path || []));
          const disabled = project.active ? ' disabled' : '';
          return `<tr>
            <td><b>${escapeHtml(project.project_name || 'Untitled')}</b><div class="media-path">${escapeHtml(project.project_directory || '')}</div></td>
            <td>${escapeHtml(project.folder_label || 'Root')}</td>
            <td>${active || '<span class="badge">available</span>'}</td>
            <td><button class="secondary" data-load-db-project="${escapeAttribute(project.project_name || '')}" data-project-folder="${folderPath}"${disabled}>Load</button></td>
          </tr>`;
        }).join('');
      body.className = '';
      body.innerHTML = `
        <div class="media-table-wrap">
          <table>
            <thead><tr><th>Project</th><th>Folder</th><th>Status</th><th></th></tr></thead>
            <tbody>${rows || '<tr><td colspan="4">No projects match the current filter.</td></tr>'}</tbody>
          </table>
        </div>`;
      body.querySelectorAll('[data-load-db-project]').forEach(button => {
        button.addEventListener('click', () => {
          const folderPath = JSON.parse(button.dataset.projectFolder || '[]');
          loadProjectFromDatabase(button.dataset.loadDbProject, folderPath).catch(alertError);
        });
      });
    }

    function restoreProjectContextSelect() {
      const select = $('projectContextSelect');
      const currentRoot = state.activeContext?.project_root;
      if (!select) return;
      select.value = currentRoot || '';
      if (select.value !== (currentRoot || '')) select.selectedIndex = 0;
    }

    // ─── Brand-styled confirm dialog ────────────────────────────────────
    // Drop-in for window.confirm(). Returns a Promise<boolean>. Falls back to
    // the native dialog if the modal DOM is somehow missing.
    let _confirmModalCleanup = null;
    function brandedConfirm(opts = {}) {
      const {
        title = 'Are you sure?',
        body = '',
        detail = '',
        kicker = 'Confirm',
        confirmLabel = 'Confirm',
        cancelLabel = 'Cancel',
        tone = 'default', // 'default' | 'danger' | 'brand'
      } = opts;
      const modal = $('confirmModal');
      const cancel = $('confirmModalCancel');
      const confirm = $('confirmModalConfirm');
      if (!modal || !cancel || !confirm) {
        return Promise.resolve(window.confirm(`${title}\n\n${body}`));
      }
      // Tear down any previous instance so we never end up with stacked listeners.
      if (_confirmModalCleanup) _confirmModalCleanup(false);
      setText('confirmModalKicker', kicker);
      setText('confirmModalTitle', title);
      setText('confirmModalBody', body);
      setText('confirmModalDetail', detail);
      confirm.textContent = confirmLabel;
      cancel.textContent = cancelLabel;
      confirm.classList.toggle('danger', tone === 'danger');
      modal.classList.add('open');
      // Wait a microtask so transitions can apply before focus shift.
      requestAnimationFrame(() => confirm.focus());
      return new Promise(resolve => {
        const finish = (value) => {
          modal.classList.remove('open');
          cancel.removeEventListener('click', onCancel);
          confirm.removeEventListener('click', onConfirm);
          modal.removeEventListener('click', onBackdrop);
          document.removeEventListener('keydown', onKeydown);
          _confirmModalCleanup = null;
          resolve(value);
        };
        _confirmModalCleanup = finish;
        const onCancel = () => finish(false);
        const onConfirm = () => finish(true);
        const onBackdrop = (event) => { if (event.target === modal) finish(false); };
        const onKeydown = (event) => {
          if (event.key === 'Escape') { event.preventDefault(); finish(false); }
          else if (event.key === 'Enter' && !event.shiftKey) {
            // Don't swallow Enter when focus is inside a textarea or contenteditable.
            const tag = document.activeElement?.tagName;
            const editable = tag === 'TEXTAREA' || document.activeElement?.isContentEditable;
            if (editable) return;
            event.preventDefault();
            finish(true);
          }
        };
        cancel.addEventListener('click', onCancel);
        confirm.addEventListener('click', onConfirm);
        modal.addEventListener('click', onBackdrop);
        document.addEventListener('keydown', onKeydown);
      });
    }

    function projectSwitchDialog(currentName, nextName) {
      const modal = $('projectSwitchModal');
      const title = $('projectSwitchTitle');
      const body = $('projectSwitchBody');
      const detail = $('projectSwitchDetail');
      const cancel = $('projectSwitchCancel');
      const confirm = $('projectSwitchConfirm');
      if (!modal || !cancel || !confirm) {
        return Promise.resolve(window.confirm(`Load "${nextName}" in DaVinci Resolve?`));
      }
      if (state.projectDialogCleanup) state.projectDialogCleanup(false);
      title.textContent = `Load "${nextName}" in DaVinci Resolve?`;
      body.textContent = `This will change the open Resolve project from "${currentName}" to "${nextName}" and make it the active control panel project.`;
      detail.textContent = 'Search, jobs, logs, diagnostics, clip inventory, and index status will refresh for the selected project.';
      modal.classList.add('open');
      confirm.focus();
      return new Promise(resolve => {
        const finish = value => {
          modal.classList.remove('open');
          cancel.removeEventListener('click', onCancel);
          confirm.removeEventListener('click', onConfirm);
          modal.removeEventListener('click', onBackdrop);
          document.removeEventListener('keydown', onKeydown);
          state.projectDialogCleanup = null;
          resolve(value);
        };
        const onCancel = () => finish(false);
        const onConfirm = () => finish(true);
        const onBackdrop = event => {
          if (event.target === modal) finish(false);
        };
        const onKeydown = event => {
          if (event.key === 'Escape') finish(false);
        };
        state.projectDialogCleanup = finish;
        cancel.addEventListener('click', onCancel);
        confirm.addEventListener('click', onConfirm);
        modal.addEventListener('click', onBackdrop);
        document.addEventListener('keydown', onKeydown);
      });
    }

    async function switchProjectContext(projectRoot) {
      if (!projectRoot) return;
      const select = $('projectContextSelect');
      const currentRoot = state.activeContext?.project_root;
      if (projectRoot === currentRoot) {
        restoreProjectContextSelect();
        return;
      }
      const context = (state.projects?.contexts || []).find(item => item.project_root === projectRoot);
      if (context?.can_load_resolve === false) {
        restoreProjectContextSelect();
        throw new Error(`${context.project_name || 'This project'} is a local analysis context only and cannot be loaded in Resolve.`);
      }
      const currentName = state.activeContext?.project_name || 'current project';
      const nextName = context?.project_name || 'selected project';
      const confirmed = await projectSwitchDialog(currentName, nextName);
      if (!confirmed) {
        restoreProjectContextSelect();
        return;
      }
      if (select) select.disabled = true;
      let payload;
      try {
        payload = await api('/api/context', {
          method: 'POST',
          body: JSON.stringify({
            project_root: projectRoot,
            project_name: context?.project_name,
            project_id: context?.project_id,
            resolve_project_name: context?.resolve_project_name || context?.project_name,
            load_resolve_project: true,
          }),
        });
      } catch (error) {
        restoreProjectContextSelect();
        throw error;
      } finally {
        if (select) select.disabled = false;
      }
      state.activeContext = payload.active;
      state.projects = payload.projects;
      state.selectedClipIds.clear();
      state.clipSelectionTouched = false;
      renderProjectContextSelect();
      await refreshIndex();
      await refreshResolveMedia();
      updatePromptSummary();
      renderControlPanels();
    }

    async function loadProjectFromDatabase(projectName, folderPath = []) {
      const targetName = String(projectName || '').trim();
      if (!targetName) return;
      const currentName = state.activeContext?.project_name || 'current project';
      const confirmed = await projectSwitchDialog(currentName, targetName);
      if (!confirmed) return;
      const payload = await api('/api/context', {
        method: 'POST',
        body: JSON.stringify({
          project_name: targetName,
          resolve_project_name: targetName,
          resolve_project_folder_path: folderPath,
          load_resolve_project: true,
        }),
      });
      state.activeContext = payload.active;
      state.projects = payload.projects;
      state.selectedClipIds.clear();
      state.clipSelectionTouched = false;
      renderProjectContextSelect();
      await refreshIndex();
      await refreshResolveMedia();
      if (state.allProjects) await refreshAllProjects();
      updatePromptSummary();
      renderControlPanels();
    }

    async function boot() {
      state.boot = await api('/api/boot');
      state.activeContext = state.boot.active_context || {
        project_name: state.boot.project_name,
        project_id: state.boot.project_id,
        project_root: state.boot.project_root,
        base_root: state.boot.output_root?.base_root,
      };
      const prefs = readPreferences();
      syncPreferencesPanel();
      applyPreferencesToControls(prefs);
      renderVersionBadge();
      // Semantic search rides on a local text-embedding backend; only show
      // the toggle when one is detected (ollama nomic-embed-text or
      // sentence-transformers).
      if (state.boot?.capabilities?.embeddings?.text?.available) {
        const toggle = $('reviewSemanticToggle');
        if (toggle) toggle.style.display = '';
      }
      // Paint the previous inventory immediately (stale) so a slow first
      // /api/resolve/media — common with network source media — doesn't leave the
      // panel blank. The live fetch below replaces it and clears the stale flag.
      const cachedInventory = loadInventorySnapshot();
      if (cachedInventory) {
        state.resolveMediaStale = true;
        renderResolveMedia(cachedInventory);
      }
      await refreshProjectContexts();
      renderControlPanels();
      await refreshIndex();
      await refreshResolveMedia();
      scheduleMediaPoll();
      refreshUpdateStatus().catch(() => {});
      refreshMcpStatus().catch(() => {});
    }

    function renderVersionBadge() {
      const numberEl = $('versionNumber');
      const badge = $('versionBadge');
      const current = state.updateStatus?.current_version || state.boot?.mcp_version;
      if (numberEl && current) numberEl.textContent = current;
      if (!badge) return;
      const hasUpdate = !!state.updateStatus?.update_available;
      badge.classList.toggle('has-update', hasUpdate);
      const latest = state.updateStatus?.latest_version;
      badge.title = hasUpdate && latest
        ? `Update available: ${current} → ${latest}`
        : `MCP ${current || ''} · click for details`;
    }

    async function refreshUpdateStatus({ force = false } = {}) {
      try {
        const payload = await api(`/api/update/status${force ? '?force=1' : ''}`);
        state.updateStatus = payload || null;
        renderVersionBadge();
      } catch (error) {
        console.warn('Update check failed', error);
      }
    }

    function openUpdateModal() {
      const modal = $('updateModal');
      if (!modal) return;
      const current = state.updateStatus?.current_version || state.boot?.mcp_version || 'unknown';
      const latest = state.updateStatus?.latest_version;
      const hasUpdate = !!state.updateStatus?.update_available;
      const status = String(state.updateStatus?.status || 'unknown');
      setText('updateModalKicker', hasUpdate ? 'Update Available' : 'MCP Version');
      setText('updateModalTitle', hasUpdate ? `Update to ${latest}` : `DaVinci Resolve MCP ${current}`);
      if (hasUpdate) {
        setText('updateModalBody', `You're on ${current}. ${latest} is the latest release. Run the command below in your shell to upgrade, then restart Resolve.`);
      } else if (status === 'up_to_date') {
        setText('updateModalBody', `You're on ${current}, the latest release. The dashboard checks for updates periodically.`);
      } else if (status === 'disabled') {
        setText('updateModalBody', `Update checks are disabled. Current version: ${current}.`);
      } else {
        setText('updateModalBody', `Current version: ${current}. The update check hasn't run yet, or hasn't been able to reach GitHub.`);
      }
      const checkedAt = state.updateStatus?.checked_at;
      setText('updateModalDetail', checkedAt ? `Last checked: ${checkedAt}` : '');
      const cmdWrap = $('updateModalCommand');
      const cmdText = $('updateModalCommandText');
      const copyBtn = $('updateModalCopy');
      const applyBtn = $('updateModalApply');
      const releaseLink = $('updateModalReleaseLink');
      const command = 'cd ' + (state.boot?.repo_root || '.') + ' && git pull --ff-only';
      if (hasUpdate) {
        cmdWrap.style.display = '';
        cmdText.textContent = command;
        copyBtn.style.display = '';
        applyBtn.style.display = '';
        applyBtn.disabled = false;
        applyBtn.textContent = 'Update Now';
      } else {
        cmdWrap.style.display = 'none';
        copyBtn.style.display = 'none';
        applyBtn.style.display = 'none';
      }
      if (state.updateStatus?.release_url) {
        releaseLink.href = state.updateStatus.release_url;
        releaseLink.style.display = '';
      } else if (hasUpdate) {
        releaseLink.href = 'https://github.com/samuelgursky/davinci-resolve-mcp/releases';
        releaseLink.style.display = '';
      } else {
        releaseLink.style.display = 'none';
      }
      copyBtn.onclick = async () => {
        try { await navigator.clipboard.writeText(command); copyBtn.textContent = 'Copied!'; setTimeout(() => { copyBtn.textContent = 'Copy Command'; }, 1200); }
        catch { window.prompt('Copy this command', command); }
      };
      applyBtn.onclick = async () => {
        const proceed = await brandedConfirm({
          kicker: 'MCP Update',
          title: 'Apply the update now?',
          body: 'Runs git pull --ff-only against the MCP repository.',
          detail: 'You’ll need to restart the MCP server (and DaVinci Resolve) for the new code to take effect.',
          confirmLabel: 'Update Now',
        });
        if (!proceed) return;
        applyBtn.disabled = true;
        applyBtn.textContent = 'Updating…';
        try {
          const result = await api('/api/update/apply', { method: 'POST' });
          if (result.success) {
            const detail = [];
            if (result.changed) detail.push('Update applied.');
            else detail.push('Already up to date.');
            if (result.message) detail.push(result.message);
            if (result.restart_required) detail.push('Restart the MCP server (and Resolve) to use the new code.');
            setText('updateModalDetail', detail.join(' '));
            applyBtn.textContent = result.changed ? 'Restart Required' : 'Up to Date';
            applyBtn.disabled = true;
            await refreshUpdateStatus({ force: true });
          } else {
            const reason = result.reason ? ` (${result.reason})` : '';
            setText('updateModalDetail', `Update failed${reason}: ${result.message || result.error || 'unknown error'}`);
            applyBtn.disabled = false;
            applyBtn.textContent = 'Update Now';
          }
        } catch (error) {
          setText('updateModalDetail', `Update failed: ${error?.message || error}`);
          applyBtn.disabled = false;
          applyBtn.textContent = 'Update Now';
        }
      };
      modal.classList.add('open');
    }

    function closeUpdateModal() {
      $('updateModal')?.classList.remove('open');
    }

    async function refreshResolveMedia(options = {}) {
      if (state.mediaRefreshing) return;
      state.mediaRefreshing = true;
      updateMediaPollStatus('refreshing');
      try {
        // Background polls reuse the cached Resolve walk and skip the network FS
        // probe (the server re-applies only the local analysis overlay); manual /
        // first loads do a full Media Pool walk with a fresh probe. The ETag lets
        // an unchanged poll short-circuit to 304 and skip the table re-render.
        const query = options.silent ? '&probe=0&reuse=1' : '';
        const headers = {};
        if (state.mediaETag) headers['If-None-Match'] = state.mediaETag;
        const res = await fetch(`/api/resolve/media?limit=500${query}`, { headers, cache: 'no-store' });
        state.mediaLastRefresh = new Date();
        state.resolveMediaStale = false;
        if (res.status === 304) return;
        const payload = await res.json();
        if (payload && payload.unchanged) return;
        if (!res.ok || payload.success === false) {
          throw new Error(payload.error || res.statusText);
        }
        state.mediaETag = res.headers.get('ETag') || state.mediaETag;
        renderResolveMedia(payload);
        saveInventorySnapshot(payload);
      } finally {
        state.mediaRefreshing = false;
        updateMediaPollStatus();
      }
    }

    // Persist the last good inventory so reopening the dashboard paints the
    // previous snapshot instantly (with a "refreshing" hint) instead of sitting
    // on "connection pending" until the first fetch returns.
    function inventorySnapshotKey() {
      return 'resolveMcpInventory:' + (state.activeContext?.project_root || state.boot?.project_root || state.boot?.project_name || 'default');
    }
    function saveInventorySnapshot(payload) {
      if (!payload?.resolve_available) return;
      try {
        localStorage.setItem(inventorySnapshotKey(), JSON.stringify({ saved_at: Date.now(), payload }));
      } catch (error) {
        // Quota or serialization failure is non-fatal — the snapshot is a nicety.
        console.warn('Could not cache inventory snapshot', error);
      }
    }
    function loadInventorySnapshot() {
      try {
        const raw = localStorage.getItem(inventorySnapshotKey());
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return parsed?.payload?.resolve_available ? parsed.payload : null;
      } catch (error) {
        return null;
      }
    }

    function promptCandidateClips() {
      return filteredResolveClips(state.resolveMedia?.clips || [])
        .filter(clip => clip.source_clip && clip.analyzable && clip.clip_id);
    }

    function selectedPromptClips() {
      const candidates = promptCandidateClips();
      if (!state.clipSelectionTouched) {
        return candidates;
      }
      const selected = candidates.filter(clip => state.selectedClipIds.has(clip.clip_id));
      return selected;
    }

    function selectReadyMedia() {
      promptCandidateClips().forEach(clip => state.selectedClipIds.add(clip.clip_id));
      state.clipSelectionTouched = true;
      rerenderResolveMedia();
      updatePromptSummary();
    }

    function updatePromptSummary() {
      // Prompt-composer summary surfaces were removed with the Batch Jobs page.
      // Selected-count UI on the Analyze action bar replaces them.
      updateSelectedMediaCounter();
    }

    function promptPayload() {
      const clips = selectedPromptClips();
      if (!clips.length) {
        throw new Error('No analyzable Resolve clips are selected or visible.');
      }
      const media = state.setupDefaults?.media_analysis || {};
      const transcriptionDefault = String(media.transcription_default || 'yes').toLowerCase();
      const transcriptionEnabled = transcriptionDefault !== 'no';
      const params = {
        name: 'Editorial analysis pass',
        target: {
          type: 'clips',
          clip_ids: clips.map(clip => clip.clip_id),
        },
        depth: media.default_depth || 'standard',
        analysis_root: state.activeContext?.base_root || state.boot?.output_root?.base_root,
        project_name: state.activeContext?.project_name,
        project_id: state.activeContext?.project_id,
        vision: { enabled: true, provider: 'host_chat_paths' },
        transcription: transcriptionEnabled
          ? { enabled: true, allow_model_download: true }
          : { enabled: false },
        reuse_project_roots: state.projects?.related_project_roots || state.boot?.related_project_roots || [],
      };
      const frames = Number(media.default_sample_frames);
      if (Number.isFinite(frames) && frames > 0) {
        params.max_analysis_frames = Math.max(0, Math.min(48, frames));
      }
      if (media.source_trust && media.source_trust !== 'auto') {
        params.source_trust = media.source_trust;
      }
      return params;
    }

    function buildMcpPrompt() {
      const params = promptPayload();
      const sliceParams = {
        job_id: '<job_id>',
        max_clips: 1,
        analysis_root: params.analysis_root,
        project_name: params.project_name,
        project_id: params.project_id,
      };
      const statusParams = {
        job_id: '<job_id>',
        analysis_root: params.analysis_root,
        project_name: params.project_name,
        project_id: params.project_id,
      };
      return [
        'Please start a source-safe DaVinci Resolve MCP analysis batch for these Resolve Media Pool clips, then run one bounded slice at a time until complete.',
        '',
        'Use this tool call first:',
        `media_analysis(action="start_batch_job", params=${JSON.stringify(params, null, 2)})`,
        '',
        'After it returns a job_id, continue with:',
        `media_analysis(action="run_batch_job_slice", params=${JSON.stringify(sliceParams, null, 2)})`,
        '',
        'Check progress with:',
        `media_analysis(action="batch_job_status", params=${JSON.stringify(statusParams, null, 2)})`,
        '',
        'Keep running slices until batch_job_status reports completed or completed_with_errors. After each clip completes, the host chat reads the deferred vision payload and calls media_analysis(action="commit_vision", ...) to finalize. Keep source media read-only.',
      ].join('\n');
    }

    async function writePromptToClipboard(prompt, options = {}) {
      const showFallback = options.showFallback !== false;
      try {
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard API unavailable');
        await navigator.clipboard.writeText(prompt);
        return true;
      } catch {
        if (showFallback) window.prompt('Copy this MCP prompt', prompt);
        return false;
      }
    }

    function chatPromptCard(message, prompt) {
      return `<div class="empty" style="padding:var(--space-3);border:1px dashed var(--border-default);border-radius:var(--radius-md);display:grid;gap:8px;justify-items:start;text-align:left;">
        <span>${escapeHtml(message)}</span>
        <code style="font-size:12px;color:var(--text-secondary);white-space:normal;">\u201c${escapeHtml(prompt)}\u201d</code>
        <button class="secondary" type="button" data-copy-chat-prompt="${escapeHtml(prompt)}">Copy prompt</button>
      </div>`;
    }
    document.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-copy-chat-prompt]');
      if (!btn) return;
      const ok = await writePromptToClipboard(btn.dataset.copyChatPrompt);
      btn.textContent = ok ? 'Copied \u2014 paste in your chat session' : 'Copy prompt';
      setTimeout(() => { btn.textContent = 'Copy prompt'; }, 2600);
    });

    async function copyMcpPrompt() {
      const prompt = buildMcpPrompt();
      await writePromptToClipboard(prompt);
      setText('copyPromptStatus', 'Copied. Paste in your MCP session to begin.');
    }

    // ─── Analyze-in-client launchers ───────────────────────────────────
    // Three tiers:
    //   prefill  → URL scheme accepts the prompt directly (Claude Desktop, Codex)
    //   launch   → URL scheme opens the app at the project path; user pastes prompt
    //   backend  → server shells out to launch the app (e.g. Terminal for claude CLI)
    //   extension→ host editor opens (VS Code); user pastes into the extension panel
    const CLIENT_LAUNCHERS = {
      'claude-desktop': {
        label: 'Claude Desktop',
        tier: 'prefill',
        url(prompt) {
          const u = new URL('claude://claude.ai/new');
          // Anthropic truncates q at ~14k chars; clip to stay within the limit.
          u.searchParams.set('q', prompt.length > 14000 ? prompt.slice(0, 14000) : prompt);
          return u.toString();
        },
      },
      'codex': {
        label: 'Codex',
        tier: 'prefill',
        url(prompt, boot) {
          const u = new URL('codex://new');
          u.searchParams.set('prompt', prompt);
          const path = boot?.codex_workspace || boot?.repo_root;
          if (path) u.searchParams.set('path', path);
          return u.toString();
        },
      },
      'claude-code': {
        label: 'Claude Code',
        tier: 'backend',
        backend: '/api/launch/claude-code',
      },
      'cursor': {
        label: 'Cursor',
        tier: 'launch',
        url(_, boot) {
          const p = boot?.repo_root;
          return p ? `cursor://file/${encodeURI(p)}` : null;
        },
      },
      'vscode': {
        label: 'VS Code',
        tier: 'launch',
        url(_, boot) {
          const p = boot?.repo_root;
          return p ? `vscode://file/${encodeURI(p)}` : null;
        },
      },
      'windsurf': {
        label: 'Windsurf',
        tier: 'launch',
        url(_, boot) {
          const p = boot?.repo_root;
          return p ? `windsurf://file/${encodeURI(p)}` : null;
        },
      },
      'zed': {
        label: 'Zed',
        tier: 'launch',
        url(_, boot) {
          const p = boot?.repo_root;
          return p ? `zed://file/${encodeURI(p)}` : null;
        },
      },
      'antigravity': {
        label: 'Antigravity',
        tier: 'launch',
        url(_, boot) {
          const p = boot?.repo_root;
          return p ? `antigravity://file/${encodeURI(p)}` : null;
        },
      },
      'cline': {
        label: 'Cline',
        tier: 'extension',
        host: 'VS Code',
        url(_, boot) {
          const p = boot?.repo_root;
          return p ? `vscode://file/${encodeURI(p)}` : null;
        },
      },
      'roo-code': {
        label: 'Roo Code',
        tier: 'extension',
        host: 'VS Code',
        url(_, boot) {
          const p = boot?.repo_root;
          return p ? `vscode://file/${encodeURI(p)}` : null;
        },
      },
      'continue': {
        label: 'Continue',
        tier: 'extension',
        host: 'VS Code',
        url(_, boot) {
          const p = boot?.repo_root;
          return p ? `vscode://file/${encodeURI(p)}` : null;
        },
      },
    };

    // Group label shown in the action dropdown for each launcher tier.
    const CLIENT_TIER_GROUP = {
      prefill: 'Chat apps',
      backend: 'Code editors',
      launch: 'Code editors',
      extension: 'VS Code extensions',
    };
    const CLIENT_GROUP_ORDER = ['Chat apps', 'Code editors', 'VS Code extensions'];

    // Returns groups of CLIENT_LAUNCHERS entries that are currently installed
    // according to /api/mcp/status. Codex is not in the MCP registry, so it is
    // excluded by this filter — both Ask and Analyze menus only surface
    // configured MCP clients.
    function getInstalledClientGroups() {
      const clients = (state.mcpStatus?.clients || []);
      const installedIds = new Set(clients.filter(c => c && c.installed).map(c => c.id));
      const groups = new Map();
      Object.keys(CLIENT_LAUNCHERS).forEach(id => {
        if (!installedIds.has(id)) return;
        const cfg = CLIENT_LAUNCHERS[id];
        const groupLabel = CLIENT_TIER_GROUP[cfg.tier] || 'Other';
        if (!groups.has(groupLabel)) groups.set(groupLabel, []);
        groups.get(groupLabel).push({ id, label: cfg.label, tier: cfg.tier, host: cfg.host });
      });
      const ordered = [];
      CLIENT_GROUP_ORDER.forEach(label => {
        if (groups.has(label)) ordered.push({ label, items: groups.get(label) });
      });
      groups.forEach((items, label) => {
        if (!CLIENT_GROUP_ORDER.includes(label)) ordered.push({ label, items });
      });
      return ordered;
    }

    // Build dropdown items HTML for either Analyze or Ask menus.
    // mode: 'analyze' uses data-analyze-client (existing enable/disable wiring
    // and event delegation pick it up); 'ask' uses inline onclick that calls
    // installInClient(clientId, toolName).
    function renderClientMenuItems(mode, opts = {}) {
      const groups = getInstalledClientGroups();
      if (!groups.length) {
        return '<div class="action-dropdown-empty">No MCP clients installed — see Setup → MCP Clients.</div>';
      }
      const html = [];
      groups.forEach(({ label, items }) => {
        html.push(`<div class="action-dropdown-label">${escapeHtml(label)}</div>`);
        items.forEach(item => {
          if (mode === 'analyze') {
            html.push(`<button type="button" role="menuitem" data-analyze-client="${escapeAttribute(item.id)}" disabled>Analyze in ${escapeHtml(item.label)}</button>`);
          } else if (mode === 'ask') {
            const toolName = opts.toolName || '';
            html.push(`<button type="button" role="menuitem" onclick="installInClient('${escapeAttribute(item.id)}', '${escapeAttribute(toolName)}').catch(alertError)">Ask ${escapeHtml(item.label)}</button>`);
          }
        });
      });
      return html.join('');
    }

    function renderAnalyzeMenu() {
      const host = document.getElementById('mediaAnalyzeClientItems');
      if (!host) return;
      host.innerHTML = renderClientMenuItems('analyze');
      // Re-apply the current enable state for the freshly rendered buttons.
      // (Mirrors the rule in renderResolveMedia: enabled iff Resolve has at
      // least one analyzable clip.)
      const hasAnalyzableClips = !!state.resolveMedia?.clips?.some(c => c?.analyzable);
      setAnalyzeClientButtonsEnabled(hasAnalyzableClips);
    }

    async function analyzeInClient(clientId) {
      const cfg = CLIENT_LAUNCHERS[clientId];
      if (!cfg) return;
      const prompt = buildMcpPrompt();
      const copyPromise = writePromptToClipboard(prompt, { showFallback: false });
      let launched = false;
      let backendErr = '';
      if (cfg.tier === 'backend' && cfg.backend) {
        try {
          const resp = await api(cfg.backend, { method: 'POST' });
          launched = !!resp?.success;
          if (!launched) backendErr = resp?.error || 'launch failed';
        } catch (err) {
          backendErr = err?.message || String(err);
        }
      }
      if (!launched && typeof cfg.url === 'function') {
        const url = cfg.url(prompt, state.boot);
        if (url) {
          const link = document.createElement('a');
          link.href = url;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          document.body.appendChild(link);
          link.click();
          link.remove();
          launched = true;
        }
      }
      const copied = await copyPromise;
      if (!copied) window.prompt('Copy this MCP prompt', prompt);
      const clipNote = copied ? '' : ' (clipboard failed — copy manually)';
      let msg;
      if (!launched) {
        msg = `Prompt copied${clipNote}. Open ${cfg.label} and paste${backendErr ? ` — ${backendErr}` : ''}.`;
      } else if (cfg.tier === 'prefill') {
        msg = `Opening ${cfg.label} with prompt prefilled${clipNote}.`;
      } else if (cfg.tier === 'backend') {
        msg = `Launching ${cfg.label} in Terminal. Prompt copied${clipNote} — paste when claude is ready.`;
      } else if (cfg.tier === 'extension') {
        msg = `Opening ${cfg.host} at project. Prompt copied${clipNote} — paste into ${cfg.label} chat panel.`;
      } else {
        msg = `Opening ${cfg.label}. Prompt copied${clipNote} — paste when ${cfg.label} loads.`;
      }
      setText('copyPromptStatus', msg);
    }

    // ─── Install missing runtime tools ─────────────────────────────────
    // Mirrors the analyze-in-client flow: builds a self-contained prompt
    // that tells an agent to install the tool, runs `recheck_capabilities`,
    // and reports back. The dashboard never executes installs itself.
    function getToolInstallPlan(toolName) {
      const tool = (state.boot?.capabilities?.tools || {})[toolName] || {};
      return tool.install || null;
    }

    function buildToolInstallPrompt(toolName) {
      const plan = getToolInstallPlan(toolName);
      const platformId = state.boot?.capabilities?.platform?.id || 'unknown';
      const cmd = plan?.command || '(no suggested command — see project docs)';
      const verify = plan?.verify ? `\nVerify with: ${plan.verify}` : '';
      const note = plan?.requirement_note || plan?.notes || '';
      const required = (plan?.required_for || []).join(', ');
      const requiredLine = required ? `\nRequired for: ${required}` : '';
      const noteLine = note ? `\nNote: ${note}` : '';
      const alts = plan?.alternates ? Object.entries(plan.alternates) : [];
      const altLines = alts.length
        ? '\nAlternates for other platforms:\n' + alts.map(([p, c]) => `  - ${p}: ${c}`).join('\n')
        : '';
      return [
        `Please install the runtime helper \`${toolName}\` for the DaVinci Resolve MCP dashboard, then verify it.`,
        '',
        `Platform detected by the server: ${platformId}`,
        `Suggested command: ${cmd}${verify}${requiredLine}${noteLine}${altLines}`,
        '',
        'Steps:',
        '1. Confirm the suggested command is appropriate for this machine. Ask the user before running anything that needs sudo or a fresh Homebrew/pip environment.',
        '2. Run the command in a terminal.',
        '3. Run the verify command (or any equivalent --version / import check) to confirm it works.',
        '4. Call media_analysis(action="recheck_capabilities") and confirm the `tools` map now shows this tool as available.',
        '5. Report back: which command you ran, the verify output, and the recheck result.',
        '',
        'Do not modify source media. Do not skip the recheck step — the dashboard relies on it to update the chip from Missing to Ready.',
      ].join('\n');
    }

    async function copyInstallCommand(toolName) {
      const plan = getToolInstallPlan(toolName);
      const statusEl = document.getElementById('toolStatus_' + cssToken(toolName));
      if (!plan?.command) {
        if (statusEl) statusEl.textContent = 'No suggested command for this platform — see project docs.';
        return;
      }
      const ok = await writePromptToClipboard(plan.command, { showFallback: true });
      if (statusEl) statusEl.textContent = ok ? 'Command copied. Paste into a terminal.' : 'Copy failed — command shown in dialog.';
    }

    async function installInClient(clientId, toolName) {
      const cfg = CLIENT_LAUNCHERS[clientId];
      const statusEl = document.getElementById('toolStatus_' + cssToken(toolName));
      if (!cfg) {
        if (statusEl) statusEl.textContent = `Unknown client "${clientId}".`;
        return;
      }
      const prompt = buildToolInstallPrompt(toolName);
      const copyPromise = writePromptToClipboard(prompt, { showFallback: false });
      let launched = false;
      let backendErr = '';
      if (cfg.tier === 'backend' && cfg.backend) {
        try {
          const resp = await api(cfg.backend, { method: 'POST' });
          launched = !!resp?.success;
          if (!launched) backendErr = resp?.error || 'launch failed';
        } catch (err) {
          backendErr = err?.message || String(err);
        }
      }
      if (!launched && typeof cfg.url === 'function') {
        const url = cfg.url(prompt, state.boot);
        if (url) {
          const link = document.createElement('a');
          link.href = url;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          document.body.appendChild(link);
          link.click();
          link.remove();
          launched = true;
        }
      }
      const copied = await copyPromise;
      if (!copied) window.prompt('Copy this install prompt', prompt);
      const clipNote = copied ? '' : ' (clipboard failed — copy manually)';
      let msg;
      if (!launched) {
        msg = `Prompt copied${clipNote}. Open ${cfg.label} and paste${backendErr ? ` — ${backendErr}` : ''}.`;
      } else if (cfg.tier === 'prefill') {
        msg = `Opening ${cfg.label} with install prompt prefilled${clipNote}.`;
      } else if (cfg.tier === 'backend') {
        msg = `Launching ${cfg.label}. Prompt copied${clipNote} — paste when ready.`;
      } else {
        msg = `Opening ${cfg.label}. Prompt copied${clipNote} — paste when it loads.`;
      }
      if (statusEl) statusEl.textContent = msg;
    }

    async function recheckCapabilities() {
      const setAllStatus = (text) => {
        Object.keys((state.boot?.capabilities?.tools) || {}).forEach(name => {
          const el = document.getElementById('toolStatus_' + cssToken(name));
          if (el) el.textContent = text;
        });
      };
      setAllStatus('Rechecking…');
      try {
        const resp = await api('/api/boot');
        if (resp && resp.success !== false) {
          state.boot = resp;
          renderDiagnostics();
          // After re-render the chip status elements are fresh; surface the diff briefly.
          const newTools = resp.capabilities?.tools || {};
          const flippedReady = Object.keys(newTools).filter(n => newTools[n]?.available).length;
          const total = Object.keys(newTools).length;
          const msg = `Rechecked: ${flippedReady}/${total} tools available.`;
          Object.keys(newTools).forEach(name => {
            const el = document.getElementById('toolStatus_' + cssToken(name));
            if (el) el.textContent = msg;
          });
        } else {
          setAllStatus('Recheck failed.');
        }
      } catch (err) {
        setAllStatus(`Recheck failed: ${err?.message || err}`);
      }
    }

    function scheduleMediaPoll() {
      if (state.mediaPollTimer) {
        clearInterval(state.mediaPollTimer);
        state.mediaPollTimer = null;
      }
      const enabled = $('autoPollMedia').checked;
      const interval = Number($('mediaPollInterval').value || 0);
      if (enabled && interval > 0) {
        state.mediaPollTimer = setInterval(() => {
          if (document.hidden) return;
          refreshResolveMedia({ silent: true }).catch(error => {
            console.warn('Resolve media poll failed', error);
            updateMediaPollStatus(error.message || String(error));
          });
        }, interval);
      }
      updateMediaPollStatus();
    }

    function updateMediaPollStatus(extra = '') {
      const el = $('mediaPollStatus');
      if (!el) return;
      const interval = Number($('mediaPollInterval').value || 0);
      const enabled = $('autoPollMedia').checked && interval > 0;
      const last = state.mediaLastRefresh ? state.mediaLastRefresh.toLocaleTimeString() : 'not yet';
      const poll = enabled ? `polling every ${Math.round(interval / 1000)}s` : 'polling off';
      const visible = state.resolveMedia?.clips ? clipLabel(filteredResolveClips(state.resolveMedia.clips).length) : 'no media snapshot';
      const prefix = state.mediaRefreshing ? 'refreshing' : poll;
      const stale = state.resolveMediaStale ? 'cached · ' : '';
      el.textContent = `${stale}${prefix} · last ${last} · ${visible}${extra ? ` · ${extra}` : ''}`;
    }

    function rerenderResolveMedia() {
      if (state.resolveMedia) {
        renderResolveMedia(state.resolveMedia);
      } else {
        updateMediaPollStatus();
      }
    }

    async function refreshIndex() {
      const status = await api('/api/index/status');
      state.indexStatus = status;
      renderControlPanels();
    }

    async function buildIndex() {
      const built = await api('/api/index/build', { method: 'POST' });
      state.indexStatus = { ...built, exists: true };
      renderControlPanels();
    }

    async function refreshAll() {
      await refreshIndex();
      await refreshResolveMedia();
    }

    // ─── V2 Review surface ──────────────────────────────────────────────
    function formatDuration(seconds) {
      if (seconds == null || !isFinite(seconds)) return '—';
      const s = Math.max(0, Math.round(Number(seconds)));
      const m = Math.floor(s / 60);
      const r = s % 60;
      return `${m}:${String(r).padStart(2, '0')}`;
    }

    function selectChipClass(selectPotential) {
      const v = String(selectPotential || '').toLowerCase();
      if (v === 'high') return 'select-high';
      if (v === 'low') return 'select-low';
      if (v === 'medium' || v === 'med') return 'select-medium';
      return '';
    }

    // ─── C6 timeline-history view ────────────────────────────────────────
    state.history = state.history || { timelines: [], selectedTimeline: null, payload: null };

    function escapeHtml(s) {
      return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function formatDelta(edit) {
      const d = edit && edit.delta;
      if (d === null || d === undefined) return '<span class="delta-zero">—</span>';
      const cls = d > 0 ? 'delta-pos' : (d < 0 ? 'delta-neg' : 'delta-zero');
      const sign = d > 0 ? '+' : '';
      return `<span class="${cls}">${sign}${d}</span>`;
    }

    function formatVersionDate(iso) {
      if (!iso) return '';
      try { return new Date(iso).toLocaleString(); } catch (e) { return iso; }
    }

    async function refreshHistoryTimelines() {
      const list = $('historyTimelineList');
      if (list) list.innerHTML = '<div class="empty">Loading…</div>';
      const data = await api('/api/timeline_versions').catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        if (list) list.innerHTML = `<div class="empty">Error: ${escapeHtml(data?.error || 'unknown')}</div>`;
        return;
      }
      state.history.timelines = data.timelines || [];
      renderHistoryTimelineList();
      // Auto-select first timeline if nothing's selected yet.
      if (!state.history.selectedTimeline && state.history.timelines.length > 0) {
        await selectHistoryTimeline(state.history.timelines[0].timeline_name);
      } else if (state.history.selectedTimeline) {
        await loadHistoryDetail(state.history.selectedTimeline);
      } else {
        renderHistoryDetailEmpty();
      }
    }

    function renderHistoryTimelineList() {
      const list = $('historyTimelineList');
      if (!list) return;
      if (!state.history.timelines.length) {
        list.innerHTML = '<div class="empty">No archived timelines yet. Make a destructive edit (or click Archive current).</div>';
        return;
      }
      list.innerHTML = state.history.timelines.map(tl => {
        const selected = tl.timeline_name === state.history.selectedTimeline ? ' is-selected' : '';
        return `
          <div class="history-timeline-row${selected}" data-tl-name="${escapeHtml(tl.timeline_name)}">
            <span class="name" title="${escapeHtml(tl.timeline_name)}">${escapeHtml(tl.timeline_name)}</span>
            <span class="count">v${tl.latest_version} · ${tl.version_count}×</span>
          </div>`;
      }).join('');
      list.querySelectorAll('.history-timeline-row').forEach(row => {
        row.addEventListener('click', () => {
          selectHistoryTimeline(row.dataset.tlName).catch(alertError);
        });
      });
    }

    async function selectHistoryTimeline(timelineName) {
      state.history.selectedTimeline = timelineName;
      renderHistoryTimelineList();
      await loadHistoryDetail(timelineName);
    }

    async function loadHistoryDetail(timelineName) {
      const body = $('historyDetailBody');
      const header = $('historyDetailHeader');
      if (body) body.innerHTML = '<div class="empty">Loading…</div>';
      if (header) header.innerHTML = `<span class="timeline-name">${escapeHtml(timelineName)}</span>`;
      const data = await api(`/api/timeline_versions/${encodeURIComponent(timelineName)}`)
        .catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        if (body) body.innerHTML = `<div class="empty">Error: ${escapeHtml(data?.error || 'unknown')}</div>`;
        return;
      }
      state.history.payload = data;
      renderHistoryDetail(data);
    }

    function renderHistoryDetailEmpty() {
      const body = $('historyDetailBody');
      const header = $('historyDetailHeader');
      if (header) header.innerHTML = '<span class="empty">Select a timeline.</span>';
      if (body) body.innerHTML = '';
    }

    function renderHistoryDetail(data) {
      const body = $('historyDetailBody');
      if (!body) return;
      const versions = (data.versions || []).slice().reverse(); // newest first
      const edits = data.edits || [];

      // Bucket edits by archived_timeline_name (timeline_after for the version
      // they produced). Edits with no matching archive are shown in an "Unbucketed
      // edits" section at the bottom.
      const editsByArchive = {};
      const unbucketed = [];
      edits.forEach(edit => {
        const key = edit.timeline_after || edit.timeline_before;
        if (key && versions.some(v => v.archived_timeline_name === key)) {
          (editsByArchive[key] = editsByArchive[key] || []).push(edit);
        } else {
          unbucketed.push(edit);
        }
      });

      const sections = [];
      if (!versions.length) {
        sections.push('<div class="empty">No archived versions yet.</div>');
      }
      versions.forEach(v => {
        const versionEdits = editsByArchive[v.archived_timeline_name] || [];
        const collapsed = v.drt_export_path
          ? `<span class="drt-collapsed">retention-collapsed → ${escapeHtml(v.drt_export_path)}</span>`
          : '';
        const editsTable = versionEdits.length ? `
          <table class="history-edits-table">
            <thead>
              <tr><th>Edit</th><th>Metric</th><th>Before</th><th>After</th><th>Δ</th><th>Rationale</th></tr>
            </thead>
            <tbody>
              ${versionEdits.map(e => `
                <tr>
                  <td class="edit-type">${escapeHtml(e.edit_type || '')}</td>
                  <td class="metric">${escapeHtml(e.target_metric || '—')}</td>
                  <td>${e.before_value ?? '—'}</td>
                  <td>${e.after_value ?? '—'}</td>
                  <td>${formatDelta(e)}</td>
                  <td>${escapeHtml(e.rationale || '')}</td>
                </tr>`).join('')}
            </tbody>
          </table>` : '<div class="empty">No declared brain edits recorded.</div>';
        const thumbUrl = v.thumbnail_path
          ? `/api/timeline_thumbnail/${encodeURIComponent(v.thumbnail_path.split('/_soul/timeline_versions/').pop() || '')}`
          : null;
        const thumb = thumbUrl
          ? `<div class="thumb"><img src="${thumbUrl}" alt="v${v.version} thumbnail" loading="lazy"></div>`
          : `<div class="thumb">no thumbnail</div>`;
        const diffOptions = versions
          .filter(other => other.version !== v.version)
          .map(other => `<option value="${other.version}">v${other.version}</option>`).join('');
        sections.push(`
          <div class="history-version-card">
            ${thumb}
            <div class="body">
              <div class="version-row">
                <span class="version-label">v${v.version}</span>
                <select class="diff-against" data-diff-against-base="${v.version}" data-diff-timeline="${escapeHtml(data.timeline_name)}">
                  <option value="">Diff against…</option>
                  ${diffOptions}
                </select>
                <button class="history-rollback-btn" data-rollback-version="${v.version}" data-rollback-timeline="${escapeHtml(data.timeline_name)}">Rollback to v${v.version}</button>
              </div>
              <div class="archived-name">${escapeHtml(v.archived_timeline_name)} ${collapsed}</div>
              <div class="timestamp">${escapeHtml(formatVersionDate(v.created_at))} · run=${escapeHtml(v.analysis_run_id || '—')}</div>
              ${v.reason ? `<div class="reason">${escapeHtml(v.reason)}</div>` : ''}
              ${editsTable}
            </div>
          </div>`);
      });
      if (unbucketed.length) {
        sections.push(`
          <div class="history-version-card">
            <div class="version-label">Recent edits (no matching archive)</div>
            <table class="history-edits-table">
              <thead>
                <tr><th>Edit</th><th>Metric</th><th>Before</th><th>After</th><th>Δ</th><th>Created</th></tr>
              </thead>
              <tbody>
                ${unbucketed.map(e => `
                  <tr>
                    <td class="edit-type">${escapeHtml(e.edit_type || '')}</td>
                    <td class="metric">${escapeHtml(e.target_metric || '—')}</td>
                    <td>${e.before_value ?? '—'}</td>
                    <td>${e.after_value ?? '—'}</td>
                    <td>${formatDelta(e)}</td>
                    <td>${escapeHtml(formatVersionDate(e.created_at))}</td>
                  </tr>`).join('')}
              </tbody>
            </table>
          </div>`);
      }
      body.innerHTML = sections.join('');
      body.querySelectorAll('.history-rollback-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const version = Number(btn.dataset.rollbackVersion);
          const timelineName = btn.dataset.rollbackTimeline;
          if (!confirm(`Rollback "${timelineName}" to v${version}? This archives the current state first, then duplicates the archived version back into the project.`)) return;
          rollbackHistoryVersion(timelineName, version).catch(alertError);
        });
      });
      body.querySelectorAll('select.diff-against').forEach(sel => {
        sel.addEventListener('change', () => {
          const against = Number(sel.value);
          if (!against) return;
          const base = Number(sel.dataset.diffAgainstBase);
          const timeline = sel.dataset.diffTimeline;
          const from = Math.min(base, against);
          const to = Math.max(base, against);
          showDiffBetween(timeline, from, to).catch(alertError);
          sel.value = '';
        });
      });
    }

    async function rollbackHistoryVersion(timelineName, version) {
      const data = await api('/api/timeline_versions/action', {
        method: 'POST',
        body: JSON.stringify({ action: 'rollback', timeline_name: timelineName, version }),
      }).catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        alert(`Rollback failed: ${data?.error || 'unknown'}`);
        return;
      }
      alert(`Restored as "${data.restored_timeline_name}". Switch to it in Resolve to inspect.`);
      await refreshHistoryTimelines();
    }

    async function archiveCurrentTimelineFromUI(reason) {
      const data = await api('/api/timeline_versions/action', {
        method: 'POST',
        body: JSON.stringify({ action: 'archive_current', reason: reason || undefined }),
      }).catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        alert(`Archive failed: ${data?.error || 'unknown'}`);
        return;
      }
      const reasonInput = $('historyArchiveReason');
      if (reasonInput) reasonInput.value = '';
      await refreshHistoryTimelines();
    }

    // ─── Edit-engine plan browser (chat-first: the panel surfaces plans
    //     and evidence; execution happens via copyable chat prompts only) ─
    state.plans = state.plans || { list: null, currentPlanId: null, payload: null };

    const PLAN_KIND_LABELS = { selects: 'Selects', tighten: 'Tighten', swap: 'Swap' };

    function planExecutePrompt(plan) {
      const id = plan.plan_id;
      if (plan.kind === 'selects') {
        return `Execute edit plan ${id}: call edit_engine(action="execute_selects", params={"plan_id": "${id}"}). It creates a NEW selects timeline; nothing existing is touched. Show me the readback when done.`;
      }
      if (plan.kind === 'tighten') {
        return `Execute edit plan ${id}: call edit_engine(action="execute_tighten", params={"plan_id": "${id}"}). It assembles a tightened VARIANT timeline from the keep ranges; the original timeline is never mutated. Show me the readback when done.`;
      }
      if (plan.kind === 'swap') {
        return `Execute edit plan ${id} with alternate <N>: call edit_engine(action="execute_swap", params={"plan_id": "${id}", "alternate_index": <N>}) — replace <N> with the number of the alternate I picked below (0-based). The timeline is version-archived before the swap. Show me the readback when done.`;
      }
      return `Load edit plan ${id} with edit_engine(action="get_plan", params={"plan_id": "${id}"}) and walk me through it.`;
    }

    function planThumb(row, altText) {
      const clipId = row.resolve_clip_id;
      const frameIndex = row.thumb_frame_index;
      if (clipId && frameIndex != null) {
        return `<img class="review-thumb" loading="lazy" src="/api/clips/${encodeURIComponent(clipId)}/frames/${frameIndex}" alt="${escapeHtml(altText)}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'review-thumb placeholder',textContent:'no frame'}))">`;
      }
      return '<div class="review-thumb placeholder">no frame</div>';
    }

    async function refreshEditPlans() {
      const body = $('plansListBody');
      if (body) body.innerHTML = '<div class="empty">Loading…</div>';
      const data = await api('/api/edit_plans').catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        if (body) body.innerHTML = `<div class="empty">Error: ${escapeHtml(data?.error || 'unknown')}</div>`;
        return;
      }
      state.plans.list = data.plans || [];
      renderPlansList();
    }

    function renderPlansList() {
      const body = $('plansListBody');
      if (!body) return;
      const plans = state.plans.list || [];
      if (!plans.length) {
        body.innerHTML = '<div class="empty">No edit plans yet. Ask your chat session to plan one, e.g. “Plan a selects reel from this bin” (edit_engine action="plan_selects").</div>';
        return;
      }
      body.innerHTML = plans.map(p => {
        if (p.corrupt) {
          return `<div class="plan-row is-corrupt">
            <span class="plan-chip corrupt">corrupt</span>
            <span class="summary">Plan ${escapeHtml(p.plan_id || '?')} failed its fingerprint check — it was edited on disk or truncated. It cannot be executed; re-plan to replace it.</span>
          </div>`;
        }
        const executed = p.executed_at
          ? `<span class="plan-chip executed" title="${escapeHtml(p.executed_at)}">executed</span>` : '';
        return `<div class="plan-row" data-plan-id="${escapeHtml(p.plan_id)}" tabindex="0" role="button" aria-label="Open plan ${escapeHtml(p.plan_id)}">
          <span class="plan-chip kind-${escapeHtml(p.kind || '')}">${escapeHtml(PLAN_KIND_LABELS[p.kind] || p.kind || '?')}</span>
          <span class="summary" title="${escapeHtml(p.summary || '')}">${escapeHtml(p.summary || p.plan_id)}</span>
          ${executed}
          <span class="saved-at">${escapeHtml(formatVersionDate(p.saved_at))}</span>
        </div>`;
      }).join('');
      body.querySelectorAll('.plan-row[data-plan-id]').forEach(row => {
        const open = () => openEditPlan(row.dataset.planId).catch(alertError);
        row.addEventListener('click', open);
        row.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } });
      });
    }

    async function openEditPlan(planId, opts = {}) {
      state.plans.currentPlanId = planId;
      reviewSetView('plan', opts);
      const body = $('planDetailBody');
      const header = $('planDetailHeader');
      if (body) body.innerHTML = '<div class="empty">Loading…</div>';
      if (header) header.innerHTML = '';
      const data = await api(`/api/edit_plans/${encodeURIComponent(planId)}`)
        .catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        if (body) body.innerHTML = `<div class="empty">Error: ${escapeHtml(data?.error || 'unknown')}</div>`;
        return;
      }
      state.plans.payload = data;
      renderPlanDetail(data);
    }

    function renderPlanDetail(data) {
      const header = $('planDetailHeader');
      const body = $('planDetailBody');
      if (!header || !body) return;
      if (data.corrupt) {
        header.innerHTML = `<span class="plan-chip corrupt">corrupt</span><span class="timeline-name">Plan ${escapeHtml(data.plan_id || '?')}</span>`;
        body.innerHTML = '<div class="empty">This plan failed its fingerprint check — it was edited on disk or truncated. It cannot be executed; re-plan to replace it.</div>';
        return;
      }
      const plan = data.plan || {};
      const executed = plan.executed_at
        ? `<span class="plan-chip executed" title="${escapeHtml(plan.executed_at)}">executed ${escapeHtml(formatVersionDate(plan.executed_at))}</span>` : '';
      header.innerHTML = `
        <span class="plan-chip kind-${escapeHtml(plan.kind || '')}">${escapeHtml(PLAN_KIND_LABELS[plan.kind] || plan.kind || '?')}</span>
        <span class="timeline-name">${escapeHtml(plan.timeline_name || plan.plan_id || '')}</span>
        ${executed}
        <span class="saved-at" style="color:var(--text-muted);font-size:var(--text-xs)">saved ${escapeHtml(formatVersionDate(plan.saved_at))} · plan ${escapeHtml(plan.plan_id || '')}</span>`;

      const sections = [];
      if (plan.summary) {
        sections.push(`<div class="plan-section"><strong>Summary</strong><div>${escapeHtml(plan.summary)}</div></div>`);
      }
      // Chat-first execute affordance: the panel NEVER executes. Executed
      // plans keep the card (re-execution of selects is harmless and swap
      // may target another alternate) — the chip above signals state.
      sections.push(`<div class="plan-section"><strong>Execute (from chat)</strong>${chatPromptCard(
        plan.kind === 'swap'
          ? 'Pick an alternate below, then paste this in your chat session (fill in <N>):'
          : 'Paste this in your chat session to execute the plan:',
        planExecutePrompt(plan))}</div>`);
      if (plan.execution_summary) {
        sections.push(`<div class="plan-section"><strong>Execution readback</strong><pre style="margin:0;white-space:pre-wrap;font-size:var(--text-xs)">${escapeHtml(JSON.stringify(plan.execution_summary, null, 2))}</pre></div>`);
      }
      if (plan.settings) {
        const settings = Object.entries(plan.settings)
          .map(([k, v]) => `${escapeHtml(k)}=${escapeHtml(v == null ? '—' : String(v))}`).join(' · ');
        sections.push(`<div class="plan-section"><strong>Settings</strong><div style="font-size:var(--text-xs);color:var(--text-secondary)">${settings}</div></div>`);
      }
      if (plan.kind === 'selects') {
        sections.push(renderSelectsDecisions(plan));
      } else if (plan.kind === 'tighten') {
        sections.push(renderTightenLifts(plan));
      } else if (plan.kind === 'swap') {
        sections.push(renderSwapAlternates(plan));
      }
      body.innerHTML = sections.join('');
      body.querySelectorAll('[data-open-shot-clip]').forEach(btn => {
        btn.addEventListener('click', () => {
          const clipId = btn.dataset.openShotClip;
          const shotIndex = Number(btn.dataset.openShotIndex);
          openClipDetail(clipId)
            .then(() => Number.isFinite(shotIndex) ? openShotDetail(shotIndex) : null)
            .catch(alertError);
        });
      });
    }

    function renderSelectsDecisions(plan) {
      const decisions = plan.decisions || [];
      const rankLabel = { 3: 'high', 2: 'medium', 1: 'low' };
      const cards = decisions.map((d, i) => {
        const range = Array.isArray(d.source_frame_range) ? `frames ${d.source_frame_range[0]}–${d.source_frame_range[1]}` : '';
        const shotLink = d.resolve_clip_id != null && d.shot_index != null
          ? `<button class="secondary" style="font-size:var(--text-xs);padding:1px 8px" data-open-shot-clip="${escapeHtml(d.resolve_clip_id)}" data-open-shot-index="${d.shot_index}">Open shot page</button>` : '';
        return `<div class="plan-decision-card">
          ${planThumb(d, `decision ${i + 1}`)}
          <div class="body">
            <div class="title-row">
              <strong>${i + 1}. ${escapeHtml(d.clip_name || d.clip_uuid || '?')} · shot ${d.shot_index ?? '?'}</strong>
              <span class="plan-chip">${escapeHtml(rankLabel[d.rank] || `rank ${d.rank}`)}</span>
              <span class="meta">${(d.duration_seconds ?? '?')}s${range ? ` · ${range}` : ''}</span>
              ${shotLink}
            </div>
            ${d.description ? `<div class="meta">${escapeHtml(d.description)}</div>` : ''}
            <div class="rationale">${escapeHtml(d.rationale || '')}</div>
          </div>
        </div>`;
      });
      return `<div class="plan-section"><strong>Decisions (${decisions.length} shots, ~${plan.estimated_duration_seconds ?? '?'}s)</strong>${cards.join('') || '<div class="empty">No decisions.</div>'}</div>`;
    }

    function renderTightenLifts(plan) {
      const lifts = plan.lifts || [];
      const rows = lifts.map(l => {
        const gap = l.evidence?.source_gap_seconds;
        return `<tr>
          <td class="edit-type">${escapeHtml(l.kind || 'lift')}</td>
          <td>${escapeHtml(l.item_name || '—')}</td>
          <td>${l.timeline_start_frame}–${l.timeline_end_frame}</td>
          <td>${l.duration_seconds ?? '—'}s</td>
          <td>${escapeHtml(l.rationale || '')}${gap ? ` <span style="color:var(--text-muted)">(gap ${gap[0]}–${gap[1]}s)</span>` : ''}</td>
        </tr>`;
      }).join('');
      const skipped = (plan.skipped || []).map(s =>
        `<div class="plan-decision-card"><div class="body"><div class="meta">skipped ${escapeHtml(s.item || '?')}: ${escapeHtml(s.reason || '')}</div></div></div>`).join('');
      return `<div class="plan-section">
        <strong>Lifts (${lifts.length} · ${plan.keep_ranges ? plan.keep_ranges.length : 0} keep ranges)</strong>
        <table class="history-edits-table">
          <thead><tr><th>Kind</th><th>Item</th><th>Timeline frames</th><th>Removes</th><th>Rationale</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="5">No lifts.</td></tr>'}</tbody>
        </table>
        ${skipped}
      </div>`;
    }

    function renderSwapAlternates(plan) {
      const alternates = plan.alternates || [];
      const item = plan.item || {};
      const current = `<div class="plan-decision-card"><div class="body">
        <div class="title-row"><strong>Current: ${escapeHtml(item.item_name || 'item')}</strong>
        <span class="meta">slot ${item.timeline_start_frame}–${item.timeline_end_frame} · track ${item.track_index ?? 1}</span></div>
        ${item.current_description ? `<div class="meta">${escapeHtml(item.current_description)}</div>` : ''}
      </div></div>`;
      const cards = alternates.map((a, i) => {
        const range = Array.isArray(a.source_frame_range) ? `frames ${a.source_frame_range[0]}–${a.source_frame_range[1]}` : '';
        const shotLink = a.resolve_clip_id != null && a.shot_index != null
          ? `<button class="secondary" style="font-size:var(--text-xs);padding:1px 8px" data-open-shot-clip="${escapeHtml(a.resolve_clip_id)}" data-open-shot-index="${a.shot_index}">Open shot page</button>` : '';
        return `<div class="plan-decision-card">
          ${planThumb(a, `alternate ${i}`)}
          <div class="body">
            <div class="title-row">
              <strong>alternate_index ${i} · ${escapeHtml(a.clip_name || '?')} · shot ${a.shot_index ?? '?'}</strong>
              <span class="plan-chip">score ${a.score ?? '?'}</span>
              <span class="meta">${range}</span>
              ${shotLink}
            </div>
            ${a.description ? `<div class="meta">${escapeHtml(a.description)}</div>` : ''}
            <div class="rationale">${escapeHtml(a.rationale || '')}</div>
          </div>
        </div>`;
      });
      return `<div class="plan-section"><strong>Alternates (${alternates.length})</strong>${current}${cards.join('') || '<div class="empty">No alternates.</div>'}</div>`;
    }

    // ─── Run scoping controls ──────────────────────────────────────────
    state.runScope = state.runScope || { current: null, recent: [] };

    async function refreshRunScope() {
      const data = await api('/api/runs').catch(() => ({ success: false }));
      if (!data || !data.success) return;
      state.runScope.current = data.current_run_id || null;
      state.runScope.recent = data.runs || [];
      const indicator = $('runScopeIndicator');
      if (indicator) {
        if (state.runScope.current) {
          indicator.textContent = state.runScope.current;
          indicator.classList.add('active');
          indicator.classList.remove('none');
        } else {
          indicator.textContent = 'none';
          indicator.classList.remove('active');
          indicator.classList.add('none');
        }
      }
      const recent = $('historyRecentRuns');
      if (recent) {
        if (!state.runScope.recent.length) {
          recent.innerHTML = '<div class="empty">no runs yet</div>';
        } else {
          recent.innerHTML = state.runScope.recent.slice(0, 8).map(r => `
            <div class="history-recent-run-row">
              <div><strong>${escapeHtml(r.label || '(no label)')}</strong></div>
              <div>${escapeHtml(r.id || '')}</div>
              <div>${escapeHtml(r.ended_at ? 'ended ' + formatVersionDate(r.ended_at) : 'open')}</div>
            </div>
          `).join('');
        }
      }
    }

    async function beginRunFromUI() {
      const label = ($('runScopeLabel')?.value || '').trim();
      const data = await api('/api/runs/begin', {
        method: 'POST',
        body: JSON.stringify({ label: label || undefined }),
      }).catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        alert(`Begin run failed: ${data?.error || 'unknown'}`);
        return;
      }
      const labelInput = $('runScopeLabel');
      if (labelInput) labelInput.value = '';
      await refreshRunScope();
    }

    async function endRunFromUI() {
      const data = await api('/api/runs/end', {
        method: 'POST',
        body: JSON.stringify({}),
      }).catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        alert(`End run failed: ${data?.error || 'unknown'}`);
        return;
      }
      await refreshRunScope();
    }

    // ─── Structural diff between versions ─────────────────────────────
    async function showDiffBetween(timelineName, fromVersion, toVersion) {
      const view = $('historyDiffView');
      const body = $('historyDiffBody');
      if (!view || !body) return;
      view.hidden = false;
      body.innerHTML = 'loading…';
      const data = await api('/api/timeline_versions/action', {
        method: 'POST',
        body: JSON.stringify({
          action: 'diff_versions', timeline_name: timelineName,
          from_version: fromVersion, to_version: toVersion,
        }),
      }).catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        body.innerHTML = `<div class="empty">diff failed: ${escapeHtml(data?.error || 'unknown')}</div>`;
        return;
      }
      const section = (kind, rows) => `
        <div class="history-diff-section ${kind}">
          <h4>${kind} (${rows.length})</h4>
          ${rows.length
            ? `<ul>${rows.slice(0, 30).map(r => `<li>${escapeHtml(r.media_pool_item_id)} @ ${escapeHtml(r.track_type)}:${r.track_index} [${r.in_frame}–${r.out_frame}]</li>`).join('')}</ul>`
            : '<div class="empty">none</div>'}
        </div>`;
      body.innerHTML = `
        <div>v${fromVersion} → v${toVersion}</div>
        ${section('added', data.added || [])}
        ${section('removed', data.removed || [])}
        ${section('moved', data.moved || [])}
      `;
    }

    // ─── Caps history chart ───────────────────────────────────────────
    async function refreshCapsHistory() {
      const el = $('capsHistoryChart');
      if (!el) return;
      const data = await api('/api/caps/history?days=30').catch(() => ({ success: false }));
      if (!data || !data.success || !(data.history || []).length) {
        el.innerHTML = '<div class="empty">no usage recorded yet</div>';
        return;
      }
      const rows = (data.history || []).slice().reverse(); // oldest → newest
      const maxV = Math.max(1, ...rows.map(r => r.vision_tokens || 0));
      const w = 100, h = 90;
      const points = rows.map((r, i) => {
        const x = rows.length === 1 ? 0 : (i / (rows.length - 1)) * w;
        const y = h - ((r.vision_tokens || 0) / maxV) * (h - 12);
        return { x, y, value: r.vision_tokens, day: r.day_bucket };
      });
      const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
      el.innerHTML = `
        <svg viewBox="0 0 ${w} ${h + 10}" preserveAspectRatio="none">
          <line class="axis" x1="0" y1="${h}" x2="${w}" y2="${h}"></line>
          <path class="line" d="${path}"></path>
          ${points.map(p => `<circle class="point" cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="1.4"><title>${p.day}: ${p.value}</title></circle>`).join('')}
          <text class="label" x="0" y="${h + 9}">${rows[0].day_bucket}</text>
          <text class="label" x="${w}" y="${h + 9}" text-anchor="end">${rows[rows.length - 1].day_bucket}</text>
          <text class="label" x="0" y="9">max ${maxV}</text>
        </svg>`;
    }

    // ─── Resolve 21 AI ops ledger (read-only) ───────────────────────
    function fmtMs(ms) {
      ms = ms || 0;
      if (ms < 1000) return ms + 'ms';
      const s = ms / 1000;
      return s < 60 ? s.toFixed(1) + 's' : (s / 60).toFixed(1) + 'm';
    }
    function fmtBytes(n) {
      n = n || 0;
      if (!n) return '—';
      const u = ['B', 'KB', 'MB', 'GB', 'TB'];
      let i = 0; let v = n;
      while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
      return v.toFixed(v < 10 && i > 0 ? 1 : 0) + ' ' + u[i];
    }
    async function refreshResolveAiOps() {
      const summaryEl = $('resolveAiOpsSummary');
      const tableEl = $('resolveAiOpsTable');
      const rowsEl = $('resolveAiOpsRows');
      if (!summaryEl || !tableEl || !rowsEl) return;
      const data = await api('/api/resolve_ai_usage').catch(() => ({ success: false }));
      if (!data || !data.success) {
        summaryEl.textContent = 'ledger unavailable';
        tableEl.style.display = 'none';
        return;
      }
      const totals = (data.summary && data.summary.totals) || {};
      const byOp = (data.summary && data.summary.by_op) || {};
      const ops = Object.keys(byOp).sort();
      if (!ops.length) {
        summaryEl.textContent = 'No Resolve AI ops recorded yet for this project.';
        tableEl.style.display = 'none';
        return;
      }
      summaryEl.innerHTML = `<strong>${totals.runs || 0}</strong> runs · `
        + `<strong>${totals.successes || 0}</strong> ok / ${totals.failures || 0} failed · `
        + `${fmtMs(totals.wall_clock_ms)} total · `
        + `<strong>${totals.files_created || 0}</strong> files (${fmtBytes(totals.bytes_created)}) created`;
      rowsEl.innerHTML = ops.map(op => {
        const b = byOp[op];
        const isRender = b.op_class === 'render';
        return `<tr style="border-top:1px solid rgba(255,255,255,0.06);">
          <td style="padding:4px 6px;">${escapeHtml(op)}${isRender ? ' <span style="opacity:0.6;">(media)</span>' : ''}</td>
          <td style="padding:4px 6px;">${b.runs}</td>
          <td style="padding:4px 6px;">${b.successes}</td>
          <td style="padding:4px 6px;">${fmtMs(b.wall_clock_ms)}</td>
          <td style="padding:4px 6px;">${b.files_created || '—'}</td>
          <td style="padding:4px 6px;">${b.bytes_created ? fmtBytes(b.bytes_created) : '—'}</td>
        </tr>`;
      }).join('');
      const recent = Array.isArray(data.recent) ? data.recent.slice(0, 8) : [];
      const recentEl = $('resolveAiOpsRecent');
      if (recentEl) {
        recentEl.innerHTML = recent.length ? '<div class="caps-section-hint" style="margin-top:8px;">Recent runs</div>'
          + recent.map(r => {
            const when = (r.occurred_at || '').replace('T', ' ');
            const who = r.actor ? ` · <span title="instance:pid that performed the op">${escapeHtml(r.actor)}</span>` : '';
            const ok = r.success ? 'ok' : 'failed';
            return `<div style="font-size:12px; color:var(--text-secondary); padding:2px 0;">${escapeHtml(when)} · ${escapeHtml(r.op)} · ${ok}${who}</div>`;
          }).join('') : '';
      }
      tableEl.style.display = '';
    }

    // ─── Resolve 21 AI Console ──────────────────────────────────────
    const AI_MARKER_COLORS = ['Blue','Cyan','Green','Yellow','Red','Pink','Purple',
      'Fuchsia','Rose','Lavender','Sky','Mint','Lemon','Sand','Cocoa','Cream'];
    const AI_OP_LABELS = {
      perform_audio_classification: 'Classify audio',
      clear_audio_classification: 'Clear classification',
      analyze_for_intellisearch: 'IntelliSearch',
      analyze_for_slate: 'Analyze for slate',
      transcribe_audio: 'Transcribe',
      clear_transcription: 'Clear transcription',
      remove_motion_blur: 'Remove motion blur',
      generate_speech: 'Generate speech',
      disable_background_tasks: 'Disable background tasks',
    };
    // Which features gate which buttons (key in resolve.ai_features.features).
    const AI_OP_FEATURE = {
      perform_audio_classification: 'perform_audio_classification',
      clear_audio_classification: 'clear_audio_classification',
      analyze_for_intellisearch: 'analyze_for_intellisearch',
      analyze_for_slate: 'analyze_for_slate',
      remove_motion_blur: 'remove_motion_blur',
      generate_speech: 'generate_speech',
      disable_background_tasks: 'disable_background_tasks',
    };
    let _aiConsoleInit = false;

    function renderAiConsole() {
      const feats = (state.boot?.resolve?.ai_features) || {};
      const features = feats.features || {};
      const requiresExtra = feats.requires_extra || {};
      const capsEl = $('aiConsoleCaps');
      if (capsEl) {
        if (state.boot?.resolve?.available !== true) {
          capsEl.innerHTML = '<div class="caps-section-hint">Resolve is not connected. Open a project in DaVinci Resolve, then reload.</div>';
        } else {
          const items = Object.keys(AI_OP_LABELS)
            .filter(op => op in AI_OP_FEATURE)
            .map(op => {
              const key = AI_OP_FEATURE[op];
              const on = !!features[key];
              const extra = requiresExtra[key];
              return `<div class="ai-caps-item"><span class="ai-caps-dot ${on ? 'on' : 'off'}"></span>`
                + `<span>${escapeHtml(AI_OP_LABELS[op])}</span>`
                + (extra ? `<span class="ai-caps-extra">· needs ${escapeHtml(extra)}</span>` : '')
                + `</div>`;
            }).join('');
          capsEl.innerHTML = `<div class="caps-section-head"><div class="caps-section-title">Available on this Resolve build</div>`
            + `<div class="caps-section-hint">A grey dot means the method is absent (older Resolve). "needs …" means the method is present but requires that Extra to actually run — install via Extras Download Manager.</div></div>`
            + `<div class="ai-caps-grid">${items}</div>`;
        }
      }
      // Slate color dropdown (once).
      const sel = $('aiSlateColor');
      if (sel && !sel.options.length) {
        sel.innerHTML = AI_MARKER_COLORS.map(c => `<option value="${c}">${c}</option>`).join('');
      }
    }

    function aiTarget() {
      const checked = document.querySelector('input[name="aiTarget"]:checked');
      return checked ? checked.value : 'folder';
    }

    function aiBuildParams(op) {
      const params = {};
      if (op === 'analyze_for_intellisearch') {
        params.identify_faces = !!$('aiIdentifyFaces')?.checked;
        params.is_better_mode = !!$('aiBetterMode')?.checked;
      } else if (op === 'analyze_for_slate') {
        params.marker_color = $('aiSlateColor')?.value || 'Blue';
      } else if (op === 'transcribe_audio') {
        if ($('aiSpeakerDetection')?.checked) params.use_speaker_detection = true;
      } else if (op === 'remove_motion_blur') {
        const d = {};
        const fmt = ($('aiDeblurFormat')?.value || '').trim(); if (fmt) d.Format = fmt;
        const codec = ($('aiDeblurCodec')?.value || '').trim(); if (codec) d.Codec = codec;
        if ($('aiDeblurExtreme')?.checked) d.UseExtremeMode = true;
        if ($('aiDeblurMarkInOut')?.checked) d.UseMarkInMarkOut = true;
        if ($('aiDeblurSourceRes')?.checked) d.RenderAtSourceRes = true;
        params.deblur_option = d;
      } else if (op === 'generate_speech') {
        const text = ($('aiSpeechText')?.value || '').trim();
        const settings = { TextInput: text };
        const voice = ($('aiSpeechVoice')?.value || '').trim(); if (voice) settings.VoiceModel = voice;
        const num = (id) => { const v = ($(id)?.value || '').trim(); return v === '' ? null : Number(v); };
        const speed = num('aiSpeechSpeed'); if (speed != null) settings.Speed = speed;
        const pitch = num('aiSpeechPitch'); if (pitch != null) settings.Pitch = pitch;
        const variation = num('aiSpeechVariation'); if (variation != null) settings.Variation = variation;
        if ($('aiSpeechAddTimeline')?.checked) {
          settings.AddToTimeline = true;
          const track = num('aiSpeechTrack'); if (track != null) settings.AudioTrack = track;
        }
        params.speech_generation_settings = settings;
        const tc = ($('aiSpeechTimecode')?.value || '').trim(); if (tc) params.timecode = tc;
      }
      return params;
    }

    function aiShowResult(op, payload, isErr) {
      const el = $('aiConsoleResult');
      if (!el) return;
      el.classList.toggle('err', !!isErr);
      el.classList.toggle('ok', !isErr);
      const head = `${AI_OP_LABELS[op] || op} — ${new Date().toLocaleTimeString()}\n`;
      el.textContent = head + JSON.stringify(payload, null, 2);
    }

    async function runAiOp(op) {
      const target = (op === 'generate_speech' || op === 'disable_background_tasks') ? 'folder' : aiTarget();
      const params = aiBuildParams(op);
      if (target === 'clip') {
        const clipId = ($('aiClipId')?.value || '').trim();
        if (!clipId) { aiShowResult(op, { error: 'Enter a clip id, or switch target to Current folder.' }, true); return; }
        params.clip_id = clipId;
      }
      if (op === 'generate_speech' && !params.speech_generation_settings?.TextInput) {
        aiShowResult(op, { error: 'Enter text to synthesize.' }, true); return;
      }
      const buttons = document.querySelectorAll('.ai-op-btn');
      buttons.forEach(b => { b.disabled = true; });
      try {
        let res = await api('/api/resolve_ai/run', {
          method: 'POST', body: JSON.stringify({ op, target, params }),
        }).catch(err => ({ success: false, error: String(err && err.message || err) }));
        // Confirm-token two-step for the media-creating ops.
        if (res && res.status === 'confirmation_required') {
          const preview = res.preview || {};
          const gov = preview.governance || {};
          const govWarn = (gov.applies && (gov.warnings || []).length)
            ? '\n\nGovernance (' + (gov.tier || '') + '):\n• ' + gov.warnings.join('\n• ')
            : '';
          const proceed = await brandedConfirm({
            kicker: gov.exceeded ? 'Over governance limit' : 'Creates new media',
            title: AI_OP_LABELS[op] || op,
            body: (preview.warning || 'This operation creates new media. Proceed?') + govWarn,
            detail: JSON.stringify(preview, null, 2),
            confirmLabel: 'Run it',
            tone: 'danger',
          });
          if (!proceed) { aiShowResult(op, { cancelled: true }, false); return; }
          const params2 = { ...params, confirm_token: res.confirm_token };
          res = await api('/api/resolve_ai/run', {
            method: 'POST', body: JSON.stringify({ op, target, params: params2 }),
          }).catch(err => ({ success: false, error: String(err && err.message || err) }));
        }
        aiShowResult(op, res, !(res && res.success));
        // Refresh the ledger + governance widgets so totals stay current.
        refreshResolveAiOps().catch(() => {});
        refreshGovernance().catch(() => {});
      } finally {
        buttons.forEach(b => { b.disabled = false; });
      }
    }

    // ─── Governance tier selector + consumption ─────────────────────
    const AI_GOV_TIER_ORDER = ['off', 'lenient', 'standard', 'strict'];
    const AI_GOV_TIER_TAGS = {
      off: 'No limits',
      lenient: 'Big jobs',
      standard: 'Sensible default',
      strict: 'Tight leash',
    };
    state.aiGov = state.aiGov || { tier: 'standard', mode: 'advisory', thresholds: {}, usage: {} };

    function aiGovFmt(dim, v) {
      if (v == null) return '∞';
      if (dim === 'render_bytes') return fmtBytes(v);
      if (dim === 'render_wall_clock_ms') return fmtMs(v);
      return String(v);
    }
    function renderGovTiers() {
      const el = $('aiGovTiers');
      if (!el) return;
      const tiers = state.aiGov.tiersAvailable || {};
      const active = state.aiGov.tier || 'standard';
      el.innerHTML = AI_GOV_TIER_ORDER.filter(k => tiers[k]).map(key => {
        const t = tiers[key];
        const stats = [['deblur_runs','Deblur runs'],['speech_runs','Speech runs'],
          ['render_bytes','Media'],['render_wall_clock_ms','Render time']].map(([d,label]) =>
          `<span class="stat-label">${escapeHtml(label)}</span><span class="stat-value">${escapeHtml(aiGovFmt(d, t[d]))}</span>`).join('');
        return `<button type="button" class="caps-preset-card${key === active ? ' is-active' : ''}" data-gov-tier="${escapeHtml(key)}" role="radio" aria-checked="${key === active}">
          <div class="caps-preset-card-head"><span class="caps-preset-card-name">${escapeHtml(key)}</span>${key === active ? '<span class="caps-preset-card-badge">Active</span>' : ''}</div>
          <div class="caps-preset-card-tag">${escapeHtml(AI_GOV_TIER_TAGS[key] || '')}</div>
          <div class="caps-preset-card-stats">${stats}</div>
        </button>`;
      }).join('');
    }
    function renderGovUsage() {
      const el = $('aiGovUsage');
      if (!el) return;
      const usage = state.aiGov.usage || {};
      const th = state.aiGov.thresholds || {};
      const dims = [['deblur_runs','Deblur runs'],['speech_runs','Speech runs'],
        ['render_bytes','Media created'],['render_wall_clock_ms','Render time']];
      el.innerHTML = dims.map(([d,label]) => {
        const used = usage[d] || 0;
        const cap = th[d];
        const pct = (cap == null || cap === 0) ? 0 : Math.min(100, Math.round((used / cap) * 100));
        const tone = pct >= 100 ? '#e06c5a' : (pct >= 80 ? '#e0a83a' : '#34a853');
        return `<div class="caps-gauge">
          <div class="caps-gauge-top"><span class="caps-gauge-label">${escapeHtml(label)}</span>
            <span class="caps-gauge-numbers">${escapeHtml(aiGovFmt(d, used))}${cap == null ? '' : ' / ' + escapeHtml(aiGovFmt(d, cap))}</span></div>
          <div class="caps-gauge-bar"><span class="caps-gauge-fill" style="width:${pct}%; background:${tone};"></span></div>
        </div>`;
      }).join('');
    }
    function renderGovMode() {
      const el = $('aiGovMode');
      if (!el) return;
      const mode = state.aiGov.mode || 'advisory';
      el.querySelectorAll('[data-gov-mode]').forEach(btn => {
        const active = btn.dataset.govMode === mode;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-checked', active ? 'true' : 'false');
      });
    }
    async function refreshGovernance() {
      const data = await api('/api/resolve_ai/governance').catch(() => ({ success: false }));
      if (!data || !data.success) return;
      state.aiGov.tier = data.tier;
      state.aiGov.mode = data.mode || 'advisory';
      state.aiGov.thresholds = data.thresholds || {};
      state.aiGov.usage = data.usage || {};
      state.aiGov.tiersAvailable = data.tiers_available || {};
      renderGovTiers();
      renderGovMode();
      renderGovUsage();
    }
    async function setGovernanceTier(tier) {
      state.aiGov.tier = tier;
      renderGovTiers();
      const res = await api('/api/resolve_ai/governance', {
        method: 'POST', body: JSON.stringify({ preset: tier }),
      }).catch(err => ({ success: false, error: String(err) }));
      if (!res || !res.success) console.warn('governance save failed:', res && res.error);
      await refreshGovernance();
    }
    async function setGovernanceMode(mode) {
      state.aiGov.mode = mode;
      renderGovMode();
      const res = await api('/api/resolve_ai/governance', {
        method: 'POST', body: JSON.stringify({ mode }),
      }).catch(err => ({ success: false, error: String(err) }));
      if (!res || !res.success) console.warn('governance mode save failed:', res && res.error);
      await refreshGovernance();
    }

    function initAiConsole() {
      if (_aiConsoleInit) { renderAiConsole(); refreshGovernance().catch(() => {}); return; }
      _aiConsoleInit = true;
      renderAiConsole();
      document.querySelectorAll('#panel-aiconsole .ai-op-btn').forEach(btn => {
        btn.addEventListener('click', () => runAiOp(btn.dataset.aiOp));
      });
      const govEl = $('aiGovTiers');
      if (govEl) {
        govEl.addEventListener('click', (ev) => {
          const card = ev.target.closest('[data-gov-tier]');
          if (card && card.dataset.govTier) setGovernanceTier(card.dataset.govTier);
        });
      }
      const govModeEl = $('aiGovMode');
      if (govModeEl) {
        govModeEl.addEventListener('click', (ev) => {
          const btn = ev.target.closest('[data-gov-mode]');
          if (btn && btn.dataset.govMode) setGovernanceMode(btn.dataset.govMode);
        });
      }
      refreshGovernance().catch(() => {});
    }

    // ─── Caps inspector + refusals + reset ──────────────────────────
    async function inspectCapsFromUI() {
      const clipId = ($('capsInspectClipId')?.value || '').trim();
      const jobId = ($('capsInspectJobId')?.value || '').trim();
      const out = $('capsInspectResult');
      if (!out) return;
      if (!clipId && !jobId) {
        out.textContent = 'enter a clip_id or job_id';
        out.classList.remove('has-data');
        return;
      }
      const qs = new URLSearchParams();
      if (clipId) qs.set('clip_id', clipId);
      if (jobId) qs.set('job_id', jobId);
      const data = await api(`/api/caps?${qs}`).catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        out.textContent = `lookup failed: ${data?.error || 'unknown'}`;
        return;
      }
      const usage = data.usage || {};
      out.classList.add('has-data');
      out.textContent = JSON.stringify(usage, null, 2);
    }

    async function resetDayUsageFromUI() {
      if (!confirm('Delete today\'s day-scope usage rows? This is for testing / circuit-breaker reset only.')) return;
      const data = await api('/api/caps/reset_day', {
        method: 'POST',
        body: JSON.stringify({}),
      }).catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        alert(`Reset failed: ${data?.error || 'unknown'}`);
        return;
      }
      alert(`Deleted ${data.deleted} row(s) for ${data.day_bucket}.`);
      await refreshCapsWidget();
      await refreshCapsHistory();
    }

    async function refreshCapsRefusals() {
      const el = $('capsRefusalsList');
      if (!el) return;
      const data = await api('/api/caps/refusals?limit=20').catch(() => ({ success: false }));
      if (!data || !data.success || !(data.events || []).length) {
        el.innerHTML = '<div class="empty">no refusals recorded</div>';
        return;
      }
      el.innerHTML = (data.events || []).map(e => `
        <div class="caps-refusal-row">
          <span class="reason">${escapeHtml(e.reason || '?')}</span>
          <span>clip=${escapeHtml(e.clip_id || '—')} job=${escapeHtml(e.job_id || '—')} est=${e.estimated_vision_tokens}</span>
          <span class="when">${escapeHtml(formatVersionDate(e.occurred_at))}</span>
        </div>
      `).join('');
    }

    // ─── Updates page wiring ──────────────────────────────────────────
    state.updates = state.updates || { restartTimer: null };

    async function refreshUpdateStatus() {
      const el = $('updateStatusBadge');
      if (!el) return;
      const data = await api('/api/update/status').catch(() => ({ success: false }));
      if (!data || !data.success) { el.textContent = 'status unknown'; el.dataset.status = ''; return; }
      el.dataset.status = data.status || '';
      const cur = data.current_version || '?';
      const latest = data.latest_version || '?';
      el.textContent = data.status === 'update_available'
        ? `update available: ${cur} → ${latest}`
        : (data.status === 'up_to_date' ? `up to date (${cur})` : `${data.status || 'unknown'} — ${cur}`);
    }

    async function refreshUpdateHistory() {
      const el = $('updateHistoryTable');
      if (!el) return;
      const data = await api('/api/update/history?limit=20').catch(() => ({ success: false }));
      if (!data || !data.success || !(data.entries || []).length) {
        el.innerHTML = '<div class="empty">no update history yet</div>';
        return;
      }
      const header = `
        <div class="update-history-row header">
          <span>timestamp</span><span>kind</span><span>versions</span><span>reason / msg</span><span>integrity</span><span>by</span>
        </div>`;
      const rows = (data.entries || []).map(e => {
        const v = (e.from_version || '?') + ' → ' + (e.to_version || '?');
        const statusCls = e.success ? 'status-ok' : 'status-fail';
        const reason = e.reason || (e.message || '').slice(0, 120);
        const integ = (e.integrity || {}).verified;
        const integHtml = integ === true
          ? '<span class="integrity-ok">verified</span>'
          : integ === false ? '<span class="integrity-bad">MISMATCH</span>'
          : '<span class="integrity-unknown">—</span>';
        return `
          <div class="update-history-row">
            <span class="${statusCls}">${escapeHtml(e.timestamp || '')}</span>
            <span class="kind">${escapeHtml(e.kind || '')}</span>
            <span>${escapeHtml(v)}</span>
            <span title="${escapeHtml(reason)}">${escapeHtml(reason || '')}</span>
            <span>${integHtml}</span>
            <span>${escapeHtml(e.initiator || '')}</span>
          </div>`;
      }).join('');
      el.innerHTML = header + rows;
    }

    async function previewUpdateFromUI() {
      const result = $('updateActionResult');
      if (result) result.textContent = 'fetching preview…';
      const data = await api('/api/update/preview').catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        if (result) result.textContent = `preview failed: ${data?.error || 'unknown'}`;
        return;
      }
      const breaking = (data.breaking_changes || []).length
        ? `⚠️ Breaking changes:\n${(data.breaking_changes || []).map(b => '  - ' + b).join('\n')}\n\n`
        : '';
      const body = (data.release_notes || '').slice(0, 4000);
      if (result) {
        result.textContent = `current: ${data.current_version}  →  ${data.latest_version} (${data.channel}${data.prerelease ? ', prerelease' : ''})\n\n${breaking}${body}`;
      }
    }

    async function applyUpdateFromUI() {
      const stash = !!$('updateStashCheckbox')?.checked;
      const force = !!$('updateForceJobsCheckbox')?.checked;
      const result = $('updateActionResult');
      if (result) result.textContent = 'applying…';
      const data = await api('/api/update/apply', {
        method: 'POST',
        body: JSON.stringify({
          strategy: stash ? 'stash_if_needed' : 'refuse_on_dirty',
          force_active_jobs: force,
        }),
      }).catch(err => ({ success: false, error: String(err) }));
      if (result) result.textContent = JSON.stringify(data, null, 2);
      await refreshUpdateStatus();
      await refreshUpdateHistory();
      await refreshRestartBanner();
    }

    async function rollbackUpdateFromUI() {
      if (!confirm('Rollback to the previous build? This runs git reset --hard to the prior SHA. Requires a clean working tree.')) return;
      const result = $('updateActionResult');
      if (result) result.textContent = 'rolling back…';
      const data = await api('/api/update/rollback', {
        method: 'POST', body: JSON.stringify({}),
      }).catch(err => ({ success: false, error: String(err) }));
      if (result) result.textContent = JSON.stringify(data, null, 2);
      await refreshUpdateHistory();
      await refreshUpdateStatus();
    }

    async function refreshRestartBanner() {
      const banner = $('restartNeededBanner');
      if (!banner) return;
      const data = await api('/api/restart_needed').catch(() => ({ needed: false }));
      if (data && data.needed) {
        banner.hidden = false;
        const detail = $('restartBannerDetail');
        if (detail) {
          detail.textContent = `from ${data.from_version || '?'} → ${data.to_version || '?'} at ${data.applied_at || ''}`;
        }
      } else {
        banner.hidden = true;
      }
    }

    async function ackRestart() {
      const data = await api('/api/restart_needed/clear', {
        method: 'POST', body: JSON.stringify({}),
      }).catch(() => ({ success: false }));
      await refreshRestartBanner();
    }

    async function setUpdateChannel(value) {
      await api('/api/update/channel', {
        method: 'POST',
        body: JSON.stringify({ channel: value }),
      }).catch(() => null);
      await refreshUpdateStatus();
    }

    // ─── Media Pool History table (was: Provenance) ─────────────────
    state.mpc = state.mpc || { allChanges: [], actions: new Set() };

    function populateMpcActionFilter(actions) {
      const sel = $('mpcActionFilter');
      if (!sel) return;
      const prev = sel.value;
      const sorted = Array.from(actions).sort();
      sel.innerHTML = '<option value="">all actions</option>' +
        sorted.map(a => `<option value="${escapeHtml(a)}">${escapeHtml(a)}</option>`).join('');
      if (sorted.includes(prev)) sel.value = prev;
    }

    function renderMpcRows(rows) {
      const el = $('mpcTable');
      if (!el) return;
      const meta = $('mpcMeta');
      if (!rows.length) {
        el.innerHTML = '<div class="empty">no media-pool changes recorded</div>';
        if (meta) meta.textContent = '';
        return;
      }
      const header = `
        <div class="mpc-row header">
          <span>timestamp</span><span>action</span><span>target</span><span>initiator</span><span>run id</span>
        </div>`;
      const groupBy = !!$('mpcGroupByClip')?.checked;
      const renderRow = (c) => {
        const ts = escapeHtml(formatVersionDate(c.created_at));
        const action = escapeHtml(c.action || '');
        const tname = c.target_name || '';
        const tid = c.target_id || '';
        const clipId = (c.params && (c.params.clip_id || c.params.id || c.params.target_id)) || null;
        const targetCell = clipId
          ? `<div class="target-cell"><a class="clip-link" data-clip-jump="${escapeHtml(clipId)}">${escapeHtml(tname || clipId)}</a><span class="target-id">${escapeHtml(tid || clipId)}</span></div>`
          : `<div class="target-cell"><span class="target-name">${escapeHtml(tname || tid || '—')}</span>${tid && tname ? `<span class="target-id">${escapeHtml(tid)}</span>` : ''}</div>`;
        return `
          <div class="mpc-row">
            <span>${ts}</span>
            <span class="action-name">${action}</span>
            ${targetCell}
            <span>${escapeHtml(c.initiator || '')}</span>
            <span class="run-id" title="${escapeHtml(c.analysis_run_id || '')}">${escapeHtml((c.analysis_run_id || '—').slice(0, 18))}</span>
          </div>`;
      };
      let body = '';
      if (groupBy) {
        const groups = new Map();
        for (const c of rows) {
          const key = (c.target_name || c.target_id || '—');
          if (!groups.has(key)) groups.set(key, []);
          groups.get(key).push(c);
        }
        for (const [key, items] of groups) {
          body += `<div class="mpc-row group"><span>${escapeHtml(key)}</span><span class="group-count">${items.length} change${items.length === 1 ? '' : 's'}</span></div>`;
          body += items.map(renderRow).join('');
        }
      } else {
        body = rows.map(renderRow).join('');
      }
      el.innerHTML = header + body;
      if (meta) meta.textContent = `${rows.length} record${rows.length === 1 ? '' : 's'}`;
    }

    async function refreshMpcTable() {
      const limit = parseInt(($('mpcLimit')?.value || '50'), 10) || 50;
      const data = await api(`/api/media_pool_changes?limit=${limit}`).catch(() => ({ success: false }));
      if (!data || !data.success) {
        renderMpcRows([]);
        return;
      }
      const changes = data.changes || [];
      state.mpc.allChanges = changes;
      const actions = new Set(changes.map(c => c.action).filter(Boolean));
      state.mpc.actions = actions;
      populateMpcActionFilter(actions);
      applyMpcFilter();
    }

    function applyMpcFilter() {
      const filter = ($('mpcActionFilter')?.value || '').trim();
      const rows = filter
        ? state.mpc.allChanges.filter(c => c.action === filter)
        : state.mpc.allChanges;
      renderMpcRows(rows);
    }

    // ─── Analysis caps widget ────────────────────────────────────────────
    state.caps = state.caps || { preset: 'standard', usage: null, debounce: null, presetsAvailable: null };

    const CAPS_OVERRIDE_FIELDS = [
      ['capsOvResponseChars', 'response_chars'],
      ['capsOvVisionClip', 'vision_tokens_per_clip'],
      ['capsOvFramesClip', 'frames_per_clip'],
      ['capsOvVisionJob', 'vision_tokens_per_job'],
      ['capsOvVisionDay', 'vision_tokens_per_day'],
      ['capsOvWallClock', 'wall_clock_seconds_per_call'],
      ['capsOvFrameDim', 'max_frame_dim_pixels'],
    ];

    const CAPS_PRESET_TAGS = {
      minimal: 'Preview / triage',
      standard: 'Realistic default',
      generous: 'High-fidelity, few clips',
      unlimited: 'Guards off — use with care',
    };

    const CAPS_PRESET_STAT_ORDER = [
      ['response_chars', 'response chars'],
      ['vision_tokens_per_clip', 'tokens / clip'],
      ['frames_per_clip', 'frames / clip'],
      ['vision_tokens_per_job', 'tokens / job'],
      ['vision_tokens_per_day', 'tokens / day'],
      ['wall_clock_seconds_per_call', 'wall clock (s)'],
      ['max_frame_dim_pixels', 'frame dim px'],
    ];

    function formatCapValue(v) {
      if (v === null || v === undefined) return '∞';
      if (typeof v === 'number') {
        if (v >= 1000) return (v / 1000).toFixed(v % 1000 === 0 ? 0 : 1).replace(/\.0$/, '') + 'k';
        return String(v);
      }
      return String(v);
    }

    function renderCapsPresetCards() {
      const container = $('capsPresetCards');
      if (!container) return;
      const presets = state.caps.presetsAvailable || {};
      const order = ['minimal', 'standard', 'generous', 'unlimited'];
      const active = state.caps.preset || 'standard';
      container.innerHTML = order.filter(k => presets[k]).map(key => {
        const p = presets[key];
        const stats = CAPS_PRESET_STAT_ORDER.map(([field, label]) => `
          <span class="stat-label">${escapeHtml(label)}</span>
          <span class="stat-value">${escapeHtml(formatCapValue(p[field]))}</span>
        `).join('');
        return `
          <button type="button" class="caps-preset-card${key === active ? ' is-active' : ''}" data-preset-card="${escapeHtml(key)}" role="radio" aria-checked="${key === active ? 'true' : 'false'}">
            <div class="caps-preset-card-head">
              <span class="caps-preset-card-name">${escapeHtml(key)}</span>
              ${key === active ? '<span class="caps-preset-card-badge">Active</span>' : ''}
            </div>
            <div class="caps-preset-card-tag">${escapeHtml(CAPS_PRESET_TAGS[key] || '')}</div>
            <div class="caps-preset-card-stats">${stats}</div>
          </button>
        `;
      }).join('');
    }

    function applyCapsOverridePlaceholders(presetKey) {
      const presets = state.caps.presetsAvailable || {};
      const p = presets[presetKey] || presets[state.caps.preset] || {};
      for (const [domId, key] of CAPS_OVERRIDE_FIELDS) {
        const el = $(domId);
        if (!el) continue;
        const val = p[key];
        el.placeholder = (val === null || val === undefined) ? '∞' : `${presetKey}: ${val}`;
      }
    }

    async function refreshCapsWidget() {
      const data = await api('/api/caps').catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) return;
      state.caps.preset = data.preset;
      state.caps.usage = data.usage || null;
      state.caps.presetsAvailable = data.presets_available || state.caps.presetsAvailable;
      const presetEl = $('prefCapsPreset');
      if (presetEl) presetEl.value = data.preset;
      renderCapsPresetCards();
      applyCapsOverridePlaceholders(data.preset);
      // Render usage gauges (only if a project is open, otherwise the usage
      // block stays at its placeholder).
      const usage = data.usage;
      if (usage) {
        renderCapsGauge('clip', usage.usage?.clip?.vision_tokens, usage.caps?.vision_tokens_per_clip, usage.percent_consumed?.clip);
        renderCapsGauge('job', usage.usage?.job?.vision_tokens, usage.caps?.vision_tokens_per_job, usage.percent_consumed?.job);
        renderCapsGauge('day', usage.usage?.day?.vision_tokens, usage.caps?.vision_tokens_per_day, usage.percent_consumed?.day);
      }
    }

    function renderCapsGauge(scope, used, cap, percent) {
      const gauge = document.querySelector(`.caps-gauge[data-scope="${scope}"]`);
      if (!gauge) return;
      const fill = gauge.querySelector('.caps-gauge-fill');
      const numbers = gauge.querySelector('.caps-gauge-numbers');
      const u = used ?? 0;
      if (cap === null || cap === undefined) {
        fill.style.width = '0%';
        numbers.textContent = `${formatCapValue(u)} / ∞`;
        gauge.dataset.state = '';
        return;
      }
      const p = percent != null ? percent : (cap > 0 ? Math.min(100, 100 * u / cap) : 0);
      fill.style.width = `${p}%`;
      numbers.textContent = `${formatCapValue(u)} / ${formatCapValue(cap)}  ·  ${p.toFixed(0)}%`;
      gauge.dataset.state = p >= 90 ? 'over' : (p >= 70 ? 'warn' : '');
    }

    function persistCapsFromUI() {
      const presetEl = $('prefCapsPreset');
      const preset = (presetEl && presetEl.value) || 'standard';
      const overrides = {};
      for (const [domId, key] of CAPS_OVERRIDE_FIELDS) {
        const el = $(domId);
        if (!el) continue;
        const raw = (el.value || '').trim();
        if (!raw) continue;
        overrides[key] = raw === 'unlimited' ? null : (Number.isFinite(+raw) ? +raw : raw);
      }
      clearTimeout(state.caps.debounce);
      state.caps.debounce = setTimeout(async () => {
        const result = await api('/api/caps', {
          method: 'POST',
          body: JSON.stringify({ preset, overrides }),
        }).catch(err => ({ success: false, error: String(err) }));
        if (!result || !result.success) {
          console.warn('caps save failed:', result?.error);
        }
        await refreshCapsWidget();
      }, 300);
    }

    function reviewSetView(view, opts = {}) {
      state.review.view = view;
      $('reviewBinView').style.display = view === 'bin' ? '' : 'none';
      $('reviewClipView').style.display = view === 'clip' ? '' : 'none';
      $('reviewShotView').style.display = view === 'shot' ? '' : 'none';
      const transcriptEl = $('reviewTranscriptView');
      if (transcriptEl) transcriptEl.style.display = view === 'transcript' ? '' : 'none';
      const combinedEl = $('reviewCombinedView');
      if (combinedEl) combinedEl.style.display = view === 'combined' ? '' : 'none';
      const historyEl = $('reviewHistoryView');
      if (historyEl) historyEl.style.display = view === 'history' ? '' : 'none';
      const plansEl = $('reviewPlansView');
      if (plansEl) plansEl.style.display = view === 'plans' ? '' : 'none';
      const planEl = $('reviewPlanView');
      if (planEl) planEl.style.display = view === 'plan' ? '' : 'none';
      const back = $('reviewBackBtn');
      if (back) back.style.display = view === 'bin' ? 'none' : '';
      const meta = $('reviewMeta');
      if (meta) {
        if (view === 'bin') meta.textContent = 'Bin overview · click a clip to drill into shot detail.';
        else if (view === 'clip') meta.textContent = state.review.currentClipData?.card?.clip_name || 'Clip detail';
        else if (view === 'shot') meta.textContent = `Shot ${state.review.currentShotIndex} of ${state.review.currentClipData?.card?.clip_name || 'clip'}`;
        else if (view === 'transcript') meta.textContent = `Transcript · ${state.review.currentClipData?.card?.clip_name || 'clip'}`;
        else if (view === 'combined') meta.textContent = `Combined review · ${state.review.combinedData?.clip_count || '?'} clips`;
        else if (view === 'history') meta.textContent = 'Timeline history · archived versions and brain edits per timeline';
        else if (view === 'plans') meta.textContent = 'Edit plans · dry-run plans saved by the edit engine';
        else if (view === 'plan') meta.textContent = `Plan ${state.plans?.currentPlanId || ''} · review here, execute from chat`;
      }
      if (opts.writePanelState !== false) {
        writePanelStateAsync({
          current_view: view,
          current_clip_id: state.review.currentClipId,
          current_shot_index: state.review.currentShotIndex,
        }).catch(() => {});
      }
      if (opts.pushHash !== false) refreshReviewHash();
    }

    async function refreshReviewBin() {
      const summary = $('reviewBinSummary');
      if (summary) summary.textContent = 'Loading analyzed clips…';
      const data = await api('/api/clips').catch(err => ({ success: false, error: String(err) }));
      state.review.clipList = data;
      populateBinFilter();
      renderReviewBin();
      // Coverage runs in parallel — failures here must not block the clip grid.
      refreshReadinessCard().catch(() => {});
      refreshEntitiesCard().catch(() => {});
    }

    // Recurring people/places/props detected across the bin (Phase D).
    // Hidden until at least one labeled entity exists.
    async function refreshEntitiesCard() {
      const card = $('reviewEntitiesCard');
      if (!card) return;
      const data = await api('/api/entities').catch(() => null);
      const labeled = (data?.entities || []).filter(e => e.label);
      if (!labeled.length) { card.style.display = 'none'; return; }
      card.style.display = '';
      card.innerHTML = `<div class="review-entities-title">Recurring across this bin</div>
        <div class="review-entities-chips">${labeled.map(e =>
          `<span class="review-chip" title="${escapeHtml(e.description || '')}">${escapeHtml(e.label)} · ${e.kind || 'unknown'} · ${e.shot_count || e.cluster_size || 0} shots</span>`
        ).join('')}</div>`;
    }

    async function refreshReadinessCard() {
      const card = $('reviewReadinessCard');
      if (!card) return;
      const data = await api('/api/coverage').catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        card.hidden = true;
        return;
      }
      card.hidden = false;
      const summary = data.summary || {};
      const evidence = $('readinessEvidenceBase');
      const row = $('readinessSummaryRow');
      const details = $('readinessDetails');
      const total = summary.clips_total_with_reports || 0;
      const signed = summary.clips_signed || 0;
      const superseded = summary.clips_superseded_by_relink || 0;
      const visionPending = summary.clips_vision_pending || 0;
      const warnings = summary.technical_warning_count || 0;
      const pct = total ? Math.round((signed / total) * 100) : 0;
      const trustDist = summary.source_trust_distribution || {};
      const layers = summary.layer_coverage || {};
      const fragments = [`${signed}/${total} clips analyzed (${pct}%)`];
      if (superseded) fragments.push(`${superseded} relink-superseded`);
      if (visionPending) fragments.push(`${visionPending} vision pending`);
      if (warnings) fragments.push(`${warnings} warnings`);
      if (evidence) evidence.textContent = 'evidence base: ' + fragments.join(', ') + '.';
      if (row) {
        row.innerHTML = [
          { label: 'Analyzed', value: signed, kind: 'good' },
          { label: 'Superseded', value: superseded, kind: superseded ? 'danger' : '' },
          { label: 'Vision pending', value: visionPending, kind: visionPending ? 'warn' : '' },
          { label: 'Warnings', value: warnings, kind: warnings ? 'warn' : '' },
        ].map(stat => `<div class="readiness-stat ${stat.kind}"><span class="stat-value">${stat.value}</span><span class="stat-label">${escapeHtml(stat.label)}</span></div>`).join('');
      }
      if (details) {
        const TRUST_LABELS = { trusted: 'Trusted source', unknown: 'Unverified source', untrusted: 'Untrusted source' };
        const LAYER_LABELS = {
          technical: 'Technical', motion: 'Motion', transcription: 'Transcript',
          vision: 'Vision', cut_analysis: 'Cut analysis', readthrough: 'Readthrough',
        };
        const trustChips = Object.entries(trustDist)
          .sort((a, b) => b[1] - a[1])
          .map(([k, v]) => `<span class="chip" title="clips by source trust">${escapeHtml(TRUST_LABELS[k] || k)} · ${v}</span>`)
          .join('');
        const layerChips = Object.entries(LAYER_LABELS)
          .filter(([layer]) => layers[layer])
          .map(([layer, label]) => `<span class="chip" title="clips with this analysis layer">${escapeHtml(label)} · ${layers[layer]}</span>`)
          .join('');
        details.innerHTML = trustChips + layerChips;
      }
    }

    function populateBinFilter() {
      const data = state.review.clipList;
      const select = $('reviewBinFilter');
      if (!select || !data || !data.clips) return;
      const bins = new Set();
      for (const c of data.clips) {
        if (c.bin_path) bins.add(c.bin_path);
      }
      const sorted = Array.from(bins).sort();
      const current = state.review.binFilter;
      select.innerHTML = `<option value="">All bins (${data.clips.length})</option>` +
        sorted.map(b => `<option value="${escapeHtml(b)}" ${b === current ? 'selected' : ''}>${escapeHtml(b)}</option>`).join('');
    }

    function filteredClips() {
      const data = state.review.clipList;
      if (!data || !data.clips) return [];
      const binFilter = state.review.binFilter || '';
      return data.clips.filter(c => !binFilter || c.bin_path === binFilter);
    }

    function renderReviewBin() {
      const grid = $('reviewBinGrid');
      const summary = $('reviewBinSummary');
      const searchEl = $('reviewSearchResults');
      const data = state.review.clipList;
      if (state.review.searchQuery) {
        // Server-side search rendering is in renderSearchResults().
        if (grid) grid.style.display = 'none';
        if (searchEl) searchEl.style.display = '';
        renderSearchResults();
        return;
      }
      if (grid) grid.style.display = '';
      if (searchEl) searchEl.style.display = 'none';
      if (!data || !data.success) {
        if (summary) summary.textContent = (data && data.error) || 'No analyzed clips yet.';
        if (grid) grid.innerHTML = '';
        return;
      }
      const clips = filteredClips();
      if (!clips.length) {
        if (state.review.binFilter) {
          if (summary) summary.textContent = `No analyzed clips in bin "${state.review.binFilter}".`;
          if (grid) grid.innerHTML = '';
        } else {
          if (summary) summary.textContent = 'Nothing analyzed yet.';
          if (grid) grid.innerHTML = chatPromptCard(
            'Review fills in as clips are analyzed. Ask your assistant to analyze this project\u2019s media:',
            'Analyze the source clips in my current Resolve project and build the search index.'
          );
        }
        return;
      }
      const selected = state.review.selectedBinClipIds;
      // Prune any selected ids that aren't in the visible set after a filter change.
      const visibleIds = new Set(clips.map(c => c.clip_id));
      Array.from(selected).forEach(id => { if (!visibleIds.has(id)) selected.delete(id); });
      if (summary) {
        const total = data.clips.length;
        const base = state.review.binFilter
          ? `${clips.length} of ${total} analyzed clip${total === 1 ? '' : 's'} · bin: ${state.review.binFilter}`
          : `${total} analyzed clip${total === 1 ? '' : 's'} in this project\u2019s analysis root.`;
        if (selected.size > 0) {
          summary.innerHTML = `<span>${escapeHtml(base)}</span>
            <span class="bin-selection-toolbar">
              <span class="status-pill pill-info">${selected.size} selected</span>
              <button class="secondary" id="binSelectionActionsBtn">Actions ▾</button>
              <button class="secondary" id="binSelectionClearBtn">Clear</button>
            </span>`;
        } else {
          summary.textContent = base;
        }
      }
      if (grid) {
        const isList = state.review.viewMode === 'list';
        grid.className = isList ? 'review-list' : 'review-grid';
        grid.innerHTML = clips.map(clip => {
          const thumb = clip.representative_frame_index && clip.clip_id
            ? `<img class="review-thumb" loading="lazy" src="/api/clips/${encodeURIComponent(clip.clip_id)}/frames/${clip.representative_frame_index}" alt="${escapeHtml(clip.clip_name || '')}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'review-thumb placeholder',textContent:'no thumbnail'}))">`
            : `<div class="review-thumb placeholder">no thumbnail</div>`;
          const chip = clip.select_potential
            ? `<span class="review-chip ${selectChipClass(clip.select_potential)}">${escapeHtml(clip.select_potential)}</span>`
            : '';
          const primaryUse = clip.primary_use ? `<span class="review-chip">${escapeHtml(clip.primary_use)}</span>` : '';
          const dur = formatDuration(clip.duration_seconds);
          const shots = clip.shot_count != null ? `${clip.shot_count} shots` : '—';
          const isSelected = selected.has(clip.clip_id);
          return `<div class="review-clip-card${isSelected ? ' is-selected' : ''}" data-clip-id="${escapeHtml(clip.clip_id || '')}" tabindex="0" role="button" aria-label="${escapeHtml(clip.clip_name || '')}" aria-selected="${isSelected ? 'true' : 'false'}">
            <button class="review-card-select" type="button" data-select-clip="${escapeHtml(clip.clip_id || '')}" title="${isSelected ? 'Deselect' : 'Select'}" aria-pressed="${isSelected ? 'true' : 'false'}">
              <span class="select-box">${isSelected ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>' : ''}</span>
            </button>
            ${thumb}
            <div class="review-clip-card-name">${escapeHtml(clip.clip_name || '')}</div>
            <div class="review-clip-card-meta"><span>${dur}</span><span>${shots}</span>${primaryUse}${chip}</div>
            ${clip.clip_summary_oneliner ? `<div class="review-clip-card-oneliner">${escapeHtml(clip.clip_summary_oneliner)}</div>` : ''}
          </div>`;
        }).join('');
      }
    }

    function smpteFromSeconds(seconds, fps) {
      if (seconds == null) return '—';
      const f = Number(fps) > 0 ? Number(fps) : 24;
      const total = Math.max(0, Math.round(Number(seconds) * f));
      const ff = total % Math.round(f);
      const ss = Math.floor(total / f);
      const hh = Math.floor(ss / 3600);
      const mm = Math.floor((ss % 3600) / 60);
      const s = ss % 60;
      const pad = (n) => String(n).padStart(2, '0');
      return `${pad(hh)}:${pad(mm)}:${pad(s)}:${pad(ff)}`;
    }

    async function runReviewSearch(query) {
      state.review.searchQuery = query;
      if (!query) {
        state.review.searchResults = null;
        renderReviewBin();
        return;
      }
      const semantic = !!$('reviewSemanticCheckbox')?.checked;
      const endpoint = semantic
        ? `/api/search/semantic?q=${encodeURIComponent(query)}&limit=40`
        : `/api/index/query?q=${encodeURIComponent(query)}&limit=40`;
      const payload = await api(endpoint)
        .catch(err => ({ success: false, error: String(err) }));
      state.review.searchResults = payload;
      renderReviewBin();
    }

    function renderSearchResults() {
      const wrap = $('reviewSearchResults');
      const data = state.review.searchResults;
      const summary = $('reviewBinSummary');
      if (!wrap) return;
      if (!data || !data.success) {
        wrap.innerHTML = `<div class="empty">${escapeHtml((data && data.error) || 'Search failed.')}</div>`;
        if (summary) summary.textContent = `Search for "${state.review.searchQuery}" failed.`;
        return;
      }
      const binFilter = state.review.binFilter || '';
      const clipBins = new Map((state.review.clipList?.clips || []).map(c => [c.clip_id, c.bin_path]));
      const rows = (data.results || []).filter(r => {
        if (!binFilter) return true;
        return (r.clip_id && clipBins.get(r.clip_id) === binFilter);
      });
      if (summary) {
        summary.textContent = `${rows.length} result${rows.length === 1 ? '' : 's'} for "${state.review.searchQuery}"${binFilter ? ` · bin: ${binFilter}` : ''}`;
      }
      if (!rows.length) {
        wrap.innerHTML = '<div class="empty">No matches in the analysis index.</div>';
        return;
      }
      wrap.innerHTML = rows.map(row => {
        const clipId = row.clip_id;
        const shotIndex = row.shot_index;
        const fps = row.fps;
        const thumbIndex = row.thumbnail_frame_index;
        const thumb = thumbIndex && clipId
          ? `<img class="thumb" loading="lazy" src="/api/clips/${encodeURIComponent(clipId)}/frames/${thumbIndex}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'thumb',textContent:''}))">`
          : `<div class="thumb"></div>`;
        const tc = row.start_seconds != null ? smpteFromSeconds(row.start_seconds, fps) : '';
        const isTranscript = String(row.result_type || '') === 'transcript';
        const hash = clipId
          ? (isTranscript
              ? `#analysis/review/clip/${encodeURIComponent(clipId)}/transcript`
              : (shotIndex != null
                  ? `#analysis/review/clip/${encodeURIComponent(clipId)}/shot/${shotIndex}`
                  : `#analysis/review/clip/${encodeURIComponent(clipId)}`))
          : '#analysis/review';
        const fallbackText = row.summary || row.file_path || '';
        const snippetHtml = renderSearchSnippet(row.snippet)
          || highlightQueryInText(fallbackText, state.review.searchQuery);
        return `<a class="review-search-card" href="${hash}" data-clip-id="${escapeHtml(clipId || '')}" data-shot-index="${shotIndex != null ? shotIndex : ''}" data-transcript-start="${isTranscript && row.start_seconds != null ? row.start_seconds : ''}">
          ${thumb}
          <div>
            <div class="meta-row"><span class="type">${escapeHtml(row.result_type || '')}</span>${tc ? `<span class="tc">${escapeHtml(tc)}</span>` : ''}${shotIndex != null ? `<span class="review-chip">shot ${shotIndex}</span>` : ''}</div>
            <div class="clip-name">${escapeHtml(row.clip_name || row.clip_key || '')}</div>
            <div class="summary">${snippetHtml}</div>
          </div>
          <div></div>
        </a>`;
      }).join('');
      // Intercept transcript-result clicks so we can pass focusSeconds into
      // openTranscript and pre-fill the filter with the search query, scrolling
      // the matching segment into view.
      wrap.querySelectorAll('a.review-search-card[data-transcript-start]').forEach(card => {
        const start = card.dataset.transcriptStart;
        if (!start) return;
        card.addEventListener('click', (event) => {
          event.preventDefault();
          const clipId = card.dataset.clipId;
          if (!clipId) return;
          state.review.transcriptFilter = state.review.searchQuery || '';
          openTranscript(clipId, { focusSeconds: Number(start) }).catch(alertError);
        });
      });
    }

    // FTS5 snippet() wraps matched terms with our sentinel tokens. Convert to
    // <mark> after escaping the rest of the snippet text — never inject raw
    // user data into the DOM.
    function renderSearchSnippet(rawSnippet) {
      if (!rawSnippet) return '';
      const escaped = escapeHtml(String(rawSnippet));
      return escaped
        .replace(/\[\[hi\]\]/g, '<mark class="search-hit">')
        .replace(/\[\[\/hi\]\]/g, '</mark>');
    }

    // Fallback highlighter for results that came back without an FTS snippet
    // (the LIKE-fallback path). Wraps every case-insensitive occurrence of
    // each whitespace-delimited query token with <mark>, after escaping the
    // raw text so we never inject HTML.
    function highlightQueryInText(text, query) {
      const raw = String(text || '');
      if (!raw) return '';
      const escaped = escapeHtml(raw);
      const q = String(query || '').trim();
      if (!q) return escaped;
      const tokens = q.split(/\s+/).filter(Boolean).map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
      if (!tokens.length) return escaped;
      const re = new RegExp(`(${tokens.join('|')})`, 'gi');
      return escaped.replace(re, '<mark class="search-hit">$1</mark>');
    }

    async function openClipDetail(clipId, opts = {}) {
      if (!clipId) return;
      state.review.currentClipId = clipId;
      state.review.currentShotIndex = null;
      const data = await api(`/api/clips/${encodeURIComponent(clipId)}`).catch(err => ({ success: false, error: String(err) }));
      state.review.currentClipData = data;
      reviewSetView('clip', opts);
      renderClipDetail();
    }

    function renderClipDetail() {
      const data = state.review.currentClipData;
      if (!data || !data.success) {
        $('reviewClipHeader').innerHTML = `<div class="empty">${escapeHtml((data && data.error) || 'Clip not found.')}</div>`;
        $('reviewClipSummary').innerHTML = '';
        $('reviewClipTags').innerHTML = '';
        setHtml('reviewClipAnalysisBlocks', '');
        $('reviewShotStrip').innerHTML = '';
        $('reviewClipCrossShot').innerHTML = '';
        return;
      }
      const card = data.card || {};
      const cls = data.editorial_classification || {};
      const shots = data.shots || [];
      const tags = (data.editing_notes && data.editing_notes.search_tags) || [];
      $('reviewClipHeader').innerHTML = `
        <span class="name">${escapeHtml(card.clip_name || '')}</span>
        <span class="meta">${formatDuration(card.duration_seconds)} · ${shots.length} shots</span>
        ${cls.primary_use ? `<span class="review-chip">${escapeHtml(cls.primary_use)}</span>` : ''}
        ${cls.select_potential ? `<span class="review-chip ${selectChipClass(cls.select_potential)}">${escapeHtml(cls.select_potential)}</span>` : ''}
        <div class="actions"><button class="secondary" id="reviewClipTranscriptBtn">Transcript</button><button class="secondary" id="reviewClipOpenInResolveBtn">Open in Resolve</button><button class="secondary" data-copy-chat-prompt="${escapeHtml(`Deepen the analysis of clip “${card.clip_name || state.review.currentClipId}”: call media_analysis(action="deepen", params={"clip_id": "${card.clip_id || state.review.currentClipId}"}), show me the cost estimate, and after I confirm, read the frames and commit the per-shot fields via commit_shot_vision.`)}">Deepen analysis</button></div>
      `;
      $('reviewClipSummary').textContent = data.clip_summary || data.clip_summary_oneliner || '';
      $('reviewClipTags').innerHTML = tags.map(t => `<span class="review-chip">${escapeHtml(t)}</span>`).join('');
      const clipScope = 'clip-' + (card.clip_id || state.review.currentClipId);
      const clipRating = readCorrectionValue(data.corrections || {}, 'clip', card.clip_id || state.review.currentClipId, 'user.rating') || 0;
      const clipNotes = readCorrectionValue(data.corrections || {}, 'clip', card.clip_id || state.review.currentClipId, 'user.notes') || '';
      $('reviewClipRating').innerHTML = renderStarsWidget(clipRating, clipScope);
      $('reviewClipNotes').innerHTML = renderNotesWidget(clipNotes, clipScope);
      const clipId = card.clip_id || state.review.currentClipId;
      $('reviewShotStrip').innerHTML = shots.map(shot => {
        const idx = shot.shot_index;
        const frameIndices = shot.frame_indices_used || shot.frame_indices || [];
        const repIndex = frameIndices && frameIndices.length ? frameIndices[0] : null;
        const thumb = repIndex && clipId
          ? `<img class="review-thumb" loading="lazy" src="/api/clips/${encodeURIComponent(clipId)}/frames/${repIndex}" alt="shot ${idx}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'review-thumb placeholder',textContent:'no frame'}))">`
          : `<div class="review-thumb placeholder">no frame</div>`;
        const role = shot.editorial && shot.editorial.editorial_role ? shot.editorial.editorial_role : (shot.editorial_role || '');
        return `<div class="review-shot-strip-card" data-shot-index="${idx}" tabindex="0" role="button" aria-label="Shot ${idx}">
          ${thumb}
          <div class="label"><span>#${idx}</span><span class="role">${escapeHtml(role)}</span></div>
        </div>`;
      }).join('');
      setHtml('reviewClipAnalysisBlocks', renderClipAnalysisBlocks(data));
      // The cross-shot summary row at the bottom is now redundant with the
      // dedicated Cross-shot analysis block. Clear it to avoid duplication.
      $('reviewClipCrossShot').innerHTML = '';
    }

    // ─── Clip-level analysis blocks (the rich layer from the vision schema) ─
    function clipBlockRow(label, value) {
      const text = formatClipBlockValue(value);
      if (text == null) return '';
      return `<div class="block-row"><span class="label">${escapeHtml(label)}</span><span class="value">${text}</span></div>`;
    }
    function clipBlockChips(values, toneFn) {
      if (!Array.isArray(values) || !values.length) return '<div class="block-empty">—</div>';
      return `<div class="chip-row">${values.map(v => {
        const text = formatClipBlockValue(v, { inline: true });
        const tone = toneFn ? ` ${toneFn(v)}` : '';
        return text == null ? '' : `<span class="review-chip${tone}">${text}</span>`;
      }).join('')}</div>`;
    }
    function clipBlockList(items) {
      if (!Array.isArray(items) || !items.length) return '<div class="block-empty">—</div>';
      return `<ul class="block-list">${items.map(i => {
        const text = formatClipBlockValue(i, { inline: true });
        return text == null ? '' : `<li>${text}</li>`;
      }).join('')}</ul>`;
    }
    function formatClipBlockValue(value, opts = {}) {
      if (value == null || value === '') return null;
      if (typeof value === 'string') return escapeHtml(value);
      if (typeof value === 'number' || typeof value === 'boolean') return escapeHtml(String(value));
      if (Array.isArray(value)) {
        if (!value.length) return null;
        return escapeHtml(value.map(v => (typeof v === 'object' ? JSON.stringify(v) : String(v))).join(', '));
      }
      if (typeof value === 'object') {
        const parts = [];
        for (const [k, v] of Object.entries(value)) {
          if (v == null || v === '' || (Array.isArray(v) && !v.length)) continue;
          parts.push(`${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`);
        }
        return parts.length ? escapeHtml(parts.join(' · ')) : null;
      }
      return escapeHtml(String(value));
    }
    function clipBlock(title, rowsHtml, opts = {}) {
      const conf = opts.confidence ? `<span class="conf ${escapeHtml(String(opts.confidence))}">${escapeHtml(String(opts.confidence))}</span>` : '';
      const body = rowsHtml && rowsHtml.replace(/\s/g, '').length
        ? rowsHtml
        : '<div class="block-empty">Not populated.</div>';
      return `<div class="review-analysis-block">
        <div class="block-title">${escapeHtml(title)}${conf}</div>
        ${body}
      </div>`;
    }

    function renderClipAnalysisBlocks(data) {
      const blocks = [];
      const conf = data.confidence || {};

      // Editorial classification
      const ec = data.editorial_classification || {};
      if (Object.keys(ec).length) {
        const rows = [
          clipBlockRow('Primary use', ec.primary_use),
          clipBlockRow('Select potential', ec.select_potential),
          clipBlockRow('Energy arc', ec.energy_arc),
          clipBlockRow('Style', ec.style),
          ec.genre_indicators && ec.genre_indicators.length
            ? `<div class="block-row"><span class="label">Genre</span><span class="value">${clipBlockChips(ec.genre_indicators)}</span></div>`
            : '',
          clipBlockRow('Reason', ec.reason),
        ].join('');
        blocks.push(clipBlock('Editorial classification', rows));
      }

      // Shot & style (clip-wide visual character)
      const ss = data.shot_and_style || {};
      if (Object.keys(ss).length) {
        const rows = [
          ss.shot_sizes && ss.shot_sizes.length
            ? `<div class="block-row"><span class="label">Shot sizes</span><span class="value">${clipBlockChips(ss.shot_sizes)}</span></div>` : '',
          ss.camera_motion && ss.camera_motion.length
            ? `<div class="block-row"><span class="label">Camera motion</span><span class="value">${clipBlockChips(ss.camera_motion)}</span></div>` : '',
          clipBlockRow('Composition', ss.composition_notes),
          clipBlockRow('Lighting mood', ss.lighting_mood),
          clipBlockRow('Color mood', ss.color_mood),
        ].join('');
        blocks.push(clipBlock('Shot & style', rows, { confidence: conf.visual }));
      }

      // Content
      const ct = data.content || {};
      if (Object.keys(ct).length) {
        const rows = [
          ct.locations && ct.locations.length
            ? `<div class="block-row"><span class="label">Locations</span><span class="value">${clipBlockChips(ct.locations)}</span></div>` : '',
          clipBlockRow('People visible', ct.people_visible),
          ct.actions && ct.actions.length
            ? `<div class="block-row"><span class="label">Actions</span><span class="value">${clipBlockList(ct.actions)}</span></div>` : '',
          ct.objects && ct.objects.length
            ? `<div class="block-row"><span class="label">Objects</span><span class="value">${clipBlockChips(ct.objects)}</span></div>` : '',
          ct.visible_text && ct.visible_text.length
            ? `<div class="block-row"><span class="label">Visible text</span><span class="value">${clipBlockChips(ct.visible_text)}</span></div>` : '',
          ct.notable_audio_context && ct.notable_audio_context.length
            ? `<div class="block-row"><span class="label">Audio</span><span class="value">${clipBlockList(ct.notable_audio_context)}</span></div>` : '',
        ].join('');
        blocks.push(clipBlock('Content', rows));
      }

      // Cut understanding
      const cu = data.cut_understanding || {};
      if (Object.keys(cu).length) {
        const rows = [
          clipBlockRow('Cut count', cu.cut_count),
          clipBlockRow('Edited sequence', cu.likely_edited_sequence === true ? 'yes' : (cu.likely_edited_sequence === false ? 'no' : null)),
          cu.flash_frame_candidates && cu.flash_frame_candidates.length
            ? `<div class="block-row"><span class="label">Flash candidates</span><span class="value">${clipBlockList(cu.flash_frame_candidates)}</span></div>` : '',
          cu.notes && cu.notes.length
            ? `<div class="block-row"><span class="label">Notes</span><span class="value">${clipBlockList(cu.notes)}</span></div>` : '',
        ].join('');
        blocks.push(clipBlock('Cut understanding', rows));
      }

      // Editing notes
      const en = data.editing_notes || {};
      if (Object.keys(en).length) {
        const rows = [
          en.best_moments && en.best_moments.length
            ? `<div class="block-row"><span class="label">Best moments</span><span class="value">${clipBlockList(en.best_moments)}</span></div>` : '',
          en.continuity_flags && en.continuity_flags.length
            ? `<div class="block-row"><span class="label">Continuity flags</span><span class="value">${clipBlockList(en.continuity_flags)}</span></div>` : '',
          en.qc_flags && en.qc_flags.length
            ? `<div class="block-row"><span class="label">QC flags</span><span class="value">${clipBlockList(en.qc_flags)}</span></div>` : '',
          en.search_tags && en.search_tags.length
            ? `<div class="block-row"><span class="label">Search tags</span><span class="value">${clipBlockChips(en.search_tags)}</span></div>` : '',
        ].join('');
        blocks.push(clipBlock('Editing notes', rows));
      }

      // QC
      const qc = data.qc || {};
      if (Object.keys(qc).length) {
        const rows = [
          qc.warnings && qc.warnings.length
            ? `<div class="block-row"><span class="label">Warnings</span><span class="value">${clipBlockList(qc.warnings)}</span></div>` : '',
          qc.continuity_observations && qc.continuity_observations.length
            ? `<div class="block-row"><span class="label">Continuity</span><span class="value">${clipBlockList(qc.continuity_observations)}</span></div>` : '',
          qc.coverage_gaps && qc.coverage_gaps.length
            ? `<div class="block-row"><span class="label">Coverage gaps</span><span class="value">${clipBlockList(qc.coverage_gaps)}</span></div>` : '',
        ].join('');
        blocks.push(clipBlock('QC', rows));
      }

      // Cross-shot
      const cs = data.cross_shot || {};
      const cg = data.coverage_groups || cs.coverage_groups || [];
      const cc = data.continuity_chains || cs.continuity_chains || [];
      const at = cs.alt_take_groups || [];
      if (Object.keys(cs).length || cg.length || cc.length) {
        const rows = [
          clipBlockRow('Energy arc', cs.energy_arc),
          cg.length
            ? `<div class="block-row"><span class="label">Coverage groups</span><span class="value">${clipBlockList(cg.map(g => typeof g === 'object' ? JSON.stringify(g) : g))}</span></div>` : '',
          cc.length
            ? `<div class="block-row"><span class="label">Continuity chains</span><span class="value">${clipBlockList(cc.map(c => typeof c === 'object' ? JSON.stringify(c) : c))}</span></div>` : '',
          at.length
            ? `<div class="block-row"><span class="label">Alt takes</span><span class="value">${clipBlockList(at.map(a => typeof a === 'object' ? JSON.stringify(a) : a))}</span></div>` : '',
        ].join('');
        blocks.push(clipBlock('Cross-shot', rows));
      }

      // Slate (only if visible OR has visible_text)
      const sl = data.slate || {};
      if (sl.slate_visible || (sl.visible_text && sl.visible_text.length)) {
        const rows = [
          clipBlockRow('Visible', sl.slate_visible ? 'yes' : 'no'),
          clipBlockRow('Scene', sl.scene),
          clipBlockRow('Shot', sl.shot),
          clipBlockRow('Take', sl.take),
          clipBlockRow('Camera', sl.camera),
          clipBlockRow('Roll', sl.roll),
          clipBlockRow('Date', sl.date),
          clipBlockRow('Production', sl.production),
          sl.visible_text && sl.visible_text.length
            ? `<div class="block-row"><span class="label">Visible text</span><span class="value">${clipBlockChips(sl.visible_text)}</span></div>` : '',
        ].join('');
        blocks.push(clipBlock('Slate', rows, { confidence: sl.confidence && sl.confidence.overall }));
      }

      // Motion (computed signal)
      const mo = data.motion || {};
      if (Object.keys(mo).length) {
        const rows = [
          clipBlockRow('Overall level', mo.overall_level),
          mo.motion_events && mo.motion_events.length
            ? `<div class="block-row"><span class="label">Motion events</span><span class="value">${clipBlockList(mo.motion_events.map(e => typeof e === 'object' ? JSON.stringify(e) : e))}</span></div>` : '',
          mo.quiet_regions && mo.quiet_regions.length
            ? `<div class="block-row"><span class="label">Quiet regions</span><span class="value">${clipBlockList(mo.quiet_regions.map(e => typeof e === 'object' ? JSON.stringify(e) : e))}</span></div>` : '',
        ].join('');
        blocks.push(clipBlock('Motion', rows));
      }

      // Confidence summary
      if (Object.keys(conf).length) {
        const rows = [
          clipBlockRow('Visual', conf.visual),
          clipBlockRow('Motion', conf.motion),
          clipBlockRow('Transcript', conf.transcript),
        ].join('');
        blocks.push(clipBlock('Confidence', rows));
      }

      return blocks.join('');
    }

    async function openShotDetail(shotIndex, opts = {}) {
      const clipId = state.review.currentClipId;
      if (!clipId) return;
      state.review.currentShotIndex = shotIndex;
      const data = await api(`/api/clips/${encodeURIComponent(clipId)}/shots/${shotIndex}`).catch(err => ({ success: false, error: String(err) }));
      state.review.currentShotData = data;
      state.review.editingShot = false;
      reviewSetView('shot', opts);
      renderShotDetail();
    }

    async function openTranscript(clipId, opts = {}) {
      const target = clipId || state.review.currentClipId;
      if (!target) return;
      // Preserve focus segment across renders so deep links scroll correctly.
      if (opts.focusSegmentIndex != null) {
        state.review.currentTranscriptSegmentIndex = opts.focusSegmentIndex;
      } else if (opts.focusSeconds != null) {
        state.review.currentTranscriptSegmentIndex = null;
        state.review._focusSeconds = opts.focusSeconds;
      } else {
        state.review.currentTranscriptSegmentIndex = null;
      }
      // Ensure clip context is loaded so the header label resolves.
      if (state.review.currentClipId !== target || !state.review.currentClipData) {
        state.review.currentClipId = target;
        const clipData = await api(`/api/clips/${encodeURIComponent(target)}`).catch(err => ({ success: false, error: String(err) }));
        state.review.currentClipData = clipData;
      }
      const data = await api(`/api/clips/${encodeURIComponent(target)}/transcript`).catch(err => ({ success: false, error: String(err) }));
      state.review.currentTranscriptData = data;
      // Reset per-segment edit state on (re-)open unless caller is preserving
      // it across a successful save round-trip.
      if (!opts.preserveDraft) {
        state.review.editingSegmentDraftIndex = null;
      }
      reviewSetView('transcript', opts);
      renderTranscriptView();
    }

    function cloneSegmentForDraft(seg) {
      return {
        index: seg.index,
        start_seconds: seg.start_seconds,
        end_seconds: seg.end_seconds,
        text: seg.text || '',
        words: Array.isArray(seg.words)
          ? seg.words.map(w => ({ index: w.index, word: w.word, start_seconds: w.start_seconds, end_seconds: w.end_seconds }))
          : undefined,
      };
    }

    function enterSegmentEdit(draftIndex) {
      state.review.editingSegmentDraftIndex = draftIndex;
      renderTranscriptView();
    }

    function exitSegmentEdit() {
      state.review.editingSegmentDraftIndex = null;
      renderTranscriptView();
    }

    /**
     * Rebuild a segment's words[] array from the contenteditable text content.
     * Preserves per-word timings where the text matches; for new/split words
     * it distributes the parent word's time range proportionally to character
     * count. Falls back to evenly-spaced timing inside the segment's start/end
     * window if there are no parent words to inherit from.
     */
    function rebuildWordsFromEditedText(newText, originalWords, segmentStart, segmentEnd) {
      const tokens = String(newText || '')
        .replace(/\s+/g, ' ')
        .trim()
        .split(' ')
        .filter(Boolean);
      if (!tokens.length) return [];
      const orig = (originalWords || []).map(w => ({ ...w }));
      const segStart = Number(segmentStart);
      const segEnd = Number(segmentEnd);
      // Build a fast lookup of original-token positions to preserve timings when text matches.
      const origByLower = new Map();
      orig.forEach((w, i) => {
        const key = String(w.word || '').toLowerCase();
        if (!origByLower.has(key)) origByLower.set(key, []);
        origByLower.get(key).push(i);
      });
      const usedOriginal = new Set();
      const placeholders = tokens.map(t => {
        const key = String(t).toLowerCase();
        const candidates = origByLower.get(key) || [];
        const idx = candidates.find(i => !usedOriginal.has(i));
        if (idx != null) {
          usedOriginal.add(idx);
          const src = orig[idx];
          return {
            word: t,
            start_seconds: src.start_seconds,
            end_seconds: src.end_seconds,
            preserved: true,
          };
        }
        return { word: t, preserved: false };
      });
      // Fill in timings for un-preserved tokens by interpolating between known anchors.
      let i = 0;
      while (i < placeholders.length) {
        if (placeholders[i].preserved) { i += 1; continue; }
        let j = i;
        while (j < placeholders.length && !placeholders[j].preserved) j += 1;
        // Range [i, j) has no preserved timings. Anchor on neighbors or segment bounds.
        const leftAnchor = i > 0 ? placeholders[i - 1].end_seconds : (Number.isFinite(segStart) ? segStart : 0);
        const rightAnchor = j < placeholders.length ? placeholders[j].start_seconds : (Number.isFinite(segEnd) ? segEnd : leftAnchor + 0.1);
        const span = Math.max(0.001, Number(rightAnchor) - Number(leftAnchor));
        const totalChars = placeholders.slice(i, j).reduce((acc, p) => acc + p.word.length, 0) || 1;
        let cursor = Number(leftAnchor);
        for (let k = i; k < j; k++) {
          const dur = (placeholders[k].word.length / totalChars) * span;
          placeholders[k].start_seconds = cursor;
          placeholders[k].end_seconds = cursor + dur;
          cursor += dur;
        }
        i = j;
      }
      return placeholders.map((p, idx) => ({
        index: idx,
        word: p.word,
        start_seconds: Number(p.start_seconds),
        end_seconds: Number(p.end_seconds),
      }));
    }

    /**
     * Read the editable words container's current text content for a segment
     * being edited. Treats each word span as a token and joins with spaces.
     */
    function readEditedWordsText(segmentEl) {
      const container = segmentEl?.querySelector('[data-words-edit]');
      if (!container) return null;
      // Innertext respects whitespace from contenteditable spans + spaces between them.
      const raw = container.innerText || container.textContent || '';
      return raw.replace(/\s+/g, ' ').trim();
    }

    async function commitSegmentEdit(draftIndex) {
      const clipId = state.review.currentClipId;
      const data = state.review.currentTranscriptData;
      if (!clipId || !data || !data.success || !Array.isArray(data.segments)) return;
      const segments = data.segments.map(cloneSegmentForDraft);
      const target = segments[draftIndex];
      if (!target) return;
      const segmentEl = document.querySelector(`.review-transcript-segment[data-draft-index="${draftIndex}"]`);
      // Word-level edit path: rebuild words[] from contenteditable.
      const hadWords = Array.isArray(target.words) && target.words.length > 0;
      if (hadWords) {
        const editedText = readEditedWordsText(segmentEl);
        if (editedText == null) return;
        target.words = rebuildWordsFromEditedText(editedText, target.words, target.start_seconds, target.end_seconds);
        target.text = target.words.map(w => w.word).join(' ');
      } else {
        // Fallback: plain text edit via textarea.
        const ta = segmentEl?.querySelector('textarea.segment-text-edit');
        if (!ta) return;
        target.text = (ta.value || '').replace(/\s+/g, ' ').trim();
      }
      await persistTranscriptSegments(clipId, segments, /* exitEdit */ true);
    }

    async function persistTranscriptSegments(clipId, segments, exitEdit) {
      const original = state.review.currentTranscriptData?.segments || [];
      const body = {
        segments: segments.map((seg, idx) => ({
          index: idx,
          start_seconds: seg.start_seconds,
          end_seconds: seg.end_seconds,
          text: seg.text,
          words: Array.isArray(seg.words) ? seg.words : undefined,
        })),
        edited_count: segments.length, // upper bound; UI just shows the count
        deleted_indices: original.length > segments.length
          ? Array.from({ length: original.length - segments.length }, (_, i) => segments.length + i)
          : [],
      };
      const result = await api(`/api/clips/${encodeURIComponent(clipId)}/transcript/corrections`, {
        method: 'POST',
        body: JSON.stringify(body),
      }).catch(err => ({ success: false, error: String(err) }));
      if (!result.success) {
        alertError(result.error || 'Saving transcript edit failed');
        return;
      }
      if (exitEdit) state.review.editingSegmentDraftIndex = null;
      // Re-fetch so the view shows the merged corrections from disk and any
      // word-array changes show up consistently.
      await openTranscript(clipId, { preserveDraft: false });
    }

    /**
     * Apply a structural op (split/merge/delete) at draftIndex and persist.
     */
    async function applyStructuralOp(action, draftIndex, opts = {}) {
      const data = state.review.currentTranscriptData;
      if (!data || !data.success || !Array.isArray(data.segments)) return;
      const segments = data.segments.map(cloneSegmentForDraft);
      if (draftIndex < 0 || draftIndex >= segments.length) return;
      const seg = segments[draftIndex];
      if (action === 'delete') {
        segments.splice(draftIndex, 1);
      } else if (action === 'merge') {
        const next = segments[draftIndex + 1];
        if (!next) return;
        seg.text = `${(seg.text || '').trim()} ${(next.text || '').trim()}`.trim();
        seg.end_seconds = next.end_seconds != null ? next.end_seconds : seg.end_seconds;
        if (Array.isArray(seg.words) && Array.isArray(next.words)) seg.words = seg.words.concat(next.words);
        else if (Array.isArray(next.words)) seg.words = next.words;
        segments.splice(draftIndex + 1, 1);
      } else if (action === 'split') {
        const text = seg.text || '';
        const cursor = Number.isFinite(opts.cursor) ? opts.cursor : Math.floor(text.length / 2);
        const firstHalf = text.slice(0, cursor).trim();
        const secondHalf = text.slice(cursor).trim();
        const totalDur = (Number(seg.end_seconds) || 0) - (Number(seg.start_seconds) || 0);
        const ratio = text.length ? cursor / text.length : 0.5;
        const splitTime = (Number(seg.start_seconds) || 0) + totalDur * ratio;
        const oldEnd = seg.end_seconds;
        seg.text = firstHalf || text;
        seg.end_seconds = splitTime;
        const newSeg = {
          index: -1,
          start_seconds: splitTime,
          end_seconds: oldEnd,
          text: secondHalf,
        };
        if (Array.isArray(seg.words) && seg.words.length) {
          const left = [];
          const right = [];
          for (const w of seg.words) {
            if (Number(w.start_seconds) < splitTime) left.push(w);
            else right.push(w);
          }
          seg.words = left;
          if (right.length) newSeg.words = right;
        }
        segments.splice(draftIndex + 1, 0, newSeg);
      } else {
        return;
      }
      await persistTranscriptSegments(clipId(), segments, /* exitEdit */ true);
    }

    function clipId() { return state.review.currentClipId; }

    async function regenerateTranscript() {
      const clipId = state.review.currentClipId;
      if (!clipId) return;
      // Per-segment edits auto-save on commit, so there are never "unsaved
      // edits" lingering at this point. Re-transcribing replaces the on-disk
      // transcript.json; existing transcript-corrections.json stays in place
      // and is re-applied on read — same as before.
      const proceed = await brandedConfirm({
        kicker: 'Transcript',
        title: 'Re-transcribe this clip with word timestamps?',
        body: 'Calls the local whisper backend and may take a few seconds. The new transcript replaces the existing one.',
        detail: 'Word-level timestamps enable per-word scrubbing and word-snap Open-in-Resolve.',
        confirmLabel: 'Re-transcribe',
      });
      if (!proceed) return;
      state.review.transcriptRegenerating = true;
      renderTranscriptView();
      const result = await api(`/api/clips/${encodeURIComponent(clipId)}/transcript/regenerate`, {
        method: 'POST',
        body: JSON.stringify({ with_words: true }),
      }).catch(err => ({ success: false, error: String(err) }));
      state.review.transcriptRegenerating = false;
      if (!result.success) {
        alertError(result.error || 'Regenerate failed');
        renderTranscriptView();
        return;
      }
      await openTranscript(clipId, {});
    }

    function renderTranscriptView() {
      const data = state.review.currentTranscriptData;
      const clipId = state.review.currentClipId;
      const clipName = state.review.currentClipData?.card?.clip_name || clipId || 'Clip';
      const header = $('reviewTranscriptHeader');
      const meta = $('reviewTranscriptMeta');
      const body = $('reviewTranscriptBody');
      const filterInput = $('reviewTranscriptFilter');
      if (!header || !meta || !body) return;
      const regenerating = !!state.review.transcriptRegenerating;
      header.innerHTML = `
        <span class="name">${escapeHtml(clipName)}</span>
        <span class="meta">Transcript</span>
        <div class="actions">
          <button class="secondary" id="reviewTranscriptBackToClipBtn">← Clip detail</button>
          <button class="secondary" id="reviewTranscriptRegenerateBtn"${regenerating ? ' disabled' : ''}>${regenerating ? 'Re-transcribing…' : 'Re-transcribe with words'}</button>
        </div>
      `;
      if (!data || !data.success) {
        meta.textContent = '';
        body.innerHTML = `<div class="empty">${escapeHtml((data && data.error) || 'Transcript unavailable.')}</div>`;
        return;
      }
      if (!data.available || !(data.segments || []).length) {
        meta.textContent = data.backend ? `${data.backend}${data.language ? ' · ' + data.language : ''}` : '';
        body.innerHTML = '<div class="empty">No transcript segments were stored for this clip. Click <em>Re-transcribe with words</em> above to capture word-level timing.</div>';
        return;
      }
      const corrSummary = data.has_corrections
        ? ` · ${data.corrections_meta?.edited_count || 0} edit${(data.corrections_meta?.edited_count || 0) === 1 ? '' : 's'}${(data.corrections_meta?.deleted_count || 0) ? `, ${data.corrections_meta.deleted_count} deleted` : ''}`
        : '';
      meta.textContent = `${data.segment_count} segment${data.segment_count === 1 ? '' : 's'} · ${data.backend || 'transcription'}${data.language ? ' · ' + data.language : ''}${corrSummary}`;
      if (filterInput && filterInput.value !== state.review.transcriptFilter) {
        filterInput.value = state.review.transcriptFilter || '';
      }
      const sourceSegments = data.segments || [];
      const focusIdx = state.review.currentTranscriptSegmentIndex;
      const filter = String(state.review.transcriptFilter || '').trim().toLowerCase();
      const editingIdx = state.review.editingSegmentDraftIndex;
      const rows = sourceSegments
        .map((seg, draftIndex) => ({ seg, draftIndex }))
        .filter(({ seg, draftIndex }) => {
          // Don't filter out the segment that's currently being edited even if
          // its text no longer matches the filter mid-edit.
          if (draftIndex === editingIdx) return true;
          if (!filter) return true;
          return String(seg.text || '').toLowerCase().includes(filter);
        });
      if (!rows.length) {
        body.innerHTML = filter
          ? `<div class="empty">No transcript segments match "${escapeHtml(filter)}".</div>`
          : '<div class="empty">No transcript segments.</div>';
        return;
      }
      body.innerHTML = rows.map(({ seg, draftIndex }) => {
        const tc = seg.start_seconds != null ? formatDuration(seg.start_seconds) : '—';
        const isMatch = focusIdx != null && Number(focusIdx) === Number(seg.index);
        const isEditing = draftIndex === editingIdx;
        const hasWords = Array.isArray(seg.words) && seg.words.length > 0;
        let bodyHtml;
        if (isEditing && hasWords) {
          // Word-level edit: each word is a contenteditable span. The container
          // is also marked contenteditable so the user can edit boundaries
          // (space splits, backspace at boundary merges).
          bodyHtml = `<div class="transcript-words editable" contenteditable="true" spellcheck="true" data-words-edit="${draftIndex}">${seg.words.map((w, wi) => {
            const ws = w.start_seconds;
            const we = w.end_seconds;
            return `<span class="transcript-word" data-word-index="${wi}" data-word-start="${ws ?? ''}" data-word-end="${we ?? ''}" title="${escapeAttribute(formatDuration(ws || 0))} → ${escapeAttribute(formatDuration(we || 0))}">${escapeHtml(w.word)}</span>`;
          }).join(' ')}</div>`;
        } else if (isEditing && !hasWords) {
          // No words[]: fall back to a textarea for the segment text.
          bodyHtml = `<textarea class="segment-text-edit" data-draft-index="${draftIndex}" rows="${Math.max(2, Math.min(6, (seg.text || '').split('\n').length + 1))}">${escapeHtml(seg.text || '')}</textarea>
            <div class="segment-text-hint">No word-level timing on this segment — text-only edit. <em>Re-transcribe with words</em> above to enable word editing.</div>`;
        } else {
          // Read mode: plain text (with filter highlighting) + read-only words row when present.
          const textInner = filter ? highlightQueryInText(seg.text, filter) : escapeHtml(seg.text || '');
          const wordsHtml = hasWords
            ? `<div class="transcript-words" data-words-for="${draftIndex}">${seg.words.map((w, wi) => {
                const ws = w.start_seconds;
                const we = w.end_seconds;
                return `<span class="transcript-word" data-word-index="${wi}" data-word-start="${ws ?? ''}" data-word-end="${we ?? ''}" title="${escapeAttribute(formatDuration(ws || 0))} → ${escapeAttribute(formatDuration(we || 0))}">${escapeHtml(w.word)}</span>`;
              }).join(' ')}</div>`
            : '';
          bodyHtml = `<div class="text">${textInner}</div>${wordsHtml}`;
        }
        const actions = isEditing
          ? `<span class="actions transcript-edit-actions">
              <button class="primary" data-segment-save="${draftIndex}" title="Save changes">Save</button>
              <button class="secondary" data-segment-cancel="${draftIndex}" title="Cancel">Cancel</button>
              <button class="secondary" data-structural-op="split" data-draft-index="${draftIndex}" title="Split into two segments">Split</button>
              <button class="secondary" data-structural-op="merge" data-draft-index="${draftIndex}" title="Merge with next segment">Merge ↓</button>
              <button class="danger" data-structural-op="delete" data-draft-index="${draftIndex}" title="Delete segment">Delete</button>
             </span>`
          : `<span class="actions">
              <button class="secondary segment-edit-btn" data-segment-edit="${draftIndex}" title="Edit this segment">Edit</button>
              <button class="secondary" data-transcript-open-resolve="${seg.start_seconds ?? ''}" data-transcript-end="${seg.end_seconds ?? ''}">Open in Resolve</button>
             </span>`;
        return `<div class="review-transcript-segment${isMatch ? ' is-match' : ''}${isEditing ? ' editing' : ''}" data-segment-index="${seg.index}" data-draft-index="${draftIndex}" data-start-seconds="${seg.start_seconds ?? ''}" data-end-seconds="${seg.end_seconds ?? ''}" tabindex="0">
          <span class="tc">${escapeHtml(tc)}</span>
          <div class="transcript-segment-body">${bodyHtml}</div>
          ${actions}
        </div>`;
      }).join('');
      // Wire per-row Open-in-Resolve buttons (read mode).
      body.querySelectorAll('[data-transcript-open-resolve]').forEach(btn => {
        btn.addEventListener('click', (event) => {
          event.stopPropagation();
          const start = Number(btn.dataset.transcriptOpenResolve);
          const end = Number(btn.dataset.transcriptEnd);
          if (Number.isFinite(start)) {
            openClipInResolveAt(clipId, start, Number.isFinite(end) ? end : undefined);
          }
        });
      });
      // Word-click → Open Resolve at the word's exact range.
      // Shift+click extends a selection across words within the same segment;
      // the segment's Open-in-Resolve button then uses the selected range
      // (selected word range's first.start → last.end).
      body.querySelectorAll('.transcript-word').forEach(el => {
        el.addEventListener('click', (event) => {
          event.stopPropagation();
          if (event.shiftKey) {
            toggleWordSelection(el, /* extend */ true);
            return;
          }
          // Plain click: clear any existing selection, then open at this word.
          clearWordSelectionsExcept(el.closest('.transcript-words'));
          const start = Number(el.dataset.wordStart);
          const end = Number(el.dataset.wordEnd);
          if (Number.isFinite(start)) {
            openClipInResolveAt(clipId, start, Number.isFinite(end) ? end : undefined);
          }
        });
      });
      // Per-row Open-in-Resolve: if any words are selected inside this row,
      // use them instead of the full segment range.
      body.querySelectorAll('.review-transcript-segment').forEach(row => {
        const openBtn = row.querySelector('[data-transcript-open-resolve]');
        if (!openBtn) return;
        const original = openBtn.onclick;
        openBtn.addEventListener('click', (event) => {
          const selected = Array.from(row.querySelectorAll('.transcript-word.selected'));
          if (!selected.length) return; // fall through to the existing handler
          event.preventDefault();
          event.stopPropagation();
          const starts = selected.map(w => Number(w.dataset.wordStart)).filter(Number.isFinite);
          const ends = selected.map(w => Number(w.dataset.wordEnd)).filter(Number.isFinite);
          if (!starts.length) return;
          openClipInResolveAt(clipId, Math.min.apply(null, starts), ends.length ? Math.max.apply(null, ends) : undefined);
        }, { capture: true });
      });
      // Per-segment edit buttons (read mode) → enter edit on that segment.
      body.querySelectorAll('[data-segment-edit]').forEach(btn => {
        btn.addEventListener('click', (event) => {
          event.stopPropagation();
          const idx = Number(btn.dataset.segmentEdit);
          if (Number.isFinite(idx)) enterSegmentEdit(idx);
        });
      });
      // Per-segment Save / Cancel.
      body.querySelectorAll('[data-segment-save]').forEach(btn => {
        btn.addEventListener('click', (event) => {
          event.stopPropagation();
          const idx = Number(btn.dataset.segmentSave);
          if (Number.isFinite(idx)) commitSegmentEdit(idx).catch(alertError);
        });
      });
      body.querySelectorAll('[data-segment-cancel]').forEach(btn => {
        btn.addEventListener('click', (event) => {
          event.stopPropagation();
          exitSegmentEdit();
        });
      });
      // Structural ops (split / merge / delete) — operate on the live transcript
      // and persist atomically via applyStructuralOp.
      body.querySelectorAll('[data-structural-op]').forEach(btn => {
        btn.addEventListener('click', (event) => {
          event.stopPropagation();
          const idx = Number(btn.dataset.draftIndex);
          const op = btn.dataset.structuralOp;
          if (!Number.isFinite(idx)) return;
          if (op === 'split') {
            // For word-level segments, infer the split point from where the
            // browser selection currently is inside the contenteditable.
            // For textarea-only segments, use the textarea's selectionStart.
            const segmentEl = body.querySelector(`.review-transcript-segment[data-draft-index="${idx}"]`);
            const ta = segmentEl?.querySelector('textarea.segment-text-edit');
            let cursor = null;
            if (ta && typeof ta.selectionStart === 'number') cursor = ta.selectionStart;
            applyStructuralOp(op, idx, { cursor }).catch(alertError);
          } else {
            applyStructuralOp(op, idx).catch(alertError);
          }
        });
      });
      // Keyboard: Enter to save, Esc to cancel — only when editing this segment.
      body.querySelectorAll('.review-transcript-segment.editing').forEach(row => {
        row.addEventListener('keydown', (event) => {
          if (event.key === 'Escape') {
            event.preventDefault();
            exitSegmentEdit();
          } else if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
            event.preventDefault();
            const idx = Number(row.dataset.draftIndex);
            if (Number.isFinite(idx)) commitSegmentEdit(idx).catch(alertError);
          }
        });
      });
      // Auto-focus the editable area on mount so the user can just type.
      if (editingIdx != null) {
        const row = body.querySelector(`.review-transcript-segment.editing[data-draft-index="${editingIdx}"]`);
        const editable = row?.querySelector('[data-words-edit], textarea.segment-text-edit');
        if (editable) {
          requestAnimationFrame(() => {
            if (editable.focus) editable.focus();
          });
        }
      }
      // Scroll-to-focus on navigation.
      if (focusIdx != null) {
        requestAnimationFrame(() => {
          const target = body.querySelector(`[data-segment-index="${focusIdx}"]`);
          if (target) target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        });
      } else if (state.review._focusSeconds != null) {
        // Find the segment whose [start, end] window contains the focus time,
        // or the closest segment by start time if nothing strictly contains it.
        const focus = Number(state.review._focusSeconds);
        const all = Array.from(body.querySelectorAll('.review-transcript-segment'));
        let target = null;
        let bestDelta = Infinity;
        for (const el of all) {
          const start = Number(el.dataset.startSeconds);
          if (!Number.isFinite(start)) continue;
          const delta = Math.abs(start - focus);
          if (delta < bestDelta) { bestDelta = delta; target = el; }
        }
        if (target) {
          target.classList.add('is-match');
          requestAnimationFrame(() => target.scrollIntoView({ behavior: 'smooth', block: 'center' }));
        }
        delete state.review._focusSeconds;
      }
    }

    function toggleWordSelection(wordEl, extend) {
      if (!wordEl) return;
      const wordsContainer = wordEl.closest('.transcript-words');
      if (!wordsContainer) return;
      // Selection lives only inside one segment at a time. Clear other rows.
      clearWordSelectionsExcept(wordsContainer);
      if (!extend) {
        wordsContainer.querySelectorAll('.transcript-word.selected').forEach(el => el.classList.remove('selected'));
      }
      wordEl.classList.toggle('selected');
      // Re-fill the gap between extremes when extending — single drag-ish UX.
      if (extend) {
        const all = Array.from(wordsContainer.querySelectorAll('.transcript-word'));
        const selectedIdx = all.map((el, i) => el.classList.contains('selected') ? i : -1).filter(i => i >= 0);
        if (selectedIdx.length > 1) {
          const min = Math.min.apply(null, selectedIdx);
          const max = Math.max.apply(null, selectedIdx);
          for (let i = min; i <= max; i++) all[i].classList.add('selected');
        }
      }
    }
    function clearWordSelectionsExcept(keepContainer) {
      document.querySelectorAll('.transcript-words').forEach(container => {
        if (container === keepContainer) return;
        container.querySelectorAll('.transcript-word.selected').forEach(el => el.classList.remove('selected'));
      });
    }

    // Editorial handles around a transcript segment so Resolve marks a clip
    // with breath, not a tight in/out that clips the head/tail off.
    const TRANSCRIPT_PREROLL_SECONDS = 0.5;
    const TRANSCRIPT_POSTROLL_SECONDS = 0.5;

    async function openClipInResolveAt(clipId, startSeconds, endSeconds) {
      if (!clipId) return;
      const start = Number(startSeconds);
      const end = Number(endSeconds);
      const body = {
        action: 'open_in_viewer',
        clip_id: clipId,
        page: 'media',
      };
      if (Number.isFinite(start)) {
        body.mark_in_seconds = Math.max(0, start - TRANSCRIPT_PREROLL_SECONDS);
        // Use the caller-supplied end (e.g. transcript segment end_seconds)
        // when available so Resolve marks the actual spoken span with breath
        // around it. Otherwise leave mark_out unset so only the in-point gets
        // a mark.
        if (Number.isFinite(end) && end > start) {
          body.mark_out_seconds = end + TRANSCRIPT_POSTROLL_SECONDS;
        }
      }
      const result = await api('/api/resolve/open_clip', { method: 'POST', body: JSON.stringify(body) })
        .catch(err => ({ success: false, error: String(err) }));
      if (!result.success) alertError(result.error || 'Open in Resolve failed');
    }

    const SHOT_FIELD_GROUPS = [
      { key: 'visual', title: 'Visual', fields: ['shot_size', 'framing', 'camera_height', 'camera_motion', 'motion_direction', 'depth_of_field', 'lens_character', 'lens_format', 'lighting', 'color_mood', 'composition_notes'] },
      { key: 'content', title: 'Content', fields: ['primary_subject', 'secondary_subjects', 'action', 'location', 'visible_text', 'objects_of_note', 'audio_character'] },
      { key: 'production', title: 'Production', fields: ['composite_shot', 'composite_panels', 'vfx_present'] },
      { key: 'editorial', title: 'Editorial', fields: ['editorial_role', 'select_potential', 'best_moment_present', 'best_moment', 'pacing', 'stillness_type', 'pacing_note'] },
      { key: 'cuttability', title: 'Cuttability', fields: ['cut_in', 'cut_out', 'match_action_in', 'match_action_out', 'cut_compatibility_hints'] },
      { key: 'relationships', title: 'Relationships', fields: ['same_setup_as', 'continues_from', 'alt_take_of'] },
    ];

    const ENUM_OPTIONS = {
      shot_size: ['wide', 'medium_wide', 'medium', 'medium_close', 'close', 'extreme_close', 'insert', 'establishing', 'other'],
      framing: ['single', 'two_shot', 'group', 'crowd', 'empty', 'insert', 'establishing', 'abstract'],
      camera_height: ['eye_level', 'high_angle', 'low_angle', 'birds_eye', 'dutch', 'unknown'],
      camera_motion: ['locked', 'pan', 'tilt', 'dolly', 'handheld', 'crane', 'drone', 'zoom', 'composite', 'other'],
      motion_direction: ['left', 'right', 'up', 'down', 'in', 'out', 'clockwise', 'counter_clockwise', 'none'],
      depth_of_field: ['deep', 'shallow', 'rack_focus', 'unknown'],
      lens_character: ['wide', 'normal', 'tele', 'fisheye', 'unknown'],
      lens_format: ['spherical', 'anamorphic', 'fisheye', 'unknown'],
      lighting: ['natural', 'high_key', 'low_key', 'practical', 'backlit', 'silhouette', 'mixed', 'unknown'],
      color_mood: ['warm', 'cool', 'neutral', 'desaturated', 'saturated', 'monochrome', 'unnatural', 'unknown'],
      audio_character: ['silence', 'sync_dialogue', 'vo_dialogue', 'music', 'ambient', 'sfx', 'mixed', 'unknown'],
      vfx_present: ['none', 'minor', 'major', 'unknown'],
      editorial_role: ['establishing', 'coverage', 'reaction', 'insert', 'transition', 'b_roll', 'montage_element', 'titles_or_graphics', 'bumper', 'other'],
      select_potential: ['high', 'medium', 'low'],
      pacing: ['still', 'moderate', 'kinetic', 'variable'],
      stillness_type: ['held_tension', 'quiet', 'contemplative', 'transitional', 'dead_air', 'unknown'],
    };

    // ─── User rating + notes (per-clip and per-shot) ────────────────────
    const STAR_PATH = 'M12 2.5l2.95 6.5 7.05.85-5.3 4.85 1.5 7-6.2-3.65L5.8 21.7l1.5-7L2 9.85l7.05-.85z';

    function renderStarsWidget(value, scope) {
      const v = Math.max(0, Math.min(5, Number(value) || 0));
      const stars = [0, 1, 2, 3, 4].map(i => {
        // Each star: bg (grey, full size) + fg (blue, clip-path to reveal left N%)
        const fillPct = Math.max(0, Math.min(1, v - i)) * 100;
        const inset = 100 - fillPct;
        return `<span class="star" data-star-index="${i}">
          <svg class="bg" viewBox="0 0 24 24"><path d="${STAR_PATH}"/></svg>
          <svg class="fg" viewBox="0 0 24 24" style="clip-path: inset(0 ${inset}% 0 0)"><path d="${STAR_PATH}"/></svg>
          <span class="hit left" data-rating-scope="${scope}" data-rating-value="${i + 0.5}"></span>
          <span class="hit right" data-rating-scope="${scope}" data-rating-value="${i + 1}"></span>
        </span>`;
      }).join('');
      const display = v > 0 ? v.toFixed(v % 1 === 0 ? 0 : 1) : '—';
      return `<div class="review-rating-row" data-rating-scope="${scope}">
        <div class="review-stars" data-rating-scope="${scope}" data-saved-rating="${v}">${stars}</div>
        <span class="review-rating-value" data-rating-display="${scope}">${display}${v > 0 ? ' / 5' : ''}</span>
        <button class="review-rating-clear" data-rating-clear="${scope}" type="button" title="Clear rating">clear</button>
      </div>`;
    }

    function applyStarsValue(starsRoot, value) {
      // Update visual fill of each star without re-rendering the whole widget.
      const stars = starsRoot.querySelectorAll('.star');
      stars.forEach((star, i) => {
        const fg = star.querySelector('.fg');
        if (fg) {
          const pct = Math.max(0, Math.min(1, value - i)) * 100;
          fg.style.clipPath = `inset(0 ${100 - pct}% 0 0)`;
        }
      });
    }

    function setStarsPreview(starsRoot, value) {
      starsRoot.classList.add('hovering');
      applyStarsValue(starsRoot, value);
      // Update inline numeric display too.
      const scope = starsRoot.dataset.ratingScope;
      const display = document.querySelector(`[data-rating-display="${scope}"]`);
      if (display) {
        const v = Number(value);
        display.textContent = v > 0 ? (v.toFixed(v % 1 === 0 ? 0 : 1) + ' / 5') : '—';
      }
    }

    function clearStarsPreview(starsRoot) {
      starsRoot.classList.remove('hovering');
      const saved = Number(starsRoot.dataset.savedRating || '0');
      applyStarsValue(starsRoot, saved);
      const scope = starsRoot.dataset.ratingScope;
      const display = document.querySelector(`[data-rating-display="${scope}"]`);
      if (display) {
        display.textContent = saved > 0 ? (saved.toFixed(saved % 1 === 0 ? 0 : 1) + ' / 5') : '—';
      }
    }

    function renderNotesWidget(value, scope) {
      const safe = value == null ? '' : String(value);
      return `<div class="review-notes-row" data-notes-scope="${scope}">
        <div class="label">Notes</div>
        <textarea data-notes-input="${scope}" placeholder="Editorial notes — saved with this clip\u2019s analysis and preserved on re-analysis\u2026">${escapeHtml(safe)}</textarea>
        <div class="controls">
          <button class="secondary" data-notes-save="${scope}" type="button">Save notes</button>
          <span class="saved" data-notes-saved="${scope}" style="opacity:0">Saved</span>
        </div>
      </div>`;
    }

    function readCorrectionValue(corrections, entityType, entityUuid, fieldPath) {
      const current = (corrections && corrections.current) || {};
      const key = `${entityType}:${entityUuid}:${fieldPath}`;
      const entry = current[key];
      return entry ? entry.value : undefined;
    }

    async function saveCorrection(entityType, entityUuid, fieldPath, newValue) {
      const clipId = state.review.currentClipId;
      if (!clipId) return { success: false, error: 'no current clip' };
      const body = {
        entity_type: entityType,
        entity_uuid: entityUuid,
        field_path: fieldPath,
        new_value: newValue,
        author: 'control_panel',
        reason: 'panel rating/notes edit',
      };
      if (entityType === 'shot') {
        body.shot_index = state.review.currentShotIndex;
      }
      return api(`/api/clips/${encodeURIComponent(clipId)}/corrections`, { method: 'POST', body: JSON.stringify(body) })
        .catch(err => ({ success: false, error: String(err) }));
    }

    function getClipRatingScope() {
      const clipId = state.review.currentClipId;
      return { entityType: 'clip', entityUuid: clipId, key: 'clip-' + clipId };
    }

    function getShotRatingScope() {
      const data = state.review.currentShotData;
      const shot = data && data.shot;
      const entityUuid = (shot && shot.shot_uuid) || state.review.currentShotIndex;
      return { entityType: 'shot', entityUuid: entityUuid, key: 'shot-' + entityUuid };
    }

    async function onRatingClick(scopeKey, value) {
      let scope;
      if (scopeKey.startsWith('clip-')) scope = getClipRatingScope();
      else scope = getShotRatingScope();
      const result = await saveCorrection(scope.entityType, scope.entityUuid, 'user.rating', value);
      if (!result.success) {
        alertError(result.error || 'Save rating failed');
        return;
      }
      if (scope.entityType === 'clip') {
        // Refresh clip-level corrections in current data without full reload.
        const clip = await api(`/api/clips/${encodeURIComponent(state.review.currentClipId)}`).catch(() => null);
        if (clip && clip.success) {
          state.review.currentClipData = clip;
          if (state.review.view === 'clip') renderClipDetail();
        }
      } else {
        await openShotDetail(state.review.currentShotIndex, { writePanelState: false, pushHash: false });
      }
    }

    async function onNotesSave(scopeKey) {
      let scope;
      if (scopeKey.startsWith('clip-')) scope = getClipRatingScope();
      else scope = getShotRatingScope();
      const root = document.querySelector(`[data-notes-input="${scopeKey}"]`);
      if (!root) return;
      const newValue = root.value;
      const result = await saveCorrection(scope.entityType, scope.entityUuid, 'user.notes', newValue);
      if (!result.success) {
        alertError(result.error || 'Save notes failed');
        return;
      }
      const tag = document.querySelector(`[data-notes-saved="${scopeKey}"]`);
      if (tag) {
        tag.style.opacity = '1';
        setTimeout(() => { tag.style.opacity = '0'; }, 1200);
      }
      // Update local state so a re-render still shows the value.
      if (scope.entityType === 'clip' && state.review.currentClipData) {
        const corr = state.review.currentClipData.corrections || {};
        corr.current = corr.current || {};
        corr.current[`clip:${scope.entityUuid}:user.notes`] = { value: newValue, source: 'human' };
        state.review.currentClipData.corrections = corr;
      } else if (scope.entityType === 'shot' && state.review.currentShotData) {
        const corr = state.review.currentShotData.corrections || {};
        corr.current = corr.current || {};
        corr.current[`shot:${scope.entityUuid}:user.notes`] = { value: newValue, source: 'human' };
        state.review.currentShotData.corrections = corr;
      }
    }

    function isHumanEditedField(corrections, entityUuid, fieldPath) {
      const current = (corrections && corrections.current) || {};
      const keys = [`shot:${entityUuid}:${fieldPath}`];
      for (const k of keys) {
        const entry = current[k];
        if (entry && entry.source === 'human') return entry;
      }
      return null;
    }

    function renderShotFieldValue(value) {
      if (value == null || value === '') return '<i style="color:var(--text-tertiary)">—</i>';
      if (Array.isArray(value)) return value.map(v => `<span class="review-chip">${escapeHtml(String(v))}</span>`).join(' ');
      if (typeof value === 'object') return `<code>${escapeHtml(JSON.stringify(value))}</code>`;
      return escapeHtml(String(value));
    }

    function renderShotDetail() {
      const data = state.review.currentShotData;
      const clipId = state.review.currentClipId;
      const shotIndex = state.review.currentShotIndex;
      if (!data || !data.success) {
        $('reviewShotHeader').innerHTML = `<div class="empty">${escapeHtml((data && data.error) || 'Shot not found.')}</div>`;
        $('reviewShotFields').innerHTML = '';
        $('reviewShotFrames').innerHTML = '';
        return;
      }
      const shot = data.shot || {};
      const corrections = data.corrections || { current: {}, changelog: [] };
      const entityUuid = shot.shot_uuid || shotIndex;
      const editing = state.review.editingShot;
      const editToggleLabel = editing ? 'Done editing' : 'Edit';
      const tStart = shot.time_seconds_start;
      const tEnd = shot.time_seconds_end;
      $('reviewShotHeader').innerHTML = `
        <span class="name">Shot ${shotIndex}</span>
        <span class="meta">${tStart != null ? `${formatDuration(tStart)}` : ''}${tEnd != null ? ` → ${formatDuration(tEnd)}` : ''}</span>
        <span class="meta">${escapeHtml(shot.description || '')}</span>
        <div class="actions">
          <button class="secondary" id="reviewShotOpenInResolveBtn">Open in Resolve</button>
          <button class="secondary" data-copy-chat-prompt="${escapeHtml(`Deepen shot ${shotIndex} of clip “${(state.review.currentClipData && state.review.currentClipData.card && state.review.currentClipData.card.clip_name) || clipId}”: call media_analysis(action="deepen", params={"clip_id": "${clipId}", "shot_index": ${shotIndex}}), show me the cost estimate, and after I confirm, read the frames and commit the per-shot fields via commit_shot_vision.`)}">Deepen this shot</button>
          <button id="reviewShotEditToggleBtn" ${editing ? '' : 'class="secondary"'}>${editToggleLabel}</button>
        </div>
      `;
      const shotScope = 'shot-' + (shot.shot_uuid || shotIndex);
      const shotRating = readCorrectionValue(corrections, 'shot', shot.shot_uuid || shotIndex, 'user.rating') || 0;
      const shotNotes = readCorrectionValue(corrections, 'shot', shot.shot_uuid || shotIndex, 'user.notes') || '';
      $('reviewShotRating').innerHTML = renderStarsWidget(shotRating, shotScope);
      $('reviewShotNotes').innerHTML = renderNotesWidget(shotNotes, shotScope);
      const isEmptyValue = (v) => v == null || v === '' || (Array.isArray(v) && v.length === 0);
      const groupsHtml = SHOT_FIELD_GROUPS.map(group => {
        const block = shot[group.key];
        const conf = shot.confidence && shot.confidence[group.key];
        const confTag = conf ? `<span class="conf ${escapeHtml(String(conf))}">${escapeHtml(String(conf))}</span>` : '';
        const rows = [];
        for (const field of group.fields) {
          const fieldPath = `${group.key}.${field}`;
          const value = block && typeof block === 'object' ? block[field] : undefined;
          const edited = isHumanEditedField(corrections, entityUuid, fieldPath);
          const effective = edited ? edited.value : value;
          // View mode: skip empty fields. Edit mode: show all so the user can fill in.
          if (!editing && isEmptyValue(effective)) continue;
          const valueHtml = editing
            ? renderShotFieldEditor(field, value, fieldPath, entityUuid)
            : renderShotFieldValue(effective);
          rows.push(`<div class="field ${edited ? 'edited' : ''}" data-field-path="${escapeHtml(fieldPath)}">
            <div class="label">${escapeHtml(field)}</div>
            <div class="value">${valueHtml}</div>
          </div>`);
        }
        // Hide the whole group if no rows survive (and not editing — in edit mode keep all visible).
        if (!editing && rows.length === 0) return '';
        return `<div class="group">
          <div class="group-title">${escapeHtml(group.title)}${confTag}</div>
          ${rows.join('')}
        </div>`;
      }).join('');
      // Decide whether the report actually carries shot-level analysis. If
      // every schema group is null/empty (the common case for analyses that
      // only filled the clip-level layers), tell the user instead of showing
      // an empty pane.
      const hasAnyGroup = SHOT_FIELD_GROUPS.some(group => {
        const block = shot[group.key];
        return block && typeof block === 'object' && Object.values(block).some(v => v != null && v !== '' && (!Array.isArray(v) || v.length > 0));
      });
      const qcFlags = Array.isArray(shot.qc_flags) ? shot.qc_flags : [];
      let extrasHtml = '';
      if (qcFlags.length) {
        extrasHtml += `<div class="group"><div class="group-title">QC flags</div><div class="chip-row" style="display:flex;flex-wrap:wrap;gap:4px">${qcFlags.map(f => `<span class="review-chip">${escapeHtml(String(f))}</span>`).join('')}</div></div>`;
      }
      if (Array.isArray(shot.frame_indices_used) && shot.frame_indices_used.length) {
        const n = shot.frame_indices_used.length;
        extrasHtml += `<div class="group"><div class="group-title">Sampled frames</div><div class="value" style="font-size:12px;color:var(--text-secondary)" title="frame indices ${escapeHtml(shot.frame_indices_used.join(', '))}">${n} frame${n === 1 ? '' : 's'} sampled from this shot (shown below)</div></div>`;
      }
      const emptyHint = !hasAnyGroup && !editing
        ? `<div class="empty" style="padding:var(--space-3);border:1px dashed var(--border-default);border-radius:var(--radius-md);color:var(--text-tertiary);font-size:12px">Shot-level analysis fields aren't populated in the report. The clip-level analysis blocks (above on the clip detail page) cover this clip. Re-run analysis with a fuller vision pass to fill in per-shot Visual / Content / Editorial fields.</div>`
        : '';
      $('reviewShotFields').innerHTML = groupsHtml + extrasHtml + emptyHint;
      const frames = data.frames || [];
      const FRAME_REASON_LABELS = {
        shot_start: 'Shot start', shot_end: 'Shot end', shot_progress: 'Mid-shot',
        shot_representative: 'Key frame', cut_after: 'After cut', cut_before: 'Before cut',
        flash_candidate: 'Flash frame', motion_peak: 'Motion peak', interval: 'Interval sample',
        scene_change: 'Scene change', first_usable: 'First usable', last_usable: 'Last usable',
        midpoint: 'Midpoint',
      };
      $('reviewShotFrames').innerHTML = frames.map(f => {
        const peak = f.motion_peak ? 'peak' : '';
        const src = clipId ? `/api/clips/${encodeURIComponent(clipId)}/frames/${f.frame_index}` : '';
        return `<div class="review-shot-frame-card ${peak}">
          ${src ? `<img class="review-thumb" loading="lazy" src="${src}" alt="frame ${f.frame_index}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'review-thumb placeholder',textContent:'frame missing'}))">` : ''}
          <div class="label">
            <span>${f.time_seconds != null ? `${Number(f.time_seconds).toFixed(2)}s` : `#${f.frame_index}`}</span>
            <span title="${escapeHtml(f.selection_reason || '')}">${escapeHtml(FRAME_REASON_LABELS[f.selection_reason] || f.selection_reason || '')}</span>
          </div>
        </div>`;
      }).join('');
    }

    function renderShotFieldEditor(field, value, fieldPath, entityUuid) {
      const enums = ENUM_OPTIONS[field];
      const safeValue = value == null ? '' : String(value);
      if (enums) {
        const options = ['', ...enums].map(opt => `<option value="${escapeHtml(opt)}" ${opt === safeValue ? 'selected' : ''}>${escapeHtml(opt || '—')}</option>`).join('');
        return `<select data-field-input="${escapeHtml(fieldPath)}" data-entity-uuid="${escapeHtml(String(entityUuid))}">${options}</select>
          <div class="field-actions"><button class="secondary" data-save-field="${escapeHtml(fieldPath)}">Save</button></div>`;
      }
      if (typeof value === 'boolean') {
        return `<label><input type="checkbox" data-field-input="${escapeHtml(fieldPath)}" data-entity-uuid="${escapeHtml(String(entityUuid))}" ${value ? 'checked' : ''}> ${escapeHtml(String(value))}</label>
          <div class="field-actions"><button class="secondary" data-save-field="${escapeHtml(fieldPath)}">Save</button></div>`;
      }
      const tagName = safeValue.length > 60 ? 'textarea' : 'input';
      return `<${tagName} data-field-input="${escapeHtml(fieldPath)}" data-entity-uuid="${escapeHtml(String(entityUuid))}" value="${escapeHtml(safeValue)}">${tagName === 'textarea' ? escapeHtml(safeValue) : ''}</${tagName}>
        <div class="field-actions"><button class="secondary" data-save-field="${escapeHtml(fieldPath)}">Save</button></div>`;
    }

    async function saveShotField(fieldPath, entityUuid) {
      const root = $('reviewShotFields');
      const input = root && root.querySelector(`[data-field-input="${cssEscape(fieldPath)}"]`);
      if (!input) return;
      let newValue;
      if (input.tagName === 'SELECT') newValue = input.value || null;
      else if (input.type === 'checkbox') newValue = input.checked;
      else newValue = input.value;
      const clipId = state.review.currentClipId;
      const body = {
        entity_type: 'shot',
        entity_uuid: entityUuid,
        shot_index: state.review.currentShotIndex,
        field_path: fieldPath,
        new_value: newValue,
        author: 'control_panel',
        reason: 'panel inline edit',
      };
      const result = await api(`/api/clips/${encodeURIComponent(clipId)}/corrections`, { method: 'POST', body: JSON.stringify(body) })
        .catch(err => ({ success: false, error: String(err) }));
      if (!result.success) {
        alertError(result.error || 'Save failed');
        return;
      }
      // Reload shot so it reflects the new correction.
      await openShotDetail(state.review.currentShotIndex, { writePanelState: false });
    }

    function cssEscape(value) {
      if (window.CSS && CSS.escape) return CSS.escape(value);
      return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\\\$&');
    }

    async function openShotInResolve() {
      const clipId = state.review.currentClipId;
      const shot = state.review.currentShotData && state.review.currentShotData.shot;
      if (!clipId || !shot) return;
      const body = {
        action: 'open_in_viewer',
        clip_id: clipId,
        mark_in_seconds: shot.time_seconds_start,
        mark_out_seconds: shot.time_seconds_end,
        page: 'media',
      };
      const result = await api('/api/resolve/open_clip', { method: 'POST', body: JSON.stringify(body) })
        .catch(err => ({ success: false, error: String(err) }));
      if (!result.success) {
        alertError(result.error || 'Open in Resolve failed');
      }
    }

    async function openClipInResolve() {
      const clipId = state.review.currentClipId;
      if (!clipId) return;
      // No mark_in/out → opens the full clip; clear_marks wipes any leftover
      // shot-range marks from a previous "Open in Resolve" on a shot.
      const body = {
        action: 'open_in_viewer',
        clip_id: clipId,
        clear_marks: true,
        page: 'media',
      };
      const result = await api('/api/resolve/open_clip', { method: 'POST', body: JSON.stringify(body) })
        .catch(err => ({ success: false, error: String(err) }));
      if (!result.success) {
        alertError(result.error || 'Open in Resolve failed');
      }
    }

    function renderReviewView() {
      if (state.review.view === 'bin') {
        renderReviewBin();
      } else if (state.review.view === 'clip') {
        renderClipDetail();
      } else if (state.review.view === 'shot') {
        renderShotDetail();
      }
    }

    async function writePanelStateAsync(updates) {
      try {
        await api('/api/panel_state', { method: 'POST', body: JSON.stringify(updates) });
      } catch (err) {
        // best-effort
      }
    }

    async function pollPanelStateOnce() {
      const data = await api('/api/panel_state').catch(() => null);
      if (!data || !data.success) return;
      const incoming = data.state || {};
      state.review.lastPanelStateAt = incoming.updated_at || null;
      // Only react if the chat (or some other writer) updated the state and we
      // are not the most recent writer. Treat 'control_panel' as our own writes.
      if (incoming.last_written_by === 'control_panel') return;
      const targetView = incoming.current_view;
      const targetClip = incoming.current_clip_id;
      const targetShot = incoming.current_shot_index;
      if (!(state.activePanel === 'analysis' && state.activeSubpages.analysis === 'review')) return;
      if (targetView === 'shot' && targetClip && targetShot != null) {
        if (state.review.currentClipId !== targetClip) {
          await openClipDetail(targetClip, { writePanelState: false });
        }
        if (state.review.currentShotIndex !== Number(targetShot)) {
          await openShotDetail(Number(targetShot), { writePanelState: false });
        }
        return;
      }
      if (targetView === 'clip' && targetClip) {
        if (state.review.currentClipId !== targetClip) {
          await openClipDetail(targetClip, { writePanelState: false });
        } else if (state.review.view !== 'clip') {
          reviewSetView('clip', { writePanelState: false });
        }
        return;
      }
      if (targetView === 'bin' && state.review.view !== 'bin') {
        reviewSetView('bin', { writePanelState: false });
      }
    }

    function ensureReviewPanelStateTimer() {
      if (state.review.panelStateTimer) return;
      state.review.panelStateTick = 0;
      state.review.panelStateTimer = window.setInterval(() => {
        if (document.hidden) return;
        state.review.panelStateTick = (state.review.panelStateTick + 1) % 5;
        if (!document.hasFocus() && state.review.panelStateTick !== 0) return;
        if (state.activePanel === 'analysis' && state.activeSubpages.analysis === 'review') {
          pollPanelStateOnce().catch(() => {});
        }
      }, 2000);
    }
    // ─── End V2 Review surface ──────────────────────────────────────────

    function readPreferences() {
      try {
        return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem('resolveMcpDashboardPrefs') || '{}') };
      } catch {
        return { ...DEFAULT_PREFS };
      }
    }

    function writePreferences(prefs) {
      localStorage.setItem('resolveMcpDashboardPrefs', JSON.stringify(prefs));
    }

    function syncPreferencesPanel() {
      renderSetupPreferences();
    }

    async function refreshSetupDefaults() {
      const [defaultsPayload, schemaPayload] = await Promise.all([
        api('/api/setup/defaults'),
        api('/api/setup/schema'),
      ]);
      state.setupDefaults = defaultsPayload.defaults || {};
      state.setupSchema = schemaPayload.defaults || {};
      renderSetupPreferences();
    }

    function setControlValue(id, value) {
      const el = $(id);
      if (!el) return;
      el.value = value == null ? '' : String(value);
    }

    function setControlChecked(id, value) {
      const el = $(id);
      if (el) el.checked = Boolean(value);
    }

    function hydratePreferenceHelp() {
      Object.entries(PREFERENCE_HELP).forEach(([id, copy]) => {
        const control = $(id);
        const label = control?.closest('label');
        if (!label || label.querySelector(`[data-help-for="${id}"]`)) return;
        const help = document.createElement('span');
        help.className = 'field-help';
        help.dataset.helpFor = id;
        help.textContent = copy;
        label.appendChild(help);
      });
    }

    function syncMarkerLimitMode() {
      const mode = $('prefMaxTimedMarkersMode');
      const input = $('prefMaxTimedMarkers');
      if (!mode || !input) return;
      const unlimited = mode.value === 'unlimited';
      input.disabled = unlimited;
      if (unlimited) {
        input.value = '0';
      } else if (Number(input.value || 0) < 1) {
        input.value = '12';
      }
    }

    function markerLimitValue() {
      const mode = $('prefMaxTimedMarkersMode')?.value || 'limited';
      if (mode === 'unlimited') return 0;
      return Math.max(1, Math.min(250, Number($('prefMaxTimedMarkers').value || 12)));
    }

    function uniqueValues(...lists) {
      const seen = new Set();
      const values = [];
      lists.flat().forEach(value => {
        const normalized = String(value || '').trim();
        if (!normalized || seen.has(normalized)) return;
        seen.add(normalized);
        values.push(normalized);
      });
      return values;
    }

    function renderTokenPills(containerId, countId, hiddenId, candidates, activeValues) {
      const container = $(containerId);
      const hidden = $(hiddenId);
      if (!container || !hidden) return;
      const active = new Set((activeValues || []).map(value => String(value || '').trim()).filter(Boolean));
      const values = uniqueValues(candidates || [], Array.from(active));
      hidden.value = Array.from(active).join(', ');
      container.innerHTML = values.map(value => {
        const label = String(value).replace(/_/g, ' ');
        return `
        <button type="button" class="token-pill${active.has(value) ? ' active' : ''}" data-token-value="${escapeHtml(value)}" aria-pressed="${active.has(value) ? 'true' : 'false'}" title="${escapeHtml(value)}">${escapeHtml(label)}</button>
      `; }).join('');
      container.querySelectorAll('[data-token-value]').forEach(button => {
        button.addEventListener('click', () => {
          button.classList.toggle('active');
          button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
          syncTokenPills(containerId, countId, hiddenId);
        });
      });
      syncTokenPills(containerId, countId, hiddenId);
    }

    function syncTokenPills(containerId, countId, hiddenId) {
      const active = activeTokenValues(containerId);
      const hidden = $(hiddenId);
      if (hidden) hidden.value = active.join(', ');
      setText(countId, `${active.length} enabled`);
    }

    function activeTokenValues(containerId) {
      const container = $(containerId);
      if (!container) return [];
      return Array.from(container.querySelectorAll('.token-pill.active'))
        .map(button => button.dataset.tokenValue)
        .filter(Boolean);
    }

    function renderSetupPreferences() {
      const media = state.setupDefaults?.media_analysis;
      const updates = state.setupDefaults?.updates;
      if (!media || !updates) {
        setText('setupPrefsStatus', 'Loading setup defaults');
        setHtml('preferencesStorage', '<div class="empty">Loading preference storage.</div>');
        return;
      }
      setText('setupPrefsStatus', `Server defaults loaded · ${new Date().toLocaleTimeString()}`);
      setControlValue('prefVisionDefault', media.vision_default);
      setControlValue('prefTranscriptionDefault', media.transcription_default);
      setControlValue('prefSlateDetectionDefault', media.slate_detection_default);
      setControlValue('prefSourceTrust', media.source_trust || 'auto');
      setControlValue('prefDepth', media.default_depth || 'standard');
      setControlValue('prefFrames', media.default_sample_frames ?? 8);
      // sampling_mode_default is null when unset → show "ask".
      setControlValue('prefSamplingMode', media.sampling_mode_default || 'ask');
      setControlValue('prefSamplingRate', media.sampling_frames_per_minute ?? 4);
      setControlValue('prefSamplingFloor', media.sampling_frame_floor ?? 3);
      setControlValue('prefSamplingCeiling', media.sampling_frame_ceiling ?? 80);
      updateSamplingModeHint();
      setControlValue('prefAnalysisPersistence', media.analysis_persistence);
      const legacySummaryMap = { assistant_editor: 'creative', producer: 'creative', qc: 'technical' };
      const summaryStyle = legacySummaryMap[media.analysis_summary_style] || media.analysis_summary_style || 'concise';
      setControlValue('prefAnalysisSummaryStyle', summaryStyle);
      setControlValue('prefReportFormat', media.report_format);
      setControlValue('prefTimedMarkersDefault', media.timed_markers_default || 'ask');
      setControlValue('prefMetadataOverwritePolicy', media.metadata_overwrite_policy);
      const markerLimit = Number(media.max_timed_markers_per_clip ?? 12);
      setControlValue('prefMaxTimedMarkersMode', markerLimit === 0 ? 'unlimited' : 'limited');
      setControlValue('prefMaxTimedMarkers', markerLimit === 0 ? 0 : markerLimit);
      syncMarkerLimitMode();
      setControlValue('prefMarkerCustomData', media.marker_custom_data);
      renderTokenPills(
        'prefMetadataFieldPills',
        'prefMetadataFieldCount',
        'prefMetadataFields',
        uniqueValues(METADATA_FIELD_CANDIDATES, media.metadata_publish_fields || []),
        media.metadata_publish_fields || []
      );
      renderTokenPills(
        'prefTimedMarkerTypePills',
        'prefTimedMarkerTypeCount',
        'prefTimedMarkerTypes',
        uniqueValues(media.options?.timed_marker_types || [], media.timed_marker_types || []),
        media.timed_marker_types || []
      );
      setControlValue('prefTimedMarkerColors', JSON.stringify(media.timed_marker_colors || {}, null, 2));
      setControlChecked('prefIncludeConfidenceScores', media.include_confidence_scores);
      setControlChecked('prefIncludeSourceTimeNotes', media.include_source_time_notes);
      setControlChecked('prefAskBeforeMetadataPublish', media.ask_before_metadata_publish);
      setControlChecked('prefDryRunFirstDefault', media.dry_run_first_default);
      setControlValue('prefPreferredAnalysisRoot', media.preferred_analysis_root || '');
      setControlValue('prefPreferredGeneratedMediaFolder', media.preferred_generated_media_folder || '');
      setControlValue('prefInventoryLimit', media.inventory_limit || 500);
      setControlValue('prefInventoryExcludeBins', media.inventory_exclude_bins || '');
      setControlValue('prefPostOperationPage', media.default_post_operation_page);
      setControlValue('prefUpdateMode', updates.mode);
      setControlValue('prefUpdateIntervalHours', updates.check_interval_hours);
      setControlValue('prefUpdateSnoozeHours', updates.snooze_hours);

      const projectRoot = state.activeContext?.project_root || state.boot?.project_root || '';
      const storageCards = [
        `<div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.root}Project root</div>
            ${statusPill(projectRoot ? 'pill-ok' : 'pill-mute', projectRoot ? 'Active' : 'Pending')}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Path', projectRoot || 'Pending', { muted: !projectRoot })}
          </div>
        </div>`,
        `<div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.database}Server defaults</div>
            ${statusPill(media.preferences_path ? 'pill-ok' : 'pill-mute', media.preferences_path ? 'Persisted' : 'Default')}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Path', media.preferences_path || 'Default preferences path', { muted: !media.preferences_path })}
          </div>
        </div>`,
        `<div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.database}Update state</div>
            ${statusPill(updates.state_path ? 'pill-ok' : 'pill-mute', updates.state_path ? 'Tracked' : 'Default')}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Path', updates.state_path || 'Default update state path', { muted: !updates.state_path })}
          </div>
        </div>`,
        `<div class="diag-card">
          <div class="diag-card-header">
            <div class="diag-card-title">${DIAG_ICONS.database}Dashboard prefs</div>
            ${statusPill('pill-info', 'Browser-local')}
          </div>
          <div class="diag-card-rows">
            ${diagRow('Store', 'Browser localStorage', { muted: false })}
            ${diagRow('Scope', 'This browser profile only', { muted: false })}
          </div>
        </div>`,
      ];
      setHtml('preferencesStorage', storageCards.join(''));
    }

    function applyPreferencesToControls(prefs, reschedule = false) {
      if ($('autoPollMedia')) $('autoPollMedia').checked = Boolean(prefs.autoPoll);
      if ($('mediaPollInterval')) $('mediaPollInterval').value = String(prefs.pollInterval || DEFAULT_PREFS.pollInterval);
      if (reschedule) scheduleMediaPoll();
    }

    function dashboardPreferencePayload() {
      return {
        autoPoll: $('autoPollMedia')?.checked ?? DEFAULT_PREFS.autoPoll,
        pollInterval: $('mediaPollInterval')?.value ?? DEFAULT_PREFS.pollInterval,
      };
    }

    // Rough per-frame vision cost for the estimate (≈768px frame at typical
    // tokenization). The engine's pre-call refusal estimates more conservatively.
    const SAMPLING_TOKENS_PER_FRAME = 450;
    function _fmtTokens(frames) {
      const k = (frames * SAMPLING_TOKENS_PER_FRAME) / 1000;
      return k >= 1 ? `~${k.toFixed(k < 10 ? 1 : 0)}k tokens` : `~${Math.round(k * 1000)} tokens`;
    }
    function updateSamplingModeHint() {
      const hintEl = document.getElementById('samplingModeHint');
      if (!hintEl) return;
      const mode = ($('prefSamplingMode') || {}).value || 'ask';
      const rate = Number(($('prefSamplingRate') || {}).value) || 4;
      const floor = Number(($('prefSamplingFloor') || {}).value) || 3;
      const ceil = Number(($('prefSamplingCeiling') || {}).value) || 80;
      const fixed = Number(($('prefFrames') || {}).value) || 8;
      let msg = '';
      if (mode === 'ask') {
        msg = 'You will be asked to pick a mode the first time you analyze. Recommended: Thorough.';
      } else if (mode === 'fixed') {
        msg = `Economy — flat ${fixed} frames per clip regardless of length (${_fmtTokens(fixed)}/clip). Most predictable.`;
      } else if (mode === 'per_minute') {
        const oneMin = Math.max(floor, Math.min(ceil, Math.round(rate)));
        const tenMin = Math.max(floor, Math.min(ceil, Math.round(rate * 10)));
        msg = `Balanced — ${rate}/min, bounded ${floor}–${ceil}. ~${oneMin}f (${_fmtTokens(oneMin)}) for 1 min · ~${tenMin}f (${_fmtTokens(tenMin)}) for 10 min. Linear cost.`;
      } else if (mode === 'adaptive_capped') {
        msg = `Thorough — content-aware (shot boundaries + flashes), bounded ${floor}–${ceil} frames/clip (${_fmtTokens(floor)}–${_fmtTokens(ceil)}). Best coverage, bounded cost.`;
      } else if (mode === 'adaptive') {
        msg = `Thorough (uncapped) — content-aware, no per-clip ceiling (up to 512 frames, ${_fmtTokens(512)}). Use only for short/few clips.`;
      }
      hintEl.textContent = msg;
    }

    function setupPreferencePayload() {
      let markerColors = {};
      try {
        markerColors = JSON.parse($('prefTimedMarkerColors').value || '{}');
      } catch {
        throw new Error('Marker colors must be valid JSON.');
      }
      return {
        media_analysis: {
          vision_default: $('prefVisionDefault').value,
          transcription_default: $('prefTranscriptionDefault').value,
          slate_detection_default: $('prefSlateDetectionDefault').value,
          source_trust: $('prefSourceTrust').value,
          default_depth: $('prefDepth').value,
          default_sample_frames: Number($('prefFrames').value || 8),
          sampling_mode_default: $('prefSamplingMode').value,
          sampling_frames_per_minute: Number($('prefSamplingRate').value || 4),
          sampling_frame_floor: Number($('prefSamplingFloor').value || 3),
          sampling_frame_ceiling: Number($('prefSamplingCeiling').value || 80),
          analysis_persistence: $('prefAnalysisPersistence').value,
          analysis_summary_style: $('prefAnalysisSummaryStyle').value,
          report_format: $('prefReportFormat').value,
          timed_markers_default: $('prefTimedMarkersDefault').value,
          metadata_overwrite_policy: $('prefMetadataOverwritePolicy').value,
          max_timed_markers_per_clip: markerLimitValue(),
          marker_custom_data: $('prefMarkerCustomData').value,
          metadata_publish_fields: activeTokenValues('prefMetadataFieldPills'),
          timed_marker_types: activeTokenValues('prefTimedMarkerTypePills'),
          timed_marker_colors: markerColors,
          include_confidence_scores: $('prefIncludeConfidenceScores').checked,
          include_source_time_notes: $('prefIncludeSourceTimeNotes').checked,
          ask_before_metadata_publish: $('prefAskBeforeMetadataPublish').checked,
          dry_run_first_default: $('prefDryRunFirstDefault').checked,
          preferred_analysis_root: $('prefPreferredAnalysisRoot').value.trim() || 'clear',
          preferred_generated_media_folder: $('prefPreferredGeneratedMediaFolder').value.trim() || 'clear',
          inventory_limit: parseInt($('prefInventoryLimit').value, 10) || 500,
          inventory_exclude_bins: $('prefInventoryExcludeBins').value.trim(),
          default_post_operation_page: $('prefPostOperationPage').value,
        },
        updates: {
          mode: $('prefUpdateMode').value,
          check_interval_hours: Number($('prefUpdateIntervalHours').value || 24),
          snooze_hours: Number($('prefUpdateSnoozeHours').value || 24),
        },
      };
    }

    async function savePreferences() {
      const prefs = {
        ...dashboardPreferencePayload(),
      };
      writePreferences(prefs);
      applyPreferencesToControls(prefs, true);
      setText('prefSaveStatus', 'Saving defaults');
      const payload = setupPreferencePayload();
      const saved = await api('/api/setup/defaults', { method: 'POST', body: JSON.stringify(payload) });
      state.setupDefaults = saved.defaults || state.setupDefaults;
      syncPreferencesPanel();
      setText('prefSaveStatus', `Saved · ${new Date().toLocaleTimeString()}`);
    }

    async function resetPreferences() {
      const proceed = await brandedConfirm({
        kicker: 'Preferences',
        title: 'Reset all preferences?',
        body: 'Server defaults and dashboard convenience preferences will return to their factory state.',
        detail: 'This cannot be undone, but you can re-save your custom values afterwards.',
        confirmLabel: 'Reset',
        cancelLabel: 'Keep my settings',
        tone: 'danger',
      });
      if (!proceed) {
        return;
      }
      localStorage.removeItem('resolveMcpDashboardPrefs');
      const prefs = readPreferences();
      applyPreferencesToControls(prefs, true);
      setText('prefSaveStatus', 'Resetting defaults');
      const reset = await api('/api/setup/clear', { method: 'POST', body: JSON.stringify({ keys: 'all' }) });
      state.setupDefaults = reset.defaults || state.setupDefaults;
      syncPreferencesPanel();
      setText('prefSaveStatus', `Reset · ${new Date().toLocaleTimeString()}`);
    }

    async function _legacySearchIndexUnused() {
      // Legacy search index endpoint preserved for callers; the UI moved to Review.
      const q = '';
      const payload = await api(`/api/index/query?q=${encodeURIComponent(q)}`);
      const wrap = { innerHTML: '' };
      if (!payload.results?.length) {
        wrap.innerHTML = '<div class="empty">No indexed matches.</div>';
        return;
      }
      wrap.innerHTML = payload.results.map(row => `
        <div class="result">
          <b>${escapeHtml(row.clip_name || row.clip_key || 'Result')}</b>
          <small>${escapeHtml(row.result_type || '')}${row.start_seconds != null ? ` · ${row.start_seconds}s` : ''}</small>
          <div>${escapeHtml(row.summary || row.file_path || '')}</div>
        </div>
      `).join('');
    }

    function renderDocsOverview() {
      $('panel-docs').classList.remove('doc-detail');
      document.querySelectorAll('[data-doc]').forEach(button => {
        button.classList.toggle('active', false);
      });
      delete $('docReader').dataset.loaded;
      setHtml('docReader', '<div class="empty">Choose a document.</div>');
      setHtml('docSectionNav', '<div class="empty">Open a document.</div>');
      setText('docMeta', '');
      setText('docSource', '');
      renderBreadcrumb();
    }

    async function loadDoc(docId, options = {}) {
      state.activeDoc = DOC_LABELS[docId] ? docId : 'readme';
      state.activeSubpages.docs = state.activeDoc;
      renderSubpage('docs', state.activeDoc);
      $('panel-docs').classList.add('doc-detail');
      document.querySelectorAll('[data-doc]').forEach(button => {
        button.classList.toggle('active', button.dataset.doc === state.activeDoc);
      });
      renderBreadcrumb();
      setText('docMeta', 'Loading document');
      setHtml('docReader', '<div class="empty">Loading document.</div>');
      setText('docSource', '');
      const payload = await api(`/api/docs?doc=${encodeURIComponent(state.activeDoc)}`);
      $('docReader').dataset.loaded = state.activeDoc;
      setText('docMeta', `${payload.title} · ${payload.path}`);
      if (options.updateHash !== false) {
        updateRouteHash('docs', state.activeDoc);
      }
      const rendered = renderMarkdown(payload.content || '', payload.path || '');
      setHtml('docReader', rendered.html);
      renderDocSectionNav(rendered.sections);
      setText('docSource', payload.path || '');
      applyDocFilters();
    }

    function renderMarkdown(markdown, docPath) {
      const lines = String(markdown || '').split(/\r?\n/);
      const parts = [];
      const sections = [];
      let inCode = false;
      let codeLines = [];
      const flushCode = () => {
        if (!codeLines.length) return;
        parts.push(`<div class="doc-block" data-md-type="code"><pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre></div>`);
        codeLines = [];
      };
      for (let index = 0; index < lines.length; index += 1) {
        const rawLine = lines[index];
        if (rawLine.trim().startsWith('```')) {
          if (inCode) {
            flushCode();
            inCode = false;
          } else {
            inCode = true;
          }
          continue;
        }
        if (inCode) {
          codeLines.push(rawLine);
          continue;
        }
        const line = rawLine.trimEnd();
        if (!line.trim()) continue;
        const badgeMatches = parseBadgeTokens(line.trim());
        // Badge rows are external status shields; a linked LOCAL image (e.g.
        // the README's control-panel screenshot) must reach the image handlers.
        if (badgeMatches.length && badgeMatches.every(token => /^https?:/i.test(token.src))) {
          while (index + 1 < lines.length) {
            const nextMatches = parseBadgeTokens(lines[index + 1].trim());
            if (!nextMatches.length) break;
            badgeMatches.push(...nextMatches);
            index += 1;
          }
          parts.push(renderBadgeTokens(badgeMatches));
          continue;
        }
        if (line.trim().startsWith('|')) {
          const tableLines = [];
          while (index < lines.length && lines[index].trim().startsWith('|')) {
            tableLines.push(lines[index].trim());
            index += 1;
          }
          index -= 1;
          parts.push(renderMarkdownTable(tableLines));
          continue;
        }
        const heading = line.match(/^(#{1,3})\s+(.+)$/);
        if (heading) {
          const level = heading[1].length;
          const text = stripMarkdown(heading[2]);
          const id = `doc-section-${sections.length}`;
          sections.push({ id, text, level });
          parts.push(`<h${level} id="${id}" class="doc-block" data-md-type="heading">${inlineMarkdown(heading[2])}</h${level}>`);
          continue;
        }
        const linkedImage = line.match(/^\[!\[([^\]]*)\]\(([^)]+)\)\]\(([^)]+)\)$/);
        if (linkedImage) {
          parts.push(renderImageBlock(linkedImage[1], linkedImage[2], docPath));
          continue;
        }
        const image = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
        if (image) {
          parts.push(renderImageBlock(image[1], image[2], docPath));
          continue;
        }
        const bullet = line.match(/^[-*]\s+(.+)$/) || line.match(/^\d+\.\s+(.+)$/);
        if (bullet) {
          parts.push(`<div class="doc-bullet doc-block" data-md-type="list">${inlineMarkdown(bullet[1])}</div>`);
          continue;
        }
        parts.push(`<p class="doc-block" data-md-type="text">${inlineMarkdown(line)}</p>`);
      }
      if (inCode) flushCode();
      return { html: parts.join('') || '<div class="empty">Document is empty.</div>', sections };
    }

    function renderBadgeLine(line) {
      const matches = parseBadgeTokens(line);
      if (!matches.length) return '';
      return renderBadgeTokens(matches);
    }

    function renderBadgeTokens(matches) {
      const badges = matches.map(match => {
        const alt = match.alt || 'badge';
        const src = match.src || '';
        const href = match.href || '';
        const img = `<img src="${escapeAttribute(src)}" alt="${escapeAttribute(alt)}" loading="lazy">`;
        return href
          ? `<a href="${escapeAttribute(href)}" target="_blank" rel="noreferrer">${img}</a>`
          : `<span>${img}</span>`;
      }).join('');
      return `<div class="doc-badges doc-block" data-md-type="image">${badges}</div>`;
    }

    function parseBadgeTokens(line) {
      const tokens = [];
      let rest = String(line || '').trim();
      while (rest) {
        if (rest.startsWith('[![')) {
          const altEnd = rest.indexOf('](', 3);
          if (altEnd < 0) return [];
          const srcEnd = rest.indexOf(')](', altEnd + 2);
          if (srcEnd < 0) return [];
          const hrefEnd = rest.indexOf(')', srcEnd + 3);
          if (hrefEnd < 0) return [];
          tokens.push({
            alt: rest.slice(3, altEnd),
            src: rest.slice(altEnd + 2, srcEnd),
            href: rest.slice(srcEnd + 3, hrefEnd),
          });
          rest = rest.slice(hrefEnd + 1).trim();
          continue;
        }
        if (rest.startsWith('![')) {
          const altEnd = rest.indexOf('](', 2);
          if (altEnd < 0 || !rest.endsWith(')')) return [];
          tokens.push({
            alt: rest.slice(2, altEnd),
            src: rest.slice(altEnd + 2, -1),
            href: '',
          });
          rest = '';
          continue;
        }
        return [];
      }
      return tokens;
    }

    function resolveDocAsset(src, docPath) {
      const clean = String(src || '').trim();
      if (/^(https?:|data:|\/)/i.test(clean)) return clean;
      const stack = [];
      const parts = String(docPath || '').split('/').slice(0, -1).concat(clean.split('/'));
      for (const part of parts) {
        if (!part || part === '.') continue;
        if (part === '..') { stack.pop(); continue; }
        stack.push(part);
      }
      const rel = stack.join('/');
      const marker = 'docs/images/';
      if (rel.startsWith(marker)) {
        return '/api/doc_asset/' + rel.slice(marker.length).split('/').map(encodeURIComponent).join('/');
      }
      return clean;
    }

    function renderImageBlock(alt, src, docPath) {
      const resolved = resolveDocAsset(src, docPath);
      return `<figure class="doc-image doc-block" data-md-type="image"><img src="${escapeAttribute(resolved)}" alt="${escapeAttribute(alt || src)}" loading="lazy"></figure>`;
    }

    function renderMarkdownTable(lines) {
      const rows = lines
        .filter(line => !/^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line))
        .map(line => line.replace(/^\||\|$/g, '').split('|').map(cell => cell.trim()));
      if (!rows.length) return '';
      const header = rows.shift();
      const head = `<thead><tr>${header.map(cell => `<th>${inlineMarkdown(cell)}</th>`).join('')}</tr></thead>`;
      const body = `<tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${inlineMarkdown(cell)}</td>`).join('')}</tr>`).join('')}</tbody>`;
      return `<div class="doc-block" data-md-type="table"><table>${head}${body}</table></div>`;
    }

    function renderDocSectionNav(sections) {
      const nav = $('docSectionNav');
      if (!nav) return;
      if (!sections.length) {
        nav.classList.remove('collapsed');
        setHtml('docSectionNav', '<div class="empty">No headings found.</div>');
        return;
      }
      const VISIBLE = 8;
      const collapsible = sections.length > VISIBLE;
      const links = sections.map((section, idx) => {
        const hidden = collapsible && idx >= VISIBLE ? ' is-hidden' : '';
        return `<button class="doc-section-link${hidden}" data-doc-section="${escapeHtml(section.id)}" style="padding-left:${8 + (section.level - 1) * 10}px">${escapeHtml(section.text)}</button>`;
      }).join('');
      const toggle = collapsible
        ? `<button class="doc-section-toggle" data-doc-section-toggle="expand">Show all (${sections.length - VISIBLE} more)</button>`
        : '';
      nav.classList.toggle('collapsed', collapsible);
      setHtml('docSectionNav', links + toggle);
      nav.querySelectorAll('[data-doc-section]').forEach(button => {
        button.addEventListener('click', () => {
          const target = document.getElementById(button.dataset.docSection);
          if (target) scrollDocSection(target);
        });
      });
      const toggleBtn = nav.querySelector('[data-doc-section-toggle]');
      if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
          if (nav.classList.contains('collapsed')) {
            nav.classList.remove('collapsed');
            toggleBtn.textContent = 'Show fewer';
            toggleBtn.dataset.docSectionToggle = 'collapse';
          } else {
            nav.classList.add('collapsed');
            toggleBtn.textContent = `Show all (${sections.length - VISIBLE} more)`;
            toggleBtn.dataset.docSectionToggle = 'expand';
          }
        });
      }
    }

    function scrollDocSection(target) {
      const reader = $('docReader');
      if (reader && reader.contains(target)) {
        const readerRect = reader.getBoundingClientRect();
        const targetRect = target.getBoundingClientRect();
        const top = reader.scrollTop + targetRect.top - readerRect.top - 22;
        reader.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
        return;
      }
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function applyDocFilters() {
      const enabled = new Set(Array.from(document.querySelectorAll('[data-md-filter]'))
        .filter(input => input.checked)
        .map(input => input.dataset.mdFilter));
      document.querySelectorAll('#docReader [data-md-type]').forEach(block => {
        block.classList.toggle('hidden', !enabled.has(block.dataset.mdType));
      });
    }

    function stripMarkdown(value) {
      return String(value || '')
        .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
        .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
        .replace(/[`*_#]/g, '')
        .trim();
    }

    function commaList(value) {
      return String(value || '')
        .split(/[,;\n]/)
        .map(item => item.trim())
        .filter(Boolean);
    }

    function inlineMarkdown(value) {
      let html = escapeHtml(value);
      html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
      html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<span>$1</span>');
      return html;
    }

    function escapeHtml(value) {
      return String(value ?? '').replace(/[&<>"']/g, char => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[char]));
    }

    function escapeAttribute(value) {
      return escapeHtml(value).replace(/`/g, '&#96;');
    }

    function cssToken(value) {
      return String(value ?? 'unknown').toLowerCase().replace(/[^a-z0-9_-]+/g, '_');
    }

    function formatBytes(value) {
      const n = Number(value || 0);
      if (n < 1024) return `${n} B`;
      if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
      if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
      return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`;
    }

    function closeNavDropdowns(except = null) {
      document.querySelectorAll('.control-nav-item.open').forEach(item => {
        if (item === except) return;
        item.classList.remove('open');
        item.querySelector('.control-tab.has-menu')?.setAttribute('aria-expanded', 'false');
      });
    }

    function toggleNavDropdown(button) {
      const item = button.closest('.control-nav-item');
      if (!item) return;
      const willOpen = !item.classList.contains('open');
      closeNavDropdowns(item);
      item.classList.toggle('open', willOpen);
      button.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    }

    function closeActionMenus(except = null) {
      document.querySelectorAll('.action-menu.open').forEach(menu => {
        if (menu === except) return;
        menu.classList.remove('open');
        menu.querySelector('[data-action-menu-trigger]')?.setAttribute('aria-expanded', 'false');
      });
    }

    function toggleActionMenu(button) {
      if (button.disabled) return;
      const menu = button.closest('.action-menu');
      if (!menu) return;
      const willOpen = !menu.classList.contains('open');
      closeActionMenus(menu);
      menu.classList.toggle('open', willOpen);
      button.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    }

    document.querySelectorAll('.control-tab.has-menu').forEach(button => {
      button.setAttribute('aria-haspopup', 'menu');
      button.setAttribute('aria-expanded', 'false');
    });

    document.querySelectorAll('[data-action-menu-trigger]').forEach(button => {
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        closeNavDropdowns();
        toggleActionMenu(button);
      });
    });

    document.querySelectorAll('[data-panel-target]').forEach(control => {
      control.addEventListener('click', (event) => {
        if (control.classList.contains('has-menu')) {
          event.stopPropagation();
          closeActionMenus();
          toggleNavDropdown(control);
          return;
        }
        closeNavDropdowns();
        closeActionMenus();
        setPanel(control.dataset.panelTarget, { subpage: control.dataset.subpageTarget });
        if (control.dataset.reviewView === 'history') {
          reviewSetView('history');
          refreshHistoryTimelines().catch(alertError);
          if (window.location.hash !== '#analysis/review/history') {
            window.history.replaceState(null, '', '#analysis/review/history');
          }
        } else if (control.dataset.reviewView === 'plans') {
          reviewSetView('plans');
          refreshEditPlans().catch(alertError);
          if (window.location.hash !== '#analysis/review/plans') {
            window.history.replaceState(null, '', '#analysis/review/plans');
          }
        }
      });
    });
    document.querySelectorAll('[data-doc]').forEach(control => {
      control.addEventListener('click', () => loadDoc(control.dataset.doc).catch(alertError));
    });
    document.querySelectorAll('[data-md-filter]').forEach(control => {
      control.addEventListener('change', applyDocFilters);
    });
    $('overviewRefresh').onclick = () => refreshAll().catch(alertError);
    $('projectsRefresh').onclick = () => refreshAllProjects().catch(alertError);
    $('projectFilterText').addEventListener('input', renderProjects);
    $('projectContextSelect').addEventListener('change', event => {
      if (event.target.value === VIEW_ALL_PROJECTS_VALUE) {
        setPanel('projects');
        restoreProjectContextSelect();
        return;
      }
      switchProjectContext(event.target.value).catch(error => {
        restoreProjectContextSelect();
        alertError(error);
      });
    });
    $('refreshMediaBtn').onclick = () => refreshResolveMedia().catch(alertError);
    $('selectReadyMediaBtn').onclick = selectReadyMedia;
    $('copyPromptFromMediaBtn').onclick = () => {
      closeActionMenus();
      copyMcpPrompt().catch(alertError);
    };
    document.querySelectorAll('[data-analyze-client]').forEach(btn => {
      btn.addEventListener('click', () => {
        closeActionMenus();
        analyzeInClient(btn.dataset.analyzeClient).catch(alertError);
      });
    });
    $('mediaFilterText').addEventListener('input', rerenderResolveMedia);
    $('mediaStatusFilter').addEventListener('change', rerenderResolveMedia);
    $('analysisStatusFilter').addEventListener('change', rerenderResolveMedia);
    $('mediaBinFilter')?.addEventListener('change', rerenderResolveMedia);
    $('mediaTypeFilter')?.addEventListener('change', rerenderResolveMedia);
    $('versionBadge')?.addEventListener('click', openUpdateModal);
    $('updateModalCancel')?.addEventListener('click', closeUpdateModal);
    $('updateModal')?.addEventListener('click', (event) => {
      if (event.target === event.currentTarget) closeUpdateModal();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && $('updateModal')?.classList.contains('open')) {
        closeUpdateModal();
      }
    });
    function persistPollPrefs() {
      try { writePreferences(dashboardPreferencePayload()); } catch {}
    }
    $('autoPollMedia').addEventListener('change', () => { persistPollPrefs(); scheduleMediaPoll(); });
    $('mediaPollInterval').addEventListener('change', () => { persistPollPrefs(); scheduleMediaPoll(); });
    document.querySelectorAll('.path-browse').forEach(btn => {
      btn.addEventListener('click', async () => {
        const target = btn.dataset.browseTarget;
        const input = $(target);
        if (!input) return;
        const originalText = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'Opening…';
        try {
          const payload = await api('/api/browse/directory', {
            method: 'POST',
            body: JSON.stringify({ initial: input.value || undefined }),
          });
          if (payload.canceled) return;
          if (payload.path) {
            input.value = payload.path;
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
          } else if (payload.error) {
            alertError(new Error(payload.error));
          }
        } catch (error) {
          alertError(error);
        } finally {
          btn.disabled = false;
          btn.textContent = originalText;
        }
      });
    });
    document.querySelectorAll('.path-recent').forEach(select => {
      select.addEventListener('change', () => {
        const target = select.dataset.recentTarget;
        const input = $(target);
        if (input && select.value) {
          input.value = select.value;
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
          select.value = '';
        }
      });
    });

    $('prefMaxTimedMarkersMode').addEventListener('change', syncMarkerLimitMode);
    $('prefMaxTimedMarkers').addEventListener('change', syncMarkerLimitMode);
    $('savePrefsBtn').onclick = () => savePreferences().catch(alertError);
    $('refreshPrefsBtn').onclick = () => refreshSetupDefaults().catch(alertError);
    $('resetPrefsBtn').onclick = () => resetPreferences().catch(alertError);
    window.addEventListener('beforeunload', () => {
      if (state.mediaPollTimer) clearInterval(state.mediaPollTimer);
      if (state.review && state.review.panelStateTimer) clearInterval(state.review.panelStateTimer);
    });
    $('reviewRefreshBtn').onclick = () => refreshReviewBin().catch(alertError);
    const historyBtnEl = $('reviewHistoryBtn');
    if (historyBtnEl) {
      historyBtnEl.onclick = () => {
        reviewSetView('history');
        refreshHistoryTimelines().catch(alertError);
      };
    }
    const historyRefreshEl = $('historyRefreshBtn');
    if (historyRefreshEl) {
      historyRefreshEl.onclick = () => refreshHistoryTimelines().catch(alertError);
    }
    const plansRefreshEl = $('plansRefreshBtn');
    if (plansRefreshEl) {
      plansRefreshEl.onclick = () => refreshEditPlans().catch(alertError);
    }
    const historyArchiveBtnEl = $('historyArchiveCurrentBtn');
    if (historyArchiveBtnEl) {
      historyArchiveBtnEl.onclick = () => {
        const reason = ($('historyArchiveReason')?.value || '').trim();
        archiveCurrentTimelineFromUI(reason).catch(alertError);
      };
    }
    // Caps widget bootstrap + listeners
    const capsPresetCardsEl = $('capsPresetCards');
    if (capsPresetCardsEl) {
      capsPresetCardsEl.addEventListener('click', (ev) => {
        const card = ev.target.closest('[data-preset-card]');
        if (!card) return;
        const preset = card.dataset.presetCard;
        if (!preset) return;
        const hidden = $('prefCapsPreset');
        if (hidden) hidden.value = preset;
        state.caps.preset = preset;
        // Optimistic UI: re-render cards + override placeholders immediately.
        renderCapsPresetCards();
        applyCapsOverridePlaceholders(preset);
        persistCapsFromUI();
      });
    }
    for (const [domId] of CAPS_OVERRIDE_FIELDS) {
      const el = $(domId);
      if (el) el.addEventListener('input', persistCapsFromUI);
    }
    refreshCapsWidget().catch(() => {});
    refreshCapsHistory().catch(() => {});
    refreshCapsRefusals().catch(() => {});
    refreshResolveAiOps().catch(() => {});

    // Caps inspector + reset
    $('capsInspectBtn')?.addEventListener('click', () => inspectCapsFromUI().catch(alertError));
    $('capsResetDayBtn')?.addEventListener('click', () => resetDayUsageFromUI().catch(alertError));

    // Run scoping bar
    $('runBeginBtn')?.addEventListener('click', () => beginRunFromUI().catch(alertError));
    $('runEndBtn')?.addEventListener('click', () => endRunFromUI().catch(alertError));
    refreshRunScope().catch(() => {});

    // History diff close
    $('historyDiffCloseBtn')?.addEventListener('click', () => {
      const view = $('historyDiffView');
      if (view) view.hidden = true;
    });

    // Updates page wiring
    $('updatePreviewBtn')?.addEventListener('click', () => previewUpdateFromUI().catch(alertError));
    $('updateApplyBtn')?.addEventListener('click', () => applyUpdateFromUI().catch(alertError));
    $('updateRollbackBtn')?.addEventListener('click', () => rollbackUpdateFromUI().catch(alertError));
    $('prefUpdateChannel')?.addEventListener('change', e => setUpdateChannel(e.target.value).catch(() => {}));
    $('restartBannerAck')?.addEventListener('click', () => ackRestart().catch(() => {}));
    refreshUpdateStatus().catch(() => {});
    refreshUpdateHistory().catch(() => {});
    refreshRestartBanner().catch(() => {});
    // Poll for restart marker every 30s
    if (state.updates.restartTimer) clearInterval(state.updates.restartTimer);
    state.updates.restartTimer = setInterval(() => { if (!document.hidden) refreshRestartBanner().catch(() => {}); }, 30000);

    // Auto-save preference (server-side preference; reads via /api/setup/defaults)
    $('prefAutoSaveAfterArchive')?.addEventListener('change', async e => {
      const data = await api('/api/setup/defaults', {
        method: 'POST',
        body: JSON.stringify({ timeline_versioning_auto_save_after_archive: !!e.target.checked }),
      }).catch(err => ({ success: false, error: String(err) }));
      if (!data || !data.success) {
        alert(`Save failed: ${data?.error || 'unknown'}`);
      }
    });

    // Media Pool History (Diagnostics)
    $('mpcRefreshBtn')?.addEventListener('click', () => refreshMpcTable().catch(alertError));
    $('mpcLimit')?.addEventListener('change', () => refreshMpcTable().catch(alertError));
    $('mpcActionFilter')?.addEventListener('change', () => applyMpcFilter());
    $('mpcGroupByClip')?.addEventListener('change', () => applyMpcFilter());
    $('mpcTable')?.addEventListener('click', (ev) => {
      const link = ev.target.closest('[data-clip-jump]');
      if (!link) return;
      ev.preventDefault();
      const clipId = link.dataset.clipJump;
      if (!clipId) return;
      try {
        setPanel('analysis', { subpage: 'review' });
        if (typeof openClipDetail === 'function') {
          openClipDetail(clipId).catch(err => console.warn('clip-jump failed', err));
        }
      } catch (err) {
        console.warn('clip-jump failed', err);
      }
    });
    refreshMpcTable().catch(() => {});
    $('reviewBackBtn').onclick = () => {
      if (state.review.view === 'shot') {
        state.review.currentShotIndex = null;
        reviewSetView('clip');
      } else if (state.review.view === 'transcript') {
        // Step back to clip detail if we have one loaded; otherwise to the bin.
        state.review.currentTranscriptData = null;
        state.review.currentTranscriptSegmentIndex = null;
        state.review.editingSegmentDraftIndex = null;
        if (state.review.currentClipId && state.review.currentClipData) {
          reviewSetView('clip');
        } else {
          state.review.currentClipId = null;
          state.review.currentClipData = null;
          reviewSetView('bin');
        }
      } else if (state.review.view === 'combined') {
        state.review.combinedClipIds = null;
        state.review.combinedData = null;
        reviewSetView('bin');
      } else if (state.review.view === 'clip') {
        state.review.currentClipId = null;
        state.review.currentClipData = null;
        reviewSetView('bin');
      } else if (state.review.view === 'history') {
        reviewSetView('bin');
      } else if (state.review.view === 'plan') {
        state.plans.currentPlanId = null;
        state.plans.payload = null;
        reviewSetView('plans');
        refreshEditPlans().catch(alertError);
      } else if (state.review.view === 'plans') {
        reviewSetView('bin');
      }
    };
    $('reviewBinGrid').addEventListener('click', event => {
      // Selection checkbox click — never opens the clip.
      const selectBtn = event.target.closest('.review-card-select');
      if (selectBtn) {
        event.preventDefault();
        event.stopPropagation();
        toggleBinSelection(selectBtn.dataset.selectClip, /* anchor */ true);
        renderReviewBin();
        return;
      }
      const card = event.target.closest('.review-clip-card');
      if (!card || !card.dataset.clipId) return;
      // Cmd/Ctrl-click toggles selection. Shift-click range-selects from anchor.
      if (event.metaKey || event.ctrlKey) {
        event.preventDefault();
        toggleBinSelection(card.dataset.clipId, true);
        renderReviewBin();
        return;
      }
      if (event.shiftKey && state.review.selectionAnchor) {
        event.preventDefault();
        extendBinSelectionToAnchor(card.dataset.clipId);
        renderReviewBin();
        return;
      }
      // Plain click opens the detail.
      openClipDetail(card.dataset.clipId).catch(alertError);
    });
    $('reviewBinGrid').addEventListener('keydown', event => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const card = event.target.closest('.review-clip-card');
      if (card && card.dataset.clipId) {
        event.preventDefault();
        // Space toggles selection; Enter opens.
        if (event.key === ' ') {
          toggleBinSelection(card.dataset.clipId, true);
          renderReviewBin();
          return;
        }
        openClipDetail(card.dataset.clipId).catch(alertError);
      }
    });
    // Right-click anywhere on the grid → context menu.
    $('reviewBinGrid').addEventListener('contextmenu', event => {
      const card = event.target.closest('.review-clip-card');
      if (!card || !card.dataset.clipId) return;
      event.preventDefault();
      // If the right-clicked card isn't in the selection, treat it as a 1-clip
      // ad-hoc context (don't change the selection state for power users).
      const clipId = card.dataset.clipId;
      let scope;
      if (state.review.selectedBinClipIds.has(clipId)) {
        scope = Array.from(state.review.selectedBinClipIds);
      } else {
        scope = [clipId];
      }
      openBinContextMenu({ scope, x: event.pageX, y: event.pageY });
    });
    // Bin summary toolbar — clear / actions buttons.
    $('reviewBinSummary')?.addEventListener('click', event => {
      if (event.target.closest('#binSelectionClearBtn')) {
        clearBinSelection();
        renderReviewBin();
      }
      if (event.target.closest('#binSelectionActionsBtn')) {
        const rect = event.target.closest('#binSelectionActionsBtn').getBoundingClientRect();
        openBinContextMenu({
          scope: Array.from(state.review.selectedBinClipIds),
          x: rect.left + window.scrollX,
          y: rect.bottom + window.scrollY + 4,
        });
      }
    });

    async function openCombinedReview(clipIds, opts = {}) {
      if (!Array.isArray(clipIds) || !clipIds.length) return;
      state.review.combinedClipIds = clipIds.slice();
      reviewSetView('combined', opts);
      const body = $('reviewCombinedBody');
      if (body) body.innerHTML = '<div class="empty">Loading combined review…</div>';
      const data = await api('/api/clips/combined', {
        method: 'POST',
        body: JSON.stringify({ clip_ids: clipIds }),
      }).catch(err => ({ success: false, error: String(err) }));
      state.review.combinedData = data;
      renderCombinedReview();
    }

    function renderCombinedReview() {
      const header = $('reviewCombinedHeader');
      const meta = $('reviewCombinedMeta');
      const body = $('reviewCombinedBody');
      const data = state.review.combinedData;
      if (!header || !body) return;
      header.innerHTML = `
        <span class="name">Combined review</span>
        <span class="meta">${data?.success ? data.clip_count + ' clips · ' + formatDuration(data.total_duration_seconds || 0) : ''}</span>
        <div class="actions">
          <button class="secondary" id="combinedBackBtn">← Back to bin</button>
          <button id="combinedSendToResolveBtn">Send to Resolve (new timeline)</button>
        </div>
      `;
      if (!data || !data.success) {
        if (meta) meta.textContent = '';
        body.innerHTML = `<div class="empty">${escapeHtml((data && data.error) || 'Combined review unavailable.')}</div>`;
        return;
      }
      if (meta) meta.textContent = `${data.clip_count} clips · ${data.shots?.length || 0} shots total · ${data.transcript_segments?.length || 0} transcript segments`;
      const sourcesHtml = (data.sources || []).map(src => {
        const thumb = src.thumbnail_frame_index && src.clip_id
          ? `<img class="review-thumb" loading="lazy" src="/api/clips/${encodeURIComponent(src.clip_id)}/frames/${src.thumbnail_frame_index}" alt="${escapeHtml(src.clip_name || '')}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'review-thumb placeholder',textContent:'no thumbnail'}))">`
          : `<div class="review-thumb placeholder">no thumbnail</div>`;
        return `<a class="review-clip-card" href="#analysis/review/clip/${encodeURIComponent(src.clip_id)}" style="text-decoration:none">
          ${thumb}
          <div class="review-clip-card-name">${escapeHtml(src.clip_name || '')}</div>
          <div class="review-clip-card-meta"><span>${formatDuration(src.duration_seconds)}</span><span>${src.shot_count != null ? src.shot_count + ' shots' : '—'}</span></div>
        </a>`;
      }).join('');
      const summariesHtml = (data.clip_summaries || []).map(s => `
        <div class="review-analysis-block">
          <div class="block-title">${escapeHtml(s.clip_name || s.clip_id || '')}</div>
          ${s.oneliner ? `<div class="block-row"><span class="label">Oneliner</span><span class="value">${escapeHtml(s.oneliner)}</span></div>` : ''}
          ${s.summary ? `<div class="block-row"><span class="label">Summary</span><span class="value">${escapeHtml(s.summary)}</span></div>` : ''}
        </div>
      `).join('');
      const classificationsHtml = (data.editorial_classifications || []).map(c => `
        <div class="review-analysis-block">
          <div class="block-title">${escapeHtml(c.clip_name || '')}</div>
          ${clipBlockRow('Primary use', c.primary_use)}
          ${clipBlockRow('Select potential', c.select_potential)}
          ${clipBlockRow('Energy arc', c.energy_arc)}
          ${clipBlockRow('Style', c.style)}
          ${(c.genre_indicators || []).length ? `<div class="block-row"><span class="label">Genre</span><span class="value">${clipBlockChips(c.genre_indicators)}</span></div>` : ''}
          ${c.reason ? clipBlockRow('Reason', c.reason) : ''}
        </div>
      `).join('');
      const shotsHtml = (data.shots || []).map(shot => {
        const tcStart = shot.time_seconds_start != null ? formatDuration(shot.time_seconds_start) : '—';
        const tcEnd = shot.time_seconds_end != null ? formatDuration(shot.time_seconds_end) : '—';
        return `<div class="combined-shot-row">
          <div class="tc"><span>${escapeHtml(tcStart)}</span><span class="tc-end">${escapeHtml(tcEnd)}</span></div>
          <div class="body">
            <div class="src"><a href="#analysis/review/clip/${encodeURIComponent(shot.source_clip_id || '')}">${escapeHtml(shot.source_clip_name || '')}</a> · shot ${shot.shot_index}</div>
            <div class="desc">${escapeHtml(shot.description || '')}</div>
          </div>
        </div>`;
      }).join('');
      const transcriptHtml = (data.transcript_segments || []).map(seg => {
        const tc = seg.start_seconds != null ? formatDuration(seg.start_seconds) : '—';
        return `<div class="review-transcript-segment" style="grid-template-columns: 92px 1fr">
          <span class="tc">${escapeHtml(tc)}</span>
          <span class="text"><span style="color:var(--text-tertiary);margin-right:6px">${escapeHtml(seg.source_clip_name || '')}</span>${escapeHtml(seg.text || '')}</span>
        </div>`;
      }).join('');
      const tagsHtml = (data.search_tags || []).map(t => `<span class="review-chip">${escapeHtml(t)}</span>`).join('');
      const qcHtml = (data.qc_warnings || []).map(w => `<li>${escapeHtml(w)}</li>`).join('');
      body.innerHTML = `
        <div class="settings-subhead">Sources</div>
        <div class="review-grid" style="margin-top:8px">${sourcesHtml}</div>
        ${summariesHtml ? `<div class="settings-subhead" style="margin-top:24px">Clip summaries</div><div class="review-analysis-blocks">${summariesHtml}</div>` : ''}
        ${classificationsHtml ? `<div class="settings-subhead" style="margin-top:24px">Editorial classifications</div><div class="review-analysis-blocks">${classificationsHtml}</div>` : ''}
        ${tagsHtml ? `<div class="settings-subhead" style="margin-top:24px">Union of tags</div><div class="review-clip-tags" style="margin-top:8px">${tagsHtml}</div>` : ''}
        ${shotsHtml ? `<div class="settings-subhead" style="margin-top:24px">All shots (in order)</div><div class="combined-shots">${shotsHtml}</div>` : ''}
        ${transcriptHtml ? `<div class="settings-subhead" style="margin-top:24px">Combined transcript</div><div class="review-transcript-body">${transcriptHtml}</div>` : ''}
        ${qcHtml ? `<div class="settings-subhead" style="margin-top:24px">QC warnings (union)</div><ul class="block-list" style="margin-top:8px">${qcHtml}</ul>` : ''}
      `;
    }

    async function sendSelectionToResolveTimeline(clipIds) {
      if (!Array.isArray(clipIds) || !clipIds.length) return;
      const timelineName = `Review Selection ${new Date().toISOString().slice(0, 16).replace('T', ' ')}`;
      const result = await api('/api/resolve/create_timeline_from_clips', {
        method: 'POST',
        body: JSON.stringify({ name: timelineName, clip_ids: clipIds }),
      }).catch(err => ({ success: false, error: String(err) }));
      if (!result.success) {
        alertError(result.error || 'Resolve timeline creation failed');
        return;
      }
      await brandedConfirm({
        kicker: 'Resolve',
        title: `Timeline "${timelineName}" created`,
        body: `${clipIds.length} clips appended in order. Switch to Resolve to scrub it.`,
        confirmLabel: 'OK',
        cancelLabel: '',
      });
    }

    async function exportSelection(clipIds, format) {
      if (!Array.isArray(clipIds) || !clipIds.length) return;
      const result = await fetch('/api/clips/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ clip_ids: clipIds, format }),
      });
      if (!result.ok) {
        const text = await result.text().catch(() => '');
        alertError(`Export failed: ${result.status} ${text || result.statusText}`);
        return;
      }
      const blob = await result.blob();
      const filename = (result.headers.get('Content-Disposition') || '').match(/filename="?([^"]+)"?/i)?.[1]
        || `selection.${format === 'csv' ? 'csv' : 'json'}`;
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 250);
    }

    async function handleBulkRating(clipIds, rating) {
      if (!Array.isArray(clipIds) || !clipIds.length) return;
      ctxStatus(`Setting rating on ${clipIds.length} clip${clipIds.length === 1 ? '' : 's'}…`);
      const tasks = clipIds.map(id => api(`/api/clips/${encodeURIComponent(id)}/corrections`, {
        method: 'POST',
        body: JSON.stringify({
          entity_type: 'clip',
          entity_uuid: id,
          field_path: 'user.rating',
          new_value: rating,
          author: 'control_panel',
          reason: 'bulk rating from review selection',
        }),
      }).catch(err => ({ success: false, error: String(err) })));
      const results = await Promise.all(tasks);
      const failed = results.filter(r => !r || !r.success).length;
      ctxStatus(failed ? `Done. ${failed} clip${failed === 1 ? '' : 's'} failed.` : `Done. ${clipIds.length} rating${clipIds.length === 1 ? '' : 's'} saved.`);
      setTimeout(() => closeBinContextMenu(), 1200);
    }

    async function handleBulkAddTag(clipIds, tag) {
      if (!Array.isArray(clipIds) || !clipIds.length || !tag) return;
      ctxStatus(`Tagging ${clipIds.length} clip${clipIds.length === 1 ? '' : 's'}…`);
      // Per-clip: fetch current tags, append (dedup), POST corrections with the
      // full new list as new_value. Done in parallel.
      const tasks = clipIds.map(async (id) => {
        try {
          const clipData = await api(`/api/clips/${encodeURIComponent(id)}`);
          const current = Array.isArray(clipData?.editing_notes?.search_tags) ? clipData.editing_notes.search_tags : [];
          if (current.map(t => String(t).toLowerCase()).includes(tag.toLowerCase())) {
            return { success: true, skipped: true };
          }
          const next = current.concat([tag]);
          return await api(`/api/clips/${encodeURIComponent(id)}/corrections`, {
            method: 'POST',
            body: JSON.stringify({
              entity_type: 'clip',
              entity_uuid: id,
              field_path: 'editing_notes.search_tags',
              new_value: next,
              author: 'control_panel',
              reason: 'bulk tag from review selection',
            }),
          });
        } catch (err) {
          return { success: false, error: String(err) };
        }
      });
      const results = await Promise.all(tasks);
      const failed = results.filter(r => !r || !r.success).length;
      const skipped = results.filter(r => r && r.skipped).length;
      const added = results.length - failed - skipped;
      const parts = [`Done. tag added to ${added} clip${added === 1 ? '' : 's'}.`];
      if (skipped) parts.push(`${skipped} already had the tag.`);
      if (failed) parts.push(`${failed} failed.`);
      ctxStatus(parts.join(' '));
      setTimeout(() => closeBinContextMenu(), 1500);
    }

    // ─── Bin grid context menu ──────────────────────────────────────────
    function closeBinContextMenu() {
      const existing = state.review.contextMenu;
      if (!existing) return;
      existing.remove();
      state.review.contextMenu = null;
      document.removeEventListener('click', _binCtxOutsideHandler, true);
      document.removeEventListener('contextmenu', _binCtxOutsideHandler, true);
      document.removeEventListener('keydown', _binCtxKeyHandler);
    }
    function _binCtxOutsideHandler(event) {
      const menu = state.review.contextMenu;
      if (!menu) return;
      if (menu.contains(event.target)) return;
      closeBinContextMenu();
    }
    function _binCtxKeyHandler(event) {
      if (event.key === 'Escape') closeBinContextMenu();
    }
    function openBinContextMenu({ scope, x, y }) {
      closeBinContextMenu();
      if (!Array.isArray(scope) || !scope.length) return;
      const isMulti = scope.length > 1;
      const menu = document.createElement('div');
      menu.className = 'context-menu';
      menu.setAttribute('role', 'menu');
      const headerLabel = isMulti ? `${scope.length} clips selected` : 'Single clip';
      const openInResolveLabel = isMulti
        ? `Open in Resolve (new timeline)`
        : `Open in Resolve (source viewer)`;
      menu.innerHTML = `
        <div class="context-menu-header">${escapeHtml(headerLabel)}</div>
        <button class="context-menu-item" data-action="open-in-resolve">${escapeHtml(openInResolveLabel)}</button>
        <button class="context-menu-item" data-action="combine" ${isMulti ? '' : 'disabled'}>${escapeHtml('Combine into review' + (isMulti ? '' : ' (need 2+)'))}</button>
        <div class="context-menu-divider"></div>
        <div class="context-menu-sub" data-sub="rating">
          <label>Set rating</label>
          <div class="star-row" id="ctxRatingRow">
            ${[1,2,3,4,5].map(n => `<button type="button" data-rating="${n}" title="${n} star${n === 1 ? '' : 's'}">★</button>`).join('')}
            <button type="button" data-rating="0" title="Clear" style="margin-left:4px">✕</button>
          </div>
        </div>
        <div class="context-menu-sub" data-sub="tag">
          <label>Add search tag</label>
          <input type="text" id="ctxTagInput" placeholder="e.g. best-of, mvp, hero">
          <button class="secondary" type="button" id="ctxTagAdd" style="margin-top:4px">Add tag to ${scope.length} clip${isMulti ? 's' : ''}</button>
        </div>
        <div class="context-menu-divider"></div>
        <button class="context-menu-item" data-action="export-json">Export as JSON</button>
        <button class="context-menu-item" data-action="export-csv">Export as CSV</button>
        <div class="context-menu-divider"></div>
        <button class="context-menu-item" data-action="clear-selection">${escapeHtml(isMulti ? 'Clear selection' : 'Cancel')}</button>
        <div class="context-menu-status" id="ctxStatus" style="display:none"></div>
      `;
      document.body.appendChild(menu);
      // Position, clamped to viewport.
      const PAD = 8;
      const w = menu.offsetWidth || 240;
      const h = menu.offsetHeight || 320;
      const maxX = window.scrollX + window.innerWidth - w - PAD;
      const maxY = window.scrollY + window.innerHeight - h - PAD;
      menu.style.left = `${Math.min(x, maxX)}px`;
      menu.style.top = `${Math.min(y, maxY)}px`;
      state.review.contextMenu = menu;
      requestAnimationFrame(() => {
        document.addEventListener('click', _binCtxOutsideHandler, true);
        document.addEventListener('contextmenu', _binCtxOutsideHandler, true);
        document.addEventListener('keydown', _binCtxKeyHandler);
      });
      // Wire menu items.
      menu.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', (event) => {
          event.stopPropagation();
          const action = btn.dataset.action;
          handleBinContextAction(action, scope).catch(alertError);
        });
      });
      menu.querySelectorAll('#ctxRatingRow button').forEach(btn => {
        btn.addEventListener('click', (event) => {
          event.stopPropagation();
          const v = Number(btn.dataset.rating);
          handleBulkRating(scope, v).catch(alertError);
        });
      });
      menu.querySelector('#ctxTagAdd')?.addEventListener('click', (event) => {
        event.stopPropagation();
        const tag = (menu.querySelector('#ctxTagInput')?.value || '').trim();
        if (!tag) return;
        handleBulkAddTag(scope, tag).catch(alertError);
      });
    }
    function ctxStatus(message) {
      const el = state.review.contextMenu?.querySelector('#ctxStatus');
      if (!el) return;
      if (message) { el.style.display = ''; el.textContent = message; }
      else { el.style.display = 'none'; el.textContent = ''; }
    }

    async function handleBinContextAction(action, scope) {
      if (action === 'clear-selection') {
        closeBinContextMenu();
        clearBinSelection();
        renderReviewBin();
        return;
      }
      if (action === 'open-in-resolve') {
        closeBinContextMenu();
        if (scope.length === 1) {
          await openClipInResolveAt(scope[0]);
        } else {
          await sendSelectionToResolveTimeline(scope);
        }
        return;
      }
      if (action === 'combine') {
        closeBinContextMenu();
        if (scope.length < 2) return;
        window.location.hash = `#analysis/review/combined/${scope.map(encodeURIComponent).join(',')}`;
        // Hash router will pick this up via applyInitialRoute/hashchange.
        await openCombinedReview(scope, { pushHash: false });
        return;
      }
      if (action === 'export-json' || action === 'export-csv') {
        const fmt = action === 'export-json' ? 'json' : 'csv';
        closeBinContextMenu();
        await exportSelection(scope, fmt);
        return;
      }
    }

    function toggleBinSelection(clipId, setAnchor) {
      if (!clipId) return;
      const sel = state.review.selectedBinClipIds;
      if (sel.has(clipId)) sel.delete(clipId);
      else sel.add(clipId);
      if (setAnchor) state.review.selectionAnchor = clipId;
    }
    function clearBinSelection() {
      state.review.selectedBinClipIds.clear();
      state.review.selectionAnchor = null;
    }
    function extendBinSelectionToAnchor(toClipId) {
      const anchor = state.review.selectionAnchor;
      if (!anchor || !toClipId) return;
      const clips = filteredClips().map(c => c.clip_id);
      const i = clips.indexOf(anchor);
      const j = clips.indexOf(toClipId);
      if (i < 0 || j < 0) return;
      const [lo, hi] = i < j ? [i, j] : [j, i];
      for (let k = lo; k <= hi; k++) state.review.selectedBinClipIds.add(clips[k]);
    }
    // Search input: debounced, hits /api/index/query and renders cards.
    $('reviewSearchInput').addEventListener('input', event => {
      const q = event.target.value.trim();
      if (state.review.searchTimer) clearTimeout(state.review.searchTimer);
      state.review.searchTimer = setTimeout(() => {
        runReviewSearch(q).catch(alertError);
      }, 250);
    });
    // Semantic toggle re-runs the current query through the embeddings index.
    $('reviewSemanticCheckbox')?.addEventListener('change', () => {
      const q = $('reviewSearchInput').value.trim();
      if (q) runReviewSearch(q).catch(alertError);
    });
    // Bin dropdown.
    $('reviewBinFilter').addEventListener('change', event => {
      state.review.binFilter = event.target.value || '';
      renderReviewBin();
    });
    // View toggle (grid / list).
    document.querySelectorAll('[data-view-mode]').forEach(btn => {
      btn.addEventListener('click', event => {
        const mode = event.currentTarget.dataset.viewMode;
        state.review.viewMode = mode;
        document.querySelectorAll('[data-view-mode]').forEach(b => b.classList.toggle('active', b.dataset.viewMode === mode));
        renderReviewBin();
      });
    });
    $('reviewClipHeader').addEventListener('click', event => {
      if (event.target.closest('#reviewClipOpenInResolveBtn')) {
        openClipInResolve().catch(alertError);
      }
      if (event.target.closest('#reviewClipTranscriptBtn')) {
        openTranscript(state.review.currentClipId).catch(alertError);
      }
    });
    $('reviewTranscriptHeader')?.addEventListener('click', event => {
      if (event.target.closest('#reviewTranscriptBackToClipBtn')) {
        const cid = state.review.currentClipId;
        if (cid) openClipDetail(cid).catch(alertError);
      }
      if (event.target.closest('#reviewTranscriptRegenerateBtn')) regenerateTranscript().catch(alertError);
    });
    $('reviewCombinedHeader')?.addEventListener('click', event => {
      if (event.target.closest('#combinedBackBtn')) {
        clearBinSelection();
        state.review.combinedClipIds = null;
        state.review.combinedData = null;
        reviewSetView('bin');
      }
      if (event.target.closest('#combinedSendToResolveBtn')) {
        const ids = state.review.combinedClipIds || [];
        sendSelectionToResolveTimeline(ids).catch(alertError);
      }
    });
    $('reviewTranscriptFilter')?.addEventListener('input', (event) => {
      state.review.transcriptFilter = event.target.value || '';
      renderTranscriptView();
    });
    // Rating + notes (delegated on the analysis panel so both clip and shot views are covered)
    document.getElementById('panel-analysis').addEventListener('click', event => {
      const hit = event.target.closest('[data-rating-value]');
      if (hit) {
        const scope = hit.dataset.ratingScope;
        const value = Number(hit.dataset.ratingValue);
        onRatingClick(scope, value).catch(alertError);
        return;
      }
      const clear = event.target.closest('[data-rating-clear]');
      if (clear) {
        const scope = clear.dataset.ratingClear;
        onRatingClick(scope, 0).catch(alertError);
        return;
      }
      const save = event.target.closest('[data-notes-save]');
      if (save) {
        const scope = save.dataset.notesSave;
        onNotesSave(scope).catch(alertError);
      }
    });
    document.getElementById('panel-analysis').addEventListener('mouseover', event => {
      const hit = event.target.closest('.review-stars .hit');
      if (!hit) return;
      const widget = hit.closest('.review-stars');
      const value = Number(hit.dataset.ratingValue);
      if (widget) setStarsPreview(widget, value);
    });
    document.getElementById('panel-analysis').addEventListener('mouseout', event => {
      const widget = event.target.closest('.review-stars');
      if (!widget) return;
      const to = event.relatedTarget;
      if (to && widget.contains(to)) return;
      clearStarsPreview(widget);
    });
    $('reviewShotStrip').addEventListener('click', event => {
      const card = event.target.closest('.review-shot-strip-card');
      if (card && card.dataset.shotIndex != null) openShotDetail(Number(card.dataset.shotIndex)).catch(alertError);
    });
    $('reviewShotStrip').addEventListener('keydown', event => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const card = event.target.closest('.review-shot-strip-card');
      if (card && card.dataset.shotIndex != null) {
        event.preventDefault();
        openShotDetail(Number(card.dataset.shotIndex)).catch(alertError);
      }
    });
    $('reviewShotHeader').addEventListener('click', event => {
      if (event.target.closest('#reviewShotOpenInResolveBtn')) {
        openShotInResolve().catch(alertError);
      }
      if (event.target.closest('#reviewShotEditToggleBtn')) {
        state.review.editingShot = !state.review.editingShot;
        renderShotDetail();
      }
    });
    $('reviewShotFields').addEventListener('click', event => {
      const btn = event.target.closest('button[data-save-field]');
      if (!btn) return;
      const fieldPath = btn.dataset.saveField;
      const input = document.querySelector(`[data-field-input="${cssEscape(fieldPath)}"]`);
      const entityUuid = input && input.dataset.entityUuid;
      saveShotField(fieldPath, entityUuid).catch(alertError);
    });
    document.addEventListener('click', event => {
      if (!event.target.closest('.control-nav-item')) closeNavDropdowns();
      if (!event.target.closest('.action-menu')) closeActionMenus();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        closeNavDropdowns();
        closeActionMenus();
      }
    });
    window.addEventListener('hashchange', () => {
      // Re-apply route from URL so back/forward and pasted deep links work.
      applyInitialRoute();
    });
    function alertError(error) { alert(error.message || String(error)); }
    hydratePreferenceHelp();
    applyInitialRoute();
    boot().catch(alertError);
  </script>
</body>
</html>
"""


def _safe_call(obj: Any, method_name: str, *args: Any) -> Tuple[Any, Optional[str]]:
    if obj is None or not hasattr(obj, method_name):
        return None, f"{method_name} unavailable"
    try:
        return getattr(obj, method_name)(*args), None
    except Exception as exc:
        return None, str(exc)


def _safe_name(obj: Any, fallback: str = "Untitled") -> str:
    value, _ = _safe_call(obj, "GetName")
    return str(value or fallback)


def _safe_id(obj: Any) -> Optional[str]:
    value, _ = _safe_call(obj, "GetUniqueId")
    return str(value) if value else None


# ── Resolve scripting API serialization ─────────────────────────────────────
# The dashboard runs on a ThreadingHTTPServer, so /api/boot, /api/projects and
# /api/resolve/media can land on separate threads concurrently (especially at
# startup). DaVinci's scripting API is not thread-safe, so every entry point that
# talks to it acquires this re-entrant lock for the full duration of its calls.
_RESOLVE_API_LOCK = threading.RLock()
_RESOLVE_ENV_READY = False


def _serialize_resolve(func):
    """Decorator: hold the Resolve API lock for the whole call."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _RESOLVE_API_LOCK:
            return func(*args, **kwargs)
    return wrapper


def _connect_resolve_read_only() -> Tuple[Any, Optional[str]]:
    global _RESOLVE_ENV_READY
    with _RESOLVE_API_LOCK:
        # Environment + sys.path setup is pure overhead and never goes stale, so
        # run it once per process rather than on every connection.
        if not _RESOLVE_ENV_READY:
            try:
                setup_environment()
                modules_path = os.environ.get("RESOLVE_SCRIPT_API")
                if modules_path:
                    candidate = os.path.join(modules_path, "Modules")
                    if candidate not in sys.path:
                        sys.path.append(candidate)
                _RESOLVE_ENV_READY = True
            except Exception as exc:
                return None, f"Resolve scripting API unavailable: {exc}"
        try:
            import DaVinciResolveScript as dvr_script  # type: ignore
        except Exception as exc:
            return None, f"Resolve scripting API unavailable: {exc}"
        try:
            resolve = dvr_script.scriptapp("Resolve")
        except Exception as exc:
            return None, f"Resolve connection failed: {exc}"
        if resolve is None:
            return None, "DaVinci Resolve is not connected. Open Resolve Studio with a project loaded."
        return resolve, None


@_serialize_resolve
def _current_resolve_project_id() -> Tuple[Optional[str], Optional[str]]:
    """(project_id, error) for the currently-open Resolve project.

    A handful of cheap API calls — used by the media-poll reuse path to detect
    when the user has switched projects in Resolve since the inventory was cached,
    without paying for a full Media Pool walk.
    """
    resolve, error = _connect_resolve_read_only()
    if error or resolve is None:
        return None, error or "Resolve unavailable"
    pm, pm_error = _safe_call(resolve, "GetProjectManager")
    if not pm or pm_error:
        return None, pm_error or "Project manager unavailable"
    project, _ = _safe_call(pm, "GetCurrentProject")
    if not project:
        return None, "No Resolve project open"
    return _safe_id(project), None


@_serialize_resolve
def _resolve_ai_features(resolve: Any) -> Dict[str, Any]:
    """Report which Resolve 21.0 AI scripting methods are available on the
    connected build, plus the Extra each AI-gated method requires. Presence is
    detected via getattr (no Resolve round-trips beyond fetching the handles),
    so this stays cheap enough for the boot handshake.
    """
    def has(obj: Any, name: str) -> bool:
        return bool(obj) and callable(getattr(obj, name, None))

    project = folder = None
    try:
        pm = resolve.GetProjectManager()
        project = pm.GetCurrentProject() if pm else None
        mp = project.GetMediaPool() if project else None
        folder = mp.GetRootFolder() if mp else None
    except Exception:
        pass

    features = {
        "disable_background_tasks": has(resolve, "DisableBackgroundTasksForCurrentResolveSession"),
        "generate_speech": has(project, "GenerateSpeech"),
        "perform_audio_classification": has(folder, "PerformAudioClassification"),
        "clear_audio_classification": has(folder, "ClearAudioClassification"),
        "analyze_for_intellisearch": has(folder, "AnalyzeForIntellisearch"),
        "analyze_for_slate": has(folder, "AnalyzeForSlate"),
        "remove_motion_blur": has(folder, "RemoveMotionBlur"),
    }
    return {
        "features": features,
        "available_count": sum(1 for v in features.values() if v),
        # Methods that additionally need an Extras download to actually run.
        "requires_extra": {
            "analyze_for_intellisearch": "AI IntelliSearch",
            "analyze_for_slate": "AI Slate ID",
            "generate_speech": "AI Speech Generator",
        },
    }


def _resolve_identity() -> Dict[str, Any]:
    resolve, error = _connect_resolve_read_only()
    if not resolve:
        return {"available": False, "error": error}
    product, _ = _safe_call(resolve, "GetProductName")
    version_string, _ = _safe_call(resolve, "GetVersionString")
    version_tuple, _ = _safe_call(resolve, "GetVersion")
    page, _ = _safe_call(resolve, "GetCurrentPage")
    return {
        "available": True,
        "product": str(product) if product else "DaVinci Resolve",
        "version_string": str(version_string) if version_string else None,
        "version": list(version_tuple) if isinstance(version_tuple, (list, tuple)) else None,
        "page": str(page) if page else None,
        "ai_features": _resolve_ai_features(resolve),
    }


# ── Resolve 21 AI Console: op dispatch ──────────────────────────────────────
# Folder/clip-level ops are routed to the consolidated `folder` /
# `media_pool_item` tools; project/resolve-level ops to their tools. The
# consolidated tools own the confirm-token gate for the two media-creators, so
# this dispatcher just relays params (incl. confirm_token) and the result.

_AI_CONSOLE_FOLDER_OPS = frozenset({
    "perform_audio_classification", "clear_audio_classification",
    "analyze_for_intellisearch", "analyze_for_slate", "remove_motion_blur",
    "transcribe_audio", "clear_transcription",
})


def _run_resolve_ai_op(body: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch one AI Console op to the right consolidated server tool.

    body = {op, target?, params?}. target is 'folder' (current Media Pool
    folder, default) or 'clip' (params.clip_id required). Returns the tool's
    response verbatim — including a {status:'confirmation_required', confirm_token,
    preview} shape for the gated media-creating ops.
    """
    op = (body.get("op") or "").strip()
    target = (body.get("target") or "folder").strip()
    params = dict(body.get("params") or {})
    if not op:
        return {"success": False, "error": "op is required"}
    try:
        from src.server import (
            folder as _folder_tool,
            media_pool_item as _mpi_tool,
            project_settings as _ps_tool,
            resolve_control as _rc_tool,
        )
    except Exception as exc:  # pragma: no cover - import guard
        return {"success": False, "error": f"server tools unavailable: {exc}"}

    if op == "disable_background_tasks":
        return _rc_tool("disable_background_tasks_for_current_session", {})
    if op == "generate_speech":
        return _ps_tool("generate_speech", params)
    if op not in _AI_CONSOLE_FOLDER_OPS:
        return {"success": False, "error": f"unknown op {op!r}"}
    if target == "clip":
        clip_id = params.get("clip_id") or body.get("clip_id")
        if not clip_id:
            return {"success": False, "error": "clip target requires a clip_id"}
        params["clip_id"] = clip_id
        return _mpi_tool(op, params)
    # default: operate on the current Media Pool folder
    return _folder_tool(op, params)


def _clip_props(clip: Any) -> Dict[str, Any]:
    props, _ = _safe_call(clip, "GetClipProperty", "")
    return props if isinstance(props, dict) else {}


def _first_prop(props: Dict[str, Any], keys: Tuple[str, ...]) -> Any:
    for key in keys:
        value = props.get(key)
        if value not in (None, ""):
            return value
    return None


# ── File-existence probing ──────────────────────────────────────────────────
# stat() calls on mounted network storage dominate inventory time (300+ source
# clips on a Z:\ share can take tens of seconds serially). We probe paths in a
# thread pool and memoize results for a short TTL so the recurring media poll
# does not re-stat unchanged paths every few seconds.
_PATH_EXISTS_TTL = 60.0
_PATH_PROBE_WORKERS = 16
_PATH_EXISTS_CACHE: Dict[str, Tuple[float, bool]] = {}
_PATH_EXISTS_LOCK = threading.Lock()


def _cached_path_exists(path: str, now: float, ttl: float) -> Optional[bool]:
    with _PATH_EXISTS_LOCK:
        entry = _PATH_EXISTS_CACHE.get(path)
    if entry is not None and (now - entry[0]) <= ttl:
        return entry[1]
    return None


def _store_path_exists(path: str, exists: bool, now: float) -> None:
    with _PATH_EXISTS_LOCK:
        _PATH_EXISTS_CACHE[path] = (now, exists)


def _probe_paths_exist(paths: Any, *, probe: bool = True, ttl: float = _PATH_EXISTS_TTL) -> Dict[str, bool]:
    """Resolve a collection of file paths to existence booleans.

    With ``probe=True`` (first load / manual refresh) any cache entry older than
    ``ttl`` is re-stat'd, and uncached paths are probed in parallel. With
    ``probe=False`` (background poll) the filesystem is never touched: cached
    values are reused at any age and unknown paths fall back to ``True`` —
    Resolve's own online/offline Status property still flags clips it knows are
    missing, so we trust it rather than paying for a network round-trip on every
    poll.
    """
    distinct = {str(p) for p in paths if p}
    result: Dict[str, bool] = {}
    to_probe: List[str] = []
    now = time.time()
    lookup_ttl = ttl if probe else float("inf")
    for path in distinct:
        cached = _cached_path_exists(path, now, lookup_ttl)
        if cached is not None:
            result[path] = cached
        elif probe:
            to_probe.append(path)
        else:
            result[path] = True
    if to_probe:
        workers = max(1, min(_PATH_PROBE_WORKERS, len(to_probe)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for path, exists in zip(to_probe, pool.map(os.path.exists, to_probe)):
                result[path] = bool(exists)
                _store_path_exists(path, bool(exists), now)
    return result


def _media_status(props: Dict[str, Any], file_path: Optional[str], *, file_exists: Optional[bool] = None) -> str:
    status_text = str(_first_prop(props, ("Status", "Media Status", "Online Status", "Offline")) or "").strip().lower()
    if not file_path:
        return "no_path"
    if "offline" in status_text or status_text in {"true", "yes", "1"}:
        return "offline"
    if "missing" in status_text:
        return "missing_file"
    # Pass `file_exists` in to reuse a single os.path.exists() probe — stat calls on
    # network source media are slow, so the caller avoids probing the same path twice.
    if file_exists is None:
        file_exists = os.path.exists(str(file_path))
    if not file_exists:
        return "missing_file"
    return "online"


_RESOLVE_CONTAINER_TYPE_PARTS = (
    "adjustment",
    "compound",
    "fusion",
    "generator",
    "multicam",
    "multi cam",
    "sequence",
    "subclip",
    "sub clip",
    "timeline",
    "title",
)


def _truthy_resolve_value(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _source_clip_status(record: Dict[str, Any], props: Dict[str, Any]) -> Tuple[bool, str]:
    media_type = str(record.get("media_type") or "").strip()
    media_type_lower = media_type.lower()
    for marker in _RESOLVE_CONTAINER_TYPE_PARTS:
        if marker in media_type_lower:
            return False, f"Resolve {media_type or 'container'} item"

    subclip_flag = _first_prop(props, ("Sub Clip", "SubClip", "Is Sub Clip", "IsSubClip", "Is Subclip"))
    if _truthy_resolve_value(subclip_flag):
        return False, "Resolve subclip"

    file_path = record.get("file_path")
    if not file_path:
        return False, "No source file path exposed"

    extension = os.path.splitext(str(file_path))[1].lower()
    if extension not in MEDIA_EXTENSIONS:
        return False, f"Unsupported extension: {extension or 'none'}"

    return True, "Source media clip"


def _record_is_sequence(record: Dict[str, Any]) -> bool:
    media_type_lower = str(record.get("media_type") or "").strip().lower()
    return "sequence" in media_type_lower or "timeline" in media_type_lower


def _analyzable_clip_status(record: Dict[str, Any], props: Dict[str, Any]) -> Tuple[bool, str]:
    source_clip, reason = _source_clip_status(record, props)
    if not source_clip:
        return False, reason

    if record.get("status") != "online":
        return False, str(record.get("status") or "offline").replace("_", " ")

    return True, "Online source media"


def _resolve_clip_record(clip: Any, bin_path: str, selected_ids: set) -> Dict[str, Any]:
    props = _clip_props(clip)
    file_path = _first_prop(props, ("File Path", "FilePath"))
    media_id, _ = _safe_call(clip, "GetMediaId")
    clip_id = _safe_id(clip)
    record = {
        "clip_id": clip_id,
        "clip_name": _safe_name(clip),
        "bin_path": bin_path,
        "file_path": str(file_path) if file_path else None,
        "media_id": str(media_id) if media_id else None,
        "duration": _first_prop(props, ("Duration",)),
        "fps": _first_prop(props, ("FPS", "Frame Rate")),
        "resolution": _first_prop(props, ("Resolution",)),
        "media_type": _first_prop(props, ("Type", "Media Type")),
        "proxy": _first_prop(props, ("Proxy", "Proxy Media Path")),
        "resolve_status": _first_prop(props, ("Status", "Media Status", "Online Status", "Offline")),
        "selected": bool(clip_id and clip_id in selected_ids),
    }
    # File-existence is resolved in a single parallel batch after every clip's
    # Resolve properties are gathered (see resolve_media_inventory), so we stash
    # the props and defer existence-dependent fields to _finalize_clip_record.
    record["clip_key"] = stable_clip_directory(record)
    record["_props"] = props
    return record


def _finalize_clip_record(record: Dict[str, Any], file_exists: bool) -> Dict[str, Any]:
    props = record.pop("_props", {}) or {}
    record["file_exists"] = file_exists
    record["status"] = _media_status(props, record["file_path"], file_exists=file_exists)
    record["source_clip"], record["source_clip_reason"] = _source_clip_status(record, props)
    record["analyzable"], record["analyzable_reason"] = _analyzable_clip_status(record, props)
    return record


def _append_folder_media(
    folder: Any,
    *,
    bin_path: str,
    recursive: bool,
    selected_ids: set,
    records: List[Dict[str, Any]],
    warnings: List[str],
    limit: int,
    exclude_bins: Optional[set] = None,
) -> bool:
    clips, clip_err = _safe_call(folder, "GetClipList")
    if clip_err:
        warnings.append(f"GetClipList failed for {bin_path}: {clip_err}")
        clips = []
    for clip in clips or []:
        if len(records) >= limit:
            return True
        records.append(_resolve_clip_record(clip, bin_path, selected_ids))

    if not recursive:
        return False
    subfolders, folder_err = _safe_call(folder, "GetSubFolderList")
    if folder_err:
        warnings.append(f"GetSubFolderList failed for {bin_path}: {folder_err}")
        return False
    for subfolder in subfolders or []:
        if len(records) >= limit:
            return True
        child_name = _safe_name(subfolder, "Unnamed")
        if exclude_bins and child_name in exclude_bins:
            continue
        truncated = _append_folder_media(
            subfolder,
            bin_path=f"{bin_path}/{child_name}",
            recursive=recursive,
            selected_ids=selected_ids,
            records=records,
            warnings=warnings,
            limit=limit,
            exclude_bins=exclude_bins,
        )
        if truncated:
            return True
    return False


def _empty_media_counts() -> Dict[str, int]:
    return {
        "total": 0,
        "source_clips": 0,
        "sequences": 0,
        "analyzable": 0,
        "not_analyzable": 0,
        "online": 0,
        "offline": 0,
        "missing_file": 0,
        "no_path": 0,
        "analyzed": 0,
        "selected": 0,
    }


def _analysis_status_by_clip(project_root: str, records: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    keys = [record.get("clip_key") for record in records if record.get("clip_key")]
    status_by_key: Dict[str, Dict[str, Any]] = {}
    if not keys:
        return status_by_key

    # Resolve each clip to its report via the persisted clip index, which maps
    # every stable id found in a report (normalized + raw file path, clip_id,
    # media_id) to its folder. This survives a Media Pool rename, a legacy hash
    # basis, AND an offline clip that no longer reports a file path but still
    # carries its clip_id — none of which a folder-name scan can match. See #51.
    clips_root = os.path.join(project_root, "clips")
    hash_to_folder = load_clip_index(project_root).get("hash_to_folder") or {}

    for record in records:
        clip_key = record.get("clip_key")
        if not clip_key:
            continue
        report_path = os.path.join(project_root, "clips", str(clip_key), "analysis.json")
        if not os.path.isfile(report_path):
            # Renamed/legacy/offline clip: the recomputed clip_key no longer
            # matches the folder on disk. Fall back to any of the clip's stable
            # hashes via the index.
            for clip_hash in stable_clip_match_hashes(record):
                folder = hash_to_folder.get(clip_hash)
                if not folder:
                    continue
                candidate = os.path.join(clips_root, folder, "analysis.json")
                if os.path.isfile(candidate):
                    report_path = candidate
                    break
        if os.path.isfile(report_path):
            status_by_key[str(clip_key)] = {
                "analysis_status": "analyzed",
                "analysis_report_path": report_path,
            }

    db_path = os.path.join(project_root, "jobs.sqlite")
    if not os.path.isfile(db_path):
        return status_by_key

    # The jobs DB stores each clip under the clip_key it had when analyzed. A
    # clip renamed afterwards produces a new clip_key, so an exact-key match
    # misses its job row. Index unresolved records by their rename-stable hash
    # so a DB row recorded under the old name (e.g. a reused batch report living
    # outside the local clips/ dir) still maps back to the current clip. #51.
    key_set = {str(k) for k in keys}
    pending_hash_to_key: Dict[str, str] = {}
    for record in records:
        clip_key = record.get("clip_key")
        if not clip_key or str(clip_key) in status_by_key:
            continue
        for folder_hash in stable_clip_match_hashes(record):
            pending_hash_to_key.setdefault(folder_hash, str(clip_key))

    def _apply_row(row: sqlite3.Row, target_key: str) -> None:
        if status_by_key.get(target_key, {}).get("analysis_status") == "analyzed":
            return
        db_status = row["status"]
        report_path = row["report_path"]
        # In media_analysis_jobs, 'succeeded' = fresh analysis written this run,
        # 'skipped' = an existing analysis report was reused. Both indicate the
        # clip has been analyzed (a report exists on disk). Normalize them to
        # "analyzed" for callers that just want to know "is there a report?",
        # but preserve the raw job state under job_status for diagnostics.
        report_resolves = False
        if isinstance(report_path, str) and report_path:
            try:
                resolved = os.path.realpath(os.path.abspath(os.path.expanduser(report_path)))
                report_resolves = os.path.isfile(resolved)
            except Exception:
                report_resolves = False
        normalized = db_status
        if db_status in ("succeeded", "skipped") and report_resolves:
            normalized = "analyzed"
        status_by_key[target_key] = {
            "analysis_status": normalized,
            "job_status": db_status,
            "cache_status": row["cache_status"],
            "analysis_report_path": report_path,
            "analysis_error": row["error"],
            "job_id": row["job_id"],
            "job_name": row["job_name"],
            "job_updated_at": row["updated_at"],
        }

    select_cols = (
        "SELECT jc.clip_key, jc.status, jc.cache_status, jc.report_path, jc.error, "
        "j.job_id, j.name AS job_name, j.updated_at "
        "FROM job_clips jc JOIN jobs j ON j.job_id = jc.job_id"
    )
    placeholders = ",".join("?" for _ in keys)
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"{select_cols} WHERE jc.clip_key IN ({placeholders}) ORDER BY jc.updated_at DESC",
            keys,
        ).fetchall()
        for row in rows:
            _apply_row(row, str(row["clip_key"]))
        # Only pay for the unfiltered scan when a rename actually left a record
        # unresolved by the disk pass and exact-key match above.
        unresolved = {
            h: k for h, k in pending_hash_to_key.items() if k not in status_by_key
        }
        if unresolved:
            for row in conn.execute(
                f"{select_cols} ORDER BY jc.updated_at DESC"
            ).fetchall():
                raw_key = str(row["clip_key"])
                if raw_key in key_set:
                    continue
                row_hash = clip_directory_hash(raw_key)
                target_key = unresolved.get(row_hash) if row_hash else None
                if target_key:
                    _apply_row(row, target_key)
    except Exception:
        return status_by_key
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return status_by_key


# Last full Resolve walk per project_root, kept overlay-free so the analysis
# status can be re-applied cheaply on every background poll without re-walking
# the Media Pool (the expensive, non-parallelizable GetClipProperty pass).
_INVENTORY_CACHE: Dict[str, Dict[str, Any]] = {}
_INVENTORY_LOCK = threading.Lock()


def _get_cached_inventory(project_root: str) -> Optional[Dict[str, Any]]:
    with _INVENTORY_LOCK:
        return _INVENTORY_CACHE.get(project_root)


def _store_cached_inventory(project_root: str, entry: Dict[str, Any]) -> None:
    with _INVENTORY_LOCK:
        _INVENTORY_CACHE[project_root] = entry


def _assemble_inventory_payload(project_root: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the (local, cheap) analysis-status overlay onto cached base records.

    Base records hold the Resolve-derived fields plus file existence; the analysis
    overlay (queued/running/analyzed, report paths, job ids) is re-read from disk
    every call so a background poll reflects job progress without touching Resolve.
    Records are copied so the cached base stays overlay-free across polls.
    """
    records = [dict(record) for record in entry["base_records"]]
    status_by_key = _analysis_status_by_clip(project_root, records)
    counts = _empty_media_counts()
    counts["total"] = len(records)
    counts["selected"] = entry.get("selected_count", sum(1 for r in records if r.get("selected")))
    for record in records:
        status = record.get("status") or "unknown"
        if status in counts:
            counts[status] += 1
        if _record_is_sequence(record):
            counts["sequences"] += 1
        if record.get("source_clip"):
            counts["source_clips"] += 1
        if record.get("analyzable"):
            counts["analyzable"] += 1
        else:
            counts["not_analyzable"] += 1
        analysis = status_by_key.get(str(record.get("clip_key") or ""), {})
        record.update(analysis)
        record.setdefault("analysis_status", "not analyzed")
        if record["analysis_status"] in {"analyzed", "succeeded", "skipped"}:
            counts["analyzed"] += 1

    return {
        "success": True,
        "resolve_available": True,
        "status": "Resolve connected",
        "project": entry["project"],
        "project_root": project_root,
        "clips": records,
        "counts": counts,
        "truncated": bool(entry.get("truncated")),
        "limit": entry.get("limit"),
        "warnings": entry.get("warnings", []),
    }


def resolve_media_inventory(
    project_root: str,
    *,
    limit: Any = 500,
    exclude_bins: Optional[set] = None,
    recursive: bool = True,
    probe_paths: bool = True,
    reuse_cached: bool = False,
) -> Dict[str, Any]:
    try:
        max_items = max(1, min(int(limit), 10000))
    except (TypeError, ValueError):
        max_items = 500

    # Background polls only need to surface analysis progress (a local, disk-backed
    # signal), so they reuse the last Resolve walk instead of paying for ~N serial
    # GetClipProperty round-trips again. A cheap project-id check still catches a
    # project switch made directly in Resolve (a handful of API calls vs a full
    # walk); we rebuild only on a confirmed mismatch. If the current project can't
    # be determined (Resolve down / no project open), we keep serving the cache —
    # a transient blip shouldn't trigger an expensive rebuild on every poll.
    if reuse_cached:
        cached = _get_cached_inventory(project_root)
        if cached is not None:
            current_id, id_error = _current_resolve_project_id()
            cached_id = (cached.get("project") or {}).get("id")
            project_changed = (
                id_error is None
                and current_id is not None
                and str(current_id) != str(cached_id)
            )
            if not project_changed:
                return _assemble_inventory_payload(project_root, cached)

    # Everything that touches the Resolve scripting API stays under the lock; the
    # parallel path probe and the disk overlay run outside it.
    with _RESOLVE_API_LOCK:
        resolve, resolve_error = _connect_resolve_read_only()
        if resolve_error:
            return {
                "success": True,
                "resolve_available": False,
                "status": "Resolve unavailable",
                "error": resolve_error,
                "clips": [],
                "counts": _empty_media_counts(),
            }
        pm, pm_error = _safe_call(resolve, "GetProjectManager")
        project = None
        if pm and not pm_error:
            project, _ = _safe_call(pm, "GetCurrentProject")
        if not project:
            return {
                "success": True,
                "resolve_available": False,
                "status": "No Resolve project",
                "error": "DaVinci Resolve is connected, but no project is open.",
                "clips": [],
                "counts": _empty_media_counts(),
            }
        media_pool, mp_error = _safe_call(project, "GetMediaPool")
        if not media_pool or mp_error:
            return {
                "success": True,
                "resolve_available": False,
                "status": "Media Pool unavailable",
                "error": mp_error or "Failed to get Resolve Media Pool",
                "clips": [],
                "counts": _empty_media_counts(),
            }
        root_folder, root_error = _safe_call(media_pool, "GetRootFolder")
        if not root_folder or root_error:
            return {
                "success": True,
                "resolve_available": False,
                "status": "Root folder unavailable",
                "error": root_error or "Failed to get Resolve root folder",
                "clips": [],
                "counts": _empty_media_counts(),
            }

        selected_ids = set()
        selected_clips, _ = _safe_call(media_pool, "GetSelectedClips")
        for clip in selected_clips or []:
            clip_id = _safe_id(clip)
            if clip_id:
                selected_ids.add(clip_id)

        warnings: List[str] = []
        records: List[Dict[str, Any]] = []
        truncated = _append_folder_media(
            root_folder,
            bin_path="Master",
            recursive=recursive,
            selected_ids=selected_ids,
            records=records,
            warnings=warnings,
            limit=max_items,
            exclude_bins=exclude_bins,
        )
        project_info = {
            "name": _safe_name(project, "Resolve Project"),
            "id": _safe_id(project),
        }
        selected_count = len(selected_ids)

    # Resolve every clip's file path in one parallel, cache-backed batch, then
    # finalize existence-dependent fields (status / analyzable).
    existence = _probe_paths_exist(
        (record.get("file_path") for record in records),
        probe=probe_paths,
    )
    for record in records:
        file_path = record.get("file_path")
        _finalize_clip_record(record, bool(file_path) and existence.get(str(file_path), False))

    entry = {
        "base_records": records,
        "project": project_info,
        "selected_count": selected_count,
        "truncated": bool(truncated),
        "limit": max_items,
        "warnings": warnings,
    }
    _store_cached_inventory(project_root, entry)
    return _assemble_inventory_payload(project_root, entry)


_PROJECT_CONTEXT_RE = re.compile(r"^(?P<slug>.+)-(?P<hash>[0-9a-f]{10})$")


def _project_context_family_slug(project_directory: Any) -> str:
    name = os.path.basename(str(project_directory or "")).strip()
    match = _PROJECT_CONTEXT_RE.match(name)
    return match.group("slug") if match else name


def _project_context_label(project_directory: Any) -> str:
    family = _project_context_family_slug(project_directory)
    return family.replace("-", " ").strip().title() or "Project"


def _context_payload(project_name: Any, project_id: Any, output_root: Dict[str, Any], *, source: str = "dashboard") -> Dict[str, Any]:
    project_directory = output_root.get("project_directory") or os.path.basename(str(output_root.get("project_root") or ""))
    return {
        "project_name": str(project_name or _project_context_label(project_directory)),
        "project_id": str(project_id) if project_id not in (None, "") else None,
        "project_root": output_root.get("project_root"),
        "base_root": output_root.get("base_root"),
        "project_directory": project_directory,
        "family_slug": _project_context_family_slug(project_directory),
        "source": source,
    }


def _context_from_project_root(base_root: str, project_root: str, *, source: str = "analysis_root") -> Optional[Dict[str, Any]]:
    root = os.path.realpath(os.path.abspath(os.path.expanduser(str(project_root))))
    base = os.path.realpath(os.path.abspath(os.path.expanduser(str(base_root))))
    try:
        if os.path.commonpath([root, base]) != base:
            return None
    except ValueError:
        return None
    if not os.path.isdir(root):
        return None
    project_directory = os.path.basename(root)
    return {
        "project_name": _project_context_label(project_directory),
        "project_id": None,
        "project_root": root,
        "base_root": base,
        "project_directory": project_directory,
        "family_slug": _project_context_family_slug(project_directory),
        "source": source,
    }


@_serialize_resolve
def _current_resolve_project_context(base_root: str) -> Optional[Dict[str, Any]]:
    resolve, resolve_error = _connect_resolve_read_only()
    if resolve_error:
        return None
    pm, pm_error = _safe_call(resolve, "GetProjectManager")
    if not pm or pm_error:
        return None
    project, _ = _safe_call(pm, "GetCurrentProject")
    if not project:
        return None
    project_name = _safe_name(project, "Resolve Project")
    project_id = _safe_id(project)
    root = project_root_for_dashboard(
        project_name=project_name,
        project_id=project_id,
        analysis_root=base_root,
    )
    if not root.get("success"):
        return None
    return _context_payload(project_name, project_id, root, source="resolve")


def _project_folder_name(folder: Any) -> str:
    if isinstance(folder, str):
        return folder
    name, _ = _safe_call(folder, "GetName")
    return str(name or folder or "").strip()


def _normalize_project_folder_path(folder_path: Any) -> List[str]:
    if folder_path is None:
        return []
    if isinstance(folder_path, (list, tuple)):
        raw_parts = [str(part or "").strip() for part in folder_path]
    else:
        raw_parts = re.split(r"[\\/]+", str(folder_path or ""))
    parts = [part for part in raw_parts if part and part not in {".", "/"}]
    if parts and parts[0].lower() in {"root", "master"}:
        parts = parts[1:]
    return parts


def _goto_project_folder(pm: Any, folder_path: Any) -> Tuple[bool, Optional[str]]:
    parts = _normalize_project_folder_path(folder_path)
    _, root_error = _safe_call(pm, "GotoRootFolder")
    if root_error:
        return False, root_error
    for part in parts:
        opened, open_error = _safe_call(pm, "OpenFolder", part)
        if open_error:
            return False, open_error
        if not opened:
            return False, f"Resolve project folder not found: {part}"
    return True, None


def _project_folder_label(folder_path: List[str]) -> str:
    return " / ".join(folder_path) if folder_path else "Root"


@_serialize_resolve
def _resolve_all_project_contexts(base_root: str, *, max_depth: int = 12, max_projects: int = 2000) -> Dict[str, Any]:
    resolve, resolve_error = _connect_resolve_read_only()
    if resolve_error:
        return {
            "success": True,
            "available": False,
            "error": resolve_error,
            "projects": [],
            "database": None,
            "current_folder": None,
        }
    pm, pm_error = _safe_call(resolve, "GetProjectManager")
    if not pm or pm_error:
        return {
            "success": True,
            "available": False,
            "error": pm_error or "ProjectManager unavailable",
            "projects": [],
            "database": None,
            "current_folder": None,
        }

    current_project, _ = _safe_call(pm, "GetCurrentProject")
    current_name = _safe_name(current_project, "") if current_project else None
    current_id = _safe_id(current_project) if current_project else None
    current_folder, _ = _safe_call(pm, "GetCurrentFolder")
    database, _ = _safe_call(pm, "GetCurrentDatabase")
    projects: List[Dict[str, Any]] = []
    errors: List[str] = []
    active_folder_path: Optional[List[str]] = None
    seen_locations = set()

    ok, root_error = _goto_project_folder(pm, [])
    if not ok:
        return {
            "success": True,
            "available": False,
            "error": root_error or "Failed to open Resolve project root folder",
            "projects": [],
            "database": database if isinstance(database, dict) else None,
            "current_folder": current_folder,
        }

    def visit(folder_path: List[str], depth: int = 0) -> None:
        nonlocal active_folder_path
        if depth > max_depth or len(projects) >= max_projects:
            return
        names, names_error = _safe_call(pm, "GetProjectListInCurrentFolder")
        if names_error:
            errors.append(f"{_project_folder_label(folder_path)}: {names_error}")
            names = []
        for raw_name in names or []:
            if len(projects) >= max_projects:
                break
            project_name = str(raw_name or "").strip()
            if not project_name:
                continue
            location_key = (tuple(folder_path), project_name)
            if location_key in seen_locations:
                continue
            seen_locations.add(location_key)
            project_id = current_id if current_name and project_name == current_name else None
            root = resolve_output_root(
                project_name=project_name,
                project_id=project_id,
                analysis_root=base_root,
                create=False,
            )
            project_directory = root.get("project_directory") if root.get("success") else ""
            is_active = bool(current_name and project_name == current_name)
            if is_active:
                active_folder_path = list(folder_path)
            projects.append({
                "project_name": project_name,
                "project_id": project_id,
                "project_directory": project_directory,
                "folder_path": list(folder_path),
                "folder_label": _project_folder_label(folder_path),
                "database_label": (database or {}).get("DbName") if isinstance(database, dict) else None,
                "active": is_active,
                "can_load_resolve": True,
            })

        folders, folders_error = _safe_call(pm, "GetFolderListInCurrentFolder")
        if folders_error:
            errors.append(f"{_project_folder_label(folder_path)} folders: {folders_error}")
            return
        for folder in folders or []:
            if len(projects) >= max_projects:
                break
            folder_name = _project_folder_name(folder)
            if not folder_name:
                continue
            opened, open_error = _safe_call(pm, "OpenFolder", folder_name)
            if open_error or not opened:
                errors.append(open_error or f"Failed to open folder {folder_name}")
                continue
            visit([*folder_path, folder_name], depth + 1)
            _, parent_error = _safe_call(pm, "GotoParentFolder")
            if parent_error:
                errors.append(f"Failed to return from {folder_name}: {parent_error}")
                _goto_project_folder(pm, folder_path)

    visit([])
    restore_path = active_folder_path if active_folder_path is not None else []
    _goto_project_folder(pm, restore_path)
    projects.sort(key=lambda row: (str(row.get("folder_label") or "").lower(), str(row.get("project_name") or "").lower()))
    return {
        "success": True,
        "available": True,
        "projects": projects,
        "count": len(projects),
        "database": database if isinstance(database, dict) else None,
        "current_folder": current_folder,
        "active_project": current_name,
        "active_folder_path": active_folder_path,
        "truncated": len(projects) >= max_projects,
        "errors": errors,
        "warning": "Project list truncated" if len(projects) >= max_projects else None,
    }


@_serialize_resolve
def _resolve_project_contexts(base_root: str) -> Dict[str, Any]:
    resolve, resolve_error = _connect_resolve_read_only()
    if resolve_error:
        return {
            "available": False,
            "error": resolve_error,
            "contexts": [],
            "current": None,
            "database": None,
            "folder": None,
        }
    pm, pm_error = _safe_call(resolve, "GetProjectManager")
    if not pm or pm_error:
        return {
            "available": False,
            "error": pm_error or "ProjectManager unavailable",
            "contexts": [],
            "current": None,
            "database": None,
            "folder": None,
        }
    current_project, _ = _safe_call(pm, "GetCurrentProject")
    current_name = _safe_name(current_project, "") if current_project else None
    current_id = _safe_id(current_project) if current_project else None
    names, names_error = _safe_call(pm, "GetProjectListInCurrentFolder")
    if names_error:
        names = []
    database, _ = _safe_call(pm, "GetCurrentDatabase")
    folder, _ = _safe_call(pm, "GetCurrentFolder")
    contexts: List[Dict[str, Any]] = []
    seen_names = set()
    for raw_name in names or []:
        project_name = str(raw_name or "").strip()
        if not project_name or project_name in seen_names:
            continue
        seen_names.add(project_name)
        project_id = current_id if current_name and project_name == current_name else None
        root = resolve_output_root(
            project_name=project_name,
            project_id=project_id,
            analysis_root=base_root,
            create=False,
        )
        if not root.get("success"):
            continue
        context = _context_payload(project_name, project_id, root, source="resolve")
        context["resolve_project_name"] = project_name
        context["can_load_resolve"] = True
        context["resolve_current"] = bool(current_name and project_name == current_name)
        contexts.append(context)
    if current_project and current_name and current_name not in seen_names:
        root = resolve_output_root(
            project_name=current_name,
            project_id=current_id,
            analysis_root=base_root,
            create=False,
        )
        if root.get("success"):
            context = _context_payload(current_name, current_id, root, source="resolve")
            context["resolve_project_name"] = current_name
            context["can_load_resolve"] = True
            context["resolve_current"] = True
            contexts.insert(0, context)
    return {
        "available": True,
        "error": names_error,
        "contexts": contexts,
        "current": next((context for context in contexts if context.get("resolve_current")), None),
        "database": database if isinstance(database, dict) else None,
        "folder": folder,
    }


@_serialize_resolve
def _load_resolve_project_context(base_root: str, project_name: Any, folder_path: Any = None) -> Dict[str, Any]:
    target_name = str(project_name or "").strip()
    if not target_name:
        return {"success": False, "error": "Resolve project name is required"}
    resolve, resolve_error = _connect_resolve_read_only()
    if resolve_error:
        return {"success": False, "error": resolve_error}
    pm, pm_error = _safe_call(resolve, "GetProjectManager")
    if not pm or pm_error:
        return {"success": False, "error": pm_error or "ProjectManager unavailable"}
    current_project, _ = _safe_call(pm, "GetCurrentProject")
    current_name = _safe_name(current_project, "") if current_project else None
    loaded_project = current_project
    target_folder = _normalize_project_folder_path(folder_path)
    if target_folder:
        ok, folder_error = _goto_project_folder(pm, target_folder)
        if not ok:
            return {"success": False, "error": folder_error or "Failed to open Resolve project folder"}
    if current_name != target_name or target_folder:
        loaded_project, load_error = _safe_call(pm, "LoadProject", target_name)
        if load_error:
            return {"success": False, "error": f"LoadProject failed: {load_error}"}
        if not loaded_project:
            folder_label = _project_folder_label(target_folder) if target_folder else "current project folder"
            return {"success": False, "error": f"Resolve project not found in {folder_label}: {target_name}"}
    project, _ = _safe_call(pm, "GetCurrentProject")
    project = project or loaded_project
    loaded_name = _safe_name(project, target_name)
    project_id = _safe_id(project)
    root = project_root_for_dashboard(
        project_name=loaded_name,
        project_id=project_id,
        analysis_root=base_root,
    )
    if not root.get("success"):
        return root
    context = _context_payload(loaded_name, project_id, root, source="resolve")
    context["resolve_project_name"] = loaded_name
    context["can_load_resolve"] = True
    context["resolve_current"] = True
    return {"success": True, "active": context, "output_root": root}


def discover_project_contexts(base_root: str, active: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = os.path.realpath(os.path.abspath(os.path.expanduser(str(base_root))))
    contexts: List[Dict[str, Any]] = []
    resolve_projects = _resolve_project_contexts(base)
    current = resolve_projects.get("current")
    contexts.extend(resolve_projects.get("contexts") or [])
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            context = _context_from_project_root(base, path)
            if context:
                context["can_load_resolve"] = False
                contexts.append(context)
    if active:
        contexts.append(dict(active, source=active.get("source") or "active"))

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for context in contexts:
        root = context.get("project_root")
        if not root or root in seen:
            continue
        seen.add(root)
        context["active"] = bool(active and root == active.get("project_root"))
        deduped.append(context)

    active_family = (active or {}).get("family_slug")
    related_roots = [
        context["project_root"]
        for context in deduped
        if active_family and context.get("family_slug") == active_family
        and (context["project_root"] == (active or {}).get("project_root") or os.path.isdir(context["project_root"]))
    ]
    return {
        "success": True,
        "base_root": base,
        "active": active,
        "current_resolve_project": current,
        "resolve_projects": resolve_projects,
        "contexts": deduped,
        "related_project_roots": related_roots,
    }


# ─── V2 Review API: clip / shot read endpoints + frame serving ──────────────
#
# These helpers power the bin grid, clip detail, and shot detail views.
# All read directly from disk artifacts (analysis.json + corrections.json
# sidecar + sampled_NNNN.jpg). When C1 (DB-as-truth) lands, swap these to
# query the V2 DB — the HTTP API contract does not change.


def _v2_iter_clip_dirs(project_root: str) -> List[Tuple[str, str]]:
    """Return (clip_slug, clip_dir_path) for each analysis.json under {project_root}/clips/."""
    clips_root = os.path.join(project_root, "clips")
    if not os.path.isdir(clips_root):
        return []
    rows: List[Tuple[str, str]] = []
    for entry in sorted(os.listdir(clips_root)):
        candidate = os.path.join(clips_root, entry)
        if not os.path.isdir(candidate):
            continue
        if not os.path.isfile(os.path.join(candidate, "analysis.json")):
            continue
        rows.append((entry, candidate))
    return rows


def _v2_iter_job_report_dirs(project_root: str) -> List[Tuple[str, str]]:
    """Return reusable analysis report dirs referenced by this project's jobs DB."""
    db_path = os.path.join(project_root, "jobs.sqlite")
    if not os.path.isfile(db_path):
        return []
    base_root = os.path.dirname(os.path.realpath(project_root))
    rows: List[Tuple[str, str]] = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        job_rows = conn.execute(
            """
            SELECT clip_key, report_path, status
            FROM job_clips
            WHERE report_path IS NOT NULL
              AND status IN ('succeeded', 'skipped', 'analyzed')
            ORDER BY updated_at DESC
            """
        ).fetchall()
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass
    for row in job_rows:
        report_path = str(row["report_path"] or "")
        if not report_path:
            continue
        real_report = os.path.realpath(os.path.abspath(os.path.expanduser(report_path)))
        if os.path.basename(real_report) != "analysis.json" or not os.path.isfile(real_report):
            continue
        try:
            if os.path.commonpath([real_report, base_root]) != base_root:
                continue
        except ValueError:
            continue
        clip_dir = os.path.dirname(real_report)
        slug = str(row["clip_key"] or os.path.basename(clip_dir))
        rows.append((slug, clip_dir))
    return rows


def _v2_iter_analysis_dirs(project_root: str) -> List[Tuple[str, str]]:
    """Return local reports plus reusable report dirs linked from batch jobs."""
    rows: List[Tuple[str, str]] = []
    seen: set = set()
    for slug, clip_dir in _v2_iter_clip_dirs(project_root) + _v2_iter_job_report_dirs(project_root):
        real_dir = os.path.realpath(clip_dir)
        if real_dir in seen:
            continue
        seen.add(real_dir)
        rows.append((slug, clip_dir))
    return rows


def _v2_load_analysis(clip_dir: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(clip_dir, "analysis.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def _v2_load_analysis_db_first(project_root: str, clip_dir: str) -> Optional[Dict[str, Any]]:
    """C1 — DB-canonical reader with JSON fallback.

    Falls back to analysis.json for reports that predate schema v9 and for
    job-linked report dirs whose rows live under another project's DB.
    """
    try:
        from src.utils import analysis_store

        report = analysis_store.load_db_report(
            project_root, clip_dir=os.path.basename(clip_dir.rstrip("/\\"))
        )
        if report is not None:
            return report
    except Exception:
        pass
    return _v2_load_analysis(clip_dir)


def _v2_semantic_search(project_root: str, q: str, *, limit: int = 20) -> Dict[str, Any]:
    """Semantic search over the embeddings index, shaped like /api/index/query
    rows so the existing search-card renderer works unchanged."""
    text = (q or "").strip()
    if not text:
        return {"success": True, "results": []}
    try:
        from src.utils import embeddings, timeline_brain_db as tbd

        found = embeddings.find_similar(project_root, text=text, kind="text", limit=limit)
        if not found.get("success"):
            return found
        conn = tbd.connect(project_root)
        resolve_ids: Dict[str, Optional[str]] = {}

        def resolve_clip_id(clip_uuid: Optional[str]) -> Optional[str]:
            if not clip_uuid:
                return None
            if clip_uuid not in resolve_ids:
                row = conn.execute(
                    "SELECT resolve_clip_id, clip_dir FROM clips WHERE clip_uuid = ?",
                    (clip_uuid,),
                ).fetchone()
                resolve_ids[clip_uuid] = (row["resolve_clip_id"] or row["clip_dir"]) if row else None
            return resolve_ids[clip_uuid]

        rows: List[Dict[str, Any]] = []
        for hit in found.get("results") or []:
            entity_type = hit.get("entity_type")
            clip_uuid = hit.get("clip_uuid") or (hit.get("entity_uuid") if entity_type == "clip" else None)
            row: Dict[str, Any] = {
                "result_type": "transcript" if entity_type == "segment" else "semantic",
                "score": hit.get("score"),
                "clip_id": resolve_clip_id(clip_uuid),
                "clip_name": hit.get("clip_name"),
            }
            if entity_type == "shot":
                row["start_seconds"] = hit.get("time_seconds_start")
                row["summary"] = hit.get("description")
            elif entity_type == "segment":
                row["start_seconds"] = hit.get("start_seconds")
                row["summary"] = hit.get("text")
            else:
                row["summary"] = hit.get("summary")
            rows.append(row)
        rows = _v2_enrich_search_results(project_root, rows)
        return {"success": True, "query": text, "model": found.get("model"), "results": rows}
    except Exception as exc:  # noqa: BLE001 — search must fail soft in the panel
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def _v2_clip_duration(report: Dict[str, Any]) -> Optional[float]:
    marker_plan = report.get("clip_analysis_markers") if isinstance(report.get("clip_analysis_markers"), dict) else {}
    duration = marker_plan.get("duration_seconds")
    if isinstance(duration, (int, float)):
        return float(duration)
    technical = report.get("technical") if isinstance(report.get("technical"), dict) else {}
    fmt = technical.get("format") if isinstance(technical.get("format"), dict) else {}
    if isinstance(fmt.get("duration_seconds"), (int, float)):
        return float(fmt["duration_seconds"])
    videos = technical.get("video") if isinstance(technical.get("video"), list) else []
    first = videos[0] if videos and isinstance(videos[0], dict) else {}
    if isinstance(first.get("duration_seconds"), (int, float)):
        return float(first["duration_seconds"])
    return None


def _v2_pick_representative_frame_index(report: Dict[str, Any]) -> Optional[int]:
    """Pick the frame index (1-based, matching sampled_NNNN.jpg) for a clip thumbnail.

    Strategy: middle shot's first frame_index_used, falling back to the middle
    analysis_keyframe, falling back to frame 1.
    """
    visual = report.get("visual") if isinstance(report.get("visual"), dict) else {}
    shots = visual.get("shot_descriptions") if isinstance(visual.get("shot_descriptions"), list) else []
    if shots:
        mid_shot = shots[len(shots) // 2]
        if isinstance(mid_shot, dict):
            indices = mid_shot.get("frame_indices_used") or mid_shot.get("frame_indices")
            if isinstance(indices, list) and indices:
                first = indices[0]
                if isinstance(first, (int, float)):
                    return int(first)
    motion = report.get("motion") if isinstance(report.get("motion"), dict) else {}
    keyframes = motion.get("analysis_keyframes") if isinstance(motion.get("analysis_keyframes"), list) else []
    if keyframes:
        mid_kf = keyframes[len(keyframes) // 2]
        if isinstance(mid_kf, dict) and isinstance(mid_kf.get("index"), (int, float)):
            return int(mid_kf["index"])
    return 1


def _v2_clip_summary_card(clip_slug: str, clip_dir: str, report: Dict[str, Any]) -> Dict[str, Any]:
    clip_block = report.get("clip") if isinstance(report.get("clip"), dict) else {}
    visual = report.get("visual") if isinstance(report.get("visual"), dict) else {}
    classification = visual.get("editorial_classification") if isinstance(visual.get("editorial_classification"), dict) else {}
    shots = visual.get("shot_descriptions") if isinstance(visual.get("shot_descriptions"), list) else []
    editing_notes = visual.get("editing_notes") if isinstance(visual.get("editing_notes"), dict) else {}
    summary = visual.get("clip_summary")
    if not isinstance(summary, str):
        summary = ""
    oneliner = visual.get("clip_summary_oneliner")
    if not isinstance(oneliner, str) or not oneliner:
        oneliner = summary[:140] + ("…" if len(summary) > 140 else "")
    rep_index = _v2_pick_representative_frame_index(report)
    return {
        "clip_id": clip_block.get("clip_id"),
        "clip_slug": clip_slug,
        "clip_dir": clip_dir,
        "clip_name": clip_block.get("clip_name") or clip_block.get("file_path") or clip_slug,
        "file_path": clip_block.get("file_path"),
        "bin_path": clip_block.get("bin_path"),
        "fps": clip_block.get("fps"),
        "duration_seconds": _v2_clip_duration(report),
        "shot_count": len(shots),
        "analyzed_at": report.get("analyzed_at"),
        "vision_committed_at": report.get("vision_committed_at"),
        "primary_use": classification.get("primary_use"),
        "select_potential": classification.get("select_potential"),
        "clip_summary": summary,
        "clip_summary_oneliner": oneliner,
        "search_tags": list(editing_notes.get("search_tags") or []) if isinstance(editing_notes.get("search_tags"), list) else [],
        "representative_frame_index": rep_index,
        "vision_status": report.get("vision_status") or visual.get("status"),
    }


def list_analyzed_clips(project_root: str) -> Dict[str, Any]:
    """List analyzed clips for the bin grid. One row per analysis.json found."""
    rows: List[Dict[str, Any]] = []
    for slug, clip_dir in _v2_iter_analysis_dirs(project_root):
        report = _v2_load_analysis_db_first(project_root, clip_dir)
        if report is None:
            continue
        rows.append(_v2_clip_summary_card(slug, clip_dir, report))
    rows.sort(key=lambda r: (r.get("clip_name") or "").lower())
    return {
        "success": True,
        "project_root": project_root,
        "clips": rows,
        "count": len(rows),
    }


def _v2_find_clip_dir(project_root: str, clip_id: str) -> Optional[str]:
    """Locate the clip directory for a given clip_id under {project_root}/clips/."""
    for slug, clip_dir in _v2_iter_analysis_dirs(project_root):
        if slug == clip_id:
            return clip_dir
        report = _v2_load_analysis(clip_dir)
        if not report:
            continue
        clip_block = report.get("clip") if isinstance(report.get("clip"), dict) else {}
        if str(clip_block.get("clip_id") or "") == clip_id:
            return clip_dir
    return None


def get_analyzed_clip(project_root: str, clip_id: str) -> Dict[str, Any]:
    clip_dir = _v2_find_clip_dir(project_root, clip_id)
    if not clip_dir:
        return {"success": False, "error": f"No analyzed clip found for id={clip_id}"}
    report = _v2_load_analysis_db_first(project_root, clip_dir)
    if report is None:
        return {"success": False, "error": "analysis.json unreadable"}
    visual = report.get("visual") if isinstance(report.get("visual"), dict) else {}
    shots = visual.get("shot_descriptions") if isinstance(visual.get("shot_descriptions"), list) else []
    corrections = _v2_read_corrections_for_dir(clip_dir)
    return {
        "success": True,
        "card": _v2_clip_summary_card(os.path.basename(clip_dir), clip_dir, report),
        "clip": report.get("clip") or {},
        "clip_summary": visual.get("clip_summary"),
        "clip_summary_oneliner": visual.get("clip_summary_oneliner"),
        "editorial_classification": visual.get("editorial_classification") or {},
        "shot_and_style": visual.get("shot_and_style") or {},
        "content": visual.get("content") or {},
        "slate": visual.get("slate") or {},
        "motion": visual.get("motion") or {},
        "cut_understanding": visual.get("cut_understanding") or {},
        "editing_notes": visual.get("editing_notes") or {},
        "cross_shot": visual.get("cross_shot") or {},
        "coverage_groups": visual.get("coverage_groups") or [],
        "continuity_chains": visual.get("continuity_chains") or [],
        "qc": visual.get("qc") or {},
        "confidence": visual.get("confidence") or {},
        "shots": shots,
        "shot_count": len(shots),
        "corrections": corrections,
        "analyzed_at": report.get("analyzed_at"),
        "vision_committed_at": report.get("vision_committed_at"),
    }


def get_analyzed_clip_shots(project_root: str, clip_id: str) -> Dict[str, Any]:
    """Lighter endpoint: just the shots array."""
    clip_dir = _v2_find_clip_dir(project_root, clip_id)
    if not clip_dir:
        return {"success": False, "error": f"No analyzed clip found for id={clip_id}"}
    report = _v2_load_analysis_db_first(project_root, clip_dir)
    if report is None:
        return {"success": False, "error": "analysis.json unreadable"}
    visual = report.get("visual") if isinstance(report.get("visual"), dict) else {}
    shots = visual.get("shot_descriptions") if isinstance(visual.get("shot_descriptions"), list) else []
    return {
        "success": True,
        "clip_id": clip_id,
        "shots": shots,
        "shot_count": len(shots),
    }


def get_analyzed_clip_shot(project_root: str, clip_id: str, shot_index: int) -> Dict[str, Any]:
    clip_dir = _v2_find_clip_dir(project_root, clip_id)
    if not clip_dir:
        return {"success": False, "error": f"No analyzed clip found for id={clip_id}"}
    report = _v2_load_analysis_db_first(project_root, clip_dir)
    if report is None:
        return {"success": False, "error": "analysis.json unreadable"}
    visual = report.get("visual") if isinstance(report.get("visual"), dict) else {}
    shots = visual.get("shot_descriptions") if isinstance(visual.get("shot_descriptions"), list) else []
    motion = report.get("motion") if isinstance(report.get("motion"), dict) else {}
    keyframes = motion.get("analysis_keyframes") if isinstance(motion.get("analysis_keyframes"), list) else []
    matched: Optional[Dict[str, Any]] = None
    for entry in shots:
        if isinstance(entry, dict):
            try:
                if int(entry.get("shot_index")) == int(shot_index):
                    matched = entry
                    break
            except (TypeError, ValueError):
                continue
    if matched is None:
        return {"success": False, "error": f"shot_index={shot_index} not found in clip {clip_id}"}
    frame_indices = matched.get("frame_indices_used") or matched.get("frame_indices") or []
    if not isinstance(frame_indices, list):
        frame_indices = []
    # Resolve each frame index back to its source keyframe (time_seconds, selection_reason, file path)
    kf_by_index: Dict[int, Dict[str, Any]] = {}
    for kf in keyframes:
        if not isinstance(kf, dict):
            continue
        try:
            kf_by_index[int(kf.get("index"))] = kf
        except (TypeError, ValueError):
            continue
    frame_rows: List[Dict[str, Any]] = []
    for raw_index in frame_indices:
        try:
            idx = int(raw_index)
        except (TypeError, ValueError):
            continue
        kf = kf_by_index.get(idx, {})
        frame_rows.append({
            "frame_index": idx,
            "time_seconds": kf.get("time_seconds"),
            "selection_reason": kf.get("selection_reason"),
            "delta_from_previous": kf.get("delta_from_previous"),
            "motion_peak": bool(kf.get("motion_peak")),
        })
    corrections = _v2_read_corrections_for_dir(clip_dir)
    shot_corrections = _v2_filter_corrections_for_shot(corrections, matched.get("shot_uuid"), shot_index)
    # Cross-shot relationships (spec §4) come from the DB, not the report —
    # fill the shot page's Relationships group when confirmed rows exist.
    # Exported reports don't carry shot_uuid, so derive it from the DB by
    # clip + shot_index.
    try:
        from src.utils import analysis_store as _analysis_store
        from src.utils import shot_relationships as _shot_rel
        conn = _timeline_brain_db.connect(project_root)
        shot_uuid = matched.get("shot_uuid")
        if not shot_uuid:
            clip_uuid = _analysis_store.resolve_clip_uuid(conn, clip_id)
            if clip_uuid:
                hit = conn.execute(
                    "SELECT shot_uuid FROM shots WHERE clip_uuid = ? AND shot_index = ?",
                    (clip_uuid, int(shot_index)),
                ).fetchone()
                shot_uuid = hit["shot_uuid"] if hit else None
        if shot_uuid:
            relationships = _shot_rel.relationships_for_shot(conn, str(shot_uuid))
            if relationships:
                matched = dict(matched)
                matched["relationships"] = relationships
    except Exception:  # noqa: BLE001 — panel reads fail soft
        pass
    return {
        "success": True,
        "clip_id": clip_id,
        "shot_index": shot_index,
        "shot": matched,
        "frames": frame_rows,
        "corrections": shot_corrections,
    }


def regenerate_clip_transcript(
    project_root: str,
    clip_id: str,
    *,
    with_words: bool = True,
    backend: Optional[str] = None,
    language: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-run transcription for a single clip, writing transcript.json (with
    word_timestamps when supported) and merging the result into analysis.json.
    Does not touch the rest of the analysis layers (visual, motion, etc.).
    """
    clip_dir = _v2_find_clip_dir(project_root, clip_id)
    if not clip_dir:
        return {"success": False, "error": f"No analyzed clip found for id={clip_id}"}
    report = _v2_load_analysis(clip_dir)
    if report is None:
        return {"success": False, "error": "analysis.json unreadable"}
    source_file = report.get("source_file") or (report.get("clip") or {}).get("file_path")
    if not source_file or not os.path.isfile(str(source_file)):
        return {"success": False, "error": f"source file not found on disk: {source_file!r}"}
    try:
        from src.utils.media_analysis import (
            _transcribe,
            detect_capabilities,
        )
    except Exception as exc:
        return {"success": False, "error": f"transcription helpers unavailable: {exc}"}
    artifacts = {
        "clip_dir": clip_dir,
        "analysis_json": os.path.join(clip_dir, "analysis.json"),
        "transcript_json": os.path.join(clip_dir, "transcript.json"),
        "transcript_srt": os.path.join(clip_dir, "transcript.srt"),
        "transcript_vtt": os.path.join(clip_dir, "transcript.vtt"),
    }
    capabilities = detect_capabilities()
    transcription_opts: Dict[str, Any] = {
        "enabled": True,
        "word_timestamps": bool(with_words),
        # Allow model download because this is a user-initiated re-transcribe;
        # without this flag _transcribe will skip with a guard error.
        "allow_model_download": True,
    }
    if backend:
        transcription_opts["backend"] = backend
    if language:
        transcription_opts["language"] = language
    if model:
        transcription_opts["model"] = model
    payload = _transcribe(source_file, artifacts, {"transcription": transcription_opts}, capabilities)
    if not payload.get("success"):
        return {"success": False, "error": payload.get("reason") or payload.get("error") or "transcription failed", "backend": payload.get("backend")}
    # Patch analysis.json so the in-memory snapshot stays in sync with the new
    # transcript.json artifact. We only touch the `transcription` block.
    try:
        with open(artifacts["analysis_json"], "r", encoding="utf-8") as handle:
            updated_report = json.load(handle)
    except Exception:
        updated_report = report
    updated_report["transcription"] = {
        "success": True,
        "backend": payload.get("backend"),
        "language": payload.get("language"),
        "text": payload.get("text"),
        "segments": payload.get("segments") or [],
    }
    if payload.get("words"):
        updated_report["transcription"]["words"] = payload["words"]
    try:
        _atomic_write_json(artifacts["analysis_json"], updated_report)
    except Exception as exc:
        return {"success": False, "error": f"transcript written but analysis.json patch failed: {exc}"}
    word_segment_count = sum(1 for seg in (payload.get("segments") or []) if isinstance(seg, dict) and seg.get("words"))
    return {
        "success": True,
        "clip_id": clip_id,
        "backend": payload.get("backend"),
        "language": payload.get("language"),
        "segment_count": len(payload.get("segments") or []),
        "word_segment_count": word_segment_count,
        "wrote_words": bool(payload.get("words") or word_segment_count),
    }


_TRANSCRIPT_CORRECTIONS_FILENAME = "transcript-corrections.json"


def _transcript_corrections_path(clip_dir: str) -> str:
    return os.path.join(clip_dir, _TRANSCRIPT_CORRECTIONS_FILENAME)


def _read_transcript_corrections(clip_dir: str) -> Optional[Dict[str, Any]]:
    path = _transcript_corrections_path(clip_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _normalize_transcript_segments(raw_segments: Any) -> List[Dict[str, Any]]:
    """Coerce a list of raw segment dicts (from transcript.json, analysis.json,
    or transcript-corrections.json) into the dashboard's canonical shape.

    Canonical: {index, start_seconds, end_seconds, text, words?: [...]}.
    """
    def _to_float(v: Any) -> Optional[float]:
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None
    out: List[Dict[str, Any]] = []
    if not isinstance(raw_segments, list):
        return out
    for index, seg in enumerate(raw_segments):
        if not isinstance(seg, dict):
            continue
        if seg.get("deleted"):
            continue
        start = seg.get("start_seconds") if seg.get("start_seconds") is not None else seg.get("start")
        end = seg.get("end_seconds") if seg.get("end_seconds") is not None else seg.get("end")
        text = seg.get("text")
        if text in (None, ""):
            text = seg.get("content")
        if text in (None, ""):
            continue
        normalized: Dict[str, Any] = {
            "index": int(seg.get("index", index)),
            "start_seconds": _to_float(start),
            "end_seconds": _to_float(end),
            "text": str(text).strip(),
        }
        words = seg.get("words")
        if isinstance(words, list) and words:
            word_rows: List[Dict[str, Any]] = []
            for w_index, w in enumerate(words):
                if not isinstance(w, dict):
                    continue
                w_text = w.get("word") if w.get("word") not in (None, "") else w.get("text")
                if w_text in (None, ""):
                    continue
                word_rows.append({
                    "index": int(w.get("index", w_index)),
                    "word": str(w_text),
                    "start_seconds": _to_float(w.get("start_seconds") if w.get("start_seconds") is not None else w.get("start")),
                    "end_seconds": _to_float(w.get("end_seconds") if w.get("end_seconds") is not None else w.get("end")),
                })
            if word_rows:
                normalized["words"] = word_rows
        out.append(normalized)
    return out


def get_analyzed_clip_transcript(project_root: str, clip_id: str) -> Dict[str, Any]:
    clip_dir = _v2_find_clip_dir(project_root, clip_id)
    if not clip_dir:
        return {"success": False, "error": f"No analyzed clip found for id={clip_id}"}
    report = _v2_load_analysis(clip_dir)
    if report is None:
        return {"success": False, "error": "analysis.json unreadable"}
    transcription = report.get("transcription") if isinstance(report.get("transcription"), dict) else {}

    corrections = _read_transcript_corrections(clip_dir)
    corrected_segments: Optional[List[Dict[str, Any]]] = None
    edited_count = 0
    deleted_indices: List[int] = []
    if corrections and isinstance(corrections.get("segments"), list):
        corrected_segments = _normalize_transcript_segments(corrections["segments"])
        edited_count = int(corrections.get("edited_count") or 0)
        deleted_indices = corrections.get("deleted_indices") or []

    if corrected_segments is not None:
        segments = corrected_segments
    else:
        segments = _normalize_transcript_segments(transcription.get("segments"))

    clip_meta = report.get("clip") if isinstance(report.get("clip"), dict) else {}
    return {
        "success": True,
        "clip_id": clip_id,
        "clip_name": clip_meta.get("clip_name"),
        "backend": transcription.get("backend"),
        "language": transcription.get("language"),
        "text": transcription.get("text"),
        "segments": segments,
        "segment_count": len(segments),
        "available": bool(segments or transcription.get("text")),
        "has_corrections": corrections is not None,
        "corrections_meta": (corrections or {}).get("metadata") or {
            "edited_count": edited_count,
            "deleted_count": len(deleted_indices),
            "updated_at": (corrections or {}).get("updated_at"),
        } if corrections is not None else None,
    }


def save_clip_transcript_corrections(project_root: str, clip_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Write the shadow segments array to <clip-dir>/transcript-corrections.json.

    Expected body shape:
      {
        "segments": [ { "index": n, "start_seconds": s, "end_seconds": e,
                        "text": "...", "words": [...] }, ... ],
        "edited_count": N,
        "deleted_indices": [int, ...]
      }
    Or "clear": true to remove the corrections file entirely.
    """
    clip_dir = _v2_find_clip_dir(project_root, clip_id)
    if not clip_dir:
        return {"success": False, "error": f"No analyzed clip found for id={clip_id}"}
    path = _transcript_corrections_path(clip_dir)
    if bool(body.get("clear")):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception as exc:
            return {"success": False, "error": str(exc)}
        return {"success": True, "cleared": True, "path": path}
    raw_segments = body.get("segments")
    if not isinstance(raw_segments, list):
        return {"success": False, "error": "body.segments must be a list"}
    normalized = _normalize_transcript_segments(raw_segments)
    payload = {
        "schema_version": "1.0",
        "updated_at": _now_iso(),
        "segments": normalized,
        "edited_count": int(body.get("edited_count") or 0),
        "deleted_indices": list(body.get("deleted_indices") or []),
        "metadata": {
            "edited_count": int(body.get("edited_count") or 0),
            "deleted_count": len(body.get("deleted_indices") or []),
            "updated_at": _now_iso(),
        },
    }
    try:
        _atomic_write_json(path, payload)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "path": path,
        "segment_count": len(normalized),
        "edited_count": payload["edited_count"],
        "deleted_count": len(payload["deleted_indices"]),
    }


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_clip_frame_path(project_root: str, clip_id: str, frame_index: int) -> Optional[str]:
    clip_dir = _v2_find_clip_dir(project_root, clip_id)
    if not clip_dir:
        return None
    candidate = os.path.join(clip_dir, "frames", f"sampled_{int(frame_index):04d}.jpg")
    if os.path.isfile(candidate):
        return candidate
    return None


def _v2_read_corrections_for_dir(clip_dir: str) -> Dict[str, Any]:
    path = os.path.join(clip_dir, "corrections.json")
    if not os.path.isfile(path):
        return {"schema_version": "2.0", "current": {}, "changelog": []}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            return {"schema_version": "2.0", "current": {}, "changelog": []}
        data.setdefault("schema_version", "2.0")
        data.setdefault("current", {})
        data.setdefault("changelog", [])
        return data
    except (OSError, json.JSONDecodeError):
        return {"schema_version": "2.0", "current": {}, "changelog": []}


def _v2_filter_corrections_for_shot(
    corrections: Dict[str, Any], shot_uuid: Any, shot_index: Any
) -> Dict[str, Any]:
    current = corrections.get("current") if isinstance(corrections.get("current"), dict) else {}
    changelog = corrections.get("changelog") if isinstance(corrections.get("changelog"), list) else []
    keep_keys: set = set()
    if shot_uuid:
        keep_keys.add(str(shot_uuid))
    if shot_index is not None:
        keep_keys.add(str(shot_index))
    filtered_current = {
        key: entry
        for key, entry in current.items()
        if key.startswith("shot:") and key.split(":", 2)[1] in keep_keys
    }
    filtered_changelog = [
        row for row in changelog
        if row.get("entity_type") == "shot"
        and str(row.get("entity_uuid")) in keep_keys
    ]
    return {"current": filtered_current, "changelog": filtered_changelog}


def apply_clip_correction(project_root: str, clip_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Proxy POST /api/clips/<id>/corrections → media_analysis update_*_field helpers."""
    clip_dir = _v2_find_clip_dir(project_root, clip_id)
    if not clip_dir:
        return {"success": False, "error": f"No analyzed clip found for id={clip_id}"}
    from src.server import _v2_update_field
    entity_type = body.get("entity_type") or body.get("entityType") or "shot"
    params: Dict[str, Any] = dict(body)
    params["clip_id"] = clip_id
    params["clip_dir"] = clip_dir
    return _v2_update_field(project_root, params, entity_type=entity_type)


def export_clip_selection(project_root: str, clip_ids: List[str], fmt: str) -> Tuple[bytes, str, str]:
    """Build the export bytes for a selection. Returns (bytes, content_type, filename)."""
    fmt = (fmt or "json").strip().lower()
    payloads: List[Dict[str, Any]] = []
    for clip_id in clip_ids:
        data = get_analyzed_clip(project_root, clip_id)
        if data.get("success"):
            payloads.append(data)
    timestamp = _now_iso().replace(":", "").replace("-", "")[:13]
    if fmt == "csv":
        import csv as _csv
        import io as _io
        buf = _io.StringIO()
        writer = _csv.writer(buf)
        writer.writerow([
            "clip_id", "clip_name", "bin_path", "duration_seconds", "shot_count",
            "primary_use", "select_potential", "energy_arc", "style",
            "search_tags", "qc_warnings", "clip_summary_oneliner", "clip_summary",
        ])
        for clip in payloads:
            card = clip.get("card") or {}
            classification = clip.get("editorial_classification") or {}
            editing_notes = clip.get("editing_notes") or {}
            qc = clip.get("qc") or {}
            writer.writerow([
                card.get("clip_id") or "",
                card.get("clip_name") or "",
                card.get("bin_path") or "",
                card.get("duration_seconds") if card.get("duration_seconds") is not None else "",
                clip.get("shot_count") if clip.get("shot_count") is not None else "",
                classification.get("primary_use") or "",
                classification.get("select_potential") or "",
                classification.get("energy_arc") or "",
                classification.get("style") or "",
                "|".join(str(t) for t in (editing_notes.get("search_tags") or [])),
                "|".join(str(w) for w in (qc.get("warnings") or [])),
                clip.get("clip_summary_oneliner") or "",
                clip.get("clip_summary") or "",
            ])
        return buf.getvalue().encode("utf-8"), "text/csv; charset=utf-8", f"selection-{timestamp}.csv"
    # JSON: full payload array
    text = json.dumps({"clip_count": len(payloads), "clips": payloads}, indent=2)
    return text.encode("utf-8"), "application/json", f"selection-{timestamp}.json"


def combined_clip_analysis(project_root: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Synthesize a multi-clip review payload. Body: {clip_ids: [str, ...]}.

    Returns a unified payload with: clip_count, sources (per-clip card),
    clip_summaries[] (one per clip), editorial_classification (union),
    shot_and_style (per-clip), shots[] (all shots from all clips, source-tagged
    and time-offset by accumulated clip duration so they read like one strip),
    transcript (concatenated segments with the same time offset), tags (union),
    qc (union).
    """
    clip_ids = body.get("clip_ids")
    if not isinstance(clip_ids, list) or not clip_ids:
        return {"success": False, "error": "clip_ids must be a non-empty list"}
    sources: List[Dict[str, Any]] = []
    shot_summaries: List[Dict[str, Any]] = []
    transcript_segments: List[Dict[str, Any]] = []
    clip_summaries: List[Dict[str, Any]] = []
    union_tags: List[str] = []
    union_qc: List[str] = []
    classifications: List[Dict[str, Any]] = []
    shot_and_style_blocks: List[Dict[str, Any]] = []
    cursor = 0.0
    total_duration = 0.0
    for clip_id in clip_ids:
        data = get_analyzed_clip(project_root, clip_id)
        if not data.get("success"):
            continue
        card = data.get("card") or {}
        duration = float(card.get("duration_seconds") or 0.0)
        sources.append({
            "clip_id": card.get("clip_id") or clip_id,
            "clip_name": card.get("clip_name"),
            "bin_path": card.get("bin_path"),
            "duration_seconds": duration,
            "shot_count": data.get("shot_count"),
            "thumbnail_frame_index": card.get("thumbnail_frame_index"),
            "offset_seconds": cursor,
        })
        if data.get("clip_summary"):
            clip_summaries.append({
                "clip_id": card.get("clip_id") or clip_id,
                "clip_name": card.get("clip_name"),
                "oneliner": data.get("clip_summary_oneliner"),
                "summary": data.get("clip_summary"),
            })
        if isinstance(data.get("editorial_classification"), dict):
            classifications.append({"clip_name": card.get("clip_name"), **data["editorial_classification"]})
        if isinstance(data.get("shot_and_style"), dict):
            shot_and_style_blocks.append({"clip_name": card.get("clip_name"), **data["shot_and_style"]})
        for shot in (data.get("shots") or []):
            if not isinstance(shot, dict):
                continue
            shot_summaries.append({
                "source_clip_id": card.get("clip_id") or clip_id,
                "source_clip_name": card.get("clip_name"),
                "source_offset_seconds": cursor,
                "shot_index": shot.get("shot_index"),
                "time_seconds_start": (float(shot.get("time_seconds_start") or 0.0) + cursor) if shot.get("time_seconds_start") is not None else None,
                "time_seconds_end": (float(shot.get("time_seconds_end") or 0.0) + cursor) if shot.get("time_seconds_end") is not None else None,
                "frame_indices_used": shot.get("frame_indices_used") or [],
                "description": shot.get("description"),
                "qc_flags": shot.get("qc_flags") or [],
            })
        # Transcript merge
        clip_dir = _v2_find_clip_dir(project_root, clip_id)
        if clip_dir:
            t = get_analyzed_clip_transcript(project_root, clip_id)
            if t.get("success"):
                for seg in (t.get("segments") or []):
                    if not isinstance(seg, dict):
                        continue
                    transcript_segments.append({
                        "source_clip_id": card.get("clip_id") or clip_id,
                        "source_clip_name": card.get("clip_name"),
                        "source_offset_seconds": cursor,
                        "start_seconds": (float(seg.get("start_seconds") or 0.0) + cursor) if seg.get("start_seconds") is not None else None,
                        "end_seconds": (float(seg.get("end_seconds") or 0.0) + cursor) if seg.get("end_seconds") is not None else None,
                        "text": seg.get("text"),
                    })
        for tag in ((data.get("editing_notes") or {}).get("search_tags") or []):
            text = str(tag).strip()
            if text and text not in union_tags:
                union_tags.append(text)
        for warn in ((data.get("qc") or {}).get("warnings") or []):
            text = str(warn).strip()
            if text and text not in union_qc:
                union_qc.append(text)
        cursor += duration
        total_duration += duration
    if not sources:
        return {"success": False, "error": "none of the requested clip_ids resolved to an analyzed clip"}
    return {
        "success": True,
        "clip_count": len(sources),
        "total_duration_seconds": total_duration,
        "sources": sources,
        "clip_summaries": clip_summaries,
        "editorial_classifications": classifications,
        "shot_and_style_blocks": shot_and_style_blocks,
        "shots": shot_summaries,
        "transcript_segments": transcript_segments,
        "search_tags": union_tags,
        "qc_warnings": union_qc,
    }


def _v2_create_timeline_from_clips(body: Dict[str, Any]) -> Dict[str, Any]:
    """POST /api/resolve/create_timeline_from_clips → proxies media_pool
    action="create_timeline_from_clips". Body: {name?, clip_ids: [str, ...]}.
    """
    clip_ids = body.get("clip_ids")
    if not isinstance(clip_ids, list) or not clip_ids:
        return {"success": False, "error": "clip_ids must be a non-empty list"}
    name = str(body.get("name") or "Review Selection").strip() or "Review Selection"
    try:
        from src.server import media_pool
        return media_pool("create_timeline_from_clips", params={"name": name, "clip_ids": list(clip_ids)})
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def _v2_open_clip_in_resolve(body: Dict[str, Any]) -> Dict[str, Any]:
    """Proxy POST /api/resolve/open_clip → media_pool_item(open_in_viewer) /
    resolve_control(save_state|restore_state). Used by the shot-detail
    'Open in Resolve' button and the save-before-preview workflow.

    Body shape:
      {action: "open_in_viewer" (default), clip_id, mark_in_seconds?,
       mark_out_seconds?, clear_marks?, mark_type?, page?}
      {action: "save_state"}
      {action: "restore_state", state_token}
    """
    requested_action = (body.get("action") or "open_in_viewer").strip().lower()
    try:
        if requested_action in {"save_state", "restore_state"}:
            from src.server import resolve_control
            return resolve_control(requested_action, params=body)
        if requested_action == "open_in_viewer":
            from src.server import media_pool_item
            params = dict(body)
            params.pop("action", None)
            params.setdefault("page", "media")
            return media_pool_item("open_in_viewer", params=params)
        return {"success": False, "error": f"Unsupported action {requested_action!r}"}
    except Exception as exc:  # noqa: BLE001 — dashboard surface should never crash
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


# ─── C6: timeline version chain + brain-edit history helpers ─────────────────


def list_timelines_with_versions(project_root: str) -> Dict[str, Any]:
    """Every timeline that has at least one archived version, with counts."""
    try:
        conn = _timeline_brain_db.connect(project_root)
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}", "timelines": []}
    rows = conn.execute(
        """
        SELECT timeline_name,
               COUNT(*) AS version_count,
               MAX(version) AS latest_version,
               MAX(created_at) AS most_recent
        FROM timeline_versions
        GROUP BY timeline_name
        ORDER BY most_recent DESC NULLS LAST
        """
    ).fetchall()
    return {
        "success": True,
        "timelines": [dict(r) for r in rows],
    }


def get_timeline_history_payload(
    project_root: str, timeline_name: str, *, history_limit: int = 200,
) -> Dict[str, Any]:
    """Combined payload: version chain + brain edits for a single timeline."""
    versions = _timeline_versioning.list_timeline_versions(
        project_root=project_root, timeline_name=timeline_name,
    )
    edits = _brain_edits.get_brain_edit_history(
        project_root=project_root, timeline_name=timeline_name, limit=history_limit,
    )
    return {
        "success": True,
        "timeline_name": timeline_name,
        "versions": versions,
        "edits": edits,
    }


def list_edit_plans_payload(project_root: str) -> Dict[str, Any]:
    """Edit-engine plan list for the panel browser (DB/file only, no Resolve).

    Fingerprint-corrupt plans surface as {"plan_id", "corrupt": True} warning
    rows rather than being silently hidden.
    """
    try:
        from src.utils import edit_engine as _edit_engine
        return _edit_engine.list_plans(project_root, limit=50, include_corrupt=True)
    except Exception as exc:  # noqa: BLE001 — panel reads fail soft
        return {"success": False, "error": f"{type(exc).__name__}: {exc}", "plans": []}


def get_edit_plan_payload(project_root: str, plan_id: str) -> Dict[str, Any]:
    """Full plan detail for the panel, enriched for rendering: selects
    decisions and swap alternates gain a `thumb_frame_index` (the shot's first
    sampled frame, for the existing /api/clips/<id>/frames/<idx> route) and a
    `resolve_clip_id` fallback mapped from clip_uuid. Enrichment is best-effort
    — the plan still renders without thumbnails when the DB is unavailable.
    """
    try:
        from src.utils import edit_engine as _edit_engine
        plan = _edit_engine.load_plan(project_root, plan_id)
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
    if plan is None:
        return {"success": False, "error": f"Plan {plan_id} not found"}
    if plan.get("_corrupt"):
        return {"success": True, "plan_id": plan_id, "corrupt": True}
    plan = json.loads(json.dumps(plan, default=str))  # detach a plain copy
    try:
        conn = _timeline_brain_db.connect(project_root)
        clip_id_cache: Dict[str, Any] = {}

        def _enrich(row: Dict[str, Any]) -> None:
            clip_uuid = str(row.get("clip_uuid") or "")
            if not row.get("resolve_clip_id") and clip_uuid:
                if clip_uuid not in clip_id_cache:
                    hit = conn.execute(
                        "SELECT resolve_clip_id FROM clips WHERE clip_uuid = ?",
                        (clip_uuid,),
                    ).fetchone()
                    clip_id_cache[clip_uuid] = hit["resolve_clip_id"] if hit else None
                if clip_id_cache[clip_uuid]:
                    row["resolve_clip_id"] = clip_id_cache[clip_uuid]
            shot_uuid = row.get("shot_uuid")
            if shot_uuid and row.get("thumb_frame_index") is None:
                hit = conn.execute(
                    "SELECT MIN(frame_index) AS frame_index FROM frames WHERE shot_uuid = ?",
                    (str(shot_uuid),),
                ).fetchone()
                if hit and hit["frame_index"] is not None:
                    row["thumb_frame_index"] = int(hit["frame_index"])

        for decision in plan.get("decisions") or []:
            if isinstance(decision, dict):
                _enrich(decision)
        for alternate in plan.get("alternates") or []:
            if isinstance(alternate, dict):
                _enrich(alternate)
    except Exception:  # noqa: BLE001 — thumbnails are progressive enhancement
        pass
    return {"success": True, "corrupt": False, "plan": plan}


def proxy_timeline_versioning_action(body: Dict[str, Any]) -> Dict[str, Any]:
    """Bridge dashboard → MCP server timeline_versioning tool.

    Body shape: {action, ...params}. Used for write actions (archive, rollback,
    prune) that need a live Resolve connection.
    """
    action = (body.get("action") or "").strip()
    if not action:
        return {"success": False, "error": "action required"}
    try:
        from src.server import timeline_versioning as _tv_tool
        params = {k: v for k, v in body.items() if k != "action"}
        return _tv_tool(action, params=params)
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}



def _v2_enrich_search_results(project_root: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Augment /api/index/query results with fps, shot_index, and a thumbnail frame.

    These come from the clip's analysis.json on disk so the UI can render SMPTE
    timecode (HH:MM:SS:FF) and a clickable card that opens the deep-link review
    page for the matching shot.
    """
    if not results:
        return results
    analyses_by_clip: Dict[str, Optional[Dict[str, Any]]] = {}
    for row in results:
        clip_id = row.get("clip_id") or row.get("clip_key")
        if not clip_id:
            continue
        if clip_id not in analyses_by_clip:
            clip_dir = _v2_find_clip_dir(project_root, clip_id)
            analyses_by_clip[clip_id] = _v2_load_analysis(clip_dir) if clip_dir else None
        report = analyses_by_clip[clip_id]
        if not report:
            continue
        # fps from technical block
        technical = report.get("technical") if isinstance(report.get("technical"), dict) else {}
        videos = technical.get("video") if isinstance(technical.get("video"), list) else []
        fps = None
        if videos and isinstance(videos[0], dict):
            raw_fps = videos[0].get("frame_rate")
            try:
                fps = float(str(raw_fps).split("/")[0]) / (float(str(raw_fps).split("/")[1]) if "/" in str(raw_fps) else 1.0) if raw_fps else None
            except (TypeError, ValueError, ZeroDivisionError):
                fps = None
        if not fps:
            marker_plan = report.get("clip_analysis_markers") if isinstance(report.get("clip_analysis_markers"), dict) else {}
            try:
                fps = float(marker_plan.get("fps")) if marker_plan.get("fps") else None
            except (TypeError, ValueError):
                fps = None
        row["fps"] = fps
        # Resolve shot_index from start_seconds against shot_descriptions
        visual = report.get("visual") if isinstance(report.get("visual"), dict) else {}
        shots = visual.get("shot_descriptions") if isinstance(visual.get("shot_descriptions"), list) else []
        start_seconds = row.get("start_seconds")
        matched_shot: Optional[Dict[str, Any]] = None
        if start_seconds is not None:
            try:
                ts = float(start_seconds)
                for shot in shots:
                    if not isinstance(shot, dict):
                        continue
                    s = shot.get("time_seconds_start")
                    e = shot.get("time_seconds_end")
                    if s is None or e is None:
                        continue
                    if float(s) <= ts < float(e):
                        matched_shot = shot
                        break
            except (TypeError, ValueError):
                matched_shot = None
        if matched_shot is None and shots:
            # Clip-level result or no time anchor — point at the middle shot.
            matched_shot = shots[len(shots) // 2] if isinstance(shots[len(shots) // 2], dict) else None
        if matched_shot is not None:
            row["shot_index"] = matched_shot.get("shot_index")
            frame_indices = matched_shot.get("frame_indices_used") or matched_shot.get("frame_indices") or []
            if isinstance(frame_indices, list) and frame_indices:
                row["thumbnail_frame_index"] = frame_indices[0]
        if "thumbnail_frame_index" not in row:
            row["thumbnail_frame_index"] = _v2_pick_representative_frame_index(report)
    return results


def read_clip_corrections(project_root: str, clip_id: str) -> Dict[str, Any]:
    clip_dir = _v2_find_clip_dir(project_root, clip_id)
    if not clip_dir:
        return {"success": False, "error": f"No analyzed clip found for id={clip_id}"}
    data = _v2_read_corrections_for_dir(clip_dir)
    return {
        "success": True,
        "clip_id": clip_id,
        "corrections_path": os.path.join(clip_dir, "corrections.json"),
        "current": data.get("current", {}),
        "changelog": data.get("changelog", []),
        "current_field_count": len(data.get("current", {})),
        "changelog_count": len(data.get("changelog", [])),
    }


class DashboardState:
    def __init__(self, project_name: str, project_id: str, analysis_root: str):
        self.base_analysis_root = os.path.realpath(os.path.abspath(os.path.expanduser(str(analysis_root))))
        if project_name == "Dashboard Analysis" and project_id == "dashboard":
            current = _current_resolve_project_context(self.base_analysis_root)
            if current:
                project_name = current["project_name"]
                project_id = current.get("project_id")
        self.project_name = project_name
        self.project_id = project_id
        root = project_root_for_dashboard(
            project_name=project_name,
            project_id=project_id,
            analysis_root=self.base_analysis_root,
        )
        if not root.get("success"):
            raise RuntimeError(root.get("error") or "Invalid analysis root")
        self.output_root = root
        self.project_root = root["project_root"]
        self.lock = threading.Lock()

    def context(self) -> Dict[str, Any]:
        return _context_payload(self.project_name, self.project_id, self.output_root, source="active")

    def projects(self) -> Dict[str, Any]:
        return discover_project_contexts(self.base_analysis_root, self.context())

    def related_project_roots(self) -> List[str]:
        return list(self.projects().get("related_project_roots") or [])

    def set_context(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        project_root = payload.get("project_root") or payload.get("projectRoot")
        project_name = payload.get("project_name") or payload.get("projectName")
        project_id = payload.get("project_id") or payload.get("projectId")
        load_resolve_project = bool(payload.get("load_resolve_project") or payload.get("loadResolveProject"))
        if load_resolve_project:
            resolve_project_name = payload.get("resolve_project_name") or payload.get("resolveProjectName") or project_name
            resolve_project_folder_path = payload.get("resolve_project_folder_path") or payload.get("resolveProjectFolderPath")
            loaded = _load_resolve_project_context(self.base_analysis_root, resolve_project_name, resolve_project_folder_path)
            if not loaded.get("success"):
                return loaded
            active = loaded["active"]
            self.project_name = active["project_name"]
            self.project_id = active.get("project_id")
            self.output_root = loaded["output_root"]
            self.project_root = active["project_root"]
            return {"success": True, "active": self.context(), "projects": self.projects()}
        if project_root:
            context = _context_from_project_root(self.base_analysis_root, str(project_root), source="selected")
            if not context:
                candidate_root = os.path.realpath(os.path.abspath(os.path.expanduser(str(project_root))))
                try:
                    under_base = os.path.commonpath([candidate_root, self.base_analysis_root]) == self.base_analysis_root
                except ValueError:
                    under_base = False
                if not under_base or not project_name:
                    return {"success": False, "error": "Project context must be under the analysis base root"}
                project_directory = os.path.basename(candidate_root)
                context = {
                    "project_name": project_name,
                    "project_id": project_id,
                    "project_root": candidate_root,
                    "project_directory": project_directory,
                }
            project_name = project_name or context["project_name"]
            project_id = project_id if project_id not in (None, "") else context.get("project_id")
            output_root = {
                "success": True,
                "analysis_version": None,
                "base_root": self.base_analysis_root,
                "project_root": context["project_root"],
                "project_directory": context["project_directory"],
                "project_name": project_name,
                "project_id": project_id,
                "errors": [],
            }
        else:
            if not project_name:
                return {"success": False, "error": "project_name or project_root is required"}
            output_root = project_root_for_dashboard(
                project_name=project_name,
                project_id=project_id,
                analysis_root=self.base_analysis_root,
            )
            if not output_root.get("success"):
                return output_root
        self.project_name = str(project_name or output_root.get("project_name") or "Project")
        self.project_id = str(project_id) if project_id not in (None, "") else None
        self.output_root = output_root
        self.project_root = output_root["project_root"]
        return {"success": True, "active": self.context(), "projects": self.projects()}


DOC_SOURCES = {
    "readme": {"title": "README", "path": "README.md"},
    "analysis-guide": {"title": "Media Analysis Guide", "path": "docs/guides/media-analysis-guide.md"},
    "agent-skill": {"title": "Agent Skill", "path": "docs/SKILL.md"},
    "release-notes": {"title": "Release Notes", "path": "CHANGELOG.md"},
}


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _mcp_version() -> str:
    try:
        from src.server import VERSION as _server_version  # type: ignore
        return str(_server_version)
    except Exception:
        try:
            pkg_path = os.path.join(_repo_root(), "package.json")
            with open(pkg_path, "r", encoding="utf-8") as handle:
                return str(json.load(handle).get("version") or "unknown")
        except Exception:
            return "unknown"


def _request_is_loopback(handler: BaseHTTPRequestHandler) -> bool:
    """Defensive guard: only allow privileged routes from loopback clients."""
    try:
        addr = (handler.client_address or ("",))[0]
    except Exception:
        return False
    return addr in {"127.0.0.1", "::1", "localhost"}


def _launch_claude_code_terminal() -> Dict[str, Any]:
    """Open a Terminal/iTerm window at the MCP server's project root running
    the ``claude`` CLI. macOS only — other platforms return a clipboard-only
    hint so the dashboard can show a sensible message instead of silently no-op.
    """
    repo_root = _repo_root()
    if sys.platform != "darwin":
        return {
            "success": False,
            "error": "Terminal launch is macOS-only. Open your terminal at the project root and run `claude`, then paste the prompt.",
        }
    import shlex
    import shutil
    import subprocess
    claude_bin = shutil.which("claude") or "claude"
    cmd = f"cd {shlex.quote(repo_root)} && {shlex.quote(claude_bin)}"
    iterm_running = False
    try:
        check = subprocess.run(
            ["osascript", "-e", 'application "iTerm" is running'],
            capture_output=True, text=True, timeout=8,
        )
        iterm_running = (check.stdout or "").strip().lower() == "true"
    except Exception:
        iterm_running = False
    if iterm_running:
        script = (
            'tell application "iTerm"\n'
            '  activate\n'
            f'  create window with default profile command "{cmd}"\n'
            'end tell'
        )
    else:
        escaped = cmd.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            'tell application "Terminal"\n'
            '  activate\n'
            f'  do script "{escaped}"\n'
            'end tell'
        )
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return {"success": False, "error": (proc.stderr or "").strip() or "osascript failed"}
        return {
            "success": True,
            "terminal": "iterm" if iterm_running else "terminal",
            "cwd": repo_root,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _native_directory_picker(initial: Optional[str] = None) -> Dict[str, Any]:
    """Open a native OS folder picker on the *server* machine and return the
    absolute path. The dashboard runs on localhost so the picker pops on the
    user's machine — works in every browser because the browser is never asked
    to expose a filesystem path.
    """
    initial_dir = initial if initial and os.path.isdir(initial) else os.path.expanduser("~")
    if sys.platform == "darwin":
        # AppleScript picker — works without a Python Tk binding installed.
        script = (
            'tell application "System Events" to activate\n'
            f'set chosenFolder to choose folder with prompt "Select a folder" default location POSIX file "{initial_dir}"\n'
            'POSIX path of chosenFolder'
        )
        try:
            import subprocess
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120,
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()
                if "User canceled" in stderr or "cancelled" in stderr.lower():
                    return {"success": True, "canceled": True}
                return {"success": False, "error": stderr or "AppleScript picker failed"}
            path = (proc.stdout or "").strip().rstrip("/")
            if not path:
                return {"success": True, "canceled": True}
            return {"success": True, "path": path}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
    # Fallback: tkinter on Linux/Windows. Requires a display.
    try:
        import tkinter
        from tkinter import filedialog
    except Exception as exc:
        return {"success": False, "error": f"native picker unavailable: {exc}"}
    try:
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(initialdir=initial_dir, title="Select a folder")
        root.destroy()
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    if not path:
        return {"success": True, "canceled": True}
    return {"success": True, "path": path}


def _load_installer_module():
    """Lazy-import install.py from the repo root. Returns (module, error)."""
    try:
        sys.path.insert(0, _repo_root())
        import importlib
        if "install" in sys.modules:
            return importlib.reload(sys.modules["install"]), None
        import install  # type: ignore
        return install, None
    except Exception as exc:
        return None, f"installer module unavailable: {exc}"


def _resolve_mcp_paths() -> Dict[str, Any]:
    """Return the paths needed to write an MCP client config:
    python_path, server_path, api_path, lib_path. Each may be None.
    """
    installer, error = _load_installer_module()
    repo = _repo_root()
    # Server entrypoint — same one the installer wires up.
    server_path = os.path.join(repo, "src", "resolve_mcp_server.py")
    # Prefer the repo venv python so the configured client launches the
    # MCP server with all dependencies available.
    candidates = [
        os.path.join(repo, "venv", "bin", "python"),
        os.path.join(repo, "venv", "Scripts", "python.exe"),
        os.path.join(repo, ".venv", "bin", "python"),
    ]
    python_path = next((c for c in candidates if os.path.isfile(c)), None)
    if not python_path:
        python_path = sys.executable
    api_path = lib_path = None
    if installer is not None:
        try:
            api_path, lib_path = installer.find_resolve_paths()
        except Exception:
            pass
    return {
        "python_path": str(python_path) if python_path else None,
        "server_path": str(server_path) if os.path.isfile(server_path) else None,
        "api_path": str(api_path) if api_path else None,
        "lib_path": str(lib_path) if lib_path else None,
        "installer_error": error,
    }


def _mcp_status_payload() -> Dict[str, Any]:
    """Return MCP server identity + per-client install status."""
    installer, error = _load_installer_module()
    paths = _resolve_mcp_paths()
    clients_out: List[Dict[str, Any]] = []
    if installer is None:
        return {
            "success": False,
            "error": error or "installer unavailable",
            "server": {
                "version": _mcp_version(),
                "python_path": paths.get("python_path"),
                "server_path": paths.get("server_path"),
            },
            "clients": [],
        }
    for client in getattr(installer, "MCP_CLIENTS", []):
        try:
            config_path = client["get_path"]()
        except Exception:
            config_path = None
        config_key = client.get("config_key", "mcpServers")
        available = config_path is not None
        installed = False
        entry: Any = None
        if available and config_path and os.path.isfile(str(config_path)):
            try:
                existing = installer.read_json(str(config_path))
                entry = (existing.get(config_key) or {}).get("davinci-resolve")
                installed = bool(entry)
            except Exception:
                installed = False
        clients_out.append({
            "id": client["id"],
            "name": client["name"],
            "notes": client.get("notes", ""),
            "config_path": str(config_path) if config_path else None,
            "config_key": config_key,
            "available": bool(available),
            "installed": bool(installed),
        })
    return {
        "success": True,
        "server": {
            "version": _mcp_version(),
            "python_path": paths.get("python_path"),
            "server_path": paths.get("server_path"),
            "resolve_api_path": paths.get("api_path"),
            "resolve_lib_path": paths.get("lib_path"),
            "resolve_api_detected": bool(paths.get("api_path")),
            "resolve_lib_detected": bool(paths.get("lib_path")),
        },
        "clients": clients_out,
        "transport": _transport_status(),
    }


def _transport_status() -> Dict[str, Any]:
    """Live networked-transport status (or local-only) for the MCP diagnostics card."""
    try:
        from src.utils.mcp_transport import read_transport_state
    except Exception:
        return {"networked": False, "mode": "stdio (local)"}
    state = read_transport_state()
    if not state:
        return {"networked": False, "mode": "stdio (local)"}
    return {
        "networked": True,
        "mode": state.get("transport"),
        "url": state.get("url"),
        "loopback": state.get("loopback", True),
        "has_token": bool(state.get("token")),
        "token": state.get("token"),
        "pid": state.get("pid"),
    }


def _transport_start() -> Dict[str, Any]:
    """Spawn a networked MCP instance (streamable-http, loopback + token)."""
    import subprocess as _sp
    from src.utils.mcp_transport import read_transport_state
    if read_transport_state():
        return {"success": False, "error": "A networked transport instance is already running."}
    paths = _resolve_mcp_paths()
    py, script = paths.get("python_path"), paths.get("server_path")
    if not py or not script:
        return {"success": False, "error": "Could not resolve the Python interpreter or server script path."}
    try:
        _sp.Popen(
            [py, script, "--transport", "streamable-http"],
            stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return {"success": False, "error": f"Failed to launch: {exc}"}
    import time as _t
    for _ in range(15):
        _t.sleep(0.2)
        if read_transport_state():
            return {"success": True, "transport": _transport_status()}
    return {"success": True, "note": "Launch initiated; status will appear shortly."}


def _transport_stop() -> Dict[str, Any]:
    """Stop the running networked MCP instance via its state-file PID."""
    import signal as _sig
    from src.utils.mcp_transport import read_transport_state, clear_transport_state
    state = read_transport_state()
    if not state:
        return {"success": True, "note": "No networked transport running."}
    pid = state.get("pid")
    if isinstance(pid, int):
        try:
            os.kill(pid, _sig.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
    clear_transport_state()
    return {"success": True}


def _mcp_install_payload(client_id: str) -> Dict[str, Any]:
    """Write the MCP entry for one client by delegating to install.write_client_config."""
    installer, error = _load_installer_module()
    if installer is None:
        return {"success": False, "error": error or "installer unavailable"}
    target = next((c for c in installer.MCP_CLIENTS if c["id"] == client_id), None)
    if not target:
        return {"success": False, "error": f"unknown client: {client_id}"}
    paths = _resolve_mcp_paths()
    if not paths.get("server_path"):
        return {"success": False, "error": "MCP server script not found in repo"}
    if not paths.get("python_path"):
        return {"success": False, "error": "Python interpreter not found"}
    if not paths.get("api_path") or not paths.get("lib_path"):
        return {
            "success": False,
            "error": "Resolve scripting API / library paths could not be auto-detected. Open Resolve Studio at least once or install via install.py.",
        }
    try:
        ok, message = installer.write_client_config(
            target,
            paths["python_path"],
            paths["server_path"],
            paths["api_path"],
            paths["lib_path"],
            dry_run=False,
        )
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {"success": bool(ok), "message": message, "client_id": client_id}


def _mcp_uninstall_payload(client_id: str) -> Dict[str, Any]:
    """Remove the davinci-resolve entry from a client's config file."""
    installer, error = _load_installer_module()
    if installer is None:
        return {"success": False, "error": error or "installer unavailable"}
    target = next((c for c in installer.MCP_CLIENTS if c["id"] == client_id), None)
    if not target:
        return {"success": False, "error": f"unknown client: {client_id}"}
    try:
        config_path = target["get_path"]()
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    if not config_path or not os.path.isfile(str(config_path)):
        return {"success": True, "message": "Nothing to remove (config file does not exist).", "client_id": client_id}
    config_key = target.get("config_key", "mcpServers")
    try:
        existing = installer.read_json(str(config_path))
        servers = existing.get(config_key) or {}
        if "davinci-resolve" not in servers:
            return {"success": True, "message": "Nothing to remove (entry not present).", "client_id": client_id}
        del servers["davinci-resolve"]
        if servers:
            existing[config_key] = servers
        else:
            existing.pop(config_key, None)
        installer.write_json(str(config_path), existing)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "message": f"Removed davinci-resolve from {config_path}", "client_id": client_id}


def _list_active_batch_jobs(project_root: str) -> List[Dict[str, Any]]:
    """Across the analysis base root, find batch jobs with status='running'.

    Used by the update apply path: refuse to update mid-job because it would
    corrupt in-flight clip analysis state (the new build's schema may not match
    what the running batch was started against).
    """
    out: List[Dict[str, Any]] = []
    if not project_root:
        return out
    base = os.path.dirname(os.path.normpath(project_root))
    if not os.path.isdir(base):
        return out
    for entry in sorted(os.listdir(base)):
        candidate = os.path.join(base, entry)
        if not os.path.isdir(candidate):
            continue
        try:
            payload = list_batch_jobs(candidate, limit=200)
        except Exception:
            continue
        for job in payload.get("jobs") or []:
            if (job.get("status") or "").lower() == "running":
                out.append({
                    "project_root": candidate,
                    "job_id": job.get("job_id"),
                    "status": job.get("status"),
                    "started_at": job.get("started_at"),
                })
    return out


def _update_apply_payload(*, strategy: str = "refuse_on_dirty", force_active_jobs: bool = False,
                          project_root: Optional[str] = None) -> Dict[str, Any]:
    """Apply a guarded git fast-forward update by delegating to install.py's
    existing apply_safe_self_update. Returns a structured result for the UI.
    """
    # Active-job lock — refuse to update if a batch analysis job is mid-flight.
    # Pass force_active_jobs=true to override (the user explicitly accepts the
    # risk of in-flight state being inconsistent with the new build).
    if not force_active_jobs and project_root:
        active = _list_active_batch_jobs(project_root)
        if active:
            return {
                "success": False,
                "reason": "active_jobs",
                "message": f"{len(active)} batch analysis job(s) are currently running. Cancel them or pass force=true to override.",
                "active_jobs": active,
            }
    try:
        sys.path.insert(0, _repo_root())
        from install import apply_safe_self_update  # type: ignore
    except Exception as exc:
        return {"success": False, "error": f"update helper unavailable: {exc}"}
    try:
        result = apply_safe_self_update(_repo_root(), dry_run=False, initiator="dashboard", strategy=strategy)
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    out: Dict[str, Any] = {
        "success": bool(result.get("success")),
        "changed": bool(result.get("changed")),
        "reason": result.get("reason"),
        "message": result.get("message"),
        "current_version": _mcp_version(),
        "from_version": result.get("from_version"),
        "to_version": result.get("to_version"),
        "from_sha": result.get("from_sha"),
        "to_sha": result.get("to_sha"),
    }
    if result.get("success") and result.get("changed"):
        out["restart_required"] = True
        # Eagerly migrate per-project DBs so schema bumps in the new build
        # surface immediately instead of waiting for the next analysis call.
        out["db_migrations"] = _eager_migrate_after_update(project_root)
        # Drop a restart-needed marker the host / dashboard can poll for.
        _write_restart_marker(_repo_root(), result)
    # Surface stash status on the result.
    for k in ("stash_ref", "stash_pop_conflict", "remediation"):
        if k in result and result[k] is not None:
            out[k] = result[k]
    return out


def _write_restart_marker(repo_root: str, update_result: Dict[str, Any]) -> None:
    """Drop a `.mcp_restart_needed` marker file with update metadata.

    The MCP server is a child process of the host (Claude Code, etc.) so we
    can't restart it ourselves. The marker is a hint the host can poll via
    `/api/restart_needed` or by reading the file directly.
    """
    log_dir = os.path.join(repo_root, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        marker = {
            "needed": True,
            "from_version": update_result.get("from_version"),
            "to_version": update_result.get("to_version"),
            "from_sha": update_result.get("from_sha"),
            "to_sha": update_result.get("to_sha"),
            "applied_at": _now_iso_safe(),
        }
        with open(os.path.join(log_dir, ".mcp_restart_needed"), "w", encoding="utf-8") as fh:
            json.dump(marker, fh, indent=2)
    except OSError:
        pass


def _now_iso_safe() -> str:
    import time as _time
    return _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())


def _read_restart_marker(repo_root: str) -> Dict[str, Any]:
    path = os.path.join(repo_root, "logs", ".mcp_restart_needed")
    if not os.path.isfile(path):
        return {"needed": False}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if isinstance(payload, dict):
            payload.setdefault("needed", True)
            return payload
    except (OSError, json.JSONDecodeError):
        pass
    return {"needed": True, "marker_path": path}


def _clear_restart_marker(repo_root: str) -> Dict[str, Any]:
    path = os.path.join(repo_root, "logs", ".mcp_restart_needed")
    try:
        os.remove(path)
    except OSError:
        return {"success": False, "error": "marker not present or unreadable"}
    return {"success": True}


def _eager_migrate_after_update(project_root: Optional[str] = None) -> Dict[str, Any]:
    """Walk every project under the analysis base root and open + migrate its
    timeline_brain.sqlite. Surfaces schema bumps from the new build right after
    `git pull` instead of on next per-project work."""
    if project_root:
        base = os.path.dirname(os.path.normpath(project_root))
    else:
        base = os.path.expanduser("~/Documents/davinci-resolve-mcp-analysis")
    migrated: List[Dict[str, Any]] = []
    if not os.path.isdir(base):
        return {"success": True, "migrated": migrated, "note": "no base root found"}
    for entry in sorted(os.listdir(base)):
        candidate = os.path.join(base, entry)
        if not os.path.isdir(os.path.join(candidate, "_soul")):
            continue
        try:
            _timeline_brain_db.connect(candidate)
            migrated.append({"project_root": candidate, "ok": True})
        except Exception as exc:
            migrated.append({"project_root": candidate, "ok": False, "error": str(exc)})
    return {"success": True, "migrated": migrated}


def _update_rollback_payload() -> Dict[str, Any]:
    try:
        sys.path.insert(0, _repo_root())
        from install import rollback_to_previous_build  # type: ignore
    except Exception as exc:
        return {"success": False, "error": f"rollback helper unavailable: {exc}"}
    try:
        result = rollback_to_previous_build(_repo_root(), initiator="dashboard")
    except Exception as exc:
        return {"success": False, "error": str(exc)}
    out: Dict[str, Any] = dict(result)
    out["current_version"] = _mcp_version()
    if result.get("success"):
        out["restart_required"] = True
    return out


def _update_history_payload(limit: int = 20) -> Dict[str, Any]:
    try:
        sys.path.insert(0, _repo_root())
        from install import read_update_history  # type: ignore
    except Exception as exc:
        return {"success": False, "error": f"history helper unavailable: {exc}", "entries": []}
    try:
        return read_update_history(_repo_root(), limit=limit)
    except Exception as exc:
        return {"success": False, "error": str(exc), "entries": []}


def _update_preview_payload() -> Dict[str, Any]:
    """Render the about-to-apply update for user confirmation.

    Returns release notes, flagged breaking changes, channel, prerelease flag,
    and the target SHA so the dashboard can show a meaningful modal before
    `git pull` actually runs.
    """
    try:
        sys.path.insert(0, _repo_root())
        from install import preview_update  # type: ignore
    except Exception as exc:
        return {"success": False, "error": f"preview helper unavailable: {exc}"}
    try:
        return preview_update(_repo_root())
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _update_status_payload(project_root: Optional[str], *, force: bool = False) -> Dict[str, Any]:
    current = _mcp_version()
    base = {
        "success": True,
        "current_version": current,
        "update_available": False,
        "status": "unknown",
    }
    # Always use the repo root, not the analysis project root — that's where the
    # MCP server's startup check writes its state file, so dashboard and server
    # share cache instead of running independent checks.
    update_project_dir = _repo_root()
    try:
        from src.utils.update_check import (
            check_for_updates,
            get_cached_update_status,
        )
    except Exception as exc:
        base["error"] = f"update check unavailable: {exc}"
        return base
    try:
        if force:
            payload = check_for_updates(current, update_project_dir, force=True)
        else:
            payload = get_cached_update_status(update_project_dir, current_version=current)
            # Cache miss → run a real check now so the UI gets a useful answer
            # on first load instead of "hasn't run yet".
            if isinstance(payload, dict) and payload.get("status") == "unknown":
                payload = check_for_updates(current, update_project_dir)
    except Exception as exc:
        base["error"] = str(exc)
        return base
    if not isinstance(payload, dict):
        return base
    status = str(payload.get("status") or "unknown")
    latest = payload.get("latest_version") or payload.get("latest")
    update_available = status == "update_available"
    return {
        "success": True,
        "current_version": current,
        "latest_version": str(latest) if latest else None,
        "status": status,
        "update_available": bool(update_available),
        "checked_at": payload.get("checked_at_iso") or payload.get("checked_at"),
        "snooze_until": payload.get("snooze_until_iso") or payload.get("snooze_until"),
        "update_mode": payload.get("update_mode"),
        "release_url": payload.get("release_url") or payload.get("html_url"),
        "release_notes": payload.get("release_notes") or payload.get("body"),
    }


def _dashboard_doc(doc_id: Any) -> Dict[str, Any]:
    key = str(doc_id or "readme")
    source = DOC_SOURCES.get(key)
    if not source:
        return {"success": False, "error": "Unknown document"}
    repo_root = _repo_root()
    rel_path = str(source["path"])
    path = os.path.abspath(os.path.join(repo_root, rel_path))
    if not path.startswith(repo_root + os.sep):
        return {"success": False, "error": "Document path escaped repository root"}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
    except OSError as exc:
        return {"success": False, "error": str(exc)}
    return {
        "success": True,
        "doc": key,
        "title": source["title"],
        "path": rel_path,
        "content": content,
    }


def _setup_defaults(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from src.server import setup as server_setup

    return server_setup(action, params or {})


def _inventory_prefs() -> Tuple[int, Optional[set]]:
    """Return (limit, exclude_bins) for the inventory walk from media-analysis
    preferences. ``exclude_bins`` is None when nothing is configured, so the walk
    indexes every folder by default."""
    try:
        from src.server import _media_analysis_effective_preferences

        prefs = _media_analysis_effective_preferences()
    except Exception:  # noqa: BLE001 — fall back to built-in defaults
        prefs = {}
    try:
        limit = max(1, min(int(prefs.get("inventory_limit", 500)), 10000))
    except (TypeError, ValueError):
        limit = 500
    raw = prefs.get("inventory_exclude_bins")
    exclude = {part.strip() for part in str(raw).split(",") if part.strip()} if raw else None
    return limit, (exclude or None)


class Handler(BaseHTTPRequestHandler):
    state: DashboardState

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _json(self, payload: Dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _json_etag(self, payload: Dict[str, Any]) -> None:
        """JSON response with an ETag so unchanged polls short-circuit to 304.

        The Resolve media inventory is re-fetched every few seconds; when the
        serialized payload is byte-identical to what the client already holds we
        skip both the body transfer and the client-side re-render of the table.
        """
        raw = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        etag = '"' + hashlib.md5(raw).hexdigest() + '"'
        if self.headers.get("If-None-Match") == etag:
            tiny = json.dumps({"success": True, "unchanged": True, "etag": etag}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(tiny)))
            self.send_header("ETag", etag)
            self.end_headers()
            self.wfile.write(tiny)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("ETag", etag)
        self.end_headers()
        self.wfile.write(raw)

    def _serve_file(self, path: str, content_type: str = "application/octet-stream") -> None:
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
        except OSError:
            self._json({"success": False, "error": "File not found"}, HTTPStatus.NOT_FOUND)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "private, max-age=300")
        self.end_headers()
        self.wfile.write(raw)

    def _html(self) -> None:
        raw = HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _serve_clip_export(self, body: Dict[str, Any]) -> None:
        clip_ids = body.get("clip_ids")
        fmt = body.get("format") or "json"
        if not isinstance(clip_ids, list) or not clip_ids:
            self._json({"success": False, "error": "clip_ids must be a non-empty list"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            raw, content_type, filename = export_clip_selection(self.state.project_root, list(clip_ids), str(fmt))
        except Exception as exc:  # noqa: BLE001
            self._json({"success": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def do_GET(self) -> None:
        try:
            self._route_get()
        except Exception as exc:  # pragma: no cover - runtime safety for dashboard users
            self._json({"success": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        try:
            self._route_post()
        except Exception as exc:  # pragma: no cover
            self._json({"success": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _route_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/":
            self._html()
            return
        if path == "/api/boot":
            self._json(
                {
                    "success": True,
                    "project_name": self.state.project_name,
                    "project_id": self.state.project_id,
                    "project_root": self.state.project_root,
                    "repo_root": _repo_root(),
                    "codex_workspace": _repo_root(),
                    "output_root": self.state.output_root,
                    "active_context": self.state.context(),
                    "related_project_roots": self.state.related_project_roots(),
                    "capabilities": detect_capabilities(),
                    "resolve": _resolve_identity(),
                    "mcp_version": _mcp_version(),
                }
            )
            return
        if path == "/api/projects":
            self._json(self.state.projects())
            return
        if path == "/api/update/status":
            force = (query.get("force") or ["0"])[0].lower() in {"1", "true", "yes"}
            self._json(_update_status_payload(self.state.project_root, force=force))
            return
        if path == "/api/update/history":
            try:
                limit = int((query.get("limit") or ["20"])[0])
            except (TypeError, ValueError):
                limit = 20
            self._json(_update_history_payload(limit=limit))
            return
        if path == "/api/restart_needed":
            self._json(_read_restart_marker(_repo_root()))
            return
        if path == "/api/update/preview":
            self._json(_update_preview_payload())
            return
        if path == "/api/mcp/status":
            self._json(_mcp_status_payload())
            return
        if path == "/api/projects/all":
            self._json(_resolve_all_project_contexts(self.state.base_analysis_root))
            return
        if path == "/api/jobs":
            self._json(list_batch_jobs(self.state.project_root))
            return
        if path == "/api/docs":
            doc = (query.get("doc") or ["readme"])[0]
            payload = _dashboard_doc(doc)
            self._json(payload, 200 if payload.get("success") else 404)
            return
        if path.startswith("/api/doc_asset/"):
            rel = unquote(path[len("/api/doc_asset/"):])
            base = os.path.realpath(os.path.join(_repo_root(), "docs", "images"))
            full = os.path.realpath(os.path.join(base, rel))
            if not (full.startswith(base + os.sep) or full == base):
                self._json({"success": False, "error": "path escape"}, HTTPStatus.FORBIDDEN)
                return
            content_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                             ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp"}
            ext = os.path.splitext(full)[1].lower()
            if ext not in content_types or not os.path.isfile(full):
                self._json({"success": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            self._serve_file(full, content_types[ext])
            return
        if path == "/api/setup/schema":
            self._json(_setup_defaults("schema"))
            return
        if path == "/api/setup/defaults":
            self._json(_setup_defaults("get_defaults"))
            return
        if path == "/api/resolve/media":
            pref_limit, exclude_bins = _inventory_prefs()
            self._json_etag(
                resolve_media_inventory(
                    self.state.project_root,
                    limit=(query.get("limit") or [pref_limit])[0],
                    exclude_bins=exclude_bins,
                    recursive=(query.get("recursive") or ["true"])[0].lower() not in {"0", "false", "no"},
                    probe_paths=(query.get("probe") or ["1"])[0].lower() not in {"0", "false", "no"},
                    reuse_cached=(query.get("reuse") or ["0"])[0].lower() in {"1", "true", "yes"},
                )
            )
            return
        if path.startswith("/api/jobs/"):
            job_id = path.split("/")[3]
            self._json(batch_job_status(self.state.project_root, job_id))
            return
        if path == "/api/index/status":
            self._json(analysis_index_status(self.state.project_root))
            return
        if path == "/api/coverage":
            # Standalone readiness rollup — no live Resolve required. The
            # `coverage_report` action gives target-vs-records detail; this
            # endpoint summarizes what the analysis directory already knows.
            self._json(analysis_root_coverage(self.state.project_root))
            return
        if path == "/api/index/query":
            q = (query.get("q") or [""])[0]
            payload = query_analysis_index(self.state.project_root, q, limit=(query.get("limit") or [20])[0])
            if payload.get("success") and payload.get("results"):
                payload["results"] = _v2_enrich_search_results(self.state.project_root, payload["results"])
            self._json(payload)
            return
        if path == "/api/entities":
            try:
                from src.utils import entities as _entities

                self._json(_entities.list_entities(self.state.project_root))
            except Exception as exc:  # noqa: BLE001 — panel reads fail soft
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/search/semantic":
            q = (query.get("q") or [""])[0]
            try:
                limit = int((query.get("limit") or ["20"])[0])
            except (TypeError, ValueError):
                limit = 20
            self._json(_v2_semantic_search(self.state.project_root, q, limit=limit))
            return
        # ─── C6 timeline-history surface ───────────────────────────────
        if path == "/api/timeline_versions":
            self._json(list_timelines_with_versions(self.state.project_root))
            return
        if path == "/api/timeline_versions/diff":
            timeline_name = (query.get("timeline_name") or [""])[0]
            try:
                from_version = int((query.get("from_version") or [""])[0])
                to_version = int((query.get("to_version") or [""])[0])
            except (ValueError, TypeError):
                self._json({"success": False, "error": "from_version and to_version (ints) required"},
                           HTTPStatus.BAD_REQUEST)
                return
            if not timeline_name:
                self._json({"success": False, "error": "timeline_name required"}, HTTPStatus.BAD_REQUEST)
                return
            self._json({"success": True, **_timeline_versioning.diff_versions(
                project_root=self.state.project_root,
                timeline_name=timeline_name,
                from_version=from_version,
                to_version=to_version,
            )})
            return
        if path.startswith("/api/timeline_versions/"):
            timeline_name = unquote(path[len("/api/timeline_versions/"):])
            if not timeline_name:
                self._json({"success": False, "error": "timeline_name required"}, HTTPStatus.BAD_REQUEST)
                return
            self._json(get_timeline_history_payload(self.state.project_root, timeline_name))
            return
        # ─── Edit-engine plan browser (DB/file only — no Resolve) ───────
        if path == "/api/edit_plans":
            self._json(list_edit_plans_payload(self.state.project_root))
            return
        if path.startswith("/api/edit_plans/"):
            plan_id = unquote(path[len("/api/edit_plans/"):])
            if not plan_id:
                self._json({"success": False, "error": "plan_id required"}, HTTPStatus.BAD_REQUEST)
                return
            payload = get_edit_plan_payload(self.state.project_root, plan_id)
            if not payload.get("success") and "not found" in str(payload.get("error", "")):
                self._json(payload, HTTPStatus.NOT_FOUND)
                return
            self._json(payload)
            return
        if path == "/api/brain_edits/registry":
            self._json({"success": True, **_brain_edits.read_brain_edits_registry(self.state.project_root)})
            return
        if path == "/api/caps/history":
            try:
                from src.utils import analysis_caps as _ac
                days = int((query.get("days") or ["30"])[0])
                self._json({
                    "success": True,
                    "history": _ac.get_usage_history(project_root=self.state.project_root, days=days),
                })
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/caps/refusals":
            try:
                from src.utils import analysis_caps as _ac
                limit = int((query.get("limit") or ["20"])[0])
                self._json({
                    "success": True,
                    "events": _ac.get_caps_events(
                        project_root=self.state.project_root,
                        event_type=(query.get("event_type") or ["refusal"])[0] or "refusal",
                        limit=limit,
                    ),
                })
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/media_pool_changes":
            try:
                from src.utils import media_pool_changes as _mpc
                limit = int((query.get("limit") or ["50"])[0])
                self._json({
                    "success": True,
                    "changes": _mpc.get_media_pool_change_history(
                        project_root=self.state.project_root, limit=limit,
                    ),
                })
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/runs":
            try:
                from src.utils import analysis_runs as _ar
                limit = int((query.get("limit") or ["50"])[0])
                self._json({
                    "success": True,
                    "runs": _ar.list_runs(project_root=self.state.project_root, limit=limit),
                    "current_run_id": _ar.current_run_id(),
                })
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/caps":
            # Effective caps + per-project usage rollup. Proxies into the
            # media_analysis tool's get_caps action which already does the
            # preference lookup + DB rollup.
            try:
                from src.server import media_analysis as _ma_tool
                import asyncio
                result = asyncio.run(_ma_tool("get_caps", params={}))
                self._json(result)
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/resolve_ai_usage":
            # Ledger of Resolve-local 21.0 AI ops (read straight from this
            # project's brain DB — no Resolve round-trip needed).
            try:
                from src.utils import resolve_ai_ledger as _ledger
                root = self.state.project_root
                self._json({
                    "success": True,
                    "summary": _ledger.get_summary(project_root=root),
                    "recent": _ledger.get_usage(project_root=root, limit=50),
                })
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/resolve_ai/governance":
            # Effective governance tier + this project's render usage. Proxies
            # into the media_analysis get_ai_governance action.
            try:
                from src.server import media_analysis as _ma_tool
                import asyncio
                self._json(asyncio.run(_ma_tool("get_ai_governance", params={})))
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path.startswith("/api/timeline_thumbnail/"):
            rel = unquote(path[len("/api/timeline_thumbnail/"):])
            # Path is <slug>/<vNN.png>; constrain it to live under _soul/timeline_versions
            base = os.path.join(self.state.project_root, "_soul", "timeline_versions")
            full = os.path.realpath(os.path.join(base, rel))
            if not full.startswith(os.path.realpath(base) + os.sep) and full != os.path.realpath(base):
                self._json({"success": False, "error": "path escape"}, HTTPStatus.FORBIDDEN)
                return
            if not os.path.isfile(full):
                self._json({"success": False, "error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            try:
                with open(full, "rb") as fh:
                    data = fh.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError as exc:
                self._json({"success": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        # ─── V2 Review API ──────────────────────────────────────────────
        if path == "/api/clips":
            self._json(list_analyzed_clips(self.state.project_root))
            return
        if path == "/api/panel_state":
            state_payload = read_panel_state(self.state.project_root) or {}
            self._json({"success": True, "state": state_payload})
            return
        if path.startswith("/api/clips/"):
            parts = path.split("/")
            # /api/clips/<clip_id>  → parts = ["", "api", "clips", "<id>"]
            if len(parts) >= 4:
                clip_id = parts[3]
                tail = parts[4:]
                if not tail:
                    self._json(get_analyzed_clip(self.state.project_root, clip_id))
                    return
                if tail == ["shots"]:
                    self._json(get_analyzed_clip_shots(self.state.project_root, clip_id))
                    return
                if tail == ["transcript"]:
                    self._json(get_analyzed_clip_transcript(self.state.project_root, clip_id))
                    return
                if len(tail) == 2 and tail[0] == "shots":
                    try:
                        shot_index = int(tail[1])
                    except ValueError:
                        self._json({"success": False, "error": "shot_index must be an integer"}, HTTPStatus.BAD_REQUEST)
                        return
                    self._json(get_analyzed_clip_shot(self.state.project_root, clip_id, shot_index))
                    return
                if len(tail) == 2 and tail[0] == "frames":
                    try:
                        frame_index = int(tail[1])
                    except ValueError:
                        self._json({"success": False, "error": "frame_index must be an integer"}, HTTPStatus.BAD_REQUEST)
                        return
                    frame_path = get_clip_frame_path(self.state.project_root, clip_id, frame_index)
                    if not frame_path:
                        self._json({"success": False, "error": f"Frame {frame_index} not found for clip {clip_id}"}, HTTPStatus.NOT_FOUND)
                        return
                    self._serve_file(frame_path, content_type="image/jpeg")
                    return
                if tail == ["corrections"]:
                    self._json(read_clip_corrections(self.state.project_root, clip_id))
                    return
        self._json({"success": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)

    def _route_post(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._body()
        if path == "/api/browse/directory":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Native folder picker is only available to loopback clients."}, HTTPStatus.FORBIDDEN)
                return
            initial = body.get("initial") or body.get("current") or None
            self._json(_native_directory_picker(initial=str(initial) if initial else None))
            return
        if path == "/api/launch/claude-code":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Terminal launch is loopback-only."}, HTTPStatus.FORBIDDEN)
                return
            self._json(_launch_claude_code_terminal())
            return
        if path == "/api/update/apply":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Self-update is only available to loopback clients."}, HTTPStatus.FORBIDDEN)
                return
            strategy = (body.get("strategy") or "refuse_on_dirty").strip().lower()
            if strategy not in {"refuse_on_dirty", "stash_if_needed"}:
                strategy = "refuse_on_dirty"
            force_active_jobs = bool(body.get("force_active_jobs") or body.get("force"))
            self._json(_update_apply_payload(
                strategy=strategy,
                force_active_jobs=force_active_jobs,
                project_root=self.state.project_root,
            ))
            return
        if path == "/api/restart_needed/clear":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Loopback only."}, HTTPStatus.FORBIDDEN)
                return
            self._json(_clear_restart_marker(_repo_root()))
            return
        if path == "/api/update/rollback":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Rollback is only available to loopback clients."}, HTTPStatus.FORBIDDEN)
                return
            self._json(_update_rollback_payload())
            return
        if path.startswith("/api/clips/") and path.endswith("/transcript/regenerate"):
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Transcript regeneration is loopback-only."}, HTTPStatus.FORBIDDEN)
                return
            clip_id = path.split("/")[3]
            # Serialize the analysis.json read-modify-write: this server is
            # threaded, so concurrent regenerations (or a regen racing a batch
            # job's report write) would interleave and the last writer would drop
            # the other's updates (PS9).
            with self.state.lock:
                result = regenerate_clip_transcript(
                    self.state.project_root,
                    clip_id,
                    with_words=bool(body.get("with_words", True)),
                    backend=body.get("backend") or None,
                    language=body.get("language") or None,
                    model=body.get("model") or None,
                )
            self._json(result)
            return
        if path.startswith("/api/clips/") and path.endswith("/transcript/corrections"):
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Transcript edits are loopback-only."}, HTTPStatus.FORBIDDEN)
                return
            clip_id = path.split("/")[3]
            self._json(save_clip_transcript_corrections(self.state.project_root, clip_id, body))
            return
        if path == "/api/mcp/install":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "MCP install routes are loopback-only."}, HTTPStatus.FORBIDDEN)
                return
            client_id = str(body.get("client_id") or "").strip()
            if not client_id:
                self._json({"success": False, "error": "client_id is required"}, HTTPStatus.BAD_REQUEST)
                return
            self._json(_mcp_install_payload(client_id))
            return
        if path == "/api/mcp/uninstall":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "MCP install routes are loopback-only."}, HTTPStatus.FORBIDDEN)
                return
            client_id = str(body.get("client_id") or "").strip()
            if not client_id:
                self._json({"success": False, "error": "client_id is required"}, HTTPStatus.BAD_REQUEST)
                return
            self._json(_mcp_uninstall_payload(client_id))
            return
        if path == "/api/mcp/transport/start":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Transport management is loopback-only."}, HTTPStatus.FORBIDDEN)
                return
            self._json(_transport_start())
            return
        if path == "/api/mcp/transport/stop":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Transport management is loopback-only."}, HTTPStatus.FORBIDDEN)
                return
            self._json(_transport_stop())
            return
        if path == "/api/jobs":
            paths = body.get("paths") or []
            if isinstance(paths, str):
                paths = [line.strip() for line in paths.splitlines() if line.strip()]
            params = {
                "depth": body.get("depth") or "standard",
                "max_analysis_frames": body.get("max_analysis_frames", 8),
                "vision": body.get("vision") or {"enabled": False},
                "transcription": body.get("transcription") or {"enabled": True, "allow_model_download": True},
                "cleanup_frames": True,
                "reuse_project_roots": self.state.related_project_roots(),
            }
            # Honor the saved frame-sampling mode (or an explicit per-job override)
            # so batch runs match the user's chosen coverage/cost. Falls back to the
            # recommended mode when the user hasn't set a default yet (batch jobs
            # shouldn't block on the first-run prompt).
            try:
                from src.server import (
                    _media_analysis_effective_preferences as _ma_eff_prefs,
                )
                from src.utils import media_analysis as _ma_mod
                _ma_prefs = _ma_eff_prefs()
                params["sampling_mode"] = (
                    body.get("sampling_mode")
                    or _ma_prefs.get("sampling_mode_default")
                    or _ma_mod.RECOMMENDED_SAMPLING_MODE
                )
                params["frames_per_minute"] = body.get("frames_per_minute") or _ma_prefs.get("sampling_frames_per_minute")
                params["frame_floor"] = body.get("frame_floor") or _ma_prefs.get("sampling_frame_floor")
                params["frame_ceiling"] = body.get("frame_ceiling") or _ma_prefs.get("sampling_frame_ceiling")
            except Exception:
                # Best-effort; the engine still applies its own defaults.
                pass
            with self.state.lock:
                created = create_batch_job_from_paths(
                    project_name=self.state.project_name,
                    project_id=self.state.project_id,
                    paths=paths,
                    analysis_root=self.state.output_root["base_root"],
                    recursive=bool(body.get("recursive", True)),
                    params=params,
                    name=body.get("name"),
                )
            self._json(created, 200 if created.get("success") else 400)
            return
        if path.startswith("/api/jobs/") and path.endswith("/run"):
            job_id = path.split("/")[3]
            with self.state.lock:
                result = run_batch_job_slice(
                    self.state.project_root,
                    job_id,
                    max_clips=body.get("max_clips", 1),
                    max_seconds=body.get("max_seconds"),
                )
            self._json(result, 200 if result.get("success") else 400)
            return
        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            job_id = path.split("/")[3]
            self._json(cancel_batch_job(self.state.project_root, job_id))
            return
        if path.startswith("/api/jobs/") and path.endswith("/resume"):
            job_id = path.split("/")[3]
            self._json(resume_batch_job(self.state.project_root, job_id))
            return
        if path == "/api/index/build":
            with self.state.lock:
                self._json(build_analysis_index(self.state.project_root))
            return
        if path == "/api/setup/defaults":
            payload = _setup_defaults("set_defaults", body)
            self._json(payload, 200 if payload.get("success") else 400)
            return
        if path == "/api/setup/clear":
            payload = _setup_defaults("clear_defaults", body)
            self._json(payload, 200 if payload.get("success") else 400)
            return
        if path == "/api/context":
            with self.state.lock:
                payload = self.state.set_context(body)
            self._json(payload, 200 if payload.get("success") else 400)
            return
        # ─── C6 timeline-history write actions (loopback only) ─────────
        if path == "/api/timeline_versions/action":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Timeline versioning writes are loopback-only."}, HTTPStatus.FORBIDDEN)
                return
            self._json(proxy_timeline_versioning_action(body))
            return
        if path == "/api/caps":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Caps writes are loopback-only."}, HTTPStatus.FORBIDDEN)
                return
            try:
                from src.server import media_analysis as _ma_tool
                import asyncio
                result = asyncio.run(_ma_tool("set_caps_preset", params=body))
                self._json(result, 200 if result.get("success") else 400)
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/resolve_ai/run":
            # Run a Resolve 21 AI op from the panel. Loopback-only because it
            # mutates Resolve (and the media-creators write new files). The
            # confirm-token two-step is handled by the consolidated tool; the
            # 'confirmation_required' shape is relayed to the panel as 200.
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Loopback only."}, HTTPStatus.FORBIDDEN)
                return
            try:
                result = _run_resolve_ai_op(body)
                ok = bool(result.get("success")) or result.get("status") == "confirmation_required"
                self._json(result, 200 if ok else 400)
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/resolve_ai/governance":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Loopback only."}, HTTPStatus.FORBIDDEN)
                return
            try:
                from src.server import media_analysis as _ma_tool
                import asyncio
                result = asyncio.run(_ma_tool("set_ai_governance", params=body))
                self._json(result, 200 if result.get("success") else 400)
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/caps/reset_day":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Loopback only."}, HTTPStatus.FORBIDDEN)
                return
            try:
                from src.utils import analysis_caps as _ac
                result = _ac.reset_day_usage(
                    project_root=self.state.project_root,
                    day_bucket=body.get("day_bucket"),
                )
                self._json(result)
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/runs/begin":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Loopback only."}, HTTPStatus.FORBIDDEN)
                return
            try:
                from src.utils import analysis_runs as _ar
                result = _ar.begin_run(
                    project_root=self.state.project_root,
                    label=body.get("label"),
                    initiator=body.get("initiator") or "dashboard",
                )
                self._json(result)
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/runs/end":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Loopback only."}, HTTPStatus.FORBIDDEN)
                return
            try:
                from src.utils import analysis_runs as _ar
                result = _ar.end_run(
                    project_root=self.state.project_root,
                    analysis_run_id=body.get("analysis_run_id"),
                )
                self._json(result)
            except Exception as exc:
                self._json({"success": False, "error": f"{type(exc).__name__}: {exc}"})
            return
        if path == "/api/update/channel":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Loopback only."}, HTTPStatus.FORBIDDEN)
                return
            channel = (body.get("channel") or "stable").strip().lower()
            if channel not in {"stable", "beta", "dev"}:
                self._json({"success": False, "error": "channel must be stable | beta | dev"}, HTTPStatus.BAD_REQUEST)
                return
            os.environ["DAVINCI_RESOLVE_MCP_UPDATE_CHANNEL"] = channel
            self._json({"success": True, "channel": channel,
                        "note": "Set for this process; persist via env var to survive restart."})
            return
        # ─── V2 Review API (writes) ─────────────────────────────────────
        if path == "/api/panel_state":
            merge = body.pop("__merge__", True)
            written_by = body.pop("__written_by__", "control_panel")
            result = write_panel_state(
                self.state.project_root,
                {k: v for k, v in body.items() if not k.startswith("__")},
                written_by=written_by,
                merge=bool(merge),
            )
            self._json(result, 200 if result.get("success") else 400)
            return
        if path == "/api/resolve/open_clip":
            result = _v2_open_clip_in_resolve(body)
            self._json(result, 200 if result.get("success") else 400)
            return
        if path == "/api/resolve/create_timeline_from_clips":
            if not _request_is_loopback(self):
                self._json({"success": False, "error": "Timeline creation is loopback-only."}, HTTPStatus.FORBIDDEN)
                return
            result = _v2_create_timeline_from_clips(body)
            self._json(result, 200 if result.get("success") else 400)
            return
        if path == "/api/clips/combined":
            result = combined_clip_analysis(self.state.project_root, body)
            self._json(result, 200 if result.get("success") else 400)
            return
        if path == "/api/clips/export":
            return self._serve_clip_export(body)
        if path.startswith("/api/clips/"):
            parts = path.split("/")
            if len(parts) >= 5 and parts[4] == "corrections":
                clip_id = parts[3]
                result = apply_clip_correction(self.state.project_root, clip_id, body)
                self._json(result, 200 if result.get("success") else 400)
                return
        self._json({"success": False, "error": "Not found"}, HTTPStatus.NOT_FOUND)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local Resolve MCP control panel.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--project-name", default="Dashboard Analysis")
    parser.add_argument("--project-id", default="dashboard")
    parser.add_argument("--analysis-root", default=os.path.expanduser("~/Documents/davinci-resolve-mcp-analysis"))
    open_group = parser.add_mutually_exclusive_group()
    open_group.add_argument("--open", dest="open", action="store_true", help="Open the control panel in the default browser.")
    open_group.add_argument("--no-open", dest="open", action="store_false", help="Run the control panel server without opening a browser.")
    parser.set_defaults(open=False)
    return parser.parse_args()


def _warm_inventory_cache(project_root: str) -> None:
    """Build the first Resolve inventory in the background at startup.

    Populates the inventory + path-existence caches before the browser connects so
    the first dashboard open paints live data immediately instead of waiting on a
    cold Media Pool walk. Best-effort: if Resolve isn't up yet this no-ops and the
    first real request builds normally.
    """
    try:
        pref_limit, exclude_bins = _inventory_prefs()
        resolve_media_inventory(project_root, limit=pref_limit, exclude_bins=exclude_bins)
    except Exception:  # noqa: BLE001 — warm-up must never crash startup
        pass


def main() -> None:
    from src.utils import actor_identity
    actor_identity.set_instance("control-panel")
    args = parse_args()
    state = DashboardState(args.project_name, args.project_id, args.analysis_root)
    Handler.state = state
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"DaVinci Resolve MCP: {url}")
    print(f"Project analysis root: {state.project_root}")
    threading.Thread(target=_warm_inventory_cache, args=(state.project_root,), daemon=True).start()
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
