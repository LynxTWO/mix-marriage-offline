import { buildFormFields } from "/lib/plugin_forms.mjs";

const discoverButton = document.getElementById("discover-button");
const doctorButton = document.getElementById("doctor-button");
const showProjectButton = document.getElementById("show-project-button");
const buildGuiButton = document.getElementById("build-gui-button");

const methodsList = document.getElementById("methods-list");
const doctorOutput = document.getElementById("doctor-output");
const projectOutput = document.getElementById("project-output");
const statusOutput = document.getElementById("status-output");
const pluginsContainer = document.getElementById("plugins-container");

const projectDirInput = document.getElementById("project-dir-input");
const stemsRootInput = document.getElementById("stems-root-input");
const packOutInput = document.getElementById("pack-out-input");
const pluginsDirInput = document.getElementById("plugins-dir-input");

const state = {
  projectShow: null,
};

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
    throw new Error(`${code}: ${message}`);
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
  renderPluginForms(payload.plugins || []);
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

function _renderFieldInput(field) {
  if (field.inputKind === "checkbox") {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = Boolean(field.defaultValue);
    input.disabled = true;
    return input;
  }

  if (field.inputKind === "select") {
    const select = document.createElement("select");
    select.disabled = true;
    for (const value of field.enumValues) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      if (value === field.defaultValue) {
        option.selected = true;
      }
      select.appendChild(option);
    }
    return select;
  }

  const input = document.createElement("input");
  input.type = field.inputKind === "number" ? "number" : "text";
  input.disabled = true;
  if (field.defaultValue !== null && field.defaultValue !== undefined) {
    input.value = String(field.defaultValue);
  }
  if (field.minimum !== null) {
    input.min = String(field.minimum);
  }
  if (field.maximum !== null) {
    input.max = String(field.maximum);
  }
  if (field.step !== null) {
    input.step = String(field.step);
  }
  return input;
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
        for (const field of fields) {
          const row = document.createElement("div");
          row.className = "field-row";

          const label = document.createElement("div");
          const requiredTag = field.required ? " (required)" : "";
          const widgetHint = field.hint?.widget ? ` [${field.hint.widget}]` : "";
          label.innerHTML = `<strong>${field.label}</strong>${requiredTag}${widgetHint}<div class="field-meta">${field.name}${field.description ? ` - ${field.description}` : ""}</div>`;
          row.appendChild(label);
          row.appendChild(_renderFieldInput(field));
          card.appendChild(row);
        }
      }
    }

    _renderLayoutSnapshot(card, plugin);
    pluginsContainer.appendChild(card);
  }
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

function _uiBundlePathFromProjectShow(projectShow) {
  if (!projectShow || typeof projectShow !== "object") {
    return "";
  }
  const artifacts = Array.isArray(projectShow.artifacts) ? projectShow.artifacts : [];
  const uiBundle = artifacts.find(
    (artifact) =>
      artifact &&
      typeof artifact === "object" &&
      artifact.path === "ui_bundle.json" &&
      artifact.exists === true,
  );
  return uiBundle && typeof uiBundle.absolute_path === "string"
    ? uiBundle.absolute_path
    : "";
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
  setStatus("project.show completed.");

  const uiBundlePath = _uiBundlePathFromProjectShow(result);
  if (uiBundlePath) {
    setStatus("Loading ui_bundle and plugin forms...");
    await loadUiBundle(uiBundlePath);
    setStatus("ui_bundle loaded.");
  } else {
    renderPluginForms([]);
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

projectDirInput.addEventListener("change", maybeSeedPackOut);
projectDirInput.addEventListener("blur", maybeSeedPackOut);

setStatus("Ready. Start with rpc.discover.");
