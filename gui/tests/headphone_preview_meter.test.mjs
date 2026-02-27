import assert from "node:assert/strict";

import {
  buildWaveformProfile,
  computeChannelRms,
  formatPeakDbfs,
  meterLevelFromDbfs,
  rmsToDbfs,
} from "../lib/headphone_preview_meter.mjs";

function _testComputeChannelRmsForKnownSignal() {
  const samples = new Float32Array([0.5, -0.5, 0.5, -0.5]);
  const rms = computeChannelRms(samples);
  assert.ok(Math.abs(rms - 0.5) < 1e-9);
}

function _testRmsToDbfsHandlesZeroAndPositive() {
  assert.equal(rmsToDbfs(0), Number.NEGATIVE_INFINITY);
  const db = rmsToDbfs(0.5);
  assert.ok(Math.abs(db - (-6.020599913279624)) < 1e-9);
}

function _testMeterLevelClamps() {
  assert.equal(meterLevelFromDbfs(Number.NEGATIVE_INFINITY), 0);
  assert.equal(meterLevelFromDbfs(-120), 0);
  assert.equal(meterLevelFromDbfs(2), 1);
  assert.ok(meterLevelFromDbfs(-18) > meterLevelFromDbfs(-36));
}

function _testWaveformProfileIsDeterministic() {
  const a = buildWaveformProfile({
    leftLevel: 0.73,
    rightLevel: 0.41,
    timeSeconds: 12.345,
    barCount: 28,
  });
  const b = buildWaveformProfile({
    leftLevel: 0.73,
    rightLevel: 0.41,
    timeSeconds: 12.345,
    barCount: 28,
  });
  assert.deepEqual(a, b);
  assert.equal(a.length, 28);
}

function _testWaveformProfileRespondsToLevelBias() {
  const profile = buildWaveformProfile({
    leftLevel: 0.85,
    rightLevel: 0.20,
    timeSeconds: 3.2,
    barCount: 28,
  });
  const midpoint = Math.floor(profile.length / 2);
  const leftMean = profile.slice(0, midpoint).reduce((acc, value) => acc + value, 0) / midpoint;
  const rightMean = profile.slice(midpoint).reduce((acc, value) => acc + value, 0) / (profile.length - midpoint);
  assert.ok(leftMean > rightMean);
}

function _testFormatPeakDbfs() {
  assert.equal(formatPeakDbfs(Number.NEGATIVE_INFINITY), "-inf dBFS");
  assert.equal(formatPeakDbfs(-7.41), "-7.4 dBFS");
}

export async function run() {
  _testComputeChannelRmsForKnownSignal();
  _testRmsToDbfsHandlesZeroAndPositive();
  _testMeterLevelClamps();
  _testWaveformProfileIsDeterministic();
  _testWaveformProfileRespondsToLevelBias();
  _testFormatPeakDbfs();
}
