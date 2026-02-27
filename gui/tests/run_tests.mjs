import { run as runPluginFormsTests } from "./plugin_forms.test.mjs";
import { run as runMmoCliRunnerTests } from "./mmo_cli_runner.test.mjs";
import { run as runRpcClientTests } from "./rpc_process_client.test.mjs";
import { run as runAuditionLoudnessTests } from "./audition_loudness.test.mjs";
import { run as runHeadphonePreviewMeterTests } from "./headphone_preview_meter.test.mjs";
import { run as runServerAudioStreamTests } from "./server_audio_stream.test.mjs";

const suites = [
  { name: "audition_loudness", run: runAuditionLoudnessTests },
  { name: "headphone_preview_meter", run: runHeadphonePreviewMeterTests },
  { name: "mmo_cli_runner", run: runMmoCliRunnerTests },
  { name: "plugin_forms", run: runPluginFormsTests },
  { name: "rpc_process_client", run: runRpcClientTests },
  { name: "server_audio_stream", run: runServerAudioStreamTests },
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
