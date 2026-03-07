import { revealItemInDir } from "@tauri-apps/plugin-opener";

import {
  buildWorkflowPaths,
  executeMmo,
  spawnMmo,
  type MmoLivePayload,
  type MmoLogKind,
  type MmoRunResult,
  type WorkflowPaths,
} from "./mmo-sidecar";

type StageKey = "analyze" | "doctor" | "prepare" | "render" | "validate";
type StageState = "fail" | "idle" | "pass" | "running";

type DoctorPayload = {
  paths?: Record<string, string>;
  python?: { executable?: string; version?: string };
};

type PluginValidationPayload = {
  issue_counts?: { error?: number };
  ok?: boolean;
  plugin_count?: number;
  plugins_dir?: string;
};

type ProjectInitPayload = {
  assignment_count?: number;
  bus_groups_count?: number;
  file_count?: number;
  out_dir?: string;
  paths_written?: string[];
};

type ProjectValidationPayload = {
  ok?: boolean;
  summary?: {
    invalid?: number;
    missing?: number;
    total?: number;
    valid?: number;
  };
};

type StageElements = {
  output: HTMLElement;
  status: HTMLElement;
};

type AppUi = {
  artifactPaths: HTMLElement;
  buttons: Record<
    "analyze" | "doctor" | "prepare" | "render" | "reveal" | "runAll" | "validate",
    HTMLButtonElement
  >;
  inputs: {
    layoutStandard: HTMLSelectElement;
    renderTarget: HTMLSelectElement;
    stemsDir: HTMLInputElement;
    workspaceDir: HTMLInputElement;
  };
  runtimeMessage: HTMLElement;
  stages: Record<StageKey, StageElements>;
  timeline: HTMLElement;
};

const state = {
  busy: false,
  timelineCount: 0,
};

function checkElements(): AppUi {
  const doctorButton = document.querySelector<HTMLButtonElement>("#doctor-run-button");
  const prepareButton = document.querySelector<HTMLButtonElement>("#workflow-prepare-button");
  const validateButton = document.querySelector<HTMLButtonElement>("#workflow-validate-button");
  const analyzeButton = document.querySelector<HTMLButtonElement>("#workflow-analyze-button");
  const renderButton = document.querySelector<HTMLButtonElement>("#workflow-render-button");
  const runAllButton = document.querySelector<HTMLButtonElement>("#workflow-run-all-button");
  const revealButton = document.querySelector<HTMLButtonElement>("#workspace-reveal-button");
  const stemsDir = document.querySelector<HTMLInputElement>("#stems-dir-input");
  const workspaceDir = document.querySelector<HTMLInputElement>("#workspace-dir-input");
  const renderTarget = document.querySelector<HTMLSelectElement>("#render-target-select");
  const layoutStandard = document.querySelector<HTMLSelectElement>("#layout-standard-select");
  const runtimeMessage = document.querySelector<HTMLElement>("#runtime-message");
  const artifactPaths = document.querySelector<HTMLElement>("#artifact-paths");
  const timeline = document.querySelector<HTMLElement>("#timeline-list");

  const stageOutputs = {
    doctor: document.querySelector<HTMLElement>("#output-doctor"),
    prepare: document.querySelector<HTMLElement>("#output-prepare"),
    validate: document.querySelector<HTMLElement>("#output-validate"),
    analyze: document.querySelector<HTMLElement>("#output-analyze"),
    render: document.querySelector<HTMLElement>("#output-render"),
  };
  const stageStatuses = {
    doctor: document.querySelector<HTMLElement>("#status-doctor"),
    prepare: document.querySelector<HTMLElement>("#status-prepare"),
    validate: document.querySelector<HTMLElement>("#status-validate"),
    analyze: document.querySelector<HTMLElement>("#status-analyze"),
    render: document.querySelector<HTMLElement>("#status-render"),
  };

  if (
    !doctorButton ||
    !prepareButton ||
    !validateButton ||
    !analyzeButton ||
    !renderButton ||
    !runAllButton ||
    !revealButton ||
    !stemsDir ||
    !workspaceDir ||
    !renderTarget ||
    !layoutStandard ||
    !runtimeMessage ||
    !artifactPaths ||
    !timeline ||
    !stageOutputs.doctor ||
    !stageOutputs.prepare ||
    !stageOutputs.validate ||
    !stageOutputs.analyze ||
    !stageOutputs.render ||
    !stageStatuses.doctor ||
    !stageStatuses.prepare ||
    !stageStatuses.validate ||
    !stageStatuses.analyze ||
    !stageStatuses.render
  ) {
    throw new Error("Desktop workflow UI is missing required DOM nodes.");
  }

  return {
    artifactPaths,
    buttons: {
      analyze: analyzeButton,
      doctor: doctorButton,
      prepare: prepareButton,
      render: renderButton,
      reveal: revealButton,
      runAll: runAllButton,
      validate: validateButton,
    },
    inputs: {
      layoutStandard,
      renderTarget,
      stemsDir,
      workspaceDir,
    },
    runtimeMessage,
    stages: {
      analyze: { output: stageOutputs.analyze, status: stageStatuses.analyze },
      doctor: { output: stageOutputs.doctor, status: stageStatuses.doctor },
      prepare: { output: stageOutputs.prepare, status: stageStatuses.prepare },
      render: { output: stageOutputs.render, status: stageStatuses.render },
      validate: { output: stageOutputs.validate, status: stageStatuses.validate },
    },
    timeline,
  };
}

