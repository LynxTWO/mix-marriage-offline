import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { promises as fs } from "node:fs";

function _toPosix(value) {
  return value.replace(/\\/g, "/");
}

async function _mkdtempRooted(prefix) {
  const roots = [
    os.tmpdir(),
    path.resolve(process.cwd(), ".mmo_tmp", "gui_tests"),
  ];
  let lastError = null;
  for (const root of roots) {
    try {
      await fs.mkdir(root, { recursive: true });
      return await fs.mkdtemp(path.join(root, prefix));
    } catch (error) {
      lastError = error;
    }
  }
  if (lastError) {
    throw lastError;
  }
  throw new Error("Failed to create temporary test directory.");
}

async function _pickPort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  await new Promise((resolve) => server.close(() => resolve()));
  if (!port) {
    throw new Error("Failed to allocate a test port.");
  }
  return port;
}

async function _startGuiServer(port, { env = {} } = {}) {
  const child = spawn(
    process.execPath,
    ["server.mjs"],
    {
      cwd: path.resolve(process.cwd()),
      env: {
        ...process.env,
        ...env,
        GUI_DEV_PORT: String(port),
      },
      stdio: ["ignore", "ignore", "ignore"],
    },
  );
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`GUI server exited before startup (code=${child.exitCode}).`);
    }
    try {
      const response = await _httpRequest({ port, pathname: "/" });
      if (response.statusCode > 0) {
        return child;
      }
    } catch {
      // Keep polling until deadline.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Timed out waiting for GUI server startup.");
}

async function _stopGuiServer(child) {
  if (!child || child.exitCode !== null) {
    return;
  }
  child.kill("SIGTERM");
  await Promise.race([
    once(child, "exit"),
    new Promise((resolve) => setTimeout(resolve, 3_000)),
  ]);
  if (child.exitCode === null) {
    child.kill();
    await Promise.race([
      once(child, "exit"),
      new Promise((resolve) => setTimeout(resolve, 3_000)),
    ]);
  }
}

async function _httpRequest({ port, pathname, headers = {} }) {
  return new Promise((resolve, reject) => {
    const request = http.request(
      {
        hostname: "127.0.0.1",
        method: "GET",
        path: pathname,
        port,
        headers,
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(Buffer.from(chunk)));
        response.on("end", () => {
          resolve({
            body: Buffer.concat(chunks),
            headers: response.headers,
            statusCode: response.statusCode || 0,
          });
        });
      },
    );
    request.setTimeout(2_000, () => {
      request.destroy(new Error("HTTP request timed out."));
    });
    request.on("error", reject);
    request.end();
  });
}

async function _writeRenderExecuteFixture(rendersDir, audioPath) {
  await fs.writeFile(
    path.join(rendersDir, "render_execute.json"),
    `${JSON.stringify(
      {
        schema_version: "0.1.0",
        run_id: "RUN.0123456789abcdef",
        request_sha256: "0".repeat(64),
        plan_sha256: "1".repeat(64),
        jobs: [
          {
            job_id: "JOB.001",
            inputs: [{ path: _toPosix(audioPath), sha256: "2".repeat(64) }],
            outputs: [{ path: _toPosix(audioPath), sha256: "3".repeat(64) }],
            ffmpeg_version: "ffmpeg test",
            ffmpeg_commands: [{ args: ["ffmpeg", "-i", "in.wav", "out.wav"], determinism_flags: [] }],
          },
        ],
      },
      null,
      2,
    )}\n`,
  );
}

