#!/usr/bin/env node

import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const APP_NAME = "davinci-resolve-mcp";
const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const VERSION = readPackageVersion();
const MANAGED_MARKER = ".davinci-resolve-mcp-managed.json";

// The only hard Python floor is the MCP SDK: mcp[cli] requires 3.10+.
// We do NOT cap the upper bound. Resolve's scripting bridge (fusionscript)
// loads cleanly into newer interpreters on recent builds — Python 3.14 is
// verified working against Resolve Studio 20.3.2. Older Resolve builds may
// fail to connect on 3.13+, but the version number is a poor proxy for that;
// the connection check in `setup`/`doctor` is the real signal, so we proceed
// with a soft heads-up rather than refusing to run.
const PY_MIN_MINOR = 10;
const PY_ABI_RISK_MINOR = 13;

const SYNC_ITEMS = [
  "bin",
  "src",
  // The Node 'advanced' bin resolves ../resolve-advanced/server/index.mjs
  // relative to itself, and install.py registers that bin into every generated
  // client config. Leaving the tree out of the sync shipped configs that
  // pointed at a module the managed install could never contain (issue #179).
  "resolve-advanced",
  "docs",
  "examples",
  "scripts",
  "install.py",
  "README.md",
  "CHANGELOG.md",
  "LICENSE",
  "SECURITY.md",
  "AGENTS.md",
  "CLAUDE.md",
  "package.json",
];

function readPackageVersion() {
  const packageJsonPath = path.join(PACKAGE_ROOT, "package.json");
  const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
  return packageJson.version;
}

function usage() {
  return `DaVinci Resolve MCP ${VERSION}

Usage:
  davinci-resolve-mcp setup [install.py options]
  davinci-resolve-mcp doctor [install.py options]
  davinci-resolve-mcp server [server.py options]
  davinci-resolve-mcp control-panel [control panel options]
  davinci-resolve-mcp batch <plan|run|status|list|resume|cancel> [options]
  davinci-resolve-mcp sync [--no-deps]
  davinci-resolve-mcp --version
  davinci-resolve-mcp --help

Examples:
  npx davinci-resolve-mcp setup
  npx davinci-resolve-mcp setup --clients cursor,claude-desktop
  npx davinci-resolve-mcp doctor
  npx davinci-resolve-mcp batch run /path/to/footage --depth standard
  npx davinci-resolve-mcp batch run /path/to/footage --json > progress.log
  npx davinci-resolve-mcp sync            # refresh the managed install only

Environment:
  DAVINCI_RESOLVE_MCP_INSTALL_ROOT   Override the managed install directory.
  DAVINCI_RESOLVE_MCP_PYTHON         Python executable to use (3.10+). Set this to
                                     pin a specific interpreter, e.g. python3.12.
  PYTHON                             Fallback Python executable to use.
`;
}

function defaultInstallRoot() {
  if (process.platform === "darwin") {
    return path.join(os.homedir(), "Library", "Application Support", APP_NAME);
  }
  if (process.platform === "win32") {
    const localAppData = process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local");
    return path.join(localAppData, APP_NAME);
  }
  const dataHome = process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share");
  return path.join(dataHome, APP_NAME);
}

function installRoot() {
  return path.resolve(process.env.DAVINCI_RESOLVE_MCP_INSTALL_ROOT || defaultInstallRoot());
}

function realPathIfExists(target) {
  try {
    return fs.realpathSync(target);
  } catch {
    return null;
  }
}

function samePath(left, right) {
  const leftReal = realPathIfExists(left);
  const rightReal = realPathIfExists(right);
  return Boolean(leftReal && rightReal && leftReal === rightReal);
}

function isRootOrHome(target) {
  const resolved = path.resolve(target);
  const parsed = path.parse(resolved);
  return resolved === parsed.root || resolved === path.resolve(os.homedir());
}

function validateManagedRoot(root) {
  if (isRootOrHome(root)) {
    throw new Error(`Refusing to use unsafe install root: ${root}`);
  }

  if (!fs.existsSync(root)) {
    fs.mkdirSync(root, { recursive: true });
    return;
  }

  const entries = fs.readdirSync(root).filter((entry) => entry !== ".DS_Store");
  if (entries.length === 0) {
    return;
  }

  const marker = path.join(root, MANAGED_MARKER);
  const knownInstall = fs.existsSync(path.join(root, "install.py")) &&
    fs.existsSync(path.join(root, "src", "server.py"));
  if (!fs.existsSync(marker) && !knownInstall) {
    throw new Error(
      `Refusing to update non-managed directory: ${root}\n` +
      `Set DAVINCI_RESOLVE_MCP_INSTALL_ROOT to an empty directory or an existing ${APP_NAME} install.`
    );
  }
}

