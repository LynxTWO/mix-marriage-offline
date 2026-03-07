import { Command } from "@tauri-apps/plugin-shell";

type DoctorCheckKey = "version" | "plugins" | "paths";

type CommandOutput = {
  code: number | null;
  signal: number | null;
  stderr: string;
  stdout: string;
};

type PluginValidationPayload = {
  issue_counts?: { error?: number };
  ok?: boolean;
  plugin_count?: number;
  plugins_dir?: string;
};

type EnvDoctorPayload = {
  paths?: Record<string, string>;
  python?: { executable?: string; version?: string };
};

type DoctorUi = {
  button: HTMLButtonElement;
  outputs: Record<DoctorCheckKey, HTMLElement>;
  statuses: Record<DoctorCheckKey, HTMLElement>;
  summary: HTMLElement;
};

const SIDECAR_NAME = "binaries/mmo";

function checkElements(): DoctorUi {
  const button = document.querySelector<HTMLButtonElement>("#doctor-run-button");
  const summary = document.querySelector<HTMLElement>("#doctor-summary");
  const outputs = {
    version: document.querySelector<HTMLElement>("#output-version"),
    plugins: document.querySelector<HTMLElement>("#output-plugins"),
    paths: document.querySelector<HTMLElement>("#output-paths"),
  };
  const statuses = {
    version: document.querySelector<HTMLElement>("#status-version"),
    plugins: document.querySelector<HTMLElement>("#status-plugins"),
    paths: document.querySelector<HTMLElement>("#status-paths"),
  };

  if (
    !button ||
    !summary ||
    !outputs.version ||
    !outputs.plugins ||
    !outputs.paths ||
    !statuses.version ||
    !statuses.plugins ||
    !statuses.paths
  ) {
    throw new Error("Doctor UI is missing required DOM nodes.");
  }

  return {
    button,
    summary,
    outputs: outputs as Record<DoctorCheckKey, HTMLElement>,
    statuses: statuses as Record<DoctorCheckKey, HTMLElement>,
  };
}

function normalizeOutput(output: CommandOutput): CommandOutput {
  return {
    code: output.code,
    signal: output.signal,
    stderr: output.stderr.trim(),
    stdout: output.stdout.trim(),
  };
}

async function runSidecar(args: string[]): Promise<CommandOutput> {
  const result = await Command.sidecar(SIDECAR_NAME, args).execute();
  return normalizeOutput(result);
}

function renderCommandOutput(output: CommandOutput): string {
  const lines = [
    `exit=${output.code ?? "null"} signal=${output.signal ?? "null"}`,
    output.stdout ? `stdout: ${output.stdout}` : "stdout: <empty>",
  ];
  if (output.stderr) {
    lines.push(`stderr: ${output.stderr}`);
  }
  return lines.join("\n");
}

function setStatus(
  element: HTMLElement,
  state: "idle" | "running" | "pass" | "fail",
  label: string
): void {
  element.textContent = label;
  element.className = `doctor-status doctor-status-${state}`;
}

