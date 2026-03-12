import { revealItemInDir } from "@tauri-apps/plugin-opener";

import {
  clamp,
  initDesignSystem,
  roundToStep,
  signedNumber,
} from "./design-system";
import {
  artifactExists,
  buildWorkflowPaths,
  executeMmo,
  joinPath,
  readArtifactJson,
  resolveSiblingPath,
  spawnMmo,
  type MmoLivePayload,
  type MmoLogKind,
  type MmoRunResult,
  type WorkflowPaths,
  writeArtifactText,
} from "./mmo-sidecar";

type CommandStage = "analyze" | "compare" | "doctor" | "render" | "scene" | "validate";
type StageKey = Exclude<CommandStage, "doctor">;
type StageState = "fail" | "idle" | "pass" | "running";
type CompareState = "A" | "B";
type ArtifactTag = "ALL" | "AUDIO" | "JSON" | "QA" | "RECEIPT";

type JsonObject = Record<string, unknown>;

type ArtifactEntry = {
  id: string;
  path: string;
  previewText: string;
  summary: string;
  tag: ArtifactTag;
  title: string;
};

type ArtifactState = {
  compare: JsonObject | null;
  compareAQa: JsonObject | null;
  compareBQa: JsonObject | null;
  manifest: JsonObject | null;
  qa: JsonObject | null;
  receipt: JsonObject | null;
  report: JsonObject | null;
  scan: JsonObject | null;
  scene: JsonObject | null;
  sceneLint: JsonObject | null;
  validation: JsonObject | null;
};

type ArtifactSourceState = {
  comparePath: string;
  compareAQaPath: string;
  compareBQaPath: string;
  manifestPath: string;
  qaPath: string;
  receiptPath: string;
  reportPath: string;
  scanPath: string;
  scenePath: string;
  sceneLintPath: string;
  validationPath: string;
};

type DragState = {
  onMove: (event: PointerEvent) => void;
  onUp: (event: PointerEvent) => void;
  pointerId: number;
  surface: HTMLElement;
};

type AppUi = {
  abButtons: HTMLButtonElement[];
  artifactPaths: HTMLElement;
  artifactPreviewDelta: HTMLElement;
  artifactPreviewName: HTMLElement;
  artifactPreviewSummary: HTMLElement;
  artifactSearch: HTMLInputElement;
  artifactTagButtons: HTMLButtonElement[];
  buttons: Record<
    "analyze" | "compare" | "doctor" | "render" | "renderCancel" | "resultsRefresh" | "reveal" | "runAll" | "scene" | "validate",
    HTMLButtonElement
  >;
  compareCompensation: {
    input: HTMLInputElement;
    knob: HTMLButtonElement;
    value: HTMLElement;
  };
  compareInputs: {
    aPath: HTMLInputElement;
    bPath: HTMLInputElement;
  };
  compareJsonPreview: HTMLElement;
  compareReadoutPrimary: HTMLElement;
  compareReadoutSecondary: HTMLElement;
  compareSummary: HTMLElement;
  compareSummaryNote: HTMLElement;
  fileInputs: Record<
    "analyzeReport" | "analyzeScan" | "compareAQa" | "compareBQa" | "compareReport" | "resultsManifest" | "resultsQa" | "resultsReceipt" | "sceneJson" | "sceneLint" | "validateValidation",
    HTMLInputElement
  >;
  inputs: {
    layoutStandard: HTMLSelectElement;
    renderTarget: HTMLSelectElement;
    sceneFocusDepth: HTMLInputElement;
    sceneFocusPan: HTMLInputElement;
    sceneLocksPath: HTMLInputElement;
    stemsDir: HTMLInputElement;
    workspaceDir: HTMLInputElement;
  };
  nerdView: {
    state: HTMLElement;
    toggle: HTMLButtonElement;
  };
  output: Record<CommandStage, HTMLElement>;
  renderConfigSummary: HTMLElement;
  renderOutputText: HTMLElement;
  renderProgressText: HTMLElement;
  results: {
    browserList: HTMLElement;
    detailFill: HTMLElement;
    detailInput: HTMLInputElement;
    detailSlider: HTMLButtonElement;
    detailValue: HTMLElement;
    jsonPreview: HTMLElement;
    qaText: HTMLElement;
    readoutNote: HTMLElement;
    readoutPrimary: HTMLElement;
    readoutSecondary: HTMLElement;
    whatChangedText: HTMLElement;
  };
  runtimeMessage: HTMLElement;
  scene: {
    focusCaption: HTMLElement;
    focusDot: HTMLElement;
    focusPad: HTMLButtonElement;
    jsonPreview: HTMLElement;
    locksText: HTMLElement;
    objectsList: HTMLElement;
    summaryText: HTMLElement;
  };
  stages: Record<StageKey, HTMLElement>;
  timeline: HTMLElement;
  validate: {
    artifactPaths: HTMLElement;
    jsonPreview: HTMLElement;
    summaryText: HTMLElement;
  };
  analyze: {
    jsonPreview: HTMLElement;
    scanText: HTMLElement;
    summaryText: HTMLElement;
  };
};

const state = {
  artifacts: {
    compare: null,
    compareAQa: null,
    compareBQa: null,
    manifest: null,
    qa: null,
    receipt: null,
    report: null,
    scan: null,
    scene: null,
    sceneLint: null,
    validation: null,
  } as ArtifactState,
  artifactSources: {
    comparePath: "",
    compareAQaPath: "",
    compareBQaPath: "",
    manifestPath: "",
    qaPath: "",
    receiptPath: "",
    reportPath: "",
    scanPath: "",
    scenePath: "",
    sceneLintPath: "",
    validationPath: "",
  } as ArtifactSourceState,
  busyStage: null as CommandStage | null,
  compareCompensationDb: 0,
  compareCompensationSource: "none" as "manual" | "none" | "render_qa",
  compareState: "A" as CompareState,
  currentCancelPath: null as string | null,
  dragState: null as DragState | null,
  nerdView: false,
  resultsArtifactSearch: "",
  resultsArtifactTag: "ALL" as ArtifactTag,
  resultsDetailLevel: 6,
  selectedArtifactId: "",
  sceneFocusDepth: 50,
  sceneFocusPan: 0,
  timelineCount: 0,
};

function requiredElement<T extends HTMLElement>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (element === null) {
    throw new Error(`Missing required desktop workflow node: ${selector}`);
  }
  return element;
}

function getUi(): AppUi {
  return {
    abButtons: Array.from(document.querySelectorAll<HTMLButtonElement>("#ab-toggle [data-ab-state]")),
    artifactPaths: requiredElement("#artifact-paths"),
    artifactPreviewDelta: requiredElement("#artifact-preview-delta"),
    artifactPreviewName: requiredElement("#artifact-preview-name"),
    artifactPreviewSummary: requiredElement("#artifact-preview-summary"),
    artifactSearch: requiredElement("#artifact-search"),
    artifactTagButtons: Array.from(
      document.querySelectorAll<HTMLButtonElement>("#artifact-tag-row [data-artifact-tag]"),
    ),
    buttons: {
      analyze: requiredElement("#workflow-analyze-button"),
      compare: requiredElement("#workflow-compare-button"),
      doctor: requiredElement("#doctor-run-button"),
      render: requiredElement("#workflow-render-button"),
      renderCancel: requiredElement("#render-cancel-button"),
      resultsRefresh: requiredElement("#results-refresh-button"),
      reveal: requiredElement("#workspace-reveal-button"),
      runAll: requiredElement("#workflow-run-all-button"),
      scene: requiredElement("#workflow-scene-button"),
      validate: requiredElement("#workflow-validate-button"),
    },
    compareCompensation: {
      input: requiredElement("#compare-compensation-input"),
      knob: requiredElement("#compare-compensation-knob"),
      value: requiredElement("#compare-compensation-value"),
    },
    compareInputs: {
      aPath: requiredElement("#compare-a-input"),
      bPath: requiredElement("#compare-b-input"),
    },
    compareJsonPreview: requiredElement("#compare-json-preview"),
    compareReadoutPrimary: requiredElement("#compare-readout-primary"),
    compareReadoutSecondary: requiredElement("#compare-readout-secondary"),
    compareSummary: requiredElement("#compare-summary"),
    compareSummaryNote: requiredElement("#compare-summary-note"),
    fileInputs: {
      analyzeReport: requiredElement("#analyze-report-file-input"),
      analyzeScan: requiredElement("#analyze-scan-file-input"),
      compareAQa: requiredElement("#compare-a-qa-file-input"),
      compareBQa: requiredElement("#compare-b-qa-file-input"),
      compareReport: requiredElement("#compare-report-file-input"),
      resultsManifest: requiredElement("#results-manifest-file-input"),
      resultsQa: requiredElement("#results-qa-file-input"),
      resultsReceipt: requiredElement("#results-receipt-file-input"),
      sceneJson: requiredElement("#scene-json-file-input"),
      sceneLint: requiredElement("#scene-lint-file-input"),
      validateValidation: requiredElement("#validate-validation-file-input"),
    },
    inputs: {
      layoutStandard: requiredElement("#layout-standard-select"),
      renderTarget: requiredElement("#render-target-select"),
      sceneFocusDepth: requiredElement("#scene-focus-depth-input"),
      sceneFocusPan: requiredElement("#scene-focus-pan-input"),
      sceneLocksPath: requiredElement("#scene-locks-input"),
      stemsDir: requiredElement("#stems-dir-input"),
      workspaceDir: requiredElement("#workspace-dir-input"),
    },
    nerdView: {
      state: requiredElement("#nerd-view-state"),
      toggle: requiredElement("#nerd-view-toggle"),
    },
    output: {
      analyze: requiredElement("#output-analyze"),
      compare: requiredElement("#output-compare"),
      doctor: requiredElement("#doctor-run-button"),
      render: requiredElement("#output-render"),
      scene: requiredElement("#output-scene"),
      validate: requiredElement("#output-validate"),
    },
    renderConfigSummary: requiredElement("#render-config-summary"),
    renderOutputText: requiredElement("#render-output-text"),
    renderProgressText: requiredElement("#render-progress-text"),
    results: {
      browserList: requiredElement("#artifact-browser-list"),
      detailFill: requiredElement("#results-detail-fill"),
      detailInput: requiredElement("#results-detail-input"),
      detailSlider: requiredElement("#results-detail-slider"),
      detailValue: requiredElement("#results-detail-value"),
      jsonPreview: requiredElement("#results-json-preview"),
      qaText: requiredElement("#results-qa-text"),
      readoutNote: requiredElement("#results-readout-note"),
      readoutPrimary: requiredElement("#results-readout-primary"),
      readoutSecondary: requiredElement("#results-readout-secondary"),
      whatChangedText: requiredElement("#results-what-changed-text"),
    },
    runtimeMessage: requiredElement("#runtime-message"),
    scene: {
      focusCaption: requiredElement("#scene-focus-caption"),
      focusDot: requiredElement("#scene-focus-dot"),
      focusPad: requiredElement("#scene-focus-pad"),
      jsonPreview: requiredElement("#scene-json-preview"),
      locksText: requiredElement("#scene-locks-text"),
      objectsList: requiredElement("#scene-objects-list"),
      summaryText: requiredElement("#scene-summary-text"),
    },
    stages: {
      analyze: requiredElement("#status-analyze"),
      compare: requiredElement("#status-compare"),
      render: requiredElement("#status-render"),
      scene: requiredElement("#status-scene"),
      validate: requiredElement("#status-validate"),
    },
    timeline: requiredElement("#timeline-list"),
    validate: {
      artifactPaths: requiredElement("#validate-artifact-paths"),
      jsonPreview: requiredElement("#validate-json-preview"),
      summaryText: requiredElement("#validate-summary-text"),
    },
    analyze: {
      jsonPreview: requiredElement("#analyze-json-preview"),
      scanText: requiredElement("#analyze-scan-text"),
      summaryText: requiredElement("#analyze-summary-text"),
    },
  };
}

