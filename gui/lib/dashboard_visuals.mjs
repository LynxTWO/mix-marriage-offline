function _isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function _coerceNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function _nonEmptyString(value) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function _pathTail(pathValue) {
  const normalized = _nonEmptyString(pathValue).replace(/\\/g, "/");
  if (!normalized) {
    return "";
  }
  const parts = normalized.split("/").filter((part) => part);
  return parts[parts.length - 1] || normalized;
}

function _measurementValue(measurements, evidenceIds = []) {
  const ids = new Set(
    Array.isArray(evidenceIds)
      ? evidenceIds.filter((item) => typeof item === "string" && item.trim())
      : [],
  );
  if (ids.size === 0 || !Array.isArray(measurements)) {
    return null;
  }
  for (const measurement of measurements) {
    if (!_isObject(measurement)) {
      continue;
    }
    const evidenceId = _nonEmptyString(measurement.evidence_id);
    if (!ids.has(evidenceId)) {
      continue;
    }
    const value = _coerceNumber(measurement.value);
    if (value !== null) {
      return value;
    }
  }
  return null;
}

function _median(values) {
  if (!Array.isArray(values) || values.length === 0) {
    return null;
  }
  const sorted = values
    .filter((value) => typeof value === "number" && Number.isFinite(value))
    .sort((left, right) => left - right);
  if (sorted.length === 0) {
    return null;
  }
  const midpoint = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) {
    return sorted[midpoint];
  }
  return (sorted[midpoint - 1] + sorted[midpoint]) / 2;
}

function _speakerFamilyForSpeaker(speaker) {
  const azimuth = _coerceNumber(speaker?.azimuth_deg) ?? 0;
  const elevation = _coerceNumber(speaker?.elevation_deg) ?? 0;
  const name = _nonEmptyString(speaker?.name).toUpperCase();
  if (name.includes("LFE")) {
    return "lfe";
  }
  if (elevation > 0.1) {
    return "height";
  }
  const absAzimuth = Math.abs(azimuth);
  if (absAzimuth >= 135) {
    return "rear";
  }
  if (absAzimuth >= 55) {
    return "surround";
  }
  return "front";
}

function _angleDistanceDegrees(left, right) {
  const delta = Math.abs(left - right) % 360;
  return delta > 180 ? 360 - delta : delta;
}

function _distributionTemplate() {
  return [
    { id: "front", label: "Front", value: 0, count: 0, speaker_count: 0 },
    { id: "surround", label: "Surround", value: 0, count: 0, speaker_count: 0 },
    { id: "rear", label: "Rear", value: 0, count: 0, speaker_count: 0 },
    { id: "height", label: "Height", value: 0, count: 0, speaker_count: 0 },
    { id: "lfe", label: "LFE", value: 0, count: 0, speaker_count: 0 },
    { id: "bed", label: "Bed", value: 0, count: 0, speaker_count: 0 },
  ];
}

export function buildMeterRowsFromReport(report) {
  const stems = Array.isArray(report?.session?.stems) ? report.session.stems : [];
  const rows = [];
  for (const stem of stems) {
    if (!_isObject(stem)) {
      continue;
    }
    const stemId = _nonEmptyString(stem.stem_id);
    if (!stemId) {
      continue;
    }
    const measurements = Array.isArray(stem.measurements) ? stem.measurements : [];
    const metrics = _isObject(stem.metrics) ? stem.metrics : {};
    const peakDbfs = (
      _measurementValue(measurements, ["EVID.METER.PEAK_DBFS", "EVID.METER.SAMPLE_PEAK_DBFS"])
      ?? _coerceNumber(metrics.peak_dbfs)
    );
    const rmsDbfs = _measurementValue(measurements, ["EVID.METER.RMS_DBFS"]);
    const truePeak = _measurementValue(measurements, ["EVID.METER.TRUEPEAK_DBTP"]);
    const integratedLufs = _measurementValue(measurements, ["EVID.METER.LUFS_I"]);
    const correlation = _measurementValue(measurements, ["EVID.IMAGE.CORRELATION"]);
    const row = {
      channel_count: Number.isInteger(stem.channel_count) ? stem.channel_count : null,
      correlation,
      integrated_lufs: integratedLufs,
      label: _nonEmptyString(stem.label) || _pathTail(stem.file_path) || stemId,
      layout_id: _nonEmptyString(stem.layout_id) || null,
      output_path: _nonEmptyString(stem.file_path) || null,
      peak_dbfs: peakDbfs,
      rms_dbfs: rmsDbfs,
      scope: "stem",
      source: "report",
      stem_id: stemId,
      true_peak_dbtp: truePeak,
    };
    if (
      row.peak_dbfs === null
      && row.rms_dbfs === null
      && row.true_peak_dbtp === null
      && row.integrated_lufs === null
      && row.correlation === null
    ) {
      continue;
    }
    rows.push(row);
  }
  rows.sort((left, right) => {
    const leftPeak = left.peak_dbfs ?? Number.NEGATIVE_INFINITY;
    const rightPeak = right.peak_dbfs ?? Number.NEGATIVE_INFINITY;
    if (leftPeak !== rightPeak) {
      return rightPeak - leftPeak;
    }
    return left.label.localeCompare(right.label);
  });
  return rows;
}

