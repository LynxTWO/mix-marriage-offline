import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import process from "node:process";
import { PassThrough, Writable } from "node:stream";

import { RpcProcessClient } from "../lib/rpc_process_client.mjs";

function _candidate(command, label) {
  return {
    command,
    args: [],
    cwd: process.cwd(),
    env: { ...process.env },
    label,
  };
}

function _fakeRpcChild() {
  const child = new EventEmitter();
  const stdout = new PassThrough();
  const stderr = new PassThrough();

  let closed = false;
  let buffer = "";
  const stdin = new Writable({
    write(chunk, _encoding, callback) {
      buffer += chunk.toString("utf8");
      while (true) {
        const newline = buffer.indexOf("\n");
        if (newline < 0) {
          break;
        }
        const line = buffer.slice(0, newline).trim();
        buffer = buffer.slice(newline + 1);
        if (!line) {
          continue;
        }
        let request;
        try {
          request = JSON.parse(line);
        } catch {
          stdout.write(JSON.stringify({
            id: null,
            ok: false,
            error: { code: "RPC.INVALID_JSON", message: "Invalid JSON request." },
          }) + "\n");
          continue;
        }
        const method = request.method;
        if (method === "rpc.discover") {
          stdout.write(JSON.stringify({
            id: request.id,
            ok: true,
            result: {
              rpc_version: "1",
              server_build: "fake",
              methods: ["env.doctor", "rpc.discover"],
            },
          }) + "\n");
        } else if (method === "env.doctor") {
          stdout.write(JSON.stringify({
            id: request.id,
            ok: true,
            result: {
              checks: [{ check_id: "CHECK.FAKE.OK", status: "ok" }],
            },
          }) + "\n");
        } else {
          stdout.write(JSON.stringify({
            id: request.id,
            ok: false,
            error: {
              code: "RPC.UNKNOWN_METHOD",
              message: `Unknown method: ${method}`,
            },
          }) + "\n");
        }
      }
      callback();
    },
  });

  child.stdout = stdout;
  child.stderr = stderr;
  child.stdin = stdin;
  child.kill = () => {
    if (closed) {
      return;
    }
    closed = true;
    process.nextTick(() => {
      child.emit("close", 0, null);
    });
  };

  return child;
}

function _fakeSpawn() {
  return (command) => {
    if (command === "missing-command") {
      const child = _fakeRpcChild();
      process.nextTick(() => {
        child.emit("error", new Error("ENOENT"));
        child.emit("close", null, null);
      });
      return child;
    }
    return _fakeRpcChild();
  };
}

async function _testRpcProcessClientStartsAndHandlesRequests() {
  const client = new RpcProcessClient({
    startupTimeoutMs: 2_000,
    spawnProcess: _fakeSpawn(),
    candidates: [
      _candidate("missing-command", "missing"),
      _candidate("working-command", "fake-rpc"),
    ],
  });

  try {
    const discover = await client.sendRequest("rpc.discover", {});
    assert.equal(discover.ok, true);
    assert.deepEqual(discover.result.methods, ["env.doctor", "rpc.discover"]);

    const doctor = await client.sendRequest("env.doctor", {});
    assert.equal(doctor.ok, true);
    assert.equal(Array.isArray(doctor.result.checks), true);

    const unknown = await client.sendRequest("project.nope", {});
    assert.equal(unknown.ok, false);
    assert.equal(unknown.error.code, "RPC.UNKNOWN_METHOD");
  } finally {
    await client.stop();
  }
}

export async function run() {
  await _testRpcProcessClientStartsAndHandlesRequests();
}
