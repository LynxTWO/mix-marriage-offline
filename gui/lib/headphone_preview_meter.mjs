function _finite(value, fallback = 0) {
  return (typeof value === "number" && Number.isFinite(value)) ? value : fallback;
}

function _clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

export function computeChannelRms(samples) {
  if (!(samples instanceof Float32Array) && !(samples instanceof Float64Array)) {
    return 0;
  }
  if (samples.length === 0) {
    return 0;
  }
  let sumSquares = 0;
  for (let index = 0; index < samples.length; index += 1) {
    // Treat non-finite decode artifacts as silence so preview math does not
    // spread NaNs through the meter.
    const sample = _finite(samples[index], 0);
    sumSquares += sample * sample;
  }
  return Math.sqrt(sumSquares / samples.length);
}

export function rmsToDbfs(rmsValue, { epsilon = 1e-12 } = {}) {
  const safeRms = _finite(rmsValue, 0);
  const floor = Math.max(1e-15, _finite(epsilon, 1e-12));
  // Keep a clear silence state instead of returning an arbitrary floor value.
  if (safeRms <= floor) {
    return Number.NEGATIVE_INFINITY;
  }
  return 20 * Math.log10(safeRms);
}

export function meterLevelFromDbfs(dbfs, { floorDb = -72 } = {}) {
  const floor = _finite(floorDb, -72);
  if (!Number.isFinite(dbfs)) {
    return 0;
  }
  // The preview meter uses one fixed floor so left and right levels remain
  // comparable across refreshes.
  return _clamp((dbfs - floor) / (0 - floor), 0, 1);
}

export function formatPeakDbfs(dbfs) {
  if (!Number.isFinite(dbfs)) {
    return "-inf dBFS";
  }
  return `${dbfs.toFixed(1)} dBFS`;
}

export function buildWaveformProfile({
  leftLevel,
  rightLevel,
  timeSeconds,
  barCount = 28,
} = {}) {
  const count = _clamp(Math.round(_finite(barCount, 28)), 1, 96);
  const left = _clamp(_finite(leftLevel, 0), 0, 1);
  const right = _clamp(_finite(rightLevel, 0), 0, 1);
  const t = _finite(timeSeconds, 0);
  const profile = [];
  // This waveform is a deterministic UI profile, not decoded audio. Splitting
  // the bar field by channel keeps stereo bias visible in the preview.
  for (let index = 0; index < count; index += 1) {
    const stereoLevel = index < Math.floor(count / 2) ? left : right;
    const pulse = 0.45 + (0.55 * Math.sin((t * 4.2) + (index * 0.63)));
    const ripple = 0.5 + (0.5 * Math.cos((t * 2.1) + (index * 0.31)));
    const baseline = 0.12 + (stereoLevel * 0.74);
    const height = _clamp((baseline * (0.56 + (0.44 * pulse))) + (0.08 * ripple), 0.08, 1);
    profile.push(height);
  }
  return profile;
}
