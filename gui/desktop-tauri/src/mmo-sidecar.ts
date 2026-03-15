import { Command, type Child } from "@tauri-apps/plugin-shell";
import { exists, readTextFile, writeTextFile } from "@tauri-apps/plugin-fs";

const SIDECAR_NAME = "binaries/mmo";
const LIVE_PREFIX = "[MMO-LIVE] ";
const DEFAULT_RPC_TIMEOUT_MS = 15_000;

export type MmoLivePayload = {
  confidence?: number | null;
  eta_seconds?: number | null;
  evidence?: Record<string, unknown> | null;
  kind?: string;
  progress?: number | null;
  scope?: string;
  step_index?: number | null;
  total_steps?: number | null;
  what?: string;
  where?: string[];
  why?: string;
};

export type MmoLogKind = "live" | "stderr" | "stdout";

export type MmoLogLine = {
  kind: MmoLogKind;
  payload: MmoLivePayload | null;
  rawText: string;
  text: string;
};

export type MmoRunOptions = {
  cwd?: string;
  env?: Record<string, string>;
  onLogLine?: (line: MmoLogLine) => void;
};

export type MmoRunResult = {
  code: number | null;
  signal: number | null;
  stderr: string;
  stdout: string;
};

type MmoRpcEnvelope<T extends Record<string, unknown>> = {
  error?: {
    code?: string;
    message?: string;
  };
  id?: string | null;
  ok?: boolean;
  result?: T;
};

type MmoRpcError = Error & {
  rpcCode?: string;
  rpcMessage?: string;
};

export type WorkflowPaths = {
  busPlanCsvPath: string;
  busPlanPath: string;
  comparePdfPath: string;
  compareReportPath: string;
  projectDir: string;
  projectValidationPath: string;
  renderDir: string;
  renderCancelDir: string;
  renderManifestPath: string;
  renderQaPath: string;
  renderReceiptPath: string;
  reportPath: string;
  scanReportPath: string;
  sceneLintPath: string;
  scenePath: string;
  stemsMapPath: string;
  workspaceDir: string;
};

class LineBuffer {
  private remainder = "";

  push(chunk: string, emit: (line: string) => void): void {
    const normalized = `${this.remainder}${chunk}`.replace(/\r\n/g, "\n");
    const parts = normalized.split("\n");
    this.remainder = parts.pop() ?? "";
    for (const line of parts) {
      emit(line);
    }
  }

  flush(emit: (line: string) => void): void {
    if (this.remainder.length > 0) {
      emit(this.remainder);
      this.remainder = "";
    }
  }
}

export function normalizePath(pathValue: string): string {
  return pathValue.trim().replace(/\\/g, "/").replace(/\/+$/, "");
}

export function joinPath(basePath: string, leafName: string): string {
  const normalizedBase = normalizePath(basePath);
  if (!normalizedBase) {
    return leafName;
  }
  return `${normalizedBase}/${leafName}`;
}

export function dirname(pathValue: string): string {
  const normalized = normalizePath(pathValue);
  const separatorIndex = normalized.lastIndexOf("/");
  if (separatorIndex <= 0) {
    return "";
  }
  return normalized.slice(0, separatorIndex);
}

export function resolveSiblingPath(pathValue: string, leafName: string): string {
  const normalized = normalizePath(pathValue);
  if (!normalized) {
    return leafName;
  }
  if (normalized.toLowerCase().endsWith(".json")) {
    return joinPath(dirname(normalized), leafName);
  }
  return joinPath(normalized, leafName);
}

export function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function normalizeCommandOutput(output: MmoRunResult): MmoRunResult {
  return {
    code: output.code,
    signal: output.signal,
    stderr: output.stderr,
    stdout: output.stdout,
  };
}

function formatLivePayload(payload: MmoLivePayload): string {
  const progressText = typeof payload.progress === "number"
    ? `${Math.round(payload.progress * 100)}%`
    : "live";
  const scope = typeof payload.scope === "string" && payload.scope.trim()
    ? payload.scope.trim()
    : "render";
  const what = typeof payload.what === "string" && payload.what.trim()
    ? payload.what.trim()
    : "progress update";
  const why = typeof payload.why === "string" && payload.why.trim()
    ? payload.why.trim()
    : "";

  if (why) {
    return `${progressText} ${scope}: ${what} | ${why}`;
  }
  return `${progressText} ${scope}: ${what}`;
}

