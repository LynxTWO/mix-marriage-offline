import { run as runPluginFormsTests } from "./plugin_forms.test.mjs";
import { run as runMmoCliRunnerTests } from "./mmo_cli_runner.test.mjs";
import { run as runRpcClientTests } from "./rpc_process_client.test.mjs";

const suites = [
  { name: "mmo_cli_runner", run: runMmoCliRunnerTests },
  { name: "plugin_forms", run: runPluginFormsTests },
  { name: "rpc_process_client", run: runRpcClientTests },
];

let failures = 0;
for (const suite of suites) {
  try {
    await suite.run();
    // eslint-disable-next-line no-console
    console.log(`ok - ${suite.name}`);
  } catch (error) {
    failures += 1;
    // eslint-disable-next-line no-console
    console.error(`not ok - ${suite.name}`);
    // eslint-disable-next-line no-console
    console.error(error instanceof Error ? error.stack || error.message : String(error));
  }
}

if (failures > 0) {
  process.exit(1);
}
