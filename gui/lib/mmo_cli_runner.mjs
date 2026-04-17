import { spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const _MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(_MODULE_DIR, "..", "..");

function _basenameLike(text) {
  return text.replace(/^.*[\\/]/, "");
}

function _publicLabelText(rawText) {
  const text = typeof rawText === "string" ? rawText.trim() : "";
  if (!text) {
    return "";
  }
  return text.split(/\s+/).map((token) => {
    if (token.includes("/") || token.includes("\\")) {
      return _basenameLike(token);
    }
    return token;
  }).join(" ");
}

function _pythonEnv() {
  const env = { ...process.env };
  const srcPath = path.join(REPO_ROOT, "src");
  // The python fallback has to work from a repo checkout, so it always prepends
  // src/ instead of assuming the package is already installed into site-packages.
  if (typeof env.PYTHONPATH === "string" && env.PYTHONPATH.trim()) {
    env.PYTHONPATH = `${srcPath}${path.delimiter}${env.PYTHONPATH}`;
  } else {
    env.PYTHONPATH = srcPath;
  }
  return env;
}

function _candidateLabel(candidate) {
  const args = Array.isArray(candidate.baseArgs) ? candidate.baseArgs.join(" ") : "";
  if (args) {
    return `${candidate.command} ${args}`.trim();
  }
  return candidate.command;
}

export function publicCandidateLabel(candidate) {
  const labeledText = typeof candidate?.label === "string" && candidate.label.trim()
    ? candidate.label
    : _candidateLabel(candidate);
  // Browser-visible bridge errors must not expose absolute binary paths from
  // env overrides or local installs. Keep only the public-facing command text.
  return _publicLabelText(labeledText);
}

export function processErrorSummary(error) {
  // Spawn errors can embed local path details in the raw exception text. The
  // bridge only needs a stable failure category and, when present, an error code.
  if (error instanceof Error && /timed out/i.test(error.message)) {
    return "error=timeout";
  }
  const errorCode = typeof error?.code === "string" && error.code.trim()
    ? error.code.trim()
    : "";
  if (errorCode) {
    return `error=process_error; error_code=${errorCode}`;
  }
  return "error=process_error";
}

export function stderrSummary(stderrText) {
  // Preserve enough debugging signal to show that stderr existed without
  // replaying path-rich subprocess output into the browser shell.
  const lines = typeof stderrText === "string"
    ? stderrText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
    : [];
  if (lines.length === 0) {
    return "stderr_present=false";
  }
  return `stderr_present=true; stderr_lines=${lines.length}`;
}

export function buildCliCandidates() {
  const mmoBin = typeof process.env.MMO_GUI_MMO_BIN === "string" && process.env.MMO_GUI_MMO_BIN.trim()
    ? process.env.MMO_GUI_MMO_BIN.trim()
    : "mmo";
  const pythonBin = typeof process.env.MMO_GUI_PYTHON_BIN === "string" && process.env.MMO_GUI_PYTHON_BIN.trim()
    ? process.env.MMO_GUI_PYTHON_BIN.trim()
    : "python";
  const pythonModuleArgs = ["-m", "mmo"];

  const pythonFallbackCandidate = {
    command: pythonBin,
    baseArgs: pythonModuleArgs,
    cwd: REPO_ROOT,
    env: _pythonEnv(),
  };
  pythonFallbackCandidate.label = _candidateLabel(pythonFallbackCandidate);

  return [
    {
      command: mmoBin,
      baseArgs: [],
      cwd: REPO_ROOT,
      env: { ...process.env },
      label: mmoBin,
    },
    // Keep python -m mmo as a first-class fallback for machines where the CLI
    // wrapper is missing but the checkout is still runnable.
    pythonFallbackCandidate,
  ];
}

export function buildRpcCommandCandidates(cliCandidates = buildCliCandidates()) {
  return cliCandidates.map((candidate) => ({
    command: candidate.command,
    args: [...candidate.baseArgs, "gui", "rpc"],
    cwd: candidate.cwd,
    env: candidate.env,
    label: `${_candidateLabel(candidate)} gui rpc`.trim(),
  }));
}

function _runCommandOnce(
  candidate,
  args,
  {
    stdinText = "",
    timeoutMs = 15_000,
    spawnProcess = spawn,
  } = {},
) {
  return new Promise((resolve) => {
    let settled = false;
    let stdout = "";
    let stderr = "";

    const child = spawnProcess(candidate.command, [...candidate.baseArgs, ...args], {
      cwd: candidate.cwd,
      env: candidate.env,
      stdio: ["pipe", "pipe", "pipe"],
    });

    const timer = setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      child.kill();
      resolve({
        code: null,
        stdout,
        stderr,
        error: new Error(`Command timed out after ${timeoutMs}ms.`),
      });
    }, timeoutMs);

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });

    child.on("error", (error) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve({
        code: null,
        stdout,
        stderr,
        error,
      });
    });

    child.on("close", (code) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve({
        code,
        stdout,
        stderr,
        error: null,
      });
    });

    if (stdinText) {
      child.stdin.write(stdinText, "utf8");
    }
    child.stdin.end();
  });
}

export async function runMmoCli(
  args,
  {
    acceptedExitCodes = [0],
    stdinText = "",
    timeoutMs = 15_000,
    candidates = buildCliCandidates(),
    spawnProcess = spawn,
  } = {},
) {
  const failures = [];
  for (const candidate of candidates) {
    const result = await _runCommandOnce(candidate, args, { stdinText, timeoutMs, spawnProcess });
    if (result.error === null && acceptedExitCodes.includes(result.code)) {
      return {
        ...result,
        candidate: publicCandidateLabel(candidate),
      };
    }
    const label = publicCandidateLabel(candidate);
    // Failure summaries list every attempted candidate so setup drift in the
    // dev shell shows up as one error, not as a silent fallback.
    const codeText = result.code === null ? "null" : String(result.code);
    const errorText = result.error ? processErrorSummary(result.error) : `code=${codeText}`;
    failures.push(
      `${label}: ${errorText}; ${stderrSummary(result.stderr)}`,
    );
  }
  throw new Error(
    `Failed to run MMO CLI command (${args.join(" ")}).\n${failures.join("\n")}`,
  );
}

export async function runMmoCliJson(args, options = {}) {
  const result = await runMmoCli(args, options);
  const stdoutText = result.stdout.trim();
  if (!stdoutText) {
    return {};
  }
  let parsed;
  try {
    parsed = JSON.parse(stdoutText);
  } catch (error) {
    throw new Error(
      `MMO CLI command returned invalid JSON for (${args.join(" ")}): ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  // The bridge only accepts object JSON here because callers merge fields by
  // name. Arrays and scalars would hide a contract mismatch until later.
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`MMO CLI command returned non-object JSON for (${args.join(" ")}).`);
  }
  return parsed;
}
