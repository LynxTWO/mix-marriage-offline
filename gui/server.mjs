import http from "node:http";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { promises as fs } from "node:fs";
import { fileURLToPath } from "node:url";

import { runMmoCli, runMmoCliJson } from "./lib/mmo_cli_runner.mjs";
import { RpcProcessClient } from "./lib/rpc_process_client.mjs";

const _SERVER_ROOT = path.dirname(fileURLToPath(import.meta.url));
const _WEB_ROOT = path.join(_SERVER_ROOT, "web");
const _PORT = Number.parseInt(process.env.GUI_DEV_PORT || "4175", 10);

const _rpcClient = new RpcProcessClient();

const _MIME_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
};

const _ALLOWED_RENDER_ARTIFACT_NAMES = new Set([
  "event_log.jsonl",
  "render_execute.json",
  "render_plan.json",
  "render_preflight.json",
  "render_report.json",
  "render_request.json",
]);

function _pathToPosix(pathValue) {
  return pathValue.replace(/\\/g, "/");
}

function _sendJson(response, statusCode, payload) {
  response.statusCode = statusCode;
  response.setHeader("Content-Type", "application/json; charset=utf-8");
  response.end(JSON.stringify(payload, null, 2));
}

function _sendText(response, statusCode, body, contentType = "text/plain; charset=utf-8") {
  response.statusCode = statusCode;
  response.setHeader("Content-Type", contentType);
  response.end(body);
}

async function _readJsonBody(request) {
  let raw = "";
  for await (const chunk of request) {
    raw += chunk;
  }
  if (!raw.trim()) {
    return {};
  }
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new Error(
      `Invalid JSON body: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON body must be an object.");
  }
  return parsed;
}

function _safeStaticPath(urlPath) {
  const normalizedUrlPath = path.posix.normalize(urlPath);

  if (normalizedUrlPath.startsWith("/lib/")) {
    const localPath = path.resolve(_SERVER_ROOT, `.${normalizedUrlPath}`);
    const relative = path.relative(_SERVER_ROOT, localPath);
    if (relative.startsWith("..") || path.isAbsolute(relative)) {
      return null;
    }
    return localPath;
  }

  const relativePath = normalizedUrlPath === "/" ? "/index.html" : normalizedUrlPath;
  const localPath = path.resolve(_WEB_ROOT, `.${relativePath}`);
  const relative = path.relative(_WEB_ROOT, localPath);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    return null;
  }
  return localPath;
}

function _pluginSnapshotOutPath(pluginId) {
  const suffix = `${Date.now()}_${Math.random().toString(16).slice(2, 10)}`;
  const safePluginId = pluginId.replace(/[^A-Za-z0-9_.-]/g, "_");
  return path.join(os.tmpdir(), `mmo_gui_snapshot_${safePluginId}_${suffix}.json`);
}

function _looksLikeRenderRequestPath(pathValue) {
  const normalized = _pathToPosix(path.resolve(pathValue));
  return normalized.endsWith("/renders/render_request.json");
}

function _renderArtifactInfo(pathValue) {
  const normalized = _pathToPosix(path.resolve(pathValue));
  const match = normalized.match(/\/renders\/([^/]+)$/);
  if (!match) {
    return null;
  }
  const artifactName = match[1].toLowerCase();
  if (!_ALLOWED_RENDER_ARTIFACT_NAMES.has(artifactName)) {
    return null;
  }
  return {
    artifactName,
    normalizedPath: normalized,
  };
}

function _parseJsonLines(text) {
  const entries = [];
  const lines = text.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const line = rawLine.trim();
    if (!line) {
      continue;
    }
    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch (error) {
      throw new Error(
        `Invalid JSONL at line ${index + 1}: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(`JSONL line ${index + 1} must be a JSON object.`);
    }
    entries.push(parsed);
  }
  return entries;
}

async function _loadSnapshot(layoutPath, viewport) {
  const tempOut = _pluginSnapshotOutPath(path.basename(layoutPath));
  try {
    await runMmoCli(
      [
        "ui-layout-snapshot",
        "--layout",
        layoutPath,
        "--viewport",
        viewport,
        "--out",
        tempOut,
        "--force",
      ],
      { acceptedExitCodes: [0, 2], timeoutMs: 20_000 },
    );
    const snapshotRaw = await fs.readFile(tempOut, "utf8");
    const parsed = JSON.parse(snapshotRaw);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return null;
    }
    return parsed;
  } finally {
    await fs.unlink(tempOut).catch(() => {});
  }
}

