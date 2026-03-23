import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { revealItemInDir } from "@tauri-apps/plugin-opener";

import {
  clamp,
  describeConfidence,
  initDesignSystem,
  roundToStep,
  SCREEN_ORDER,
  signedDb,
  type ScreenKey,
} from "./design-system";
import {
  humanizeFailureReason,
  renderOutcomeLabel,
  renderOutcomeTone,
  type DeliverableResultBucket,
} from "./status-display";
import {
  browseDirectory,
  browseFile,
  loadRecentPaths,
  recordRecentPath,
  saveRecentPaths,
  type RecentPathGroup,
  type RecentPathsState,
} from "./desktop-paths";
import {
  artifactExists,
  buildWorkflowPaths,
  dirname,
  executeMmo,
  isTauriRuntime,
  joinPath,
  normalizePath,
  readArtifactJson,
  resolveArtifactMediaUrl,
  resolveSiblingPath,
  runMmoRpc,
  spawnMmo,
  type MmoLivePayload,
  type MmoLogKind,
  type MmoRunResult,
  type WorkflowPaths,
  writeArtifactText,
} from "./mmo-sidecar";

type CommandStage = "analyze" | "compare" | "doctor" | "render" | "scene" | "validate";
type StageKey = Exclude<CommandStage, "doctor">;
type StageState = "fail" | "idle" | "pass" | "running" | "warn";
type CompareState = "A" | "B";
type ArtifactTag = "ALL" | "AUDIO" | "JSON" | "QA" | "RECEIPT";
type SceneLockStatusTone = "error" | "info" | "ok";
type WorkflowPathKey =
  | "workspace"
  | "project"
  | "projectValidation"
  | "report"
  | "scanReport"
  | "stemsMap"
  | "busPlan"
  | "busPlanCsv"
  | "scene"
  | "sceneLint"
  | "renderDir"
  | "renderManifest"
  | "renderReceipt"
  | "renderQa"
  | "compareReport";

type JsonObject = Record<string, unknown>;

type DoctorRunResult = {
  envDoctorPayload: JsonObject | null;
  envDoctorResult: MmoRunResult;
  ok: boolean;
  pluginsResult: MmoRunResult;
  versionResult: MmoRunResult;
};

type DesktopSmokeConfig = {
  layoutStandard: string;
  renderTarget: string;
  sceneLocksPath: string | null;
  stemsDir: string;
  summaryPath: string;
  workspaceDir: string;
};

type DesktopSmokeSummary = {
  appLaunchVerified: boolean;
  artifactPaths: Record<string, string>;
  doctor: {
    checks: JsonObject | null;
    dataRoot: string;
    envDoctorExitCode: number | null;
    ok: boolean;
    pluginsExitCode: number | null;
    versionExitCode: number | null;
  };
  error: string;
  ok: boolean;
  renderTarget: string;
  timelineTail: string[];
  workspaceDir: string;
};

type ArtifactEntry = {
  id: string;
  path: string;
  previewText: string;
  resolvedPath: string;
  summary: string;
  tag: ArtifactTag;
  title: string;
};

type QuickActionButtonSpec = {
  disabled?: boolean;
  label: string;
  onClick: () => void;
  title?: string;
};

const SCREEN_SHORTCUT_LABELS: Record<ScreenKey, string> = {
  analyze: "Alt+2",
  compare: "Alt+6",
  render: "Alt+4",
  results: "Alt+5",
  scene: "Alt+3",
  validate: "Alt+1",
};

type ChangeSummaryChip = {
  label: string;
  tone: "danger" | "info" | "ok" | "warn";
};

