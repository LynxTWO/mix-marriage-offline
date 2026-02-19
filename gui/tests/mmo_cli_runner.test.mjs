import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import process from "node:process";
import { PassThrough, Writable } from "node:stream";

import { buildCliCandidates, runMmoCli } from "../lib/mmo_cli_runner.mjs";

function _candidate({
  command = process.execPath,
  baseArgs = [],
  label = "",
} = {}) {
  return {
    command,
    baseArgs,
    cwd: process.cwd(),
    env: { ...process.env },
    label,
  };
}

function _withEnv(overrides, run) {
  const keys = Object.keys(overrides);
  const previous = new Map(keys.map((key) => [key, process.env[key]]));
  try {
    for (const [key, value] of Object.entries(overrides)) {
      if (typeof value === "string") {
        process.env[key] = value;
      } else {
        delete process.env[key];
      }
    }
    run();
  } finally {
    for (const key of keys) {
      const value = previous.get(key);
      if (typeof value === "string") {
        process.env[key] = value;
      } else {
        delete process.env[key];
      }
    }
  }
}

function _testBuildCliCandidatesKeepsPythonModuleFallback() {
  _withEnv(
    {
      MMO_GUI_MMO_BIN: "mmo-custom",
      MMO_GUI_PYTHON_BIN: "python-custom",
    },
    () => {
      const candidates = buildCliCandidates();
      assert.equal(candidates.length, 2);
      assert.equal(candidates[0].label, "mmo-custom");
      assert.equal(candidates[1].command, "python-custom");
      assert.deepEqual(candidates[1].baseArgs, ["-m", "mmo"]);
      assert.equal(candidates[1].label, "python-custom -m mmo");
    },
  );
}

async function _testRunMmoCliFailureSummaryListsFallbackCandidates() {
  const spawnProcess = _fakeSpawnFactory([
    { code: 2, stderr: "mmo failed" },
    { code: 0, stdout: "fallback-ok" },
  ]);
  const candidates = [
    _candidate({
      label: "mmo",
    }),
    _candidate({
      label: "python -m mmo",
    }),
  ];

  const result = await runMmoCli([], {
    candidates,
    acceptedExitCodes: [0],
    timeoutMs: 5_000,
    spawnProcess,
  });
  assert.equal(result.candidate, "python -m mmo");
  assert.equal(result.stdout, "fallback-ok");
}

async function _testRunMmoCliFailureSummaryIncludesPythonFallbackLabel() {
  const spawnProcess = _fakeSpawnFactory([
    { code: 2, stderr: "mmo failed" },
    { code: 4, stderr: "python fallback failed" },
  ]);
  const candidates = [
    _candidate({ label: "mmo" }),
    _candidate({ label: "python -m mmo" }),
  ];

  let raised = null;
  try {
    await runMmoCli([], {
      candidates,
      acceptedExitCodes: [0],
      timeoutMs: 5_000,
      spawnProcess,
    });
  } catch (error) {
    raised = error;
  }
  assert.ok(raised instanceof Error);
  assert.match(raised.message, /mmo: code=2; stderr=mmo failed/);
  assert.match(raised.message, /python -m mmo: code=4; stderr=python fallback failed/);
}

function _fakeChild({ code = 0, stdout = "", stderr = "" } = {}) {
  const child = new EventEmitter();
  const out = new PassThrough();
  const err = new PassThrough();

  child.stdout = out;
  child.stderr = err;
  child.stdin = new Writable({
    write(_chunk, _encoding, callback) {
      callback();
    },
  });
  child.kill = () => {
    child.emit("close", null);
  };

  process.nextTick(() => {
    if (stdout) {
      out.write(stdout);
    }
    if (stderr) {
      err.write(stderr);
    }
    out.end();
    err.end();
    child.emit("close", code);
  });
  return child;
}

function _fakeSpawnFactory(outcomes) {
  const queue = Array.isArray(outcomes) ? [...outcomes] : [];
  return () => {
    const next = queue.length > 0 ? queue.shift() : { code: 1, stderr: "unexpected" };
    return _fakeChild(next);
  };
}

export async function run() {
  _testBuildCliCandidatesKeepsPythonModuleFallback();
  await _testRunMmoCliFailureSummaryListsFallbackCandidates();
  await _testRunMmoCliFailureSummaryIncludesPythonFallbackLabel();
}
