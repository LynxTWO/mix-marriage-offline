import { buildFormFields, orderFieldsByLayout, resolveFieldStep } from "/lib/plugin_forms.mjs";
import {
  computeAuditionCompensation,
  formatAuditionCompensationReceipt,
  resolveAuditionLoudnessDb,
} from "/lib/audition_loudness.mjs";

const discoverButton = document.getElementById("discover-button");
const doctorButton = document.getElementById("doctor-button");
const showProjectButton = document.getElementById("show-project-button");
const buildGuiButton = document.getElementById("build-gui-button");
const chainAddButton = document.getElementById("chain-add-button");
const chainSaveButton = document.getElementById("chain-save-button");
const runRenderButton = document.getElementById("run-render-button");

const methodsList = document.getElementById("methods-list");
const doctorOutput = document.getElementById("doctor-output");
const projectOutput = document.getElementById("project-output");
const statusOutput = document.getElementById("status-output");
const pluginsContainer = document.getElementById("plugins-container");
const chainContainer = document.getElementById("chain-container");
const chainOutput = document.getElementById("chain-output");
const intentOutput = document.getElementById("intent-output");
const renderSummaryOutput = document.getElementById("render-summary-output");
const determinismOutput = document.getElementById("determinism-output");
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
const auditionInputSha = document.getElementById("audition-input-sha");
const auditionOutputSha = document.getElementById("audition-output-sha");
const auditionAudio = document.getElementById("audition-audio");
const auditionLoudnessMatchLabel = document.getElementById("audition-loudness-match-label");
const auditionLoudnessMatchToggle = document.getElementById("audition-loudness-match-toggle");
const auditionLoudnessReceipt = document.getElementById("audition-loudness-receipt");
const auditionStatus = document.getElementById("audition-status");

const projectDirInput = document.getElementById("project-dir-input");
const stemsRootInput = document.getElementById("stems-root-input");
const packOutInput = document.getElementById("pack-out-input");
const pluginsDirInput = document.getElementById("plugins-dir-input");
const chainPluginSelect = document.getElementById("chain-plugin-select");
const fineModeIndicator = document.getElementById("fine-mode-indicator");

const state = {
  projectShow: null,
  pluginsById: new Map(),
  editablePluginIds: [],
  pluginChain: [],
  renderRequestIntent: {
    dry_run: null,
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
  },
  modifierState: {
    shift: false,
    alt: false,
    ctrl: false,
    meta: false,
  },
};
const AUDITION_ALLOW_BOOST = false;
let auditionAudioContext = null;
let auditionAudioGainNode = null;
let auditionAudioSourceNode = null;

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
  const plugins = Array.isArray(payload.plugins) ? payload.plugins : [];
  renderPluginForms(plugins);
  _setEditablePlugins(plugins);
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
    report: null,
    timelineFilterJob: "",
    timelineFilterStage: "",
  };
}

function _recordRenderRefusal(error) {
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
  if (!state.audition.loudnessMatchEnabled) {
    await _applyAuditionGainDb(0);
    _renderAuditionReceipt(selectedJob, streamKind);
    return;
  }
  const result = _auditionCompensationResult(streamKind, selectedJob);
  await _applyAuditionGainDb(result.gainDb);
  _renderAuditionReceipt(selectedJob, streamKind);
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
    auditionInputSha.textContent = "sha256: -";
    auditionOutputSha.textContent = "sha256: -";
    _renderAuditionLoudnessToggle({ disabled: true });
    _setAuditionReceipt("Loudness match unavailable: no render_execute jobs.");
    state.audition.activeStream = "";
    _setAuditionStatus("No render_execute jobs available for audition.");
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

  const selectedInput = _selectedPointerOrNull(selectedJob, "input", state.audition.inputSlot);
  const selectedOutput = _selectedPointerOrNull(selectedJob, "output", state.audition.outputSlot);
  auditionInputSha.textContent = `sha256: ${selectedInput?.sha256 || "-"}`;
  auditionOutputSha.textContent = `sha256: ${selectedOutput?.sha256 || "-"}`;
  _renderAuditionLoudnessToggle({ disabled: false });
  const previewStream = state.audition.activeStream === "input" ? "input" : "output";
  _renderAuditionReceipt(selectedJob, previewStream);
  _setAuditionStatus(`Ready: ${state.audition.jobId}`);
}

function _auditionUrl(streamKind) {
  const projectDir = normalizePath(projectDirInput?.value || "");
  if (!projectDir) {
    throw new Error("Project directory is required before auditioning.");
  }
  const slot = streamKind === "input" ? state.audition.inputSlot : state.audition.outputSlot;
  const query = new URLSearchParams({
    job_id: state.audition.jobId,
    project_dir: projectDir,
    slot: String(slot),
    stream: streamKind,
  });
  return `/api/audio-stream?${query.toString()}`;
}

