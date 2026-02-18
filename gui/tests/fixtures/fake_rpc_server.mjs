import readline from "node:readline";

const input = readline.createInterface({
  input: process.stdin,
  crlfDelay: Infinity,
});

function respond(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

for await (const line of input) {
  const trimmed = line.trim();
  if (!trimmed) {
    continue;
  }

  let request;
  try {
    request = JSON.parse(trimmed);
  } catch {
    respond({
      id: null,
      ok: false,
      error: {
        code: "RPC.INVALID_JSON",
        message: "Invalid JSON request.",
      },
    });
    continue;
  }

  const method = request.method;
  const id = request.id ?? null;

  if (method === "rpc.discover") {
    respond({
      id,
      ok: true,
      result: {
        rpc_version: "1",
        server_build: "fake",
        methods: ["env.doctor", "rpc.discover"],
      },
    });
    continue;
  }

  if (method === "env.doctor") {
    respond({
      id,
      ok: true,
      result: {
        checks: [{ check_id: "CHECK.FAKE.OK", status: "ok" }],
      },
    });
    continue;
  }

  respond({
    id,
    ok: false,
    error: {
      code: "RPC.UNKNOWN_METHOD",
      message: `Unknown method: ${method}`,
    },
  });
}