function renderPathRows(container: HTMLElement, rows: Array<[string, string]>): void {
  container.innerHTML = "";
  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "path-row";

    const dt = document.createElement("dt");
    dt.textContent = label;

    const dd = document.createElement("dd");
    dd.textContent = value;

    row.append(dt, dd);
    container.append(row);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  const { button, summary, outputs, statuses } = checkElements();

  button.addEventListener("click", async () => {
    button.disabled = true;
    summary.textContent = "Running MMO sidecar doctor checks.";
    outputs.version.textContent = "Launching sidecar...";
    outputs.plugins.textContent = "Waiting for plugin validation...";
    renderPathRows(outputs.paths, [["Waiting", "Waiting for env doctor output."]]);
    setStatus(statuses.version, "running", "Running");
    setStatus(statuses.plugins, "idle", "Queued");
    setStatus(statuses.paths, "idle", "Queued");

    try {
      const versionOutput = await runSidecar(["--version"]);
      outputs.version.textContent = renderCommandOutput(versionOutput);
      setStatus(
        statuses.version,
        versionOutput.code === 0 ? "pass" : "fail",
        versionOutput.code === 0 ? "Pass" : "Fail"
      );

      setStatus(statuses.plugins, "running", "Running");
      const pluginsOutput = await runSidecar([
        "plugins",
        "validate",
        "--bundled-only",
        "--format",
        "json",
      ]);
      let pluginsSummary = renderCommandOutput(pluginsOutput);
      let pluginsPayload: PluginValidationPayload | null = null;
      if (pluginsOutput.stdout) {
        try {
          pluginsPayload = JSON.parse(pluginsOutput.stdout) as PluginValidationPayload;
          pluginsSummary = [
            `exit=${pluginsOutput.code ?? "null"} signal=${pluginsOutput.signal ?? "null"}`,
            `ok=${pluginsPayload.ok === true}`,
            `plugin_count=${pluginsPayload.plugin_count ?? 0}`,
            `plugins_dir=${pluginsPayload.plugins_dir ?? "-"}`,
            `errors=${pluginsPayload.issue_counts?.error ?? 0}`,
          ].join("\n");
        } catch (error) {
          pluginsSummary = `${pluginsSummary}\nparse_error=${String(error)}`;
        }
      }
      outputs.plugins.textContent = pluginsSummary;
      setStatus(
        statuses.plugins,
        pluginsOutput.code === 0 ? "pass" : "fail",
        pluginsOutput.code === 0 ? "Pass" : "Fail"
      );

      setStatus(statuses.paths, "running", "Running");
      const envDoctorOutput = await runSidecar(["env", "doctor", "--format", "json"]);
      let envDoctorPayload: EnvDoctorPayload | null = null;
      if (envDoctorOutput.stdout) {
        envDoctorPayload = JSON.parse(envDoctorOutput.stdout) as EnvDoctorPayload;
      }

      const pathRows: Array<[string, string]> = [];
      if (envDoctorPayload?.python?.executable) {
        pathRows.push(["sidecar executable", envDoctorPayload.python.executable]);
      }
      if (envDoctorPayload?.python?.version) {
        pathRows.push(["python version", envDoctorPayload.python.version]);
      }
      if (pluginsPayload?.plugins_dir) {
        pathRows.push(["bundled plugins", pluginsPayload.plugins_dir]);
      }
      const orderedPathKeys = [
        "data_root",
        "presets_dir",
        "ontology_dir",
        "schemas_dir",
        "cache_dir",
        "temp_dir",
        "temp_root_selection",
      ] as const;
      for (const key of orderedPathKeys) {
        const value = envDoctorPayload?.paths?.[key];
        if (value) {
          pathRows.push([key, value]);
        }
      }

      renderPathRows(
        outputs.paths,
        pathRows.length > 0 ? pathRows : [["paths", "No path data returned."]]
      );
      setStatus(
        statuses.paths,
        envDoctorOutput.code === 0 ? "pass" : "fail",
        envDoctorOutput.code === 0 ? "Pass" : "Fail"
      );

      const doctorFailed =
        versionOutput.code !== 0 ||
        pluginsOutput.code !== 0 ||
        envDoctorOutput.code !== 0;
      summary.textContent = doctorFailed
        ? "Doctor found a sidecar or bundle problem."
        : "Doctor passed. The packaged MMO sidecar executed successfully.";
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      summary.textContent = `Doctor failed before the sidecar completed: ${detail}`;
      outputs.version.textContent = detail;
      setStatus(statuses.version, "fail", "Fail");
      setStatus(statuses.plugins, "fail", "Blocked");
      setStatus(statuses.paths, "fail", "Blocked");
      renderPathRows(outputs.paths, [["error", detail]]);
    } finally {
      button.disabled = false;
    }
  });
});