// Top-level children of a synced item that the sync must NOT delete. The
// advanced server's node_modules is installed *into* the managed root by
// provisionAdvancedDeps and has no counterpart in the package, so a blanket
// clear would throw it away on every subsequent command and force a reinstall.
const SYNC_PRESERVE = {
  "resolve-advanced": ["node_modules"],
};

function clearDestination(destination, preserve) {
  if (!preserve.length || !fs.existsSync(destination)) {
    fs.rmSync(destination, { recursive: true, force: true });
    return;
  }
  const keep = new Set(preserve);
  for (const entry of fs.readdirSync(destination)) {
    if (keep.has(entry)) {
      continue;
    }
    fs.rmSync(path.join(destination, entry), { recursive: true, force: true });
  }
}

function copyItem(name, destinationRoot) {
  const source = path.join(PACKAGE_ROOT, name);
  if (!fs.existsSync(source)) {
    return;
  }

  const destination = path.join(destinationRoot, name);
  clearDestination(destination, SYNC_PRESERVE[name] || []);
  fs.cpSync(source, destination, {
    recursive: true,
    errorOnExist: false,
    force: true,
    preserveTimestamps: true,
    filter: (sourcePath) => shouldSyncPath(sourcePath),
  });
}

function shouldSyncPath(sourcePath) {
  const basename = path.basename(sourcePath);
  if (basename === "__pycache__" || basename === ".DS_Store") {
    return false;
  }
  // A dev checkout carries resolve-advanced/node_modules with optional native
  // deps (sharp, better-sqlite3) built for the developer's platform+ABI.
  // Copying those into a managed install is slow and ships binaries that may
  // not load there; provisionAdvancedDeps installs them fresh instead.
  if (basename === "node_modules") {
    return false;
  }
  if (basename.endsWith(".pyc") || basename.endsWith(".pyo")) {
    return false;
  }
  return true;
}

function syncManagedInstall(root) {
  validateManagedRoot(root);
  if (samePath(PACKAGE_ROOT, root)) {
    return root;
  }

  for (const item of SYNC_ITEMS) {
    copyItem(item, root);
  }

  const markerPath = path.join(root, MANAGED_MARKER);
  fs.writeFileSync(
    markerPath,
    `${JSON.stringify({ name: APP_NAME, version: VERSION, managed: true, updatedAt: new Date().toISOString() }, null, 2)}\n`,
    "utf8"
  );
  return root;
}

// ─── Advanced (Node) server runtime ─────────────────────────────────────────
//
// The advanced bin imports ../resolve-advanced/server/index.mjs, which in turn
// imports @modelcontextprotocol/sdk, zod, jszip, fzstd, zstd-codec and the
// vendored codecs. Syncing the tree is only half the fix for issue #179: the
// managed root has no node_modules, so the imports still fail. Node resolves
// them from resolve-advanced/node_modules, which resolve-advanced/package.json
// declares — so that manifest, not a list duplicated here, is the source of
// truth for what has to be present.

function advancedRoot(root) {
  return path.join(root, "resolve-advanced");
}

function advancedServerEntry(root) {
  return path.join(advancedRoot(root), "server", "index.mjs");
}

function advancedRequiredDeps(root) {
  const manifest = path.join(advancedRoot(root), "package.json");
  try {
    const parsed = JSON.parse(fs.readFileSync(manifest, "utf8"));
    return Object.keys(parsed.dependencies || {});
  } catch {
    return [];
  }
}

/** Can the advanced server actually boot from this root? Names what is missing. */
function advancedRuntimeStatus(root) {
  const entry = advancedServerEntry(root);
  const entryPresent = fs.existsSync(entry);
  const modulesDir = path.join(advancedRoot(root), "node_modules");
  const required = advancedRequiredDeps(root);
  const missingDeps = required.filter(
    (dep) => !fs.existsSync(path.join(modulesDir, ...dep.split("/")))
  );
  return {
    entry,
    entryPresent,
    // No manifest to read means we cannot tell what is required; treat that as
    // "not bootable" rather than quietly reporting a clean bill of health.
    depsPresent: required.length > 0 && missingDeps.length === 0,
    required,
    missingDeps,
    bootable: entryPresent && required.length > 0 && missingDeps.length === 0,
  };
}