export function buildMeterRowsFromRenderQa(qaPayload) {
  const jobs = Array.isArray(qaPayload?.jobs) ? qaPayload.jobs : [];
  const rows = [];
  for (const job of jobs) {
    if (!_isObject(job)) {
      continue;
    }
    const jobId = _nonEmptyString(job.job_id);
    const outputs = Array.isArray(job.outputs) ? job.outputs : [];
    outputs.forEach((output, index) => {
      if (!_isObject(output)) {
        return;
      }
      const metrics = _isObject(output.metrics) ? output.metrics : {};
      const pathValue = _nonEmptyString(output.path);
      rows.push(
        {
          channel_count: Number.isInteger(output.channel_count) ? output.channel_count : null,
          correlation: _coerceNumber(metrics.correlation_lr),
          integrated_lufs: _coerceNumber(metrics.integrated_lufs),
          job_id: jobId || null,
          label: _pathTail(pathValue) || `Output ${index + 1}`,
          loudness_range_lu: _coerceNumber(metrics.loudness_range_lu),
          output_path: pathValue || null,
          peak_dbfs: _coerceNumber(metrics.peak_dbfs),
          rms_dbfs: _coerceNumber(metrics.rms_dbfs),
          scope: "render_output",
          source: "render_qa",
          true_peak_dbtp: _coerceNumber(metrics.true_peak_dbtp),
        },
      );
    });
  }
  rows.sort((left, right) => {
    const leftJob = _nonEmptyString(left.job_id);
    const rightJob = _nonEmptyString(right.job_id);
    if (leftJob !== rightJob) {
      return leftJob.localeCompare(rightJob);
    }
    return _nonEmptyString(left.output_path).localeCompare(_nonEmptyString(right.output_path));
  });
  return rows;
}

export function buildMeterSummary(rows) {
  const validRows = Array.isArray(rows) ? rows : [];
  const peaks = validRows.map((row) => _coerceNumber(row.peak_dbfs)).filter((value) => value !== null);
  const rmsValues = validRows.map((row) => _coerceNumber(row.rms_dbfs)).filter((value) => value !== null);
  const truePeaks = validRows.map((row) => _coerceNumber(row.true_peak_dbtp)).filter((value) => value !== null);
  const lufsValues = validRows.map((row) => _coerceNumber(row.integrated_lufs)).filter((value) => value !== null);
  const correlationValues = validRows.map((row) => _coerceNumber(row.correlation)).filter((value) => value !== null);
  const lufsMin = lufsValues.length > 0 ? Math.min(...lufsValues) : null;
  const lufsMax = lufsValues.length > 0 ? Math.max(...lufsValues) : null;
  return {
    correlation_min: correlationValues.length > 0 ? Math.min(...correlationValues) : null,
    lufs_max: lufsMax,
    lufs_min: lufsMin,
    lufs_span: lufsMin !== null && lufsMax !== null ? lufsMax - lufsMin : null,
    peak_max_dbfs: peaks.length > 0 ? Math.max(...peaks) : null,
    rms_median_dbfs: _median(rmsValues),
    row_count: validRows.length,
    true_peak_max_dbtp: truePeaks.length > 0 ? Math.max(...truePeaks) : null,
  };
}