function asObject(value: unknown): JsonObject | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as JsonObject;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value.trim());
    return Number.isFinite(parsed) ? parsed : null;
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

function truncateLines(text: string, maxLines: number): string {
  const lines = text.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length <= maxLines) {
    return lines.join("\n");
  }
  return `${lines.slice(0, maxLines).join("\n")}\n... (${lines.length - maxLines} more line(s))`;
}

function serializeJson(value: unknown, maxLines: number): string {
  if (value === null) {
    return "null";
  }
  if (value === undefined) {
    return "No artifact loaded.";
  }
  return truncateLines(JSON.stringify(value, null, 2), maxLines);
}

function setStageStatus(element: HTMLElement, stateValue: StageState, label: string): void {
  element.textContent = label;
  element.className = `stage-status stage-status-${stateValue}`;
}

function quoteArg(value: string): string {
  if (!value || /\s|["']/u.test(value)) {
    return JSON.stringify(value);
  }
  return value;
}

function appendTimeline(
  ui: AppUi,
  stage: CommandStage,
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

function appendMeta(ui: AppUi, stage: CommandStage, text: string): void {
  appendTimeline(ui, stage, "stdout", text);
}

function clearTimeline(ui: AppUi): void {
  ui.timeline.innerHTML = "";
  state.timelineCount = 0;
}

function updateRuntimeMessage(ui: AppUi, text: string): void {
  ui.runtimeMessage.textContent = text;
}

function renderNerdView(ui: AppUi): void {
  ui.nerdView.state.textContent = state.nerdView ? "On" : "Off";
  ui.nerdView.state.classList.toggle("status-chip-ok", state.nerdView);
  ui.nerdView.toggle.classList.toggle("is-active", state.nerdView);
  ui.nerdView.toggle.textContent = state.nerdView ? "Nerd view enabled" : "Nerd view disabled";
}

function applyBusyState(ui: AppUi): void {
  const busy = state.busyStage !== null;
  ui.buttons.doctor.disabled = busy;
  ui.buttons.runAll.disabled = busy;
  ui.buttons.validate.disabled = busy;
  ui.buttons.analyze.disabled = busy;
  ui.buttons.scene.disabled = busy;
  ui.buttons.render.disabled = busy;
  ui.buttons.compare.disabled = busy;
  ui.buttons.resultsRefresh.disabled = busy;
  ui.buttons.reveal.disabled = busy || !ui.inputs.workspaceDir.value.trim();
  ui.buttons.renderCancel.disabled = !(busy && state.busyStage === "render" && state.currentCancelPath !== null);
}

function buildRenderCancelPath(paths: WorkflowPaths): string {
  return joinPath(paths.renderCancelDir, `safe_render.cancel.${Date.now().toString(36)}.json`);
}

function collectInputs(ui: AppUi): {
  layoutStandard: string;
  paths: WorkflowPaths;
  renderTarget: string;
  sceneLocksPath: string;
  stemsDir: string;
  workspaceDir: string;
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
    sceneLocksPath: ui.inputs.sceneLocksPath.value.trim(),
    stemsDir,
    workspaceDir,
  };
}

function renderExpectedPaths(ui: AppUi): void {
  const workspaceDir = ui.inputs.workspaceDir.value.trim();
  ui.artifactPaths.innerHTML = "";
  ui.validate.artifactPaths.innerHTML = "";

  if (!workspaceDir) {
    const row = document.createElement("div");
    row.className = "path-row";
    const dt = document.createElement("dt");
    dt.textContent = "workspace";
    const dd = document.createElement("dd");
    dd.textContent = "Enter a workspace folder to preview artifact paths.";
    row.append(dt, dd);
    ui.artifactPaths.append(row);
    ui.validate.artifactPaths.append(row.cloneNode(true));
    applyBusyState(ui);
    return;
  }

  const paths = buildWorkflowPaths(workspaceDir);
  const rows: Array<[string, string]> = [
    ["workspace", paths.workspaceDir],
    ["project", paths.projectDir],
    ["project validation", paths.projectValidationPath],
    ["analysis report", paths.reportPath],
    ["analysis scan", paths.scanReportPath],
    ["stems map", paths.stemsMapPath],
    ["bus plan", paths.busPlanPath],
    ["bus plan csv", paths.busPlanCsvPath],
    ["scene", paths.scenePath],
    ["scene lint", paths.sceneLintPath],
    ["render dir", paths.renderDir],
    ["render manifest", paths.renderManifestPath],
    ["safe-render receipt", paths.renderReceiptPath],
    ["render qa", paths.renderQaPath],
    ["compare report", paths.compareReportPath],
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

    if (label === "project" || label === "project validation") {
      ui.validate.artifactPaths.append(row.cloneNode(true));
    }
  }

  applyBusyState(ui);
}

function summarizeValidationPayload(payload: JsonObject | null): string {
  if (payload === null) {
    return "No validation artifact loaded.";
  }
  const summary = asObject(payload.summary);
  const lines = [
    `ok=${payload.ok === true}`,
    `checks=${asNumber(summary?.total) ?? 0}`,
    `valid=${asNumber(summary?.valid) ?? 0}`,
    `missing=${asNumber(summary?.missing) ?? 0}`,
    `invalid=${asNumber(summary?.invalid) ?? 0}`,
  ];
  return lines.join(" · ");
}

function summarizeAnalyzeArtifacts(report: JsonObject | null): string {
  if (report === null) {
    return "No report loaded.";
  }
  const runConfig = asObject(report.run_config);
  const session = asObject(report.session);
  return [
    asString(report.report_id) || "report",
    `profile=${asString(runConfig?.profile_id) || asString(report.profile_id) || "-"}`,
    `stems=${asArray(session?.stems).length}`,
    `issues=${asArray(report.issues).length}`,
    `recommendations=${asArray(report.recommendations).length}`,
    `translation_risk=${asString(asObject(report.vibe_signals)?.translation_risk) || "unknown"}`,
  ].join(" · ");
}

function summarizeScanArtifact(scan: JsonObject | null): string {
  if (scan === null) {
    return "No scan artifact loaded.";
  }
  const summary = asObject(scan.summary);
  const counts = [
    `files=${asNumber(summary?.file_count) ?? asNumber(scan.file_count) ?? 0}`,
    `stems=${asNumber(summary?.stem_count) ?? 0}`,
    `warnings=${asNumber(summary?.warn_count) ?? 0}`,
  ];
  return counts.join(" · ");
}

type SceneRow = {
  azimuth: number | null;
  confidence: number | null;
  depth: number | null;
  groupBus: string;
  kind: "bed" | "object";
  label: string;
  locks: string[];
  objectId: string;
  roleId: string;
  width: number | null;
};

function formatSceneNumber(value: number | null, digits = 2, suffix = ""): string {
  if (value === null) {
    return "n/a";
  }
  return `${value.toFixed(digits)}${suffix}`;
}

function sceneRows(scene: JsonObject | null): SceneRow[] {
  if (scene === null) {
    return [];
  }
  const rows: SceneRow[] = [];

  for (const item of asArray(scene.objects)) {
    const object = asObject(item);
    if (object === null) {
      continue;
    }
    const intent = asObject(object.intent);
    const position = asObject(intent?.position);
    rows.push({
      azimuth: asNumber(position?.azimuth_deg) ?? asNumber(object.azimuth_hint),
      confidence: asNumber(intent?.confidence) ?? asNumber(object.confidence),
      depth: asNumber(intent?.depth) ?? asNumber(object.depth_hint),
      groupBus: asString(object.group_bus),
      kind: "object",
      label: asString(object.label) || asString(object.object_id),
      locks: asArray(intent?.locks).map(asString).filter(Boolean),
      objectId: asString(object.object_id),
      roleId: asString(object.role_id),
      width: asNumber(intent?.width) ?? asNumber(object.width_hint),
    });
  }

  for (const item of asArray(scene.beds)) {
    const bed = asObject(item);
    if (bed === null) {
      continue;
    }
    const intent = asObject(bed.intent);
    rows.push({
      azimuth: null,
      confidence: asNumber(intent?.confidence) ?? asNumber(bed.confidence),
      depth: asNumber(intent?.diffuse),
      groupBus: asString(bed.bus_id),
      kind: "bed",
      label: asString(bed.label) || asString(bed.bed_id),
      locks: asArray(intent?.locks).map(asString).filter(Boolean),
      objectId: asString(bed.bed_id) || asString(bed.bus_id),
      roleId: asString(bed.kind),
      width: asNumber(bed.width_hint),
    });
  }

  rows.sort((left, right) => left.objectId.localeCompare(right.objectId));
  return rows;
}

function renderSceneSummary(scene: JsonObject | null, lint: JsonObject | null): string {
  if (scene === null) {
    return "No scene artifact loaded.";
  }
  const intent = asObject(scene.intent);
  const lines = ["Perspective:"];
  lines.push(
    `- ${asString(intent?.perspective) || "(unspecified)"} (confidence=${formatSceneNumber(asNumber(intent?.confidence))})`,
  );
  lines.push("", "Objects (azimuth/width/depth/confidence):");

  const objects = sceneRows(scene).filter((row) => row.kind === "object");
  if (objects.length === 0) {
    lines.push("- (none)");
  } else {
    for (const row of objects) {
      const parts = [
        `${row.label} [${row.objectId}]`,
        `azimuth=${formatSceneNumber(row.azimuth, 1, " deg")}`,
        `width=${formatSceneNumber(row.width)}`,
        `depth=${formatSceneNumber(row.depth)}`,
        `confidence=${formatSceneNumber(row.confidence)}`,
      ];
      if (row.roleId) {
        parts.push(`role=${row.roleId}`);
      }
      if (row.groupBus) {
        parts.push(`bus=${row.groupBus}`);
      }
      lines.push(`- ${parts.join(" | ")}`);
    }
  }

  lines.push("", "Bed buses:");
  const beds = sceneRows(scene).filter((row) => row.kind === "bed");
  if (beds.length === 0) {
    lines.push("- (none)");
  } else {
    for (const row of beds) {
      const parts = [
        `${row.groupBus || "(no bus)"} <- ${row.label} [${row.objectId}]`,
        `confidence=${formatSceneNumber(row.confidence)}`,
      ];
      if (row.roleId) {
        parts.push(`kind=${row.roleId}`);
      }
      if (row.width !== null) {
        parts.push(`hint=${formatSceneNumber(row.width)}`);
      }
      lines.push(`- ${parts.join(" | ")}`);
    }
  }

  const lintSummary = asObject(lint?.summary);
  const warnings = asArray(lint?.issues)
    .map(asObject)
    .filter((row): row is JsonObject => row !== null && asString(row.severity).toLowerCase().startsWith("warn"));
  lines.push("", "Scene lint warnings:");
  if (lintSummary !== null) {
    lines.push(
      `- summary: ${asNumber(lintSummary.error_count) ?? 0} error(s), ${asNumber(lintSummary.warn_count) ?? 0} warning(s)`,
    );
  }
  if (warnings.length === 0) {
    lines.push(lint === null ? "- (scene lint report unavailable)" : "- (none)");
  } else {
    for (const row of warnings.slice(0, state.resultsDetailLevel)) {
      const path = asString(row.path);
      const message = asString(row.message);
      const issueId = asString(row.issue_id);
      lines.push(`- ${issueId} ${path}`.trim() + (message ? `: ${message}` : ""));
    }
  }
  return lines.join("\n");
}

function renderSceneLocks(scene: JsonObject | null, sceneLocksPath: string, lint: JsonObject | null): string {
  if (scene === null) {
    return "No lint or lock context loaded.";
  }
  const lines = [
    `scene_locks_path=${sceneLocksPath || "(not set)"}`,
    `scene_path=${state.artifactSources.scenePath || "(not loaded)"}`,
    `scene_lint_path=${state.artifactSources.sceneLintPath || "(not loaded)"}`,
  ];

  const intent = asObject(scene.intent);
  const sceneLocks = asArray(intent?.locks).map(asString).filter(Boolean);
  lines.push(`scene.intent.locks=${sceneLocks.length ? sceneLocks.join(", ") : "(none)"}`);

  const rowLines: string[] = [];
  for (const row of sceneRows(scene)) {
    if (row.locks.length === 0) {
      continue;
    }
    rowLines.push(`${row.kind}:${row.objectId} -> ${row.locks.join(", ")}`);
  }
  lines.push("object_and_bed_locks:");
  lines.push(...(rowLines.length > 0 ? rowLines : ["(none)"]));

  const lintSummary = asObject(lint?.summary);
  if (lintSummary !== null) {
    lines.push(
      `lint_counts=error:${asNumber(lintSummary.error_count) ?? 0} warn:${asNumber(lintSummary.warn_count) ?? 0}`,
    );
  }
  return lines.join("\n");
}

function nearestSceneRow(): SceneRow | null {
  const rows = sceneRows(state.artifacts.scene).filter((row) => row.kind === "object");
  if (rows.length === 0) {
    return null;
  }
  let best: SceneRow | null = null;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const row of rows) {
    const rowPan = row.azimuth ?? 0;
    const rowDepth = (row.depth ?? 0) * 100;
    const distance = Math.hypot(state.sceneFocusPan - rowPan, state.sceneFocusDepth - rowDepth);
    if (distance < bestDistance) {
      best = row;
      bestDistance = distance;
    }
  }
  return best;
}

