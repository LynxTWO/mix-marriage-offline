function _clamp(value, minimum, maximum) {
  return Math.max(minimum, Math.min(maximum, value));
}

function _isArrayLikeFloat32(value) {
  return value instanceof Float32Array || value instanceof Float64Array;
}

export function mixChannelsToMono(channels, maxFrames = 262_144) {
  const channelData = Array.isArray(channels)
    ? channels.filter((channel) => _isArrayLikeFloat32(channel))
    : [];
  if (channelData.length === 0) {
    return new Float32Array();
  }
  const frameCount = channelData.reduce(
    (minimum, channel) => Math.min(minimum, channel.length),
    channelData[0].length,
  );
  // Preview overlays only use the shared decoded prefix. Truncating to the
  // shortest channel avoids reading past partial decode results.
  const limitedFrames = Math.max(0, Math.min(frameCount, maxFrames));
  const mono = new Float32Array(limitedFrames);
  for (let frameIndex = 0; frameIndex < limitedFrames; frameIndex += 1) {
    let total = 0;
    for (const channel of channelData) {
      total += channel[frameIndex];
    }
    mono[frameIndex] = total / channelData.length;
  }
  return mono;
}

export function buildWaveformEnvelope(samples, { pointCount = 96 } = {}) {
  if (!_isArrayLikeFloat32(samples) || samples.length === 0) {
    return [];
  }
  // The overlay keeps one peak per window. That favors readable evidence over
  // raw sample detail and keeps the browser payload small.
  const count = Math.max(2, Math.min(256, Number.parseInt(String(pointCount), 10) || 96));
  const envelope = new Array(count).fill(0);
  const stride = samples.length / count;
  for (let index = 0; index < count; index += 1) {
    const start = Math.floor(index * stride);
    const end = Math.min(samples.length, Math.ceil((index + 1) * stride));
    let peak = 0;
    for (let frameIndex = start; frameIndex < end; frameIndex += 1) {
      peak = Math.max(peak, Math.abs(samples[frameIndex]));
    }
    envelope[index] = _clamp(peak, 0, 1);
  }
  return envelope;
}

function _goertzelMagnitude(samples, sampleRate, targetHz) {
  if (!_isArrayLikeFloat32(samples) || samples.length === 0 || sampleRate <= 0 || targetHz <= 0) {
    return 0;
  }
  const omega = (2 * Math.PI * targetHz) / sampleRate;
  const coefficient = 2 * Math.cos(omega);
  let q0 = 0;
  let q1 = 0;
  let q2 = 0;
  for (let index = 0; index < samples.length; index += 1) {
    q0 = coefficient * q1 - q2 + samples[index];
    q2 = q1;
    q1 = q0;
  }
  const real = q1 - (q2 * Math.cos(omega));
  const imag = q2 * Math.sin(omega);
  return Math.sqrt((real * real) + (imag * imag));
}

function _logSpacedCenters(minHz, maxHz, count) {
  const centers = [];
  const safeMin = Math.max(1, minHz);
  const safeMax = Math.max(safeMin * 1.01, maxHz);
  for (let index = 0; index < count; index += 1) {
    const ratio = index / Math.max(1, count - 1);
    centers.push(safeMin * ((safeMax / safeMin) ** ratio));
  }
  return centers;
}

export function buildSpectrumProfile(
  samples,
  sampleRate,
  {
    bandCount = 40,
    maxHz = 20_000,
    minHz = 20,
    sampleFrames = 4_096,
  } = {},
) {
  if (!_isArrayLikeFloat32(samples) || samples.length === 0 || !Number.isFinite(sampleRate) || sampleRate <= 0) {
    return { centersHz: [], levelsDb: [] };
  }
  // Overlay spectra use a bounded slice, not full-file analysis. The browser
  // only needs a cheap shape preview here.
  const availableFrames = Math.max(128, Math.min(samples.length, sampleFrames));
  const mono = samples.subarray(0, availableFrames);
  const windowed = new Float32Array(mono.length);
  for (let index = 0; index < mono.length; index += 1) {
    const window = 0.5 - (0.5 * Math.cos((2 * Math.PI * index) / Math.max(1, mono.length - 1)));
    windowed[index] = mono[index] * window;
  }
  const nyquist = sampleRate * 0.5;
  const centersHz = _logSpacedCenters(
    Math.max(10, minHz),
    Math.min(maxHz, nyquist),
    Math.max(12, Math.min(96, bandCount)),
  );
  const magnitudes = centersHz.map((centerHz) => _goertzelMagnitude(windowed, sampleRate, centerHz));
  // Normalize against the loudest sampled band so the overlay compares shape
  // within one preview instead of mixing in export level.
  const maxMagnitude = Math.max(...magnitudes, 1e-9);
  const levelsDb = magnitudes.map((magnitude) => {
    const normalized = magnitude / maxMagnitude;
    return 20 * Math.log10(Math.max(normalized, 1e-9));
  });
  return { centersHz, levelsDb };
}

export function normalizeSpectralProfile(spectral) {
  const rawCenters = Array.isArray(spectral?.centers_hz)
    ? spectral.centers_hz
    : Array.isArray(spectral?.centersHz)
      ? spectral.centersHz
      : [];
  const rawLevels = Array.isArray(spectral?.levels_db)
    ? spectral.levels_db
    : Array.isArray(spectral?.levelsDb)
      ? spectral.levelsDb
      : [];
  const centersHz = [];
  const levelsDb = [];
  // Drop malformed pairs instead of filling gaps. Less evidence is safer than
  // invented overlay data.
  for (let index = 0; index < Math.min(rawCenters.length, rawLevels.length); index += 1) {
    const centerHz = rawCenters[index];
    const levelDb = rawLevels[index];
    if (!Number.isFinite(centerHz) || !Number.isFinite(levelDb)) {
      continue;
    }
    centersHz.push(Number(centerHz));
    levelsDb.push(Number(levelDb));
  }
  return { centersHz, levelsDb };
}