function setStageStatus(
  element: HTMLElement,
  stateValue: StageState,
  label: string,
): void {
  element.textContent = label;
  element.className = `stage-status stage-status-${stateValue}`;
}

function parseJsonObject<T>(rawText: string): T | null {
  const trimmed = rawText.trim();
  if (!trimmed) {
    return null;
  }
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as T;
    }
  } catch {
    return null;
  }
  return null;
}

function formatExitSummary(result: MmoRunResult): string {
  return `exit=${result.code ?? "null"} signal=${result.signal ?? "null"}`;
}

function formatFailureOutput(result: MmoRunResult): string {
  const lines = [formatExitSummary(result)];
  if (result.stderr.trim()) {
    lines.push(`stderr: ${result.stderr.trim()}`);
  }
  if (result.stdout.trim()) {
    lines.push(`stdout: ${result.stdout.trim()}`);
  }
  return lines.join("\n");
}

function summarizePrepare(result: MmoRunResult, payload: ProjectInitPayload | null): string {
  if (payload === null) {
    return formatFailureOutput(result);
  }

  return [
    formatExitSummary(result),
    `project_dir=${payload.out_dir ?? "-"}`,
    `stems=${payload.file_count ?? 0}`,
    `assignments=${payload.assignment_count ?? 0}`,
    `bus_groups=${payload.bus_groups_count ?? 0}`,
    `paths_written=${Array.isArray(payload.paths_written) ? payload.paths_written.length : 0}`,
  ].join("\n");
}

function summarizeValidation(
  mode: string,
  result: MmoRunResult,
  payload: ProjectValidationPayload | null,
): string {
  if (payload === null) {
    return formatFailureOutput(result);
  }

  return [
    formatExitSummary(result),
    `mode=${mode}`,
    `ok=${payload.ok === true}`,
    `valid=${payload.summary?.valid ?? 0}`,
    `missing=${payload.summary?.missing ?? 0}`,
    `invalid=${payload.summary?.invalid ?? 0}`,
    `checks=${payload.summary?.total ?? 0}`,
  ].join("\n");
}

function summarizeAnalyze(result: MmoRunResult, paths: WorkflowPaths): string {
  const stderrTail = result.stderr.trim().split(/\r?\n/).filter(Boolean).slice(-1)[0] ?? "";
  const lines = [
    formatExitSummary(result),
    `report=${paths.reportPath}`,
    `scan=${paths.scanReportPath}`,
  ];
  if (stderrTail) {
    lines.push(`tail=${stderrTail}`);
  }
  return lines.join("\n");
}