function renderSceneFocus(ui: AppUi): void {
  const pan = clamp(state.sceneFocusPan, -90, 90);
  const depth = clamp(state.sceneFocusDepth, 0, 100);
  state.sceneFocusPan = pan;
  state.sceneFocusDepth = depth;
  ui.inputs.sceneFocusPan.value = Math.round(pan).toString();
  ui.inputs.sceneFocusDepth.value = Math.round(depth).toString();
  const x = ((pan + 90) / 180) * 100;
  ui.scene.focusDot.style.setProperty("--xy-x", x.toFixed(2));
  ui.scene.focusDot.style.setProperty("--xy-y", depth.toFixed(2));

  const nearest = nearestSceneRow();
  if (nearest === null) {
    ui.scene.focusCaption.textContent = "No scene objects loaded.";
    ui.scene.objectsList.textContent = "No scene objects loaded.";
    return;
  }

  ui.scene.focusCaption.textContent = [
    `Nearest: ${nearest.label} [${nearest.objectId}]`,
    `pan=${formatSceneNumber(nearest.azimuth, 1, " deg")}`,
    `depth=${formatSceneNumber(nearest.depth !== null ? nearest.depth * 100 : null, 0, "%")}`,
  ].join(" · ");

  const lines = sceneRows(state.artifacts.scene).map((row) => {
    const marker = row.objectId === nearest.objectId ? "* " : "  ";
    const detail = [
      `${row.label} [${row.objectId}]`,
      row.kind,
      `pan=${formatSceneNumber(row.azimuth, 1, " deg")}`,
      `depth=${formatSceneNumber(row.depth !== null ? row.depth * 100 : null, 0, "%")}`,
      `locks=${row.locks.length ? row.locks.join(",") : "none"}`,
    ];
    return `${marker}${detail.join(" | ")}`;
  });
  ui.scene.objectsList.textContent = lines.join("\n");
}

function flattenManifestOutputs(manifest: JsonObject | null): JsonObject[] {
  if (manifest === null) {
    return [];
  }
  const outputs: JsonObject[] = [];
  for (const rendererManifest of asArray(manifest.renderer_manifests)) {
    const row = asObject(rendererManifest);
    if (row === null) {
      continue;
    }
    for (const output of asArray(row.outputs)) {
      const outputRow = asObject(output);
      if (outputRow !== null) {
        outputs.push({
          ...outputRow,
          renderer_id: asString(row.renderer_id),
          received_recommendation_ids: asArray(row.received_recommendation_ids),
        });
      }
    }
  }
  return outputs;
}

function artifactPreviewForOutput(output: JsonObject): string {
  const lines = [
    `renderer_id=${asString(output.renderer_id) || "-"}`,
    `output_id=${asString(output.output_id) || "-"}`,
    `file_path=${asString(output.file_path) || "-"}`,
    `layout_id=${asString(output.layout_id) || "-"}`,
    `format=${asString(output.format) || "-"}`,
    `recommendation_id=${asString(output.recommendation_id) || "-"}`,
  ];
  return lines.join("\n");
}