function npmCommand() {
  return process.platform === "win32" ? "npm.cmd" : "npm";
}

/**
 * Install the advanced server's Node deps into the managed root.
 *
 * Optional deps (better-sqlite3, sharp, pg, js-yaml) stay omitted on purpose:
 * they are native or heavy, the server already reports capability-specific
 * setup gaps when they are absent, and a failed native build must not take the
 * whole setup down with it.
 *
 * stdio is inherited on stderr only — this must never write to stdout, which
 * on the server path is a JSON-RPC channel.
 */
function provisionAdvancedDeps(root, { force = false } = {}) {
  const before = advancedRuntimeStatus(root);
  if (!before.entryPresent) {
    return { ...before, ran: false, reason: "advanced server tree is not present" };
  }
  if (before.depsPresent && !force) {
    return { ...before, ran: false, reason: "already provisioned" };
  }

  const result = spawnSync(
    npmCommand(),
    ["install", "--omit=dev", "--omit=optional", "--no-audit", "--no-fund"],
    { cwd: advancedRoot(root), stdio: ["ignore", "inherit", "inherit"], encoding: "utf8" }
  );

  const after = advancedRuntimeStatus(root);
  return {
    ...after,
    ran: true,
    ok: result.status === 0 && after.bootable,
    status: result.status,
    error: result.error ? result.error.message : null,
  };
}

function reportAdvancedRuntime(root, { provision }) {
  const outcome = provision
    ? provisionAdvancedDeps(root)
    : advancedRuntimeStatus(root);

  if (outcome.bootable) {
    console.log("Advanced server (Node): ready");
    return outcome;
  }
  if (!outcome.entryPresent) {
    console.log(
      `Advanced server (Node): unavailable — ${outcome.entry} is missing. ` +
      `The 'davinci-resolve-advanced' entry will be registered as an npx command instead.`
    );
    return outcome;
  }
  const missing = outcome.missingDeps.length
    ? outcome.missingDeps.join(", ")
    : "its dependency manifest";
  console.log(
    `Advanced server (Node): not bootable — missing ${missing}. ` +
    (outcome.error ? `npm install failed: ${outcome.error}. ` : "") +
    `Fix: run 'npm install --omit=dev --omit=optional' in ${advancedRoot(root)}, ` +
    `or re-run 'npx davinci-resolve-mcp setup' with a network connection. ` +
    `Until then the 'davinci-resolve-advanced' entry falls back to an npx command.`
  );
  return outcome;
}

function parseExecutable(value) {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  return { command: trimmed, args: [] };
}

function pythonCandidates() {
  const explicit = parseExecutable(process.env.DAVINCI_RESOLVE_MCP_PYTHON || process.env.PYTHON);
  const candidates = [];
  if (explicit) {
    candidates.push(explicit);
  }
  // Prefer the lowest-ABI-risk interpreters first, then newer ones, then the
  // generic launchers. All 3.10+ are accepted; ordering just picks the safest
  // when several are installed.
  // No existence probe in front of these. `py --version` is not a reliable
  // one — the Windows launcher does not accept it on every build, and it
  // exits 101 on the ones it does not (issue #158). A probe that gets that
  // wrong discards every version-pinned candidate below and falls through to
  // bare `python`, which is exactly the 3.13 the ordering exists to avoid.
  // checkPython() runs each candidate anyway, so a missing `py` costs one
  // failed spawn and is skipped.
  if (process.platform === "win32") {
    candidates.push(
      { command: "py", args: ["-3.12"] },
      { command: "py", args: ["-3.11"] },
      { command: "py", args: ["-3.10"] },
      { command: "py", args: ["-3.13"] },
      { command: "py", args: ["-3.14"] }
    );
  }
  candidates.push(
    { command: "python3.12", args: [] },
    { command: "python3.11", args: [] },
    { command: "python3.10", args: [] },
    { command: "python3.13", args: [] },
    { command: "python3.14", args: [] },
    { command: "python3", args: [] },
    { command: "python", args: [] }
  );
  return candidates;
}