function summarizeRender(result: MmoRunResult, paths: WorkflowPaths, targetToken: string): string {
  const stderrLines = result.stderr.trim().split(/\r?\n/).filter(Boolean);
  const tail = stderrLines.slice(-2);
  const lines = [
    formatExitSummary(result),
    `target=${targetToken}`,
    `render_dir=${paths.renderDir}`,
    `manifest=${paths.renderManifestPath}`,
    `receipt=${paths.renderReceiptPath}`,
    `qa=${paths.renderQaPath}`,
  ];
  if (tail.length > 0) {
    lines.push(...tail.map((line) => `log=${line}`));
  }
  return lines.join("\n");
}

function summarizeDoctor(
  versionResult: MmoRunResult,
  pluginsResult: MmoRunResult,
  envDoctorResult: MmoRunResult,
  pluginsPayload: PluginValidationPayload | null,
  envDoctorPayload: DoctorPayload | null,
): string {
  const pathKeys = [
    "data_root",
    "presets_dir",
    "ontology_dir",
    "schemas_dir",
    "cache_dir",
    "temp_dir",
  ];
  const lines = [
    `version=${versionResult.stdout.trim() || "-"}`,
    `plugins_ok=${pluginsPayload?.ok === true}`,
    `plugins=${pluginsPayload?.plugin_count ?? 0}`,
    `plugins_dir=${pluginsPayload?.plugins_dir ?? "-"}`,
    `python=${envDoctorPayload?.python?.executable ?? "-"}`,
    `python_version=${envDoctorPayload?.python?.version ?? "-"}`,
  ];
  for (const key of pathKeys) {
    const value = envDoctorPayload?.paths?.[key];
    if (value) {
      lines.push(`${key}=${value}`);
    }
  }
  lines.push(
    `checks=${[
      versionResult.code === 0 ? "version:pass" : "version:fail",
      pluginsResult.code === 0 ? "plugins:pass" : "plugins:fail",
      envDoctorResult.code === 0 ? "env:pass" : "env:fail",
    ].join(",")}`,
  );
  return lines.join("\n");
}

function quoteArg(value: string): string {
  if (!value || /\s|["']/u.test(value)) {
    return JSON.stringify(value);
  }
  return value;
}

function appendTimeline(
  ui: AppUi,
  stage: StageKey,
  kind: MmoLogKind,
  text: string,
  payload: MmoLivePayload | null = null,
): void {
  if (state.timelineCount >= 400) {
    ui.timeline.firstElementChild?.remove();
    state.timelineCount -= 1;
  }

  const item = document.createElement("article");
  item.className = `timeline-item timeline-item-${kind}`;

  const heading = document.createElement("div");
  heading.className = "timeline-item-heading";

  const badge = document.createElement("span");
  badge.className = "timeline-badge";
  badge.textContent = stage;

  const stream = document.createElement("span");
  stream.className = "timeline-stream";
  stream.textContent = kind;

  const stamp = document.createElement("time");
  stamp.className = "timeline-stamp";
  stamp.textContent = new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  heading.append(badge, stream, stamp);

  const body = document.createElement("p");
  body.className = "timeline-item-body";
  body.textContent = text;

  item.append(heading, body);

  if (payload !== null && Array.isArray(payload.where) && payload.where.length > 0) {
    const meta = document.createElement("p");
    meta.className = "timeline-item-meta";
    meta.textContent = payload.where.join(" | ");
    item.append(meta);
  }

  ui.timeline.append(item);
  ui.timeline.scrollTop = ui.timeline.scrollHeight;
  state.timelineCount += 1;
}

function appendMeta(ui: AppUi, stage: StageKey, text: string): void {
  appendTimeline(ui, stage, "stdout", text);
}

function clearTimeline(ui: AppUi): void {
  ui.timeline.innerHTML = "";
  state.timelineCount = 0;
}

function setBusy(ui: AppUi, busy: boolean): void {
  state.busy = busy;
  for (const button of Object.values(ui.buttons)) {
    if (button === ui.buttons.reveal) {
      button.disabled = busy || !ui.inputs.workspaceDir.value.trim();
      continue;
    }
    button.disabled = busy;
  }
}

function updateRuntimeMessage(ui: AppUi, text: string): void {
  ui.runtimeMessage.textContent = text;
}

function renderArtifactPaths(ui: AppUi): void {
  const workspaceDir = ui.inputs.workspaceDir.value.trim();
  ui.artifactPaths.innerHTML = "";

  if (!workspaceDir) {
    const row = document.createElement("div");
    row.className = "path-row";

    const dt = document.createElement("dt");
    dt.textContent = "workspace";

    const dd = document.createElement("dd");
    dd.textContent = "Enter a workspace folder to preview deterministic artifact paths.";

    row.append(dt, dd);
    ui.artifactPaths.append(row);
    ui.buttons.reveal.disabled = true;
    return;
  }

  const paths = buildWorkflowPaths(workspaceDir);
  const rows: Array<[string, string]> = [
    ["workspace", paths.workspaceDir],
    ["project", paths.projectDir],
    ["project validate", paths.projectValidationPath],
    ["analysis report", paths.reportPath],
    ["analysis scan", paths.scanReportPath],
    ["render dir", paths.renderDir],
    ["render manifest", paths.renderManifestPath],
    ["safe-render receipt", paths.renderReceiptPath],
    ["render qa", paths.renderQaPath],
  ];

  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "path-row";

    const dt = document.createElement("dt");
    dt.textContent = label;

    const dd = document.createElement("dd");
    dd.textContent = value;

    row.append(dt, dd);
    ui.artifactPaths.append(row);
  }

  ui.buttons.reveal.disabled = state.busy;
}