function parseLivePayload(text: string): MmoLivePayload | null {
  if (!text.startsWith(LIVE_PREFIX)) {
    return null;
  }
  const rawPayload = text.slice(LIVE_PREFIX.length).trim();
  if (!rawPayload) {
    return null;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(rawPayload);
  } catch {
    return null;
  }

  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return null;
  }

  const payload = parsed as Record<string, unknown>;
  const where = Array.isArray(payload.where)
    ? payload.where.filter((value): value is string => typeof value === "string")
    : undefined;
  const evidence = payload.evidence;
  const evidenceRecord = evidence !== null && typeof evidence === "object" && !Array.isArray(evidence)
    ? evidence as Record<string, unknown>
    : null;

  return {
    confidence: typeof payload.confidence === "number" ? payload.confidence : null,
    eta_seconds: typeof payload.eta_seconds === "number" ? payload.eta_seconds : null,
    evidence: evidenceRecord,
    kind: typeof payload.kind === "string" ? payload.kind : undefined,
    progress: typeof payload.progress === "number" ? payload.progress : null,
    scope: typeof payload.scope === "string" ? payload.scope : undefined,
    step_index: typeof payload.step_index === "number" ? payload.step_index : null,
    total_steps: typeof payload.total_steps === "number" ? payload.total_steps : null,
    what: typeof payload.what === "string" ? payload.what : undefined,
    where,
    why: typeof payload.why === "string" ? payload.why : undefined,
  };
}

function emitLogLine(
  options: MmoRunOptions,
  kind: "stderr" | "stdout",
  rawText: string,
): void {
  const payload = parseLivePayload(rawText);
  options.onLogLine?.({
    kind: payload === null ? kind : "live",
    payload,
    rawText,
    text: payload === null ? rawText : formatLivePayload(payload),
  });
}

function createSidecar(args: string[], options: MmoRunOptions): Command<string> {
  return Command.sidecar(SIDECAR_NAME, args, {
    cwd: options.cwd,
    env: options.env,
  });
}

function parseRpcEnvelope<T extends Record<string, unknown>>(line: string): MmoRpcEnvelope<T> | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(line);
  } catch {
    return null;
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return null;
  }
  return parsed as MmoRpcEnvelope<T>;
}

function rpcError(code: string, message: string): MmoRpcError {
  const error = new Error(`${code}: ${message}`) as MmoRpcError;
  error.rpcCode = code;
  error.rpcMessage = message;
  return error;
}

export function buildWorkflowPaths(workspaceDir: string): WorkflowPaths {
  const normalizedWorkspaceDir = normalizePath(workspaceDir);
  const projectDir = joinPath(normalizedWorkspaceDir, "project");
  const renderDir = joinPath(normalizedWorkspaceDir, "render");

  return {
    busPlanCsvPath: joinPath(normalizedWorkspaceDir, "bus_plan.summary.csv"),
    busPlanPath: joinPath(normalizedWorkspaceDir, "bus_plan.json"),
    comparePdfPath: joinPath(normalizedWorkspaceDir, "compare_report.pdf"),
    compareReportPath: joinPath(normalizedWorkspaceDir, "compare_report.json"),
    projectDir,
    projectValidationPath: joinPath(projectDir, "validation.json"),
    renderDir,
    renderCancelDir: normalizedWorkspaceDir,
    renderManifestPath: joinPath(normalizedWorkspaceDir, "render_manifest.json"),
    renderQaPath: joinPath(normalizedWorkspaceDir, "render_qa.json"),
    renderReceiptPath: joinPath(normalizedWorkspaceDir, "safe_render_receipt.json"),
    reportPath: joinPath(normalizedWorkspaceDir, "report.json"),
    scanReportPath: joinPath(normalizedWorkspaceDir, "report.scan.json"),
    sceneLintPath: joinPath(normalizedWorkspaceDir, "scene_lint.json"),
    scenePath: joinPath(normalizedWorkspaceDir, "scene.json"),
    stemsMapPath: joinPath(normalizedWorkspaceDir, "stems_map.json"),
    workspaceDir: normalizedWorkspaceDir,
  };
}

export async function artifactExists(path: string): Promise<boolean> {
  if (!path.trim() || !isTauriRuntime()) {
    return false;
  }
  try {
    return await exists(path);
  } catch {
    return false;
  }
}

export async function readArtifactText(path: string): Promise<string | null> {
  if (!path.trim() || !isTauriRuntime()) {
    return null;
  }
  try {
    return await readTextFile(path);
  } catch {
    return null;
  }
}