function checkPython(candidate) {
  const script = [
    "import json, sys",
    "print(json.dumps({'major': sys.version_info.major, 'minor': sys.version_info.minor, 'micro': sys.version_info.micro, 'executable': sys.executable}))",
  ].join("; ");
  const result = spawnSync(candidate.command, [...candidate.args, "-c", script], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (result.status !== 0) {
    return null;
  }
  try {
    const info = JSON.parse(result.stdout.trim());
    const supported = info.major === 3 && info.minor >= PY_MIN_MINOR;
    const abiRisk = info.major === 3 && info.minor >= PY_ABI_RISK_MINOR;
    return { ...candidate, ...info, supported, abiRisk };
  } catch {
    return null;
  }
}

function findSupportedPython() {
  const checked = [];
  for (const candidate of pythonCandidates()) {
    const info = checkPython(candidate);
    if (!info) {
      continue;
    }
    checked.push(`${candidate.command}${candidate.args.length ? ` ${candidate.args.join(" ")}` : ""} (${info.major}.${info.minor}.${info.micro})`);
    if (info.supported) {
      return info;
    }
  }

  throw new Error(unsupportedPythonMessage(checked));
}

// Print the 3.13+ heads-up for run modes that never invoke install.py
// (server/control-panel/batch). setup/doctor stay quiet here because
// install.py emits a richer, connection-aware note of its own.
function maybeWarnAbiRisk(info) {
  if (info && info.abiRisk) {
    console.warn(abiRiskNote(info));
  }
}

function abiRiskNote(info) {
  return (
    `Note: using Python ${info.major}.${info.minor}.${info.micro}. ` +
    `This is verified working on recent Resolve builds (Studio 20.3.2). ` +
    `If Resolve fails to connect (scriptapp("Resolve") returns None), install ` +
    `Python 3.10-3.12 and pin it with DAVINCI_RESOLVE_MCP_PYTHON=/path/to/python3.12.`
  );
}

function unsupportedPythonMessage(checked) {
  const found = checked.length ? ` Found: ${checked.join(", ")}.` : "";
  const lines = [
    `Python 3.${PY_MIN_MINOR} or newer is required (the MCP SDK needs Python 3.${PY_MIN_MINOR}+).${found}`,
    "",
    "How to fix:",
    "  - Install Python 3.12 (the lowest-risk version for Resolve), e.g.:",
    "      macOS:   brew install python@3.12   (or: pyenv install 3.12)",
    "      Linux:   pyenv install 3.12          (or your distro's python3.12 package)",
    "      Windows: install Python 3.12 from python.org",
    `  - Point the launcher at it:  DAVINCI_RESOLVE_MCP_PYTHON=/path/to/python3.12 npx ${APP_NAME} setup`,
  ];
  return lines.join("\n");
}

function venvPython(root) {
  const relative = process.platform === "win32"
    ? path.join("venv", "Scripts", "python.exe")
    : path.join("venv", "bin", "python");
  const executable = path.join(root, relative);
  if (!fs.existsSync(executable)) {
    return null;
  }
  const info = checkPython({ command: executable, args: [] });
  if (!info || !info.supported) {
    throw new Error(
      `Managed venv Python must be 3.${PY_MIN_MINOR} or newer. ` +
        `Re-run setup to recreate it: ${executable}`
    );
  }
  return info;
}

// Windows reports a hard access violation as the process exit code, not as a
// signal and not as a traceback: the interpreter is gone before it can say
// anything. Loading Resolve's fusionscript under a Python its C ABI does not
// match is one way to get there, so name that possibility rather than letting
// the run end in a bare unexplained code (issue #158).
const WINDOWS_ACCESS_VIOLATION = [3221225477, -1073741819];

function accessViolationNote(code) {
  return [
    `The Python process was terminated by an access violation (0x${(code >>> 0).toString(16).toUpperCase()}).`,
    "It crashed inside a native library before it could report anything, so there is no traceback above.",
    "The usual cause is Resolve's scripting library being loaded by a Python whose C ABI it was not built",
    "against. If you are on Python 3.13+, install Python 3.10-3.12 and pin it:",
    "  DAVINCI_RESOLVE_MCP_PYTHON=C:\\Path\\To\\python3.12.exe",
    "then re-run setup so the managed venv is rebuilt on that interpreter.",
  ].join("\n");
}

function run(command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: options.cwd,
    env: options.env || process.env,
    stdio: "inherit",
  });

  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
      return;
    }
    if (WINDOWS_ACCESS_VIOLATION.includes(code)) {
      console.error(accessViolationNote(code));
    }
    process.exit(code ?? 1);
  });
  child.on("error", (error) => {
    console.error(error.message);
    process.exit(1);
  });
}