function updateRenderProgress(ui: AppUi, payload: MmoLivePayload): void {
  const progressText = typeof payload.progress === "number"
    ? `${Math.round(payload.progress * 100)}%`
    : "live";
  const scope = typeof payload.scope === "string" && payload.scope.trim()
    ? payload.scope.trim()
    : "render";
  const what = typeof payload.what === "string" && payload.what.trim()
    ? payload.what.trim()
    : "progress update";
  ui.stages.render.output.textContent = `${progressText}\n${scope}\n${what}`;
}

function collectInputs(ui: AppUi): {
  layoutStandard: string;
  paths: WorkflowPaths;
  renderTarget: string;
  stemsDir: string;
} {
  const stemsDir = ui.inputs.stemsDir.value.trim();
  const workspaceDir = ui.inputs.workspaceDir.value.trim();
  if (!stemsDir) {
    throw new Error("Enter a stems folder path first.");
  }
  if (!workspaceDir) {
    throw new Error("Enter a workspace folder path first.");
  }

  return {
    layoutStandard: ui.inputs.layoutStandard.value,
    paths: buildWorkflowPaths(workspaceDir),
    renderTarget: ui.inputs.renderTarget.value,
    stemsDir,
  };
}

function assertSuccess(result: MmoRunResult, stageLabel: string): void {
  if (result.code === 0) {
    return;
  }
  throw new Error(`${stageLabel} failed (${formatExitSummary(result)}).`);
}

async function runExecuteCommand(
  ui: AppUi,
  stage: StageKey,
  args: string[],
): Promise<MmoRunResult> {
  appendMeta(ui, stage, `$ mmo ${args.map(quoteArg).join(" ")}`);
  const result = await executeMmo(args, {
    onLogLine: (line) => {
      appendTimeline(ui, stage, line.kind, line.text, line.payload);
      if (stage === "render" && line.payload !== null) {
        updateRenderProgress(ui, line.payload);
      }
    },
  });
  appendMeta(ui, stage, formatExitSummary(result));
  return result;
}

async function runSpawnCommand(
  ui: AppUi,
  stage: StageKey,
  args: string[],
): Promise<MmoRunResult> {
  appendMeta(ui, stage, `$ mmo ${args.map(quoteArg).join(" ")}`);
  const result = await spawnMmo(args, {
    onLogLine: (line) => {
      appendTimeline(ui, stage, line.kind, line.text, line.payload);
      if (stage === "render" && line.payload !== null) {
        updateRenderProgress(ui, line.payload);
      }
    },
  });
  appendMeta(ui, stage, formatExitSummary(result));
  return result;
}