export async function readArtifactJson<T>(path: string): Promise<T | null> {
  const text = await readArtifactText(path);
  if (text === null) {
    return null;
  }
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

export async function writeArtifactText(path: string, text: string): Promise<boolean> {
  if (!path.trim() || !isTauriRuntime()) {
    return false;
  }
  try {
    await writeTextFile(path, text);
    return true;
  } catch {
    return false;
  }
}

export async function executeMmo(
  args: string[],
  options: MmoRunOptions = {},
): Promise<MmoRunResult> {
  const result = normalizeCommandOutput(await createSidecar(args, options).execute());

  for (const line of result.stdout.replace(/\r\n/g, "\n").split("\n")) {
    if (line.length > 0) {
      emitLogLine(options, "stdout", line);
    }
  }
  for (const line of result.stderr.replace(/\r\n/g, "\n").split("\n")) {
    if (line.length > 0) {
      emitLogLine(options, "stderr", line);
    }
  }

  return result;
}

export async function spawnMmo(
  args: string[],
  options: MmoRunOptions = {},
): Promise<MmoRunResult> {
  const command = createSidecar(args, options);
  const stdoutBuffer = new LineBuffer();
  const stderrBuffer = new LineBuffer();
  let stdout = "";
  let stderr = "";

  return await new Promise<MmoRunResult>((resolve, reject) => {
    let settled = false;

    const settleResolve = (result: MmoRunResult) => {
      if (settled) {
        return;
      }
      settled = true;
      resolve(normalizeCommandOutput(result));
    };

    const settleReject = (error: unknown) => {
      if (settled) {
        return;
      }
      settled = true;
      reject(error);
    };

    command.stdout.on("data", (chunk) => {
      const text = String(chunk);
      stdout += text;
      stdoutBuffer.push(text, (line) => emitLogLine(options, "stdout", line));
    });

    command.stderr.on("data", (chunk) => {
      const text = String(chunk);
      stderr += text;
      stderrBuffer.push(text, (line) => emitLogLine(options, "stderr", line));
    });

    command.on("error", (message) => {
      settleReject(new Error(message));
    });

    command.on("close", ({ code, signal }) => {
      stdoutBuffer.flush((line) => emitLogLine(options, "stdout", line));
      stderrBuffer.flush((line) => emitLogLine(options, "stderr", line));
      settleResolve({
        code,
        signal,
        stderr,
        stdout,
      });
    });

    command.spawn().catch((error) => {
      settleReject(error);
    });
  });
}

export async function runMmoRpc<T extends Record<string, unknown>>(
  method: string,
  params: Record<string, unknown> = {},
  options: MmoRunOptions & { timeoutMs?: number } = {},
): Promise<T> {
  if (!isTauriRuntime()) {
    throw new Error("MMO GUI RPC is only available in the Tauri desktop runtime.");
  }

  const timeoutMs = options.timeoutMs ?? DEFAULT_RPC_TIMEOUT_MS;
  const command = createSidecar(["gui", "rpc"], options);
  const stdoutBuffer = new LineBuffer();
  let child: Child | null = null;
  try {
    const response = await new Promise<MmoRpcEnvelope<T>>((resolve, reject) => {
      let settled = false;
      let stdout = "";
      let stderr = "";

      const settleResolve = (payload: MmoRpcEnvelope<T>) => {
        if (settled) {
          return;
        }
        settled = true;
        resolve(payload);
      };

      const settleReject = (error: unknown) => {
        if (settled) {
          return;
        }
        settled = true;
        reject(error);
      };

      const timer = window.setTimeout(() => {
        settleReject(new Error(`RPC request timed out (${method}) after ${timeoutMs}ms.`));
      }, timeoutMs);

      command.stdout.on("data", (chunk) => {
        const text = String(chunk);
        stdout += text;
        stdoutBuffer.push(text, (line) => {
          const payload = parseRpcEnvelope<T>(line);
          if (payload !== null) {
            window.clearTimeout(timer);
            settleResolve(payload);
          }
        });
      });

      command.stderr.on("data", (chunk) => {
        stderr += String(chunk);
      });

      command.on("error", (message) => {
        window.clearTimeout(timer);
        settleReject(new Error(message));
      });

      command.on("close", ({ code, signal }) => {
        stdoutBuffer.flush((line) => {
          const payload = parseRpcEnvelope<T>(line);
          if (payload !== null) {
            settleResolve(payload);
          }
        });
        window.clearTimeout(timer);
        if (!settled) {
          const stderrText = stderr.trim();
          const stdoutText = stdout.trim();
          const detail = stderrText || stdoutText || "RPC process closed before returning a response.";
          settleReject(
            new Error(
              `RPC process exited (code=${code ?? "null"} signal=${signal ?? "null"}): ${detail}`,
            ),
          );
        }
      });

      command.spawn()
        .then(async (spawnedChild) => {
          child = spawnedChild;
          await spawnedChild.write(
            `${JSON.stringify({
              id: `desktop-rpc-${Date.now().toString(36)}`,
              method,
              params,
            })}\n`,
          );
        })
        .catch((error) => {
          window.clearTimeout(timer);
          settleReject(error);
        });
    });

    if (response.ok !== true) {
      const code = typeof response.error?.code === "string" ? response.error.code : "RPC.ERROR";
      const message = typeof response.error?.message === "string"
        ? response.error.message
        : "Unknown RPC error.";
      throw rpcError(code, message);
    }
    return (response.result ?? {}) as T;
  } finally {
    const activeChild = child as { kill: () => Promise<void> } | null;
    if (activeChild !== null) {
      await activeChild.kill().catch(() => undefined);
    }
  }
}
