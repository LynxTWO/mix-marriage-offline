import { buildFormFields, orderFieldsByLayout, resolveFieldStep } from "/lib/plugin_forms.mjs";
import {
  computeAuditionCompensation,
  formatAuditionCompensationReceipt,
  resolveAuditionLoudnessDb,
} from "/lib/audition_loudness.mjs";
import {
  buildWaveformProfile,
  computeChannelRms,
  formatPeakDbfs,
  meterLevelFromDbfs,
  rmsToDbfs,
} from "/lib/headphone_preview_meter.mjs";
import {
  buildSpectrumProfile,
  buildWaveformEnvelope,
  mixChannelsToMono,
  normalizeSpectralProfile,
} from "/lib/audition_overlays.mjs";
import {
  buildMeterHistogram,
  buildMeterRowsFromRenderQa,
  buildMeterRowsFromReport,
  buildMeterSummary,
  buildSceneDistribution,
  resolveAuditionQaComparison,
} from "/lib/dashboard_visuals.mjs";

const discoverButton = document.getElementById("discover-button");
const doctorButton = document.getElementById("doctor-button");
const showProjectButton = document.getElementById("show-project-button");
const buildGuiButton = document.getElementById("build-gui-button");
const chainAddButton = document.getElementById("chain-add-button");
const chainSaveButton = document.getElementById("chain-save-button");
const safeRunButton = document.getElementById("safe-run-button");

const methodsList = document.getElementById("methods-list");
const doctorOutput = document.getElementById("doctor-output");
const projectOutput = document.getElementById("project-output");
const statusOutput = document.getElementById("status-output");
const dashboardMeterCanvas = document.getElementById("dashboard-meter-canvas");
const dashboardMeterSummary = document.getElementById("dashboard-meter-summary");
const dashboardDistributionCanvas = document.getElementById("dashboard-distribution-canvas");
const dashboardDistributionSummary = document.getElementById("dashboard-distribution-summary");
const pluginsContainer = document.getElementById("plugins-container");
const pluginMarketContainer = document.getElementById("plugin-market-container");
const pluginMarketListButton = document.getElementById("plugin-market-list-button");
const pluginMarketUpdateButton = document.getElementById("plugin-market-update-button");
const pluginMarketOutput = document.getElementById("plugin-market-output");
const chainContainer = document.getElementById("chain-container");
const chainOutput = document.getElementById("chain-output");
const intentOutput = document.getElementById("intent-output");
const sceneLayoutSelect = document.getElementById("scene-layout-select");
const scenePreviewWarnings = document.getElementById("scene-preview-warnings");
const scenePreviewStage = document.getElementById("scene-preview-stage");
const scenePreviewStageCanvas = document.getElementById("scene-preview-stage-canvas");
const scenePreviewStageEmpty = document.getElementById("scene-preview-stage-empty");
const scenePreviewOutput = document.getElementById("scene-preview-output");
const scenePerspectiveSelect = document.getElementById("scene-perspective-select");
const sceneLocksReloadButton = document.getElementById("scene-locks-reload-button");
const sceneLocksSaveButton = document.getElementById("scene-locks-save-button");
const sceneLocksContainer = document.getElementById("scene-locks-container");
const sceneLocksOutput = document.getElementById("scene-locks-output");
const renderSummaryOutput = document.getElementById("render-summary-output");
const determinismOutput = document.getElementById("determinism-output");
const safeRunReceiptOutput = document.getElementById("safe-run-receipt-output");
const copyReceiptButton = document.getElementById("copy-receipt-button");
const renderRefusalOutput = document.getElementById("render-refusal-output");
const renderExecuteOutput = document.getElementById("render-execute-output");
const timelineContainer = document.getElementById("timeline-container");
const timelineJobFilter = document.getElementById("timeline-job-filter");
const timelineStageFilter = document.getElementById("timeline-stage-filter");
const auditionJobSelect = document.getElementById("audition-job-select");
const auditionInputSlotSelect = document.getElementById("audition-input-slot-select");
const auditionOutputSlotSelect = document.getElementById("audition-output-slot-select");
const auditionPlayInputButton = document.getElementById("audition-play-input-button");
const auditionPlayOutputButton = document.getElementById("audition-play-output-button");
const previewHeadphonesButton = document.getElementById("preview-headphones-button");
const auditionInputSha = document.getElementById("audition-input-sha");
const auditionOutputSha = document.getElementById("audition-output-sha");
const auditionAudio = document.getElementById("audition-audio");
const auditionLoudnessMatchLabel = document.getElementById("audition-loudness-match-label");
const auditionLoudnessMatchToggle = document.getElementById("audition-loudness-match-toggle");
const auditionLoudnessReceipt = document.getElementById("audition-loudness-receipt");
const auditionStatus = document.getElementById("audition-status");
const headphonePreviewVisual = document.getElementById("headphone-preview-visual");
const headphonePreviewWaveform = document.getElementById("headphone-preview-waveform");
const headphonePreviewPeak = document.getElementById("headphone-preview-peak");
const headphonePreviewMeterLeft = document.getElementById("headphone-preview-meter-left");
const headphonePreviewMeterRight = document.getElementById("headphone-preview-meter-right");
const auditionWaveformCanvas = document.getElementById("audition-waveform-canvas");
const auditionSpectrumCanvas = document.getElementById("audition-spectrum-canvas");
const auditionOverlayStatus = document.getElementById("audition-overlay-status");

const projectDirInput = document.getElementById("project-dir-input");
const stemsRootInput = document.getElementById("stems-root-input");
const packOutInput = document.getElementById("pack-out-input");
const pluginsDirInput = document.getElementById("plugins-dir-input");
const chainPluginSelect = document.getElementById("chain-plugin-select");
const maxTheoreticalQualityToggle = document.getElementById("max-theoretical-quality-toggle");
const fineModeIndicator = document.getElementById("fine-mode-indicator");

// Browser state mixes disk-backed receipts with unsaved UI drafts. When a
// later refresh disagrees, project.show and artifact files stay authoritative.
const state = {
  projectShow: null,
  uiBundle: null,
  sceneLayoutId: "",
  scenePreview: null,
  sceneLocks: {
    objects: [],
    overridesCount: 0,
    perspective: "audience",
    perspectiveValues: ["audience", "on_stage", "in_band", "in_orchestra"],
    roleOptions: [],
    sceneLocksPath: "",
    scenePath: "",
  },
  pluginMarket: null,
  pluginMarketUpdate: null,
  pluginsById: new Map(),
  editablePluginIds: [],
  pluginChain: [],
  renderRequestIntent: {
    dry_run: null,
    max_theoretical_quality: null,
    plugin_chain_length: 0,
    policies: {},
    render_request_path: "",
    target_ids: [],
    target_layout_ids: [],
  },
  renderArtifacts: {
    eventLogEntries: [],
    execute: null,
    lastRefusal: null,
    qa: null,
    report: null,
    timelineFilterJob: "",
    timelineFilterStage: "",
  },
  audition: {
    activeStream: "",
    inputSlot: 0,
    jobId: "",
    loudnessMatchEnabled: true,
    outputSlot: 0,
    overlays: {
      inputSpectrum: null,
      inputWaveform: null,
      outputSpectrum: null,
      outputWaveform: null,
      status: "Select a render job to inspect pre/post audition overlays.",
      spectrumSource: "",
      waveformSource: "",
    },
  },
  modifierState: {
    shift: false,
    alt: false,
    ctrl: false,
    meta: false,
  },
};
const AUDITION_ALLOW_BOOST = false;
const HEADPHONE_PREVIEW_BAR_COUNT = 28;
const AUDITION_OVERLAY_MAX_DECODE_BYTES = 20 * 1024 * 1024;
const auditionOverlayCache = new Map();
let auditionOverlayRequestVersion = 0;
let auditionAudioContext = null;
let auditionAudioGainNode = null;
let auditionAudioSourceNode = null;
let auditionAnalyserLeft = null;
let auditionAnalyserRight = null;
let auditionAnalyserDataLeft = null;
let auditionAnalyserDataRight = null;
let headphonePreviewAnimationFrame = 0;

function normalizePath(value) {
  if (typeof value !== "string") {
    return "";
  }
  return value.trim().replace(/\\/g, "/");
}

function joinPosix(basePath, leafName) {
  const normalizedBase = normalizePath(basePath).replace(/\/+$/, "");
  if (!normalizedBase) {
    return leafName;
  }
  return `${normalizedBase}/${leafName}`;
}

function setStatus(text) {
  statusOutput.textContent = text;
}

function _isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function _deepClone(value) {
  if (value === null || value === undefined) {
    return value;
  }
  return JSON.parse(JSON.stringify(value));
}

function _isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function _clampUnit(value, fallback = 1) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  if (numeric <= 0) {
    return 0;
  }
  if (numeric >= 1) {
    return 1;
  }
  return numeric;
}

function _formatMetricValue(value, suffix = "", digits = 1) {
  if (!Number.isFinite(value)) {
    return "n/a";
  }
  return `${Number(value).toFixed(digits)}${suffix}`;
}

function _renderSummaryChips(container, items) {
  if (!container) {
    return;
  }
  container.innerHTML = "";
  const rows = Array.isArray(items) ? items : [];
  for (const item of rows) {
    if (!_isObject(item)) {
      continue;
    }
    const labelText = typeof item.label === "string" ? item.label.trim() : "";
    const valueText = typeof item.value === "string" ? item.value.trim() : "";
    if (!labelText || !valueText) {
      continue;
    }
    const chip = document.createElement("div");
    chip.className = "dashboard-summary-chip";

    const label = document.createElement("span");
    label.className = "dashboard-summary-label";
    label.textContent = labelText;
    chip.appendChild(label);

    const value = document.createElement("span");
    value.className = "dashboard-summary-value";
    value.textContent = valueText;
    chip.appendChild(value);

    container.appendChild(chip);
  }
}

function _prepareCanvasFrame(canvas, fallbackHeight = 220) {
  if (!canvas) {
    return null;
  }
  const rect = canvas.getBoundingClientRect();
  const cssWidth = Math.max(1, Math.round(rect.width || canvas.clientWidth || 320));
  const cssHeight = Math.max(
    1,
    Number.parseInt(canvas.getAttribute("height") || "", 10) || Math.round(rect.height || fallbackHeight),
  );
  const devicePixelRatio = typeof window !== "undefined" && Number.isFinite(window.devicePixelRatio)
    ? window.devicePixelRatio
    : 1;
  const targetWidth = Math.max(1, Math.round(cssWidth * devicePixelRatio));
  const targetHeight = Math.max(1, Math.round(cssHeight * devicePixelRatio));
  if (canvas.width !== targetWidth || canvas.height !== targetHeight) {
    canvas.width = targetWidth;
    canvas.height = targetHeight;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return null;
  }
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  return {
    ctx,
    height: cssHeight,
    width: cssWidth,
  };
}

function _drawEmptyCanvasState(canvas, message, fallbackHeight = 220) {
  const frame = _prepareCanvasFrame(canvas, fallbackHeight);
  if (!frame) {
    return;
  }
  const { ctx, width, height } = frame;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#0f171d";
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = "rgba(244, 248, 251, 0.82)";
  ctx.font = '14px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(message, width / 2, height / 2);
}

function _valuePosition(value, minValue, maxValue, width) {
  if (!Number.isFinite(value)) {
    return null;
  }
  const ratio = (value - minValue) / Math.max(1e-9, maxValue - minValue);
  return _clampUnit(ratio, 0) * width;
}

function _normalizeModifierKey(value) {
  const normalized = typeof value === "string" ? value.trim().toLowerCase() : "";
  if (normalized === "alt" || normalized === "ctrl" || normalized === "meta") {
    return normalized;
  }
  return "shift";
}

function _modifierStateFromKeyboardEvent(event) {
  return {
    shift: Boolean(event?.shiftKey),
    alt: Boolean(event?.altKey),
    ctrl: Boolean(event?.ctrlKey),
    meta: Boolean(event?.metaKey),
  };
}

function _modifierStateChanged(nextState) {
  return (
    state.modifierState.shift !== nextState.shift
    || state.modifierState.alt !== nextState.alt
    || state.modifierState.ctrl !== nextState.ctrl
    || state.modifierState.meta !== nextState.meta
  );
}

function _renderFineModeIndicator() {
  if (!fineModeIndicator) {
    return;
  }
  const active = (
    state.modifierState.shift
    || state.modifierState.alt
    || state.modifierState.ctrl
    || state.modifierState.meta
  );
  fineModeIndicator.classList.toggle("active", active);
  fineModeIndicator.textContent = active ? "Fine" : "Normal";
}

function _activeStepForInput(input) {
  const baseStep = Number(input.dataset.mmoStep || "");
  if (!Number.isFinite(baseStep) || baseStep <= 0) {
    return null;
  }
  const fineStep = Number(input.dataset.mmoFineStep || "");
  const modifierKey = _normalizeModifierKey(input.dataset.mmoModifierKey);
  if (Number.isFinite(fineStep) && fineStep > 0 && state.modifierState[modifierKey] === true) {
    return fineStep;
  }
  return baseStep;
}

function _refreshFineSteps() {
  const inputs = document.querySelectorAll("[data-mmo-step]");
  for (const input of inputs) {
    const step = _activeStepForInput(input);
    if (step === null) {
      input.removeAttribute("step");
      continue;
    }
    input.step = String(step);
  }
  _renderFineModeIndicator();
}

function _setModifierState(nextState) {
  if (!_modifierStateChanged(nextState)) {
    return;
  }
  state.modifierState = {
    shift: nextState.shift,
    alt: nextState.alt,
    ctrl: nextState.ctrl,
    meta: nextState.meta,
  };
  _refreshFineSteps();
}

function _bindFineStepInput(input, field) {
  const baseStep = resolveFieldStep(field, {});
  if (!_isFiniteNumber(baseStep) || baseStep <= 0) {
    return;
  }
  input.dataset.mmoStep = String(baseStep);
  if (_isFiniteNumber(field.fineStep) && field.fineStep > 0) {
    input.dataset.mmoFineStep = String(field.fineStep);
  }
  input.dataset.mmoModifierKey = _normalizeModifierKey(field.modifierKey);
  const liveStep = resolveFieldStep(field, state.modifierState);
  if (_isFiniteNumber(liveStep) && liveStep > 0) {
    input.step = String(liveStep);
  }
}