async function runDoctor(ui: AppUi): Promise<void> {
  const { output, status } = ui.stages.doctor;
  setStageStatus(status, "running", "Running");
  output.textContent = "Launching sidecar health checks.";
  updateRuntimeMessage(ui, "Running sidecar doctor checks.");

  const versionResult = await runExecuteCommand(ui, "doctor", ["--version"]);
  const pluginsResult = await runExecuteCommand(ui, "doctor", [
    "plugins",
    "validate",
    "--bundled-only",
    "--format",
    "json",
  ]);
  const envDoctorResult = await runExecuteCommand(ui, "doctor", [
    "env",
    "doctor",
    "--format",
    "json",
  ]);

  const pluginsPayload = parseJsonObject<PluginValidationPayload>(pluginsResult.stdout);
  const envDoctorPayload = parseJsonObject<DoctorPayload>(envDoctorResult.stdout);
  output.textContent = summarizeDoctor(
    versionResult,
    pluginsResult,
    envDoctorResult,
    pluginsPayload,
    envDoctorPayload,
  );

  const ok =
    versionResult.code === 0 &&
    pluginsResult.code === 0 &&
    envDoctorResult.code === 0;
  setStageStatus(status, ok ? "pass" : "fail", ok ? "Pass" : "Fail");
  updateRuntimeMessage(
    ui,
    ok
      ? "Doctor passed. The packaged sidecar is ready."
      : "Doctor failed. Check the timeline for the blocked command.",
  );
}

async function runPrepare(ui: AppUi): Promise<void> {
  const { paths, stemsDir } = collectInputs(ui);
  const { output, status } = ui.stages.prepare;
  setStageStatus(status, "running", "Running");
  output.textContent = `Writing project scaffold to\n${paths.projectDir}`;
  updateRuntimeMessage(ui, "Preparing project scaffold inside the workspace.");

  const result = await runExecuteCommand(ui, "prepare", [
    "project",
    "init",
    "--stems-root",
    stemsDir,
    "--out-dir",
    paths.projectDir,
    "--force",
  ]);
  const payload = parseJsonObject<ProjectInitPayload>(result.stdout);
  output.textContent = summarizePrepare(result, payload);
  setStageStatus(status, result.code === 0 ? "pass" : "fail", result.code === 0 ? "Pass" : "Fail");
  updateRuntimeMessage(
    ui,
    result.code === 0
      ? "Project scaffold refreshed."
      : "Project scaffold failed. Review stderr lines in the timeline.",
  );
  assertSuccess(result, "prepare");
}

async function runValidate(ui: AppUi): Promise<void> {
  const { paths } = collectInputs(ui);
  const { output, status } = ui.stages.validate;
  setStageStatus(status, "running", "Running");
  output.textContent = `Validating project artifacts in\n${paths.projectDir}`;
  updateRuntimeMessage(ui, "Validating the workspace project contract.");

  const result = await runExecuteCommand(ui, "validate", [
    "project",
    "validate",
    paths.projectDir,
    "--out",
    paths.projectValidationPath,
  ]);
  const payload = parseJsonObject<ProjectValidationPayload>(result.stdout);
  output.textContent = summarizeValidation("project", result, payload);
  setStageStatus(status, result.code === 0 ? "pass" : "fail", result.code === 0 ? "Pass" : "Fail");
  updateRuntimeMessage(
    ui,
    result.code === 0
      ? "Project validation passed."
      : "Project validation failed. Review the generated validation JSON and timeline.",
  );
  assertSuccess(result, "validate");
}

async function runAnalyze(ui: AppUi): Promise<void> {
  const { paths, stemsDir } = collectInputs(ui);
  const { output, status } = ui.stages.analyze;
  setStageStatus(status, "running", "Running");
  output.textContent = `Analyzing stems into\n${paths.reportPath}`;
  updateRuntimeMessage(ui, "Analyzing stems with the packaged MMO sidecar.");

  const result = await runSpawnCommand(ui, "analyze", [
    "analyze",
    stemsDir,
    "--out-report",
    paths.reportPath,
    "--cache",
    "off",
    "--keep-scan",
  ]);
  output.textContent = summarizeAnalyze(result, paths);
  setStageStatus(status, result.code === 0 ? "pass" : "fail", result.code === 0 ? "Pass" : "Fail");
  updateRuntimeMessage(
    ui,
    result.code === 0
      ? "Analysis completed."
      : "Analysis failed. Review the timeline and generated report artifacts.",
  );
  assertSuccess(result, "analyze");
}