async function _testAudioStreamAllowlistAndRange() {
  const tempRoot = await _mkdtempRooted("mmo_gui_audio_stream_");
  const projectDir = path.join(tempRoot, "project");
  const rendersDir = path.join(projectDir, "renders");
  const audioPath = path.join(projectDir, "renders", "outputs", "audition.wav");
  const audioBytes = Buffer.from("0123456789abcdefghijklmnopqrstuvwxyz");

  await fs.mkdir(path.dirname(audioPath), { recursive: true });
  await fs.writeFile(audioPath, audioBytes);
  await _writeRenderExecuteFixture(rendersDir, audioPath);

  const port = await _pickPort();
  const server = await _startGuiServer(port);
  try {
    const rejectArbitraryPath = await _httpRequest({
      port,
      pathname: `/api/audio-stream?path=${encodeURIComponent(_toPosix(audioPath))}`,
    });
    assert.equal(rejectArbitraryPath.statusCode, 400);
    assert.match(rejectArbitraryPath.body.toString("utf8"), /project_dir must be a non-empty string/i);

    const fullResponse = await _httpRequest({
      port,
      pathname: `/api/audio-stream?project_dir=${encodeURIComponent(_toPosix(projectDir))}&job_id=JOB.001&stream=output&slot=0`,
    });
    assert.equal(fullResponse.statusCode, 200);
    assert.equal(fullResponse.headers["accept-ranges"], "bytes");
    assert.equal(fullResponse.headers["x-mmo-audio-sha256"], "3".repeat(64));
    assert.deepEqual(fullResponse.body, audioBytes);

    const rangeResponse = await _httpRequest({
      port,
      pathname: `/api/audio-stream?project_dir=${encodeURIComponent(_toPosix(projectDir))}&job_id=JOB.001&stream=output&slot=0`,
      headers: {
        Range: "bytes=2-7",
      },
    });
    assert.equal(rangeResponse.statusCode, 206);
    assert.equal(rangeResponse.headers["content-range"], `bytes 2-7/${audioBytes.length}`);
    assert.equal(rangeResponse.headers["content-length"], "6");
    assert.deepEqual(rangeResponse.body, audioBytes.subarray(2, 8));
  } finally {
    await _stopGuiServer(server);
    await fs.rm(tempRoot, { recursive: true, force: true });
  }
}

async function _testAudioStreamRejectsExternalPathByDefault() {
  const tempRoot = await _mkdtempRooted("mmo_gui_audio_stream_external_");
  const projectDir = path.join(tempRoot, "project");
  const rendersDir = path.join(projectDir, "renders");
  const externalAudioPath = path.join(tempRoot, "external", "audition.wav");
  const audioBytes = Buffer.from("ABCDEFGHIJKLMNOPQRSTUVWXYZ");

  await fs.mkdir(path.dirname(externalAudioPath), { recursive: true });
  await fs.mkdir(rendersDir, { recursive: true });
  await fs.writeFile(externalAudioPath, audioBytes);
  await _writeRenderExecuteFixture(rendersDir, externalAudioPath);

  const port = await _pickPort();
  const server = await _startGuiServer(port);
  try {
    const response = await _httpRequest({
      port,
      pathname: `/api/audio-stream?project_dir=${encodeURIComponent(_toPosix(projectDir))}&job_id=JOB.001&stream=output&slot=0`,
    });
    assert.equal(response.statusCode, 403);
    assert.match(
      response.body.toString("utf8"),
      /MMO_GUI_ALLOW_EXTERNAL_OUTPUT_PATHS=1/i,
    );
  } finally {
    await _stopGuiServer(server);
    await fs.rm(tempRoot, { recursive: true, force: true });
  }
}

async function _testAudioStreamAllowsExternalPathWhenOptInEnabled() {
  const tempRoot = await _mkdtempRooted("mmo_gui_audio_stream_external_optin_");
  const projectDir = path.join(tempRoot, "project");
  const rendersDir = path.join(projectDir, "renders");
  const externalAudioPath = path.join(tempRoot, "external", "audition.wav");
  const audioBytes = Buffer.from("0123456789");

  await fs.mkdir(path.dirname(externalAudioPath), { recursive: true });
  await fs.mkdir(rendersDir, { recursive: true });
  await fs.writeFile(externalAudioPath, audioBytes);
  await _writeRenderExecuteFixture(rendersDir, externalAudioPath);

  const port = await _pickPort();
  const server = await _startGuiServer(port, {
    env: {
      MMO_GUI_ALLOW_EXTERNAL_OUTPUT_PATHS: "1",
    },
  });
  try {
    const response = await _httpRequest({
      port,
      pathname: `/api/audio-stream?project_dir=${encodeURIComponent(_toPosix(projectDir))}&job_id=JOB.001&stream=output&slot=0`,
    });
    assert.equal(response.statusCode, 200);
    assert.equal(response.headers["x-mmo-audio-sha256"], "3".repeat(64));
    assert.deepEqual(response.body, audioBytes);
  } finally {
    await _stopGuiServer(server);
    await fs.rm(tempRoot, { recursive: true, force: true });
  }
}

export async function run() {
  await _testAudioStreamAllowlistAndRange();
  await _testAudioStreamRejectsExternalPathByDefault();
  await _testAudioStreamAllowsExternalPathWhenOptInEnabled();
}