function buildArtifactEntries(paths: WorkflowPaths | null): ArtifactEntry[] {
  const entries: ArtifactEntry[] = [];

  const pushJsonEntry = (
    id: string,
    title: string,
    path: string,
    tag: ArtifactTag,
    payload: JsonObject | null,
    summary: string,
  ) => {
    if (!path && payload === null) {
      return;
    }
    entries.push({
      id,
      path,
      previewText: serializeJson(payload, state.nerdView ? 60 : Math.max(12, state.resultsDetailLevel * 3)),
      summary,
      tag,
      title,
    });
  };

  pushJsonEntry(
    "receipt",
    "Final receipt",
    state.artifactSources.receiptPath || paths?.renderReceiptPath || "",
    "RECEIPT",
    state.artifacts.receipt,
    summarizeReceipt(state.artifacts.receipt, state.artifacts.manifest, state.artifacts.qa),
  );
  pushJsonEntry(
    "manifest",
    "Render manifest",
    state.artifactSources.manifestPath || paths?.renderManifestPath || "",
    "JSON",
    state.artifacts.manifest,
    `${flattenManifestOutputs(state.artifacts.manifest).length} output artifact(s) in manifest`,
  );
  pushJsonEntry(
    "qa",
    "Render QA",
    state.artifactSources.qaPath || paths?.renderQaPath || "",
    "QA",
    state.artifacts.qa,
    summarizeQa(state.artifacts.qa),
  );
  pushJsonEntry(
    "compare",
    "Compare report",
    state.artifactSources.comparePath || paths?.compareReportPath || "",
    "JSON",
    state.artifacts.compare,
    summarizeCompareHeadline(state.artifacts.compare),
  );

  for (const output of flattenManifestOutputs(state.artifacts.manifest)) {
    const outputId = asString(output.output_id) || asString(output.file_path);
    entries.push({
      id: `audio:${outputId}`,
      path: asString(output.file_path),
      previewText: artifactPreviewForOutput(output),
      summary: `${asString(output.renderer_id) || "renderer"} · ${asString(output.format) || "audio"}`,
      tag: "AUDIO",
      title: asString(output.file_path) || outputId,
    });
  }

  entries.sort((left, right) => left.title.localeCompare(right.title));
  return entries;
}

function summarizeReceipt(receipt: JsonObject | null, manifest: JsonObject | null, qa: JsonObject | null): string {
  if (receipt === null) {
    return "No receipt loaded";
  }
  const summary = asObject(receipt.recommendations_summary);
  return [
    `${asString(receipt.status) || "unknown"} receipt`,
    `outputs=${flattenManifestOutputs(manifest).length}`,
    `applied=${asNumber(summary?.applied) ?? 0}`,
    `qa_issues=${asArray(qa?.issues).length || asArray(receipt.qa_issues).length}`,
  ].join(" · ");
}

function summarizeQa(qa: JsonObject | null): string {
  if (qa === null) {
    return "No render QA loaded.";
  }
  const issues = asArray(qa.issues).map(asObject).filter((row): row is JsonObject => row !== null);
  const errorCount = issues.filter((row) => asString(row.severity) === "error").length;
  const warnCount = issues.filter((row) => asString(row.severity) === "warn").length;
  const jobCount = asArray(qa.jobs).length;
  return `jobs=${jobCount} · errors=${errorCount} · warnings=${warnCount}`;
}

function recommendationArtifactPaths(recommendationId: string, manifest: JsonObject | null): string[] {
  const outputs = flattenManifestOutputs(manifest);
  const directMatches = outputs
    .filter((output) => asString(output.recommendation_id) === recommendationId)
    .map((output) => asString(output.file_path))
    .filter(Boolean);
  if (directMatches.length > 0) {
    return directMatches;
  }
  const inferredMatches = outputs
    .filter((output) => {
      const receivedIds = asArray(output.received_recommendation_ids).map(asString);
      return receivedIds.includes(recommendationId);
    })
    .map((output) => asString(output.file_path))
    .filter(Boolean);
  return inferredMatches;
}

function renderWhatChanged(receipt: JsonObject | null, manifest: JsonObject | null): string {
  if (receipt === null) {
    return "No receipt or manifest loaded.";
  }
  const lines: string[] = [];
  const applied = asArray(receipt.applied_recommendations)
    .map(asObject)
    .filter((row): row is JsonObject => row !== null);
  const blocked = asArray(receipt.blocked_recommendations)
    .map(asObject)
    .filter((row): row is JsonObject => row !== null);

  if (applied.length > 0) {
    lines.push("Applied changes:");
    for (const row of applied.slice(0, state.resultsDetailLevel)) {
      const recommendationId = asString(row.recommendation_id);
      const artifactPaths = recommendationArtifactPaths(recommendationId, manifest);
      const scope = asObject(row.scope);
      const scopeLabel =
        asString(scope?.stem_id) ||
        asString(scope?.bus_id) ||
        asString(scope?.layout_id) ||
        (scope?.global === true ? "global" : "unspecified");
      lines.push(
        `- ${recommendationId} (${asString(row.action_id) || "-"}) -> ${artifactPaths.join(", ") || "no output path recorded"} | scope=${scopeLabel}`,
      );
    }
  }

  if (blocked.length > 0) {
    if (lines.length > 0) {
      lines.push("");
    }
    lines.push("Blocked changes:");
    for (const row of blocked.slice(0, Math.max(1, state.resultsDetailLevel - applied.length))) {
      lines.push(`- ${asString(row.recommendation_id)} -> ${asString(row.gate_summary) || "blocked"}`);
    }
  }

  if (lines.length === 0) {
    lines.push("No applied or blocked recommendations were recorded.");
  }
  return lines.join("\n");
}

function renderQaText(qa: JsonObject | null): string {
  if (qa === null) {
    return "No render QA loaded.";
  }
  const issues = asArray(qa.issues)
    .map(asObject)
    .filter((row): row is JsonObject => row !== null);
  const lines = [summarizeQa(qa)];
  if (issues.length === 0) {
    lines.push("- (no issues)");
    return lines.join("\n");
  }
  for (const issue of issues.slice(0, state.resultsDetailLevel)) {
    const detail = [
      asString(issue.severity).toUpperCase() || "INFO",
      asString(issue.issue_id) || "ISSUE.UNKNOWN",
      asString(issue.output_path) || asString(issue.job_id) || "-",
    ];
    const message = asString(issue.message);
    lines.push(`- ${detail.join(" | ")}${message ? `: ${message}` : ""}`);
  }
  return lines.join("\n");
}

