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

const SYNC_ITEMS = [
  "bin",
  "src",
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
  davinci-resolve-mcp --version
  davinci-resolve-mcp --help

Examples:
  npx davinci-resolve-mcp setup
  npx davinci-resolve-mcp setup --clients cursor,claude-desktop
  npx davinci-resolve-mcp doctor

Environment:
  DAVINCI_RESOLVE_MCP_INSTALL_ROOT   Override the managed install directory.
  DAVINCI_RESOLVE_MCP_PYTHON         Python executable to use.
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

function copyItem(name, destinationRoot) {
  const source = path.join(PACKAGE_ROOT, name);
  if (!fs.existsSync(source)) {
    return;
  }

  const destination = path.join(destinationRoot, name);
  fs.rmSync(destination, { recursive: true, force: true });
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

function commandExists(command, args = []) {
  const result = spawnSync(command, [...args, "--version"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  return result.status === 0;
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
  if (process.platform === "win32" && commandExists("py")) {
    candidates.push(
      { command: "py", args: ["-3.12"] },
      { command: "py", args: ["-3.11"] },
      { command: "py", args: ["-3.10"] }
    );
  }
  candidates.push(
    { command: "python3.12", args: [] },
    { command: "python3.11", args: [] },
    { command: "python3.10", args: [] },
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
    const supported = info.major === 3 && info.minor >= 10 && info.minor <= 12;
    return { ...candidate, ...info, supported };
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

  const suffix = checked.length ? ` Found: ${checked.join(", ")}.` : "";
  throw new Error(`Python 3.10-3.12 is required for Resolve scripting compatibility.${suffix}`);
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
    throw new Error(`Managed venv Python must be 3.10-3.12. Re-run setup to recreate it: ${executable}`);
  }
  return info;
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
  run(command, commandArgs, { cwd: root });
}

function commandServer(args) {
  const root = syncManagedInstall(installRoot());
  const python = venvPython(root) || findSupportedPython();
  const serverScript = path.join(root, "src", "server.py");
  const [command, ...commandArgs] = pythonCommandLine(python, [serverScript, ...args]);
  run(command, commandArgs, { cwd: root });
}

function commandControlPanel(args) {
  const root = syncManagedInstall(installRoot());
  const python = venvPython(root) || findSupportedPython();
  const [command, ...commandArgs] = pythonCommandLine(python, ["-m", "src.control_panel", ...args]);
  run(command, commandArgs, { cwd: root });
}

function main() {
  const [command = "--help", ...args] = process.argv.slice(2);

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

    console.error(`Unknown command: ${command}\n`);
    console.error(usage());
    process.exit(2);
  } catch (error) {
    console.error(error.message);
    process.exit(1);
  }
}

main();