export function buildMeterHistogram(
  rows,
  metricName = "integrated_lufs",
  {
    bins = 10,
    max = null,
    min = null,
  } = {},
) {
  const values = (Array.isArray(rows) ? rows : [])
    .map((row) => _coerceNumber(row?.[metricName]))
    .filter((value) => value !== null);
  if (values.length === 0) {
    return {
      bins: [],
      max: null,
      metric_name: metricName,
      min: null,
    };
  }
  const resolvedMin = min !== null && Number.isFinite(min)
    ? Number(min)
    : Math.floor(Math.min(...values) - 1);
  const resolvedMax = max !== null && Number.isFinite(max)
    ? Number(max)
    : Math.ceil(Math.max(...values) + 1);
  const binCount = Math.max(4, Math.min(24, Number.parseInt(String(bins), 10) || 10));
  const span = Math.max(1e-6, resolvedMax - resolvedMin);
  const histogram = Array.from({ length: binCount }, (_, index) => {
    const start = resolvedMin + ((span * index) / binCount);
    const end = resolvedMin + ((span * (index + 1)) / binCount);
    return {
      count: 0,
      end,
      index,
      start,
    };
  });
  for (const value of values) {
    const normalized = (value - resolvedMin) / span;
    const index = Math.max(0, Math.min(binCount - 1, Math.floor(normalized * binCount)));
    histogram[index].count += 1;
  }
  return {
    bins: histogram,
    max: resolvedMax,
    metric_name: metricName,
    min: resolvedMin,
  };
}

export function buildSceneDistribution(preview, layoutId) {
  const layoutOptions = Array.isArray(preview?.layout_options) ? preview.layout_options : [];
  const selectedLayout = layoutOptions.find(
    (row) => _isObject(row) && _nonEmptyString(row.layout_id) === _nonEmptyString(layoutId),
  );
  if (!_isObject(selectedLayout)) {
    return [];
  }
  const speakers = Array.isArray(selectedLayout.speakers)
    ? selectedLayout.speakers.filter((speaker) => _isObject(speaker))
    : [];
  const distribution = _distributionTemplate();
  const byId = new Map(distribution.map((row) => [row.id, row]));

  for (const speaker of speakers) {
    const family = _speakerFamilyForSpeaker(speaker);
    const row = byId.get(family);
    if (row) {
      row.speaker_count += 1;
    }
  }

  const objects = Array.isArray(preview?.objects) ? preview.objects : [];
  for (const objectRow of objects) {
    if (!_isObject(objectRow)) {
      continue;
    }
    const confidence = Math.max(0, Math.min(1, _coerceNumber(objectRow.confidence) ?? 0));
    const azimuth = _coerceNumber(objectRow.azimuth_deg) ?? 0;
    let selectedSpeaker = null;
    let selectedDistance = Number.POSITIVE_INFINITY;
    for (const speaker of speakers) {
      const speakerAzimuth = _coerceNumber(speaker.azimuth_deg) ?? 0;
      const distance = _angleDistanceDegrees(azimuth, speakerAzimuth);
      if (distance < selectedDistance) {
        selectedDistance = distance;
        selectedSpeaker = speaker;
      }
    }
    const family = selectedSpeaker ? _speakerFamilyForSpeaker(selectedSpeaker) : "front";
    const row = byId.get(family);
    if (!row) {
      continue;
    }
    let weight = 0.25 + (confidence * 0.75);
    if (objectRow.inferred_position === true) {
      weight *= 0.85;
    }
    row.value += weight;
    row.count += 1;
  }

  const bedEnergy = Math.max(0, Math.min(1, _coerceNumber(preview?.bed_energy) ?? 0));
  const bedCount = Array.isArray(preview?.beds) ? preview.beds.length : 0;
  const bedRow = byId.get("bed");
  if (bedRow && (bedEnergy > 0 || bedCount > 0)) {
    bedRow.value = bedEnergy * Math.max(1, bedCount);
    bedRow.count = bedCount;
  }

  return distribution.filter(
    (row) => row.value > 0 || row.count > 0 || row.speaker_count > 0,
  );
}

export function resolveAuditionQaComparison(qaPayload, jobId, outputPath = "") {
  const jobs = Array.isArray(qaPayload?.jobs) ? qaPayload.jobs : [];
  const normalizedJobId = _nonEmptyString(jobId);
  const normalizedOutputPath = _nonEmptyString(outputPath);
  const job = jobs.find(
    (row) => _isObject(row) && _nonEmptyString(row.job_id) === normalizedJobId,
  );
  if (!_isObject(job)) {
    return null;
  }
  const outputs = Array.isArray(job.outputs) ? job.outputs.filter((row) => _isObject(row)) : [];
  const comparisons = Array.isArray(job.comparisons)
    ? job.comparisons.filter((row) => _isObject(row))
    : [];
  const output = normalizedOutputPath
    ? outputs.find((row) => _nonEmptyString(row.path) === normalizedOutputPath) || outputs[0] || null
    : outputs[0] || null;
  const comparison = normalizedOutputPath
    ? comparisons.find((row) => _nonEmptyString(row.output_path) === normalizedOutputPath)
      || comparisons[0]
      || null
    : comparisons[0] || null;
  return {
    comparison,
    input: _isObject(job.input) ? job.input : null,
    job,
    output,
  };
}
