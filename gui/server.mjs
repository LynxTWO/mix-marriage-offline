import http from "node:http";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { createReadStream, promises as fs } from "node:fs";
import { fileURLToPath } from "node:url";

import { runMmoCli, runMmoCliJson } from "./lib/mmo_cli_runner.mjs";
import { RpcProcessClient } from "./lib/rpc_process_client.mjs";

const _SERVER_ROOT = path.dirname(fileURLToPath(import.meta.url));
const _WEB_ROOT = path.join(_SERVER_ROOT, "web");
const _PORT = Number.parseInt(process.env.GUI_DEV_PORT || "4175", 10);
const _ALLOW_EXTERNAL_OUTPUT_PATHS = _envFlagEnabled(process.env.MMO_GUI_ALLOW_EXTERNAL_OUTPUT_PATHS);
const _PROJECT_OUTPUT_ROOT_SEGMENTS = ["renders", "outputs"];

const _rpcClient = new RpcProcessClient();

const _MIME_TYPES = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
};

const _AUDIO_MIME_TYPES = {
  ".aiff": "audio/aiff",
  ".flac": "audio/flac",
  ".m4a": "audio/mp4",
  ".mp3": "audio/mpeg",
  ".ogg": "audio/ogg",
  ".wav": "audio/wav",
};

const _ALLOWED_RENDER_ARTIFACT_NAMES = new Set([
  "event_log.jsonl",
  "render_execute.json",
  "render_plan.json",
  "render_preflight.json",
  "render_report.json",
  "render_request.json",
]);

function _envFlagEnabled(rawValue) {
  if (typeof rawValue !== "string" || !rawValue.trim()) {
    return false;
  }
  const normalized = rawValue.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

function _pathToPosix(pathValue) {
  return pathValue.replace(/\\/g, "/");
}

async function _resolveRealPathOrAbsolute(pathValue) {
  try {
    return await fs.realpath(pathValue);
  } catch {
    return path.resolve(pathValue);
  }
}

function _isPathInsideRoot(candidatePath, rootPath) {
  const relative = path.relative(path.resolve(rootPath), path.resolve(candidatePath));
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
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
    // The dev shell only serves checked-in helper modules from gui/lib.
    // Keep this containment check strict so browser requests cannot walk
    // outside the repo-owned bridge code.
    const localPath = path.resolve(_SERVER_ROOT, `.${normalizedUrlPath}`);
    const relative = path.relative(_SERVER_ROOT, localPath);
    if (relative.startsWith("..") || path.isAbsolute(relative)) {
      return null;
    }
    return localPath;
  }

  const relativePath = normalizedUrlPath === "/" ? "/index.html" : normalizedUrlPath;
  // Everything else must stay inside gui/web so static requests cannot
  // turn into arbitrary local file reads.
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

async function _loadJsonObject(pathValue) {
  const raw = await fs.readFile(pathValue, "utf8");
  const parsed = JSON.parse(raw);
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return null;
  }
  return parsed;
}

function _looksLikeRenderRequestPath(pathValue) {
  const normalized = _pathToPosix(path.resolve(pathValue));
  // This endpoint is read-only and intentionally narrow. It exists to inspect
  // the canonical project render_request artifact, not arbitrary JSON files.
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
  // Keep the artifact allowlist explicit so new bridge reads are a reviewable
  // code change instead of an accidental filename convention.
  return {
    artifactName,
    normalizedPath: normalized,
  };
}

function _audioMimeType(audioPath) {
  const ext = path.extname(audioPath).toLowerCase();
  return _AUDIO_MIME_TYPES[ext] || "application/octet-stream";
}

function _parseSlot(rawValue) {
  const text = typeof rawValue === "string" ? rawValue.trim() : "";
  if (!text) {
    return 0;
  }
  if (!/^\d+$/.test(text)) {
    return null;
  }
  return Number.parseInt(text, 10);
}

function _parseRangeHeader(rangeHeader, fileSize) {
  if (!rangeHeader || typeof rangeHeader !== "string") {
    return null;
  }
  const trimmed = rangeHeader.trim();
  if (!trimmed) {
    return null;
  }
  const match = trimmed.match(/^bytes=(\d*)-(\d*)$/i);
  if (!match) {
    return { invalid: true };
  }

  const startText = match[1];
  const endText = match[2];
  if (!startText && !endText) {
    return { invalid: true };
  }

  let start;
  let end;
  if (!startText) {
    const suffixLength = Number.parseInt(endText, 10);
    if (!Number.isFinite(suffixLength) || suffixLength <= 0) {
      return { invalid: true };
    }
    const clampedLength = Math.min(suffixLength, fileSize);
    start = Math.max(fileSize - clampedLength, 0);
    end = fileSize - 1;
  } else {
    start = Number.parseInt(startText, 10);
    if (!Number.isFinite(start) || start < 0) {
      return { invalid: true };
    }
    if (!endText) {
      end = fileSize - 1;
    } else {
      end = Number.parseInt(endText, 10);
      if (!Number.isFinite(end) || end < 0) {
        return { invalid: true };
      }
    }
  }

  if (fileSize <= 0 || start >= fileSize || end < start) {
    return { invalid: true };
  }
  if (end >= fileSize) {
    end = fileSize - 1;
  }
  return { start, end };
}