function meanQaMetric(qa: JsonObject | null, metricKey: string): number | null {
  if (qa === null) {
    return null;
  }
  const values: number[] = [];
  for (const job of asArray(qa.jobs)) {
    const jobObject = asObject(job);
    if (jobObject === null) {
      continue;
    }
    for (const output of asArray(jobObject.outputs)) {
      const outputObject = asObject(output);
      const metrics = asObject(outputObject?.metrics);
      const value = asNumber(metrics?.[metricKey]);
      if (value !== null) {
        values.push(value);
      }
    }
  }
  if (values.length === 0) {
    return null;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function deriveCompareCompensation(): { db: number; note: string; source: "none" | "render_qa" } {
  const aIntegrated = meanQaMetric(state.artifacts.compareAQa, "integrated_lufs");
  const bIntegrated = meanQaMetric(state.artifacts.compareBQa, "integrated_lufs");
  if (aIntegrated !== null && bIntegrated !== null) {
    return {
      db: roundToStep(aIntegrated - bIntegrated, 0.1),
      note: `Default loudness match from A/B render_qa mean integrated LUFS (${aIntegrated.toFixed(1)} vs ${bIntegrated.toFixed(1)}).`,
      source: "render_qa",
    };
  }

  const aRms = meanQaMetric(state.artifacts.compareAQa, "rms_dbfs");
  const bRms = meanQaMetric(state.artifacts.compareBQa, "rms_dbfs");
  if (aRms !== null && bRms !== null) {
    return {
      db: roundToStep(aRms - bRms, 0.1),
      note: `Default loudness match from A/B render_qa mean RMS dBFS (${aRms.toFixed(1)} vs ${bRms.toFixed(1)}).`,
      source: "render_qa",
    };
  }

  return { db: 0, note: "No paired render_qa loudness metrics were available.", source: "none" };
}

function summarizeCompareHeadline(compare: JsonObject | null): string {
  if (compare === null) {
    return "No compare artifact loaded.";
  }
  const notes = asArray(compare.notes).map(asString).filter(Boolean);
  return notes[0] ?? "Compare artifact loaded.";
}

function renderCompare(ui: AppUi): void {
  const compare = state.artifacts.compare;
  const compareExists = compare !== null;

  for (const button of ui.abButtons) {
    const active = button.dataset.abState === state.compareState;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }

  const compensationRatio = (state.compareCompensationDb + 12) / 24;
  ui.compareCompensation.knob.style.setProperty("--control-ratio", clamp(compensationRatio, 0, 1).toFixed(4));
  ui.compareCompensation.knob.setAttribute("aria-valuenow", state.compareCompensationDb.toFixed(1));
  ui.compareCompensation.input.value = state.compareCompensationDb.toFixed(1);
  ui.compareCompensation.value.textContent = `${signedNumber(state.compareCompensationDb)} dB`;

  const compensationNote = state.compareCompensationSource === "render_qa"
    ? `B is loudness-matched by ${signedNumber(state.compareCompensationDb)} dB.`
    : `B compensation is ${signedNumber(state.compareCompensationDb)} dB.`;
  requiredElement<HTMLElement>("#ab-compensation").textContent = compareExists
    ? compensationNote
    : "No loudness-match data loaded.";

  if (!compareExists) {
    ui.compareReadoutPrimary.textContent = "No compare artifact loaded";
    ui.compareReadoutSecondary.textContent = "A/B readout appears after compare_report.json is loaded.";
    ui.compareSummary.textContent = "No compare artifact loaded.";
    ui.compareSummaryNote.textContent = "Warnings and notes will appear here.";
    ui.compareJsonPreview.textContent = "No compare artifact loaded.";
    return;
  }

  const sideKey = state.compareState.toLowerCase() as "a" | "b";
  const side = asObject(compare[sideKey]);
  const notes = asArray(compare.notes).map(asString).filter(Boolean);
  const warnings = asArray(compare.warnings).map(asString).filter(Boolean);
  const loudnessRaw = sideKey === "a"
    ? meanQaMetric(state.artifacts.compareAQa, "integrated_lufs") ?? meanQaMetric(state.artifacts.compareAQa, "rms_dbfs")
    : meanQaMetric(state.artifacts.compareBQa, "integrated_lufs") ?? meanQaMetric(state.artifacts.compareBQa, "rms_dbfs");
  const loudnessUnit = meanQaMetric(sideKey === "a" ? state.artifacts.compareAQa : state.artifacts.compareBQa, "integrated_lufs") !== null
    ? "LUFS"
    : "dBFS";
  const matchedLoudness = sideKey === "b" && loudnessRaw !== null
    ? loudnessRaw + state.compareCompensationDb
    : loudnessRaw;

  ui.compareReadoutPrimary.textContent = [
    `${state.compareState} · ${asString(side?.label) || state.compareState}`,
    loudnessRaw === null ? "no loudness metric" : `${matchedLoudness?.toFixed(1)} ${loudnessUnit}`,
  ].join(" · ");
  ui.compareReadoutSecondary.textContent = [
    `profile=${asString(side?.profile_id) || "-"}`,
    `preset=${asString(side?.preset_id) || "-"}`,
    loudnessRaw === null ? "raw=n/a" : `raw=${loudnessRaw.toFixed(1)} ${loudnessUnit}`,
  ].join(" · ");

  ui.compareSummary.textContent = notes[0] ?? "No tracked differences were detected.";
  const summaryLines = [
    state.compareCompensationSource === "render_qa"
      ? `compensation_source=render_qa | compensation=${signedNumber(state.compareCompensationDb)} dB`
      : `compensation_source=${state.compareCompensationSource} | compensation=${signedNumber(state.compareCompensationDb)} dB`,
    ...warnings.slice(0, state.resultsDetailLevel),
    ...notes.slice(1, 1 + Math.max(1, state.resultsDetailLevel - warnings.length)),
  ];
  ui.compareSummaryNote.textContent = summaryLines.join("\n");
  ui.compareJsonPreview.textContent = serializeJson(compare, state.nerdView ? 70 : 18);
}

function renderResults(ui: AppUi): void {
  const paths = ui.inputs.workspaceDir.value.trim()
    ? buildWorkflowPaths(ui.inputs.workspaceDir.value.trim())
    : null;
  const entries = buildArtifactEntries(paths);
  const query = state.resultsArtifactSearch.trim().toLowerCase();
  const filtered = entries.filter((entry) => {
    if (state.resultsArtifactTag !== "ALL" && entry.tag !== state.resultsArtifactTag) {
      return false;
    }
    if (!query) {
      return true;
    }
    return `${entry.title} ${entry.summary} ${entry.path}`.toLowerCase().includes(query);
  });

  if (!filtered.some((entry) => entry.id === state.selectedArtifactId)) {
    state.selectedArtifactId = filtered[0]?.id ?? "";
  }

  for (const button of ui.artifactTagButtons) {
    const active = button.dataset.artifactTag === state.resultsArtifactTag;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }

  ui.results.browserList.innerHTML = "";
  for (const entry of filtered) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "preset-button";
    button.textContent = entry.title;
    if (entry.id === state.selectedArtifactId) {
      button.classList.add("is-active");
    }
    const meta = document.createElement("small");
    meta.textContent = `${entry.tag} · ${entry.summary}`;
    button.append(meta);
    button.addEventListener("click", () => {
      state.selectedArtifactId = entry.id;
      renderResults(ui);
    });
    ui.results.browserList.append(button);
  }

  const selected = filtered.find((entry) => entry.id === state.selectedArtifactId) ?? null;
  ui.artifactPreviewName.textContent = selected?.title ?? "No artifact selected";
  ui.artifactPreviewSummary.textContent = selected?.summary ?? "Load or generate render artifacts to inspect them here.";
  ui.artifactPreviewDelta.textContent = selected?.path ? `path=${selected.path}` : "";

  ui.results.detailSlider.style.setProperty("--slider-ratio", ((state.resultsDetailLevel - 1) / 9).toFixed(4));
  ui.results.detailSlider.setAttribute("aria-valuenow", state.resultsDetailLevel.toString());
  ui.results.detailInput.value = state.resultsDetailLevel.toString();
  ui.results.detailValue.textContent = `${state.resultsDetailLevel} line(s) of detail`;

  ui.results.readoutPrimary.textContent = summarizeReceipt(
    state.artifacts.receipt,
    state.artifacts.manifest,
    state.artifacts.qa,
  );
  ui.results.readoutSecondary.textContent = [
    state.artifactSources.receiptPath || "safe_render_receipt.json",
    state.artifactSources.manifestPath || "render_manifest.json",
  ].join(" · ");
  ui.results.readoutNote.textContent = state.artifactSources.qaPath || "render_qa.json";
  ui.results.whatChangedText.textContent = renderWhatChanged(state.artifacts.receipt, state.artifacts.manifest);
  ui.results.qaText.textContent = renderQaText(state.artifacts.qa);
  ui.results.jsonPreview.textContent = selected?.previewText ?? "No artifact selected.";
}

function renderAnalyze(ui: AppUi): void {
  ui.analyze.summaryText.textContent = summarizeAnalyzeArtifacts(state.artifacts.report);
  ui.analyze.scanText.textContent = summarizeScanArtifact(state.artifacts.scan);
  ui.analyze.jsonPreview.textContent = serializeJson(
    state.artifacts.report,
    state.nerdView ? 80 : 18,
  );
}

function renderValidate(ui: AppUi): void {
  ui.validate.summaryText.textContent = summarizeValidationPayload(state.artifacts.validation);
  ui.validate.jsonPreview.textContent = serializeJson(
    state.artifacts.validation,
    state.nerdView ? 60 : 18,
  );
}

function renderScene(ui: AppUi): void {
  ui.scene.summaryText.textContent = renderSceneSummary(state.artifacts.scene, state.artifacts.sceneLint);
  ui.scene.locksText.textContent = renderSceneLocks(
    state.artifacts.scene,
    ui.inputs.sceneLocksPath.value.trim(),
    state.artifacts.sceneLint,
  );
  ui.scene.jsonPreview.textContent = serializeJson(
    state.artifacts.scene,
    state.nerdView ? 80 : 18,
  );
  renderSceneFocus(ui);
}

function updateRenderConfigSummary(ui: AppUi): void {
  const workspaceDir = ui.inputs.workspaceDir.value.trim();
  if (!workspaceDir) {
    ui.renderConfigSummary.textContent = "Enter a workspace folder to preview render inputs.";
    return;
  }
  const paths = buildWorkflowPaths(workspaceDir);
  const lines = [
    `target=${ui.inputs.renderTarget.value}`,
    `layout_standard=${ui.inputs.layoutStandard.value}`,
    `report=${paths.reportPath}`,
    `scene=${paths.scenePath}`,
    `scene_locks=${ui.inputs.sceneLocksPath.value.trim() || "(not set)"}`,
    `out_dir=${paths.renderDir}`,
  ];
  ui.renderConfigSummary.textContent = lines.join("\n");
}

function renderAll(ui: AppUi): void {
  renderNerdView(ui);
  renderExpectedPaths(ui);
  renderValidate(ui);
  renderAnalyze(ui);
  renderScene(ui);
  renderResults(ui);
  renderCompare(ui);
  updateRenderConfigSummary(ui);
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
  ui.renderProgressText.textContent = `${progressText}\n${scope}\n${what}`;
}

async function runExecuteCommand(
  ui: AppUi,
  stage: CommandStage,
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
  stage: CommandStage,
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

function assertSuccess(result: MmoRunResult, stageLabel: string): void {
  if (result.code === 0) {
    return;
  }
  throw new Error(`${stageLabel} failed (${formatExitSummary(result)}).`);
}

async function refreshValidationArtifacts(paths: WorkflowPaths): Promise<void> {
  state.artifacts.validation = await readArtifactJson<JsonObject>(paths.projectValidationPath);
  state.artifactSources.validationPath = paths.projectValidationPath;
}

async function refreshAnalyzeArtifacts(paths: WorkflowPaths): Promise<void> {
  state.artifacts.report = await readArtifactJson<JsonObject>(paths.reportPath);
  state.artifacts.scan = await readArtifactJson<JsonObject>(paths.scanReportPath);
  state.artifactSources.reportPath = paths.reportPath;
  state.artifactSources.scanPath = paths.scanReportPath;
}

async function refreshSceneArtifacts(paths: WorkflowPaths): Promise<void> {
  state.artifacts.scene = await readArtifactJson<JsonObject>(paths.scenePath);
  state.artifacts.sceneLint = await readArtifactJson<JsonObject>(paths.sceneLintPath);
  state.artifactSources.scenePath = paths.scenePath;
  state.artifactSources.sceneLintPath = paths.sceneLintPath;
}

async function refreshResultsArtifacts(paths: WorkflowPaths): Promise<void> {
  state.artifacts.receipt = await readArtifactJson<JsonObject>(paths.renderReceiptPath);
  state.artifacts.manifest = await readArtifactJson<JsonObject>(paths.renderManifestPath);
  state.artifacts.qa = await readArtifactJson<JsonObject>(paths.renderQaPath);
  state.artifactSources.receiptPath = paths.renderReceiptPath;
  state.artifactSources.manifestPath = paths.renderManifestPath;
  state.artifactSources.qaPath = paths.renderQaPath;
}

function compareQaPath(candidatePath: string): string {
  return resolveSiblingPath(candidatePath, "render_qa.json");
}

async function refreshCompareArtifacts(paths: WorkflowPaths, aPath: string, bPath: string): Promise<void> {
  state.artifacts.compare = await readArtifactJson<JsonObject>(paths.compareReportPath);
  state.artifactSources.comparePath = paths.compareReportPath;

  const aQaPath = compareQaPath(aPath);
  const bQaPath = compareQaPath(bPath);
  state.artifacts.compareAQa = await readArtifactJson<JsonObject>(aQaPath);
  state.artifacts.compareBQa = await readArtifactJson<JsonObject>(bQaPath);
  state.artifactSources.compareAQaPath = aQaPath;
  state.artifactSources.compareBQaPath = bQaPath;

  const derived = deriveCompareCompensation();
  if (state.compareCompensationSource !== "manual" || state.artifacts.compare === null) {
    state.compareCompensationDb = derived.db;
    state.compareCompensationSource = derived.source;
  }
}

async function runDoctor(ui: AppUi): Promise<void> {
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

  const ok = versionResult.code === 0 && pluginsResult.code === 0 && envDoctorResult.code === 0;
  updateRuntimeMessage(ui, ok ? "Doctor passed. The packaged sidecar is ready." : "Doctor failed. Check the timeline.");
}

async function runValidate(ui: AppUi, controller: ReturnType<typeof initDesignSystem>): Promise<void> {
  const { paths, stemsDir } = collectInputs(ui);
  setStageStatus(ui.stages.validate, "running", "Running");
  ui.output.validate.textContent = `Refreshing project scaffold in\n${paths.projectDir}`;
  updateRuntimeMessage(ui, "Validating project workspace artifacts.");

  const initResult = await runExecuteCommand(ui, "validate", [
    "project",
    "init",
    "--stems-root",
    stemsDir,
    "--out-dir",
    paths.projectDir,
    "--force",
  ]);
  assertSuccess(initResult, "validate");

  const validateResult = await runExecuteCommand(ui, "validate", [
    "project",
    "validate",
    paths.projectDir,
    "--out",
    paths.projectValidationPath,
  ]);
  await refreshValidationArtifacts(paths);
  renderValidate(ui);
  ui.output.validate.textContent = validateResult.code === 0
    ? [
      formatExitSummary(validateResult),
      `project_dir=${paths.projectDir}`,
      `validation=${paths.projectValidationPath}`,
      summarizeValidationPayload(state.artifacts.validation),
    ].join("\n")
    : formatFailureOutput(validateResult);
  setStageStatus(ui.stages.validate, validateResult.code === 0 ? "pass" : "fail", validateResult.code === 0 ? "Pass" : "Fail");
  assertSuccess(validateResult, "validate");
  updateRuntimeMessage(ui, "Workspace validation passed.");
  controller.setScreen("analyze");
}

async function runAnalyze(ui: AppUi, controller: ReturnType<typeof initDesignSystem>): Promise<void> {
  const { paths, stemsDir } = collectInputs(ui);
  setStageStatus(ui.stages.analyze, "running", "Running");
  ui.output.analyze.textContent = `Analyzing stems into\n${paths.reportPath}`;
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
  await refreshAnalyzeArtifacts(paths);
  renderAnalyze(ui);
  ui.output.analyze.textContent = result.code === 0
    ? [
      formatExitSummary(result),
      `report=${paths.reportPath}`,
      `scan=${paths.scanReportPath}`,
      summarizeAnalyzeArtifacts(state.artifacts.report),
    ].join("\n")
    : formatFailureOutput(result);
  setStageStatus(ui.stages.analyze, result.code === 0 ? "pass" : "fail", result.code === 0 ? "Pass" : "Fail");
  assertSuccess(result, "analyze");
  updateRuntimeMessage(ui, "Analyze completed.");
  controller.setScreen("scene");
}

async function runScene(ui: AppUi, controller: ReturnType<typeof initDesignSystem>): Promise<void> {
  const { paths, sceneLocksPath, stemsDir } = collectInputs(ui);
  setStageStatus(ui.stages.scene, "running", "Running");
  ui.output.scene.textContent = `Building scene artifacts in\n${paths.workspaceDir}`;
  updateRuntimeMessage(ui, "Building stems map, bus plan, scene.json, and scene_lint.json.");

  const classifyResult = await runExecuteCommand(ui, "scene", [
    "stems",
    "classify",
    "--root",
    stemsDir,
    "--out",
    paths.stemsMapPath,
  ]);
  assertSuccess(classifyResult, "scene");

  const busPlanResult = await runExecuteCommand(ui, "scene", [
    "stems",
    "bus-plan",
    "--map",
    paths.stemsMapPath,
    "--out",
    paths.busPlanPath,
    "--csv",
    paths.busPlanCsvPath,
  ]);
  assertSuccess(busPlanResult, "scene");

  const buildArgs = [
    "scene",
    "build",
    "--map",
    paths.stemsMapPath,
    "--bus",
    paths.busPlanPath,
    "--out",
    paths.scenePath,
    "--profile",
    "PROFILE.ASSIST",
  ];
  if (sceneLocksPath) {
    buildArgs.push("--locks", sceneLocksPath);
  }
  const buildResult = await runExecuteCommand(ui, "scene", buildArgs);
  assertSuccess(buildResult, "scene");

  const lintArgs = [
    "scene",
    "lint",
    "--scene",
    paths.scenePath,
    "--out",
    paths.sceneLintPath,
  ];
  if (sceneLocksPath) {
    lintArgs.push("--scene-locks", sceneLocksPath);
  }
  const lintResult = await runExecuteCommand(ui, "scene", lintArgs);
  await refreshSceneArtifacts(paths);
  renderScene(ui);
  ui.output.scene.textContent = lintResult.code === 0
    ? [
      formatExitSummary(lintResult),
      `stems_map=${paths.stemsMapPath}`,
      `bus_plan=${paths.busPlanPath}`,
      `scene=${paths.scenePath}`,
      `scene_lint=${paths.sceneLintPath}`,
    ].join("\n")
    : formatFailureOutput(lintResult);
  setStageStatus(ui.stages.scene, lintResult.code === 0 ? "pass" : "fail", lintResult.code === 0 ? "Pass" : "Fail");
  assertSuccess(lintResult, "scene");
  updateRuntimeMessage(ui, "Scene artifacts refreshed.");
  controller.setScreen("render");
}

async function runRender(ui: AppUi, controller: ReturnType<typeof initDesignSystem>): Promise<void> {
  const { layoutStandard, paths, renderTarget, sceneLocksPath } = collectInputs(ui);
  setStageStatus(ui.stages.render, "running", "Running");
  state.currentCancelPath = buildRenderCancelPath(paths);
  applyBusyState(ui);
  ui.output.render.textContent = `Launching safe-render for ${renderTarget}`;
  ui.renderOutputText.textContent = `render_manifest=${paths.renderManifestPath}\nsafe_render_receipt=${paths.renderReceiptPath}\nrender_qa=${paths.renderQaPath}`;
  updateRuntimeMessage(ui, "Rendering from the analyzed report with live sidecar logs.");

  const args = [
    "safe-render",
    "--report",
    paths.reportPath,
    "--scene",
    paths.scenePath,
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
    "--cancel-file",
    state.currentCancelPath,
    "--live-progress",
    "--force",
  ];
  if (sceneLocksPath) {
    args.push("--scene-locks", sceneLocksPath);
  }
  const result = await runSpawnCommand(ui, "render", args);
  await refreshResultsArtifacts(paths);
  renderResults(ui);
  ui.output.render.textContent = result.code === 0
    ? [
      formatExitSummary(result),
      `target=${renderTarget}`,
      `render_dir=${paths.renderDir}`,
      `manifest=${paths.renderManifestPath}`,
      `receipt=${paths.renderReceiptPath}`,
      `qa=${paths.renderQaPath}`,
    ].join("\n")
    : formatFailureOutput(result);
  ui.renderOutputText.textContent = summarizeReceipt(
    state.artifacts.receipt,
    state.artifacts.manifest,
    state.artifacts.qa,
  );
  const canceled = result.code === 130;
  setStageStatus(
    ui.stages.render,
    result.code === 0 ? "pass" : "fail",
    result.code === 0 ? "Pass" : (canceled ? "Canceled" : "Fail"),
  );
  state.currentCancelPath = null;
  applyBusyState(ui);
  assertSuccess(result, "render");
  updateRuntimeMessage(ui, "Render completed and wrote artifacts into the workspace.");
  controller.setScreen("results");
}

async function runCompare(ui: AppUi): Promise<void> {
  const { paths } = collectInputs(ui);
  const aPath = ui.compareInputs.aPath.value.trim();
  const bPath = ui.compareInputs.bPath.value.trim();
  if (!aPath || !bPath) {
    throw new Error("Enter both compare input paths first.");
  }
  setStageStatus(ui.stages.compare, "running", "Running");
  ui.output.compare.textContent = `Comparing\nA=${aPath}\nB=${bPath}`;
  updateRuntimeMessage(ui, "Running mmo compare from the desktop sidecar.");

  const result = await runExecuteCommand(ui, "compare", [
    "compare",
    "--a",
    aPath,
    "--b",
    bPath,
    "--out",
    paths.compareReportPath,
  ]);
  await refreshCompareArtifacts(paths, aPath, bPath);
  renderCompare(ui);
  ui.output.compare.textContent = result.code === 0
    ? [
      formatExitSummary(result),
      `compare_report=${paths.compareReportPath}`,
      summarizeCompareHeadline(state.artifacts.compare),
    ].join("\n")
    : formatFailureOutput(result);
  setStageStatus(ui.stages.compare, result.code === 0 ? "pass" : "fail", result.code === 0 ? "Pass" : "Fail");
  assertSuccess(result, "compare");
  updateRuntimeMessage(ui, "Compare report written.");
}

async function runWithBusy(
  ui: AppUi,
  stage: CommandStage,
  action: () => Promise<void>,
  clearLogs = false,
): Promise<void> {
  if (state.busyStage !== null) {
    return;
  }
  state.busyStage = stage;
  applyBusyState(ui);
  if (clearLogs) {
    clearTimeline(ui);
  }
  try {
    await action();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    updateRuntimeMessage(ui, detail);
    if (stage !== "doctor") {
      const targetStage = ui.stages[stage as StageKey];
      if (targetStage !== undefined) {
        setStageStatus(targetStage, "fail", "Fail");
      }
    }
  } finally {
    state.busyStage = null;
    applyBusyState(ui);
    renderAll(ui);
  }
}

function parseJsonFile(file: File): Promise<JsonObject | null> {
  return file.text()
    .then((text) => JSON.parse(text) as unknown)
    .then((payload) => asObject(payload))
    .catch(() => null);
}

function bindJsonFileInput(
  input: HTMLInputElement,
  onLoad: (payload: JsonObject, sourceName: string) => void,
  onFailure: () => void,
): void {
  input.addEventListener("change", async () => {
    const file = input.files?.[0];
    if (file === undefined) {
      return;
    }
    const payload = await parseJsonFile(file);
    if (payload === null) {
      onFailure();
      return;
    }
    onLoad(payload, file.name);
  });
}

function bindResultsDetailSlider(ui: AppUi, controller: ReturnType<typeof initDesignSystem>): void {
  const minimum = 1;
  const maximum = 10;
  const applyValue = (value: number) => {
    state.resultsDetailLevel = clamp(Math.round(value), minimum, maximum);
    renderAll(ui);
  };
  ui.results.detailInput.addEventListener("change", () => {
    applyValue(Number(ui.results.detailInput.value));
  });
  const beginDrag = (
    startX: number,
    fineAdjust: boolean,
    cleanup: (onMove: (event: MouseEvent | PointerEvent) => void, onUp: (event: MouseEvent | PointerEvent) => void) => void,
  ) => {
    const startValue = state.resultsDetailLevel;
    const sensitivity = fineAdjust ? 0.03 : 0.08;
    const onMove = (moveEvent: MouseEvent | PointerEvent) => {
      const delta = (moveEvent.clientX - startX) * sensitivity;
      applyValue(startValue + delta);
    };
    const onUp = (_event: MouseEvent | PointerEvent) => {
      controller.setFineAdjustContext(null);
    };
    controller.setFineAdjustContext("detail slider");
    cleanup(onMove, onUp);
  };

  ui.results.detailSlider.addEventListener("pointerdown", (event) => {
    ui.results.detailSlider.setPointerCapture(event.pointerId);
    beginDrag(event.clientX, controller.isFineAdjust(event), (onMove, onUp) => {
      const pointerMove = onMove as (event: PointerEvent) => void;
      const pointerUp = (upEvent: PointerEvent) => {
        ui.results.detailSlider.releasePointerCapture(upEvent.pointerId);
        ui.results.detailSlider.removeEventListener("pointermove", pointerMove);
        ui.results.detailSlider.removeEventListener("pointerup", pointerUp);
        ui.results.detailSlider.removeEventListener("pointercancel", pointerUp);
        onUp(upEvent);
      };
      ui.results.detailSlider.addEventListener("pointermove", pointerMove);
      ui.results.detailSlider.addEventListener("pointerup", pointerUp);
      ui.results.detailSlider.addEventListener("pointercancel", pointerUp);
    });
  });
  ui.results.detailSlider.addEventListener("mousedown", (event) => {
    beginDrag(event.clientX, controller.isFineAdjust(event), (onMove, onUp) => {
      const mouseMove = onMove as (event: MouseEvent) => void;
      const mouseUp = (upEvent: MouseEvent) => {
        window.removeEventListener("mousemove", mouseMove);
        window.removeEventListener("mouseup", mouseUp);
        onUp(upEvent);
      };
      window.addEventListener("mousemove", mouseMove);
      window.addEventListener("mouseup", mouseUp);
    });
  });
}

function bindCompareKnob(ui: AppUi, controller: ReturnType<typeof initDesignSystem>): void {
  const minimum = -12;
  const maximum = 12;
  const applyValue = (value: number, source: "manual" | "render_qa" | "none" = "manual") => {
    state.compareCompensationDb = clamp(roundToStep(value, 0.1), minimum, maximum);
    state.compareCompensationSource = source;
    renderCompare(ui);
  };
  ui.compareCompensation.input.addEventListener("change", () => {
    applyValue(Number(ui.compareCompensation.input.value), "manual");
  });
  const beginDrag = (
    startX: number,
    startY: number,
    fineAdjust: boolean,
    cleanup: (onMove: (event: MouseEvent | PointerEvent) => void, onUp: (event: MouseEvent | PointerEvent) => void) => void,
  ) => {
    const startValue = state.compareCompensationDb;
    const sensitivity = fineAdjust ? 0.02 : 0.06;
    const onMove = (moveEvent: MouseEvent | PointerEvent) => {
      const delta = ((moveEvent.clientX - startX) - (moveEvent.clientY - startY)) * sensitivity;
      applyValue(startValue + delta, "manual");
    };
    const onUp = (_event: MouseEvent | PointerEvent) => {
      controller.setFineAdjustContext(null);
    };
    controller.setFineAdjustContext("compare compensation");
    cleanup(onMove, onUp);
  };
  ui.compareCompensation.knob.addEventListener("pointerdown", (event) => {
    ui.compareCompensation.knob.setPointerCapture(event.pointerId);
    beginDrag(event.clientX, event.clientY, controller.isFineAdjust(event), (onMove, onUp) => {
      const pointerMove = onMove as (event: PointerEvent) => void;
      const pointerUp = (upEvent: PointerEvent) => {
        ui.compareCompensation.knob.releasePointerCapture(upEvent.pointerId);
        ui.compareCompensation.knob.removeEventListener("pointermove", pointerMove);
        ui.compareCompensation.knob.removeEventListener("pointerup", pointerUp);
        ui.compareCompensation.knob.removeEventListener("pointercancel", pointerUp);
        onUp(upEvent);
      };
      ui.compareCompensation.knob.addEventListener("pointermove", pointerMove);
      ui.compareCompensation.knob.addEventListener("pointerup", pointerUp);
      ui.compareCompensation.knob.addEventListener("pointercancel", pointerUp);
    });
  });
  ui.compareCompensation.knob.addEventListener("mousedown", (event) => {
    beginDrag(event.clientX, event.clientY, controller.isFineAdjust(event), (onMove, onUp) => {
      const mouseMove = onMove as (event: MouseEvent) => void;
      const mouseUp = (upEvent: MouseEvent) => {
        window.removeEventListener("mousemove", mouseMove);
        window.removeEventListener("mouseup", mouseUp);
        onUp(upEvent);
      };
      window.addEventListener("mousemove", mouseMove);
      window.addEventListener("mouseup", mouseUp);
    });
  });
}

function bindSceneFocus(ui: AppUi, controller: ReturnType<typeof initDesignSystem>): void {
  const applyFocus = (pan: number, depth: number) => {
    state.sceneFocusPan = clamp(pan, -90, 90);
    state.sceneFocusDepth = clamp(depth, 0, 100);
    renderScene(ui);
  };
  ui.inputs.sceneFocusPan.addEventListener("change", () => {
    applyFocus(Number(ui.inputs.sceneFocusPan.value), state.sceneFocusDepth);
  });
  ui.inputs.sceneFocusDepth.addEventListener("change", () => {
    applyFocus(state.sceneFocusPan, Number(ui.inputs.sceneFocusDepth.value));
  });
  ui.scene.focusPad.addEventListener("pointerdown", (event) => {
    const rect = ui.scene.focusPad.getBoundingClientRect();
    controller.setFineAdjustContext("scene focus");
    ui.scene.focusPad.setPointerCapture(event.pointerId);
    const startPan = state.sceneFocusPan;
    const startDepth = state.sceneFocusDepth;
    const startX = event.clientX;
    const startY = event.clientY;
    const fineAdjust = controller.isFineAdjust(event);

    const applyFromPointer = (moveEvent: PointerEvent) => {
      if (fineAdjust) {
        const nextPan = startPan + ((moveEvent.clientX - startX) / rect.width) * 30;
        const nextDepth = startDepth - ((moveEvent.clientY - startY) / rect.height) * 30;
        applyFocus(nextPan, nextDepth);
        return;
      }
      const xRatio = clamp((moveEvent.clientX - rect.left) / rect.width, 0, 1);
      const yRatio = clamp((moveEvent.clientY - rect.top) / rect.height, 0, 1);
      applyFocus(-90 + (xRatio * 180), (1 - yRatio) * 100);
    };

    const onMove = (moveEvent: PointerEvent) => {
      applyFromPointer(moveEvent);
    };
    const onUp = (upEvent: PointerEvent) => {
      ui.scene.focusPad.releasePointerCapture(upEvent.pointerId);
      ui.scene.focusPad.removeEventListener("pointermove", onMove);
      ui.scene.focusPad.removeEventListener("pointerup", onUp);
      ui.scene.focusPad.removeEventListener("pointercancel", onUp);
      controller.setFineAdjustContext(null);
    };

    applyFromPointer(event);
    ui.scene.focusPad.addEventListener("pointermove", onMove);
    ui.scene.focusPad.addEventListener("pointerup", onUp);
    ui.scene.focusPad.addEventListener("pointercancel", onUp);
  });
}

window.addEventListener("DOMContentLoaded", () => {
  const controller = initDesignSystem({
    defaultScreen: "validate",
  });
  const ui = getUi();

  for (const stage of Object.values(ui.stages)) {
    setStageStatus(stage, "idle", "Idle");
  }

  updateRuntimeMessage(
    ui,
    "Enter a stems folder and workspace folder. Desktop builds call the MMO sidecar directly.",
  );
  renderAll(ui);
  applyBusyState(ui);

  ui.inputs.workspaceDir.addEventListener("input", () => {
    renderAll(ui);
  });
  ui.inputs.stemsDir.addEventListener("input", () => {
    renderAll(ui);
  });
  ui.inputs.sceneLocksPath.addEventListener("input", () => {
    renderAll(ui);
  });
  ui.inputs.renderTarget.addEventListener("change", () => {
    renderAll(ui);
  });
  ui.inputs.layoutStandard.addEventListener("change", () => {
    renderAll(ui);
  });

  ui.nerdView.toggle.addEventListener("click", () => {
    state.nerdView = !state.nerdView;
    renderAll(ui);
  });

  ui.artifactSearch.addEventListener("input", () => {
    state.resultsArtifactSearch = ui.artifactSearch.value;
    renderResults(ui);
  });
  for (const button of ui.artifactTagButtons) {
    button.addEventListener("click", () => {
      const tag = button.dataset.artifactTag as ArtifactTag | undefined;
      if (tag === undefined) {
        return;
      }
      state.resultsArtifactTag = tag;
      renderResults(ui);
    });
  }
  for (const button of ui.abButtons) {
    button.addEventListener("click", () => {
      const compareState = button.dataset.abState as CompareState | undefined;
      if (compareState === undefined) {
        return;
      }
      state.compareState = compareState;
      renderCompare(ui);
    });
  }

  bindCompareKnob(ui, controller);
  bindResultsDetailSlider(ui, controller);
  bindSceneFocus(ui, controller);

  ui.buttons.doctor.addEventListener("click", () => {
    void runWithBusy(ui, "doctor", async () => {
      await runDoctor(ui);
    }, true);
  });
  ui.buttons.validate.addEventListener("click", () => {
    void runWithBusy(ui, "validate", async () => {
      await runValidate(ui, controller);
    }, true);
  });
  ui.buttons.analyze.addEventListener("click", () => {
    void runWithBusy(ui, "analyze", async () => {
      await runAnalyze(ui, controller);
    }, true);
  });
  ui.buttons.scene.addEventListener("click", () => {
    void runWithBusy(ui, "scene", async () => {
      await runScene(ui, controller);
    }, true);
  });
  ui.buttons.render.addEventListener("click", () => {
    void runWithBusy(ui, "render", async () => {
      await runRender(ui, controller);
    }, true);
  });
  ui.buttons.compare.addEventListener("click", () => {
    void runWithBusy(ui, "compare", async () => {
      await runCompare(ui);
    }, true);
  });
  ui.buttons.runAll.addEventListener("click", () => {
    void runWithBusy(ui, "validate", async () => {
      await runValidate(ui, controller);
      await runAnalyze(ui, controller);
      await runScene(ui, controller);
      await runRender(ui, controller);
    }, true);
  });
  ui.buttons.resultsRefresh.addEventListener("click", () => {
    void runWithBusy(ui, "render", async () => {
      const workspaceDir = ui.inputs.workspaceDir.value.trim();
      if (!workspaceDir) {
        throw new Error("Enter a workspace folder path first.");
      }
      const paths = buildWorkflowPaths(workspaceDir);
      await refreshResultsArtifacts(paths);
      renderResults(ui);
      updateRuntimeMessage(ui, "Results artifacts refreshed from disk.");
    });
  });
  ui.buttons.renderCancel.addEventListener("click", () => {
    void (async () => {
      if (state.currentCancelPath === null) {
        updateRuntimeMessage(ui, "No active render to cancel.");
        return;
      }
      const wrote = await writeArtifactText(
        state.currentCancelPath,
        `${JSON.stringify({ requested_at: new Date().toISOString() })}\n`,
      );
      updateRuntimeMessage(
        ui,
        wrote
          ? `Render cancel token written: ${state.currentCancelPath}`
          : "Unable to write render cancel token.",
      );
    })();
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

  bindJsonFileInput(
    ui.fileInputs.validateValidation,
    (payload, sourceName) => {
      state.artifacts.validation = payload;
      state.artifactSources.validationPath = sourceName;
      renderValidate(ui);
      updateRuntimeMessage(ui, `Loaded validation artifact: ${sourceName}`);
    },
    () => updateRuntimeMessage(ui, "validation.json import is not valid JSON."),
  );
  bindJsonFileInput(
    ui.fileInputs.analyzeReport,
    (payload, sourceName) => {
      state.artifacts.report = payload;
      state.artifactSources.reportPath = sourceName;
      renderAnalyze(ui);
      controller.setScreen("analyze");
      updateRuntimeMessage(ui, `Loaded report artifact: ${sourceName}`);
    },
    () => updateRuntimeMessage(ui, "report.json import is not valid JSON."),
  );
  bindJsonFileInput(
    ui.fileInputs.analyzeScan,
    (payload, sourceName) => {
      state.artifacts.scan = payload;
      state.artifactSources.scanPath = sourceName;
      renderAnalyze(ui);
      updateRuntimeMessage(ui, `Loaded scan artifact: ${sourceName}`);
    },
    () => updateRuntimeMessage(ui, "report.scan.json import is not valid JSON."),
  );
  bindJsonFileInput(
    ui.fileInputs.sceneJson,
    (payload, sourceName) => {
      state.artifacts.scene = payload;
      state.artifactSources.scenePath = sourceName;
      renderScene(ui);
      controller.setScreen("scene");
      updateRuntimeMessage(ui, `Loaded scene artifact: ${sourceName}`);
    },
    () => updateRuntimeMessage(ui, "scene.json import is not valid JSON."),
  );
  bindJsonFileInput(
    ui.fileInputs.sceneLint,
    (payload, sourceName) => {
      state.artifacts.sceneLint = payload;
      state.artifactSources.sceneLintPath = sourceName;
      renderScene(ui);
      updateRuntimeMessage(ui, `Loaded scene lint artifact: ${sourceName}`);
    },
    () => updateRuntimeMessage(ui, "scene_lint.json import is not valid JSON."),
  );
  bindJsonFileInput(
    ui.fileInputs.resultsReceipt,
    (payload, sourceName) => {
      state.artifacts.receipt = payload;
      state.artifactSources.receiptPath = sourceName;
      renderResults(ui);
      controller.setScreen("results");
      updateRuntimeMessage(ui, `Loaded safe-render receipt: ${sourceName}`);
    },
    () => updateRuntimeMessage(ui, "safe_render_receipt.json import is not valid JSON."),
  );
  bindJsonFileInput(
    ui.fileInputs.resultsManifest,
    (payload, sourceName) => {
      state.artifacts.manifest = payload;
      state.artifactSources.manifestPath = sourceName;
      renderResults(ui);
      updateRuntimeMessage(ui, `Loaded render manifest: ${sourceName}`);
    },
    () => updateRuntimeMessage(ui, "render_manifest.json import is not valid JSON."),
  );
  bindJsonFileInput(
    ui.fileInputs.resultsQa,
    (payload, sourceName) => {
      state.artifacts.qa = payload;
      state.artifactSources.qaPath = sourceName;
      renderResults(ui);
      updateRuntimeMessage(ui, `Loaded render QA: ${sourceName}`);
    },
    () => updateRuntimeMessage(ui, "render_qa.json import is not valid JSON."),
  );
  bindJsonFileInput(
    ui.fileInputs.compareReport,
    (payload, sourceName) => {
      state.artifacts.compare = payload;
      state.artifactSources.comparePath = sourceName;
      const derived = deriveCompareCompensation();
      state.compareCompensationDb = derived.db;
      state.compareCompensationSource = derived.source;
      renderCompare(ui);
      controller.setScreen("compare");
      updateRuntimeMessage(ui, `Loaded compare report: ${sourceName}`);
    },
    () => updateRuntimeMessage(ui, "compare_report.json import is not valid JSON."),
  );
  bindJsonFileInput(
    ui.fileInputs.compareAQa,
    (payload, sourceName) => {
      state.artifacts.compareAQa = payload;
      state.artifactSources.compareAQaPath = sourceName;
      const derived = deriveCompareCompensation();
      if (state.compareCompensationSource !== "manual") {
        state.compareCompensationDb = derived.db;
        state.compareCompensationSource = derived.source;
      }
      renderCompare(ui);
      updateRuntimeMessage(ui, `Loaded A render QA: ${sourceName}`);
    },
    () => updateRuntimeMessage(ui, "A render_qa.json import is not valid JSON."),
  );
  bindJsonFileInput(
    ui.fileInputs.compareBQa,
    (payload, sourceName) => {
      state.artifacts.compareBQa = payload;
      state.artifactSources.compareBQaPath = sourceName;
      const derived = deriveCompareCompensation();
      if (state.compareCompensationSource !== "manual") {
        state.compareCompensationDb = derived.db;
        state.compareCompensationSource = derived.source;
      }
      renderCompare(ui);
      updateRuntimeMessage(ui, `Loaded B render QA: ${sourceName}`);
    },
    () => updateRuntimeMessage(ui, "B render_qa.json import is not valid JSON."),
  );

  void (async () => {
    const workspaceDir = ui.inputs.workspaceDir.value.trim();
    if (!workspaceDir) {
      return;
    }
    const paths = buildWorkflowPaths(workspaceDir);
    if (await artifactExists(paths.renderReceiptPath)) {
      await refreshResultsArtifacts(paths);
    }
    if (await artifactExists(paths.compareReportPath)) {
      state.artifacts.compare = await readArtifactJson<JsonObject>(paths.compareReportPath);
      state.artifactSources.comparePath = paths.compareReportPath;
    }
    renderAll(ui);
  })();
});