function pythonCommandLine(python, rest) {
  return [python.command, ...python.args, ...rest];
}

function hasOption(args, name) {
  return args.some((arg) => arg === name || arg.startsWith(`${name}=`));
}

function commandSetup(args) {
  const root = syncManagedInstall(installRoot());
  const python = findSupportedPython();
  const installScript = path.join(root, "install.py");
  const [command, ...commandArgs] = pythonCommandLine(python, [installScript, ...args]);

  console.log(`DaVinci Resolve MCP managed install: ${root}`);
  console.log(`Python: ${python.executable} (${python.major}.${python.minor}.${python.micro})`);
  // Before install.py, not after: it inspects this layout to decide whether the
  // 'davinci-resolve-advanced' entry can point at the managed bin.
  reportAdvancedRuntime(root, { provision: true });
  run(command, commandArgs, { cwd: root });
}

function commandDoctor(args) {
  const root = syncManagedInstall(installRoot());
  const python = findSupportedPython();
  const doctorArgs = [...args];
  if (!hasOption(doctorArgs, "--dry-run")) {
    doctorArgs.unshift("--dry-run");
  }
  if (!hasOption(doctorArgs, "--no-venv")) {
    doctorArgs.unshift("--no-venv");
  }
  if (!hasOption(doctorArgs, "--clients")) {
    doctorArgs.push("--clients", "manual");
  }
  const installScript = path.join(root, "install.py");
  const [command, ...commandArgs] = pythonCommandLine(python, [installScript, ...doctorArgs]);

  console.log(`DaVinci Resolve MCP managed install: ${root}`);
  console.log(`Python: ${python.executable} (${python.major}.${python.minor}.${python.micro})`);
  // Diagnose only — doctor already forces --dry-run and must not install.
  reportAdvancedRuntime(root, { provision: false });
  run(command, commandArgs, { cwd: root });
}

function commandServer(args) {
  const root = syncManagedInstall(installRoot());
  const python = venvPython(root) || findSupportedPython();
  maybeWarnAbiRisk(python);
  const serverScript = path.join(root, "src", "server.py");
  const [command, ...commandArgs] = pythonCommandLine(python, [serverScript, ...args]);
  run(command, commandArgs, { cwd: root });
}

function commandControlPanel(args) {
  const root = syncManagedInstall(installRoot());
  const python = venvPython(root) || findSupportedPython();
  maybeWarnAbiRisk(python);
  const [command, ...commandArgs] = pythonCommandLine(python, ["-m", "src.control_panel", ...args]);
  run(command, commandArgs, { cwd: root });
}

function commandBatch(args) {
  const root = syncManagedInstall(installRoot());
  const python = venvPython(root) || findSupportedPython();
  maybeWarnAbiRisk(python);
  const [command, ...commandArgs] = pythonCommandLine(python, ["-m", "src.batch_cli", ...args]);
  run(command, commandArgs, { cwd: root });
}

function commandSync(args) {
  const provision = !args.includes("--no-deps");
  const root = syncManagedInstall(installRoot());
  console.log(`DaVinci Resolve MCP managed install: ${root}`);
  const outcome = reportAdvancedRuntime(root, { provision });
  if (provision && !outcome.bootable) {
    process.exit(1);
  }
}

function main() {
  const argv = process.argv.slice(2);
  // No args → run the MCP stdio server. Anything printed to stdout would
  // otherwise be parsed as JSON-RPC by MCP clients and break the connection.
  const [command = "server", ...args] = argv;

  try {
    if (command === "--help" || command === "-h" || command === "help") {
      console.log(usage());
      return;
    }
    if (command === "--version" || command === "-v" || command === "version") {
      console.log(VERSION);
      return;
    }
    if (command === "setup") {
      commandSetup(args);
      return;
    }
    if (command === "doctor") {
      commandDoctor(args);
      return;
    }
    if (command === "server") {
      commandServer(args);
      return;
    }
    if (command === "control-panel" || command === "control_panel") {
      commandControlPanel(args);
      return;
    }
    if (command === "batch") {
      commandBatch(args);
      return;
    }
    if (command === "sync") {
      commandSync(args);
      return;
    }

    console.error(`Unknown command: ${command}\n`);
    console.error(usage());
    process.exit(2);
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
}

main();