function _selectedAudioPointer(executePayload, jobId, streamKind, slot) {
  const jobs = Array.isArray(executePayload?.jobs) ? executePayload.jobs : [];
  const job = jobs.find(
    (row) =>
      row &&
      typeof row === "object" &&
      typeof row.job_id === "string" &&
      row.job_id === jobId,
  );
  if (!job || typeof job !== "object") {
    throw new Error(`Unknown job_id: ${jobId}`);
  }

  const pointers = streamKind === "input"
    ? (Array.isArray(job.inputs) ? job.inputs : [])
    : (Array.isArray(job.outputs) ? job.outputs : []);
  if (slot < 0 || slot >= pointers.length) {
    throw new Error(`Slot ${slot} not available for ${streamKind} on ${jobId}`);
  }

  const pointer = pointers[slot];
  if (!pointer || typeof pointer !== "object") {
    throw new Error(`Invalid file pointer for ${streamKind} slot ${slot}`);
  }
  const pathText = typeof pointer.path === "string" ? pointer.path.trim() : "";
  if (!pathText) {
    throw new Error(`Missing path for ${streamKind} slot ${slot}`);
  }
  const sha256 = typeof pointer.sha256 === "string" && pointer.sha256.trim()
    ? pointer.sha256.trim()
    : "";
  return {
    audioPath: path.resolve(pathText),
    jobId,
    sha256,
    slot,
    streamKind,
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
      // Event logs are evidence, not best-effort telemetry. Reject malformed
      // JSONL so the caller sees the artifact drift instead of a partial read.
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
    // Snapshot generation shells out through the same CLI contract the real UI
    // uses, then deletes the temp file on every path.
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
    return await _loadJsonObject(tempOut);
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
    // Pull the richer plugin view from the CLI instead of reconstructing it
    // in Node. That keeps one authority for schema, hints, and layout paths.
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
    let layoutDocument = null;
    const layoutPath = typeof pluginDetails?.ui_layout?.path === "string"
      ? pluginDetails.ui_layout.path
      : null;
    if (layoutPath) {
      // The raw layout doc is optional UI context. Snapshot generation is the
      // only step here with extra CLI side effects.
      try {
        layoutDocument = await _loadJsonObject(layoutPath);
      } catch {
        layoutDocument = null;
      }
      layoutSnapshot = await _loadSnapshot(layoutPath, viewport);
    }

    return {
      plugin_id: pluginId,
      plugin_type: entry.plugin_type || "",
      version: entry.version || "",
      config_schema: configSchema && typeof configSchema === "object" ? configSchema : null,
      ui_hints: uiHints,
      ui_layout: pluginDetails?.ui_layout || entry?.ui_layout || null,
      ui_layout_document: layoutDocument,
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
  // Keep render-request reads pinned to the canonical project artifact. This
  // route is for inspection, not for browsing arbitrary workspace JSON.
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
  // This endpoint only exposes a fixed set of render artifacts that the dev
  // shell knows how to summarize and display safely.
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

async function _handleAudioStreamRequest(request, response, requestUrl) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    _sendText(response, 405, "Method not allowed.");
    return;
  }

  const projectDirRaw = requestUrl.searchParams.get("project_dir");
  const jobIdRaw = requestUrl.searchParams.get("job_id");
  const streamRaw = requestUrl.searchParams.get("stream");
  const slotRaw = requestUrl.searchParams.get("slot");

  const projectDir = typeof projectDirRaw === "string" ? projectDirRaw.trim() : "";
  const jobId = typeof jobIdRaw === "string" ? jobIdRaw.trim() : "";
  const streamKind = typeof streamRaw === "string" ? streamRaw.trim().toLowerCase() : "";
  const slot = _parseSlot(slotRaw);

  if (!projectDir) {
    _sendJson(response, 400, { error: "project_dir must be a non-empty string." });
    return;
  }
  if (!jobId) {
    _sendJson(response, 400, { error: "job_id must be a non-empty string." });
    return;
  }
  if (streamKind !== "input" && streamKind !== "output") {
    _sendJson(response, 400, { error: "stream must be either 'input' or 'output'." });
    return;
  }
  if (!Number.isInteger(slot) || slot < 0) {
    _sendJson(response, 400, { error: "slot must be a non-negative integer." });
    return;
  }

  const resolvedProjectDir = await _resolveRealPathOrAbsolute(projectDir);
  const resolvedProjectOutputRoot = await _resolveRealPathOrAbsolute(
    path.resolve(resolvedProjectDir, ..._PROJECT_OUTPUT_ROOT_SEGMENTS),
  );

  const executePath = path.resolve(projectDir, "renders", "render_execute.json");
  let executePayload;
  try {
    executePayload = await _loadJsonObject(executePath);
  } catch (error) {
    _sendJson(response, 404, {
      error: `Failed to read render_execute JSON: ${error instanceof Error ? error.message : String(error)}`,
    });
    return;
  }
  if (!executePayload) {
    _sendJson(response, 404, { error: "render_execute JSON must be an object." });
    return;
  }

  let selected;
  try {
    // render_execute.json is the pointer authority for playable inputs and
    // outputs. The HTTP layer should not guess paths from query params alone.
    selected = _selectedAudioPointer(executePayload, jobId, streamKind, slot);
  } catch (error) {
    _sendJson(response, 404, { error: error instanceof Error ? error.message : String(error) });
    return;
  }

  const resolvedAudioPath = await _resolveRealPathOrAbsolute(selected.audioPath);
  const insideProjectDir = _isPathInsideRoot(resolvedAudioPath, resolvedProjectDir);
  const insideProjectOutputRoot = _isPathInsideRoot(resolvedAudioPath, resolvedProjectOutputRoot);
  // External output paths stay opt-in because this endpoint streams raw local
  // media. The default contract only trusts files inside the project roots.
  if (!_ALLOW_EXTERNAL_OUTPUT_PATHS && !insideProjectDir && !insideProjectOutputRoot) {
    _sendJson(response, 403, {
      error: (
        "Audio stream path is outside allowed project roots. "
        + "Set MMO_GUI_ALLOW_EXTERNAL_OUTPUT_PATHS=1 to opt in to external paths."
      ),
    });
    return;
  }
  selected.audioPath = resolvedAudioPath;

  let fileStat;
  try {
    fileStat = await fs.stat(selected.audioPath);
  } catch {
    _sendJson(response, 404, { error: `Audio file does not exist: ${selected.audioPath}` });
    return;
  }
  if (!fileStat.isFile()) {
    _sendJson(response, 404, { error: `Audio file is not a regular file: ${selected.audioPath}` });
    return;
  }

  const fileSize = fileStat.size;
  const range = _parseRangeHeader(request.headers.range, fileSize);
  if (range?.invalid) {
    response.statusCode = 416;
    response.setHeader("Accept-Ranges", "bytes");
    response.setHeader("Content-Range", `bytes */${fileSize}`);
    response.end();
    return;
  }

  const baseHeaders = {
    "Accept-Ranges": "bytes",
    "Cache-Control": "no-store",
    "Content-Type": _audioMimeType(selected.audioPath),
    "X-MMO-Audio-SHA256": selected.sha256 || "",
    "X-MMO-Job-ID": selected.jobId,
    "X-MMO-Stream": selected.streamKind,
    "X-MMO-Slot": String(selected.slot),
  };
  for (const [key, value] of Object.entries(baseHeaders)) {
    response.setHeader(key, value);
  }

  if (range) {
    // Support ranged reads so long local files do not need to load in one shot
    // before the browser can start playback or scrubbing.
    const contentLength = range.end - range.start + 1;
    response.statusCode = 206;
    response.setHeader("Content-Length", String(contentLength));
    response.setHeader("Content-Range", `bytes ${range.start}-${range.end}/${fileSize}`);
    if (request.method === "HEAD") {
      response.end();
      return;
    }
    const readStream = createReadStream(selected.audioPath, { start: range.start, end: range.end });
    readStream.on("error", () => {
      if (!response.headersSent) {
        _sendJson(response, 500, { error: "Failed to stream audio." });
        return;
      }
      response.destroy();
    });
    readStream.pipe(response);
    return;
  }

  response.statusCode = 200;
  response.setHeader("Content-Length", String(fileSize));
  if (request.method === "HEAD") {
    response.end();
    return;
  }
  const readStream = createReadStream(selected.audioPath);
  readStream.on("error", () => {
    if (!response.headersSent) {
      _sendJson(response, 500, { error: "Failed to stream audio." });
      return;
    }
    response.destroy();
  });
  readStream.pipe(response);
}

async function _handleApiRequest(request, response, pathname) {
  if (pathname === "/api/audio-stream") {
    const requestUrl = new URL(request.url || "/", "http://localhost");
    await _handleAudioStreamRequest(request, response, requestUrl);
    return true;
  }

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
      // This bridge trusts the local browser and forwards method calls as-is
      // after basic shape checks. It does not add another auth layer.
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