type RenderOutcomeSummary = {
  bucket: DeliverableResultBucket;
  deliverablesSummary: JsonObject;
  label: string;
  message: string | null;
  remedy: string | null;
  topFailureReason: string | null;
  topFailureReasonLabel: string | null;
  tone: "danger" | "info" | "ok" | "warn";
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

type AuditionSource = {
  id: string;
  label: string;
  mediaUrl: string;
  path: string;
};

type AuditionSourceState = {
  candidatePath: string;
  message: string;
  source: AuditionSource | null;
  status: "error" | "idle" | "loading" | "missing" | "ready";
};

type PlaybackContext = "compare" | "results" | null;

type PlaybackState = {
  context: PlaybackContext;
  error: string;
  requestToken: number;
  sourceId: string;
  status: "loading" | "paused" | "playing" | "stopped";
};

type CompareAuditionSourcesState = {
  A: AuditionSourceState;
  B: AuditionSourceState;
  refreshToken: number;
};

type DragState = {
  onMove: (event: PointerEvent) => void;
  onUp: (event: PointerEvent) => void;
  pointerId: number;
  surface: HTMLElement;
};

type SceneLockRoleOption = {
  label: string;
  roleId: string;
};

type SceneLockRowState = {
  confidence: number;
  editFrontOnly: boolean;
  editHeightCap: number;
  editRoleId: string;
  editSurroundCap: number;
  inferredRoleId: string;
  label: string;
  objectId: string;
  stemId: string;
};

type SceneLocksState = {
  dirty: boolean;
  isInspecting: boolean;
  isSaving: boolean;
  loadedSignature: string;
  objects: SceneLockRowState[];
  overridesCount: number;
  perspective: string;
  perspectiveValues: string[];
  roleOptions: SceneLockRoleOption[];
  sceneLocksPath: string;
  scenePath: string;
  statusMessage: string;
  statusTone: SceneLockStatusTone;
};

type AppUi = {
  artifactPreviewActions: HTMLElement;
  artifactPreviewTransport: {
    activeFile: HTMLElement;
    note: HTMLElement;
    pause: HTMLButtonElement;
    play: HTMLButtonElement;
    state: HTMLElement;
    stop: HTMLButtonElement;
  };
  abButtons: HTMLButtonElement[];
  auditionAudio: HTMLAudioElement;
  artifactPaths: HTMLElement;
  artifactPreviewDelta: HTMLElement;
  artifactPreviewName: HTMLElement;
  artifactPreviewSummary: HTMLElement;
  artifactSearch: HTMLInputElement;
  artifactTagButtons: HTMLButtonElement[];
  browseButtons: Record<
    | "compareAFolder"
    | "compareAFile"
    | "compareAQa"
    | "compareBFolder"
    | "compareBFile"
    | "compareBQa"
    | "compareReport"
    | "resultsManifest"
    | "resultsQa"
    | "resultsReceipt"
    | "sceneJson"
    | "sceneLint"
    | "sceneLocksPath"
    | "stemsDir"
    | "workspaceDir",
    HTMLButtonElement
  >;
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
  compareChangeSummary: HTMLElement;
  compareSummary: HTMLElement;
  compareSummaryNote: HTMLElement;
  compareTransport: {
    activeFile: HTMLElement;
    note: HTMLElement;
    pause: HTMLButtonElement;
    play: HTMLButtonElement;
    state: HTMLElement;
    stop: HTMLButtonElement;
  };
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
  recents: Record<
    "compareA" | "compareB" | "sceneLocksPath" | "stemsDir" | "workspaceDir",
    HTMLElement
  >;
  results: {
    browserList: HTMLElement;
    detailFill: HTMLElement;
    detailInput: HTMLInputElement;
    detailSlider: HTMLButtonElement;
    detailValue: HTMLElement;
    changeSummary: HTMLElement;
    confidenceList: HTMLElement;
    confidenceNote: HTMLElement;
    gainReductionMeter: HTMLElement;
    gainReductionValue: HTMLElement;
    jsonPreview: HTMLElement;
    phaseCorrelationMeter: HTMLElement;
    phaseCorrelationValue: HTMLElement;
    phaseNote: HTMLElement;
    qaActions: HTMLElement;
    qaText: HTMLElement;
    readoutNote: HTMLElement;
    readoutPrimary: HTMLElement;
    readoutSecondary: HTMLElement;
    summaryActions: HTMLElement;
    transferCurvePath: SVGPathElement;
    transferNote: HTMLElement;
    vectorscopePath: SVGPathElement;
    vectorscopeSummary: HTMLElement;
    whatChangedText: HTMLElement;
  };
  runtimeMessage: HTMLElement;
  screenPanels: Record<ScreenKey, HTMLElement>;
  screenTabs: Record<ScreenKey, HTMLButtonElement>;
  shell: HTMLElement;
  scene: {
    focusCaption: HTMLElement;
    focusDot: HTMLElement;
    focusPad: HTMLButtonElement;
    lockEditorDetails: HTMLDetailsElement;
    lockInspectButton: HTMLButtonElement;
    lockPerspectiveSelect: HTMLSelectElement;
    lockRows: HTMLElement;
    lockSaveButton: HTMLButtonElement;
    lockStatus: HTMLElement;
    lockSummaryDirty: HTMLElement;
    lockSummaryPath: HTMLElement;
    lockSummaryPerspective: HTMLElement;
    lockSummaryRows: HTMLElement;
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

const desktopTestRpcResults = new Map<string, JsonObject>();

function defaultScenePerspectiveValues(): string[] {
  return ["audience", "on_stage", "in_band", "in_orchestra"];
}

function sceneLocksSignature(rows: SceneLockRowState[], perspective: string): string {
  return JSON.stringify({
    perspective,
    rows: rows.map((row) => ({
      editFrontOnly: row.editFrontOnly,
      editHeightCap: row.editHeightCap,
      editRoleId: row.editRoleId,
      editSurroundCap: row.editSurroundCap,
      stemId: row.stemId,
    })),
  });
}

function emptySceneLocksState(): SceneLocksState {
  const perspectiveValues = defaultScenePerspectiveValues();
  const perspective = perspectiveValues[0] ?? "audience";
  return {
    dirty: false,
    isInspecting: false,
    isSaving: false,
    loadedSignature: sceneLocksSignature([], perspective),
    objects: [],
    overridesCount: 0,
    perspective,
    perspectiveValues,
    roleOptions: [],
    sceneLocksPath: "",
    scenePath: "",
    statusMessage: "Inspect scene locks to fine-tune how MMO places each part in the room.",
    statusTone: "info",
  };
}

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
  compareCompensationEvaluationOnly: true,
  compareCompensationMethodId: "",
  compareCompensationNote: "",
  compareCompensationSource: "none" as "compare_report" | "manual" | "none" | "render_qa",
  compareAuditionSources: {
    A: {
      candidatePath: "",
      message: "Set compare A to resolve an audition file.",
      source: null,
      status: "idle",
    },
    B: {
      candidatePath: "",
      message: "Set compare B to resolve an audition file.",
      source: null,
      status: "idle",
    },
    refreshToken: 0,
  } as CompareAuditionSourcesState,
  compareState: "A" as CompareState,
  currentCancelPath: null as string | null,
  dragState: null as DragState | null,
  nerdView: false,
  playback: {
    context: null as PlaybackContext,
    error: "",
    requestToken: 0,
    sourceId: "",
    status: "stopped" as PlaybackState["status"],
  },
  recentPaths: {
    compareInputs: [],
    sceneLocksPaths: [],
    stemsDirs: [],
    version: 1,
    workspaceDirs: [],
  } as RecentPathsState,
  resultsArtifactSearch: "",
  resultsArtifactTag: "ALL" as ArtifactTag,
  resultsDetailLevel: 6,
  sceneLocks: emptySceneLocksState(),
  selectedArtifactId: "",
  sceneFocusDepth: 50,
  sceneFocusPan: 0,
  timelineCount: 0,
};

let designController: ReturnType<typeof initDesignSystem> | null = null;
let auditionAudioContext: AudioContext | null = null;
let auditionAudioGainNode: GainNode | null = null;
let auditionAudioSourceNode: MediaElementAudioSourceNode | null = null;
const AUDITION_GAIN_SETUP_TIMEOUT_MS = 250;

function requiredElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (element === null) {
    throw new Error(`Missing required desktop workflow node: ${selector}`);
  }
  return element;
}

function getUi(): AppUi {
  return {
    artifactPreviewActions: requiredElement("#artifact-preview-actions"),
    artifactPreviewTransport: {
      activeFile: requiredElement("#artifact-preview-active-file"),
      note: requiredElement("#artifact-preview-transport-note"),
      pause: requiredElement("#artifact-preview-pause-button"),
      play: requiredElement("#artifact-preview-play-button"),
      state: requiredElement("#artifact-preview-transport-state"),
      stop: requiredElement("#artifact-preview-stop-button"),
    },
    abButtons: Array.from(document.querySelectorAll<HTMLButtonElement>("#ab-toggle [data-ab-state]")),
    auditionAudio: requiredElement("#audition-audio"),
    artifactPaths: requiredElement("#artifact-paths"),
    artifactPreviewDelta: requiredElement("#artifact-preview-delta"),
    artifactPreviewName: requiredElement("#artifact-preview-name"),
    artifactPreviewSummary: requiredElement("#artifact-preview-summary"),
    artifactSearch: requiredElement("#artifact-search"),
    artifactTagButtons: Array.from(
      document.querySelectorAll<HTMLButtonElement>("#artifact-tag-row [data-artifact-tag]"),
    ),
    browseButtons: {
      compareAFolder: requiredElement("#compare-a-folder-browse-button"),
      compareAFile: requiredElement("#compare-a-file-browse-button"),
      compareAQa: requiredElement("#compare-a-qa-browse-button"),
      compareBFolder: requiredElement("#compare-b-folder-browse-button"),
      compareBFile: requiredElement("#compare-b-file-browse-button"),
      compareBQa: requiredElement("#compare-b-qa-browse-button"),
      compareReport: requiredElement("#compare-report-browse-button"),
      resultsManifest: requiredElement("#results-manifest-browse-button"),
      resultsQa: requiredElement("#results-qa-browse-button"),
      resultsReceipt: requiredElement("#results-receipt-browse-button"),
      sceneJson: requiredElement("#scene-json-browse-button"),
      sceneLint: requiredElement("#scene-lint-browse-button"),
      sceneLocksPath: requiredElement("#scene-locks-browse-button"),
      stemsDir: requiredElement("#stems-dir-browse-button"),
      workspaceDir: requiredElement("#workspace-dir-browse-button"),
    },
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
    compareChangeSummary: requiredElement("#compare-change-summary"),
    compareSummary: requiredElement("#compare-summary"),
    compareSummaryNote: requiredElement("#compare-summary-note"),
    compareTransport: {
      activeFile: requiredElement("#compare-transport-active-file"),
      note: requiredElement("#compare-transport-note"),
      pause: requiredElement("#compare-transport-pause-button"),
      play: requiredElement("#compare-transport-play-button"),
      state: requiredElement("#compare-transport-state"),
      stop: requiredElement("#compare-transport-stop-button"),
    },
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
    recents: {
      compareA: requiredElement("#recent-compare-a-list"),
      compareB: requiredElement("#recent-compare-b-list"),
      sceneLocksPath: requiredElement("#recent-scene-locks-list"),
      stemsDir: requiredElement("#recent-stems-dir-list"),
      workspaceDir: requiredElement("#recent-workspace-dir-list"),
    },
    results: {
      browserList: requiredElement("#artifact-browser-list"),
      changeSummary: requiredElement("#results-change-summary"),
      confidenceList: requiredElement("#results-confidence-list"),
      confidenceNote: requiredElement("#results-confidence-note"),
      detailFill: requiredElement("#results-detail-fill"),
      detailInput: requiredElement("#results-detail-input"),
      detailSlider: requiredElement("#results-detail-slider"),
      detailValue: requiredElement("#results-detail-value"),
      gainReductionMeter: requiredElement("#results-gain-reduction-meter"),
      gainReductionValue: requiredElement("#results-gain-reduction-value"),
      jsonPreview: requiredElement("#results-json-preview"),
      phaseCorrelationMeter: requiredElement("#results-phase-correlation-meter"),
      phaseCorrelationValue: requiredElement("#results-phase-correlation-value"),
      phaseNote: requiredElement("#results-phase-note"),
      qaActions: requiredElement("#results-qa-actions"),
      qaText: requiredElement("#results-qa-text"),
      readoutNote: requiredElement("#results-readout-note"),
      readoutPrimary: requiredElement("#results-readout-primary"),
      readoutSecondary: requiredElement("#results-readout-secondary"),
      summaryActions: requiredElement("#results-summary-actions"),
      transferCurvePath: requiredElement("#results-transfer-curve-path"),
      transferNote: requiredElement("#results-transfer-note"),
      vectorscopePath: requiredElement("#results-vectorscope-path"),
      vectorscopeSummary: requiredElement("#results-vectorscope-summary"),
      whatChangedText: requiredElement("#results-what-changed-text"),
    },
    runtimeMessage: requiredElement("#runtime-message"),
    screenPanels: {
      analyze: requiredElement("#screen-analyze"),
      compare: requiredElement("#screen-compare"),
      render: requiredElement("#screen-render"),
      results: requiredElement("#screen-results"),
      scene: requiredElement("#screen-scene"),
      validate: requiredElement("#screen-validate"),
    },
    screenTabs: {
      analyze: requiredElement("#screen-tab-analyze"),
      compare: requiredElement("#screen-tab-compare"),
      render: requiredElement("#screen-tab-render"),
      results: requiredElement("#screen-tab-results"),
      scene: requiredElement("#screen-tab-scene"),
      validate: requiredElement("#screen-tab-validate"),
    },
    shell: requiredElement("#app-shell"),
    scene: {
      focusCaption: requiredElement("#scene-focus-caption"),
      focusDot: requiredElement("#scene-focus-dot"),
      focusPad: requiredElement("#scene-focus-pad"),
      lockEditorDetails: requiredElement("#scene-locks-editor-details"),
      lockInspectButton: requiredElement("#scene-locks-inspect-button"),
      lockPerspectiveSelect: requiredElement("#scene-locks-perspective-select"),
      lockRows: requiredElement("#scene-locks-editor"),
      lockSaveButton: requiredElement("#scene-locks-save-button"),
      lockStatus: requiredElement("#scene-locks-status"),
      lockSummaryDirty: requiredElement("#scene-lock-summary-dirty"),
      lockSummaryPath: requiredElement("#scene-lock-summary-path"),
      lockSummaryPerspective: requiredElement("#scene-lock-summary-perspective"),
      lockSummaryRows: requiredElement("#scene-lock-summary-rows"),
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

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const selector = "input, textarea, select, [contenteditable=''], [contenteditable='true']";
  return target.matches(selector) || target.closest(selector) !== null;
}

function isDisabledElement(element: HTMLElement): boolean {
  return "disabled" in element && Boolean((element as HTMLButtonElement | HTMLInputElement | HTMLSelectElement).disabled);
}

function focusPrimaryControlForScreen(ui: AppUi, screen: ScreenKey): void {
  const target: HTMLElement = (() => {
    switch (screen) {
      case "analyze":
        return ui.buttons.analyze;
      case "compare":
        return ui.compareInputs.aPath;
      case "render":
        return ui.buttons.render;
      case "results":
        return ui.artifactSearch;
      case "scene":
        return ui.buttons.scene;
      case "validate":
      default:
        return ui.buttons.validate;
    }
  })();
  if (!isDisabledElement(target)) {
    target.focus({ preventScroll: true });
    return;
  }
  ui.screenPanels[screen].focus({ preventScroll: true });
}

function setScreenAndFocus(
  ui: AppUi,
  controller: ReturnType<typeof initDesignSystem>,
  screen: ScreenKey,
): void {
  controller.setScreen(screen);
  window.requestAnimationFrame(() => {
    focusPrimaryControlForScreen(ui, screen);
  });
}

function resultsArtifactButtons(ui: AppUi): HTMLButtonElement[] {
  return Array.from(
    ui.results.browserList.querySelectorAll<HTMLButtonElement>("[data-artifact-entry-id]"),
  );
}

function focusResultsArtifactButton(ui: AppUi, artifactId: string): void {
  const button = resultsArtifactButtons(ui).find((item) => item.dataset.artifactEntryId === artifactId) ?? null;
  if (button === null) {
    return;
  }
  button.focus({ preventScroll: true });
  button.scrollIntoView({
    block: "nearest",
    inline: "nearest",
  });
}

function selectResultsArtifact(
  ui: AppUi,
  artifactId: string,
  options: { focusSelection?: boolean } = {},
): void {
  if (!artifactId) {
    return;
  }
  state.selectedArtifactId = artifactId;
  renderResults(ui);
  if (options.focusSelection) {
    focusResultsArtifactButton(ui, artifactId);
  }
}

function moveSelectedResultsArtifact(
  ui: AppUi,
  direction: "first" | "last" | "next" | "previous",
): void {
  const buttons = resultsArtifactButtons(ui);
  if (buttons.length === 0) {
    return;
  }
  const selectedIndex = buttons.findIndex((button) => {
    return button.dataset.artifactEntryId === state.selectedArtifactId;
  });
  const activeIndex = buttons.findIndex((button) => button === document.activeElement);
  const currentIndex = activeIndex >= 0 ? activeIndex : (selectedIndex >= 0 ? selectedIndex : 0);

  let nextIndex = currentIndex;
  if (direction === "first") {
    nextIndex = 0;
  } else if (direction === "last") {
    nextIndex = buttons.length - 1;
  } else if (direction === "next") {
    nextIndex = currentIndex >= buttons.length - 1 ? buttons.length - 1 : currentIndex + 1;
  } else if (direction === "previous") {
    nextIndex = currentIndex <= 0 ? 0 : currentIndex - 1;
  }

  const nextId = buttons[nextIndex]?.dataset.artifactEntryId ?? "";
  if (!nextId) {
    return;
  }
  selectResultsArtifact(ui, nextId, { focusSelection: true });
}

function applyShortcutMetadata(ui: AppUi): void {
  for (const screen of SCREEN_ORDER) {
    const button = ui.screenTabs[screen];
    const shortcut = SCREEN_SHORTCUT_LABELS[screen];
    button.title = `${button.textContent?.trim() || screen} (${shortcut})`;
    button.setAttribute("aria-keyshortcuts", shortcut);
  }

  ui.browseButtons.workspaceDir.title = "Browse workspace folder (Alt+Shift+W)";
  ui.browseButtons.workspaceDir.setAttribute("aria-keyshortcuts", "Alt+Shift+W");
  ui.browseButtons.stemsDir.title = "Browse stems folder (Alt+Shift+S)";
  ui.browseButtons.stemsDir.setAttribute("aria-keyshortcuts", "Alt+Shift+S");
  ui.buttons.validate.title = "Run Validate (Alt+Shift+V)";
  ui.buttons.validate.setAttribute("aria-keyshortcuts", "Alt+Shift+V");
  ui.buttons.render.title = "Run Render (Alt+Shift+R)";
  ui.buttons.render.setAttribute("aria-keyshortcuts", "Alt+Shift+R");
  ui.artifactSearch.title = "Jump to Results search (/)";
  ui.artifactSearch.setAttribute("aria-keyshortcuts", "/");
  ui.results.detailSlider.title = "Adjust Results detail depth with arrow keys, Home/End, or drag";
  ui.compareCompensation.knob.title = "Adjust B compensation with arrow keys, Home/End, or drag";
  ui.scene.focusPad.title = "Adjust scene focus with arrow keys or drag";
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

function cloneJsonObject<T extends JsonObject>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
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

function isDirectMediaUrl(pathValue: string): boolean {
  return /^(?:asset|blob|data|https?):/iu.test(pathValue);
}

function isDesktopTestRuntime(): boolean {
  return typeof window !== "undefined" && window.__MMO_DESKTOP_TEST__ !== undefined;
}

function isAudioFilePath(pathValue: string): boolean {
  return /\.(?:aif|aiff|m4a|mp3|ogg|wav)$/iu.test(pathValue);
}

function audioContextConstructor(): typeof AudioContext | null {
  if (typeof window.AudioContext === "function") {
    return window.AudioContext;
  }
  const webkitWindow = window as Window & {
    webkitAudioContext?: typeof AudioContext;
  };
  if (typeof webkitWindow.webkitAudioContext === "function") {
    return webkitWindow.webkitAudioContext;
  }
  return null;
}

function auditionGainSetupTimeout<T>(fallback: T): Promise<T> {
  return new Promise((resolve) => {
    window.setTimeout(() => resolve(fallback), AUDITION_GAIN_SETUP_TIMEOUT_MS);
  });
}

function isAuditionContextRunning(context: AudioContext): boolean {
  return context.state === "running";
}

async function ensureAuditionGainNode(audio: HTMLAudioElement): Promise<GainNode | null> {
  const AudioContextCtor = audioContextConstructor();
  if (AudioContextCtor === null) {
    return null;
  }
  if (auditionAudioContext === null) {
    auditionAudioContext = new AudioContextCtor();
  }
  if (auditionAudioSourceNode === null || auditionAudioGainNode === null) {
    auditionAudioSourceNode = auditionAudioContext.createMediaElementSource(audio);
    auditionAudioGainNode = auditionAudioContext.createGain();
    auditionAudioSourceNode.connect(auditionAudioGainNode);
    auditionAudioGainNode.connect(auditionAudioContext.destination);
  }
  if (auditionAudioContext.state === "closed") {
    return null;
  }
  if (auditionAudioContext.state !== "running") {
    const resumed = await Promise.race([
      (async () => {
        try {
          await auditionAudioContext.resume();
        } catch {
          return false;
        }
        return isAuditionContextRunning(auditionAudioContext);
      })(),
      auditionGainSetupTimeout(false),
    ]);
    if (!resumed && !isAuditionContextRunning(auditionAudioContext)) {
      return null;
    }
  }
  if (!isAuditionContextRunning(auditionAudioContext)) {
    return null;
  }
  return auditionAudioGainNode;
}

function gainDbToLinear(gainDb: number): number {
  return 10 ** (gainDb / 20);
}

function clampUnitValue(value: unknown, fallback: number): number {
  const numeric = asNumber(value);
  if (numeric === null) {
    return fallback;
  }
  return clamp(numeric, 0, 1);
}

function normalizeSceneLockRoleOptions(value: unknown): SceneLockRoleOption[] {
  const normalized = asArray(value)
    .map(asObject)
    .filter((row): row is JsonObject => row !== null)
    .map((row) => ({
      label: asString(row.label).trim() || asString(row.role_id).trim(),
      roleId: asString(row.role_id).trim(),
    }))
    .filter((row) => row.roleId.length > 0);
  normalized.sort((left, right) => left.roleId.localeCompare(right.roleId));
  return normalized;
}

function normalizeSceneLockRows(value: unknown): SceneLockRowState[] {
  const rows: SceneLockRowState[] = [];
  for (const item of asArray(value)) {
    const row = asObject(item);
    if (row === null) {
      continue;
    }
    const stemId = asString(row.stem_id).trim();
    if (!stemId) {
      continue;
    }
    const objectId = asString(row.object_id).trim() || `OBJ.${stemId}`;
    const label = asString(row.label).trim() || objectId;
    const inferredRoleId = asString(row.inferred_role_id).trim();
    const roleOverrideId = asString(row.role_override_id).trim();
    const surroundOverride = asNumber(row.surround_cap_override);
    const heightOverride = asNumber(row.height_cap_override);
    const frontOnlyOverride = row.front_only_override === true || (surroundOverride !== null && surroundOverride <= 0);
    rows.push({
      confidence: clampUnitValue(row.confidence, 0),
      editFrontOnly: frontOnlyOverride,
      editHeightCap: heightOverride === null ? 1 : clampUnitValue(heightOverride, 1),
      editRoleId: roleOverrideId,
      editSurroundCap: frontOnlyOverride ? 0 : (surroundOverride === null ? 1 : clampUnitValue(surroundOverride, 1)),
      inferredRoleId,
      label,
      objectId,
      stemId,
    });
  }
  rows.sort((left, right) => {
    if (left.objectId !== right.objectId) {
      return left.objectId.localeCompare(right.objectId);
    }
    return left.stemId.localeCompare(right.stemId);
  });
  return rows;
}

function average(values: number[]): number | null {
  if (values.length === 0) {
    return null;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

async function readDesktopSmokeConfig(): Promise<DesktopSmokeConfig | null> {
  if (!isTauriRuntime()) {
    return null;
  }
  try {
    const payload = await invoke<DesktopSmokeConfig | null>("desktop_smoke_config");
    if (payload === null) {
      return null;
    }
    return payload;
  } catch {
    return null;
  }
}

function collectTimelineTail(ui: AppUi, maxItems: number): string[] {
  const items = Array.from(ui.timeline.querySelectorAll(".timeline-item-body"));
  return items
    .slice(Math.max(0, items.length - maxItems))
    .map((item) => item.textContent?.trim() ?? "")
    .filter((line) => line.length > 0);
}

function formatNumber(value: number | null, digits = 1, suffix = ""): string {
  if (value === null) {
    return "n/a";
  }
  return `${value.toFixed(digits)}${suffix}`;
}

function formatScopedLabel(scope: JsonObject | null): string {
  if (scope === null) {
    return "unspecified";
  }
  return (
    asString(scope.stem_id) ||
    asString(scope.bus_id) ||
    asString(scope.layout_id) ||
    (scope.global === true ? "global" : "unspecified")
  );
}

function numericDeltaValue(delta: JsonObject | null): number | null {
  if (delta === null) {
    return null;
  }
  const from = asNumber(delta.from);
  const to = asNumber(delta.to);
  if (from === null || to === null) {
    return null;
  }
  return to - from;
}

function formatExitSummary(result: MmoRunResult): string {
  return `exit=${result.code ?? "null"} signal=${result.signal ?? "null"}`;
}

function failureOutputLines(text: string): string[] {
  return text
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function firstMeaningfulFailureLine(result: MmoRunResult): string | null {
  const lines = [
    ...failureOutputLines(result.stderr),
    ...failureOutputLines(result.stdout),
  ];
  if (lines.length === 0) {
    return null;
  }
  const preferred = lines.find((line) => /error|failed|missing|invalid|traceback|blocked|not found/i.test(line));
  return preferred ?? lines[0];
}

function stageFailureWhat(stageLabel: string): string {
  switch (stageLabel) {
    case "doctor":
      return "Doctor could not finish the health check.";
    case "validate":
      return "Validate could not finish checking the session.";
    case "analyze":
      return "Analyze could not finish listening to the stems.";
    case "scene":
      return "Scene could not finish building the placement plan.";
    case "render":
      return "Render could not finish the bounce.";
    case "compare":
      return "Compare could not finish the A/B check.";
    default:
      return `${stageLabel} could not finish.`;
  }
}

function stageFailureNextStep(stageLabel: string): string {
  switch (stageLabel) {
    case "doctor":
      return "Run Doctor again after checking FFmpeg/ffprobe and the packaged install. If it still fails, reinstall the release build.";
    case "validate":
      return "Check that your stems folder and workspace folder are both set, then fix the first reported problem and rerun Validate.";
    case "analyze":
      return "Check that the stems folder exists, contains audio files, and that FFmpeg/ffprobe are available, then rerun Analyze.";
    case "scene":
      return "Open the first scene warning or error, fix the missing file or lock issue, then rebuild the scene.";
    case "render":
      return "Open the receipt or QA output, fix the first blocked item, then rerun Render.";
    case "compare":
      return "Choose two finished runs or two report.json files, then rerun Compare.";
    default:
      return "Fix the first reported problem and try the step again.";
  }
}

function formatFailureOutput(result: MmoRunResult): string {
  const lines = [formatExitSummary(result)];
  const reason = firstMeaningfulFailureLine(result);
  if (reason) {
    lines.push(`reason: ${reason}`);
  }
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

const WORKSPACE_ROOT_ARTIFACT_LEAVES = new Set([
  "bus_plan.json",
  "bus_plan.summary.csv",
  "compare_report.json",
  "compare_report.pdf",
  "render_manifest.json",
  "render_qa.json",
  "report.json",
  "report.scan.json",
  "safe_render_receipt.json",
  "scene.json",
  "scene_lint.json",
  "stems_map.json",
  "validation.json",
]);

function basename(pathValue: string): string {
  const normalized = normalizePath(pathValue);
  if (!normalized) {
    return "";
  }
  const separatorIndex = normalized.lastIndexOf("/");
  if (separatorIndex < 0) {
    return normalized;
  }
  return normalized.slice(separatorIndex + 1);
}

function isAbsoluteLikePath(pathValue: string): boolean {
  const normalized = normalizePath(pathValue);
  if (!normalized) {
    return false;
  }
  return (
    normalized.startsWith("/")
    || /^[A-Za-z]:\//u.test(normalized)
    || normalized.startsWith("//")
  );
}

function workspaceDirFromArtifactPath(pathValue: string): string {
  const normalized = normalizePath(pathValue);
  if (!normalized) {
    return "";
  }
  const lower = normalized.toLowerCase();
  const renderMarker = "/render/";
  const renderIndex = lower.lastIndexOf(renderMarker);
  if (renderIndex > 0) {
    return normalized.slice(0, renderIndex);
  }
  if (lower.endsWith("/render")) {
    return dirname(normalized);
  }
  const leaf = basename(normalized).toLowerCase();
  if (WORKSPACE_ROOT_ARTIFACT_LEAVES.has(leaf)) {
    return dirname(normalized);
  }
  return normalized;
}

function resolveArtifactPath(pathValue: string, paths: WorkflowPaths | null): string {
  const normalized = normalizePath(pathValue);
  if (!normalized) {
    return "";
  }
  if (isDirectMediaUrl(normalized) || isAbsoluteLikePath(normalized) || paths === null) {
    return normalized;
  }
  return joinPath(paths.workspaceDir, normalized);
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

async function copyTextToClipboard(text: string): Promise<void> {
  if (
    typeof navigator !== "undefined"
    && navigator.clipboard
    && typeof navigator.clipboard.writeText === "function"
  ) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const fallbackInput = document.createElement("textarea");
  fallbackInput.value = text;
  fallbackInput.setAttribute("readonly", "");
  fallbackInput.style.opacity = "0";
  fallbackInput.style.pointerEvents = "none";
  fallbackInput.style.position = "fixed";
  fallbackInput.style.top = "-1000px";
  document.body.appendChild(fallbackInput);
  fallbackInput.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(fallbackInput);
  if (!copied) {
    throw new Error("Clipboard write is unavailable in this desktop context.");
  }
}

function renderQuickActionButtons(
  container: HTMLElement,
  buttons: QuickActionButtonSpec[],
): void {
  container.innerHTML = "";
  for (const buttonSpec of buttons) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button-secondary button-compact";
    button.textContent = buttonSpec.label;
    button.disabled = buttonSpec.disabled === true;
    button.title = buttonSpec.title ?? buttonSpec.label;
    button.addEventListener("click", buttonSpec.onClick);
    container.append(button);
  }
}

function hasLoadedWorkspaceContext(ui: AppUi): boolean {
  if (ui.inputs.workspaceDir.value.trim()) {
    return true;
  }
  return Object.values(state.artifacts).some((artifact) => artifact !== null);
}

function updateWorkspaceMode(ui: AppUi): void {
  ui.shell.dataset.workspaceMode = hasLoadedWorkspaceContext(ui) ? "compact" : "hero";
}

function persistRecentPathsState(): void {
  void saveRecentPaths(state.recentPaths);
}

function commitRecentPath(ui: AppUi, group: RecentPathGroup, value: string): void {
  const next = recordRecentPath(state.recentPaths, group, value);
  if (JSON.stringify(next[group]) === JSON.stringify(state.recentPaths[group])) {
    return;
  }
  state.recentPaths = next;
  renderRecentPaths(ui);
  persistRecentPathsState();
}

function defaultBrowsePath(currentValue: string, recents: string[]): string | undefined {
  const trimmed = currentValue.trim();
  return trimmed || recents[0];
}

function renderRecentChipList(
  container: HTMLElement,
  items: string[],
  emptyLabel: string,
  onSelect: (value: string) => void,
): void {
  container.innerHTML = "";
  if (items.length === 0) {
    const empty = document.createElement("p");
    empty.className = "recent-chip-empty";
    empty.textContent = emptyLabel;
    container.append(empty);
    return;
  }

  for (const item of items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "recent-chip button-secondary";
    button.textContent = item;
    button.title = item;
    button.addEventListener("click", () => {
      onSelect(item);
    });
    container.append(button);
  }
}

function renderRecentPaths(ui: AppUi): void {
  renderRecentChipList(ui.recents.stemsDir, state.recentPaths.stemsDirs, "No stems folders yet.", (value) => {
    ui.inputs.stemsDir.value = value;
    commitRecentPath(ui, "stemsDirs", value);
    renderAll(ui);
  });
  renderRecentChipList(ui.recents.workspaceDir, state.recentPaths.workspaceDirs, "No workspaces yet.", (value) => {
    ui.inputs.workspaceDir.value = value;
    commitRecentPath(ui, "workspaceDirs", value);
    resetSceneLocksState("Inspect scene locks to fine-tune how MMO places each part in the room.");
    renderAll(ui);
  });
  renderRecentChipList(ui.recents.sceneLocksPath, state.recentPaths.sceneLocksPaths, "No scene-lock artifacts yet.", (value) => {
    ui.inputs.sceneLocksPath.value = value;
    commitRecentPath(ui, "sceneLocksPaths", value);
    renderAll(ui);
  });
  renderRecentChipList(ui.recents.compareA, state.recentPaths.compareInputs, "No compare inputs yet.", (value) => {
    ui.compareInputs.aPath.value = value;
    commitRecentPath(ui, "compareInputs", value);
    scheduleCompareAuditionRefresh(ui);
    renderCompare(ui);
  });
  renderRecentChipList(ui.recents.compareB, state.recentPaths.compareInputs, "No compare inputs yet.", (value) => {
    ui.compareInputs.bPath.value = value;
    commitRecentPath(ui, "compareInputs", value);
    scheduleCompareAuditionRefresh(ui);
    renderCompare(ui);
  });
}

function setWorkspaceInput(ui: AppUi, workspaceDir: string): void {
  const normalized = normalizePath(workspaceDir);
  if (!normalized || ui.inputs.workspaceDir.value.trim() === normalized) {
    return;
  }
  ui.inputs.workspaceDir.value = normalized;
  commitRecentPath(ui, "workspaceDirs", normalized);
  resetSceneLocksState("Inspect scene locks to fine-tune how MMO places each part in the room.");
}

function setCompareInput(
  ui: AppUi,
  side: "aPath" | "bPath",
  value: string,
): void {
  const normalized = normalizePath(value);
  ui.compareInputs[side].value = normalized;
  if (normalized) {
    commitRecentPath(ui, "compareInputs", normalized);
  }
}

function openResultsArtifact(ui: AppUi, artifactId: string, message: string): void {
  state.selectedArtifactId = artifactId;
  designController?.setScreen("results");
  renderResults(ui);
  updateRuntimeMessage(ui, message);
}

async function copyArtifactPath(ui: AppUi, pathValue: string, label: string): Promise<void> {
  const normalized = normalizePath(pathValue);
  if (!normalized) {
    updateRuntimeMessage(ui, `No ${label.toLowerCase()} path is available to copy.`);
    return;
  }
  await copyTextToClipboard(normalized);
  updateRuntimeMessage(ui, `${label} path copied to the clipboard.`);
}

async function revealArtifactPath(ui: AppUi, pathValue: string, label: string): Promise<void> {
  const normalized = normalizePath(pathValue);
  if (!normalized) {
    updateRuntimeMessage(ui, `No ${label.toLowerCase()} path is available to reveal.`);
    return;
  }
  try {
    await revealItemInDir(normalized);
    updateRuntimeMessage(ui, `Revealed ${label.toLowerCase()} in the file manager.`);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    updateRuntimeMessage(ui, `Unable to reveal ${label.toLowerCase()}: ${detail}`);
  }
}

function prepareCompareInputsFromCandidate(
  ui: AppUi,
  candidatePath: string,
): { message: string; ready: boolean } {
  const candidate = normalizePath(candidatePath);
  if (!candidate) {
    throw new Error("No compare-ready artifact path is available.");
  }

  let aPath = normalizePath(ui.compareInputs.aPath.value);
  let bPath = normalizePath(ui.compareInputs.bPath.value);

  if (!aPath && !bPath) {
    aPath = candidate;
  } else if (aPath === candidate || bPath === candidate) {
    // Keep the selected artifact on the side where it already lives.
  } else if (!aPath) {
    aPath = candidate;
  } else if (!bPath) {
    bPath = candidate;
  } else {
    aPath = candidate;
  }

  setCompareInput(ui, "aPath", aPath);
  setCompareInput(ui, "bPath", bPath);

  const ready = Boolean(aPath && bPath);
  if (!ready) {
    return {
      message: `Selected ${candidate} for compare. Pick the other side to rerun compare.`,
      ready: false,
    };
  }
  if (aPath === candidate && bPath) {
    return {
      message: `Rerunning compare with ${candidate} as A against the current B input.`,
      ready: true,
    };
  }
  if (bPath === candidate && aPath) {
    return {
      message: `Rerunning compare with ${candidate} as B against the current A input.`,
      ready: true,
    };
  }
  return {
    message: `Rerunning compare from ${candidate}.`,
    ready: true,
  };
}

function queueCompareFromArtifact(ui: AppUi, candidatePath: string): void {
  const candidate = normalizePath(candidatePath);
  if (!candidate) {
    updateRuntimeMessage(ui, "No compare-ready artifact path is available.");
    return;
  }

  const workspaceDir = workspaceDirFromArtifactPath(candidate);
  if (workspaceDir) {
    setWorkspaceInput(ui, workspaceDir);
  }

  designController?.setScreen("compare");
  const prepared = prepareCompareInputsFromCandidate(ui, candidate);
  renderAll(ui);
  scheduleCompareAuditionRefresh(ui);
  if (!prepared.ready) {
    updateRuntimeMessage(ui, prepared.message);
    return;
  }
  void runWithBusy(ui, "compare", async () => {
    updateRuntimeMessage(ui, prepared.message);
    await runCompare(ui);
  }, true);
}

function queueRenderFromWorkspace(ui: AppUi, workspaceDir: string): void {
  const normalized = normalizePath(workspaceDir);
  if (!normalized) {
    updateRuntimeMessage(ui, "No render-ready workspace path is available.");
    return;
  }
  if (designController === null) {
    updateRuntimeMessage(ui, "Render controls are not ready yet.");
    return;
  }
  const controller = designController;
  setWorkspaceInput(ui, normalized);
  controller.setScreen("render");
  renderAll(ui);
  void runWithBusy(ui, "render", async () => {
    updateRuntimeMessage(ui, `Rerunning render from ${normalized}.`);
    await runRender(ui, controller);
  }, true);
}

async function browseAndLoadJson(
  input: HTMLInputElement,
  options: {
    defaultPath?: string;
    label: string;
    onFailure: () => void;
    onLoad: (payload: JsonObject, sourceName: string) => void;
    title: string;
  },
): Promise<void> {
  if (!isTauriRuntime()) {
    input.click();
    return;
  }

  const path = await browseFile({
    defaultPath: options.defaultPath,
    extensions: ["json"],
    label: options.label,
    title: options.title,
  });
  if (!path) {
    return;
  }

  const payload = await readArtifactJson<JsonObject>(path);
  if (payload === null) {
    options.onFailure();
    return;
  }
  options.onLoad(payload, path);
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
  ui.scene.lockInspectButton.disabled = busy || !ui.inputs.workspaceDir.value.trim() || state.sceneLocks.isInspecting || state.sceneLocks.isSaving;
  ui.scene.lockSaveButton.disabled = busy || state.sceneLocks.isInspecting || state.sceneLocks.isSaving || !state.sceneLocks.dirty || state.sceneLocks.objects.length === 0;
  for (const button of Object.values(ui.browseButtons)) {
    button.disabled = busy;
  }
}

function buildRenderCancelPath(paths: WorkflowPaths): string {
  return joinPath(paths.renderCancelDir, `safe_render.cancel.${Date.now().toString(36)}.json`);
}

function collectWorkspacePaths(ui: AppUi): { paths: WorkflowPaths; workspaceDir: string } {
  const workspaceDir = ui.inputs.workspaceDir.value.trim();
  if (!workspaceDir) {
    throw new Error(
      "Choose a workspace folder first.\n"
      + "Why: MMO uses the workspace like a session notebook for reports, scenes, renders, and receipts.\n"
      + "Next: Pick an empty or reusable folder where you want all outputs to live.",
    );
  }
  return {
    paths: buildWorkflowPaths(workspaceDir),
    workspaceDir,
  };
}

function collectWorkspaceAndStems(ui: AppUi): {
  paths: WorkflowPaths;
  stemsDir: string;
  workspaceDir: string;
} {
  const stemsDir = ui.inputs.stemsDir.value.trim();
  if (!stemsDir) {
    throw new Error(
      "Choose a stems folder first.\n"
      + "Why: MMO needs the folder that holds the exported audio tracks it will listen to.\n"
      + "Next: Pick the folder that contains your stem WAVs or similar audio files.",
    );
  }
  return {
    ...collectWorkspacePaths(ui),
    stemsDir,
  };
}

function collectSceneInputs(ui: AppUi): {
  paths: WorkflowPaths;
  sceneLocksPath: string;
  stemsDir: string;
  workspaceDir: string;
} {
  return {
    ...collectWorkspaceAndStems(ui),
    sceneLocksPath: ui.inputs.sceneLocksPath.value.trim(),
  };
}

function collectRenderInputs(ui: AppUi): {
  layoutStandard: string;
  paths: WorkflowPaths;
  renderTarget: string;
  sceneLocksPath: string;
  workspaceDir: string;
} {
  return {
    ...collectWorkspacePaths(ui),
    layoutStandard: ui.inputs.layoutStandard.value,
    renderTarget: ui.inputs.renderTarget.value,
    sceneLocksPath: ui.inputs.sceneLocksPath.value.trim(),
  };
}

function collectCompareInputs(ui: AppUi): {
  aPath: string;
  bPath: string;
  paths: WorkflowPaths;
  workspaceDir: string;
} {
  return {
    ...collectWorkspacePaths(ui),
    aPath: ui.compareInputs.aPath.value.trim(),
    bPath: ui.compareInputs.bPath.value.trim(),
  };
}

function buildResultsOpenButtons(
  ui: AppUi,
  options: {
    labels?: Partial<Record<"manifest" | "qa" | "receipt", string>>;
    skip?: string[];
  } = {},
): QuickActionButtonSpec[] {
  const skip = new Set(options.skip ?? []);
  const hasWorkspace = ui.inputs.workspaceDir.value.trim().length > 0;
  const labels = {
    manifest: options.labels?.manifest ?? "Manifest",
    qa: options.labels?.qa ?? "QA",
    receipt: options.labels?.receipt ?? "Receipt",
  };
  const buttons: QuickActionButtonSpec[] = [];
  if (!skip.has("receipt")) {
    buttons.push({
      disabled: !hasWorkspace && state.artifacts.receipt === null && !state.artifactSources.receiptPath,
      label: labels.receipt,
      onClick: () => {
        openResultsArtifact(ui, "receipt", "Opened safe-render receipt.");
      },
    });
  }
  if (!skip.has("manifest")) {
    buttons.push({
      disabled: !hasWorkspace && state.artifacts.manifest === null && !state.artifactSources.manifestPath,
      label: labels.manifest,
      onClick: () => {
        openResultsArtifact(ui, "manifest", "Opened render manifest.");
      },
    });
  }
  if (!skip.has("qa")) {
    buttons.push({
      disabled: !hasWorkspace && state.artifacts.qa === null && !state.artifactSources.qaPath,
      label: labels.qa,
      onClick: () => {
        openResultsArtifact(ui, "qa", "Opened render QA.");
      },
    });
  }
  return buttons;
}

function buildPathRowActionButtons(
  ui: AppUi,
  label: string,
  pathKey: WorkflowPathKey,
  pathValue: string,
  paths: WorkflowPaths,
): QuickActionButtonSpec[] {
  const buttons: QuickActionButtonSpec[] = [];
  buttons.push({
    label: "Copy",
    onClick: () => {
      void copyArtifactPath(ui, pathValue, label);
    },
  });
  buttons.push({
    label: "Reveal",
    onClick: () => {
      void revealArtifactPath(ui, pathValue, label);
    },
  });

  if (pathKey === "workspace" || pathKey === "report" || pathKey === "scene") {
    buttons.push(
      ...buildResultsOpenButtons(ui),
      {
        label: "Render",
        onClick: () => {
          const workspaceDir = pathKey === "workspace" ? pathValue : dirname(pathValue);
          queueRenderFromWorkspace(ui, workspaceDir);
        },
      },
    );
  }

  if (pathKey === "report") {
    buttons.push({
      label: "Compare",
      onClick: () => {
        queueCompareFromArtifact(ui, pathValue);
      },
    });
  }

  if (pathKey === "renderManifest" || pathKey === "renderReceipt" || pathKey === "renderQa") {
    const skip = pathKey === "renderManifest"
      ? ["manifest"]
      : (pathKey === "renderReceipt" ? ["receipt"] : ["qa"]);
    buttons.push(...buildResultsOpenButtons(ui, { skip }));
    buttons.push({
      label: "Compare",
      onClick: () => {
        queueCompareFromArtifact(ui, paths.workspaceDir);
      },
    });
  }

  return buttons;
}

function renderPathRow(
  ui: AppUi,
  container: HTMLElement,
  label: string,
  pathValue: string,
  pathKey: WorkflowPathKey,
  paths: WorkflowPaths,
): void {
  const row = document.createElement("div");
  row.className = "path-row";

  const dt = document.createElement("dt");
  dt.textContent = label;

  const dd = document.createElement("dd");
  dd.textContent = pathValue;

  row.append(dt, dd);
  const actions = buildPathRowActionButtons(ui, label, pathKey, pathValue, paths);
  if (actions.length > 0) {
    const actionRow = document.createElement("div");
    actionRow.className = "path-actions";
    renderQuickActionButtons(actionRow, actions);
    row.append(actionRow);
  }

  container.append(row);
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
  const rows: Array<{ key: WorkflowPathKey; label: string; value: string }> = [
    { key: "workspace", label: "workspace", value: paths.workspaceDir },
    { key: "project", label: "project", value: paths.projectDir },
    { key: "projectValidation", label: "project validation", value: paths.projectValidationPath },
    { key: "report", label: "analysis report", value: paths.reportPath },
    { key: "scanReport", label: "analysis scan", value: paths.scanReportPath },
    { key: "stemsMap", label: "stems map", value: paths.stemsMapPath },
    { key: "busPlan", label: "bus plan", value: paths.busPlanPath },
    { key: "busPlanCsv", label: "bus plan csv", value: paths.busPlanCsvPath },
    { key: "scene", label: "scene", value: paths.scenePath },
    { key: "sceneLint", label: "scene lint", value: paths.sceneLintPath },
    { key: "renderDir", label: "render dir", value: paths.renderDir },
    { key: "renderManifest", label: "render manifest", value: paths.renderManifestPath },
    { key: "renderReceipt", label: "safe-render receipt", value: paths.renderReceiptPath },
    { key: "renderQa", label: "render qa", value: paths.renderQaPath },
    { key: "compareReport", label: "compare report", value: paths.compareReportPath },
  ];

  for (const row of rows) {
    renderPathRow(ui, ui.artifactPaths, row.label, row.value, row.key, paths);
    if (row.key === "project" || row.key === "projectValidation") {
      renderPathRow(ui, ui.validate.artifactPaths, row.label, row.value, row.key, paths);
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
    for (const row of warnings) {
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
    `scene_locks_input=${sceneLocksPath || "(not set)"}`,
    `editor_scene_locks_path=${state.sceneLocks.sceneLocksPath || "(not loaded)"}`,
    `editor_scene_path=${state.sceneLocks.scenePath || "(not loaded)"}`,
    `scene_path=${state.artifactSources.scenePath || "(not loaded)"}`,
    `scene_lint_path=${state.artifactSources.sceneLintPath || "(not loaded)"}`,
    `scene_lock_rows=${state.sceneLocks.objects.length}`,
    `scene_lock_unsaved=${state.sceneLocks.dirty}`,
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
  if (state.sceneLocks.statusMessage.trim()) {
    lines.push(`scene_lock_editor_status=${state.sceneLocks.statusMessage.trim()}`);
  }
  return lines.join("\n");
}

function setSelectOptions(
  select: HTMLSelectElement,
  options: Array<{ label: string; value: string }>,
  selectedValue: string,
): void {
  const nextMarkup = options
    .map((option) => `<option value="${option.value}">${option.label}</option>`)
    .join("");
  if (select.innerHTML !== nextMarkup) {
    select.innerHTML = nextMarkup;
  }
  select.value = options.some((option) => option.value === selectedValue)
    ? selectedValue
    : (options[0]?.value ?? "");
}

const RENDER_TARGET_SELECT_ALIASES: Record<string, string[]> = {
  stereo: [
    "TARGET.STEREO.2_0",
    "TARGET.STEREO.2_0_ALT",
    "LAYOUT.2_0",
    "2.0",
    "2_0",
  ],
  "5.1": [
    "TARGET.SURROUND.5_1",
    "LAYOUT.5_1",
    "5_1",
    "surround51",
  ],
  "7.1.4": [
    "TARGET.IMMERSIVE.7_1_4",
    "LAYOUT.7_1_4",
    "7_1_4",
    "immersive714",
  ],
  binaural: [
    "TARGET.HEADPHONES.BINAURAL",
    "LAYOUT.BINAURAL",
    "headphone",
    "headphones",
  ],
};

function normalizeSelectAliasToken(value: string): string {
  return value.trim().toLowerCase().replace(/[\s-]+/gu, "_");
}

function supportedSelectOptions(select: HTMLSelectElement): string {
  return Array.from(select.options)
    .map((option) => `"${option.value}" (${option.label})`)
    .join(", ");
}

function resolveSelectValue(
  select: HTMLSelectElement,
  requestedValue: string,
  aliasesByValue: Record<string, string[]> = {},
): string | null {
  const trimmedRequestedValue = requestedValue.trim();
  if (!trimmedRequestedValue) {
    return null;
  }
  const optionValues = new Set(Array.from(select.options).map((option) => option.value));
  if (optionValues.has(trimmedRequestedValue)) {
    return trimmedRequestedValue;
  }

  const normalizedRequestedValue = normalizeSelectAliasToken(trimmedRequestedValue);
  for (const optionValue of optionValues) {
    if (normalizeSelectAliasToken(optionValue) === normalizedRequestedValue) {
      return optionValue;
    }
  }

  for (const [optionValue, aliases] of Object.entries(aliasesByValue)) {
    if (!optionValues.has(optionValue)) {
      continue;
    }
    const tokens = [optionValue, ...aliases];
    if (tokens.some((token) => normalizeSelectAliasToken(token) === normalizedRequestedValue)) {
      return optionValue;
    }
  }
  return null;
}

function syncSceneLocksDirty(): void {
  state.sceneLocks.dirty = sceneLocksSignature(
    state.sceneLocks.objects,
    state.sceneLocks.perspective,
  ) !== state.sceneLocks.loadedSignature;
}

function updateSceneLockRow(stemId: string, patch: Partial<SceneLockRowState>): void {
  state.sceneLocks.objects = state.sceneLocks.objects.map((row) => {
    if (row.stemId !== stemId) {
      return row;
    }
    const next: SceneLockRowState = {
      ...row,
      ...patch,
      editFrontOnly: (patch.editFrontOnly ?? row.editFrontOnly) === true,
      editHeightCap: clampUnitValue(patch.editHeightCap ?? row.editHeightCap, row.editHeightCap),
      editRoleId: typeof (patch.editRoleId ?? row.editRoleId) === "string"
        ? (patch.editRoleId ?? row.editRoleId).trim()
        : row.editRoleId,
      editSurroundCap: clampUnitValue(patch.editSurroundCap ?? row.editSurroundCap, row.editSurroundCap),
    };
    if (next.editFrontOnly) {
      next.editSurroundCap = 0;
    }
    return next;
  });
  syncSceneLocksDirty();
}

function hydrateSceneLocksInspect(
  payload: JsonObject,
  {
    autoFillMode,
    statusMessage,
    statusTone,
    ui,
  }: {
    autoFillMode: "always" | "if-empty";
    statusMessage: string;
    statusTone: SceneLockStatusTone;
    ui: AppUi;
  },
): void {
  const previousSceneLocksPath = state.sceneLocks.sceneLocksPath;
  const perspectiveValues = asArray(payload.perspective_values)
    .map((item) => asString(item).trim())
    .filter(Boolean);
  const normalizedPerspectiveValues = perspectiveValues.length > 0
    ? perspectiveValues
    : defaultScenePerspectiveValues();
  const perspective = asString(payload.perspective).trim();
  const nextPerspective = normalizedPerspectiveValues.includes(perspective)
    ? perspective
    : (normalizedPerspectiveValues[0] ?? "audience");
  const objects = normalizeSceneLockRows(payload.objects);

  state.sceneLocks = {
    dirty: false,
    isInspecting: false,
    isSaving: state.sceneLocks.isSaving,
    loadedSignature: sceneLocksSignature(objects, nextPerspective),
    objects,
    overridesCount: asNumber(payload.overrides_count) ?? 0,
    perspective: nextPerspective,
    perspectiveValues: normalizedPerspectiveValues,
    roleOptions: normalizeSceneLockRoleOptions(payload.role_options),
    sceneLocksPath: asString(payload.scene_locks_path).trim(),
    scenePath: asString(payload.scene_path).trim(),
    statusMessage,
    statusTone,
  };

  const currentInputPath = ui.inputs.sceneLocksPath.value.trim();
  if (
    state.sceneLocks.sceneLocksPath &&
    (
      autoFillMode === "always" ||
      currentInputPath.length === 0 ||
      currentInputPath === previousSceneLocksPath
    )
  ) {
    ui.inputs.sceneLocksPath.value = state.sceneLocks.sceneLocksPath;
  }
}

function renderSceneLockEditor(ui: AppUi): void {
  const workspaceDir = ui.inputs.workspaceDir.value.trim();
  const hasRows = state.sceneLocks.objects.length > 0;
  const globalBusy = state.busyStage !== null;
  const editorBusy = state.sceneLocks.isInspecting || state.sceneLocks.isSaving;
  const canInspect = workspaceDir.length > 0 && !globalBusy && !editorBusy;
  const canSave = hasRows && state.sceneLocks.dirty && !globalBusy && !editorBusy;

  ui.scene.lockInspectButton.disabled = !canInspect;
  ui.scene.lockSaveButton.disabled = !canSave;
  ui.scene.lockPerspectiveSelect.disabled = !hasRows || globalBusy || editorBusy;
  ui.scene.lockSummaryPerspective.textContent = state.sceneLocks.perspective || "(not loaded)";
  ui.scene.lockSummaryRows.textContent = hasRows
    ? `${state.sceneLocks.objects.length} row(s), ${state.sceneLocks.overridesCount} override(s)`
    : "No rows loaded.";
  ui.scene.lockSummaryPath.textContent = state.sceneLocks.sceneLocksPath || "(project save path unavailable)";
  ui.scene.lockSummaryDirty.textContent = state.sceneLocks.dirty ? "Yes" : "No";
  ui.scene.lockStatus.textContent = state.sceneLocks.statusMessage;
  ui.scene.lockStatus.dataset.tone = state.sceneLocks.statusTone;

  setSelectOptions(
    ui.scene.lockPerspectiveSelect,
    state.sceneLocks.perspectiveValues.map((value) => ({ label: value, value })),
    state.sceneLocks.perspective,
  );

  ui.scene.lockRows.innerHTML = "";
  if (!workspaceDir) {
    const empty = document.createElement("p");
    empty.className = "scene-lock-empty";
    empty.textContent = "Choose a workspace folder first, then inspect scene locks to fine-tune the placement plan.";
    ui.scene.lockRows.append(empty);
    return;
  }
  if (!hasRows) {
    const empty = document.createElement("p");
    empty.className = "scene-lock-empty";
    empty.textContent = state.sceneLocks.isInspecting
      ? "Loading scene lock rows..."
      : "No scene lock rows loaded yet. Use Inspect Scene Locks to load the current project draft.";
    ui.scene.lockRows.append(empty);
    return;
  }

  for (const row of state.sceneLocks.objects) {
    const card = document.createElement("article");
    card.className = "scene-lock-row";

    const header = document.createElement("div");
    header.className = "scene-lock-row-header";

    const title = document.createElement("div");
    title.className = "scene-lock-row-title";
    title.textContent = `${row.label} (${row.stemId})`;

    const meta = document.createElement("div");
    meta.className = "scene-lock-row-meta";
    meta.textContent = `${row.objectId} · confidence ${(row.confidence * 100).toFixed(0)}%`;

    header.append(title, meta);
    card.append(header);

    const controls = document.createElement("div");
    controls.className = "scene-lock-row-controls";

    const roleField = document.createElement("label");
    roleField.className = "field scene-lock-field";
    const roleLabel = document.createElement("span");
    roleLabel.className = "field-label";
    roleLabel.textContent = "Role override";
    const roleSelect = document.createElement("select");
    roleSelect.className = "field-input";
    setSelectOptions(
      roleSelect,
      [
        {
          label: row.inferredRoleId ? `Auto (${row.inferredRoleId})` : "Auto",
          value: "",
        },
        ...state.sceneLocks.roleOptions.map((option) => ({
          label: `${option.roleId} · ${option.label}`,
          value: option.roleId,
        })),
      ],
      row.editRoleId,
    );
    roleSelect.disabled = globalBusy || editorBusy;
    roleSelect.addEventListener("change", () => {
      updateSceneLockRow(row.stemId, { editRoleId: roleSelect.value });
      renderSceneLockEditor(ui);
    });
    roleField.append(roleLabel, roleSelect);
    controls.append(roleField);

    const frontOnlyLabel = document.createElement("label");
    frontOnlyLabel.className = "toggle-inline scene-lock-front-toggle";
    const frontOnlyInput = document.createElement("input");
    frontOnlyInput.type = "checkbox";
    frontOnlyInput.checked = row.editFrontOnly;
    frontOnlyInput.disabled = globalBusy || editorBusy;
    frontOnlyInput.addEventListener("change", () => {
      updateSceneLockRow(row.stemId, {
        editFrontOnly: frontOnlyInput.checked,
        editSurroundCap: frontOnlyInput.checked ? 0 : (row.editSurroundCap <= 0 ? 1 : row.editSurroundCap),
      });
      renderSceneLockEditor(ui);
    });
    const frontOnlyText = document.createElement("span");
    frontOnlyText.textContent = "Front-only";
    frontOnlyLabel.append(frontOnlyInput, frontOnlyText);
    controls.append(frontOnlyLabel);

    const capGrid = document.createElement("div");
    capGrid.className = "scene-lock-cap-grid";

    const appendCapControl = (
      label: string,
      value: number,
      disabled: boolean,
      onChange: (nextValue: number) => void,
      valueLabel: string,
    ) => {
      const field = document.createElement("label");
      field.className = "field scene-lock-field";

      const top = document.createElement("span");
      top.className = "field-label";
      top.textContent = label;

      const rangeRow = document.createElement("div");
      rangeRow.className = "scene-lock-range-row";

      const slider = document.createElement("input");
      slider.className = "scene-lock-range";
      slider.type = "range";
      slider.min = "0";
      slider.max = "1";
      slider.step = "0.01";
      slider.value = value.toFixed(2);
      slider.disabled = disabled;
      slider.addEventListener("input", () => {
        onChange(clampUnitValue(slider.value, value));
        renderSceneLockEditor(ui);
      });

      const numberWrap = document.createElement("span");
      numberWrap.className = "scene-lock-number-wrap";
      const numberInput = document.createElement("input");
      numberInput.className = "value-input scene-lock-number";
      numberInput.type = "number";
      numberInput.min = "0";
      numberInput.max = "1";
      numberInput.step = "0.01";
      numberInput.value = value.toFixed(2);
      numberInput.disabled = disabled;
      numberInput.addEventListener("change", () => {
        onChange(clampUnitValue(numberInput.value, value));
        renderSceneLockEditor(ui);
      });
      const unit = document.createElement("span");
      unit.className = "control-unit control-unit-inline";
      unit.textContent = "ratio";
      numberWrap.append(numberInput, unit);

      rangeRow.append(slider, numberWrap);

      const valueNote = document.createElement("span");
      valueNote.className = "scene-lock-slider-value";
      valueNote.textContent = valueLabel;

      field.append(top, rangeRow, valueNote);
      capGrid.append(field);
    };

    appendCapControl(
      "Surround cap",
      row.editSurroundCap,
      row.editFrontOnly || globalBusy || editorBusy,
      (nextValue) => {
        updateSceneLockRow(row.stemId, {
          editFrontOnly: nextValue > 0 ? false : row.editFrontOnly,
          editSurroundCap: nextValue,
        });
      },
      row.editFrontOnly ? "forced to 0.00 while front-only is enabled" : `${row.editSurroundCap.toFixed(2)} ratio`,
    );

    appendCapControl(
      "Height cap",
      row.editHeightCap,
      globalBusy || editorBusy,
      (nextValue) => {
        updateSceneLockRow(row.stemId, { editHeightCap: nextValue });
      },
      `${row.editHeightCap.toFixed(2)} ratio`,
    );

    controls.append(capGrid);
    card.append(controls);
    ui.scene.lockRows.append(card);
  }
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
  ui.scene.focusPad.setAttribute(
    "aria-label",
    `Scene focus XY pad, pan ${Math.round(pan)} degrees, depth ${Math.round(depth)} percent`,
  );

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

function resolveDeliverables(
  receipt: JsonObject | null,
  manifest: JsonObject | null,
  qa: JsonObject | null,
): JsonObject[] {
  const candidates = [
    asArray(manifest?.deliverables),
    asArray(receipt?.deliverables),
    asArray(qa?.deliverables),
  ];
  for (const candidate of candidates) {
    const deliverables = candidate
      .map(asObject)
      .filter((row): row is JsonObject => row !== null);
    if (deliverables.length > 0) {
      return deliverables;
    }
  }
  return [];
}

function deliverableFailureReason(deliverable: JsonObject): string | null {
  const explicitReason = asString(deliverable.failure_reason).trim();
  if (explicitReason) {
    return explicitReason;
  }
  const warningCodes = asArray(deliverable.warning_codes)
    .map(asString)
    .map((value) => value.trim())
    .filter(Boolean);
  return warningCodes[0] ?? null;
}

function deriveDeliverableResultBucket(summary: JsonObject): DeliverableResultBucket {
  const explicitBucket = asString(summary.result_bucket).trim();
  if (
    explicitBucket === "diagnostics_only"
    || explicitBucket === "full_failure"
    || explicitBucket === "partial_success"
    || explicitBucket === "success_no_master"
    || explicitBucket === "valid_master"
  ) {
    return explicitBucket;
  }

  const overallStatus = asString(summary.overall_status).trim();
  const validMasterCount = asNumber(summary.valid_master_count) ?? 0;
  if (overallStatus === "success") {
    return validMasterCount > 0 ? "valid_master" : "success_no_master";
  }
  if (overallStatus === "partial") {
    return "partial_success";
  }
  if (overallStatus === "invalid_master") {
    return "diagnostics_only";
  }
  if (overallStatus === "failed") {
    return "full_failure";
  }
  return "unknown";
}

function resolveRenderOutcomeSummary(
  receipt: JsonObject | null,
  manifest: JsonObject | null,
  qa: JsonObject | null,
): RenderOutcomeSummary | null {
  const deliverablesSummary = resolveDeliverablesSummary(receipt, manifest, qa);
  if (deliverablesSummary === null) {
    return null;
  }

  const resultSummary = resolveResultSummary(receipt, manifest);
  const deliverables = resolveDeliverables(receipt, manifest, qa);
  const bucket = deriveDeliverableResultBucket(deliverablesSummary);
  let topFailureReason = asString(resultSummary?.top_failure_reason).trim()
    || asString(deliverablesSummary.top_failure_reason).trim()
    || null;
  if (topFailureReason === null) {
    const rankedFailures = deliverables
      .map((deliverable) => {
        const status = asString(deliverable.status).trim();
        const reason = deliverableFailureReason(deliverable);
        let priority = 99;
        if (status === "failed") {
          priority = 0;
        } else if (status === "invalid_master") {
          priority = 1;
        } else if (status === "partial") {
          priority = 2;
        }
        return { priority, reason, status };
      })
      .filter((row) => row.priority < 99 && row.reason);
    rankedFailures.sort((left, right) => {
      return left.priority - right.priority || String(left.reason).localeCompare(String(right.reason));
    });
    topFailureReason = rankedFailures[0]?.reason ?? null;
  }

  const label = asString(resultSummary?.title).trim() || renderOutcomeLabel(bucket);
  return {
    bucket,
    deliverablesSummary,
    label,
    message: asString(resultSummary?.message).trim() || null,
    remedy: asString(resultSummary?.remedy).trim() || null,
    topFailureReason,
    topFailureReasonLabel: topFailureReason ? humanizeFailureReason(topFailureReason) : null,
    tone: renderOutcomeTone(bucket),
  };
}

function resolveOutputDeliverable(output: JsonObject, deliverables: JsonObject[]): JsonObject | null {
  const outputId = asString(output.output_id).trim();
  if (!outputId) {
    return null;
  }
  return deliverables.find((deliverable) => {
    return asArray(deliverable.output_ids).map(asString).includes(outputId);
  }) ?? null;
}

function summarizeManifestArtifact(
  receipt: JsonObject | null,
  manifest: JsonObject | null,
  qa: JsonObject | null,
): string {
  const outputCount = flattenManifestOutputs(manifest).length;
  const renderOutcome = resolveRenderOutcomeSummary(receipt, manifest, qa);
  if (renderOutcome === null) {
    return `${outputCount} output artifact(s) in manifest`;
  }
  return [
    renderOutcome.label,
    renderOutcome.message ?? "",
    `outputs=${outputCount}`,
  ].filter(Boolean).join(" · ");
}

function summarizeOutputArtifact(
  output: JsonObject,
  deliverable: JsonObject | null,
  summaryRow: JsonObject | null = null,
): string {
  const parts: string[] = [];
  if (deliverable !== null) {
    const artifactRole = asString(deliverable.artifact_role).trim();
    const status = asString(deliverable.status).trim();
    if (artifactRole === "master") {
      if (deliverable.is_valid_master === true) {
        parts.push("Valid master");
      } else if (status === "invalid_master") {
        parts.push("Diagnostic master");
      } else if (status === "failed") {
        parts.push("Failed master");
      } else if (status === "partial") {
        parts.push("Partial master");
      } else {
        parts.push("Master artifact");
      }
    } else if (artifactRole === "processed_stem") {
      parts.push(status === "partial" ? "Partial stem artifact" : "Processed stem");
    } else if (artifactRole === "processed_bus") {
      parts.push(status === "partial" ? "Partial bus artifact" : "Processed bus");
    }

    const failureReason = deliverableFailureReason(deliverable);
    if (failureReason !== null && status !== "success") {
      parts.push(humanizeFailureReason(failureReason));
    }
  } else if (summaryRow !== null) {
    const validity = asString(summaryRow.validity).trim();
    if (validity === "valid_master") {
      parts.push("Valid master");
    } else if (validity === "diagnostics_only") {
      parts.push("Diagnostic master");
    } else if (validity === "full_failure") {
      parts.push("Failed render");
    } else if (validity === "partial_success") {
      parts.push("Partial render");
    } else if (validity === "success_no_master") {
      parts.push("Rendered artifact");
    }
    const failureReason = asString(summaryRow.failure_reason).trim();
    if (failureReason && validity !== "valid_master") {
      parts.push(humanizeFailureReason(failureReason));
    }
  }
  parts.push(asString(output.format) || "audio");
  parts.push(asString(output.renderer_id) || "renderer");
  return parts.filter(Boolean).join(" · ");
}

function artifactPreviewForOutput(
  output: JsonObject,
  deliverable: JsonObject | null = null,
  summaryRow: JsonObject | null = null,
): string {
  const channelCount = asNumber(summaryRow?.channel_count) ?? asNumber(output.channel_count);
  const sampleRateHz = asNumber(summaryRow?.sample_rate_hz) ?? asNumber(output.sample_rate_hz);
  const renderedFrameCount = asNumber(summaryRow?.rendered_frame_count);
  const durationSeconds = asNumber(summaryRow?.duration_seconds);
  const lines = [
    `renderer_id=${asString(output.renderer_id) || "-"}`,
    `output_id=${asString(output.output_id) || "-"}`,
    `file_path=${asString(output.file_path) || "-"}`,
    `layout_id=${asString(output.layout_id) || "-"}`,
    `channel_count=${channelCount ?? "-"}`,
    `sample_rate_hz=${sampleRateHz ?? "-"}`,
    `rendered_frame_count=${renderedFrameCount ?? "-"}`,
    `duration_seconds=${durationSeconds ?? "-"}`,
    `format=${asString(output.format) || "-"}`,
    `recommendation_id=${asString(output.recommendation_id) || "-"}`,
  ];
  if (deliverable !== null) {
    lines.push(`deliverable_status=${asString(deliverable.status) || "-"}`);
    lines.push(`is_valid_master=${String(deliverable.is_valid_master === true)}`);
    lines.push(`failure_reason=${deliverableFailureReason(deliverable) || "-"}`);
  }
  if (summaryRow !== null) {
    lines.push(`validity=${asString(summaryRow.validity) || "-"}`);
    lines.push(`summary_status=${asString(summaryRow.status) || "-"}`);
    lines.push(`summary_failure_reason=${asString(summaryRow.failure_reason) || "-"}`);
  }
  return lines.join("\n");
}

function buildArtifactEntries(paths: WorkflowPaths | null): ArtifactEntry[] {
  const entries: ArtifactEntry[] = [];
  const deliverables = resolveDeliverables(
    state.artifacts.receipt,
    state.artifacts.manifest,
    state.artifacts.qa,
  );
  const deliverableSummaryRows = resolveDeliverableSummaryRows(
    state.artifacts.receipt,
    state.artifacts.manifest,
  );

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
    const resolvedPath = resolveArtifactPath(path, paths);
    entries.push({
      id,
      path: resolvedPath || path,
      previewText: payload === null
        ? "Artifact not loaded yet. Refresh Results or import the artifact to inspect it here."
        : serializeJson(payload, state.nerdView ? 60 : Math.max(12, state.resultsDetailLevel * 3)),
      resolvedPath,
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
    summarizeManifestArtifact(
      state.artifacts.receipt,
      state.artifacts.manifest,
      state.artifacts.qa,
    ),
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
    const rawPath = asString(output.file_path);
    const resolvedPath = resolveArtifactPath(rawPath, paths);
    const deliverable = resolveOutputDeliverable(output, deliverables);
    const summaryRow = resolveOutputSummaryRow(output, deliverableSummaryRows);
    entries.push({
      id: `audio:${outputId}`,
      path: resolvedPath || rawPath,
      previewText: artifactPreviewForOutput(output, deliverable, summaryRow),
      resolvedPath,
      summary: summarizeOutputArtifact(output, deliverable, summaryRow),
      tag: "AUDIO",
      title: rawPath || outputId,
    });
  }

  entries.sort((left, right) => left.title.localeCompare(right.title));
  return entries;
}

function auditionPathLabel(pathValue: string): string {
  const normalized = normalizePath(pathValue);
  if (!normalized) {
    return "(no file)";
  }
  if (isDirectMediaUrl(normalized)) {
    return "embedded audition audio";
  }
  return basename(normalized) || normalized;
}

function auditionReadyState(source: AuditionSource, message: string, candidatePath: string): AuditionSourceState {
  return {
    candidatePath,
    message,
    source,
    status: "ready",
  };
}

function auditionMissingState(candidatePath: string, message: string): AuditionSourceState {
  return {
    candidatePath,
    message,
    source: null,
    status: "missing",
  };
}

function auditionErrorState(candidatePath: string, message: string): AuditionSourceState {
  return {
    candidatePath,
    message,
    source: null,
    status: "error",
  };
}

function buildAuditionSource(
  id: string,
  label: string,
  resolvedPath: string,
): AuditionSourceState {
  const mediaUrl = resolveArtifactMediaUrl(resolvedPath);
  if (!mediaUrl) {
    return auditionErrorState(
      resolvedPath,
      `Unable to open ${auditionPathLabel(resolvedPath)} for in-app playback in this runtime.`,
    );
  }
  return auditionReadyState(
    {
      id,
      label,
      mediaUrl,
      path: resolvedPath,
    },
    `Ready: ${auditionPathLabel(resolvedPath)}`,
    resolvedPath,
  );
}

function auditionOutputPriority(output: JsonObject): [number, number, string] {
  const rawPath = asString(output.file_path).trim();
  const normalized = rawPath.toLowerCase();
  const format = asString(output.format).trim().toLowerCase();
  const previewPriority = /(?:audition|binaural|headphone|preview)/u.test(normalized) ? 0 : 1;
  const wavPriority = format === "wav" || normalized.endsWith(".wav") ? 0 : 1;
  return [previewPriority, wavPriority, normalized];
}

function preferredAuditionOutput(manifest: JsonObject | null): JsonObject | null {
  const outputs = flattenManifestOutputs(manifest).filter((output) => {
    const filePath = asString(output.file_path).trim();
    const format = asString(output.format).trim().toLowerCase();
    return Boolean(filePath) && (
      isDirectMediaUrl(filePath)
      || isAudioFilePath(filePath)
      || ["aif", "aiff", "m4a", "mp3", "ogg", "wav"].includes(format)
    );
  });
  outputs.sort((left, right) => {
    const leftPriority = auditionOutputPriority(left);
    const rightPriority = auditionOutputPriority(right);
    return (
      leftPriority[0] - rightPriority[0]
      || leftPriority[1] - rightPriority[1]
      || leftPriority[2].localeCompare(rightPriority[2])
    );
  });
  return outputs[0] ?? null;
}

function compareAuditionCandidatePath(sideKey: "a" | "b", ui: AppUi): string {
  const inputPath = sideKey === "a" ? ui.compareInputs.aPath.value : ui.compareInputs.bPath.value;
  if (inputPath.trim()) {
    return normalizePath(inputPath);
  }
  const compareSide = asObject(state.artifacts.compare?.[sideKey]);
  return normalizePath(asString(compareSide?.report_path));
}

async function resolveCompareAuditionSource(
  side: CompareState,
  candidatePath: string,
): Promise<AuditionSourceState> {
  const normalized = normalizePath(candidatePath);
  if (!normalized) {
    return auditionMissingState(
      "",
      `Set compare ${side} to a workspace, report, render artifact, or audition file.`,
    );
  }

  if (isDirectMediaUrl(normalized) || isAudioFilePath(normalized)) {
    return buildAuditionSource(
      `compare:${side}:${normalized}`,
      `${side} · ${auditionPathLabel(normalized)}`,
      normalized,
    );
  }

  const workspaceDir = workspaceDirFromArtifactPath(normalized);
  if (!workspaceDir) {
    return auditionMissingState(
      normalized,
      `Unable to derive a workspace for compare ${side}.`,
    );
  }

  const manifestPath = joinPath(workspaceDir, "render_manifest.json");
  const manifest = await readArtifactJson<JsonObject>(manifestPath);
  if (manifest === null) {
    return auditionMissingState(
      normalized,
      `No render_manifest.json found for compare ${side}.`,
    );
  }

  const output = preferredAuditionOutput(manifest);
  if (output === null) {
    return auditionMissingState(
      normalized,
      `Compare ${side} has no playable audio outputs in render_manifest.json.`,
    );
  }

  const resolvedOutputPath = resolveArtifactPath(
    asString(output.file_path),
    buildWorkflowPaths(workspaceDir),
  );
  if (!resolvedOutputPath) {
    return auditionErrorState(
      normalized,
      `Compare ${side} resolved an empty audition path.`,
    );
  }

  const resolved = buildAuditionSource(
    `compare:${side}:${resolvedOutputPath}`,
    `${side} · ${auditionPathLabel(resolvedOutputPath)}`,
    resolvedOutputPath,
  );
  if (resolved.status !== "ready") {
    return resolved;
  }
  return {
    ...resolved,
    message: `Compare ${side} uses ${auditionPathLabel(resolvedOutputPath)} from render_manifest.json.`,
  };
}

function resultsAuditionSource(selected: ArtifactEntry | null): AuditionSourceState {
  if (selected === null || selected.tag !== "AUDIO") {
    return auditionMissingState(
      "",
      "Select an audio artifact in Results to preview it here.",
    );
  }
  const resolvedPath = selected.resolvedPath || selected.path;
  if (!resolvedPath) {
    return auditionMissingState(
      "",
      "Selected audio artifact does not expose a playable path.",
    );
  }
  const resolved = buildAuditionSource(
    `results:${selected.id}:${resolvedPath}`,
    selected.title || auditionPathLabel(resolvedPath),
    resolvedPath,
  );
  if (resolved.status !== "ready") {
    return resolved;
  }
  return {
    ...resolved,
    message: `Selected artifact: ${auditionPathLabel(resolvedPath)}`,
  };
}

function activeCompareAuditionSource(): AuditionSource | null {
  const active = state.compareAuditionSources[state.compareState];
  return active.source;
}

function renderTransportStateLabel(
  context: PlaybackContext,
  sourceId: string,
  fallback: string,
): string {
  if (state.playback.context !== context || state.playback.sourceId !== sourceId) {
    return fallback;
  }
  if (state.playback.status === "loading") {
    return "Loading";
  }
  if (state.playback.status === "playing") {
    return "Playing";
  }
  if (state.playback.status === "paused") {
    return "Paused";
  }
  return fallback;
}

async function applyAuditionGain(ui: AppUi, gainDb: number): Promise<void> {
  const linear = gainDbToLinear(gainDb);
  if (isDesktopTestRuntime()) {
    ui.auditionAudio.volume = clamp(linear, 0, 1);
    return;
  }

  let gainNode: GainNode | null = null;
  try {
    gainNode = await Promise.race([
      ensureAuditionGainNode(ui.auditionAudio),
      auditionGainSetupTimeout<GainNode | null>(null),
    ]);
  } catch {
    gainNode = null;
  }

  if (gainNode !== null) {
    gainNode.gain.value = linear;
    ui.auditionAudio.volume = 1;
    return;
  }
  ui.auditionAudio.volume = clamp(linear, 0, 1);
}

function compareAuditionGainDb(): number {
  return state.compareState === "B" ? state.compareCompensationDb : 0;
}

function renderResultsTransport(ui: AppUi, selected: ArtifactEntry | null): void {
  const transportState = resultsAuditionSource(selected);
  if (
    state.playback.context === "results"
    && (
      transportState.source === null
      || state.playback.sourceId !== transportState.source.id
    )
    && state.playback.status !== "stopped"
  ) {
    stopAuditionPlayback(ui);
  }

  const source = transportState.source;
  const isCurrent = source !== null
    && state.playback.context === "results"
    && state.playback.sourceId === source.id;
  ui.artifactPreviewTransport.state.textContent = source === null
    ? (transportState.status === "error" ? "Unavailable" : "Stopped")
    : renderTransportStateLabel("results", source.id, "Stopped");
  ui.artifactPreviewTransport.activeFile.textContent = source === null
    ? transportState.message
    : `Active file: ${source.label}`;
  ui.artifactPreviewTransport.note.textContent = [
    transportState.message,
    state.playback.context === "results" && state.playback.error ? state.playback.error : "",
  ].filter(Boolean).join(" ");
  ui.artifactPreviewTransport.play.disabled = source === null || state.playback.status === "loading";
  ui.artifactPreviewTransport.pause.disabled = !isCurrent || state.playback.status !== "playing";
  ui.artifactPreviewTransport.stop.disabled = !isCurrent || state.playback.status === "stopped";
}

function renderCompareTransport(ui: AppUi): void {
  const activeState = state.compareAuditionSources[state.compareState];
  const inactiveState = state.compareAuditionSources[state.compareState === "A" ? "B" : "A"];
  const source = activeState.source;
  const isCurrent = source !== null
    && state.playback.context === "compare"
    && state.playback.sourceId === source.id;
  ui.compareTransport.state.textContent = source === null
    ? (activeState.status === "loading" ? "Loading" : (activeState.status === "error" ? "Unavailable" : "Stopped"))
    : renderTransportStateLabel("compare", source.id, "Stopped");
  ui.compareTransport.activeFile.textContent = source === null
    ? activeState.message
    : `Active ${state.compareState}: ${auditionPathLabel(source.path)}`;
  ui.compareTransport.note.textContent = [
    `A: ${state.compareAuditionSources.A.source?.label ?? state.compareAuditionSources.A.message}`,
    `B: ${state.compareAuditionSources.B.source?.label ?? state.compareAuditionSources.B.message}`,
    source !== null && state.compareState === "B"
      ? `Fair-listen gain on B: ${signedDb(state.compareCompensationDb)}.`
      : "",
    inactiveState.status === "loading" ? "Resolving alternate side..." : "",
    state.playback.context === "compare" && state.playback.error ? state.playback.error : "",
  ].filter(Boolean).join(" ");
  ui.compareTransport.play.disabled = source === null || activeState.status === "loading" || state.playback.status === "loading";
  ui.compareTransport.pause.disabled = !isCurrent || state.playback.status !== "playing";
  ui.compareTransport.stop.disabled = !isCurrent || state.playback.status === "stopped";
}

function renderAuditionTransports(ui: AppUi): void {
  const paths = ui.inputs.workspaceDir.value.trim()
    ? buildWorkflowPaths(ui.inputs.workspaceDir.value.trim())
    : null;
  const selected = buildArtifactEntries(paths).find((entry) => entry.id === state.selectedArtifactId) ?? null;
  renderResultsTransport(ui, selected);
  renderCompareTransport(ui);
}

function waitForAuditionReady(audio: HTMLAudioElement, mediaUrl: string): Promise<void> {
  if (audio.readyState >= 1 || isDirectMediaUrl(mediaUrl) || isDesktopTestRuntime()) {
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    const cleanup = () => {
      audio.removeEventListener("canplay", onReady);
      audio.removeEventListener("loadedmetadata", onReady);
      audio.removeEventListener("error", onError);
      window.clearTimeout(timer);
    };
    const settle = (callback: () => void) => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      callback();
    };
    const onReady = () => settle(resolve);
    const onError = () => settle(() => reject(new Error("Audio metadata could not be loaded.")));
    const timer = window.setTimeout(() => settle(resolve), 400);
    audio.addEventListener("canplay", onReady, { once: true });
    audio.addEventListener("loadedmetadata", onReady, { once: true });
    audio.addEventListener("error", onError, { once: true });
  });
}

async function activateAuditionSource(
  ui: AppUi,
  source: AuditionSource,
  context: Exclude<PlaybackContext, null>,
  options: {
    autoplay: boolean;
    gainDb: number;
    preserveTime: number;
  },
): Promise<void> {
  const token = state.playback.requestToken + 1;
  state.playback.requestToken = token;
  state.playback.context = context;
  state.playback.error = "";
  state.playback.sourceId = source.id;
  state.playback.status = "loading";
  renderAuditionTransports(ui);

  const audio = ui.auditionAudio;
  try {
    await applyAuditionGain(ui, options.gainDb);
    const sourceChanged = audio.dataset.sourceId !== source.id || audio.src !== source.mediaUrl;
    if (sourceChanged) {
      audio.src = source.mediaUrl;
      audio.dataset.sourceId = source.id;
      try {
        audio.load();
      } catch {
        // Ignore runtimes that reject explicit load().
      }
      await waitForAuditionReady(audio, source.mediaUrl);
    }
    if (state.playback.requestToken !== token) {
      return;
    }
    try {
      audio.currentTime = Math.max(0, options.preserveTime);
    } catch {
      // Some codecs refuse early seeks before metadata fully settles.
    }
    await applyAuditionGain(ui, options.gainDb);
    if (options.autoplay) {
      await audio.play();
      if (state.playback.requestToken !== token) {
        return;
      }
      state.playback.status = audio.paused ? "paused" : "playing";
    } else {
      audio.pause();
      state.playback.status = audio.currentTime > 0 ? "paused" : "stopped";
    }
  } catch (error) {
    if (state.playback.requestToken !== token) {
      return;
    }
    state.playback.error = error instanceof Error ? error.message : String(error);
    state.playback.status = "stopped";
  }
  renderAuditionTransports(ui);
}

function pauseAuditionPlayback(ui: AppUi): void {
  ui.auditionAudio.pause();
  state.playback.status = ui.auditionAudio.currentTime > 0 ? "paused" : "stopped";
  renderAuditionTransports(ui);
}

function stopAuditionPlayback(ui: AppUi): void {
  state.playback.requestToken += 1;
  ui.auditionAudio.pause();
  try {
    ui.auditionAudio.currentTime = 0;
  } catch {
    // Ignore seek failures during stop.
  }
  state.playback.error = "";
  state.playback.status = "stopped";
  renderAuditionTransports(ui);
}

async function playResultsAudition(ui: AppUi): Promise<void> {
  const paths = ui.inputs.workspaceDir.value.trim()
    ? buildWorkflowPaths(ui.inputs.workspaceDir.value.trim())
    : null;
  const selected = buildArtifactEntries(paths).find((entry) => entry.id === state.selectedArtifactId) ?? null;
  const transportState = resultsAuditionSource(selected);
  if (transportState.source === null) {
    state.playback.error = transportState.message;
    renderAuditionTransports(ui);
    return;
  }
  const preserveTime = (
    state.playback.context === "results"
    && state.playback.sourceId === transportState.source.id
  )
    ? ui.auditionAudio.currentTime
    : 0;
  await activateAuditionSource(ui, transportState.source, "results", {
    autoplay: true,
    gainDb: 0,
    preserveTime,
  });
}

async function playCompareAudition(
  ui: AppUi,
  options: {
    autoplay: boolean;
    preserveTime?: number;
  } = { autoplay: true },
): Promise<void> {
  const active = activeCompareAuditionSource();
  if (active === null) {
    state.playback.error = state.compareAuditionSources[state.compareState].message;
    renderAuditionTransports(ui);
    return;
  }
  const preserveTime = options.preserveTime ?? (
    state.playback.context === "compare" && state.playback.sourceId === active.id
      ? ui.auditionAudio.currentTime
      : 0
  );
  await activateAuditionSource(ui, active, "compare", {
    autoplay: options.autoplay,
    gainDb: compareAuditionGainDb(),
    preserveTime,
  });
}

async function refreshCompareAuditionSources(ui: AppUi): Promise<void> {
  const aCandidate = compareAuditionCandidatePath("a", ui);
  const bCandidate = compareAuditionCandidatePath("b", ui);
  const token = state.compareAuditionSources.refreshToken + 1;
  state.compareAuditionSources.refreshToken = token;
  state.compareAuditionSources.A = aCandidate
    ? {
      candidatePath: aCandidate,
      message: "Resolving compare A audition file...",
      source: null,
      status: "loading",
    }
    : auditionMissingState("", "Set compare A to resolve an audition file.");
  state.compareAuditionSources.B = bCandidate
    ? {
      candidatePath: bCandidate,
      message: "Resolving compare B audition file...",
      source: null,
      status: "loading",
    }
    : auditionMissingState("", "Set compare B to resolve an audition file.");
  renderCompareTransport(ui);

  const [resolvedA, resolvedB] = await Promise.all([
    resolveCompareAuditionSource("A", aCandidate),
    resolveCompareAuditionSource("B", bCandidate),
  ]);
  if (state.compareAuditionSources.refreshToken !== token) {
    return;
  }
  state.compareAuditionSources.A = resolvedA;
  state.compareAuditionSources.B = resolvedB;

  const active = activeCompareAuditionSource();
  if (
    state.playback.context === "compare"
    && state.playback.sourceId
    && (active === null || state.playback.sourceId !== active.id)
  ) {
    stopAuditionPlayback(ui);
  } else if (state.playback.context === "compare" && active !== null) {
    void applyAuditionGain(ui, compareAuditionGainDb()).catch(() => undefined);
  }
  renderCompareTransport(ui);
}

function scheduleCompareAuditionRefresh(ui: AppUi): void {
  void refreshCompareAuditionSources(ui).catch(() => undefined);
}

function resolveDeliverablesSummary(
  receipt: JsonObject | null,
  manifest: JsonObject | null,
  qa: JsonObject | null,
): JsonObject | null {
  const candidates = [
    asObject(receipt?.deliverables_summary),
    asObject(manifest?.deliverables_summary),
    asObject(qa?.deliverables_summary),
  ];
  for (const candidate of candidates) {
    if (candidate !== null) {
      return candidate;
    }
  }
  return null;
}

function resolveResultSummary(
  receipt: JsonObject | null,
  manifest: JsonObject | null,
): JsonObject | null {
  const candidates = [
    asObject(receipt?.result_summary),
    asObject(manifest?.result_summary),
  ];
  for (const candidate of candidates) {
    if (candidate !== null) {
      return candidate;
    }
  }
  return null;
}

function resolveDeliverableSummaryRows(
  receipt: JsonObject | null,
  manifest: JsonObject | null,
): JsonObject[] {
  const candidates = [
    asArray(receipt?.deliverable_summary_rows),
    asArray(manifest?.deliverable_summary_rows),
  ];
  for (const candidate of candidates) {
    const rows = candidate
      .map(asObject)
      .filter((row): row is JsonObject => row !== null);
    if (rows.length > 0) {
      return rows;
    }
  }
  return [];
}

function resolveOutputSummaryRow(output: JsonObject, summaryRows: JsonObject[]): JsonObject | null {
  const outputId = asString(output.output_id).trim();
  if (outputId) {
    const byId = summaryRows.find((row) => asString(row.output_id).trim() === outputId) ?? null;
    if (byId !== null) {
      return byId;
    }
  }
  const filePath = asString(output.file_path).trim();
  if (filePath) {
    return summaryRows.find((row) => asString(row.file_path).trim() === filePath) ?? null;
  }
  return null;
}

function summarizeReceipt(receipt: JsonObject | null, manifest: JsonObject | null, qa: JsonObject | null): string {
  if (receipt === null) {
    return "No receipt loaded";
  }
  const renderOutcome = resolveRenderOutcomeSummary(receipt, manifest, qa);
  if (renderOutcome !== null) {
    return [
      renderOutcome.label,
      renderOutcome.message ?? "",
      renderOutcome.remedy ? `next=${renderOutcome.remedy}` : "",
    ].filter(Boolean).join(" · ");
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

function meanQaComparisonMetric(qa: JsonObject | null, metricKey: string): number | null {
  if (qa === null) {
    return null;
  }
  const values: number[] = [];
  for (const job of asArray(qa.jobs)) {
    const jobObject = asObject(job);
    if (jobObject === null) {
      continue;
    }
    for (const comparison of asArray(jobObject.comparisons)) {
      const comparisonObject = asObject(comparison);
      const metricsDelta = asObject(comparisonObject?.metrics_delta);
      const value = asNumber(metricsDelta?.[metricKey]);
      if (value !== null) {
        values.push(value);
      }
    }
  }
  return average(values);
}

function meanQaInputOutputDelta(qa: JsonObject | null, metricKey: string): number | null {
  if (qa === null) {
    return null;
  }
  const values: number[] = [];
  for (const job of asArray(qa.jobs)) {
    const jobObject = asObject(job);
    const input = asObject(jobObject?.input);
    const inputMetrics = asObject(input?.metrics);
    const inputValue = asNumber(inputMetrics?.[metricKey]);
    if (inputValue === null) {
      continue;
    }
    for (const output of asArray(jobObject?.outputs)) {
      const outputObject = asObject(output);
      const outputMetrics = asObject(outputObject?.metrics);
      const outputValue = asNumber(outputMetrics?.[metricKey]);
      if (outputValue !== null) {
        values.push(outputValue - inputValue);
      }
    }
  }
  return average(values);
}

type RecommendationStatus = "applied" | "approved" | "blocked" | "eligible";

type RecommendationInsight = {
  actionId: string;
  confidence: number | null;
  recommendationId: string;
  scopeLabel: string;
  status: RecommendationStatus;
  why: string;
};

function recommendationConfidence(recommendation: JsonObject): number | null {
  const deltaValues = asArray(recommendation.deltas)
    .map(asObject)
    .filter((row): row is JsonObject => row !== null)
    .map((row) => asNumber(row.confidence))
    .filter((value): value is number => value !== null);
  return average(deltaValues);
}

function recommendationReason(recommendation: JsonObject): string {
  const firstDelta = asArray(recommendation.deltas)
    .map(asObject)
    .find((row): row is JsonObject => row !== null);
  if (firstDelta !== undefined) {
    const from = firstDelta.from === undefined ? "?" : String(firstDelta.from);
    const to = firstDelta.to === undefined ? "?" : String(firstDelta.to);
    const unit = asString(firstDelta.unit);
    return `${asString(firstDelta.param_id) || "delta"}: ${from} -> ${to}${unit ? ` ${unit}` : ""}`;
  }
  const notes = asString(recommendation.notes);
  if (notes) {
    return notes;
  }
  const gateSummary = asString(recommendation.gate_summary);
  if (gateSummary) {
    return `Gate: ${gateSummary}`;
  }
  return `${asString(recommendation.action_id) || "No action"} on ${formatScopedLabel(asObject(recommendation.scope))}`;
}

function recommendationInsights(receipt: JsonObject | null): RecommendationInsight[] {
  if (receipt === null) {
    return [];
  }
  const sources: Array<{ key: string; status: RecommendationStatus }> = [
    { key: "applied_recommendations", status: "applied" },
    { key: "approved_by_user", status: "approved" },
    { key: "blocked_recommendations", status: "blocked" },
    { key: "eligible_recommendations", status: "eligible" },
  ];
  const insights: RecommendationInsight[] = [];
  for (const source of sources) {
    for (const item of asArray(receipt[source.key])) {
      const recommendation = asObject(item);
      if (recommendation === null) {
        continue;
      }
      insights.push({
        actionId: asString(recommendation.action_id),
        confidence: recommendationConfidence(recommendation),
        recommendationId: asString(recommendation.recommendation_id) || `${source.status}.unknown`,
        scopeLabel: formatScopedLabel(asObject(recommendation.scope)),
        status: source.status,
        why: recommendationReason(recommendation),
      });
    }
  }
  const statusOrder: Record<RecommendationStatus, number> = {
    applied: 0,
    approved: 1,
    blocked: 2,
    eligible: 3,
  };
  insights.sort((left, right) => {
    const byStatus = statusOrder[left.status] - statusOrder[right.status];
    if (byStatus !== 0) {
      return byStatus;
    }
    const leftConfidence = left.confidence ?? -1;
    const rightConfidence = right.confidence ?? -1;
    if (leftConfidence !== rightConfidence) {
      return rightConfidence - leftConfidence;
    }
    return left.recommendationId.localeCompare(right.recommendationId);
  });
  return insights;
}

function receiptChangeSummaryChips(
  receipt: JsonObject | null,
  manifest: JsonObject | null,
  qa: JsonObject | null,
): ChangeSummaryChip[] {
  if (receipt === null) {
    return [];
  }
  const summary = asObject(receipt.recommendations_summary);
  const status = asString(receipt.status);
  const qaCount = asArray(qa?.issues).length || asArray(receipt.qa_issues).length;
  const outputCount = flattenManifestOutputs(manifest).length;
  const renderOutcome = resolveRenderOutcomeSummary(receipt, manifest, qa);
  const chips: ChangeSummaryChip[] = [];

  if (renderOutcome !== null) {
    const deliverablesSummary = renderOutcome.deliverablesSummary;
    chips.push({
      label: renderOutcome.label,
      tone: renderOutcome.tone,
    });
    if (renderOutcome.topFailureReasonLabel) {
      chips.push({
        label: `Reason ${renderOutcome.topFailureReasonLabel}`,
        tone: renderOutcome.tone,
      });
    }
    chips.push({
      label: `Valid masters ${asNumber(deliverablesSummary.valid_master_count) ?? 0}`,
      tone:
        (asNumber(deliverablesSummary.valid_master_count) ?? 0) > 0
          ? "ok"
          : (renderOutcome.bucket === "diagnostics_only" || renderOutcome.bucket === "full_failure"
            ? "danger"
            : "warn"),
    });
  } else {
    chips.push({
      label: status || "receipt loaded",
      tone: status === "blocked" ? "danger" : (status === "completed" ? "ok" : "info"),
    });
  }
  chips.push({
    label: `Applied ${asNumber(summary?.applied) ?? asArray(receipt.applied_recommendations).length}`,
    tone: (asNumber(summary?.applied) ?? asArray(receipt.applied_recommendations).length) > 0 ? "ok" : "info",
  });
  if (renderOutcome !== null) {
    const deliverablesSummary = renderOutcome.deliverablesSummary;
    chips.push({
      label: `Failed ${asNumber(deliverablesSummary.failed_count) ?? 0}`,
      tone: (asNumber(deliverablesSummary.failed_count) ?? 0) > 0 ? "danger" : "info",
    });
    chips.push({
      label: `Invalid ${asNumber(deliverablesSummary.invalid_master_count) ?? 0}`,
      tone: (asNumber(deliverablesSummary.invalid_master_count) ?? 0) > 0 ? "danger" : "info",
    });
  } else {
    chips.push({
      label: `Blocked ${asNumber(summary?.blocked) ?? asArray(receipt.blocked_recommendations).length}`,
      tone: (asNumber(summary?.blocked) ?? asArray(receipt.blocked_recommendations).length) > 0 ? "warn" : "info",
    });
  }
  chips.push({
    label: outputCount > 0 ? `Outputs ${outputCount}` : "No outputs",
    tone: outputCount > 0 ? "info" : "warn",
  });
  chips.push({
    label: qaCount > 0 ? `QA issues ${qaCount}` : "QA clear",
    tone: qaCount > 0 ? "warn" : "ok",
  });

  return chips;
}

function compareChangeSummaryChips(compare: JsonObject | null): ChangeSummaryChip[] {
  if (compare === null) {
    return [];
  }

  const chips: ChangeSummaryChip[] = [];
  const diffs = asObject(compare.diffs);
  const profileDiff = asObject(diffs?.profile_id);
  const presetDiff = asObject(diffs?.preset_id);
  const metrics = asObject(diffs?.metrics);
  const downmixQa = asObject(metrics?.downmix_qa);
  const corrDelta = asObject(downmixQa?.corr_delta);
  const changeFlags = asObject(metrics?.change_flags);
  const translationRisk = asObject(changeFlags?.translation_risk);
  const loudnessMatch = compareLoudnessMatch(compare);

  if (profileDiff !== null) {
    chips.push({
      label: `Profile ${asString(profileDiff.a) || "-"} -> ${asString(profileDiff.b) || "-"}`,
      tone: "info",
    });
  }
  if (presetDiff !== null) {
    chips.push({
      label: `Preset ${asString(presetDiff.a) || "-"} -> ${asString(presetDiff.b) || "-"}`,
      tone: "info",
    });
  }
  if (translationRisk !== null) {
    const shift = asNumber(translationRisk.shift) ?? 0;
    chips.push({
      label: `Risk ${asString(translationRisk.a) || "-"} -> ${asString(translationRisk.b) || "-"}`,
      tone: shift > 0 ? "warn" : "ok",
    });
  }
  if (corrDelta !== null) {
    const delta = asNumber(corrDelta.delta);
    chips.push({
      label: delta === null ? "Stereo coherence n/a" : `Stereo coherence ${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`,
      tone: delta !== null && Math.abs(delta) >= 0.2 ? "warn" : "info",
    });
  }
  if (loudnessMatch !== null && loudnessMatch.matched) {
    chips.push({
      label: `Fair listen ${signedDb(loudnessMatch.compensationDb)}`,
      tone: "info",
    });
  }
  if (chips.length === 0) {
    chips.push({
      label: `${asArray(compare.warnings).length} warning(s)`,
      tone: asArray(compare.warnings).length > 0 ? "warn" : "info",
    });
  }
  return chips.slice(0, 5);
}

function renderChangeSummary(container: HTMLElement, chips: ChangeSummaryChip[], emptyLabel: string): void {
  container.innerHTML = "";
  const rows = chips.length > 0 ? chips : [{ label: emptyLabel, tone: "info" as const }];
  for (const chip of rows) {
    const node = document.createElement("div");
    node.className = "change-summary-chip";
    node.dataset.tone = chip.tone;
    node.textContent = chip.label;
    container.append(node);
  }
}

function recommendationParamValue(receipt: JsonObject | null, pattern: RegExp): number | null {
  if (receipt === null) {
    return null;
  }
  for (const recommendation of asArray(receipt.applied_recommendations)) {
    const recommendationObject = asObject(recommendation);
    if (recommendationObject === null) {
      continue;
    }
    for (const delta of asArray(recommendationObject.deltas)) {
      const deltaObject = asObject(delta);
      if (deltaObject === null) {
        continue;
      }
      if (!pattern.test(asString(deltaObject.param_id).toUpperCase())) {
        continue;
      }
      const value = asNumber(deltaObject.to) ?? asNumber(deltaObject.from);
      if (value !== null) {
        return value;
      }
    }
  }
  return null;
}

type GainReductionState = {
  note: string;
  ratio: number;
  thresholdDb: number | null;
  transferRatio: number | null;
  value: number | null;
};

function deriveGainReduction(receipt: JsonObject | null, qa: JsonObject | null): GainReductionState {
  const rmsDelta = meanQaComparisonMetric(qa, "rms_dbfs") ?? meanQaInputOutputDelta(qa, "rms_dbfs");
  if (rmsDelta !== null && rmsDelta < 0) {
    return {
      note: `Measured from render_qa RMS delta (${rmsDelta.toFixed(1)} dB).`,
      ratio: clamp(Math.abs(rmsDelta) / 12, 0, 1),
      thresholdDb: recommendationParamValue(receipt, /THRESH/),
      transferRatio: recommendationParamValue(receipt, /RATIO/),
      value: Math.abs(rmsDelta),
    };
  }

  const peakDelta = meanQaComparisonMetric(qa, "peak_dbfs") ?? meanQaInputOutputDelta(qa, "peak_dbfs");
  if (peakDelta !== null && peakDelta < 0) {
    return {
      note: `Measured from render_qa peak delta (${peakDelta.toFixed(1)} dB).`,
      ratio: clamp(Math.abs(peakDelta) / 12, 0, 1),
      thresholdDb: recommendationParamValue(receipt, /THRESH/),
      transferRatio: recommendationParamValue(receipt, /RATIO/),
      value: Math.abs(peakDelta),
    };
  }

  const reductionValues = asArray(receipt?.applied_recommendations)
    .map(asObject)
    .filter((row): row is JsonObject => row !== null)
    .flatMap((row) => asArray(row.deltas).map(asObject))
    .filter((row): row is JsonObject => row !== null)
    .flatMap((row) => {
      const paramId = asString(row.param_id).toUpperCase();
      const unit = asString(row.unit).toLowerCase();
      const deltaValue = numericDeltaValue(row);
      if (deltaValue === null || deltaValue >= 0) {
        return [];
      }
      if (!unit.includes("db") || !/(GAIN|TRIM|OUTPUT|CEILING|MAKEUP)/.test(paramId)) {
        return [];
      }
      return [Math.abs(deltaValue)];
    });
  const maxReduction = reductionValues.length > 0 ? Math.max(...reductionValues) : null;
  if (maxReduction !== null) {
    return {
      note: "Measured from applied receipt delta(s).",
      ratio: clamp(maxReduction / 12, 0, 1),
      thresholdDb: recommendationParamValue(receipt, /THRESH/),
      transferRatio: recommendationParamValue(receipt, /RATIO/),
      value: maxReduction,
    };
  }

  return {
    note: "No receipt or render-QA level delta recorded.",
    ratio: 0,
    thresholdDb: null,
    transferRatio: null,
    value: null,
  };
}

function buildTransferCurvePath(gainReduction: GainReductionState): string {
  const threshold = gainReduction.value === null
    ? 0
    : clamp(gainReduction.thresholdDb ?? (-18 + Math.min(gainReduction.value, 10)), -30, -4);
  const ratio = gainReduction.value === null
    ? 1
    : clamp(gainReduction.transferRatio ?? (1 + (gainReduction.value / 2.5)), 1.2, 8);
  const points: string[] = [];
  for (let index = 0; index <= 18; index += 1) {
    const inputDb = -48 + ((48 / 18) * index);
    const outputDb = ratio <= 1 || inputDb <= threshold
      ? inputDb
      : threshold + ((inputDb - threshold) / ratio);
    const x = 6 + (((inputDb + 48) / 48) * 108);
    const y = 74 - (((outputDb + 48) / 48) * 68);
    points.push(`${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`);
  }
  return points.join(" ");
}

function phaseCorrelationState(qa: JsonObject | null): {
  note: string;
  ratio: number;
  tone: "danger" | "info" | "ok" | "warn";
  value: number | null;
} {
  const value = meanQaMetric(qa, "correlation_lr");
  if (value === null) {
    return {
      note: "Load render_qa.json to inspect stereo coherence thresholds.",
      ratio: 0.5,
      tone: "info",
      value: null,
    };
  }
  const thresholds = asObject(qa?.thresholds);
  const warnThreshold = asNumber(thresholds?.correlation_warn_lte);
  const errorThreshold = asNumber(thresholds?.polarity_error_correlation_lte);
  const tone = errorThreshold !== null && value <= errorThreshold
    ? "danger"
    : (warnThreshold !== null && value <= warnThreshold ? "warn" : "ok");
  return {
    note: [
      "Stereo coherence from render_qa mean correlation.",
      warnThreshold === null ? null : `warn<=${warnThreshold.toFixed(2)}`,
      errorThreshold === null ? null : `polarity<=${errorThreshold.toFixed(2)}`,
    ].filter(Boolean).join(" · "),
    ratio: clamp((value + 1) / 2, 0, 1),
    tone,
    value,
  };
}

function buildVectorscopePath(correlation: number | null, sideMidRatio: number | null, crestFactor: number | null): string {
  const correlationRatio = correlation === null ? 0.5 : clamp((correlation + 1) / 2, 0, 1);
  const sideRatio = sideMidRatio === null ? 0.4 : clamp((sideMidRatio + 18) / 24, 0, 1);
  const crestRatio = crestFactor === null ? 0.5 : clamp(crestFactor / 18, 0, 1);

  const horizontal = 12 + ((1 - correlationRatio) * 22) + (sideRatio * 8);
  const vertical = 14 + (correlationRatio * 22) + (crestRatio * 4) - (sideRatio * 3);
  const waist = 0.32 + (sideRatio * 0.24);

  const topY = 50 - vertical;
  const rightInsetX = 50 + (horizontal * 0.58);
  const rightMidX = 50 + horizontal;
  const rightY = 50 - (vertical * waist);
  const bottomY = 50 + vertical;
  const leftInsetX = 50 - (horizontal * 0.58);
  const leftMidX = 50 - horizontal;

  return [
    `M 50 ${topY.toFixed(2)}`,
    `L ${rightInsetX.toFixed(2)} ${rightY.toFixed(2)}`,
    `L ${rightMidX.toFixed(2)} 50`,
    `L ${rightInsetX.toFixed(2)} ${(100 - rightY).toFixed(2)}`,
    `L 50 ${bottomY.toFixed(2)}`,
    `L ${leftInsetX.toFixed(2)} ${(100 - rightY).toFixed(2)}`,
    `L ${leftMidX.toFixed(2)} 50`,
    `L ${leftInsetX.toFixed(2)} ${rightY.toFixed(2)}`,
    "Z",
  ].join(" ");
}

function renderRecommendationConfidence(ui: AppUi): void {
  ui.results.confidenceList.innerHTML = "";
  const insights = recommendationInsights(state.artifacts.receipt).slice(0, Math.max(2, state.resultsDetailLevel));

  if (insights.length === 0) {
    const empty = document.createElement("p");
    empty.className = "control-caption";
    empty.textContent = "No recommendation confidence data loaded.";
    ui.results.confidenceList.append(empty);
  } else {
    for (const insight of insights) {
      const confidence = describeConfidence(insight.confidence);
      const row = document.createElement("article");
      row.className = "confidence-row";
      row.dataset.confidenceTone = confidence.tone;

      const head = document.createElement("div");
      head.className = "confidence-row-head";

      const title = document.createElement("p");
      title.textContent = `${insight.recommendationId} · ${insight.actionId || "-"}`;

      const status = document.createElement("span");
      status.className = "confidence-row-status";
      status.dataset.status = insight.status;
      status.textContent = insight.status;

      head.append(title, status);

      const meta = document.createElement("p");
      meta.className = "confidence-row-meta";
      meta.textContent = `${confidence.percentLabel} ${confidence.label} · scope=${insight.scopeLabel}`;

      const bar = document.createElement("div");
      bar.className = "confidence-bar";
      bar.style.setProperty("--confidence-ratio", insight.confidence === null ? "0" : clamp(insight.confidence, 0, 1).toFixed(4));

      const why = document.createElement("p");
      why.className = "control-caption";
      why.textContent = insight.why;

      row.append(head, meta, bar, why);
      ui.results.confidenceList.append(row);
    }
  }

  const summary = asObject(state.artifacts.receipt?.recommendations_summary);
  ui.results.confidenceNote.textContent = summary === null
    ? "Confidence rows use receipt deltas when they are available."
    : [
      `eligible=${asNumber(summary.eligible) ?? 0}`,
      `applied=${asNumber(summary.applied) ?? 0}`,
      `blocked=${asNumber(summary.blocked) ?? 0}`,
    ].join(" · ");
}

function renderResultsInspection(ui: AppUi): void {
  const gainReduction = deriveGainReduction(state.artifacts.receipt, state.artifacts.qa);
  ui.results.gainReductionValue.textContent = gainReduction.value === null
    ? "n/a"
    : `${gainReduction.value.toFixed(1)} dB`;
  ui.results.gainReductionMeter.style.setProperty("--bar-ratio", gainReduction.ratio.toFixed(4));
  ui.results.transferCurvePath.setAttribute("d", buildTransferCurvePath(gainReduction));
  ui.results.transferNote.textContent = gainReduction.value === null
    ? "Transfer curve proxy will appear when dynamics data is available."
    : [
      gainReduction.note,
      gainReduction.thresholdDb === null ? null : `threshold=${gainReduction.thresholdDb.toFixed(1)} dB`,
      gainReduction.transferRatio === null ? null : `ratio=${gainReduction.transferRatio.toFixed(1)}:1`,
    ].filter(Boolean).join(" · ");

  const phaseState = phaseCorrelationState(state.artifacts.qa);
  ui.results.phaseCorrelationValue.textContent = phaseState.value === null
    ? "n/a corr"
    : `${phaseState.value.toFixed(2)} corr`;
  ui.results.phaseCorrelationMeter.style.setProperty("--phase-ratio", phaseState.ratio.toFixed(4));
  ui.results.phaseCorrelationMeter.dataset.phaseTone = phaseState.tone;
  ui.results.phaseNote.textContent = phaseState.note;

  const correlation = meanQaMetric(state.artifacts.qa, "correlation_lr");
  const sideMidRatio = meanQaMetric(state.artifacts.qa, "side_mid_ratio_db");
  const crestFactor = meanQaMetric(state.artifacts.qa, "crest_factor_db");
  ui.results.vectorscopePath.setAttribute("d", buildVectorscopePath(correlation, sideMidRatio, crestFactor));

  const spreadLabel = correlation === null
    ? "Spread unavailable"
    : (correlation >= 0.7
      ? "Tight / mono-safe"
      : (correlation >= 0.2 ? "Balanced stereo" : (correlation >= -0.2 ? "Wide stereo" : "Anti-phase risk")));
  ui.results.vectorscopeSummary.textContent = [
    spreadLabel,
    `side/mid=${formatNumber(sideMidRatio, 1, " dB")}`,
    `crest=${formatNumber(crestFactor, 1, " dB")}`,
  ].join(" · ");
}

type CompareCompensationState = {
  db: number;
  evaluationOnly: boolean;
  methodId: string;
  note: string;
  source: "compare_report" | "none" | "render_qa";
};

type CompareLoudnessMatch = {
  compensationDb: number;
  details: string;
  evaluationOnly: boolean;
  matched: boolean;
  measurementA: number | null;
  measurementB: number | null;
  methodId: string;
  unitLabel: string;
};

function compareLoudnessMatch(compare: JsonObject | null): CompareLoudnessMatch | null {
  if (compare === null) {
    return null;
  }
  const loudnessMatch = asObject(compare.loudness_match);
  if (loudnessMatch === null) {
    return null;
  }

  const unitId = asString(loudnessMatch.measurement_unit_id);
  return {
    compensationDb: asNumber(loudnessMatch.compensation_db) ?? 0,
    details: asString(loudnessMatch.details),
    evaluationOnly: loudnessMatch.evaluation_only !== false,
    matched: asString(loudnessMatch.status) === "matched",
    measurementA: asNumber(loudnessMatch.measurement_a),
    measurementB: asNumber(loudnessMatch.measurement_b),
    methodId: asString(loudnessMatch.method_id),
    unitLabel: unitId === "UNIT.LUFS" ? "LUFS" : (unitId === "UNIT.DBFS" ? "dBFS" : ""),
  };
}

function compareMeasurementForSide(
  sideKey: "a" | "b",
  loudnessMatch: CompareLoudnessMatch | null,
): { unitLabel: string; value: number | null } {
  const qa = sideKey === "a" ? state.artifacts.compareAQa : state.artifacts.compareBQa;
  const integrated = meanQaMetric(qa, "integrated_lufs");
  if (integrated !== null) {
    return { value: integrated, unitLabel: "LUFS" };
  }

  const rms = meanQaMetric(qa, "rms_dbfs");
  if (rms !== null) {
    return { value: rms, unitLabel: "dBFS" };
  }

  if (loudnessMatch !== null && loudnessMatch.matched) {
    return {
      value: sideKey === "a" ? loudnessMatch.measurementA : loudnessMatch.measurementB,
      unitLabel: loudnessMatch.unitLabel,
    };
  }

  return { value: null, unitLabel: "" };
}

function deriveCompareCompensation(): CompareCompensationState {
  const fromCompare = compareLoudnessMatch(state.artifacts.compare);
  if (fromCompare !== null && fromCompare.matched) {
    return {
      db: fromCompare.compensationDb,
      evaluationOnly: fromCompare.evaluationOnly,
      methodId: fromCompare.methodId,
      note: fromCompare.details,
      source: fromCompare.matched ? "compare_report" : "none",
    };
  }

  const aIntegrated = meanQaMetric(state.artifacts.compareAQa, "integrated_lufs");
  const bIntegrated = meanQaMetric(state.artifacts.compareBQa, "integrated_lufs");
  if (aIntegrated !== null && bIntegrated !== null) {
    return {
      db: roundToStep(aIntegrated - bIntegrated, 0.1),
      evaluationOnly: true,
      methodId: "COMPARE.LOUDNESS_MATCH.RENDER_QA.MEAN_INTEGRATED_LUFS",
      note: `Default loudness match from A/B render_qa mean integrated LUFS (${aIntegrated.toFixed(1)} vs ${bIntegrated.toFixed(1)}).`,
      source: "render_qa",
    };
  }

  const aRms = meanQaMetric(state.artifacts.compareAQa, "rms_dbfs");
  const bRms = meanQaMetric(state.artifacts.compareBQa, "rms_dbfs");
  if (aRms !== null && bRms !== null) {
    return {
      db: roundToStep(aRms - bRms, 0.1),
      evaluationOnly: true,
      methodId: "COMPARE.LOUDNESS_MATCH.RENDER_QA.MEAN_RMS_DBFS",
      note: `Default loudness match from A/B render_qa mean RMS dBFS (${aRms.toFixed(1)} vs ${bRms.toFixed(1)}).`,
      source: "render_qa",
    };
  }

  return {
    db: 0,
    evaluationOnly: true,
    methodId: "COMPARE.LOUDNESS_MATCH.UNAVAILABLE",
    note: fromCompare?.details || "No compare-report or paired render_qa loudness metrics were available.",
    source: "none",
  };
}

function summarizeCompareHeadline(compare: JsonObject | null): string {
  if (compare === null) {
    return "No compare artifact loaded.";
  }
  const loudness = compareLoudnessMatch(compare);
  if (loudness !== null && loudness.details) {
    return loudness.details;
  }
  const notes = asArray(compare.notes).map(asString).filter(Boolean);
  return notes[0] ?? "Compare artifact loaded.";
}

function renderCompare(ui: AppUi): void {
  const compare = state.artifacts.compare;
  const compareExists = compare !== null;
  renderChangeSummary(ui.compareChangeSummary, compareChangeSummaryChips(compare), "Load compare_report.json.");

  for (const button of ui.abButtons) {
    const active = button.dataset.abState === state.compareState;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }

  const compensationRatio = (state.compareCompensationDb + 12) / 24;
  ui.compareCompensation.knob.style.setProperty("--control-ratio", clamp(compensationRatio, 0, 1).toFixed(4));
  ui.compareCompensation.knob.setAttribute("aria-valuenow", state.compareCompensationDb.toFixed(1));
  ui.compareCompensation.knob.setAttribute("aria-valuetext", signedDb(state.compareCompensationDb));
  ui.compareCompensation.input.value = state.compareCompensationDb.toFixed(1);
  ui.compareCompensation.value.textContent = signedDb(state.compareCompensationDb);

  const compensationNote = state.compareCompensationSource === "compare_report" || state.compareCompensationSource === "render_qa"
    ? `Fair listen on: B is compensated by ${signedDb(state.compareCompensationDb)}${state.compareCompensationEvaluationOnly ? " (evaluation only)." : "."}`
    : (state.compareCompensationSource === "manual"
      ? `Manual B compensation is ${signedDb(state.compareCompensationDb)}${state.compareCompensationEvaluationOnly ? " (evaluation only)." : "."}`
      : "Fair listen unavailable: load paired render_qa metrics or rerun compare.");
  requiredElement<HTMLElement>("#ab-compensation").textContent = compareExists
    ? compensationNote
    : "No loudness-match data loaded.";

  renderCompareTransport(ui);

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
  const loudnessMatch = compareLoudnessMatch(compare);
  const notes = asArray(compare.notes).map(asString).filter(Boolean);
  const warnings = asArray(compare.warnings).map(asString).filter(Boolean);
  const measurement = compareMeasurementForSide(sideKey, loudnessMatch);
  const loudnessRaw = measurement.value;
  const loudnessUnit = measurement.unitLabel;
  const matchedLoudness = sideKey === "b" && loudnessRaw !== null
    ? loudnessRaw + state.compareCompensationDb
    : loudnessRaw;

  ui.compareReadoutPrimary.textContent = [
    `${state.compareState} · ${asString(side?.label) || state.compareState}`,
    loudnessRaw === null || !loudnessUnit ? "no loudness metric" : `${matchedLoudness?.toFixed(1)} ${loudnessUnit}`,
  ].join(" · ");
  ui.compareReadoutSecondary.textContent = [
    `profile=${asString(side?.profile_id) || "-"}`,
    `preset=${asString(side?.preset_id) || "-"}`,
    loudnessRaw === null || !loudnessUnit ? "raw=n/a" : `raw=${loudnessRaw.toFixed(1)} ${loudnessUnit}`,
  ].join(" · ");

  ui.compareSummary.textContent = notes[0] ?? "No tracked differences were detected.";
  const summaryLines = [
    `compensation_source=${state.compareCompensationSource} | method=${state.compareCompensationMethodId || "-"} | compensation=${signedDb(state.compareCompensationDb)} | evaluation_only=${state.compareCompensationEvaluationOnly ? "true" : "false"}`,
    state.compareCompensationNote,
    ...warnings.slice(0, state.resultsDetailLevel),
    ...notes.slice(1, 1 + Math.max(1, state.resultsDetailLevel - warnings.length)),
  ].filter(Boolean);
  ui.compareSummaryNote.textContent = summaryLines.join("\n");
  ui.compareJsonPreview.textContent = serializeJson(compare, state.nerdView ? 70 : 18);
}

function resultsCompareCandidate(
  selected: ArtifactEntry | null,
  paths: WorkflowPaths | null,
): string {
  if (selected === null || selected.id === "compare") {
    return "";
  }
  if (selected.id === "receipt" || selected.id === "manifest" || selected.id === "qa" || selected.id.startsWith("audio:")) {
    return paths?.workspaceDir || workspaceDirFromArtifactPath(selected.resolvedPath || selected.path);
  }
  return "";
}

function renderResultsActionRows(
  ui: AppUi,
  selected: ArtifactEntry | null,
  paths: WorkflowPaths | null,
): void {
  const previewButtons: QuickActionButtonSpec[] = [];
  const selectedPath = selected?.resolvedPath || selected?.path || "";
  if (selected !== null && selectedPath) {
    previewButtons.push(
      {
        label: "Copy path",
        onClick: () => {
          void copyArtifactPath(ui, selectedPath, selected.title);
        },
      },
      {
        label: "Reveal",
        onClick: () => {
          void revealArtifactPath(ui, selectedPath, selected.title);
        },
      },
    );
  }
  if (selected !== null) {
    const skip = selected.id === "receipt" || selected.id === "manifest" || selected.id === "qa"
      ? [selected.id]
      : [];
    previewButtons.push(...buildResultsOpenButtons(ui, { skip }));
  }
  const compareCandidate = resultsCompareCandidate(selected, paths);
  if (compareCandidate) {
    previewButtons.push({
      label: "Compare",
      onClick: () => {
        queueCompareFromArtifact(ui, compareCandidate);
      },
    });
  }
  renderQuickActionButtons(ui.artifactPreviewActions, previewButtons);

  renderQuickActionButtons(
    ui.results.summaryActions,
    buildResultsOpenButtons(ui, {
      labels: {
        manifest: "Open manifest",
        qa: "Open QA",
        receipt: "Open receipt",
      },
    }),
  );
  renderQuickActionButtons(ui.results.qaActions, [{
    disabled: ui.inputs.workspaceDir.value.trim().length === 0
      && state.artifacts.qa === null
      && !state.artifactSources.qaPath,
    label: "Open QA",
    onClick: () => {
      openResultsArtifact(ui, "qa", "Opened render QA.");
    },
  }]);
}

function renderResults(ui: AppUi): void {
  const paths = ui.inputs.workspaceDir.value.trim()
    ? buildWorkflowPaths(ui.inputs.workspaceDir.value.trim())
    : null;
  const entries = buildArtifactEntries(paths);
  const query = state.resultsArtifactSearch.trim().toLowerCase();
  ui.artifactSearch.value = state.resultsArtifactSearch;
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
    button.id = `artifact-option-${entry.id.replace(/[^a-z0-9_-]/giu, "-")}`;
    button.dataset.artifactEntryId = entry.id;
    button.setAttribute("role", "option");
    button.setAttribute("aria-label", `${entry.title}. ${entry.tag}. ${entry.summary}`);
    button.setAttribute("aria-selected", entry.id === state.selectedArtifactId ? "true" : "false");
    button.tabIndex = entry.id === state.selectedArtifactId ? 0 : -1;
    button.title = `${entry.title}\n${entry.summary}`;
    button.textContent = entry.title;
    if (entry.id === state.selectedArtifactId) {
      button.classList.add("is-active");
    }
    const meta = document.createElement("small");
    meta.textContent = `${entry.tag} · ${entry.summary}`;
    button.append(meta);
    button.addEventListener("click", () => {
      selectResultsArtifact(ui, entry.id);
    });
    ui.results.browserList.append(button);
  }

  const selectedOptionId = filtered.find((entry) => entry.id === state.selectedArtifactId)?.id ?? "";
  if (selectedOptionId) {
    const selectedButton = resultsArtifactButtons(ui).find((button) => {
      return button.dataset.artifactEntryId === selectedOptionId;
    }) ?? null;
    if (selectedButton !== null) {
      ui.results.browserList.setAttribute("aria-activedescendant", selectedButton.id);
    } else {
      ui.results.browserList.removeAttribute("aria-activedescendant");
    }
  } else {
    ui.results.browserList.removeAttribute("aria-activedescendant");
  }

  const selected = filtered.find((entry) => entry.id === state.selectedArtifactId) ?? null;
  ui.artifactPreviewName.textContent = selected?.title ?? "No artifact selected";
  ui.artifactPreviewSummary.textContent = selected?.summary ?? "Load or generate render artifacts to inspect them here.";
  ui.artifactPreviewDelta.textContent = selected?.path ? `path=${selected.path}` : "";

  ui.results.detailSlider.style.setProperty("--slider-ratio", ((state.resultsDetailLevel - 1) / 9).toFixed(4));
  ui.results.detailSlider.setAttribute("aria-valuenow", state.resultsDetailLevel.toString());
  ui.results.detailSlider.setAttribute("aria-valuetext", `${state.resultsDetailLevel} line(s) of detail`);
  ui.results.detailInput.value = state.resultsDetailLevel.toString();
  ui.results.detailValue.textContent = `${state.resultsDetailLevel} line(s) of detail`;
  renderChangeSummary(
    ui.results.changeSummary,
    receiptChangeSummaryChips(state.artifacts.receipt, state.artifacts.manifest, state.artifacts.qa),
    "Load a receipt or manifest.",
  );
  renderRecommendationConfidence(ui);
  renderResultsInspection(ui);

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
  renderResultsActionRows(ui, selected, paths);
  renderResultsTransport(ui, selected);
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
  renderSceneLockEditor(ui);
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
  updateWorkspaceMode(ui);
  renderRecentPaths(ui);
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
  let result: MmoRunResult;
  try {
    result = await executeMmo(args, {
      onLogLine: (line) => {
        appendTimeline(ui, stage, line.kind, line.text, line.payload);
        if (stage === "render" && line.payload !== null) {
          updateRenderProgress(ui, line.payload);
        }
      },
    });
  } catch (error) {
    throw sidecarLaunchFailure(stage, error);
  }
  appendMeta(ui, stage, formatExitSummary(result));
  return result;
}

async function runSpawnCommand(
  ui: AppUi,
  stage: CommandStage,
  args: string[],
): Promise<MmoRunResult> {
  appendMeta(ui, stage, `$ mmo ${args.map(quoteArg).join(" ")}`);
  let result: MmoRunResult;
  try {
    result = await spawnMmo(args, {
      onLogLine: (line) => {
        appendTimeline(ui, stage, line.kind, line.text, line.payload);
        if (stage === "render" && line.payload !== null) {
          updateRenderProgress(ui, line.payload);
        }
      },
    });
  } catch (error) {
    throw sidecarLaunchFailure(stage, error);
  }
  appendMeta(ui, stage, formatExitSummary(result));
  return result;
}

function assertSuccess(result: MmoRunResult, stageLabel: string): void {
  if (result.code === 0) {
    return;
  }
  const reason = firstMeaningfulFailureLine(result);
  throw new Error(
    [
      stageFailureWhat(stageLabel),
      `Why: MMO stopped this step with ${formatExitSummary(result)}${reason ? `; first clue: ${reason}` : "."}`,
      `Next: ${stageFailureNextStep(stageLabel)}`,
    ].join("\n"),
  );
}

function sidecarLaunchFailure(stage: CommandStage, error: unknown): Error {
  const detail = error instanceof Error ? error.message : String(error);
  const nextStep = stage === "doctor"
    ? "Reinstall the packaged app or try a fresh release asset, then run Doctor again."
    : "Run Doctor first. If Doctor also fails, reinstall the packaged app or try a fresh release asset.";
  return new Error(
    "MMO could not start its packaged audio helper.\n"
    + "Why: the desktop shell opened, but the small background tool that does the real audio work did not launch.\n"
    + `Next: ${nextStep}\n`
    + `Details: ${detail}`,
  );
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

function resetSceneLocksState(message = "Inspect scene locks to fine-tune how MMO places each part in the room."): void {
  state.sceneLocks = {
    ...emptySceneLocksState(),
    statusMessage: message,
  };
}

async function inspectSceneLocks(
  ui: AppUi,
  options: {
    autoFillMode?: "always" | "if-empty";
    quiet?: boolean;
    statusMessage?: string;
  } = {},
): Promise<void> {
  const workspaceDir = ui.inputs.workspaceDir.value.trim();
  if (!workspaceDir) {
    resetSceneLocksState(
      "Choose a workspace folder first. MMO needs the project folder before it can load scene lock rows.",
    );
    renderScene(ui);
    if (!options.quiet) {
      updateRuntimeMessage(ui, state.sceneLocks.statusMessage);
    }
    return;
  }

  state.sceneLocks.isInspecting = true;
  state.sceneLocks.statusMessage = "Inspecting project scene locks...";
  state.sceneLocks.statusTone = "info";
  renderScene(ui);

  try {
    const result = await runMmoRpc<JsonObject>("scene.locks.inspect", {
      project_dir: buildWorkflowPaths(workspaceDir).projectDir,
    });
    hydrateSceneLocksInspect(result, {
      autoFillMode: options.autoFillMode ?? "if-empty",
      statusMessage: options.statusMessage ?? "Scene lock rows loaded from the project draft.",
      statusTone: "ok",
      ui,
    });
    if (!options.quiet) {
      updateRuntimeMessage(ui, state.sceneLocks.statusMessage);
    }
  } catch (error) {
    state.sceneLocks.isInspecting = false;
    state.sceneLocks.statusMessage = error instanceof Error ? error.message : String(error);
    state.sceneLocks.statusTone = "error";
    if (!options.quiet) {
      updateRuntimeMessage(ui, state.sceneLocks.statusMessage);
    }
    throw error;
  } finally {
    state.sceneLocks.isInspecting = false;
    renderScene(ui);
  }
}

function sceneLockRowsForSave(): Array<Record<string, boolean | number | string>> {
  return state.sceneLocks.objects.map((row) => ({
    front_only: row.editFrontOnly === true,
    height_cap: clampUnitValue(row.editHeightCap, 1),
    role_id: row.editRoleId,
    stem_id: row.stemId,
    surround_cap: clampUnitValue(row.editSurroundCap, 1),
  }));
}

async function refreshScenePreviewFromSavedLocks(
  ui: AppUi,
  sceneLocksPath: string,
  projectScenePath: string,
): Promise<{ lintPath: string; previewMode: "project_draft" | "workspace_scene"; scenePath: string }> {
  const workspaceDir = ui.inputs.workspaceDir.value.trim();
  if (!workspaceDir) {
    state.artifacts.scene = await readArtifactJson<JsonObject>(projectScenePath);
    state.artifactSources.scenePath = projectScenePath;
    renderScene(ui);
    return {
      lintPath: "",
      previewMode: "project_draft",
      scenePath: projectScenePath,
    };
  }

  const paths = buildWorkflowPaths(workspaceDir);
  const hasWorkspaceSceneInputs = await artifactExists(paths.stemsMapPath)
    && await artifactExists(paths.busPlanPath);
  let previewScenePath = projectScenePath;
  let previewMode: "project_draft" | "workspace_scene" = "project_draft";

  if (hasWorkspaceSceneInputs) {
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
      "--locks",
      sceneLocksPath,
    ];
    const buildResult = await runExecuteCommand(ui, "scene", buildArgs);
    assertSuccess(buildResult, "scene");
    previewScenePath = paths.scenePath;
    previewMode = "workspace_scene";
  }

  const lintArgs = [
    "scene",
    "lint",
    "--scene",
    previewScenePath,
    "--out",
    paths.sceneLintPath,
    "--scene-locks",
    sceneLocksPath,
  ];
  const lintResult = await runExecuteCommand(ui, "scene", lintArgs);
  assertSuccess(lintResult, "scene");

  if (previewMode === "workspace_scene") {
    await refreshSceneArtifacts(paths);
  } else {
    state.artifacts.scene = await readArtifactJson<JsonObject>(previewScenePath);
    state.artifacts.sceneLint = await readArtifactJson<JsonObject>(paths.sceneLintPath);
    state.artifactSources.scenePath = previewScenePath;
    state.artifactSources.sceneLintPath = paths.sceneLintPath;
  }
  renderScene(ui);

  return {
    lintPath: paths.sceneLintPath,
    previewMode,
    scenePath: previewScenePath,
  };
}

async function saveSceneLocks(ui: AppUi): Promise<void> {
  const workspaceDir = ui.inputs.workspaceDir.value.trim();
  if (!workspaceDir) {
    throw new Error(
      "Choose a workspace folder before saving scene locks.\n"
      + "Why: MMO writes scene_locks.yaml into that project folder.\n"
      + "Next: Pick the workspace you used for Validate/Analyze/Scene, then save again.",
    );
  }
  if (state.sceneLocks.objects.length === 0) {
    throw new Error(
      "Load the scene lock rows first.\n"
      + "Why: MMO can only save edits for rows it has already loaded from the project.\n"
      + "Next: Click Inspect Scene Locks, review the rows, then save your changes.",
    );
  }

  const projectDir = buildWorkflowPaths(workspaceDir).projectDir;
  setStageStatus(ui.stages.scene, "running", "Saving");
  state.sceneLocks.isSaving = true;
  state.sceneLocks.statusMessage = "Saving scene_locks.yaml and refreshing scene context...";
  state.sceneLocks.statusTone = "info";
  renderScene(ui);
  updateRuntimeMessage(ui, "Saving scene_locks.yaml through the packaged GUI RPC.");
  try {
    const saveResult = await runMmoRpc<JsonObject>("scene.locks.save", {
      perspective: state.sceneLocks.perspective,
      project_dir: projectDir,
      rows: sceneLockRowsForSave(),
    });

    const savedSceneLocksPath = asString(saveResult.scene_locks_path).trim();
    const savedScenePath = asString(saveResult.scene_path).trim();
    ui.inputs.sceneLocksPath.value = savedSceneLocksPath;

    await inspectSceneLocks(ui, {
      autoFillMode: "always",
      quiet: true,
      statusMessage: "scene_locks.yaml saved. Refreshing scene preview and lint context...",
    });

    const refreshed = await refreshScenePreviewFromSavedLocks(ui, savedSceneLocksPath, savedScenePath);
    const lintPathText = refreshed.lintPath || "(not written)";
    ui.output.scene.textContent = [
      `scene_locks=${savedSceneLocksPath}`,
      `project_scene_draft=${savedScenePath}`,
      `scene_preview=${refreshed.scenePath}`,
      `scene_lint=${lintPathText}`,
      `preview_mode=${refreshed.previewMode}`,
      `overrides=${asNumber(saveResult.overrides_count) ?? state.sceneLocks.overridesCount}`,
      `perspective=${asString(saveResult.perspective).trim() || state.sceneLocks.perspective}`,
    ].join("\n");

    state.sceneLocks.statusMessage = "scene_locks.yaml saved and scene context refreshed.";
    state.sceneLocks.statusTone = "ok";
    setStageStatus(ui.stages.scene, "pass", "Pass");
    updateRuntimeMessage(ui, "scene_locks.yaml saved and the Scene screen was refreshed.");
  } catch (error) {
    state.sceneLocks.statusMessage = error instanceof Error ? error.message : String(error);
    state.sceneLocks.statusTone = "error";
    throw error;
  } finally {
    state.sceneLocks.isSaving = false;
    renderScene(ui);
  }
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
  const workspaceDir = workspaceDirFromArtifactPath(candidatePath);
  if (workspaceDir) {
    return joinPath(workspaceDir, "render_qa.json");
  }
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
  state.compareCompensationDb = derived.db;
  state.compareCompensationEvaluationOnly = derived.evaluationOnly;
  state.compareCompensationMethodId = derived.methodId;
  state.compareCompensationNote = derived.note;
  state.compareCompensationSource = derived.source;
}

async function runDoctor(ui: AppUi): Promise<DoctorRunResult> {
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
  let envDoctorPayload: JsonObject | null = null;
  if (envDoctorResult.stdout.trim()) {
    try {
      envDoctorPayload = asObject(JSON.parse(envDoctorResult.stdout) as unknown);
    } catch {
      envDoctorPayload = null;
    }
  }

  const ok = versionResult.code === 0 && pluginsResult.code === 0 && envDoctorResult.code === 0;
  updateRuntimeMessage(ui, ok ? "Doctor passed. The packaged sidecar is ready." : "Doctor failed. Check the timeline.");
  return {
    envDoctorPayload,
    envDoctorResult,
    ok,
    pluginsResult,
    versionResult,
  };
}

async function runValidate(ui: AppUi, controller: ReturnType<typeof initDesignSystem>): Promise<void> {
  const { paths, stemsDir } = collectWorkspaceAndStems(ui);
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
  const { paths, stemsDir } = collectWorkspaceAndStems(ui);
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
  const { paths, sceneLocksPath, stemsDir } = collectSceneInputs(ui);
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
  try {
    await inspectSceneLocks(ui, {
      autoFillMode: "if-empty",
      quiet: true,
    });
  } catch {
    state.sceneLocks.statusMessage = "Scene artifacts refreshed, but scene-lock editor data is unavailable for the current project state.";
    state.sceneLocks.statusTone = "error";
  }
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
  const { layoutStandard, paths, renderTarget, sceneLocksPath } = collectRenderInputs(ui);
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
  const renderOutcome = resolveRenderOutcomeSummary(
    state.artifacts.receipt,
    state.artifacts.manifest,
    state.artifacts.qa,
  );
  const renderStageState: StageState = result.code !== 0
    ? "fail"
    : (renderOutcome?.bucket === "partial_success" ? "warn" : "pass");
  const renderStageLabel = result.code !== 0
    ? (canceled ? "Canceled" : "Fail")
    : (renderOutcome?.bucket === "partial_success" ? "Partial" : "Pass");
  setStageStatus(
    ui.stages.render,
    renderStageState,
    renderStageLabel,
  );
  state.currentCancelPath = null;
  applyBusyState(ui);
  assertSuccess(result, "render");
  if (renderOutcome?.bucket === "partial_success") {
    updateRuntimeMessage(ui, "Render finished with partial success. MMO wrote a valid master, but at least one deliverable still failed.");
  } else if (renderOutcome?.bucket === "valid_master") {
    updateRuntimeMessage(ui, "Render finished with a valid master and wrote artifacts into the workspace.");
  } else if (renderOutcome?.bucket === "success_no_master") {
    updateRuntimeMessage(ui, "Render finished and wrote artifacts into the workspace, but no master deliverable was requested.");
  } else {
    updateRuntimeMessage(ui, "Render finished and wrote artifacts into the workspace.");
  }
  controller.setScreen("results");
}

async function runCompare(ui: AppUi): Promise<void> {
  const { aPath, bPath, paths } = collectCompareInputs(ui);
  if (!aPath || !bPath) {
    throw new Error(
      "Choose both Compare inputs first.\n"
      + "Why: MMO needs two finished runs to A/B, like lining up two bounces on the same desk.\n"
      + "Next: Pick either a workspace folder or a report.json file for A and B.",
    );
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
  await refreshCompareAuditionSources(ui);
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
  commitRecentPath(ui, "compareInputs", aPath);
  commitRecentPath(ui, "compareInputs", bPath);
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

async function runWithBusyStrict<T>(
  ui: AppUi,
  stage: CommandStage,
  action: () => Promise<T>,
  clearLogs = false,
): Promise<T> {
  if (state.busyStage !== null) {
    throw new Error(`Another stage is already running: ${state.busyStage}`);
  }
  state.busyStage = stage;
  applyBusyState(ui);
  if (clearLogs) {
    clearTimeline(ui);
  }
  try {
    return await action();
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    updateRuntimeMessage(ui, detail);
    if (stage !== "doctor") {
      const targetStage = ui.stages[stage as StageKey];
      if (targetStage !== undefined) {
        setStageStatus(targetStage, "fail", "Fail");
      }
    }
    throw error;
  } finally {
    state.busyStage = null;
    applyBusyState(ui);
    renderAll(ui);
  }
}

function buildDesktopSmokeSummary(
  ui: AppUi,
  config: DesktopSmokeConfig,
  paths: WorkflowPaths,
  doctorResult: DoctorRunResult | null,
  error: string,
): DesktopSmokeSummary {
  const envDoctorPayload = doctorResult?.envDoctorPayload;
  const checks = asObject(envDoctorPayload?.checks);
  const pathPayload = asObject(envDoctorPayload?.paths);

  return {
    appLaunchVerified: true,
    artifactPaths: {
      busPlanCsvPath: paths.busPlanCsvPath,
      busPlanPath: paths.busPlanPath,
      projectValidationPath: paths.projectValidationPath,
      renderManifestPath: paths.renderManifestPath,
      renderQaPath: paths.renderQaPath,
      renderReceiptPath: paths.renderReceiptPath,
      reportPath: paths.reportPath,
      scanReportPath: paths.scanReportPath,
      sceneLintPath: paths.sceneLintPath,
      scenePath: paths.scenePath,
      stemsMapPath: paths.stemsMapPath,
      workspaceDir: paths.workspaceDir,
    },
    doctor: {
      checks,
      dataRoot: asString(pathPayload?.data_root),
      envDoctorExitCode: doctorResult?.envDoctorResult.code ?? null,
      ok: doctorResult?.ok ?? false,
      pluginsExitCode: doctorResult?.pluginsResult.code ?? null,
      versionExitCode: doctorResult?.versionResult.code ?? null,
    },
    error,
    ok: error.length === 0,
    renderTarget: config.renderTarget,
    timelineTail: collectTimelineTail(ui, 24),
    workspaceDir: config.workspaceDir,
  };
}

async function writeDesktopSmokeSummary(summaryPath: string, payload: DesktopSmokeSummary): Promise<void> {
  const wrote = await writeArtifactText(
    summaryPath,
    `${JSON.stringify(payload, null, 2)}\n`,
  );
  if (!wrote) {
    throw new Error(`Unable to write desktop smoke summary: ${summaryPath}`);
  }
}

async function runDesktopSmoke(
  ui: AppUi,
  controller: ReturnType<typeof initDesignSystem>,
  config: DesktopSmokeConfig,
): Promise<void> {
  const paths = buildWorkflowPaths(config.workspaceDir);
  let doctorResult: DoctorRunResult | null = null;
  let error = "";
  const resolvedRenderTarget = resolveSelectValue(
    ui.inputs.renderTarget,
    config.renderTarget,
    RENDER_TARGET_SELECT_ALIASES,
  );
  const resolvedLayoutStandard = resolveSelectValue(ui.inputs.layoutStandard, config.layoutStandard);

  ui.inputs.stemsDir.value = config.stemsDir;
  ui.inputs.workspaceDir.value = config.workspaceDir;
  ui.inputs.sceneLocksPath.value = config.sceneLocksPath ?? "";
  if (!resolvedRenderTarget) {
    throw new Error(
      "Desktop smoke could not choose a render target.\n"
      + `Why: The smoke config asked for \"${config.renderTarget}\", but this build only offers `
      + `${supportedSelectOptions(ui.inputs.renderTarget)}.\n`
      + "Next: Update the smoke config to use one of the menu targets, or add the missing target to the desktop Render target menu.",
    );
  }
  if (!resolvedLayoutStandard) {
    throw new Error(
      "Desktop smoke could not choose a layout standard.\n"
      + `Why: The smoke config asked for \"${config.layoutStandard}\", but this build only offers `
      + `${supportedSelectOptions(ui.inputs.layoutStandard)}.\n`
      + "Next: Update the smoke config to use one of the menu standards, or add the missing standard to the desktop Layout standard menu.",
    );
  }
  ui.inputs.renderTarget.value = resolvedRenderTarget;
  ui.inputs.layoutStandard.value = resolvedLayoutStandard;
  renderAll(ui);

  try {
    doctorResult = await runWithBusyStrict(ui, "doctor", async () => runDoctor(ui), true);
    if (!doctorResult.ok) {
      throw new Error("Desktop smoke doctor failed.");
    }
    await runWithBusyStrict(ui, "validate", async () => runValidate(ui, controller), true);
    await runWithBusyStrict(ui, "analyze", async () => runAnalyze(ui, controller), true);
    await runWithBusyStrict(ui, "scene", async () => runScene(ui, controller), true);
    await runWithBusyStrict(ui, "render", async () => runRender(ui, controller), true);
  } catch (caught) {
    error = caught instanceof Error ? caught.message : String(caught);
  }

  const summary = buildDesktopSmokeSummary(ui, config, paths, doctorResult, error);
  await writeDesktopSmokeSummary(config.summaryPath, summary);

  try {
    await getCurrentWindow().close();
  } catch {
    window.close();
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

function bindRecentInput(
  ui: AppUi,
  input: HTMLInputElement,
  group: RecentPathGroup,
  onChange?: () => void,
): void {
  input.addEventListener("change", () => {
    commitRecentPath(ui, group, input.value);
    onChange?.();
  });
}

function bindDirectoryBrowseButton(
  ui: AppUi,
  button: HTMLButtonElement,
  input: HTMLInputElement,
  group: RecentPathGroup,
  title: string,
  afterSelect?: () => void,
): void {
  button.addEventListener("click", () => {
    void (async () => {
      const selectedPath = await browseDirectory({
        defaultPath: defaultBrowsePath(input.value, state.recentPaths[group]),
        title,
      });
      if (!selectedPath) {
        if (!isTauriRuntime()) {
          updateRuntimeMessage(ui, "Native folder pickers are available in packaged desktop builds.");
        }
        return;
      }
      input.value = selectedPath;
      commitRecentPath(ui, group, selectedPath);
      afterSelect?.();
      renderAll(ui);
    })();
  });
}

function bindFilePathBrowseButton(
  ui: AppUi,
  button: HTMLButtonElement,
  input: HTMLInputElement,
  group: RecentPathGroup,
  options: {
    afterSelect?: () => void;
    extensions: string[];
    label: string;
    title: string;
  },
): void {
  button.addEventListener("click", () => {
    void (async () => {
      const selectedPath = await browseFile({
        defaultPath: defaultBrowsePath(input.value, state.recentPaths[group]),
        extensions: options.extensions,
        label: options.label,
        title: options.title,
      });
      if (!selectedPath) {
        if (!isTauriRuntime()) {
          updateRuntimeMessage(ui, "Native file pickers are available in packaged desktop builds.");
        }
        return;
      }
      input.value = selectedPath;
      commitRecentPath(ui, group, selectedPath);
      options.afterSelect?.();
    })();
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
  ui.results.detailSlider.addEventListener("keydown", (event) => {
    let nextValue: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowUp") {
      nextValue = state.resultsDetailLevel + 1;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
      nextValue = state.resultsDetailLevel - 1;
    } else if (event.key === "PageUp") {
      nextValue = state.resultsDetailLevel + 2;
    } else if (event.key === "PageDown") {
      nextValue = state.resultsDetailLevel - 2;
    } else if (event.key === "Home") {
      nextValue = minimum;
    } else if (event.key === "End") {
      nextValue = maximum;
    }
    if (nextValue === null) {
      return;
    }
    event.preventDefault();
    applyValue(nextValue);
  });
}

function bindCompareKnob(ui: AppUi, controller: ReturnType<typeof initDesignSystem>): void {
  const minimum = -12;
  const maximum = 12;
  const applyValue = (value: number, source: "compare_report" | "manual" | "render_qa" | "none" = "manual") => {
    state.compareCompensationDb = clamp(roundToStep(value, 0.1), minimum, maximum);
    state.compareCompensationEvaluationOnly = true;
    if (source === "manual") {
      state.compareCompensationMethodId = "COMPARE.LOUDNESS_MATCH.MANUAL";
      state.compareCompensationNote = "Manual compare compensation override. Evaluation only until you explicitly render or commit a change.";
    }
    state.compareCompensationSource = source;
    if (state.playback.context === "compare") {
      void applyAuditionGain(ui, compareAuditionGainDb()).catch(() => undefined);
    }
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
  ui.compareCompensation.knob.addEventListener("keydown", (event) => {
    const fineAdjust = controller.isFineAdjust(event);
    const arrowStep = fineAdjust ? 0.1 : 0.5;
    const pageStep = fineAdjust ? 0.5 : 2;
    let nextValue: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowUp") {
      nextValue = state.compareCompensationDb + arrowStep;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
      nextValue = state.compareCompensationDb - arrowStep;
    } else if (event.key === "PageUp") {
      nextValue = state.compareCompensationDb + pageStep;
    } else if (event.key === "PageDown") {
      nextValue = state.compareCompensationDb - pageStep;
    } else if (event.key === "Home") {
      nextValue = minimum;
    } else if (event.key === "End") {
      nextValue = maximum;
    }
    if (nextValue === null) {
      return;
    }
    event.preventDefault();
    applyValue(nextValue, "manual");
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
  ui.scene.focusPad.addEventListener("keydown", (event) => {
    const step = controller.isFineAdjust(event) ? 5 : 10;
    let nextPan = state.sceneFocusPan;
    let nextDepth = state.sceneFocusDepth;
    if (event.key === "ArrowLeft") {
      nextPan -= step;
    } else if (event.key === "ArrowRight") {
      nextPan += step;
    } else if (event.key === "ArrowUp") {
      nextDepth += step;
    } else if (event.key === "ArrowDown") {
      nextDepth -= step;
    } else {
      return;
    }
    event.preventDefault();
    applyFocus(nextPan, nextDepth);
  });
}

window.addEventListener("DOMContentLoaded", () => {
  const controller = initDesignSystem({
    defaultScreen: "validate",
  });
  designController = controller;
  const ui = getUi();

  for (const stage of Object.values(ui.stages)) {
    setStageStatus(stage, "idle", "Idle");
  }

  updateRuntimeMessage(
    ui,
    "Choose a stems folder and a workspace folder to get started. Think of the workspace as MMO's session notebook: every report, scene, render, and receipt lands there.",
  );
  renderAll(ui);
  applyBusyState(ui);
  applyShortcutMetadata(ui);

  ui.inputs.workspaceDir.addEventListener("input", () => {
    resetSceneLocksState("Inspect scene locks to fine-tune how MMO places each part in the room.");
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
  bindRecentInput(ui, ui.inputs.stemsDir, "stemsDirs");
  bindRecentInput(ui, ui.inputs.workspaceDir, "workspaceDirs", () => {
    resetSceneLocksState("Inspect scene locks to fine-tune how MMO places each part in the room.");
    renderAll(ui);
  });
  bindRecentInput(ui, ui.inputs.sceneLocksPath, "sceneLocksPaths");
  bindRecentInput(ui, ui.compareInputs.aPath, "compareInputs", () => {
    scheduleCompareAuditionRefresh(ui);
    renderCompare(ui);
  });
  bindRecentInput(ui, ui.compareInputs.bPath, "compareInputs", () => {
    scheduleCompareAuditionRefresh(ui);
    renderCompare(ui);
  });

  bindDirectoryBrowseButton(
    ui,
    ui.browseButtons.stemsDir,
    ui.inputs.stemsDir,
    "stemsDirs",
    "Pick stems folder",
  );
  bindDirectoryBrowseButton(
    ui,
    ui.browseButtons.workspaceDir,
    ui.inputs.workspaceDir,
    "workspaceDirs",
    "Pick workspace folder",
    () => resetSceneLocksState("Inspect scene locks to fine-tune how MMO places each part in the room."),
  );
  bindFilePathBrowseButton(
    ui,
    ui.browseButtons.sceneLocksPath,
    ui.inputs.sceneLocksPath,
    "sceneLocksPaths",
    {
      afterSelect: () => renderAll(ui),
      extensions: ["json", "yaml", "yml"],
      label: "Scene locks",
      title: "Pick scene-locks artifact",
    },
  );
  bindFilePathBrowseButton(
    ui,
    ui.browseButtons.compareAFile,
    ui.compareInputs.aPath,
    "compareInputs",
    {
      afterSelect: () => {
        scheduleCompareAuditionRefresh(ui);
        renderCompare(ui);
      },
      extensions: ["json"],
      label: "Compare input JSON",
      title: "Pick compare A artifact",
    },
  );
  bindDirectoryBrowseButton(
    ui,
    ui.browseButtons.compareAFolder,
    ui.compareInputs.aPath,
    "compareInputs",
    "Pick compare A workspace folder",
    () => {
      scheduleCompareAuditionRefresh(ui);
      renderCompare(ui);
    },
  );
  bindFilePathBrowseButton(
    ui,
    ui.browseButtons.compareBFile,
    ui.compareInputs.bPath,
    "compareInputs",
    {
      afterSelect: () => {
        scheduleCompareAuditionRefresh(ui);
        renderCompare(ui);
      },
      extensions: ["json"],
      label: "Compare input JSON",
      title: "Pick compare B artifact",
    },
  );
  bindDirectoryBrowseButton(
    ui,
    ui.browseButtons.compareBFolder,
    ui.compareInputs.bPath,
    "compareInputs",
    "Pick compare B workspace folder",
    () => {
      scheduleCompareAuditionRefresh(ui);
      renderCompare(ui);
    },
  );

  ui.nerdView.toggle.addEventListener("click", () => {
    state.nerdView = !state.nerdView;
    renderAll(ui);
  });

  ui.artifactSearch.addEventListener("input", () => {
    state.resultsArtifactSearch = ui.artifactSearch.value;
    renderResults(ui);
  });
  ui.results.browserList.addEventListener("keydown", (event) => {
    const target = event.target instanceof HTMLElement
      ? event.target.closest<HTMLButtonElement>("[data-artifact-entry-id]")
      : null;
    if (target === null) {
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      event.preventDefault();
      moveSelectedResultsArtifact(ui, "next");
      return;
    }
    if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      event.preventDefault();
      moveSelectedResultsArtifact(ui, "previous");
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      moveSelectedResultsArtifact(ui, "first");
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      moveSelectedResultsArtifact(ui, "last");
    }
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
      const preserveTime = ui.auditionAudio.currentTime;
      const shouldResume = state.playback.context === "compare" && state.playback.status === "playing";
      const shouldKeepPausedState = state.playback.context === "compare" && state.playback.status === "paused";
      state.compareState = compareState;
      renderCompare(ui);
      if (shouldResume || shouldKeepPausedState) {
        void playCompareAudition(ui, {
          autoplay: shouldResume,
          preserveTime,
        });
      }
    });
  }
  window.addEventListener("keydown", (event) => {
    if (event.defaultPrevented || event.repeat) {
      return;
    }
    if (!event.altKey && !event.ctrlKey && !event.metaKey && event.key === "/" && !isEditableTarget(event.target)) {
      event.preventDefault();
      setScreenAndFocus(ui, controller, "results");
      window.requestAnimationFrame(() => {
        ui.artifactSearch.focus({ preventScroll: true });
        ui.artifactSearch.select();
      });
      return;
    }
    if (event.ctrlKey || event.metaKey) {
      return;
    }

    if (event.altKey && !event.shiftKey) {
      const screen = (() => {
        switch (event.code) {
          case "Digit1":
            return "validate";
          case "Digit2":
            return "analyze";
          case "Digit3":
            return "scene";
          case "Digit4":
            return "render";
          case "Digit5":
            return "results";
          case "Digit6":
            return "compare";
          default:
            return null;
        }
      })();
      if (screen !== null) {
        event.preventDefault();
        setScreenAndFocus(ui, controller, screen);
      }
      return;
    }

    if (!event.altKey || !event.shiftKey) {
      return;
    }

    switch (event.code) {
      case "KeyR":
        event.preventDefault();
        setScreenAndFocus(ui, controller, "render");
        ui.buttons.render.click();
        break;
      case "KeyS":
        event.preventDefault();
        ui.browseButtons.stemsDir.click();
        break;
      case "KeyV":
        event.preventDefault();
        setScreenAndFocus(ui, controller, "validate");
        ui.buttons.validate.click();
        break;
      case "KeyW":
        event.preventDefault();
        ui.browseButtons.workspaceDir.click();
        break;
      default:
        break;
    }
  });

  ui.artifactPreviewTransport.play.addEventListener("click", () => {
    void playResultsAudition(ui);
  });
  ui.artifactPreviewTransport.pause.addEventListener("click", () => {
    pauseAuditionPlayback(ui);
  });
  ui.artifactPreviewTransport.stop.addEventListener("click", () => {
    stopAuditionPlayback(ui);
  });
  ui.compareTransport.play.addEventListener("click", () => {
    void playCompareAudition(ui);
  });
  ui.compareTransport.pause.addEventListener("click", () => {
    pauseAuditionPlayback(ui);
  });
  ui.compareTransport.stop.addEventListener("click", () => {
    stopAuditionPlayback(ui);
  });

  ui.auditionAudio.addEventListener("play", () => {
    state.playback.error = "";
    state.playback.status = "playing";
    renderAuditionTransports(ui);
  });
  ui.auditionAudio.addEventListener("pause", () => {
    if (state.playback.status === "loading") {
      return;
    }
    state.playback.status = ui.auditionAudio.currentTime > 0 ? "paused" : "stopped";
    renderAuditionTransports(ui);
  });
  ui.auditionAudio.addEventListener("ended", () => {
    state.playback.status = "stopped";
    state.playback.error = "";
    renderAuditionTransports(ui);
  });
  ui.auditionAudio.addEventListener("error", () => {
    state.playback.status = "stopped";
    state.playback.error = "Audio playback failed for the active audition file.";
    renderAuditionTransports(ui);
  });

  bindCompareKnob(ui, controller);
  bindResultsDetailSlider(ui, controller);
  bindSceneFocus(ui, controller);

  ui.scene.lockPerspectiveSelect.addEventListener("change", () => {
    state.sceneLocks.perspective = ui.scene.lockPerspectiveSelect.value;
    syncSceneLocksDirty();
    renderScene(ui);
  });
  ui.scene.lockInspectButton.addEventListener("click", () => {
    void inspectSceneLocks(ui).catch(() => undefined);
  });
  ui.scene.lockSaveButton.addEventListener("click", () => {
    void runWithBusy(ui, "scene", async () => {
      await saveSceneLocks(ui);
    });
  });

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
        throw new Error(
          "Choose a workspace folder first.\n"
          + "Why: MMO refreshes Results from files already saved in that workspace.\n"
          + "Next: Pick the workspace you used for Render, then refresh Results again.",
        );
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

  const applyDerivedCompareCompensation = (force = false) => {
    const derived = deriveCompareCompensation();
    if (!force && state.compareCompensationSource === "manual") {
      return;
    }
    state.compareCompensationDb = derived.db;
    state.compareCompensationEvaluationOnly = derived.evaluationOnly;
    state.compareCompensationMethodId = derived.methodId;
    state.compareCompensationNote = derived.note;
    state.compareCompensationSource = derived.source;
    if (state.playback.context === "compare") {
      void applyAuditionGain(ui, compareAuditionGainDb()).catch(() => undefined);
    }
  };

  const loadValidationArtifact = (payload: JsonObject, sourceName: string) => {
    state.artifacts.validation = payload;
    state.artifactSources.validationPath = sourceName;
    renderAll(ui);
    updateRuntimeMessage(ui, `Loaded validation artifact: ${sourceName}`);
  };
  const loadReportArtifact = (payload: JsonObject, sourceName: string) => {
    state.artifacts.report = payload;
    state.artifactSources.reportPath = sourceName;
    renderAll(ui);
    controller.setScreen("analyze");
    updateRuntimeMessage(ui, `Loaded report artifact: ${sourceName}`);
  };
  const loadScanArtifact = (payload: JsonObject, sourceName: string) => {
    state.artifacts.scan = payload;
    state.artifactSources.scanPath = sourceName;
    renderAll(ui);
    updateRuntimeMessage(ui, `Loaded scan artifact: ${sourceName}`);
  };
  const loadSceneArtifact = (payload: JsonObject, sourceName: string) => {
    state.artifacts.scene = payload;
    state.artifactSources.scenePath = sourceName;
    renderAll(ui);
    controller.setScreen("scene");
    updateRuntimeMessage(ui, `Loaded scene artifact: ${sourceName}`);
  };
  const loadSceneLintArtifact = (payload: JsonObject, sourceName: string) => {
    state.artifacts.sceneLint = payload;
    state.artifactSources.sceneLintPath = sourceName;
    renderAll(ui);
    updateRuntimeMessage(ui, `Loaded scene lint artifact: ${sourceName}`);
  };
  const loadResultsReceiptArtifact = (payload: JsonObject, sourceName: string) => {
    state.artifacts.receipt = payload;
    state.artifactSources.receiptPath = sourceName;
    renderAll(ui);
    controller.setScreen("results");
    updateRuntimeMessage(ui, `Loaded safe-render receipt: ${sourceName}`);
  };
  const loadResultsManifestArtifact = (payload: JsonObject, sourceName: string) => {
    state.artifacts.manifest = payload;
    state.artifactSources.manifestPath = sourceName;
    renderAll(ui);
    updateRuntimeMessage(ui, `Loaded render manifest: ${sourceName}`);
  };
  const loadResultsQaArtifact = (payload: JsonObject, sourceName: string) => {
    state.artifacts.qa = payload;
    state.artifactSources.qaPath = sourceName;
    renderAll(ui);
    updateRuntimeMessage(ui, `Loaded render QA: ${sourceName}`);
  };
  const loadCompareReportArtifact = (payload: JsonObject, sourceName: string) => {
    state.artifacts.compare = payload;
    state.artifactSources.comparePath = sourceName;
    applyDerivedCompareCompensation(true);
    renderAll(ui);
    scheduleCompareAuditionRefresh(ui);
    controller.setScreen("compare");
    updateRuntimeMessage(ui, `Loaded compare report: ${sourceName}`);
  };
  const loadCompareAQaArtifact = (payload: JsonObject, sourceName: string) => {
    state.artifacts.compareAQa = payload;
    state.artifactSources.compareAQaPath = sourceName;
    applyDerivedCompareCompensation();
    renderAll(ui);
    scheduleCompareAuditionRefresh(ui);
    updateRuntimeMessage(ui, `Loaded A render QA: ${sourceName}`);
  };
  const loadCompareBQaArtifact = (payload: JsonObject, sourceName: string) => {
    state.artifacts.compareBQa = payload;
    state.artifactSources.compareBQaPath = sourceName;
    applyDerivedCompareCompensation();
    renderAll(ui);
    scheduleCompareAuditionRefresh(ui);
    updateRuntimeMessage(ui, `Loaded B render QA: ${sourceName}`);
  };

  bindJsonFileInput(ui.fileInputs.validateValidation, loadValidationArtifact, () => {
    updateRuntimeMessage(ui, "validation.json import is not valid JSON.");
  });
  bindJsonFileInput(ui.fileInputs.analyzeReport, loadReportArtifact, () => {
    updateRuntimeMessage(ui, "report.json import is not valid JSON.");
  });
  bindJsonFileInput(ui.fileInputs.analyzeScan, loadScanArtifact, () => {
    updateRuntimeMessage(ui, "report.scan.json import is not valid JSON.");
  });
  bindJsonFileInput(ui.fileInputs.sceneJson, loadSceneArtifact, () => {
    updateRuntimeMessage(ui, "scene.json import is not valid JSON.");
  });
  bindJsonFileInput(ui.fileInputs.sceneLint, loadSceneLintArtifact, () => {
    updateRuntimeMessage(ui, "scene_lint.json import is not valid JSON.");
  });
  bindJsonFileInput(ui.fileInputs.resultsReceipt, loadResultsReceiptArtifact, () => {
    updateRuntimeMessage(ui, "safe_render_receipt.json import is not valid JSON.");
  });
  bindJsonFileInput(ui.fileInputs.resultsManifest, loadResultsManifestArtifact, () => {
    updateRuntimeMessage(ui, "render_manifest.json import is not valid JSON.");
  });
  bindJsonFileInput(ui.fileInputs.resultsQa, loadResultsQaArtifact, () => {
    updateRuntimeMessage(ui, "render_qa.json import is not valid JSON.");
  });
  bindJsonFileInput(ui.fileInputs.compareReport, loadCompareReportArtifact, () => {
    updateRuntimeMessage(ui, "compare_report.json import is not valid JSON.");
  });
  bindJsonFileInput(ui.fileInputs.compareAQa, loadCompareAQaArtifact, () => {
    updateRuntimeMessage(ui, "A render_qa.json import is not valid JSON.");
  });
  bindJsonFileInput(ui.fileInputs.compareBQa, loadCompareBQaArtifact, () => {
    updateRuntimeMessage(ui, "B render_qa.json import is not valid JSON.");
  });

  ui.browseButtons.sceneJson.addEventListener("click", () => {
    void browseAndLoadJson(ui.fileInputs.sceneJson, {
      defaultPath: state.artifactSources.scenePath || state.recentPaths.workspaceDirs[0],
      label: "Scene artifact JSON",
      onFailure: () => updateRuntimeMessage(ui, "scene.json import is not valid JSON."),
      onLoad: loadSceneArtifact,
      title: "Pick scene.json",
    });
  });
  ui.browseButtons.sceneLint.addEventListener("click", () => {
    void browseAndLoadJson(ui.fileInputs.sceneLint, {
      defaultPath: state.artifactSources.sceneLintPath || state.recentPaths.workspaceDirs[0],
      label: "Scene lint JSON",
      onFailure: () => updateRuntimeMessage(ui, "scene_lint.json import is not valid JSON."),
      onLoad: loadSceneLintArtifact,
      title: "Pick scene_lint.json",
    });
  });
  ui.browseButtons.resultsReceipt.addEventListener("click", () => {
    void browseAndLoadJson(ui.fileInputs.resultsReceipt, {
      defaultPath: state.artifactSources.receiptPath || state.recentPaths.workspaceDirs[0],
      label: "Render receipt JSON",
      onFailure: () => updateRuntimeMessage(ui, "safe_render_receipt.json import is not valid JSON."),
      onLoad: loadResultsReceiptArtifact,
      title: "Pick safe_render_receipt.json",
    });
  });
  ui.browseButtons.resultsManifest.addEventListener("click", () => {
    void browseAndLoadJson(ui.fileInputs.resultsManifest, {
      defaultPath: state.artifactSources.manifestPath || state.recentPaths.workspaceDirs[0],
      label: "Render manifest JSON",
      onFailure: () => updateRuntimeMessage(ui, "render_manifest.json import is not valid JSON."),
      onLoad: loadResultsManifestArtifact,
      title: "Pick render_manifest.json",
    });
  });
  ui.browseButtons.resultsQa.addEventListener("click", () => {
    void browseAndLoadJson(ui.fileInputs.resultsQa, {
      defaultPath: state.artifactSources.qaPath || state.recentPaths.workspaceDirs[0],
      label: "Render QA JSON",
      onFailure: () => updateRuntimeMessage(ui, "render_qa.json import is not valid JSON."),
      onLoad: loadResultsQaArtifact,
      title: "Pick render_qa.json",
    });
  });
  ui.browseButtons.compareReport.addEventListener("click", () => {
    void browseAndLoadJson(ui.fileInputs.compareReport, {
      defaultPath: state.artifactSources.comparePath || state.recentPaths.workspaceDirs[0],
      label: "Compare report JSON",
      onFailure: () => updateRuntimeMessage(ui, "compare_report.json import is not valid JSON."),
      onLoad: loadCompareReportArtifact,
      title: "Pick compare_report.json",
    });
  });
  ui.browseButtons.compareAQa.addEventListener("click", () => {
    void browseAndLoadJson(ui.fileInputs.compareAQa, {
      defaultPath: state.artifactSources.compareAQaPath || ui.compareInputs.aPath.value.trim() || state.recentPaths.compareInputs[0],
      label: "Render QA JSON",
      onFailure: () => updateRuntimeMessage(ui, "A render_qa.json import is not valid JSON."),
      onLoad: loadCompareAQaArtifact,
      title: "Pick A render_qa.json",
    });
  });
  ui.browseButtons.compareBQa.addEventListener("click", () => {
    void browseAndLoadJson(ui.fileInputs.compareBQa, {
      defaultPath: state.artifactSources.compareBQaPath || ui.compareInputs.bPath.value.trim() || state.recentPaths.compareInputs[0],
      label: "Render QA JSON",
      onFailure: () => updateRuntimeMessage(ui, "B render_qa.json import is not valid JSON."),
      onLoad: loadCompareBQaArtifact,
      title: "Pick B render_qa.json",
    });
  });

  window.__MMO_DESKTOP_TEST__ = {
    ...(window.__MMO_DESKTOP_TEST__ ?? {}),
    clearMockRpcResults: () => {
      desktopTestRpcResults.clear();
    },
    runMmoRpc: async (method) => {
      const payload = desktopTestRpcResults.get(method);
      if (payload === undefined) {
        throw new Error(`No desktop test RPC mock registered for ${method}.`);
      }
      return cloneJsonObject(payload);
    },
    setMockRpcResult: (method: string, payload: JsonObject) => {
      desktopTestRpcResults.set(method, cloneJsonObject(payload));
    },
  };

  void (async () => {
    state.recentPaths = await loadRecentPaths();
    renderAll(ui);

    const desktopSmokeConfig = await readDesktopSmokeConfig();
    if (desktopSmokeConfig !== null) {
      await runDesktopSmoke(ui, controller, desktopSmokeConfig);
      return;
    }

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
      applyDerivedCompareCompensation(true);
    }
    scheduleCompareAuditionRefresh(ui);
    renderAll(ui);
  })();
});
