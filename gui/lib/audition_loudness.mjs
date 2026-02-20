function _finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function _normalizeStreamKind(value) {
  return value === "input" || value === "output" ? value : "";
}

export function resolveAuditionLoudnessDb(pointer) {
  const meters = pointer && typeof pointer === "object" ? pointer.meters : null;
  if (meters && typeof meters === "object") {
    const integrated = _finiteNumber(meters.integrated_lufs);
    if (integrated !== null) {
      return integrated;
    }
    const rms = _finiteNumber(meters.rms_dbfs);
    if (rms !== null) {
      return rms;
    }
  }
  return null;
}

export function computeAuditionCompensation({
  rmsInputDbfs,
  rmsOutputDbfs,
  streamKind,
  allowBoost = false,
  maxBoostDb = 12,
} = {}) {
  const normalizedStream = _normalizeStreamKind(streamKind);
  const inputDb = _finiteNumber(rmsInputDbfs);
  const outputDb = _finiteNumber(rmsOutputDbfs);
  if (!normalizedStream || inputDb === null || outputDb === null) {
    return {
      gainDb: 0,
      metersAvailable: false,
      streamKind: normalizedStream,
    };
  }

  const deltaDb = outputDb - inputDb;
  let gainDb = normalizedStream === "input" ? deltaDb : -deltaDb;

  if (!allowBoost && gainDb > 0) {
    gainDb = 0;
  }
  if (allowBoost && Number.isFinite(maxBoostDb) && maxBoostDb >= 0 && gainDb > maxBoostDb) {
    gainDb = maxBoostDb;
  }
  if (Object.is(gainDb, -0)) {
    gainDb = 0;
  }

  return {
    deltaDb,
    gainDb,
    metersAvailable: true,
    streamKind: normalizedStream,
  };
}

export function formatAuditionCompensationReceipt(result, { enabled = true } = {}) {
  if (!enabled) {
    return "Loudness match: Off";
  }
  if (!result || result.metersAvailable !== true) {
    return "Loudness match: meters unavailable";
  }

  const streamLabel = result.streamKind === "input" ? "Input" : "Output";
  const gainDb = _finiteNumber(result.gainDb) || 0;
  if (gainDb < 0) {
    return `Matched by ${gainDb.toFixed(1)} dB (${streamLabel} trimmed).`;
  }
  if (gainDb > 0) {
    return `Matched by +${gainDb.toFixed(1)} dB (${streamLabel} boosted).`;
  }
  return "Matched by 0.0 dB (no trim needed).";
}
