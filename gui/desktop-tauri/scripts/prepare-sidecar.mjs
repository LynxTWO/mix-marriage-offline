import { spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, "../../..");
const toolPath = resolve(repoRoot, "tools", "prepare_tauri_sidecar.py");
const tauriSrc = resolve(scriptDir, "../src-tauri");

const pythonCandidates = [];
if (typeof process.env.PYTHON === "string" && process.env.PYTHON.trim()) {
  pythonCandidates.push([process.env.PYTHON.trim()]);
}
if (process.platform === "win32") {
  pythonCandidates.push(["py", "-3"]);
}
pythonCandidates.push(["python3"]);
pythonCandidates.push(["python"]);

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
  const result = spawnSync(command, args, {
    cwd: repoRoot,
    stdio: "inherit",
  });
  if (result.error && "code" in result.error && result.error.code === "ENOENT") {
    continue;
  }
  process.exit(result.status ?? 1);
}

console.error(
  "Unable to locate a Python interpreter. Set PYTHON or install python3 to build the MMO sidecar."
);
process.exit(1);
