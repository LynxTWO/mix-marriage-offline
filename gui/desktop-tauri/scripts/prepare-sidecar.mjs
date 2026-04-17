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
// Priority matters here because release and CI often pin Python explicitly.
// Generic PATH names should only win when no stronger signal exists.
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

// De-duplicate by the resolved command string so the same interpreter does not
// appear twice under different env names and produce duplicate failure noise.
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
    // Missing binaries are normal while walking the fallback list. Keep going
    // until one candidate launches or the list is exhausted.
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
  // Stop after the first real process result. Later candidates would hide which
  // interpreter the developer or CI job used.
  exitCode = result.status ?? 1;
  break;
}

if (exitCode === null) {
  // Surface every attempted label so missing-Python failures show the exact
  // search order instead of looking like one generic launcher error.
  console.error(
    "Unable to locate a Python interpreter. Tried:\n" +
    attempted.map((c) => `  ${c}`).join("\n") +
    "\nSet PYTHON or install python to build the MMO sidecar."
  );
  exitCode = 1;
}

process.exitCode = exitCode;