async function _enrichPluginEntry(pluginEntry, pluginsDir, viewport) {
  const entry = pluginEntry && typeof pluginEntry === "object" ? pluginEntry : {};
  const pluginId = typeof entry.plugin_id === "string" ? entry.plugin_id : "";
  if (!pluginId) {
    return {
      ...entry,
      error: "Missing plugin_id in ui_bundle entry.",
    };
  }

  try {
    const pluginDetails = await runMmoCliJson(
      [
        "plugins",
        "show",
        pluginId,
        "--plugins",
        pluginsDir,
        "--format",
        "json",
        "--include-ui-layout-snapshot",
        "--include-ui-hints",
      ],
      { timeoutMs: 20_000 },
    );

    const configSchema = pluginDetails?.config_schema?.schema;
    const uiHints = Array.isArray(pluginDetails?.ui_hints?.hints)
      ? pluginDetails.ui_hints.hints
      : Array.isArray(pluginEntry?.ui_hints?.hints)
        ? pluginEntry.ui_hints.hints
        : [];

    let layoutSnapshot = null;
    const layoutPath = typeof pluginDetails?.ui_layout?.path === "string"
      ? pluginDetails.ui_layout.path
      : null;
    if (layoutPath) {
      layoutSnapshot = await _loadSnapshot(layoutPath, viewport);
    }

    return {
      plugin_id: pluginId,
      plugin_type: entry.plugin_type || "",
      version: entry.version || "",
      config_schema: configSchema && typeof configSchema === "object" ? configSchema : null,
      ui_hints: uiHints,
      ui_layout: pluginDetails?.ui_layout || entry?.ui_layout || null,
      ui_layout_snapshot_meta: pluginDetails?.ui_layout_snapshot || entry?.ui_layout_snapshot || null,
      ui_layout_snapshot: layoutSnapshot,
    };
  } catch (error) {
    return {
      ...entry,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

async function _handleUiBundleRequest(response, body) {
  const uiBundlePathRaw = body.ui_bundle_path;
  if (typeof uiBundlePathRaw !== "string" || !uiBundlePathRaw.trim()) {
    _sendJson(response, 400, { error: "ui_bundle_path must be a non-empty string." });
    return;
  }

  const viewport = typeof body.viewport === "string" && body.viewport.trim()
    ? body.viewport.trim()
    : "1280x720";
  const uiBundlePath = path.resolve(uiBundlePathRaw);
  let bundle;
  try {
    const bundleRaw = await fs.readFile(uiBundlePath, "utf8");
    bundle = JSON.parse(bundleRaw);
  } catch (error) {
    _sendJson(response, 400, {
      error: `Failed to read ui_bundle JSON: ${error instanceof Error ? error.message : String(error)}`,
    });
    return;
  }
  if (bundle === null || typeof bundle !== "object" || Array.isArray(bundle)) {
    _sendJson(response, 400, { error: "ui_bundle JSON must be an object." });
    return;
  }

  const pluginsPayload = bundle.plugins;
  const pluginEntries = Array.isArray(pluginsPayload?.entries) ? pluginsPayload.entries : [];
  const pluginsDir = typeof pluginsPayload?.plugins_dir === "string" && pluginsPayload.plugins_dir.trim()
    ? pluginsPayload.plugins_dir
    : "plugins";

  const enrichedPlugins = await Promise.all(
    pluginEntries.map((entry) => _enrichPluginEntry(entry, pluginsDir, viewport)),
  );

  _sendJson(response, 200, {
    ui_bundle_path: _pathToPosix(uiBundlePath),
    ui_bundle: bundle,
    plugins: enrichedPlugins,
  });
}

async function _handleRenderRequestRead(response, body) {
  const renderRequestPathRaw = body.render_request_path;
  if (typeof renderRequestPathRaw !== "string" || !renderRequestPathRaw.trim()) {
    _sendJson(response, 400, { error: "render_request_path must be a non-empty string." });
    return;
  }
  const renderRequestPath = path.resolve(renderRequestPathRaw);
  if (!_looksLikeRenderRequestPath(renderRequestPath)) {
    _sendJson(response, 400, {
      error: "render_request_path must point to renders/render_request.json.",
    });
    return;
  }

  let payload;
  try {
    const raw = await fs.readFile(renderRequestPath, "utf8");
    payload = JSON.parse(raw);
  } catch (error) {
    _sendJson(response, 400, {
      error: `Failed to read render_request JSON: ${error instanceof Error ? error.message : String(error)}`,
    });
    return;
  }
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    _sendJson(response, 400, { error: "render_request JSON must be an object." });
    return;
  }

  _sendJson(response, 200, {
    render_request_path: _pathToPosix(renderRequestPath),
    render_request: payload,
  });
}

async function _handleRenderArtifactRead(response, body) {
  const artifactPathRaw = body.artifact_path;
  if (typeof artifactPathRaw !== "string" || !artifactPathRaw.trim()) {
    _sendJson(response, 400, { error: "artifact_path must be a non-empty string." });
    return;
  }

  const artifactPath = path.resolve(artifactPathRaw);
  const artifactInfo = _renderArtifactInfo(artifactPath);
  if (!artifactInfo) {
    _sendJson(response, 400, {
      error: "artifact_path must point to an allowlisted renders artifact file.",
    });
    return;
  }

  let raw;
  try {
    raw = await fs.readFile(artifactPath, "utf8");
  } catch (error) {
    _sendJson(response, 400, {
      error: `Failed to read render artifact: ${error instanceof Error ? error.message : String(error)}`,
    });
    return;
  }

  let artifact;
  const format = artifactInfo.artifactName.endsWith(".jsonl") ? "jsonl" : "json";
  try {
    artifact = format === "jsonl" ? _parseJsonLines(raw) : JSON.parse(raw);
  } catch (error) {
    _sendJson(response, 400, {
      error: `Failed to parse render artifact: ${error instanceof Error ? error.message : String(error)}`,
    });
    return;
  }

  if (format === "json" && (artifact === null || typeof artifact !== "object")) {
    _sendJson(response, 400, { error: "Render artifact JSON must be an object or array." });
    return;
  }

  _sendJson(response, 200, {
    artifact_name: artifactInfo.artifactName,
    artifact_path: artifactInfo.normalizedPath,
    format,
    artifact,
  });
}

async function _handleApiRequest(request, response, pathname) {
  if (request.method === "POST" && pathname === "/api/rpc") {
    let body;
    try {
      body = await _readJsonBody(request);
    } catch (error) {
      _sendJson(response, 400, {
        error: error instanceof Error ? error.message : String(error),
      });
      return true;
    }

    const method = body.method;
    if (typeof method !== "string" || !method.trim()) {
      _sendJson(response, 400, { error: "method must be a non-empty string." });
      return true;
    }
    const params = body.params && typeof body.params === "object" && !Array.isArray(body.params)
      ? body.params
      : {};

    try {
      const rpcResponse = await _rpcClient.sendRequest(method.trim(), params);
      _sendJson(response, 200, { response: rpcResponse });
    } catch (error) {
      _sendJson(response, 500, {
        error: error instanceof Error ? error.message : String(error),
      });
    }
    return true;
  }

  if (request.method === "POST" && pathname === "/api/ui-bundle") {
    let body;
    try {
      body = await _readJsonBody(request);
    } catch (error) {
      _sendJson(response, 400, {
        error: error instanceof Error ? error.message : String(error),
      });
      return true;
    }
    await _handleUiBundleRequest(response, body);
    return true;
  }

  if (request.method === "POST" && pathname === "/api/render-request") {
    let body;
    try {
      body = await _readJsonBody(request);
    } catch (error) {
      _sendJson(response, 400, {
        error: error instanceof Error ? error.message : String(error),
      });
      return true;
    }
    await _handleRenderRequestRead(response, body);
    return true;
  }

  if (request.method === "POST" && pathname === "/api/render-artifact") {
    let body;
    try {
      body = await _readJsonBody(request);
    } catch (error) {
      _sendJson(response, 400, {
        error: error instanceof Error ? error.message : String(error),
      });
      return true;
    }
    await _handleRenderArtifactRead(response, body);
    return true;
  }

  return false;
}

async function _serveStatic(response, pathname) {
  const localPath = _safeStaticPath(pathname);
  if (!localPath) {
    _sendText(response, 404, "Not found.");
    return;
  }
  try {
    const data = await fs.readFile(localPath);
    const ext = path.extname(localPath);
    const contentType = _MIME_TYPES[ext] || "application/octet-stream";
    _sendText(response, 200, data, contentType);
  } catch {
    _sendText(response, 404, "Not found.");
  }
}

const server = http.createServer(async (request, response) => {
  const requestUrl = new URL(request.url || "/", "http://localhost");
  try {
    const handledApi = await _handleApiRequest(request, response, requestUrl.pathname);
    if (handledApi) {
      return;
    }
    if (request.method !== "GET") {
      _sendText(response, 405, "Method not allowed.");
      return;
    }
    await _serveStatic(response, requestUrl.pathname);
  } catch (error) {
    _sendJson(response, 500, {
      error: error instanceof Error ? error.message : String(error),
    });
  }
});

server.listen(_PORT, () => {
  // eslint-disable-next-line no-console
  console.log(`MMO GUI dev shell listening on http://localhost:${_PORT}`);
});

async function _shutdown() {
  await _rpcClient.stop().catch(() => {});
  await new Promise((resolve) => server.close(() => resolve()));
}

process.on("SIGINT", async () => {
  await _shutdown();
  process.exit(0);
});

process.on("SIGTERM", async () => {
  await _shutdown();
  process.exit(0);
});