async function _playAudition(streamKind) {
  if (!auditionAudio) {
    return;
  }
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
  _renderRefusalBlock();
  _renderExecutePointersBlock();
  _renderAuditionPanel();
  _renderTimelineEntries();
}

async function refreshRenderArtifactsFromProjectShow(projectShow) {
  const reportPath = _artifactPathFromProjectShow(projectShow, "renders/render_report.json");
  const executePath = _artifactPathFromProjectShow(projectShow, "renders/render_execute.json");
  const eventLogPath = _artifactPathFromProjectShow(projectShow, "renders/event_log.jsonl");

  let reportPayload = null;
  let executePayload = null;
  let eventLogEntries = [];

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

  state.renderArtifacts = {
    ...state.renderArtifacts,
    eventLogEntries,
    execute: executePayload,
    report: reportPayload,
  };
  renderRenderArtifactsViewer();
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
}

function _resetRenderRequestIntent() {
  state.renderRequestIntent = {
    dry_run: null,
    plugin_chain_length: 0,
    policies: {},
    render_request_path: "",
    target_ids: [],
    target_layout_ids: [],
  };
  state.pluginChain = [];
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

  state.pluginChain = _chainFromRpcPayload(options.plugin_chain);
  state.renderRequestIntent = {
    dry_run: typeof options.dry_run === "boolean" ? options.dry_run : null,
    plugin_chain_length: state.pluginChain.length,
    policies,
    render_request_path: renderRequestPath,
    target_ids: _normalizeIdList(options.target_ids),
    target_layout_ids: _normalizeIdList(payload.target_layout_ids),
  };

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
  if (chain.length === 0) {
    chainOutput.textContent = "Plugin chain is empty.";
    _renderIntentPreview();
    return;
  }
  chainOutput.textContent = JSON.stringify(
    {
      set: {
        dry_run: false,
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
  const pluginChain = _pluginChainPayload();
  if (pluginChain.length === 0) {
    throw new Error("Plugin chain is empty. Add at least one stage before saving.");
  }

  setStatus("Calling project.write_render_request...");
  const result = await apiRpc("project.write_render_request", {
    project_dir: projectDir,
    set: {
      dry_run: false,
      plugin_chain: pluginChain,
    },
  });
  projectOutput.textContent = JSON.stringify(result, null, 2);
  state.pluginChain = _chainFromRpcPayload(result.plugin_chain);
  state.renderRequestIntent = {
    ...state.renderRequestIntent,
    dry_run: false,
    plugin_chain_length: state.pluginChain.length,
  };
  renderPluginChainEditor();
  _renderIntentPreview();
  setStatus("project.write_render_request completed.");
}

async function runProjectRender() {
  const projectDir = normalizePath(projectDirInput.value);
  if (!projectDir) {
    throw new Error("Project directory is required.");
  }

  _clearRenderRefusal();
  renderRenderArtifactsViewer();
  setStatus("Calling project.render_run...");
  let result;
  try {
    result = await apiRpc("project.render_run", {
      project_dir: projectDir,
      force: true,
      event_log: true,
      event_log_force: true,
      execute: true,
      execute_force: true,
    });
  } catch (error) {
    _recordRenderRefusal(error);
    renderRenderArtifactsViewer();
    throw error;
  }
  projectOutput.textContent = JSON.stringify(result, null, 2);
  setStatus("project.render_run completed. Refreshing project.show...");
  await refreshProjectShow();
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
    renderPluginForms([]);
    _setEditablePlugins([]);
    setStatus("ui_bundle missing. Reading render_request...");
  }

  const renderRequestPath = _renderRequestPathFromProjectShow(result);
  if (renderRequestPath) {
    const renderRequest = await loadRenderRequest(renderRequestPath);
    _hydrateRenderRequestIntent(renderRequest.path, renderRequest.payload);
  } else {
    _resetRenderRequestIntent();
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

runRenderButton.addEventListener("click", async () => {
  try {
    await runProjectRender();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  }
});

timelineJobFilter.addEventListener("change", () => {
  state.renderArtifacts.timelineFilterJob = timelineJobFilter.value;
  _renderTimelineEntries();
});

timelineStageFilter.addEventListener("change", () => {
  state.renderArtifacts.timelineFilterStage = timelineStageFilter.value;
  _renderTimelineEntries();
});

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

projectDirInput.addEventListener("change", maybeSeedPackOut);
projectDirInput.addEventListener("blur", maybeSeedPackOut);

if (auditionLoudnessMatchToggle) {
  state.audition.loudnessMatchEnabled = auditionLoudnessMatchToggle.checked;
}

renderChainPluginSelect();
renderPluginChainEditor();
renderRenderArtifactsViewer();
_renderFineModeIndicator();
_refreshFineSteps();
setStatus("Ready. Start with rpc.discover.");
