import { spawn } from "node:child_process";
import readline from "node:readline";

import {
  buildRpcCommandCandidates,
  processErrorSummary,
  publicCandidateLabel,
} from "./mmo_cli_runner.mjs";

const _DEFAULT_TIMEOUT_MS = 15_000;

function _errorMessageText(error) {
  if (error instanceof Error) {
    return error.message;
  }
  return processErrorSummary(error);
}

export class RpcProcessClient {
  constructor({
    candidates = buildRpcCommandCandidates(),
    startupTimeoutMs = 4_000,
    spawnProcess = spawn,
  } = {}) {
    this._candidates = candidates;
    this._startupTimeoutMs = startupTimeoutMs;
    this._spawnProcess = spawnProcess;

    this._child = null;
    this._reader = null;
    this._pending = new Map();
    this._nextId = 1;
    this._stderrLineCount = 0;
    this._stderrPresent = false;
    this._startingPromise = null;
    this._stopping = false;
    this._activeLabel = "";
  }

  async start() {
    if (this._child !== null) {
      return;
    }
    if (this._startingPromise !== null) {
      return this._startingPromise;
    }
    this._startingPromise = this._startInternal();
    try {
      await this._startingPromise;
    } finally {
      this._startingPromise = null;
    }
  }

  async _startInternal() {
    const failures = [];
    for (const candidate of this._candidates) {
      try {
        // Try each CLI launch shape in order and keep the failure list. Startup
        // errors here are usually environment drift, not RPC payload bugs.
        await this._startCandidate(candidate);
        return;
      } catch (error) {
        failures.push(`${publicCandidateLabel(candidate)}: ${_errorMessageText(error)}`);
        await this.stop();
      }
    }
    throw new Error(`Failed to start mmo gui rpc subprocess.\n${failures.join("\n")}`);
  }

  async _startCandidate(candidate) {
    const child = this._spawnProcess(candidate.command, candidate.args, {
      cwd: candidate.cwd,
      env: candidate.env,
      stdio: ["pipe", "pipe", "pipe"],
    });

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");

    this._child = child;
    this._activeLabel = publicCandidateLabel(candidate);
    this._stderrLineCount = 0;
    this._stderrPresent = false;
    this._bindChild(child);

    // The client is not live until rpc.discover succeeds. That handshake proves
    // the subprocess can parse requests and return framed JSON responses.
    await this._sendRequestInternal("rpc.discover", {}, this._startupTimeoutMs);
  }

  _bindChild(child) {
    this._reader = readline.createInterface({ input: child.stdout });
    this._reader.on("line", (line) => {
      this._handleLine(line);
    });

    child.stderr.on("data", (chunk) => {
      const lines = String(chunk).split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
      if (lines.length === 0) {
        return;
      }
      this._stderrPresent = true;
      this._stderrLineCount += lines.length;
    });

    child.on("error", (error) => {
      this._rejectAllPending(
        new Error(
          `RPC process error (${this._activeLabel}): ${processErrorSummary(error)}`,
        ),
      );
    });

    child.on("close", (code, signal) => {
      const reason = [
        `RPC process exited (${this._activeLabel})`,
        `code=${code === null ? "null" : String(code)}`,
        `signal=${signal === null ? "null" : String(signal)}`,
      ].join(", ");
      const stderrText = this._stderrPresent
        ? `stderr_present=true, stderr_lines=${this._stderrLineCount}`
        : "stderr_present=false";
      const message = `${reason}, ${stderrText}`;
      if (!this._stopping) {
        this._rejectAllPending(new Error(message));
      } else {
        this._clearPending();
      }
      this._child = null;
      if (this._reader !== null) {
        this._reader.close();
        this._reader = null;
      }
    });
  }

  _handleLine(line) {
    const trimmed = line.trim();
    if (!trimmed) {
      return;
    }

    let payload;
    try {
      payload = JSON.parse(trimmed);
    } catch {
      return;
    }
    if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
      return;
    }
    const id = payload.id;
    // Match replies by request ID so overlapping browser calls cannot resolve
    // the wrong pending promise.
    if (!this._pending.has(id)) {
      return;
    }
    const pending = this._pending.get(id);
    clearTimeout(pending.timer);
    this._pending.delete(id);
    pending.resolve(payload);
  }

  _sendRequestInternal(method, params, timeoutMs) {
    if (this._child === null) {
      return Promise.reject(new Error("RPC process is not running."));
    }
    const requestId = `rpc-${this._nextId++}`;
    const request = {
      id: requestId,
      method,
      params: params && typeof params === "object" ? params : {},
    };

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        // Timeouts must clear the pending entry first so a late line from the
        // subprocess cannot resolve a promise the caller already gave up on.
        this._pending.delete(requestId);
        reject(new Error(`RPC request timed out (${method}) after ${timeoutMs}ms.`));
      }, timeoutMs);
      this._pending.set(requestId, { resolve, reject, timer });
      try {
        this._child.stdin.write(`${JSON.stringify(request)}\n`, "utf8");
      } catch (error) {
        clearTimeout(timer);
        this._pending.delete(requestId);
        reject(error);
      }
    });
  }

  async sendRequest(method, params = {}, { timeoutMs = _DEFAULT_TIMEOUT_MS } = {}) {
    await this.start();
    return this._sendRequestInternal(method, params, timeoutMs);
  }

  _rejectAllPending(error) {
    for (const pending of this._pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this._pending.clear();
  }

  _clearPending() {
    for (const pending of this._pending.values()) {
      clearTimeout(pending.timer);
    }
    this._pending.clear();
  }

  async stop() {
    this._stopping = true;
    // Clear pending callers before killing the subprocess so the browser does
    // not keep promises alive after an intentional shutdown.
    this._clearPending();

    if (this._reader !== null) {
      this._reader.close();
      this._reader = null;
    }

    if (this._child !== null) {
      const child = this._child;
      this._child = null;
      await new Promise((resolve) => {
        child.once("close", () => resolve());
        child.kill();
      });
    }
    this._stopping = false;
  }
}
