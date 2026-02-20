import assert from "node:assert/strict";

import {
  computeAuditionCompensation,
  formatAuditionCompensationReceipt,
  resolveAuditionLoudnessDb,
} from "../lib/audition_loudness.mjs";

function _testLouderInputGetsTrimmedForInputPlayback() {
  const result = computeAuditionCompensation({
    rmsInputDbfs: -12,
    rmsOutputDbfs: -15,
    streamKind: "input",
  });
  assert.equal(result.metersAvailable, true);
  assert.equal(result.gainDb, -3);
  assert.equal(
    formatAuditionCompensationReceipt(result),
    "Matched by -3.0 dB (Input trimmed).",
  );
}

function _testLouderOutputGetsTrimmedForOutputPlayback() {
  const result = computeAuditionCompensation({
    rmsInputDbfs: -18,
    rmsOutputDbfs: -14,
    streamKind: "output",
  });
  assert.equal(result.metersAvailable, true);
  assert.equal(result.gainDb, -4);
  assert.equal(
    formatAuditionCompensationReceipt(result),
    "Matched by -4.0 dB (Output trimmed).",
  );
}

function _testNeverBoostsWhenBoostNotAllowed() {
  const result = computeAuditionCompensation({
    rmsInputDbfs: -20,
    rmsOutputDbfs: -14,
    streamKind: "input",
    allowBoost: false,
  });
  assert.equal(result.gainDb, 0);
}

function _testBoostsOnlyWhenExplicitlyAllowed() {
  const result = computeAuditionCompensation({
    rmsInputDbfs: -20,
    rmsOutputDbfs: -14,
    streamKind: "input",
    allowBoost: true,
  });
  assert.equal(result.gainDb, 6);
}

function _testMetersUnavailableFallsBackGracefully() {
  const result = computeAuditionCompensation({
    rmsInputDbfs: null,
    rmsOutputDbfs: -14,
    streamKind: "output",
  });
  assert.equal(result.metersAvailable, false);
  assert.equal(result.gainDb, 0);
  assert.equal(
    formatAuditionCompensationReceipt(result),
    "Loudness match: meters unavailable",
  );
}

function _testLoudnessResolverPrefersIntegratedLufs() {
  assert.equal(
    resolveAuditionLoudnessDb({
      meters: {
        integrated_lufs: -14.5,
        rms_dbfs: -13.2,
      },
    }),
    -14.5,
  );
  assert.equal(
    resolveAuditionLoudnessDb({
      meters: {
        integrated_lufs: null,
        rms_dbfs: -11.0,
      },
    }),
    -11,
  );
}

export async function run() {
  _testLouderInputGetsTrimmedForInputPlayback();
  _testLouderOutputGetsTrimmedForOutputPlayback();
  _testNeverBoostsWhenBoostNotAllowed();
  _testBoostsOnlyWhenExplicitlyAllowed();
  _testMetersUnavailableFallsBackGracefully();
  _testLoudnessResolverPrefersIntegratedLufs();
}
