import { Command } from "@tauri-apps/plugin-shell";

const SIDECAR_NAME = "binaries/mmo";
const LIVE_PREFIX = "[MMO-LIVE] ";

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

export type WorkflowPaths = {
  projectDir: string;
  projectValidationPath: string;
  renderDir: string;
  renderManifestPath: string;
  renderQaPath: string;
  renderReceiptPath: string;
  reportPath: string;
  scanReportPath: string;
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

function normalizePath(pathValue: string): string {
  return pathValue.trim().replace(/\\/g, "/").replace(/\/+$/, "");
}

function joinPath(basePath: string, leafName: string): string {
  const normalizedBase = normalizePath(basePath);
  if (!normalizedBase) {
    return leafName;
  }
  return `${normalizedBase}/${leafName}`;
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

export function buildWorkflowPaths(workspaceDir: string): WorkflowPaths {
  const normalizedWorkspaceDir = normalizePath(workspaceDir);
  const projectDir = joinPath(normalizedWorkspaceDir, "project");

  return {
    projectDir,
    projectValidationPath: joinPath(projectDir, "validation.json"),
    renderDir: joinPath(normalizedWorkspaceDir, "render"),
    renderManifestPath: joinPath(normalizedWorkspaceDir, "render_manifest.json"),
    renderQaPath: joinPath(normalizedWorkspaceDir, "render_qa.json"),
    renderReceiptPath: joinPath(normalizedWorkspaceDir, "safe_render_receipt.json"),
    reportPath: joinPath(normalizedWorkspaceDir, "report.json"),
    scanReportPath: joinPath(normalizedWorkspaceDir, "report.scan.json"),
    workspaceDir: normalizedWorkspaceDir,
  };
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