async function runRender(ui: AppUi): Promise<void> {
  const { layoutStandard, paths, renderTarget } = collectInputs(ui);
  const { output, status } = ui.stages.render;
  setStageStatus(status, "running", "Running");
  output.textContent = `Launching safe-render for ${renderTarget}`;
  updateRuntimeMessage(ui, "Rendering from the analyzed report with live sidecar logs.");

  const result = await runSpawnCommand(ui, "render", [
    "safe-render",
    "--report",
    paths.reportPath,
    "--target",
    renderTarget,
    "--out-dir",
    paths.renderDir,
    "--out-manifest",
    paths.renderManifestPath,
    "--receipt-out",
    paths.renderReceiptPath,
    "--qa-out",
    paths.renderQaPath,
    "--layout-standard",
    layoutStandard,
    "--live-progress",
    "--force",
  ]);
  output.textContent = summarizeRender(result, paths, renderTarget);
  setStageStatus(status, result.code === 0 ? "pass" : "fail", result.code === 0 ? "Pass" : "Fail");
  updateRuntimeMessage(
    ui,
    result.code === 0
      ? "Render completed and wrote artifacts into the workspace."
      : "Render failed. Check the safe-render timeline lines for the blocked phase.",
  );
  assertSuccess(result, "render");
}

async function runWithBusy(ui: AppUi, action: () => Promise<void>, clearLogs = false): Promise<void> {
  if (state.busy) {
    return;
  }

  setBusy(ui, true);
  if (clearLogs) {
    clearTimeline(ui);
  }

  try {
    await action();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    updateRuntimeMessage(ui, detail);
  } finally {
    setBusy(ui, false);
    renderArtifactPaths(ui);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  const ui = checkElements();

  for (const stage of Object.values(ui.stages)) {
    setStageStatus(stage.status, "idle", "Idle");
  }

  renderArtifactPaths(ui);
  updateRuntimeMessage(
    ui,
    "Enter a stems folder and workspace folder. Desktop builds call the MMO sidecar directly.",
  );

  ui.inputs.workspaceDir.addEventListener("input", () => {
    renderArtifactPaths(ui);
  });
  ui.inputs.stemsDir.addEventListener("input", () => {
    renderArtifactPaths(ui);
  });

  ui.buttons.doctor.addEventListener("click", () => {
    void runWithBusy(ui, async () => {
      await runDoctor(ui);
    }, true);
  });

  ui.buttons.prepare.addEventListener("click", () => {
    void runWithBusy(ui, async () => {
      await runPrepare(ui);
    }, true);
  });

  ui.buttons.validate.addEventListener("click", () => {
    void runWithBusy(ui, async () => {
      await runValidate(ui);
    }, true);
  });

  ui.buttons.analyze.addEventListener("click", () => {
    void runWithBusy(ui, async () => {
      await runAnalyze(ui);
    }, true);
  });

  ui.buttons.render.addEventListener("click", () => {
    void runWithBusy(ui, async () => {
      await runRender(ui);
    }, true);
  });

  ui.buttons.runAll.addEventListener("click", () => {
    void runWithBusy(ui, async () => {
      await runPrepare(ui);
      await runValidate(ui);
      await runAnalyze(ui);
      await runRender(ui);
    }, true);
  });

  ui.buttons.reveal.addEventListener("click", async () => {
    const workspaceDir = ui.inputs.workspaceDir.value.trim();
    if (!workspaceDir) {
      updateRuntimeMessage(ui, "Enter a workspace folder path before revealing it.");
      return;
    }
    try {
      await revealItemInDir(buildWorkflowPaths(workspaceDir).workspaceDir);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      updateRuntimeMessage(ui, `Unable to reveal the workspace: ${detail}`);
    }
  });
});
