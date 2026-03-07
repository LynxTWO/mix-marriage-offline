import assert from "node:assert/strict";

import {
  buildSpectrumProfile,
  buildWaveformEnvelope,
  mixChannelsToMono,
  normalizeSpectralProfile,
} from "../lib/audition_overlays.mjs";

function _sineWave(frames, frequencyHz, sampleRate) {
  const samples = new Float32Array(frames);
  for (let index = 0; index < frames; index += 1) {
    samples[index] = Math.sin((2 * Math.PI * frequencyHz * index) / sampleRate);
  }
  return samples;
}

function _testMixChannelsToMonoAveragesInputs() {
  const mono = mixChannelsToMono(
    [
      new Float32Array([1, 0, -1, 0]),
      new Float32Array([0, 1, 0, -1]),
    ],
    4,
  );
  assert.deepEqual(Array.from(mono), [0.5, 0.5, -0.5, -0.5]);
}

function _testWaveformEnvelopeCapturesWindowPeaks() {
  const envelope = buildWaveformEnvelope(new Float32Array([0, 0.25, -0.8, 0.3, 0.1, -0.6]), {
    pointCount: 3,
  });
  assert.deepEqual(
    envelope.map((value) => Number(value.toFixed(2))),
    [0.25, 0.8, 0.6],
  );
}

function _testSpectrumProfileFindsToneNearExpectedBand() {
  const sampleRate = 48_000;
  const profile = buildSpectrumProfile(
    _sineWave(4_096, 440, sampleRate),
    sampleRate,
    { bandCount: 24, minHz: 40, maxHz: 4_000 },
  );
  assert.equal(profile.centersHz.length, 24);
  const peakIndex = profile.levelsDb.reduce(
    (bestIndex, level, index, levels) => (level > levels[bestIndex] ? index : bestIndex),
    0,
  );
  assert.ok(profile.centersHz[peakIndex] > 250);
  assert.ok(profile.centersHz[peakIndex] < 700);
}

function _testNormalizeSpectralProfileDropsNulls() {
  const normalized = normalizeSpectralProfile({
    centers_hz: [100, 1000, 10_000],
    levels_db: [-12, null, -24],
  });
  assert.deepEqual(normalized.centersHz, [100, 10_000]);
  assert.deepEqual(normalized.levelsDb, [-12, -24]);
}

export async function run() {
  _testMixChannelsToMonoAveragesInputs();
  _testWaveformEnvelopeCapturesWindowPeaks();
  _testSpectrumProfileFindsToneNearExpectedBand();
  _testNormalizeSpectralProfileDropsNulls();
}
