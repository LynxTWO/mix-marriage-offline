import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "../../..");
const toolPath = resolve(repoRoot, "tools", "prepare_tauri_sidecar.py");
const tauriSrc = resolve(scriptDir, "../src-tauri");

function isPathLike(command) {
  return command.includes("/") || command.includes("\\");
}

function normalizeCommand(command) {
  if (!isPathLike(command)) {
    return command;
  }
  const normalized = resolve(command);
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}

function candidateKey(candidate) {
  return JSON.stringify([normalizeCommand(candidate[0]), ...candidate.slice(1)]);
}

function formatCandidate(candidate) {
  return candidate.join(" ");
}

// Build an ordered list of [command, ...args] candidates.
// Priority: explicit env overrides > setup-python location > generic names.
const rawCandidates = [];

if (typeof process.env.PYTHON === "string" && process.env.PYTHON.trim()) {
  rawCandidates.push([process.env.PYTHON.trim()]);
}

if (typeof process.env.npm_config_python === "string" && process.env.npm_config_python.trim()) {
  rawCandidates.push([process.env.npm_config_python.trim()]);
}

if (typeof process.env.pythonLocation === "string" && process.env.pythonLocation.trim()) {
  const loc = process.env.pythonLocation.trim();
  if (process.platform === "win32") {
    rawCandidates.push([resolve(loc, "python.exe")]);
  } else {
    rawCandidates.push([resolve(loc, "bin", "python")]);
  }
}

rawCandidates.push(["python"]);

if (process.platform === "win32") {
  rawCandidates.push(["py", "-3"]);
}

rawCandidates.push(["python3"]);

// De-duplicate by the resolved command string (first element + any fixed args).
const seen = new Set();
const pythonCandidates = [];
for (const candidate of rawCandidates) {
  const key = candidateKey(candidate);
  if (!seen.has(key)) {
    seen.add(key);
    pythonCandidates.push(candidate);
  }
}

const attempted = [];
let exitCode = null;
for (const candidate of pythonCandidates) {
  const command = candidate[0];
  const args = [
    ...candidate.slice(1),
    toolPath,
    "--repo-root",
    repoRoot,
    "--tauri-src",
    tauriSrc,
  ];
  const attemptedCandidate = formatCandidate(candidate);
  attempted.push(attemptedCandidate);
  const result = spawnSync(command, args, {
    cwd: repoRoot,
    stdio: "inherit",
  });
  if (result.error && "code" in result.error && result.error.code === "ENOENT") {
    continue;
  }
  if (result.error) {
    console.error(
      `Failed to launch Python interpreter ${attemptedCandidate}: ${result.error.message}`
    );
    exitCode = 1;
    break;
  }
  if (result.status !== 0) {
    console.error(`MMO sidecar build failed using Python interpreter: ${attemptedCandidate}`);
  }
  exitCode = result.status ?? 1;
  break;
}

if (exitCode === null) {
  console.error(
    "Unable to locate a Python interpreter. Tried:\n" +
    attempted.map((c) => `  ${c}`).join("\n") +
    "\nSet PYTHON or install python to build the MMO sidecar."
  );
  exitCode = 1;
}

process.exitCode = exitCode;
