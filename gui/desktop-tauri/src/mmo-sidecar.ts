import { convertFileSrc } from "@tauri-apps/api/core";
import { Command, type Child } from "@tauri-apps/plugin-shell";
import { exists, readTextFile, writeTextFile } from "@tauri-apps/plugin-fs";

const SIDECAR_NAME = "binaries/mmo";
const LIVE_PREFIX = "[MMO-LIVE] ";
const DEFAULT_RPC_TIMEOUT_MS = 15_000;

type DesktopTestApi = {
  clearMockRpcResults?: () => void;
  readArtifactText?: (path: string) => Promise<string | null> | string | null;
  resolveMediaUrl?: (path: string) => string | null;
  runMmoRpc?: (
    method: string,
    params?: Record<string, unknown>,
    options?: { timeoutMs?: number },
  ) => Promise<Record<string, unknown> | null> | Record<string, unknown> | null;
  setMockRpcResult?: (method: string, payload: Record<string, unknown>) => void;
};

declare global {
  interface Window {
    __MMO_DESKTOP_TEST__?: DesktopTestApi;
  }
}

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

function isDirectMediaUrl(pathValue: string): boolean {
  // Browser and test URLs are already resolved pointers. Converting them again
  // would break blob/data sources and hide path-bridge bugs behind fake file URLs.
  return /^(?:asset|blob|data|https?):/iu.test(pathValue);
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

function desktopTestApi(): DesktopTestApi | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.__MMO_DESKTOP_TEST__ ?? null;
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
  // Desktop RPC is one JSON object per line. Ignore partial or malformed lines
  // instead of guessing where an envelope ends.
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
  const testText = await desktopTestApi()?.readArtifactText?.(path);
  if (typeof testText === "string") {
    return testText;
  }
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
  // Artifact JSON is UI state authority. A parse failure must look missing so
  // the desktop app does not treat half-written files as valid evidence.
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

export function resolveArtifactMediaUrl(path: string): string | null {
  const mockUrl = desktopTestApi()?.resolveMediaUrl?.(path);
  if (typeof mockUrl === "string" && mockUrl.trim()) {
    return mockUrl.trim();
  }

  const normalized = normalizePath(path);
  if (!normalized) {
    return null;
  }
  // Filesystem paths need the Tauri bridge. Direct media URLs skip that bridge
  // so tests and browser-owned sources keep their original authority.
  if (isDirectMediaUrl(normalized)) {
    return normalized;
  }
  if (!isTauriRuntime()) {
    return null;
  }
  try {
    return convertFileSrc(normalized);
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

  // Replay buffered output through the same line parser as streaming runs so
  // short stages and long stages leave the same operator-facing timeline.
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
  // Keep the raw byte stream and the parsed line view in lockstep. Render
  // progress needs live payloads, but failure summaries still rely on raw text.
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
  const timeoutMs = options.timeoutMs ?? DEFAULT_RPC_TIMEOUT_MS;
  if (!isTauriRuntime()) {
    const mockResult = await desktopTestApi()?.runMmoRpc?.(method, params, { timeoutMs });
    if (mockResult !== null && mockResult !== undefined) {
      return mockResult as T;
    }
    throw new Error("MMO GUI RPC is only available in the Tauri desktop runtime.");
  }

  const command = createSidecar(["gui", "rpc"], options);
  const stdoutBuffer = new LineBuffer();
  let child: Child | null = null;
  try {
    // Give each RPC call its own short-lived sidecar. Reusing a child would let
    // stale stdout, stderr, or request state leak across desktop screens.
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
          // Only a complete JSONL envelope counts as a reply. Partial lines stay
          // buffered until close so a short write does not become fake success.
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
          // If the RPC child exits without a final envelope, keep the captured
          // output in the thrown error. That is often the only startup clue.
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
    // Always tear down the helper after one request. Hung children would keep
    // file handles and sidecar state alive after the desktop UI moved on.
    const activeChild = child as { kill: () => Promise<void> } | null;
    if (activeChild !== null) {
      await activeChild.kill().catch(() => undefined);
    }
  }
}