async function apiRpc(method, params = {}) {
  // The local bridge is trusted only after HTTP success and RPC shape checks.
  // Refuse partial payloads here so the UI does not invent a backend result.
  const response = await fetch("/api/rpc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ method, params }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  const rpcResponse = payload.response;
  if (!rpcResponse || typeof rpcResponse !== "object") {
    throw new Error("RPC response missing.");
  }
  if (rpcResponse.ok !== true) {
    const code = rpcResponse.error?.code || "RPC.ERROR";
    const message = rpcResponse.error?.message || "Unknown RPC error.";
    const error = new Error(`${code}: ${message}`);
    error.rpcCode = code;
    error.rpcMessage = message;
    throw error;
  }
  return rpcResponse.result || {};
}

async function loadUiBundle(uiBundlePath) {
  const response = await fetch("/api/ui-bundle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ui_bundle_path: uiBundlePath, viewport: "1280x720" }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  // Missing plugin or scene payloads stay explicit empties. The browser can
  // reset local panels, but it should not guess fields the backend did not ship.
  const plugins = Array.isArray(payload.plugins) ? payload.plugins : [];
  const bundle = _isObject(payload.ui_bundle) ? payload.ui_bundle : {};
  state.uiBundle = _deepClone(bundle);
  state.scenePreview = _isObject(bundle.scene_preview) ? _deepClone(bundle.scene_preview) : null;
  renderPluginForms(plugins);
  _setEditablePlugins(plugins);
  _renderScenePreview();
  _renderDashboardVisuals();
}

async function loadRenderRequest(renderRequestPath) {
  const response = await fetch("/api/render-request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ render_request_path: renderRequestPath }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  // The editor mirrors render_request.json only when the bridge returned a real
  // object payload. Missing structure is a load failure, not a local default.
  if (!_isObject(payload.render_request)) {
    throw new Error("render_request payload missing.");
  }
  return {
    path: typeof payload.render_request_path === "string" ? payload.render_request_path : "",
    payload: payload.render_request,
  };
}

async function loadRenderArtifact(artifactPath) {
  const response = await fetch("/api/render-artifact", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ artifact_path: artifactPath }),
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  // Artifact routes can return JSON objects, arrays, or scalar content. Keep
  // the bridge metadata alongside the parsed payload instead of reshaping it.
  return {
    artifact: payload.artifact,
    artifactName: typeof payload.artifact_name === "string" ? payload.artifact_name : "",
    format: typeof payload.format === "string" ? payload.format : "",
    path: typeof payload.artifact_path === "string" ? payload.artifact_path : "",
  };
}

function renderMethods(methods) {
  methodsList.innerHTML = "";
  if (!Array.isArray(methods) || methods.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No methods returned.";
    methodsList.appendChild(li);
    return;
  }
  for (const methodName of methods) {
    const li = document.createElement("li");
    li.textContent = methodName;
    methodsList.appendChild(li);
  }
}

function _snapshotCanvas(snapshot) {
  const viewport = snapshot.viewport || {};
  const width = typeof viewport.width_px === "number" ? viewport.width_px : 1;
  const height = typeof viewport.height_px === "number" ? viewport.height_px : 1;
  const maxWidth = 560;
  const drawScale = Math.min(maxWidth / width, 1);
  const drawWidth = Math.max(Math.round(width * drawScale), 1);
  const drawHeight = Math.max(Math.round(height * drawScale), 1);

  const canvas = document.createElement("div");
  canvas.className = "snapshot-canvas";
  canvas.style.width = `${drawWidth}px`;
  canvas.style.height = `${drawHeight}px`;

  const sections = Array.isArray(snapshot.sections) ? snapshot.sections : [];
  for (const section of sections) {
    const box = document.createElement("div");
    box.className = "snapshot-section";
    box.style.left = `${Math.round((section.x_px || 0) * drawScale)}px`;
    box.style.top = `${Math.round((section.y_px || 0) * drawScale)}px`;
    box.style.width = `${Math.max(Math.round((section.width_px || 0) * drawScale), 1)}px`;
    box.style.height = `${Math.max(Math.round((section.height_px || 0) * drawScale), 1)}px`;
    box.title = section.section_id || "";
    canvas.appendChild(box);
  }

  const widgets = Array.isArray(snapshot.widgets) ? snapshot.widgets : [];
  for (const widget of widgets) {
    const box = document.createElement("div");
    box.className = "snapshot-widget";
    box.style.left = `${Math.round((widget.x_px || 0) * drawScale)}px`;
    box.style.top = `${Math.round((widget.y_px || 0) * drawScale)}px`;
    box.style.width = `${Math.max(Math.round((widget.width_px || 0) * drawScale), 1)}px`;
    box.style.height = `${Math.max(Math.round((widget.height_px || 0) * drawScale), 1)}px`;
    box.textContent = widget.widget_id || "";
    box.title = widget.widget_id || "";
    canvas.appendChild(box);
  }
  return canvas;
}

function _renderLayoutSnapshot(container, plugin) {
  const snapshot = plugin.ui_layout_snapshot;
  const meta = plugin.ui_layout_snapshot_meta;
  if (!snapshot || typeof snapshot !== "object") {
    if (meta && typeof meta === "object") {
      const info = document.createElement("p");
      info.className = "field-meta";
      info.textContent = `Layout snapshot metadata only. violations_count=${meta.violations_count ?? "-"}`;
      container.appendChild(info);
    }
    return;
  }

  const heading = document.createElement("p");
  heading.className = "field-meta";
  const viewport = snapshot.viewport || {};
  heading.textContent = `Snapshot: ${viewport.width_px || "?"}x${viewport.height_px || "?"}, ok=${snapshot.ok === true}`;
  container.appendChild(heading);

  const wrapper = document.createElement("div");
  wrapper.className = "layout-snapshot";
  wrapper.appendChild(_snapshotCanvas(snapshot));
  container.appendChild(wrapper);

  const violations = Array.isArray(snapshot.violations) ? snapshot.violations : [];
  if (violations.length > 0) {
    const violationsPre = document.createElement("pre");
    violationsPre.className = "code-block";
    violationsPre.textContent = JSON.stringify(violations, null, 2);
    container.appendChild(violationsPre);
  }
}

function _encodeSelectValue(value) {
  return JSON.stringify(value);
}

function _decodeSelectValue(rawValue) {
  if (typeof rawValue !== "string") {
    return rawValue;
  }
  try {
    return JSON.parse(rawValue);
  } catch {
    return rawValue;
  }
}

function _setNumericBounds(input, field) {
  if (_isFiniteNumber(field.minimum)) {
    input.min = String(field.minimum);
  }
  if (_isFiniteNumber(field.maximum)) {
    input.max = String(field.maximum);
  }
}

function _withUnits(control, field) {
  if (typeof field.units !== "string" || !field.units) {
    return control;
  }
  const wrapped = document.createElement("div");
  wrapped.className = "control-with-units";
  wrapped.appendChild(control);

  const units = document.createElement("span");
  units.className = "control-units";
  units.textContent = field.units;
  wrapped.appendChild(units);
  return wrapped;
}

function _numericControlValue(value, field) {
  if (_isFiniteNumber(value)) {
    return value;
  }
  if (_isFiniteNumber(field.minimum)) {
    return field.minimum;
  }
  if (_isFiniteNumber(field.maximum)) {
    return field.maximum;
  }
  return 0;
}

function _snapshotLayoutForOrdering(snapshot) {
  const widgets = Array.isArray(snapshot?.widgets)
    ? snapshot.widgets.filter((widget) => _isObject(widget))
    : [];
  if (widgets.length === 0) {
    return null;
  }

  const sortedWidgets = [...widgets].sort((left, right) => {
    const leftY = _isFiniteNumber(left.y_px) ? left.y_px : 0;
    const rightY = _isFiniteNumber(right.y_px) ? right.y_px : 0;
    if (leftY !== rightY) {
      return leftY - rightY;
    }
    const leftX = _isFiniteNumber(left.x_px) ? left.x_px : 0;
    const rightX = _isFiniteNumber(right.x_px) ? right.x_px : 0;
    if (leftX !== rightX) {
      return leftX - rightX;
    }
    const leftId = typeof left.widget_id === "string" ? left.widget_id : "";
    const rightId = typeof right.widget_id === "string" ? right.widget_id : "";
    return leftId.localeCompare(rightId);
  });

  return {
    sections: [
      {
        section_id: "snapshot",
        widgets: sortedWidgets,
      },
    ],
  };
}

function _orderedFieldsByLayout(plugin, fields) {
  const layoutPresent = _isObject(plugin?.ui_layout) && plugin.ui_layout.present !== false;
  if (!layoutPresent) {
    return { orderedFields: fields, moreFields: [], hasLayout: false };
  }

  const fromLayout = orderFieldsByLayout(fields, plugin?.ui_layout_document);
  if (fromLayout.hasLayout) {
    return fromLayout;
  }
  const snapshotLayout = _snapshotLayoutForOrdering(plugin?.ui_layout_snapshot);
  const fromSnapshot = orderFieldsByLayout(fields, snapshotLayout);
  if (fromSnapshot.hasLayout) {
    return fromSnapshot;
  }
  return { orderedFields: fields, moreFields: [], hasLayout: false };
}

function _renderFieldLabel(field) {
  const label = document.createElement("div");
  const requiredTag = field.required ? " (required)" : "";
  const widgetHint = field.hint?.widget ? ` [${field.hint.widget}]` : "";
  label.innerHTML = `<strong>${field.label}</strong>${requiredTag}${widgetHint}<div class="field-meta">${field.name}${field.description ? ` - ${field.description}` : ""}</div>`;
  return label;
}

function _appendFieldRow(container, field, inputNode) {
  const row = document.createElement("div");
  row.className = "field-row";
  row.appendChild(_renderFieldLabel(field));
  row.appendChild(inputNode);
  container.appendChild(row);
}

function _selectOptionsForField(field) {
  if (Array.isArray(field.selectOptions) && field.selectOptions.length > 0) {
    return field.selectOptions;
  }
  return Array.isArray(field.enumValues)
    ? field.enumValues.map((value) => ({ value, label: String(value) }))
    : [];
}

function _createSelectInput(field, currentValue, { disabled = false, onChange = null } = {}) {
  const select = document.createElement("select");
  select.disabled = disabled;
  const options = _selectOptionsForField(field);
  const encodedCurrent = _encodeSelectValue(currentValue);
  for (const optionRow of options) {
    const option = document.createElement("option");
    option.value = _encodeSelectValue(optionRow.value);
    option.textContent = optionRow.label;
    option.selected = option.value === encodedCurrent;
    select.appendChild(option);
  }
  if (typeof onChange === "function") {
    select.addEventListener("change", () => {
      onChange(_decodeSelectValue(select.value), select.value);
    });
  }
  return select;
}

function _createReadOnlyRangeInput(field, currentValue) {
  const controls = document.createElement("div");
  controls.className = "range-with-entry";

  const rangeInput = document.createElement("input");
  rangeInput.type = "range";
  rangeInput.disabled = true;
  const numericInput = document.createElement("input");
  numericInput.type = "number";
  numericInput.disabled = true;

  const value = _numericControlValue(currentValue, field);
  rangeInput.value = String(value);
  numericInput.value = String(value);
  _setNumericBounds(rangeInput, field);
  _setNumericBounds(numericInput, field);
  _bindFineStepInput(rangeInput, field);
  _bindFineStepInput(numericInput, field);

  controls.appendChild(rangeInput);
  controls.appendChild(numericInput);
  return _withUnits(controls, field);
}

function _renderFieldInput(field) {
  const currentValue = field.defaultValue;

  if (field.inputKind === "checkbox") {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(currentValue);
    input.disabled = true;
    return _withUnits(input, field);
  }

  if (field.inputKind === "select") {
    return _withUnits(_createSelectInput(field, currentValue, { disabled: true }), field);
  }

  if (field.inputKind === "range") {
    return _createReadOnlyRangeInput(field, currentValue);
  }

  const input = document.createElement("input");
  input.type = field.inputKind === "number" ? "number" : "text";
  input.disabled = true;
  if (currentValue !== null && currentValue !== undefined) {
    input.value = String(currentValue);
  }
  if (field.inputKind === "number") {
    _setNumericBounds(input, field);
    _bindFineStepInput(input, field);
  }
  return _withUnits(input, field);
}

function _appendMoreSection(container, fields, renderInput) {
  if (!Array.isArray(fields) || fields.length === 0) {
    return;
  }
  const section = document.createElement("section");
  section.className = "field-more";
  const heading = document.createElement("h4");
  heading.textContent = "More";
  section.appendChild(heading);
  for (const field of fields) {
    _appendFieldRow(section, field, renderInput(field));
  }
  container.appendChild(section);
}

function renderPluginForms(plugins) {
  pluginsContainer.innerHTML = "";
  if (!Array.isArray(plugins) || plugins.length === 0) {
    const empty = document.createElement("p");
    empty.className = "subtle";
    empty.textContent = "No plugin payload found in ui_bundle.";
    pluginsContainer.appendChild(empty);
    return;
  }

  for (const plugin of plugins) {
    const card = document.createElement("article");
    card.className = "plugin-card";

    const title = document.createElement("h3");
    title.textContent = `${plugin.plugin_id || "(unknown)"}  [${plugin.plugin_type || "unknown"}]`;
    card.appendChild(title);

    if (plugin.error) {
      const errorBlock = document.createElement("div");
      errorBlock.className = "error-text";
      errorBlock.textContent = plugin.error;
      card.appendChild(errorBlock);
      pluginsContainer.appendChild(card);
      continue;
    }

    const schema = plugin.config_schema;
    const uiHints = Array.isArray(plugin.ui_hints) ? plugin.ui_hints : [];
    if (!schema || typeof schema !== "object") {
      const noSchema = document.createElement("p");
      noSchema.className = "subtle";
      noSchema.textContent = "No config_schema present for this plugin.";
      card.appendChild(noSchema);
    } else {
      const fields = buildFormFields(schema, uiHints);
      if (fields.length === 0) {
        const noProps = document.createElement("p");
        noProps.className = "subtle";
        noProps.textContent = "config_schema has no form fields.";
        card.appendChild(noProps);
      } else {
        const ordered = _orderedFieldsByLayout(plugin, fields);
        for (const field of ordered.orderedFields) {
          _appendFieldRow(card, field, _renderFieldInput(field));
        }
        if (ordered.hasLayout) {
          _appendMoreSection(card, ordered.moreFields, _renderFieldInput);
        }
      }
    }

    _renderLayoutSnapshot(card, plugin);
    pluginsContainer.appendChild(card);
  }
  _refreshFineSteps();
}

function _normalizeMarketplaceEntries(payload) {
  if (!_isObject(payload)) {
    return [];
  }
  const entries = Array.isArray(payload.entries) ? payload.entries : [];
  const normalized = entries
    .filter((entry) => _isObject(entry))
    .map((entry) => ({
      install_state: typeof entry.install_state === "string" ? entry.install_state : "available",
      installed: entry.installed === true,
      manifest_path: typeof entry.manifest_path === "string" ? entry.manifest_path : "",
      name: typeof entry.name === "string" ? entry.name : "",
      plugin_id: typeof entry.plugin_id === "string" ? entry.plugin_id : "",
      plugin_type: typeof entry.plugin_type === "string" ? entry.plugin_type : "",
      summary: typeof entry.summary === "string" ? entry.summary : "",
      tags: Array.isArray(entry.tags) ? entry.tags.filter((tag) => typeof tag === "string") : [],
      version: typeof entry.version === "string" ? entry.version : "",
    }));
  normalized.sort((left, right) => left.plugin_id.localeCompare(right.plugin_id));
  return normalized;
}

function renderPluginMarketplace(payload) {
  if (!pluginMarketContainer || !pluginMarketOutput) {
    return;
  }

  const entries = _normalizeMarketplaceEntries(payload);
  pluginMarketContainer.innerHTML = "";
  if (entries.length === 0) {
    const empty = document.createElement("p");
    empty.className = "subtle";
    empty.textContent = "No marketplace entries loaded.";
    pluginMarketContainer.appendChild(empty);
  } else {
    for (const entry of entries) {
      const card = document.createElement("article");
      card.className = "plugin-market-card";

      const title = document.createElement("h3");
      title.textContent = `${entry.plugin_id} [${entry.plugin_type}]`;
      card.appendChild(title);

      const meta = document.createElement("p");
      meta.className = "subtle";
      const tags = entry.tags.length > 0 ? entry.tags.join(",") : "-";
      meta.textContent = (
        `version=${entry.version || "-"} `
        + `state=${entry.install_state || "available"} `
        + `tags=${tags}`
      );
      card.appendChild(meta);

      if (entry.summary) {
        const summary = document.createElement("p");
        summary.textContent = entry.summary;
        card.appendChild(summary);
      }
      if (entry.manifest_path) {
        const manifest = document.createElement("code");
        manifest.textContent = entry.manifest_path;
        card.appendChild(manifest);
      }
      pluginMarketContainer.appendChild(card);
    }
  }

  const header = _isObject(payload) ? payload : {};
  pluginMarketOutput.textContent = JSON.stringify(
    {
      entry_count: typeof header.entry_count === "number" ? header.entry_count : entries.length,
      index_path: typeof header.index_path === "string" ? header.index_path : "",
      installed_count: typeof header.installed_count === "number" ? header.installed_count : 0,
      installed_scan_error: typeof header.installed_scan_error === "string"
        ? header.installed_scan_error
        : "",
      market_id: typeof header.market_id === "string" ? header.market_id : "",
      schema_version: typeof header.schema_version === "string" ? header.schema_version : "",
    },
    null,
    2,
  );
}

function _isEditablePlugin(plugin) {
  return (
    _isObject(plugin)
    && typeof plugin.plugin_id === "string"
    && plugin.plugin_id.trim()
    && _isObject(plugin.config_schema)
    && Array.isArray(plugin.ui_hints)
  );
}

function _setEditablePlugins(plugins) {
  // Only schema-backed plugins join the local chain editor. The browser should
  // not invent editable params for payloads it cannot round-trip safely.
  const editable = Array.isArray(plugins)
    ? plugins.filter((plugin) => _isEditablePlugin(plugin))
    : [];

  editable.sort((left, right) => {
    const a = typeof left.plugin_id === "string" ? left.plugin_id : "";
    const b = typeof right.plugin_id === "string" ? right.plugin_id : "";
    return a.localeCompare(b);
  });

  state.pluginsById = new Map(
    editable.map((plugin) => [plugin.plugin_id, plugin]),
  );
  state.editablePluginIds = editable.map((plugin) => plugin.plugin_id);
  renderChainPluginSelect();
  renderPluginChainEditor();
}

function renderChainPluginSelect() {
  chainPluginSelect.innerHTML = "";
  if (state.editablePluginIds.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No eligible plugins loaded";
    chainPluginSelect.appendChild(option);
    chainPluginSelect.disabled = true;
    return;
  }

  chainPluginSelect.disabled = false;
  for (const pluginId of state.editablePluginIds) {
    const option = document.createElement("option");
    option.value = pluginId;
    option.textContent = pluginId;
    chainPluginSelect.appendChild(option);
  }
}

function _defaultParamsForPlugin(plugin) {
  if (!_isObject(plugin)) {
    return {};
  }
  const schema = _isObject(plugin.config_schema) ? plugin.config_schema : null;
  if (!schema) {
    return {};
  }
  const hints = Array.isArray(plugin.ui_hints) ? plugin.ui_hints : [];
  const fields = buildFormFields(schema, hints);
  const defaults = {};
  for (const field of fields) {
    if (field.defaultValue !== null && field.defaultValue !== undefined) {
      defaults[field.name] = _deepClone(field.defaultValue);
    }
  }
  return defaults;
}

function _normalizeIdList(rawValue) {
  if (!Array.isArray(rawValue)) {
    return [];
  }
  const unique = new Set();
  for (const value of rawValue) {
    if (typeof value !== "string") {
      continue;
    }
    const trimmed = value.trim();
    if (!trimmed) {
      continue;
    }
    unique.add(trimmed);
  }
  return Array.from(unique).sort();
}

function _extractIssueId(text) {
  const candidate = typeof text === "string" ? text : "";
  const match = candidate.match(/ISSUE\.RENDER\.RUN\.[A-Z0-9_]+/);
  return match ? match[0] : "";
}

function _resetRenderArtifactsState() {
  state.renderArtifacts = {
    eventLogEntries: [],
    execute: null,
    lastRefusal: null,
    qa: null,
    report: null,
    timelineFilterJob: "",
    timelineFilterStage: "",
  };
}

function _recordRenderRefusal(error) {
  // Refusals start as session-local browser receipts. A later render refresh or
  // project.show reload can replace them with disk-backed artifact truth.
  const rpcCode = typeof error?.rpcCode === "string" ? error.rpcCode : "RPC.ERROR";
  const rpcMessage = typeof error?.rpcMessage === "string"
    ? error.rpcMessage
    : (error instanceof Error ? error.message : String(error));
  const issueId = _extractIssueId(rpcMessage);
  state.renderArtifacts.lastRefusal = {
    issue_id: issueId || null,
    message: rpcMessage,
    rpc_code: rpcCode,
  };
}

function _clearRenderRefusal() {
  // Clear the local refusal note before a new run so stale browser errors do
  // not look like the next disk-backed render outcome.
  state.renderArtifacts.lastRefusal = null;
}

function _extractReasonFromNotes(notes) {
  if (!Array.isArray(notes)) {
    return "";
  }
  for (const item of notes) {
    if (typeof item !== "string") {
      continue;
    }
    const trimmed = item.trim();
    if (!trimmed) {
      continue;
    }
    if (trimmed.toLowerCase().startsWith("reason:")) {
      return trimmed.slice("reason:".length).trim();
    }
  }
  return "";
}

function _extractIssueIdFromNotes(notes) {
  if (!Array.isArray(notes)) {
    return "";
  }
  for (const item of notes) {
    if (typeof item !== "string") {
      continue;
    }
    const issueId = _extractIssueId(item);
    if (issueId) {
      return issueId;
    }
  }
  return "";
}

function _artifactPathToJobIds() {
  const map = new Map();
  const append = (pathValue, jobId) => {
    const normalizedPath = normalizePath(pathValue);
    if (!normalizedPath || !jobId) {
      return;
    }
    const current = map.get(normalizedPath) || new Set();
    current.add(jobId);
    map.set(normalizedPath, current);
  };

  const executeJobs = Array.isArray(state.renderArtifacts.execute?.jobs)
    ? state.renderArtifacts.execute.jobs
    : [];
  for (const job of executeJobs) {
    if (!_isObject(job)) {
      continue;
    }
    const jobId = typeof job.job_id === "string" ? job.job_id.trim() : "";
    if (!jobId) {
      continue;
    }
    const inputs = Array.isArray(job.inputs) ? job.inputs : [];
    for (const input of inputs) {
      if (_isObject(input) && typeof input.path === "string") {
        append(input.path, jobId);
      }
    }
    const outputs = Array.isArray(job.outputs) ? job.outputs : [];
    for (const output of outputs) {
      if (_isObject(output) && typeof output.path === "string") {
        append(output.path, jobId);
      }
    }
  }

  const reportJobs = Array.isArray(state.renderArtifacts.report?.jobs)
    ? state.renderArtifacts.report.jobs
    : [];
  for (const job of reportJobs) {
    if (!_isObject(job)) {
      continue;
    }
    const jobId = typeof job.job_id === "string" ? job.job_id.trim() : "";
    if (!jobId) {
      continue;
    }
    const outputs = Array.isArray(job.output_files) ? job.output_files : [];
    for (const output of outputs) {
      if (_isObject(output) && typeof output.file_path === "string") {
        append(output.file_path, jobId);
      }
    }
  }
  return map;
}

function _inferEventJobIds(event, pathToJobIds) {
  const jobIds = new Set();
  const evidence = _isObject(event?.evidence) ? event.evidence : {};
  const evidenceIds = Array.isArray(evidence.ids) ? evidence.ids : [];
  for (const item of evidenceIds) {
    if (typeof item !== "string") {
      continue;
    }
    const trimmed = item.trim();
    if (/^JOB\.[0-9]{3}$/.test(trimmed)) {
      jobIds.add(trimmed);
    }
  }

  const where = Array.isArray(event?.where) ? event.where : [];
  for (const item of where) {
    if (typeof item !== "string") {
      continue;
    }
    const normalizedPath = normalizePath(item);
    if (!normalizedPath) {
      continue;
    }
    const mapped = pathToJobIds.get(normalizedPath);
    if (!mapped) {
      continue;
    }
    for (const jobId of mapped) {
      jobIds.add(jobId);
    }
  }

  const evidencePaths = Array.isArray(evidence.paths) ? evidence.paths : [];
  for (const item of evidencePaths) {
    if (typeof item !== "string") {
      continue;
    }
    const normalizedPath = normalizePath(item);
    if (!normalizedPath) {
      continue;
    }
    const mapped = pathToJobIds.get(normalizedPath);
    if (!mapped) {
      continue;
    }
    for (const jobId of mapped) {
      jobIds.add(jobId);
    }
  }
  return Array.from(jobIds).sort();
}

function _inferEventStage(event) {
  const where = Array.isArray(event?.where) ? event.where : [];
  for (const item of where) {
    if (typeof item === "string" && item.startsWith("plugin_chain.stage.")) {
      return item;
    }
  }
  const evidence = _isObject(event?.evidence) ? event.evidence : {};
  const metrics = Array.isArray(evidence.metrics) ? evidence.metrics : [];
  const stageMetric = metrics.find(
    (metric) => _isObject(metric) && metric.name === "stage_index",
  );
  if (_isObject(stageMetric) && typeof stageMetric.value === "number") {
    return `plugin_chain.stage.${String(stageMetric.value).padStart(3, "0")}`;
  }
  const codes = Array.isArray(evidence.codes) ? evidence.codes : [];
  if (codes.length > 0 && typeof codes[0] === "string" && codes[0].trim()) {
    return codes[0].trim();
  }
  return "general";
}

function _annotatedEventLogEntries() {
  const entries = Array.isArray(state.renderArtifacts.eventLogEntries)
    ? state.renderArtifacts.eventLogEntries
    : [];
  const pathToJobIds = _artifactPathToJobIds();
  return entries.map((event, index) => {
    const jobIds = _inferEventJobIds(event, pathToJobIds);
    const stage = _inferEventStage(event);
    const evidence = _isObject(event?.evidence) ? event.evidence : {};
    const codes = Array.isArray(evidence.codes)
      ? evidence.codes.filter((code) => typeof code === "string" && code.trim())
      : [];
    return {
      ...event,
      _codes: codes,
      _index: index + 1,
      _job_ids: jobIds,
      _stage: stage,
    };
  });
}

function _setSelectOptions(selectElement, options, selectedValue) {
  selectElement.innerHTML = "";
  for (const optionRow of options) {
    const option = document.createElement("option");
    option.value = optionRow.value;
    option.textContent = optionRow.label;
    option.selected = optionRow.value === selectedValue;
    selectElement.appendChild(option);
  }
}

function _pathTail(pathValue) {
  if (typeof pathValue !== "string" || !pathValue.trim()) {
    return "(unknown)";
  }
  const normalized = pathValue.replace(/\\/g, "/");
  const parts = normalized.split("/").filter((part) => part);
  return parts[parts.length - 1] || normalized;
}

function _pointerRows(job, streamKind) {
  if (!_isObject(job)) {
    return [];
  }
  const pointers = streamKind === "input"
    ? (Array.isArray(job.inputs) ? job.inputs : [])
    : (Array.isArray(job.outputs) ? job.outputs : []);
  return pointers.filter((pointer) => _isObject(pointer));
}

function _selectedPointerOrNull(job, streamKind, slot) {
  const pointers = _pointerRows(job, streamKind);
  if (!Number.isInteger(slot) || slot < 0 || slot >= pointers.length) {
    return null;
  }
  return pointers[slot];
}

function _slotSelectValue(selectElement) {
  const raw = typeof selectElement?.value === "string" ? selectElement.value.trim() : "";
  if (!/^\d+$/.test(raw)) {
    return 0;
  }
  return Number.parseInt(raw, 10);
}

function _setAuditionStatus(text) {
  if (auditionStatus) {
    auditionStatus.textContent = text;
  }
}

function _setAuditionReceipt(text) {
  if (auditionLoudnessReceipt) {
    auditionLoudnessReceipt.textContent = text;
  }
}

function _renderAuditionLoudnessToggle({ disabled } = { disabled: false }) {
  if (auditionLoudnessMatchToggle) {
    auditionLoudnessMatchToggle.checked = state.audition.loudnessMatchEnabled === true;
    auditionLoudnessMatchToggle.disabled = Boolean(disabled);
  }
  if (auditionLoudnessMatchLabel) {
    auditionLoudnessMatchLabel.textContent = `Loudness match: ${state.audition.loudnessMatchEnabled ? "On" : "Off"}`;
  }
}

function _ensureHeadphonePreviewBars() {
  if (!headphonePreviewWaveform) {
    return [];
  }
  if (headphonePreviewWaveform.childElementCount === 0) {
    for (let index = 0; index < HEADPHONE_PREVIEW_BAR_COUNT; index += 1) {
      const bar = document.createElement("span");
      bar.className = "headphone-preview-wave-bar";
      headphonePreviewWaveform.appendChild(bar);
    }
  }
  return Array.from(headphonePreviewWaveform.children);
}

function _setHeadphonePreviewActive(active) {
  if (!headphonePreviewVisual) {
    return;
  }
  headphonePreviewVisual.classList.toggle("is-active", Boolean(active));
}

function _renderHeadphonePreviewFrame(leftLevel, rightLevel, peakDbfs) {
  const safeLeft = Math.max(0, Math.min(1, Number.isFinite(leftLevel) ? leftLevel : 0));
  const safeRight = Math.max(0, Math.min(1, Number.isFinite(rightLevel) ? rightLevel : 0));
  if (headphonePreviewMeterLeft) {
    headphonePreviewMeterLeft.style.width = `${(safeLeft * 100).toFixed(1)}%`;
  }
  if (headphonePreviewMeterRight) {
    headphonePreviewMeterRight.style.width = `${(safeRight * 100).toFixed(1)}%`;
  }
  if (headphonePreviewPeak) {
    headphonePreviewPeak.textContent = formatPeakDbfs(peakDbfs);
  }
  const bars = _ensureHeadphonePreviewBars();
  if (bars.length === 0) {
    return;
  }
  const profile = buildWaveformProfile({
    leftLevel: safeLeft,
    rightLevel: safeRight,
    timeSeconds: auditionAudio?.currentTime || 0,
    barCount: bars.length,
  });
  for (let index = 0; index < bars.length; index += 1) {
    const bar = bars[index];
    const height = profile[index] ?? 0.1;
    bar.style.transform = `scaleY(${height.toFixed(4)})`;
    bar.style.opacity = (0.3 + (height * 0.68)).toFixed(3);
  }
}

function _renderHeadphonePreviewIdle() {
  _renderHeadphonePreviewFrame(0, 0, Number.NEGATIVE_INFINITY);
}

function _stopHeadphonePreviewAnimation() {
  if (headphonePreviewAnimationFrame && typeof window !== "undefined") {
    window.cancelAnimationFrame(headphonePreviewAnimationFrame);
  }
  headphonePreviewAnimationFrame = 0;
  _setHeadphonePreviewActive(false);
}

function _headphonePreviewTick() {
  if (!auditionAudio || auditionAudio.paused || auditionAudio.ended) {
    _stopHeadphonePreviewAnimation();
    _renderHeadphonePreviewIdle();
    return;
  }
  let leftLevel = 0;
  let rightLevel = 0;
  let peakDbfs = Number.NEGATIVE_INFINITY;
  if (
    auditionAnalyserLeft
    && auditionAnalyserRight
    && auditionAnalyserDataLeft
    && auditionAnalyserDataRight
  ) {
    auditionAnalyserLeft.getFloatTimeDomainData(auditionAnalyserDataLeft);
    auditionAnalyserRight.getFloatTimeDomainData(auditionAnalyserDataRight);
    const leftDbfs = rmsToDbfs(computeChannelRms(auditionAnalyserDataLeft));
    const rightDbfs = rmsToDbfs(computeChannelRms(auditionAnalyserDataRight));
    leftLevel = meterLevelFromDbfs(leftDbfs);
    rightLevel = meterLevelFromDbfs(rightDbfs);
    peakDbfs = Math.max(leftDbfs, rightDbfs);
  }
  _renderHeadphonePreviewFrame(leftLevel, rightLevel, peakDbfs);
  if (typeof window === "undefined") {
    return;
  }
  headphonePreviewAnimationFrame = window.requestAnimationFrame(_headphonePreviewTick);
}

function _startHeadphonePreviewAnimation() {
  if (typeof window === "undefined" || headphonePreviewAnimationFrame) {
    return;
  }
  _setHeadphonePreviewActive(true);
  headphonePreviewAnimationFrame = window.requestAnimationFrame(_headphonePreviewTick);
}

function _audioContextConstructor() {
  if (typeof window === "undefined") {
    return null;
  }
  if (typeof window.AudioContext === "function") {
    return window.AudioContext;
  }
  if (typeof window.webkitAudioContext === "function") {
    return window.webkitAudioContext;
  }
  return null;
}

async function _ensureAuditionGainNode() {
  if (!auditionAudio) {
    return null;
  }
  const AudioContextCtor = _audioContextConstructor();
  if (!AudioContextCtor) {
    return null;
  }
  if (!auditionAudioContext) {
    auditionAudioContext = new AudioContextCtor();
  }
  if (!auditionAudioSourceNode) {
    auditionAudioSourceNode = auditionAudioContext.createMediaElementSource(auditionAudio);
    auditionAudioGainNode = auditionAudioContext.createGain();
    auditionAudioSourceNode.connect(auditionAudioGainNode);
    auditionAudioGainNode.connect(auditionAudioContext.destination);
  }
  if (!auditionAnalyserLeft || !auditionAnalyserRight) {
    const splitter = auditionAudioContext.createChannelSplitter(2);
    auditionAnalyserLeft = auditionAudioContext.createAnalyser();
    auditionAnalyserRight = auditionAudioContext.createAnalyser();
    auditionAnalyserLeft.fftSize = 1024;
    auditionAnalyserRight.fftSize = 1024;
    auditionAnalyserDataLeft = new Float32Array(auditionAnalyserLeft.fftSize);
    auditionAnalyserDataRight = new Float32Array(auditionAnalyserRight.fftSize);
    auditionAudioGainNode.connect(splitter);
    splitter.connect(auditionAnalyserLeft, 0);
    splitter.connect(auditionAnalyserRight, 1);
  }
  if (auditionAudioContext.state === "suspended") {
    try {
      await auditionAudioContext.resume();
    } catch {
      // Browser policy can block resume outside a trusted gesture.
    }
  }
  return auditionAudioGainNode;
}

async function _applyAuditionGainDb(gainDb) {
  const gainNode = await _ensureAuditionGainNode();
  if (!gainNode) {
    return;
  }
  const linear = Math.pow(10, gainDb / 20);
  gainNode.gain.value = linear;
}

function _selectedAuditionJobOrNull() {
  const jobs = Array.isArray(state.renderArtifacts.execute?.jobs)
    ? state.renderArtifacts.execute.jobs.filter((job) => _isObject(job))
    : [];
  const selected = jobs.find((job) => job.job_id === state.audition.jobId);
  return selected || null;
}

function _auditionCompensationResult(streamKind, selectedJob) {
  const resolvedJob = _isObject(selectedJob) ? selectedJob : _selectedAuditionJobOrNull();
  const inputPointer = _selectedPointerOrNull(resolvedJob, "input", state.audition.inputSlot);
  const outputPointer = _selectedPointerOrNull(resolvedJob, "output", state.audition.outputSlot);
  return computeAuditionCompensation({
    rmsInputDbfs: resolveAuditionLoudnessDb(inputPointer),
    rmsOutputDbfs: resolveAuditionLoudnessDb(outputPointer),
    streamKind,
    allowBoost: AUDITION_ALLOW_BOOST,
  });
}

function _renderAuditionReceipt(selectedJob, streamKind) {
  if (!state.audition.loudnessMatchEnabled) {
    _setAuditionReceipt(formatAuditionCompensationReceipt(null, { enabled: false }));
    return;
  }
  const result = _auditionCompensationResult(streamKind, selectedJob);
  _setAuditionReceipt(formatAuditionCompensationReceipt(result, { enabled: true }));
}

async function _applyAuditionCompensation(streamKind, selectedJob) {
  // Loudness matching is preview-only. It trims the browser gain node and does
  // not rewrite render outputs or pointer metadata on disk.
  if (!state.audition.loudnessMatchEnabled) {
    await _applyAuditionGainDb(0);
    _renderAuditionReceipt(selectedJob, streamKind);
    return;
  }
  const result = _auditionCompensationResult(streamKind, selectedJob);
  await _applyAuditionGainDb(result.gainDb);
  _renderAuditionReceipt(selectedJob, streamKind);
}

function _drawWaveformOverlayCanvas() {
  if (!auditionWaveformCanvas) {
    return;
  }
  const overlays = _isObject(state.audition.overlays) ? state.audition.overlays : {};
  const inputWaveform = Array.isArray(overlays.inputWaveform) ? overlays.inputWaveform : [];
  const outputWaveform = Array.isArray(overlays.outputWaveform) ? overlays.outputWaveform : [];
  if (inputWaveform.length === 0 && outputWaveform.length === 0) {
    _drawEmptyCanvasState(auditionWaveformCanvas, "Waveform overlay unavailable.", 180);
    return;
  }
  const frame = _prepareCanvasFrame(auditionWaveformCanvas, 180);
  if (!frame) {
    return;
  }
  const { ctx, width, height } = frame;
  ctx.clearRect(0, 0, width, height);
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "#0d1419");
  gradient.addColorStop(1, "#16232a");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  const centerY = height * 0.53;
  ctx.strokeStyle = "rgba(202, 219, 228, 0.16)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, centerY);
  ctx.lineTo(width, centerY);
  ctx.stroke();

  const drawEnvelope = (envelope, fillStyle, strokeStyle) => {
    if (!Array.isArray(envelope) || envelope.length === 0) {
      return;
    }
    const maxHeight = height * 0.34;
    ctx.beginPath();
    for (let index = 0; index < envelope.length; index += 1) {
      const x = (index / Math.max(1, envelope.length - 1)) * width;
      const y = centerY - ((_clampUnit(envelope[index], 0) || 0) * maxHeight);
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    for (let index = envelope.length - 1; index >= 0; index -= 1) {
      const x = (index / Math.max(1, envelope.length - 1)) * width;
      const y = centerY + ((_clampUnit(envelope[index], 0) || 0) * maxHeight);
      ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fillStyle = fillStyle;
    ctx.fill();
    ctx.strokeStyle = strokeStyle;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  };

  drawEnvelope(inputWaveform, "rgba(90, 180, 199, 0.24)", "#6bd0de");
  drawEnvelope(outputWaveform, "rgba(223, 148, 74, 0.26)", "#f0b663");

  ctx.fillStyle = "#e5eef2";
  ctx.font = '12px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  ctx.fillText("Input", 14, 18);
  ctx.fillText("Output", 74, 18);
}

function _drawSpectrumOverlayCanvas() {
  if (!auditionSpectrumCanvas) {
    return;
  }
  const overlays = _isObject(state.audition.overlays) ? state.audition.overlays : {};
  const inputSpectrum = _isObject(overlays.inputSpectrum) ? overlays.inputSpectrum : {};
  const outputSpectrum = _isObject(overlays.outputSpectrum) ? overlays.outputSpectrum : {};
  const inputCenters = Array.isArray(inputSpectrum.centersHz) ? inputSpectrum.centersHz : [];
  const outputCenters = Array.isArray(outputSpectrum.centersHz) ? outputSpectrum.centersHz : [];
  if (inputCenters.length === 0 && outputCenters.length === 0) {
    _drawEmptyCanvasState(auditionSpectrumCanvas, "Spectrum overlay unavailable.", 180);
    return;
  }
  const frame = _prepareCanvasFrame(auditionSpectrumCanvas, 180);
  if (!frame) {
    return;
  }
  const { ctx, width, height } = frame;
  ctx.clearRect(0, 0, width, height);
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "#0d1419");
  gradient.addColorStop(1, "#16232a");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  const pairs = [];
  const appendPairs = (spectrum) => {
    const centersHz = Array.isArray(spectrum.centersHz) ? spectrum.centersHz : [];
    const levelsDb = Array.isArray(spectrum.levelsDb) ? spectrum.levelsDb : [];
    for (let index = 0; index < Math.min(centersHz.length, levelsDb.length); index += 1) {
      const centerHz = centersHz[index];
      const levelDb = levelsDb[index];
      if (Number.isFinite(centerHz) && Number.isFinite(levelDb)) {
        pairs.push({ centerHz, levelDb });
      }
    }
  };
  appendPairs(inputSpectrum);
  appendPairs(outputSpectrum);

  const minHz = Math.max(20, Math.min(...pairs.map((row) => row.centerHz)));
  const maxHz = Math.max(minHz + 1, Math.max(...pairs.map((row) => row.centerHz)));
  const maxLevel = Math.max(...pairs.map((row) => row.levelDb));
  const minLevel = Math.min(maxLevel - 72, ...pairs.map((row) => row.levelDb));
  const top = 20;
  const bottom = height - 18;
  const plotHeight = bottom - top;

  const drawSpectrum = (spectrum, strokeStyle) => {
    const centersHz = Array.isArray(spectrum.centersHz) ? spectrum.centersHz : [];
    const levelsDb = Array.isArray(spectrum.levelsDb) ? spectrum.levelsDb : [];
    if (centersHz.length === 0 || levelsDb.length === 0) {
      return;
    }
    ctx.beginPath();
    for (let index = 0; index < Math.min(centersHz.length, levelsDb.length); index += 1) {
      const centerHz = centersHz[index];
      const levelDb = levelsDb[index];
      if (!Number.isFinite(centerHz) || !Number.isFinite(levelDb)) {
        continue;
      }
      const x = (
        (Math.log10(centerHz) - Math.log10(minHz))
        / Math.max(1e-9, Math.log10(maxHz) - Math.log10(minHz))
      ) * (width - 28) + 14;
      const y = top + ((maxLevel - levelDb) / Math.max(1e-9, maxLevel - minLevel)) * plotHeight;
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.strokeStyle = strokeStyle;
    ctx.lineWidth = 2;
    ctx.stroke();
  };

  ctx.strokeStyle = "rgba(196, 212, 222, 0.14)";
  ctx.lineWidth = 1;
  for (const markerHz of [40, 100, 250, 1000, 4000, 16000]) {
    if (markerHz < minHz || markerHz > maxHz) {
      continue;
    }
    const x = (
      (Math.log10(markerHz) - Math.log10(minHz))
      / Math.max(1e-9, Math.log10(maxHz) - Math.log10(minHz))
    ) * (width - 28) + 14;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.stroke();
  }

  drawSpectrum(inputSpectrum, "#6bd0de");
  drawSpectrum(outputSpectrum, "#f0b663");
  ctx.fillStyle = "#e5eef2";
  ctx.font = '12px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  ctx.fillText("Input", 14, 16);
  ctx.fillText("Output", 74, 16);
}

function _renderAuditionVisualOverlays() {
  _drawWaveformOverlayCanvas();
  _drawSpectrumOverlayCanvas();
  if (auditionOverlayStatus) {
    const overlays = _isObject(state.audition.overlays) ? state.audition.overlays : {};
    auditionOverlayStatus.textContent = overlays.status
      || "Select a render job to inspect pre/post audition overlays.";
  }
}

async function _decodeAuditionPointerSummary(jobId, streamKind, slot, sha256) {
  // Cache by content hash when present so repeated preview clicks do not keep
  // re-decoding the same file through the local audio bridge.
  const cacheKey = sha256 || `${jobId}:${streamKind}:${slot}`;
  if (auditionOverlayCache.has(cacheKey)) {
    return auditionOverlayCache.get(cacheKey);
  }
  const task = (async () => {
    if (typeof fetch !== "function") {
      return null;
    }
    const AudioContextCtor = _audioContextConstructor();
    if (!AudioContextCtor) {
      return null;
    }
    if (!auditionAudioContext) {
      auditionAudioContext = new AudioContextCtor();
    }
    const url = _auditionUrlFor(jobId, streamKind, slot);
    try {
      // HEAD keeps oversized decode work out of the browser before a full fetch.
      const headResponse = await fetch(url, { method: "HEAD" });
      if (!headResponse.ok) {
        return null;
      }
      const byteLength = Number(headResponse.headers.get("content-length"));
      if (Number.isFinite(byteLength) && byteLength > AUDITION_OVERLAY_MAX_DECODE_BYTES) {
        return {
          skipped: "oversize",
          spectrum: null,
          waveform: null,
        };
      }
      const response = await fetch(url);
      if (!response.ok) {
        return null;
      }
      const arrayBuffer = await response.arrayBuffer();
      const decoded = await auditionAudioContext.decodeAudioData(arrayBuffer.slice(0));
      const channels = [];
      for (let index = 0; index < Math.min(decoded.numberOfChannels, 2); index += 1) {
        channels.push(decoded.getChannelData(index));
      }
      const mono = mixChannelsToMono(channels);
      return {
        spectrum: buildSpectrumProfile(mono, decoded.sampleRate, { bandCount: 40 }),
        waveform: buildWaveformEnvelope(mono, { pointCount: 96 }),
      };
    } catch {
      return null;
    }
  })();
  auditionOverlayCache.set(cacheKey, task);
  return task;
}

async function _refreshAuditionOverlays() {
  const selectedJob = _selectedAuditionJobOrNull();
  const inputPointer = _selectedPointerOrNull(selectedJob, "input", state.audition.inputSlot);
  const outputPointer = _selectedPointerOrNull(selectedJob, "output", state.audition.outputSlot);
  if (!selectedJob || !inputPointer || !outputPointer) {
    state.audition.overlays = {
      inputSpectrum: null,
      inputWaveform: null,
      outputSpectrum: null,
      outputWaveform: null,
      spectrumSource: "",
      status: "Select both input and output pointers to inspect overlays.",
      waveformSource: "",
    };
    _renderAuditionVisualOverlays();
    return;
  }

  // Drop stale overlay responses when the user changes jobs or slots mid-load.
  const requestVersion = auditionOverlayRequestVersion + 1;
  auditionOverlayRequestVersion = requestVersion;
  state.audition.overlays = {
    ...state.audition.overlays,
    status: `Loading overlays for ${state.audition.jobId}...`,
  };
  _renderAuditionVisualOverlays();

  const qaMatch = resolveAuditionQaComparison(
    state.renderArtifacts.qa,
    state.audition.jobId,
    outputPointer.path,
  );
  const [inputSummary, outputSummary] = await Promise.all([
    _decodeAuditionPointerSummary(
      state.audition.jobId,
      "input",
      state.audition.inputSlot,
      inputPointer.sha256,
    ),
    _decodeAuditionPointerSummary(
      state.audition.jobId,
      "output",
      state.audition.outputSlot,
      outputPointer.sha256,
    ),
  ]);
  if (requestVersion !== auditionOverlayRequestVersion) {
    return;
  }

  // QA spectra win over ad hoc browser decode when the render artifacts already
  // carry analyzer output for this pointer pair.
  const qaInputSpectrum = normalizeSpectralProfile(qaMatch?.input?.spectral);
  const qaOutputSpectrum = normalizeSpectralProfile(qaMatch?.output?.spectral);
  const decodedInputSpectrum = normalizeSpectralProfile(inputSummary?.spectrum);
  const decodedOutputSpectrum = normalizeSpectralProfile(outputSummary?.spectrum);
  const inputSpectrum = qaInputSpectrum.centersHz.length > 0 ? qaInputSpectrum : decodedInputSpectrum;
  const outputSpectrum = qaOutputSpectrum.centersHz.length > 0 ? qaOutputSpectrum : decodedOutputSpectrum;
  const waveformSource = (
    Array.isArray(inputSummary?.waveform) && inputSummary.waveform.length > 0
    && Array.isArray(outputSummary?.waveform) && outputSummary.waveform.length > 0
  ) ? "audio decode" : "unavailable";
  const spectrumSource = (
    inputSpectrum.centersHz.length > 0 && outputSpectrum.centersHz.length > 0
      ? (qaInputSpectrum.centersHz.length > 0 && qaOutputSpectrum.centersHz.length > 0
          ? "render_qa"
          : "audio decode")
      : "unavailable"
  );

  state.audition.overlays = {
    inputSpectrum,
    inputWaveform: Array.isArray(inputSummary?.waveform) ? inputSummary.waveform : null,
    outputSpectrum,
    outputWaveform: Array.isArray(outputSummary?.waveform) ? outputSummary.waveform : null,
    spectrumSource,
    status: `Waveform: ${waveformSource}. Spectrum: ${spectrumSource}.`,
    waveformSource,
  };
  _renderAuditionVisualOverlays();
}

function _renderAuditionPanel() {
  if (
    !auditionJobSelect
    || !auditionInputSlotSelect
    || !auditionOutputSlotSelect
    || !auditionInputSha
    || !auditionOutputSha
    || !auditionPlayInputButton
    || !auditionPlayOutputButton
  ) {
    return;
  }

  // Audition options come from render_execute.json pointers. Without that file,
  // the browser has nothing safe to stream or compare.
  const jobs = Array.isArray(state.renderArtifacts.execute?.jobs)
    ? state.renderArtifacts.execute.jobs.filter((job) => _isObject(job) && typeof job.job_id === "string" && job.job_id)
    : [];
  jobs.sort((left, right) => String(left.job_id).localeCompare(String(right.job_id)));

  if (jobs.length === 0) {
    _setSelectOptions(auditionJobSelect, [{ value: "", label: "No jobs" }], "");
    _setSelectOptions(auditionInputSlotSelect, [{ value: "0", label: "(none)" }], "0");
    _setSelectOptions(auditionOutputSlotSelect, [{ value: "0", label: "(none)" }], "0");
    auditionJobSelect.disabled = true;
    auditionInputSlotSelect.disabled = true;
    auditionOutputSlotSelect.disabled = true;
    auditionPlayInputButton.disabled = true;
    auditionPlayOutputButton.disabled = true;
    if (previewHeadphonesButton) {
      previewHeadphonesButton.disabled = true;
    }
    auditionInputSha.textContent = "sha256: -";
    auditionOutputSha.textContent = "sha256: -";
    _renderAuditionLoudnessToggle({ disabled: true });
    _setAuditionReceipt("Loudness match unavailable: no render_execute jobs.");
    state.audition.activeStream = "";
    _stopHeadphonePreviewAnimation();
    _renderHeadphonePreviewIdle();
    _setAuditionStatus("No render_execute jobs available for audition.");
    void _refreshAuditionOverlays();
    return;
  }

  const knownJobId = state.audition.jobId;
  if (!knownJobId || !jobs.some((job) => job.job_id === knownJobId)) {
    state.audition.jobId = String(jobs[0].job_id);
  }
  const selectedJob = jobs.find((job) => job.job_id === state.audition.jobId) || jobs[0];
  state.audition.jobId = String(selectedJob.job_id);

  _setSelectOptions(
    auditionJobSelect,
    jobs.map((job) => ({ value: String(job.job_id), label: String(job.job_id) })),
    state.audition.jobId,
  );
  auditionJobSelect.disabled = false;

  const inputPointers = _pointerRows(selectedJob, "input");
  const outputPointers = _pointerRows(selectedJob, "output");
  if (state.audition.inputSlot >= inputPointers.length) {
    state.audition.inputSlot = 0;
  }
  if (state.audition.outputSlot >= outputPointers.length) {
    state.audition.outputSlot = 0;
  }

  _setSelectOptions(
    auditionInputSlotSelect,
    inputPointers.length > 0
      ? inputPointers.map((pointer, index) => ({
        value: String(index),
        label: `${index}: ${_pathTail(pointer.path)}`,
      }))
      : [{ value: "0", label: "(none)" }],
    String(state.audition.inputSlot),
  );
  _setSelectOptions(
    auditionOutputSlotSelect,
    outputPointers.length > 0
      ? outputPointers.map((pointer, index) => ({
        value: String(index),
        label: `${index}: ${_pathTail(pointer.path)}`,
      }))
      : [{ value: "0", label: "(none)" }],
    String(state.audition.outputSlot),
  );

  auditionInputSlotSelect.disabled = inputPointers.length === 0;
  auditionOutputSlotSelect.disabled = outputPointers.length === 0;
  auditionPlayInputButton.disabled = inputPointers.length === 0;
  auditionPlayOutputButton.disabled = outputPointers.length === 0;
  if (previewHeadphonesButton) {
    previewHeadphonesButton.disabled = outputPointers.length === 0;
  }

  const selectedInput = _selectedPointerOrNull(selectedJob, "input", state.audition.inputSlot);
  const selectedOutput = _selectedPointerOrNull(selectedJob, "output", state.audition.outputSlot);
  auditionInputSha.textContent = `sha256: ${selectedInput?.sha256 || "-"}`;
  auditionOutputSha.textContent = `sha256: ${selectedOutput?.sha256 || "-"}`;
  _renderAuditionLoudnessToggle({ disabled: false });
  const previewStream = state.audition.activeStream === "input" ? "input" : "output";
  _renderAuditionReceipt(selectedJob, previewStream);
  _setAuditionStatus(`Ready: ${state.audition.jobId}`);
  void _refreshAuditionOverlays();
}

function _auditionUrlFor(jobId, streamKind, slot) {
  const projectDir = normalizePath(projectDirInput?.value || "");
  if (!projectDir) {
    throw new Error("Project directory is required before auditioning.");
  }
  // Build the URL from project and job identifiers only. The server resolves
  // the pointer through render_execute.json and its allowlisted path rules.
  const query = new URLSearchParams({
    job_id: jobId,
    project_dir: projectDir,
    slot: String(slot),
    stream: streamKind,
  });
  return `/api/audio-stream?${query.toString()}`;
}

function _auditionUrl(streamKind) {
  const slot = streamKind === "input" ? state.audition.inputSlot : state.audition.outputSlot;
  return _auditionUrlFor(state.audition.jobId, streamKind, slot);
}

async function _playAudition(streamKind) {
  if (!auditionAudio) {
    return;
  }
  // Resolve preview gain before loading the next source so the browser A/B path
  // stays aligned with the selected pointers and loudness-match toggle.
  state.audition.activeStream = streamKind;
  await _applyAuditionCompensation(streamKind, _selectedAuditionJobOrNull());
  const label = streamKind === "input" ? "input" : "output";
  const url = _auditionUrl(streamKind);
  auditionAudio.src = url;
  auditionAudio.load();
  _setAuditionStatus(`Loading ${label} ${state.audition.jobId} slot ${streamKind === "input" ? state.audition.inputSlot : state.audition.outputSlot}...`);
  try {
    await auditionAudio.play();
    _setAuditionStatus(`Playing ${label} ${state.audition.jobId}`);
  } catch {
    _setAuditionStatus(`Loaded ${label}; press play on the audio controls if autoplay was blocked.`);
  }
}

async function _playHeadphonePreview() {
  await _playAudition("output");
  _setAuditionStatus(`Preview on Headphones: ${state.audition.jobId}`);
}

function _renderTimelineEntries() {
  const entries = _annotatedEventLogEntries();
  const availableJobIds = new Set();
  const availableStages = new Set();
  for (const entry of entries) {
    for (const jobId of entry._job_ids) {
      availableJobIds.add(jobId);
    }
    if (typeof entry._stage === "string" && entry._stage.trim()) {
      availableStages.add(entry._stage);
    }
  }

  const knownJobFilter = state.renderArtifacts.timelineFilterJob;
  const knownStageFilter = state.renderArtifacts.timelineFilterStage;
  const sortedJobIds = Array.from(availableJobIds).sort();
  const sortedStages = Array.from(availableStages).sort();

  // Event log contents can change on every run. Clear filters that no longer
  // exist so the browser does not hide fresh entries behind stale state.
  if (knownJobFilter && !availableJobIds.has(knownJobFilter)) {
    state.renderArtifacts.timelineFilterJob = "";
  }
  if (knownStageFilter && !availableStages.has(knownStageFilter)) {
    state.renderArtifacts.timelineFilterStage = "";
  }

  _setSelectOptions(
    timelineJobFilter,
    [
      { value: "", label: "All jobs" },
      ...sortedJobIds.map((jobId) => ({ value: jobId, label: jobId })),
    ],
    state.renderArtifacts.timelineFilterJob,
  );
  _setSelectOptions(
    timelineStageFilter,
    [
      { value: "", label: "All stages" },
      ...sortedStages.map((stage) => ({ value: stage, label: stage })),
    ],
    state.renderArtifacts.timelineFilterStage,
  );

  const filtered = entries.filter((entry) => {
    if (state.renderArtifacts.timelineFilterJob) {
      if (!entry._job_ids.includes(state.renderArtifacts.timelineFilterJob)) {
        return false;
      }
    }
    if (state.renderArtifacts.timelineFilterStage) {
      if (entry._stage !== state.renderArtifacts.timelineFilterStage) {
        return false;
      }
    }
    return true;
  });

  timelineContainer.innerHTML = "";
  if (filtered.length === 0) {
    const empty = document.createElement("p");
    empty.className = "subtle";
    empty.textContent = "No event log entries match the selected filters.";
    timelineContainer.appendChild(empty);
    return;
  }

  for (const entry of filtered) {
    const article = document.createElement("article");
    article.className = "timeline-item";

    const title = document.createElement("div");
    title.className = "timeline-item-title";
    const what = typeof entry.what === "string" ? entry.what : "(no what)";
    title.textContent = `#${entry._index} ${what}`;
    article.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "timeline-item-meta";
    const kind = typeof entry.kind === "string" ? entry.kind : "-";
    const scope = typeof entry.scope === "string" ? entry.scope : "-";
    const jobIds = entry._job_ids.length > 0 ? entry._job_ids.join(", ") : "-";
    meta.textContent = `kind=${kind}  scope=${scope}  job_id=${jobIds}  stage=${entry._stage}`;
    article.appendChild(meta);

    const details = document.createElement("pre");
    details.className = "code-block";
    details.textContent = JSON.stringify(
      {
        event_id: entry.event_id || null,
        ts_utc: entry.ts_utc || null,
        why: entry.why || "",
        codes: entry._codes,
        where: Array.isArray(entry.where) ? entry.where : [],
      },
      null,
      2,
    );
    article.appendChild(details);
    timelineContainer.appendChild(article);
  }
}

function _renderRunSummaryBlock() {
  // Keep missing report evidence explicit. A partial render session should show
  // which receipts exist instead of looking complete from browser memory alone.
  const report = _isObject(state.renderArtifacts.report) ? state.renderArtifacts.report : null;
  const jobs = Array.isArray(report?.jobs) ? report.jobs : [];
  const summaryJobs = jobs
    .filter((job) => _isObject(job))
    .map((job) => {
      const notes = Array.isArray(job.notes) ? job.notes : [];
      const refusalReason = _extractReasonFromNotes(notes);
      const refusalIssueId = _extractIssueId(refusalReason) || _extractIssueIdFromNotes(notes);
      return {
        job_id: typeof job.job_id === "string" ? job.job_id : "",
        output_count: Array.isArray(job.output_files) ? job.output_files.length : 0,
        refusal_issue_id: refusalIssueId || null,
        refusal_reason: refusalReason || null,
        status: typeof job.status === "string" ? job.status : "unknown",
      };
    });

  renderSummaryOutput.textContent = JSON.stringify(
    {
      event_log_entries: Array.isArray(state.renderArtifacts.eventLogEntries)
        ? state.renderArtifacts.eventLogEntries.length
        : 0,
      jobs: summaryJobs,
      qa_status: report?.qa_gates?.status || null,
      refusal: state.renderArtifacts.lastRefusal,
      report_present: Boolean(report),
    },
    null,
    2,
  );
}

function _renderExecutePointersBlock() {
  const execute = _isObject(state.renderArtifacts.execute) ? state.renderArtifacts.execute : null;
  if (!execute) {
    renderExecuteOutput.textContent = "render_execute.json not present for current project state.";
    return;
  }

  const executeJobs = Array.isArray(execute.jobs) ? execute.jobs : [];
  const compact = executeJobs
    .filter((job) => _isObject(job))
    .map((job) => ({
      ffmpeg_argv: Array.isArray(job.ffmpeg_commands)
        ? job.ffmpeg_commands
          .filter((command) => _isObject(command))
          .map((command) => Array.isArray(command.args) ? command.args : [])
        : [],
      ffmpeg_version: typeof job.ffmpeg_version === "string" ? job.ffmpeg_version : "",
      inputs: Array.isArray(job.inputs) ? job.inputs : [],
      job_id: typeof job.job_id === "string" ? job.job_id : "",
      outputs: Array.isArray(job.outputs) ? job.outputs : [],
    }));

  renderExecuteOutput.textContent = JSON.stringify(
    {
      jobs: compact,
      plan_sha256: execute.plan_sha256 || null,
      request_sha256: execute.request_sha256 || null,
      run_id: execute.run_id || null,
    },
    null,
    2,
  );
}

function _renderDeterminismReceipt() {
  const execute = _isObject(state.renderArtifacts.execute) ? state.renderArtifacts.execute : null;
  const outputSha = new Set();

  const executeJobs = Array.isArray(execute?.jobs) ? execute.jobs : [];
  for (const job of executeJobs) {
    if (!_isObject(job)) {
      continue;
    }
    const outputs = Array.isArray(job.outputs) ? job.outputs : [];
    for (const output of outputs) {
      if (_isObject(output) && typeof output.sha256 === "string" && output.sha256.trim()) {
        outputSha.add(output.sha256.trim());
      }
    }
  }

  // Fall back to report hashes only when execute pointers are missing. That
  // keeps the receipt visible without pretending execute evidence exists.
  if (outputSha.size === 0) {
    const reportJobs = Array.isArray(state.renderArtifacts.report?.jobs)
      ? state.renderArtifacts.report.jobs
      : [];
    for (const job of reportJobs) {
      if (!_isObject(job)) {
        continue;
      }
      const outputs = Array.isArray(job.output_files) ? job.output_files : [];
      for (const output of outputs) {
        if (_isObject(output) && typeof output.sha256 === "string" && output.sha256.trim()) {
          outputSha.add(output.sha256.trim());
        }
      }
    }
  }

  determinismOutput.textContent = JSON.stringify(
    {
      output_sha256: Array.from(outputSha).sort(),
      plan_sha: execute?.plan_sha256 || null,
      request_sha: execute?.request_sha256 || null,
      run_id: execute?.run_id || null,
    },
    null,
    2,
  );
}

function _nonEmptyString(value) {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed || null;
}

function _numberOrNull(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function _collectOutputSha256() {
  const outputSha = new Set();

  const executeJobs = Array.isArray(state.renderArtifacts.execute?.jobs)
    ? state.renderArtifacts.execute.jobs
    : [];
  for (const job of executeJobs) {
    if (!_isObject(job)) {
      continue;
    }
    const outputs = Array.isArray(job.outputs) ? job.outputs : [];
    for (const output of outputs) {
      const shaValue = _isObject(output) ? _nonEmptyString(output.sha256) : null;
      if (shaValue) {
        outputSha.add(shaValue);
      }
    }
  }

  const qaJobs = Array.isArray(state.renderArtifacts.qa?.jobs)
    ? state.renderArtifacts.qa.jobs
    : [];
  for (const job of qaJobs) {
    if (!_isObject(job)) {
      continue;
    }
    const outputs = Array.isArray(job.outputs) ? job.outputs : [];
    for (const output of outputs) {
      const shaValue = _isObject(output) ? _nonEmptyString(output.sha256) : null;
      if (shaValue) {
        outputSha.add(shaValue);
      }
    }
  }

  if (outputSha.size === 0) {
    const reportJobs = Array.isArray(state.renderArtifacts.report?.jobs)
      ? state.renderArtifacts.report.jobs
      : [];
    for (const job of reportJobs) {
      if (!_isObject(job)) {
        continue;
      }
      const outputs = Array.isArray(job.output_files) ? job.output_files : [];
      for (const output of outputs) {
        const shaValue = _isObject(output) ? _nonEmptyString(output.sha256) : null;
        if (shaValue) {
          outputSha.add(shaValue);
        }
      }
    }
  }

  return Array.from(outputSha).sort();
}

function _safeRunMetersSummary(qaPayload) {
  const meters = [];
  const jobs = Array.isArray(qaPayload?.jobs) ? qaPayload.jobs : [];
  for (const job of jobs) {
    if (!_isObject(job)) {
      continue;
    }
    const jobId = _nonEmptyString(job.job_id) || "";
    const outputs = Array.isArray(job.outputs) ? job.outputs : [];
    for (const output of outputs) {
      if (!_isObject(output)) {
        continue;
      }
      const metrics = _isObject(output.metrics) ? output.metrics : {};
      meters.push({
        correlation_lr: _numberOrNull(metrics.correlation_lr),
        integrated_lufs: _numberOrNull(metrics.integrated_lufs),
        job_id: jobId,
        loudness_range_lu: _numberOrNull(metrics.loudness_range_lu),
        output_path: _nonEmptyString(output.path) || "",
        peak_dbfs: _numberOrNull(metrics.peak_dbfs),
        rms_dbfs: _numberOrNull(metrics.rms_dbfs),
        true_peak_dbtp: _numberOrNull(metrics.true_peak_dbtp),
      });
    }
  }
  meters.sort((left, right) => {
    if (left.job_id !== right.job_id) {
      return left.job_id.localeCompare(right.job_id);
    }
    return left.output_path.localeCompare(right.output_path);
  });
  return meters;
}

function _safeRunQaSummary(qaPayload) {
  const issueCounts = { error: 0, warn: 0, info: 0 };
  const issues = [];
  const issueIds = new Set();
  const jobsWithIssues = new Set();
  const rows = Array.isArray(qaPayload?.issues) ? qaPayload.issues : [];

  for (const row of rows) {
    if (!_isObject(row)) {
      continue;
    }
    const severity = _nonEmptyString(row.severity) || "info";
    if (severity === "error" || severity === "warn" || severity === "info") {
      issueCounts[severity] += 1;
    }
    const issueId = _nonEmptyString(row.issue_id) || "";
    const jobId = _nonEmptyString(row.job_id) || "";
    const issue = {
      issue_id: issueId || null,
      job_id: jobId || null,
      metric: _nonEmptyString(row.metric) || null,
      output_path: _nonEmptyString(row.output_path) || null,
      severity,
      threshold: _numberOrNull(row.threshold),
      value: _numberOrNull(row.value),
    };
    issues.push(issue);
    if (issueId) {
      issueIds.add(issueId);
    }
    if (jobId) {
      jobsWithIssues.add(jobId);
    }
  }

  const severityRank = { error: 0, warn: 1, info: 2 };
  issues.sort((left, right) => {
    const leftRank = severityRank[left.severity] ?? 3;
    const rightRank = severityRank[right.severity] ?? 3;
    if (leftRank !== rightRank) {
      return leftRank - rightRank;
    }
    const leftIssueId = left.issue_id || "";
    const rightIssueId = right.issue_id || "";
    if (leftIssueId !== rightIssueId) {
      return leftIssueId.localeCompare(rightIssueId);
    }
    const leftJobId = left.job_id || "";
    const rightJobId = right.job_id || "";
    if (leftJobId !== rightJobId) {
      return leftJobId.localeCompare(rightJobId);
    }
    const leftPath = left.output_path || "";
    const rightPath = right.output_path || "";
    if (leftPath !== rightPath) {
      return leftPath.localeCompare(rightPath);
    }
    const leftMetric = left.metric || "";
    const rightMetric = right.metric || "";
    return leftMetric.localeCompare(rightMetric);
  });

  return {
    issue_count_total: issues.length,
    issue_counts: issueCounts,
    issue_ids: Array.from(issueIds).sort(),
    issues,
    jobs_with_issues: Array.from(jobsWithIssues).sort(),
  };
}

function _buildSafeRunReceiptPayload() {
  // Merge execute and QA receipts into one browser copy payload. Missing files
  // stay visible as nulls or empty lists instead of implied success.
  const execute = _isObject(state.renderArtifacts.execute) ? state.renderArtifacts.execute : null;
  const qa = _isObject(state.renderArtifacts.qa) ? state.renderArtifacts.qa : null;
  const runId = _nonEmptyString(execute?.run_id) || _nonEmptyString(qa?.run_id);

  return {
    hashes: {
      output_sha256: _collectOutputSha256(),
      plan_sha256: _nonEmptyString(execute?.plan_sha256) || _nonEmptyString(qa?.plan_sha256),
      report_sha256: _nonEmptyString(qa?.report_sha256),
      request_sha256: _nonEmptyString(execute?.request_sha256) || _nonEmptyString(qa?.request_sha256),
    },
    meters: _safeRunMetersSummary(qa),
    qa_summary: _safeRunQaSummary(qa),
    run_id: runId,
  };
}

function _renderSafeRunReceipt() {
  if (!safeRunReceiptOutput) {
    return;
  }
  safeRunReceiptOutput.textContent = JSON.stringify(_buildSafeRunReceiptPayload(), null, 2);
}

async function _copySafeRunReceipt() {
  const receiptText = JSON.stringify(_buildSafeRunReceiptPayload(), null, 2);
  if (
    typeof navigator !== "undefined"
    && navigator.clipboard
    && typeof navigator.clipboard.writeText === "function"
  ) {
    await navigator.clipboard.writeText(receiptText);
    return;
  }

  const fallbackInput = document.createElement("textarea");
  fallbackInput.value = receiptText;
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
    throw new Error("Clipboard write is unavailable in this browser context.");
  }
}

function _renderRefusalBlock() {
  if (state.renderArtifacts.lastRefusal) {
    renderRefusalOutput.textContent = JSON.stringify(state.renderArtifacts.lastRefusal, null, 2);
    return;
  }
  renderRefusalOutput.textContent = "No refusal captured in this session.";
}

function renderRenderArtifactsViewer() {
  _renderRunSummaryBlock();
  _renderDeterminismReceipt();
  _renderSafeRunReceipt();
  _renderRefusalBlock();
  _renderExecutePointersBlock();
  _renderAuditionPanel();
  _renderTimelineEntries();
}

async function refreshRenderArtifactsFromProjectShow(projectShow) {
  // Project.show owns which artifact files exist for this project state. Load
  // only the receipt paths it reports instead of scanning the renders folder.
  const reportPath = _artifactPathFromProjectShow(projectShow, "renders/render_report.json");
  const executePath = _artifactPathFromProjectShow(projectShow, "renders/render_execute.json");
  const eventLogPath = _artifactPathFromProjectShow(projectShow, "renders/event_log.jsonl");
  const qaPath = _artifactPathFromProjectShow(projectShow, "renders/render_qa.json");

  let reportPayload = null;
  let executePayload = null;
  let eventLogEntries = [];
  let qaPayload = null;

  if (reportPath) {
    const reportArtifact = await loadRenderArtifact(reportPath);
    if (_isObject(reportArtifact.artifact)) {
      reportPayload = reportArtifact.artifact;
    }
  }
  if (executePath) {
    const executeArtifact = await loadRenderArtifact(executePath);
    if (_isObject(executeArtifact.artifact)) {
      executePayload = executeArtifact.artifact;
    }
  }
  if (eventLogPath) {
    const eventLogArtifact = await loadRenderArtifact(eventLogPath);
    if (Array.isArray(eventLogArtifact.artifact)) {
      eventLogEntries = eventLogArtifact.artifact;
    }
  }
  if (qaPath) {
    const qaArtifact = await loadRenderArtifact(qaPath);
    if (_isObject(qaArtifact.artifact)) {
      qaPayload = qaArtifact.artifact;
    }
  }

  state.renderArtifacts = {
    ...state.renderArtifacts,
    eventLogEntries,
    execute: executePayload,
    qa: qaPayload,
    report: reportPayload,
  };
  _renderDashboardVisuals();
  renderRenderArtifactsViewer();
}

function _scenePreviewLayoutOptions(preview) {
  const rawRows = Array.isArray(preview?.layout_options) ? preview.layout_options : [];
  const rows = rawRows
    .filter((item) => _isObject(item))
    .map((item) => ({
      label: typeof item.label === "string" && item.label.trim()
        ? item.label.trim()
        : (typeof item.layout_id === "string" ? item.layout_id : ""),
      layout_id: typeof item.layout_id === "string" ? item.layout_id.trim() : "",
      speakers: Array.isArray(item.speakers)
        ? item.speakers.filter((speaker) => _isObject(speaker))
        : [],
    }))
    .filter((item) => item.layout_id && item.speakers.length > 0);
  rows.sort((left, right) => left.layout_id.localeCompare(right.layout_id));
  return rows;
}

function _scenePreviewPreferredLayoutId(layoutRows, preview) {
  const available = new Set(layoutRows.map((row) => row.layout_id));
  // Prefer render_request target layouts first so the preview follows the last
  // saved backend intent before falling back to scene-preview defaults.
  for (const layoutId of state.renderRequestIntent.target_layout_ids) {
    if (available.has(layoutId)) {
      return layoutId;
    }
  }
  const defaultLayoutId = typeof preview?.default_layout_id === "string"
    ? preview.default_layout_id.trim()
    : "";
  if (defaultLayoutId && available.has(defaultLayoutId)) {
    return defaultLayoutId;
  }
  return layoutRows.length > 0 ? layoutRows[0].layout_id : "";
}

function _ensureSceneLayoutSelection(layoutRows, preview) {
  if (layoutRows.length === 0) {
    state.sceneLayoutId = "";
    return "";
  }
  if (layoutRows.some((row) => row.layout_id === state.sceneLayoutId)) {
    return state.sceneLayoutId;
  }
  const preferred = _scenePreviewPreferredLayoutId(layoutRows, preview);
  state.sceneLayoutId = preferred;
  return preferred;
}

function _svgNode(tagName, attributes = {}) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tagName);
  for (const [key, value] of Object.entries(attributes)) {
    node.setAttribute(key, String(value));
  }
  return node;
}

function _pointFromAzimuth(azimuthDeg, radius, centerX, centerY) {
  const radians = (Number.isFinite(azimuthDeg) ? azimuthDeg : 0) * (Math.PI / 180);
  const x = centerX + (Math.sin(radians) * radius);
  const y = centerY - (Math.cos(radians) * radius);
  return { x, y };
}

function _sceneObjectPoint(row, centerX, centerY) {
  const azimuth = Number(row.azimuth_deg);
  const depth = Number(row.depth);
  const safeDepth = Number.isFinite(depth) ? Math.max(0, Math.min(1, depth)) : 0.5;
  const radius = 58 + (safeDepth * 185);
  return _pointFromAzimuth(azimuth, radius, centerX, centerY);
}

function _sceneConfidenceColor(confidence) {
  const safe = Number.isFinite(confidence) ? Math.max(0, Math.min(1, confidence)) : 0;
  const hue = 12 + (safe * 128);
  return `hsl(${hue.toFixed(1)} 72% 42%)`;
}

function _setScenePreviewStageEmpty(message = "") {
  if (!scenePreviewStageEmpty) {
    return;
  }
  const text = typeof message === "string" ? message.trim() : "";
  scenePreviewStageEmpty.textContent = text;
  scenePreviewStageEmpty.classList.toggle("visible", Boolean(text));
}

function _scenePerspectiveSettings(perspective) {
  switch (perspective) {
    case "on_stage":
      return { radialScale: 0.95, rotationDeg: 180, xScale: 1.0, yScale: 1.0 };
    case "in_band":
      return { radialScale: 0.82, rotationDeg: 0, xScale: 1.12, yScale: 0.86 };
    case "in_orchestra":
      return { radialScale: 0.88, rotationDeg: 0, xScale: 1.22, yScale: 0.92 };
    default:
      return { radialScale: 1.0, rotationDeg: 0, xScale: 1.0, yScale: 1.0 };
  }
}

function _transformStagePoint(point, centerX, centerY, perspective) {
  const settings = _scenePerspectiveSettings(perspective);
  const dx = point.x - centerX;
  const dy = point.y - centerY;
  const radians = settings.rotationDeg * (Math.PI / 180);
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  const rotatedX = (dx * cos) - (dy * sin);
  const rotatedY = (dx * sin) + (dy * cos);
  return {
    x: centerX + (rotatedX * settings.xScale * settings.radialScale),
    y: centerY + (rotatedY * settings.yScale * settings.radialScale),
  };
}

function _renderDashboardMeterCanvas(rows) {
  if (!dashboardMeterCanvas) {
    return;
  }
  const visibleRows = rows.slice(0, 12);
  if (visibleRows.length === 0) {
    _drawEmptyCanvasState(dashboardMeterCanvas, "No peak / RMS / true-peak / LUFS data.", 300);
    return;
  }
  dashboardMeterCanvas.setAttribute("height", String(Math.max(260, 90 + (visibleRows.length * 34))));
  const frame = _prepareCanvasFrame(dashboardMeterCanvas, 300);
  if (!frame) {
    return;
  }
  const { ctx, width, height } = frame;
  ctx.clearRect(0, 0, width, height);
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "#0c1217");
  gradient.addColorStop(1, "#17242b");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = "rgba(236, 244, 248, 0.92)";
  ctx.font = '13px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  ctx.textBaseline = "top";
  ctx.fillText("Peak / RMS / TP", 16, 14);
  ctx.fillText("LUFS", width - 128, 14);

  const labelWidth = 116;
  const valuesWidth = 122;
  const trackGap = 18;
  const peakTrackX = 18 + labelWidth;
  const lufsTrackWidth = 78;
  const lufsTrackX = width - valuesWidth - lufsTrackWidth - 22;
  const peakTrackWidth = Math.max(80, lufsTrackX - peakTrackX - trackGap);
  const startY = 42;
  const rowHeight = 34;

  for (let index = 0; index < visibleRows.length; index += 1) {
    const row = visibleRows[index];
    const top = startY + (index * rowHeight);
    const peakY = top + 6;
    const lufsY = top + 19;
    const trackHeight = 8;
    const label = row.label.length > 16 ? `${row.label.slice(0, 13)}...` : row.label;

    ctx.fillStyle = index % 2 === 0 ? "rgba(255, 255, 255, 0.025)" : "rgba(255, 255, 255, 0.05)";
    ctx.fillRect(10, top - 2, width - 20, rowHeight - 2);

    ctx.fillStyle = "#d8e7ee";
    ctx.font = '12px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
    ctx.fillText(label, 16, top + 2);

    ctx.fillStyle = "rgba(150, 172, 185, 0.18)";
    ctx.fillRect(peakTrackX, peakY, peakTrackWidth, trackHeight);
    ctx.fillRect(lufsTrackX, lufsY, lufsTrackWidth, trackHeight);

    const peakX = _valuePosition(row.peak_dbfs, -60, 3, peakTrackWidth);
    const rmsX = _valuePosition(row.rms_dbfs, -60, 3, peakTrackWidth);
    const tpX = _valuePosition(row.true_peak_dbtp, -60, 3, peakTrackWidth);
    const lufsX = _valuePosition(row.integrated_lufs, -36, -6, lufsTrackWidth);

    if (peakX !== null) {
      const peakGradient = ctx.createLinearGradient(peakTrackX, 0, peakTrackX + peakTrackWidth, 0);
      peakGradient.addColorStop(0, "#346b7a");
      peakGradient.addColorStop(0.6, "#d59042");
      peakGradient.addColorStop(1, "#e16041");
      ctx.fillStyle = peakGradient;
      ctx.fillRect(peakTrackX, peakY, peakX, trackHeight);
    }
    if (rmsX !== null) {
      ctx.fillStyle = "rgba(82, 189, 184, 0.95)";
      ctx.fillRect(peakTrackX, peakY + 1, Math.max(0, rmsX), trackHeight - 2);
    }
    if (tpX !== null) {
      ctx.strokeStyle = "#f4f6f8";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(peakTrackX + tpX, peakY - 2);
      ctx.lineTo(peakTrackX + tpX, peakY + trackHeight + 2);
      ctx.stroke();
    }
    if (lufsX !== null) {
      ctx.fillStyle = "#f7c96d";
      ctx.beginPath();
      ctx.arc(lufsTrackX + lufsX, lufsY + (trackHeight * 0.5), 4.2, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.fillStyle = "#a8c0cc";
    ctx.font = '11px Consolas, "Courier New", monospace';
    ctx.fillText(
      [
        _formatMetricValue(row.peak_dbfs, "", 1),
        _formatMetricValue(row.rms_dbfs, "", 1),
        _formatMetricValue(row.true_peak_dbtp, "", 1),
        _formatMetricValue(row.integrated_lufs, "", 1),
      ].join(" / "),
      width - valuesWidth,
      top + 1,
    );
  }
}

function _renderDashboardDistributionCanvas(rows, histogram, distribution, selectedLayout) {
  if (!dashboardDistributionCanvas) {
    return;
  }
  if (histogram.bins.length === 0 && distribution.length === 0) {
    _drawEmptyCanvasState(
      dashboardDistributionCanvas,
      "Build GUI or render QA artifacts to inspect distribution.",
      220,
    );
    return;
  }
  const frame = _prepareCanvasFrame(dashboardDistributionCanvas, 220);
  if (!frame) {
    return;
  }
  const { ctx, width, height } = frame;
  ctx.clearRect(0, 0, width, height);
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "#0b1115");
  gradient.addColorStop(1, "#142127");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  const topPanelHeight = distribution.length > 0 ? Math.floor(height * 0.48) : height - 20;
  const bottomPanelTop = topPanelHeight + 18;

  if (histogram.bins.length > 0) {
    ctx.fillStyle = "rgba(235, 244, 248, 0.92)";
    ctx.font = '12px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
    ctx.fillText("LUFS spread", 14, 14);

    const maxCount = Math.max(1, ...histogram.bins.map((row) => row.count));
    const chartX = 14;
    const chartY = 34;
    const chartWidth = width - 28;
    const chartHeight = Math.max(40, topPanelHeight - 48);
    const barWidth = chartWidth / histogram.bins.length;
    histogram.bins.forEach((bin, index) => {
      const ratio = bin.count / maxCount;
      const barHeight = ratio * chartHeight;
      const x = chartX + (index * barWidth) + 2;
      const y = chartY + chartHeight - barHeight;
      ctx.fillStyle = "rgba(84, 171, 196, 0.22)";
      ctx.fillRect(x, chartY, Math.max(3, barWidth - 4), chartHeight);
      ctx.fillStyle = "#d79b48";
      ctx.fillRect(x, y, Math.max(3, barWidth - 4), barHeight);
    });
  }

  if (distribution.length > 0) {
    ctx.fillStyle = "rgba(235, 244, 248, 0.92)";
    ctx.font = '12px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
    ctx.fillText(
      `Scene distribution${selectedLayout ? ` · ${selectedLayout.layout_id}` : ""}`,
      14,
      bottomPanelTop,
    );
    const maxValue = Math.max(0.5, ...distribution.map((row) => row.value));
    const barX = 110;
    const barWidth = width - barX - 18;
    distribution.forEach((row, index) => {
      const y = bottomPanelTop + 18 + (index * 24);
      const ratio = row.value / maxValue;
      ctx.fillStyle = "#c8d6dd";
      ctx.font = '11px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
      ctx.fillText(row.label, 14, y + 3);
      ctx.fillStyle = "rgba(115, 142, 156, 0.18)";
      ctx.fillRect(barX, y, barWidth, 10);
      ctx.fillStyle = row.id === "bed" ? "#d99044" : "#57b8b1";
      ctx.fillRect(barX, y, barWidth * ratio, 10);
      ctx.fillStyle = "#9eb5c1";
      ctx.fillText(String(row.count), barX + barWidth + 4, y + 2);
    });
  }
}

function _renderDashboardVisuals() {
  const report = _isObject(state.uiBundle?.report) ? state.uiBundle.report : null;
  const reportRows = buildMeterRowsFromReport(report);
  const qaRows = buildMeterRowsFromRenderQa(state.renderArtifacts.qa);
  const activeRows = qaRows.length > 0 ? qaRows : reportRows;
  const summary = buildMeterSummary(activeRows);
  const histogram = buildMeterHistogram(activeRows, "integrated_lufs", {
    bins: 10,
    max: -6,
    min: -36,
  });
  const preview = _isObject(state.scenePreview) ? state.scenePreview : null;
  const layoutRows = _scenePreviewLayoutOptions(preview);
  const selectedLayoutId = _ensureSceneLayoutSelection(layoutRows, preview);
  const selectedLayout = layoutRows.find((row) => row.layout_id === selectedLayoutId) || null;
  const distribution = buildSceneDistribution(preview, selectedLayoutId);

  _renderDashboardMeterCanvas(activeRows);
  _renderDashboardDistributionCanvas(activeRows, histogram, distribution, selectedLayout);

  _renderSummaryChips(
    dashboardMeterSummary,
    [
      {
        label: "Source",
        value: qaRows.length > 0 ? "Render QA" : (reportRows.length > 0 ? "Scan Report" : "Unavailable"),
      },
      {
        label: "Rows",
        value: activeRows.length > 0 ? String(activeRows.length) : "0",
      },
      {
        label: "Peak Max",
        value: _formatMetricValue(summary.peak_max_dbfs, " dBFS"),
      },
      {
        label: "RMS Median",
        value: _formatMetricValue(summary.rms_median_dbfs, " dBFS"),
      },
      {
        label: "True Peak",
        value: _formatMetricValue(summary.true_peak_max_dbtp, " dBTP"),
      },
      {
        label: "LUFS Span",
        value: _formatMetricValue(summary.lufs_span, " LU"),
      },
    ],
  );

  _renderSummaryChips(
    dashboardDistributionSummary,
    [
      {
        label: "Layout",
        value: selectedLayout ? selectedLayout.layout_id : "n/a",
      },
      {
        label: "Perspective",
        value: state.sceneLocks.perspective || "audience",
      },
      {
        label: "Objects",
        value: _isObject(preview?.totals) ? String(preview.totals.object_count ?? 0) : "0",
      },
      {
        label: "Warnings",
        value: Array.isArray(preview?.warnings) ? String(preview.warnings.length) : "0",
      },
      {
        label: "Bed",
        value: _formatMetricValue(Number(preview?.bed_energy) * 100, "%", 0),
      },
      {
        label: "LUFS Bins",
        value: histogram.bins.length > 0 ? String(histogram.bins.length) : "0",
      },
    ],
  );
}

function _renderScenePreviewWarnings(preview) {
  if (!scenePreviewWarnings) {
    return;
  }
  scenePreviewWarnings.innerHTML = "";
  const warnings = Array.isArray(preview?.warnings)
    ? preview.warnings.filter((item) => _isObject(item))
    : [];
  if (warnings.length === 0) {
    const okChip = document.createElement("div");
    okChip.className = "scene-preview-warning";
    okChip.textContent = "No confidence or lock warnings in scene intent.";
    scenePreviewWarnings.appendChild(okChip);
    return;
  }
  warnings.sort((left, right) => {
    const leftId = typeof left.warning_id === "string" ? left.warning_id : "";
    const rightId = typeof right.warning_id === "string" ? right.warning_id : "";
    return leftId.localeCompare(rightId);
  });
  for (const warning of warnings) {
    const warningId = typeof warning.warning_id === "string" ? warning.warning_id : "WARN";
    const count = Number.isFinite(warning.count) ? Number(warning.count) : 0;
    const message = typeof warning.message === "string" ? warning.message : "";
    const chip = document.createElement("div");
    chip.className = "scene-preview-warning";
    chip.textContent = `${warningId} (${count}) · ${message}`;
    scenePreviewWarnings.appendChild(chip);
  }
}

function _renderScenePreviewStage(preview, selectedLayout) {
  if (!scenePreviewStageCanvas) {
    return;
  }
  if (!_isObject(preview) || !_isObject(selectedLayout)) {
    _setScenePreviewStageEmpty("Scene preview is not available for the current project state.");
    _drawEmptyCanvasState(
      scenePreviewStageCanvas,
      "Scene preview is not available for the current project state.",
      320,
    );
    return;
  }
  _setScenePreviewStageEmpty("");
  const frame = _prepareCanvasFrame(scenePreviewStageCanvas, 320);
  if (!frame) {
    return;
  }
  const { ctx, width, height } = frame;
  const centerX = 450;
  const centerY = 280;
  const speakerRadius = 228;
  const scaleX = width / 900;
  const scaleY = height / 520;
  const perspective = state.sceneLocks.perspective || "audience";

  ctx.clearRect(0, 0, width, height);
  const gradient = ctx.createLinearGradient(0, 0, 0, height);
  gradient.addColorStop(0, "#f7fbfd");
  gradient.addColorStop(1, "#e8eff4");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "#cfdae2";
  ctx.lineWidth = 1;
  ctx.strokeRect(1, 1, width - 2, height - 2);

  ctx.save();
  ctx.scale(scaleX, scaleY);
  ctx.strokeStyle = "#b8c8d6";
  ctx.lineWidth = 2;
  ctx.setLineDash([8, 8]);
  ctx.beginPath();
  ctx.arc(centerX, centerY, speakerRadius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.strokeStyle = "#d1dde6";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(centerX, centerY - speakerRadius - 20);
  ctx.lineTo(centerX, centerY + speakerRadius + 20);
  ctx.moveTo(centerX - speakerRadius - 20, centerY);
  ctx.lineTo(centerX + speakerRadius + 20, centerY);
  ctx.stroke();

  const bedEnergy = Number(preview.bed_energy);
  const safeBedEnergy = Number.isFinite(bedEnergy) ? Math.max(0, Math.min(1, bedEnergy)) : 0;
  const bedRingRadius = 96 + (safeBedEnergy * 118);
  ctx.strokeStyle = "#c28332";
  ctx.lineWidth = 10 + (safeBedEnergy * 11);
  ctx.globalAlpha = 0.2 + (safeBedEnergy * 0.65);
  ctx.beginPath();
  ctx.arc(centerX, centerY, bedRingRadius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#8a4a17";
  ctx.font = '700 13px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  ctx.textAlign = "center";
  ctx.fillText(`Bed halo ${(safeBedEnergy * 100).toFixed(0)}%`, centerX, centerY + 4);

  const speakers = Array.isArray(selectedLayout.speakers) ? selectedLayout.speakers : [];
  for (const speaker of speakers) {
    const azimuth = Number(speaker.azimuth_deg);
    const elevation = Number(speaker.elevation_deg);
    const isHeight = Number.isFinite(elevation) && elevation > 0;
    const name = typeof speaker.name === "string" ? speaker.name : "?";
    const point = _transformStagePoint(
      _pointFromAzimuth(azimuth, speakerRadius, centerX, centerY),
      centerX,
      centerY,
      perspective,
    );
    const fill = name === "LFE"
      ? "#b94a34"
      : (isHeight ? "#2e7f9f" : "#4f6574");
    ctx.fillStyle = fill;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.3;
    ctx.beginPath();
    ctx.arc(point.x, point.y, isHeight ? 5 : 4.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "#50606e";
    ctx.font = '10.5px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
    ctx.fillText(name, point.x, point.y - 10);
  }

  const objectRows = Array.isArray(preview.objects) ? preview.objects : [];
  for (const row of objectRows) {
    if (!_isObject(row)) {
      continue;
    }
    const point = _transformStagePoint(
      _sceneObjectPoint(row, centerX, centerY),
      centerX,
      centerY,
      perspective,
    );
    const confidence = Number(row.confidence);
    const safeConfidence = Number.isFinite(confidence)
      ? Math.max(0, Math.min(1, confidence))
      : 0;
    const dotRadius = 4.5 + (safeConfidence * 4.5);
    const color = _sceneConfidenceColor(safeConfidence);
    ctx.strokeStyle = "#d4dee6";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(centerX, centerY);
    ctx.lineTo(point.x, point.y);
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 1.5;
    ctx.setLineDash(row.inferred_position === true ? [2, 2] : []);
    ctx.beginPath();
    ctx.arc(point.x, point.y, dotRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.setLineDash([]);
    const labelRaw = typeof row.label === "string" && row.label.trim()
      ? row.label.trim()
      : (typeof row.object_id === "string" ? row.object_id : "Object");
    const label = labelRaw.length > 16 ? `${labelRaw.slice(0, 13)}...` : labelRaw;
    ctx.fillStyle = "#33424f";
    ctx.font = '11px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
    ctx.textAlign = "left";
    ctx.fillText(`${label} ${(safeConfidence * 100).toFixed(0)}%`, point.x + 8, point.y - 8);
  }

  ctx.fillStyle = "#2a3a47";
  ctx.font = '700 15px "Segoe UI", "Helvetica Neue", Arial, sans-serif';
  ctx.textAlign = "left";
  ctx.fillText(
    `Stage view · ${selectedLayout.label} (${selectedLayout.layout_id}) · ${perspective}`,
    18,
    28,
  );
  ctx.restore();
}

function _renderScenePreview() {
  const preview = _isObject(state.scenePreview) ? state.scenePreview : null;
  const layoutRows = _scenePreviewLayoutOptions(preview);
  const selectedLayoutId = _ensureSceneLayoutSelection(layoutRows, preview);

  if (sceneLayoutSelect) {
    if (layoutRows.length === 0) {
      _setSelectOptions(sceneLayoutSelect, [{ value: "", label: "No scene preview" }], "");
      sceneLayoutSelect.disabled = true;
    } else {
      _setSelectOptions(
        sceneLayoutSelect,
        layoutRows.map((row) => ({
          value: row.layout_id,
          label: `${row.label} (${row.layout_id})`,
        })),
        selectedLayoutId,
      );
      sceneLayoutSelect.disabled = false;
    }
  }

  const selectedLayout = layoutRows.find((row) => row.layout_id === selectedLayoutId) || null;
  _renderScenePreviewWarnings(preview);
  _renderScenePreviewStage(preview, selectedLayout);

  if (!scenePreviewOutput) {
    return;
  }
  // Keep preview absence explicit. The canvas should not invent a stage layout
  // when the backend did not ship scene-preview evidence.
  if (!_isObject(preview)) {
    scenePreviewOutput.textContent = "Scene preview unavailable. Build GUI payload with a scene.json pointer.";
    return;
  }
  const totals = _isObject(preview.totals) ? preview.totals : {};
  const warningIds = Array.isArray(preview.warnings)
    ? preview.warnings
      .filter((item) => _isObject(item) && typeof item.warning_id === "string")
      .map((item) => item.warning_id)
      .sort()
    : [];
  scenePreviewOutput.textContent = JSON.stringify(
    {
      bed_energy: preview.bed_energy ?? null,
      layout_id: selectedLayoutId || null,
      object_count: Number.isFinite(totals.object_count) ? totals.object_count : 0,
      bed_count: Number.isFinite(totals.bed_count) ? totals.bed_count : 0,
      scene_lock_count: Number.isFinite(totals.scene_lock_count) ? totals.scene_lock_count : 0,
      total_lock_count: Number.isFinite(totals.total_lock_count) ? totals.total_lock_count : 0,
      warning_ids: warningIds,
    },
    null,
    2,
  );
}

function _defaultScenePerspectiveValues() {
  return ["audience", "on_stage", "in_band", "in_orchestra"];
}

function _resetSceneLocksState() {
  state.sceneLocks = {
    objects: [],
    overridesCount: 0,
    perspective: "audience",
    perspectiveValues: _defaultScenePerspectiveValues(),
    roleOptions: [],
    sceneLocksPath: "",
    scenePath: "",
  };
}

function _normalizeSceneLockRoleOptions(rows) {
  const normalized = Array.isArray(rows)
    ? rows
      .filter((item) => _isObject(item))
      .map((item) => ({
        label: typeof item.label === "string" && item.label.trim()
          ? item.label.trim()
          : (typeof item.role_id === "string" ? item.role_id.trim() : ""),
        roleId: typeof item.role_id === "string" ? item.role_id.trim() : "",
      }))
      .filter((item) => item.roleId)
    : [];
  normalized.sort((left, right) => left.roleId.localeCompare(right.roleId));
  return normalized;
}

function _normalizeSceneLockRows(rows) {
  const normalized = [];
  const sourceRows = Array.isArray(rows) ? rows : [];
  for (const item of sourceRows) {
    if (!_isObject(item)) {
      continue;
    }
    const stemId = typeof item.stem_id === "string" ? item.stem_id.trim() : "";
    if (!stemId) {
      continue;
    }
    const objectId = typeof item.object_id === "string" && item.object_id.trim()
      ? item.object_id.trim()
      : `OBJ.${stemId}`;
    const label = typeof item.label === "string" && item.label.trim()
      ? item.label.trim()
      : objectId;
    const inferredRoleId = typeof item.inferred_role_id === "string" && item.inferred_role_id.trim()
      ? item.inferred_role_id.trim()
      : "";
    const roleOverrideId = typeof item.role_override_id === "string" && item.role_override_id.trim()
      ? item.role_override_id.trim()
      : "";
    const surroundOverride = _isFiniteNumber(item.surround_cap_override)
      ? _clampUnit(item.surround_cap_override, 1)
      : null;
    const heightOverride = _isFiniteNumber(item.height_cap_override)
      ? _clampUnit(item.height_cap_override, 1)
      : null;
    const frontOnlyOverride = item.front_only_override === true
      || (surroundOverride !== null && surroundOverride <= 0);
    normalized.push({
      confidence: _clampUnit(item.confidence, 0),
      editFrontOnly: frontOnlyOverride,
      editHeightCap: heightOverride === null ? 1 : heightOverride,
      editRoleId: roleOverrideId,
      editSurroundCap: frontOnlyOverride ? 0 : (surroundOverride === null ? 1 : surroundOverride),
      inferredRoleId,
      label,
      objectId,
      stemId,
    });
  }
  normalized.sort((left, right) => {
    if (left.objectId !== right.objectId) {
      return left.objectId.localeCompare(right.objectId);
    }
    return left.stemId.localeCompare(right.stemId);
  });
  return normalized;
}

function _hydrateSceneLocksInspect(payload) {
  const perspectiveValuesRaw = Array.isArray(payload?.perspective_values)
    ? payload.perspective_values
    : _defaultScenePerspectiveValues();
  const perspectiveValues = perspectiveValuesRaw
    .filter((item) => typeof item === "string" && item.trim())
    .map((item) => item.trim());
  const perspective = typeof payload?.perspective === "string" ? payload.perspective.trim() : "audience";
  state.sceneLocks = {
    objects: _normalizeSceneLockRows(payload?.objects),
    overridesCount: Number.isFinite(payload?.overrides_count) ? Number(payload.overrides_count) : 0,
    perspective: perspectiveValues.includes(perspective) ? perspective : (perspectiveValues[0] || "audience"),
    perspectiveValues: perspectiveValues.length > 0 ? perspectiveValues : _defaultScenePerspectiveValues(),
    roleOptions: _normalizeSceneLockRoleOptions(payload?.role_options),
    sceneLocksPath: typeof payload?.scene_locks_path === "string" ? payload.scene_locks_path : "",
    scenePath: typeof payload?.scene_path === "string" ? payload.scene_path : "",
  };
}

function _updateSceneLockRow(stemId, patch) {
  // Row edits stay local until saveSceneLocks sends them back through the
  // backend. Re-render the editor, but do not treat this as persisted state.
  const nextRows = state.sceneLocks.objects.map((row) => {
    if (row.stemId !== stemId) {
      return row;
    }
    const next = { ...row, ...patch };
    next.editRoleId = typeof next.editRoleId === "string" ? next.editRoleId.trim() : "";
    next.editFrontOnly = next.editFrontOnly === true;
    next.editSurroundCap = _clampUnit(next.editSurroundCap, 1);
    next.editHeightCap = _clampUnit(next.editHeightCap, 1);
    if (next.editFrontOnly) {
      next.editSurroundCap = 0;
    }
    return next;
  });
  state.sceneLocks = {
    ...state.sceneLocks,
    objects: nextRows,
  };
  _renderSceneLocksEditor();
}

function _renderSceneLocksEditor() {
  if (!sceneLocksContainer) {
    return;
  }
  if (sceneLocksSaveButton) {
    sceneLocksSaveButton.disabled = !Array.isArray(state.sceneLocks.objects)
      || state.sceneLocks.objects.length === 0;
  }

  if (scenePerspectiveSelect) {
    _setSelectOptions(
      scenePerspectiveSelect,
      state.sceneLocks.perspectiveValues.map((item) => ({
        value: item,
        label: item,
      })),
      state.sceneLocks.perspective,
    );
    scenePerspectiveSelect.disabled = false;
  }

  sceneLocksContainer.innerHTML = "";
  if (!Array.isArray(state.sceneLocks.objects) || state.sceneLocks.objects.length === 0) {
    const empty = document.createElement("p");
    empty.className = "subtle";
    empty.textContent = "Scene lock editor is unavailable (scene.draft.json missing or has no object rows).";
    sceneLocksContainer.appendChild(empty);
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
    header.appendChild(title);
    header.appendChild(meta);
    card.appendChild(header);

    const controls = document.createElement("div");
    controls.className = "scene-lock-row-controls";

    const roleLabel = document.createElement("label");
    roleLabel.className = "scene-lock-control";
    roleLabel.textContent = "Role override";
    const roleSelect = document.createElement("select");
    const autoRoleLabel = row.inferredRoleId ? `Auto (${row.inferredRoleId})` : "Auto";
    _setSelectOptions(
      roleSelect,
      [
        { value: "", label: autoRoleLabel },
        ...state.sceneLocks.roleOptions.map((option) => ({
          value: option.roleId,
          label: `${option.roleId} · ${option.label}`,
        })),
      ],
      row.editRoleId,
    );
    roleSelect.addEventListener("change", () => {
      _updateSceneLockRow(row.stemId, { editRoleId: roleSelect.value });
    });
    roleLabel.appendChild(roleSelect);
    controls.appendChild(roleLabel);

    const frontOnlyLabel = document.createElement("label");
    frontOnlyLabel.className = "toggle-inline scene-lock-control";
    const frontOnlyToggle = document.createElement("input");
    frontOnlyToggle.type = "checkbox";
    frontOnlyToggle.checked = row.editFrontOnly === true;
    frontOnlyToggle.addEventListener("change", () => {
      const next = { editFrontOnly: frontOnlyToggle.checked };
      if (frontOnlyToggle.checked) {
        next.editSurroundCap = 0;
      } else if (row.editSurroundCap <= 0) {
        next.editSurroundCap = 1;
      }
      _updateSceneLockRow(row.stemId, next);
    });
    const frontOnlyText = document.createElement("span");
    frontOnlyText.textContent = "Front-only";
    frontOnlyLabel.appendChild(frontOnlyToggle);
    frontOnlyLabel.appendChild(frontOnlyText);
    controls.appendChild(frontOnlyLabel);

    const surroundWrap = document.createElement("label");
    surroundWrap.className = "scene-lock-slider";
    surroundWrap.textContent = "Surround cap";
    const surroundSlider = document.createElement("input");
    surroundSlider.type = "range";
    surroundSlider.min = "0";
    surroundSlider.max = "1";
    surroundSlider.step = "0.01";
    surroundSlider.value = String(_clampUnit(row.editSurroundCap, 1));
    surroundSlider.disabled = row.editFrontOnly === true;
    surroundSlider.addEventListener("input", () => {
      const nextCap = _clampUnit(surroundSlider.value, 1);
      _updateSceneLockRow(row.stemId, {
        editFrontOnly: nextCap > 0 ? false : row.editFrontOnly,
        editSurroundCap: nextCap,
      });
    });
    const surroundValue = document.createElement("span");
    surroundValue.className = "scene-lock-slider-value";
    surroundValue.textContent = row.editFrontOnly
      ? "forced 0.00 (front-only)"
      : `${_clampUnit(row.editSurroundCap, 1).toFixed(2)}`;
    surroundWrap.appendChild(surroundSlider);
    surroundWrap.appendChild(surroundValue);
    controls.appendChild(surroundWrap);

    const heightWrap = document.createElement("label");
    heightWrap.className = "scene-lock-slider";
    heightWrap.textContent = "Height cap";
    const heightSlider = document.createElement("input");
    heightSlider.type = "range";
    heightSlider.min = "0";
    heightSlider.max = "1";
    heightSlider.step = "0.01";
    heightSlider.value = String(_clampUnit(row.editHeightCap, 1));
    heightSlider.addEventListener("input", () => {
      _updateSceneLockRow(row.stemId, {
        editHeightCap: _clampUnit(heightSlider.value, 1),
      });
    });
    const heightValue = document.createElement("span");
    heightValue.className = "scene-lock-slider-value";
    heightValue.textContent = _clampUnit(row.editHeightCap, 1).toFixed(2);
    heightWrap.appendChild(heightSlider);
    heightWrap.appendChild(heightValue);
    controls.appendChild(heightWrap);

    card.appendChild(controls);
    sceneLocksContainer.appendChild(card);
  }
}

async function refreshSceneLocks() {
  const projectDir = normalizePath(projectDirInput.value);
  if (!projectDir) {
    _resetSceneLocksState();
    _renderSceneLocksEditor();
    if (sceneLocksOutput) {
      sceneLocksOutput.textContent = "Project directory is required to inspect scene locks.";
    }
    return;
  }
  // Inspect is the source of truth for the current draft plus saved overrides.
  // Rebuild the local editor state from that payload on every refresh.
  const result = await apiRpc("scene.locks.inspect", { project_dir: projectDir });
  _hydrateSceneLocksInspect(result);
  _renderSceneLocksEditor();
  if (_isObject(result.scene_preview)) {
    state.scenePreview = _deepClone(result.scene_preview);
    _renderScenePreview();
    _renderDashboardVisuals();
  }
  if (sceneLocksOutput) {
    sceneLocksOutput.textContent = JSON.stringify(
      {
        overrides_count: state.sceneLocks.overridesCount,
        perspective: state.sceneLocks.perspective,
        scene_locks_path: state.sceneLocks.sceneLocksPath || null,
        scene_path: state.sceneLocks.scenePath || null,
      },
      null,
      2,
    );
  }
}

async function saveSceneLocks() {
  const projectDir = normalizePath(projectDirInput.value);
  if (!projectDir) {
    throw new Error("Project directory is required.");
  }
  // These rows are a browser draft until save succeeds. Only the RPC write plus
  // follow-up inspect call can confirm what landed on disk.
  const rows = Array.isArray(state.sceneLocks.objects)
    ? state.sceneLocks.objects.map((row) => ({
      front_only: row.editFrontOnly === true,
      height_cap: _clampUnit(row.editHeightCap, 1),
      role_id: row.editRoleId || "",
      stem_id: row.stemId,
      surround_cap: _clampUnit(row.editSurroundCap, 1),
    }))
    : [];

  setStatus("Saving scene_locks.yaml...");
  const saveResult = await apiRpc("scene.locks.save", {
    project_dir: projectDir,
    perspective: state.sceneLocks.perspective,
    rows,
  });
  if (_isObject(saveResult.scene_preview)) {
    state.scenePreview = _deepClone(saveResult.scene_preview);
    _renderScenePreview();
    _renderDashboardVisuals();
  }
  if (sceneLocksOutput) {
    sceneLocksOutput.textContent = JSON.stringify(saveResult, null, 2);
  }
  // Re-read inspect output after save so the editor stays aligned with the
  // persisted scene draft rather than trusting optimistic local state.
  await refreshSceneLocks();
  setStatus("scene_locks.yaml saved and scene draft updated.");
}

function _renderIntentPreview() {
  const pluginChain = _pluginChainPayload();
  intentOutput.textContent = JSON.stringify(
    {
      ...state.renderRequestIntent,
      plugin_chain: pluginChain,
      plugin_chain_length: pluginChain.length,
    },
    null,
    2,
  );
  _renderScenePreview();
  _renderDashboardVisuals();
}

function _syncMaxTheoreticalQualityToggle() {
  if (!maxTheoreticalQualityToggle) {
    return;
  }
  maxTheoreticalQualityToggle.checked = state.renderRequestIntent.max_theoretical_quality === true;
}

function _resetRenderRequestIntent() {
  // Clear local intent when render_request.json is missing so old chain state
  // does not leak across projects or stale project.show results.
  state.renderRequestIntent = {
    dry_run: null,
    max_theoretical_quality: null,
    plugin_chain_length: 0,
    policies: {},
    render_request_path: "",
    target_ids: [],
    target_layout_ids: [],
  };
  state.pluginChain = [];
  _syncMaxTheoreticalQualityToggle();
  renderPluginChainEditor();
  _renderIntentPreview();
}

function _hydrateRenderRequestIntent(renderRequestPath, renderRequestPayload) {
  const payload = _isObject(renderRequestPayload) ? renderRequestPayload : {};
  const options = _isObject(payload.options) ? payload.options : {};

  const policies = {};
  if (typeof options.downmix_policy_id === "string" && options.downmix_policy_id.trim()) {
    policies.downmix_policy_id = options.downmix_policy_id.trim();
  }
  if (typeof options.gates_policy_id === "string" && options.gates_policy_id.trim()) {
    policies.gates_policy_id = options.gates_policy_id.trim();
  }

  // Hydrate the local editor from the saved render_request payload. The browser
  // can reorder or tweak drafts later, but disk-backed intent wins on reload.
  state.pluginChain = _chainFromRpcPayload(options.plugin_chain);
  state.renderRequestIntent = {
    dry_run: typeof options.dry_run === "boolean" ? options.dry_run : null,
    max_theoretical_quality: (
      typeof options.max_theoretical_quality === "boolean"
        ? options.max_theoretical_quality
        : null
    ),
    plugin_chain_length: state.pluginChain.length,
    policies,
    render_request_path: renderRequestPath,
    target_ids: _normalizeIdList(options.target_ids),
    target_layout_ids: _normalizeIdList(payload.target_layout_ids),
  };

  _syncMaxTheoreticalQualityToggle();
  renderPluginChainEditor();
  _renderIntentPreview();
}

function _normalizeChainStage(stage) {
  if (!_isObject(stage)) {
    return null;
  }
  const pluginIdRaw = stage.plugin_id;
  if (typeof pluginIdRaw !== "string" || !pluginIdRaw.trim()) {
    return null;
  }
  const pluginId = pluginIdRaw.trim();
  const normalized = { plugin_id: pluginId };

  const paramsRaw = _isObject(stage.params) ? stage.params : {};
  const paramKeys = Object.keys(paramsRaw);
  if (paramKeys.length > 0) {
    const params = {};
    for (const key of paramKeys) {
      const value = paramsRaw[key];
      if (value !== undefined) {
        params[key] = _deepClone(value);
      }
    }
    if (Object.keys(params).length > 0) {
      normalized.params = params;
    }
  }

  return normalized;
}

function _pluginChainPayload() {
  const payload = [];
  for (const stage of state.pluginChain) {
    const normalized = _normalizeChainStage(stage);
    if (normalized) {
      payload.push(normalized);
    }
  }
  return payload;
}

function _renderChainPayloadPreview() {
  const chain = _pluginChainPayload();
  const maxTheoreticalQuality = Boolean(maxTheoreticalQualityToggle?.checked);
  if (chain.length === 0) {
    chainOutput.textContent = "Plugin chain is empty.";
    _renderIntentPreview();
    return;
  }
  chainOutput.textContent = JSON.stringify(
    {
      set: {
        dry_run: false,
        max_theoretical_quality: maxTheoreticalQuality,
        plugin_chain: chain,
      },
    },
    null,
    2,
  );
  _renderIntentPreview();
}

function _clearStageParam(stage, name) {
  if (!_isObject(stage.params)) {
    return;
  }
  delete stage.params[name];
  if (Object.keys(stage.params).length === 0) {
    delete stage.params;
  }
}

function _setStageParam(stage, name, value) {
  if (!_isObject(stage.params)) {
    stage.params = {};
  }
  stage.params[name] = _deepClone(value);
}

function _stageFieldValue(stage, field) {
  if (_isObject(stage.params) && Object.prototype.hasOwnProperty.call(stage.params, field.name)) {
    return stage.params[field.name];
  }
  return field.defaultValue;
}

function _parseNumericFieldValue(field, rawValue) {
  const raw = typeof rawValue === "string" ? rawValue.trim() : "";
  if (!raw) {
    return { empty: true };
  }
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    return { error: `Field ${field.name} must be numeric.` };
  }
  if (field.type === "integer" && !Number.isInteger(parsed)) {
    return { error: `Field ${field.name} must be an integer.` };
  }
  if (_isFiniteNumber(field.minimum) && parsed < field.minimum) {
    return { error: `Field ${field.name} must be >= ${field.minimum}.` };
  }
  if (_isFiniteNumber(field.maximum) && parsed > field.maximum) {
    return { error: `Field ${field.name} must be <= ${field.maximum}.` };
  }
  return { value: parsed };
}

function _commitNumericParam(stage, field, rawValue) {
  const parsed = _parseNumericFieldValue(field, rawValue);
  if (parsed.empty) {
    if (field.required) {
      setStatus(`Field ${field.name} is required.`);
      return null;
    }
    _clearStageParam(stage, field.name);
    _renderChainPayloadPreview();
    return null;
  }
  if (parsed.error) {
    setStatus(parsed.error);
    return null;
  }
  _setStageParam(stage, field.name, parsed.value);
  _renderChainPayloadPreview();
  return parsed.value;
}

function _createChainRangeInput(stage, field, currentValue) {
  const controls = document.createElement("div");
  controls.className = "range-with-entry";

  const rangeInput = document.createElement("input");
  rangeInput.type = "range";
  const textInput = document.createElement("input");
  textInput.type = "number";

  _setNumericBounds(rangeInput, field);
  _setNumericBounds(textInput, field);
  _bindFineStepInput(rangeInput, field);
  _bindFineStepInput(textInput, field);

  const startValue = _numericControlValue(currentValue, field);
  rangeInput.value = String(startValue);
  textInput.value = String(startValue);

  rangeInput.addEventListener("input", () => {
    textInput.value = rangeInput.value;
  });
  rangeInput.addEventListener("change", () => {
    _setStageParam(stage, field.name, Number(rangeInput.value));
    _renderChainPayloadPreview();
  });
  textInput.addEventListener("change", () => {
    const committed = _commitNumericParam(stage, field, textInput.value);
    if (_isFiniteNumber(committed)) {
      rangeInput.value = String(committed);
    }
  });

  controls.appendChild(rangeInput);
  controls.appendChild(textInput);
  return _withUnits(controls, field);
}

function _renderChainFieldInput(stage, field) {
  const currentValue = _stageFieldValue(stage, field);

  if (field.inputKind === "checkbox") {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(currentValue);
    input.addEventListener("change", () => {
      _setStageParam(stage, field.name, input.checked);
      _renderChainPayloadPreview();
    });
    return _withUnits(input, field);
  }

  if (field.inputKind === "select") {
    const select = _createSelectInput(
      field,
      currentValue,
      {
        onChange: (decodedValue, rawValue) => {
          if (!rawValue && !field.required) {
            _clearStageParam(stage, field.name);
          } else {
            _setStageParam(stage, field.name, decodedValue);
          }
          _renderChainPayloadPreview();
        },
      },
    );
    if (!field.required) {
      const emptyOption = document.createElement("option");
      emptyOption.value = "";
      emptyOption.textContent = "(unset)";
      emptyOption.selected = currentValue === null || currentValue === undefined;
      select.insertBefore(emptyOption, select.firstChild);
      if (emptyOption.selected) {
        select.value = "";
      }
    }
    return _withUnits(select, field);
  }

  if (field.inputKind === "range") {
    return _createChainRangeInput(stage, field, currentValue);
  }

  if (field.inputKind === "number") {
    const input = document.createElement("input");
    input.type = "number";
    if (typeof currentValue === "number") {
      input.value = String(currentValue);
    } else if (currentValue !== null && currentValue !== undefined) {
      input.value = String(currentValue);
    }
    _setNumericBounds(input, field);
    _bindFineStepInput(input, field);
    input.addEventListener("change", () => {
      _commitNumericParam(stage, field, input.value);
    });
    return _withUnits(input, field);
  }

  if (field.inputKind === "json") {
    const textarea = document.createElement("textarea");
    textarea.className = "field-input-json";
    if (currentValue !== null && currentValue !== undefined) {
      if (typeof currentValue === "string") {
        textarea.value = currentValue;
      } else {
        textarea.value = JSON.stringify(currentValue, null, 2);
      }
    }
    textarea.addEventListener("change", () => {
      const raw = textarea.value.trim();
      if (!raw) {
        if (field.required) {
          setStatus(`Field ${field.name} is required.`);
          return;
        }
        textarea.classList.remove("field-input-invalid");
        _clearStageParam(stage, field.name);
        _renderChainPayloadPreview();
        return;
      }
      try {
        const parsed = JSON.parse(raw);
        _setStageParam(stage, field.name, parsed);
        textarea.classList.remove("field-input-invalid");
        _renderChainPayloadPreview();
      } catch {
        textarea.classList.add("field-input-invalid");
        setStatus(`Field ${field.name} must be valid JSON.`);
      }
    });
    return textarea;
  }

  const input = document.createElement("input");
  input.type = "text";
  if (currentValue !== null && currentValue !== undefined) {
    input.value = String(currentValue);
  }
  input.addEventListener("change", () => {
    const value = input.value;
    if (!value.trim() && !field.required) {
      _clearStageParam(stage, field.name);
    } else {
      _setStageParam(stage, field.name, value);
    }
    _renderChainPayloadPreview();
  });
  return _withUnits(input, field);
}

function _moveChainStage(stageIndex, delta) {
  const newIndex = stageIndex + delta;
  if (newIndex < 0 || newIndex >= state.pluginChain.length) {
    return;
  }
  const [item] = state.pluginChain.splice(stageIndex, 1);
  state.pluginChain.splice(newIndex, 0, item);
  renderPluginChainEditor();
}

function renderPluginChainEditor() {
  chainContainer.innerHTML = "";
  if (state.pluginChain.length === 0) {
    const empty = document.createElement("p");
    empty.className = "subtle";
    empty.textContent = "No chain stages yet. Add a plugin to start.";
    chainContainer.appendChild(empty);
    _renderChainPayloadPreview();
    return;
  }

  state.pluginChain.forEach((stage, stageIndex) => {
    const card = document.createElement("article");
    card.className = "chain-stage";

    const header = document.createElement("div");
    header.className = "chain-stage-header";

    const title = document.createElement("div");
    title.className = "chain-stage-title";
    title.textContent = `Stage ${stageIndex + 1}: ${stage.plugin_id}`;
    header.appendChild(title);

    const controls = document.createElement("div");
    controls.className = "chain-controls";

    const upButton = document.createElement("button");
    upButton.type = "button";
    upButton.textContent = "Up";
    upButton.disabled = stageIndex === 0;
    upButton.addEventListener("click", () => _moveChainStage(stageIndex, -1));
    controls.appendChild(upButton);

    const downButton = document.createElement("button");
    downButton.type = "button";
    downButton.textContent = "Down";
    downButton.disabled = stageIndex === state.pluginChain.length - 1;
    downButton.addEventListener("click", () => _moveChainStage(stageIndex, 1));
    controls.appendChild(downButton);

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.textContent = "Remove";
    removeButton.addEventListener("click", () => {
      state.pluginChain.splice(stageIndex, 1);
      renderPluginChainEditor();
    });
    controls.appendChild(removeButton);

    header.appendChild(controls);
    card.appendChild(header);

    const plugin = state.pluginsById.get(stage.plugin_id);
    if (!plugin) {
      const warning = document.createElement("div");
      warning.className = "error-text";
      warning.textContent = "Plugin metadata is not loaded for this stage. Rebuild GUI and refresh.";
      card.appendChild(warning);
      chainContainer.appendChild(card);
      return;
    }

    const fields = buildFormFields(plugin.config_schema, plugin.ui_hints);
    if (fields.length === 0) {
      const noFields = document.createElement("p");
      noFields.className = "subtle";
      noFields.textContent = "This plugin has no editable config fields.";
      card.appendChild(noFields);
      chainContainer.appendChild(card);
      return;
    }

    const ordered = _orderedFieldsByLayout(plugin, fields);
    for (const field of ordered.orderedFields) {
      _appendFieldRow(card, field, _renderChainFieldInput(stage, field));
    }
    if (ordered.hasLayout) {
      _appendMoreSection(card, ordered.moreFields, (field) => _renderChainFieldInput(stage, field));
    }

    chainContainer.appendChild(card);
  });

  _renderChainPayloadPreview();
  _refreshFineSteps();
}

function _chainFromRpcPayload(rawChain) {
  if (!Array.isArray(rawChain)) {
    return [];
  }
  const stages = [];
  for (const stage of rawChain) {
    const normalized = _normalizeChainStage(stage);
    if (normalized) {
      stages.push(normalized);
    }
  }
  return stages;
}

function addPluginToChain() {
  const pluginId = chainPluginSelect.value;
  if (!pluginId) {
    throw new Error("No editable plugin is selected.");
  }
  const plugin = state.pluginsById.get(pluginId);
  if (!plugin) {
    throw new Error(`Unknown plugin selected: ${pluginId}`);
  }
  state.pluginChain.push({
    plugin_id: pluginId,
    params: _defaultParamsForPlugin(plugin),
  });
  renderPluginChainEditor();
  setStatus(`Added ${pluginId} to plugin chain.`);
}

async function savePluginChain() {
  const projectDir = normalizePath(projectDirInput.value);
  if (!projectDir) {
    throw new Error("Project directory is required.");
  }
  // The chain editor is local draft state until project.write_render_request
  // echoes back the saved payload from render_request.json.
  const pluginChain = _pluginChainPayload();
  const maxTheoreticalQuality = Boolean(maxTheoreticalQualityToggle?.checked);
  if (pluginChain.length === 0) {
    throw new Error("Plugin chain is empty. Add at least one stage before saving.");
  }

  setStatus("Calling project.write_render_request...");
  const result = await apiRpc("project.write_render_request", {
    project_dir: projectDir,
    set: {
      dry_run: false,
      max_theoretical_quality: maxTheoreticalQuality,
      plugin_chain: pluginChain,
    },
  });
  projectOutput.textContent = JSON.stringify(result, null, 2);
  state.pluginChain = _chainFromRpcPayload(result.plugin_chain);
  state.renderRequestIntent = {
    ...state.renderRequestIntent,
    dry_run: false,
    max_theoretical_quality: maxTheoreticalQuality,
    plugin_chain_length: state.pluginChain.length,
  };
  renderPluginChainEditor();
  _renderIntentPreview();
  setStatus("project.write_render_request completed.");
}

async function runSafeRun() {
  const projectDir = normalizePath(projectDirInput.value);
  if (!projectDir) {
    throw new Error("Project directory is required.");
  }

  // Safe Run writes its preset through the backend first. The browser does not
  // mutate render_request state locally and call render_run later.
  setStatus("Calling project.write_render_request (Safe Run preset)...");
  const writeResult = await apiRpc("project.write_render_request", {
    project_dir: projectDir,
    set: {
      dry_run: false,
    },
  });
  state.renderRequestIntent = {
    ...state.renderRequestIntent,
    dry_run: false,
  };
  _renderIntentPreview();

  _clearRenderRefusal();
  renderRenderArtifactsViewer();
  setStatus("Calling project.render_run (Safe Run preset)...");
  let runResult;
  try {
    runResult = await apiRpc("project.render_run", {
      project_dir: projectDir,
      force: true,
      event_log: true,
      event_log_force: true,
      preflight: true,
      preflight_force: true,
      execute: true,
      execute_force: true,
      qa_out: true,
    });
  } catch (error) {
    _recordRenderRefusal(error);
    renderRenderArtifactsViewer();
    throw error;
  }

  state.audition.activeStream = "output";
  state.audition.jobId = "";
  state.audition.inputSlot = 0;
  state.audition.outputSlot = 0;

  projectOutput.textContent = JSON.stringify(
    {
      render_run: runResult,
      write_render_request: writeResult,
    },
    null,
    2,
  );
  setStatus("Safe Run completed. Refreshing project.show...");
  await refreshProjectShow();
  setStatus("Safe Run completed. Receipt is ready.");
}

async function refreshPluginMarketplace() {
  const pluginsDir = normalizePath(pluginsDirInput.value) || "plugins";
  setStatus("Calling plugin.market.list...");
  const result = await apiRpc("plugin.market.list", { plugins: pluginsDir });
  state.pluginMarket = _deepClone(result);
  renderPluginMarketplace(result);
  setStatus("plugin.market.list completed.");
}

async function updatePluginMarketplace() {
  setStatus("Calling plugin.market.update...");
  const result = await apiRpc("plugin.market.update", {});
  state.pluginMarketUpdate = _deepClone(result);
  if (pluginMarketOutput) {
    pluginMarketOutput.textContent = JSON.stringify(result, null, 2);
  }
  setStatus("plugin.market.update completed.");
  await refreshPluginMarketplace();
}

async function refreshDiscover() {
  setStatus("Calling rpc.discover...");
  const result = await apiRpc("rpc.discover", {});
  renderMethods(result.methods || []);
  setStatus("rpc.discover completed.");
}

async function refreshDoctor() {
  setStatus("Calling env.doctor...");
  const result = await apiRpc("env.doctor", {});
  doctorOutput.textContent = JSON.stringify(result, null, 2);
  setStatus("env.doctor completed.");
}

function _artifactPathFromProjectShow(projectShow, artifactPath) {
  if (!projectShow || typeof projectShow !== "object") {
    return "";
  }
  const artifacts = Array.isArray(projectShow.artifacts) ? projectShow.artifacts : [];
  const match = artifacts.find(
    (artifact) =>
      artifact &&
      typeof artifact === "object" &&
      artifact.path === artifactPath &&
      artifact.exists === true,
  );
  // Only trust absolute paths that project.show marked present. The browser
  // should not guess render-artifact locations from relative names alone.
  return match && typeof match.absolute_path === "string"
    ? match.absolute_path
    : "";
}

function _uiBundlePathFromProjectShow(projectShow) {
  return _artifactPathFromProjectShow(projectShow, "ui_bundle.json");
}

function _renderRequestPathFromProjectShow(projectShow) {
  return _artifactPathFromProjectShow(projectShow, "renders/render_request.json");
}

async function refreshProjectShow() {
  const projectDir = normalizePath(projectDirInput.value);
  if (!projectDir) {
    throw new Error("Project directory is required.");
  }
  setStatus("Calling project.show...");
  // Project.show is the browser hydration root for this shell. Every later
  // panel refresh hangs off the artifact and path receipts it returns.
  const result = await apiRpc("project.show", { project_dir: projectDir });
  state.projectShow = result;
  projectOutput.textContent = JSON.stringify(result, null, 2);
  setStatus("project.show completed. Hydrating state...");

  const uiBundlePath = _uiBundlePathFromProjectShow(result);
  if (uiBundlePath) {
    setStatus("Loading ui_bundle and plugin forms...");
    await loadUiBundle(uiBundlePath);
    setStatus("ui_bundle loaded. Reading render_request...");
  } else {
    state.uiBundle = null;
    state.scenePreview = null;
    renderPluginForms([]);
    _setEditablePlugins([]);
    _renderScenePreview();
    _renderDashboardVisuals();
    setStatus("ui_bundle missing. Reading render_request...");
  }

  const renderRequestPath = _renderRequestPathFromProjectShow(result);
  if (renderRequestPath) {
    const renderRequest = await loadRenderRequest(renderRequestPath);
    _hydrateRenderRequestIntent(renderRequest.path, renderRequest.payload);
  } else {
    _resetRenderRequestIntent();
  }

  try {
    setStatus("Loading scene lock editor...");
    await refreshSceneLocks();
  } catch (error) {
    _resetSceneLocksState();
    _renderSceneLocksEditor();
    if (sceneLocksOutput) {
      sceneLocksOutput.textContent = JSON.stringify(
        {
          error: error instanceof Error ? error.message : String(error),
        },
        null,
        2,
      );
    }
    setStatus("Scene lock editor unavailable for current project state.");
  }

  setStatus("Loading render artifacts...");
  await refreshRenderArtifactsFromProjectShow(result);

  if (renderRequestPath) {
    setStatus("project.show hydration completed.");
  } else {
    setStatus("project.show completed (render_request missing).");
  }
}

async function runBuildGuiAndRefresh() {
  const projectDir = normalizePath(projectDirInput.value);
  const stemsRoot = normalizePath(stemsRootInput.value);
  const packOut = normalizePath(packOutInput.value) || joinPosix(projectDir, "project_gui_shell.zip");
  const pluginsDir = normalizePath(pluginsDirInput.value) || "plugins";

  if (!projectDir) {
    throw new Error("Project directory is required.");
  }
  if (!stemsRoot) {
    throw new Error("Stems root is required for build_gui scan.");
  }

  setStatus("Calling project.build_gui...");
  const buildResult = await apiRpc("project.build_gui", {
    project_dir: projectDir,
    pack_out: packOut,
    scan: true,
    scan_stems: stemsRoot,
    scan_out: joinPosix(projectDir, "report.json"),
    force: true,
    event_log: true,
    event_log_force: true,
    include_plugins: true,
    include_plugin_layouts: true,
    include_plugin_layout_snapshots: true,
    include_plugin_ui_hints: true,
    plugins: pluginsDir,
  });

  projectOutput.textContent = JSON.stringify(buildResult, null, 2);
  // Refresh from project.show after build_gui so the browser rehydrates from
  // disk-backed artifacts instead of trusting pre-build local state.
  setStatus("project.build_gui completed. Refreshing project.show...");
  await refreshProjectShow();
}

function maybeSeedPackOut() {
  const projectDir = normalizePath(projectDirInput.value);
  if (!projectDir) {
    return;
  }
  if (!normalizePath(packOutInput.value)) {
    packOutInput.value = joinPosix(projectDir, "project_gui_shell.zip");
  }
}

discoverButton.addEventListener("click", async () => {
  try {
    await refreshDiscover();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  }
});

doctorButton.addEventListener("click", async () => {
  try {
    await refreshDoctor();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  }
});

if (pluginMarketListButton) {
  pluginMarketListButton.addEventListener("click", async () => {
    try {
      await refreshPluginMarketplace();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  });
}

if (pluginMarketUpdateButton) {
  pluginMarketUpdateButton.addEventListener("click", async () => {
    try {
      await updatePluginMarketplace();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  });
}

showProjectButton.addEventListener("click", async () => {
  try {
    await refreshProjectShow();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  }
});

buildGuiButton.addEventListener("click", async () => {
  try {
    await runBuildGuiAndRefresh();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  }
});

chainAddButton.addEventListener("click", () => {
  try {
    addPluginToChain();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  }
});

chainSaveButton.addEventListener("click", async () => {
  try {
    await savePluginChain();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  }
});

if (safeRunButton) {
  safeRunButton.addEventListener("click", async () => {
    try {
      await runSafeRun();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  });
}

if (copyReceiptButton) {
  copyReceiptButton.addEventListener("click", async () => {
    try {
      await _copySafeRunReceipt();
      setStatus("Safe Run receipt copied to clipboard.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  });
}

timelineJobFilter.addEventListener("change", () => {
  state.renderArtifacts.timelineFilterJob = timelineJobFilter.value;
  _renderTimelineEntries();
});

timelineStageFilter.addEventListener("change", () => {
  state.renderArtifacts.timelineFilterStage = timelineStageFilter.value;
  _renderTimelineEntries();
});

if (sceneLayoutSelect) {
  sceneLayoutSelect.addEventListener("change", () => {
    state.sceneLayoutId = sceneLayoutSelect.value;
    _renderScenePreview();
    _renderDashboardVisuals();
  });
}

if (scenePerspectiveSelect) {
  scenePerspectiveSelect.addEventListener("change", () => {
    state.sceneLocks = {
      ...state.sceneLocks,
      perspective: scenePerspectiveSelect.value,
    };
    _renderScenePreview();
    _renderDashboardVisuals();
  });
}

if (sceneLocksReloadButton) {
  sceneLocksReloadButton.addEventListener("click", async () => {
    try {
      await refreshSceneLocks();
      setStatus("scene lock editor refreshed.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  });
}

if (sceneLocksSaveButton) {
  sceneLocksSaveButton.addEventListener("click", async () => {
    try {
      await saveSceneLocks();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    }
  });
}

if (auditionJobSelect) {
  auditionJobSelect.addEventListener("change", () => {
    state.audition.jobId = auditionJobSelect.value;
    state.audition.inputSlot = 0;
    state.audition.outputSlot = 0;
    _renderAuditionPanel();
  });
}

if (auditionInputSlotSelect) {
  auditionInputSlotSelect.addEventListener("change", () => {
    state.audition.inputSlot = _slotSelectValue(auditionInputSlotSelect);
    _renderAuditionPanel();
  });
}

if (auditionOutputSlotSelect) {
  auditionOutputSlotSelect.addEventListener("change", () => {
    state.audition.outputSlot = _slotSelectValue(auditionOutputSlotSelect);
    _renderAuditionPanel();
  });
}

if (auditionLoudnessMatchToggle) {
  auditionLoudnessMatchToggle.addEventListener("change", () => {
    state.audition.loudnessMatchEnabled = auditionLoudnessMatchToggle.checked;
    _renderAuditionPanel();
    if (state.audition.activeStream === "input" || state.audition.activeStream === "output") {
      void _applyAuditionCompensation(state.audition.activeStream, _selectedAuditionJobOrNull());
    }
  });
}

if (auditionPlayInputButton) {
  auditionPlayInputButton.addEventListener("click", async () => {
    try {
      await _playAudition("input");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      _setAuditionStatus(message);
      setStatus(message);
    }
  });
}

if (auditionPlayOutputButton) {
  auditionPlayOutputButton.addEventListener("click", async () => {
    try {
      await _playAudition("output");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      _setAuditionStatus(message);
      setStatus(message);
    }
  });
}

if (previewHeadphonesButton) {
  previewHeadphonesButton.addEventListener("click", async () => {
    try {
      await _playHeadphonePreview();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      _setAuditionStatus(message);
      setStatus(message);
    }
  });
}

if (auditionAudio) {
  auditionAudio.addEventListener("play", () => {
    void _ensureAuditionGainNode();
    _startHeadphonePreviewAnimation();
  });
  auditionAudio.addEventListener("pause", () => {
    _stopHeadphonePreviewAnimation();
    _renderHeadphonePreviewIdle();
  });
  auditionAudio.addEventListener("ended", () => {
    _stopHeadphonePreviewAnimation();
    _renderHeadphonePreviewIdle();
  });
  auditionAudio.addEventListener("emptied", () => {
    _stopHeadphonePreviewAnimation();
    _renderHeadphonePreviewIdle();
  });
}

if (maxTheoreticalQualityToggle) {
  maxTheoreticalQualityToggle.addEventListener("change", () => {
    state.renderRequestIntent.max_theoretical_quality = maxTheoreticalQualityToggle.checked;
    _renderChainPayloadPreview();
  });
}

window.addEventListener("keydown", (event) => {
  _setModifierState(_modifierStateFromKeyboardEvent(event));
});

window.addEventListener("keyup", (event) => {
  _setModifierState(_modifierStateFromKeyboardEvent(event));
});

window.addEventListener("blur", () => {
  _setModifierState({
    shift: false,
    alt: false,
    ctrl: false,
    meta: false,
  });
});

window.addEventListener("resize", () => {
  _renderDashboardVisuals();
  _renderScenePreview();
  _renderAuditionVisualOverlays();
});

projectDirInput.addEventListener("change", maybeSeedPackOut);
projectDirInput.addEventListener("blur", maybeSeedPackOut);

if (auditionLoudnessMatchToggle) {
  state.audition.loudnessMatchEnabled = auditionLoudnessMatchToggle.checked;
}

renderChainPluginSelect();
renderPluginChainEditor();
renderPluginMarketplace(state.pluginMarket);
renderRenderArtifactsViewer();
_syncMaxTheoreticalQualityToggle();
_renderFineModeIndicator();
_refreshFineSteps();
_renderDashboardVisuals();
_renderScenePreview();
_renderSceneLocksEditor();
_renderHeadphonePreviewIdle();
_renderAuditionVisualOverlays();
setStatus("Ready. Start with rpc.discover.");
