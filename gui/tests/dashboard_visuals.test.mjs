import assert from "node:assert/strict";

import {
  buildMeterHistogram,
  buildMeterRowsFromRenderQa,
  buildMeterRowsFromReport,
  buildMeterSummary,
  buildSceneDistribution,
  resolveAuditionQaComparison,
} from "../lib/dashboard_visuals.mjs";

function _sampleReport() {
  return {
    session: {
      stems: [
        {
          stem_id: "vox",
          label: "Lead Vox",
          file_path: "/tmp/vox.wav",
          channel_count: 1,
          metrics: {
            peak_dbfs: -3.1,
          },
          measurements: [
            { evidence_id: "EVID.METER.RMS_DBFS", value: -18.4 },
            { evidence_id: "EVID.METER.TRUEPEAK_DBTP", value: -2.4 },
            { evidence_id: "EVID.METER.LUFS_I", value: -16.8 },
            { evidence_id: "EVID.IMAGE.CORRELATION", value: 0.95 },
          ],
        },
        {
          stem_id: "pad",
          label: "Wide Pad",
          file_path: "/tmp/pad.wav",
          channel_count: 2,
          measurements: [
            { evidence_id: "EVID.METER.SAMPLE_PEAK_DBFS", value: -10.2 },
            { evidence_id: "EVID.METER.RMS_DBFS", value: -23.6 },
            { evidence_id: "EVID.METER.TRUEPEAK_DBTP", value: -9.4 },
            { evidence_id: "EVID.METER.LUFS_I", value: -21.1 },
            { evidence_id: "EVID.IMAGE.CORRELATION", value: 0.12 },
          ],
        },
      ],
    },
  };
}

function _sampleQa() {
  return {
    jobs: [
      {
        job_id: "JOB.002",
        input: {
          path: "/tmp/input.wav",
          spectral: {
            centers_hz: [100, 1000, 10000],
            levels_db: [-18, -6, -10],
          },
        },
        outputs: [
          {
            path: "/tmp/render_a.wav",
            channel_count: 2,
            metrics: {
              peak_dbfs: -1.5,
              rms_dbfs: -17.2,
              true_peak_dbtp: -1.0,
              integrated_lufs: -15.1,
              correlation_lr: 0.84,
              loudness_range_lu: 6.1,
            },
            spectral: {
              centers_hz: [100, 1000, 10000],
              levels_db: [-16, -5, -12],
            },
          },
        ],
        comparisons: [
          {
            input_path: "/tmp/input.wav",
            output_path: "/tmp/render_a.wav",
            metrics_delta: {
              true_peak_dbtp: 1.4,
            },
          },
        ],
      },
    ],
  };
}

function _samplePreview() {
  return {
    bed_energy: 0.4,
    beds: [{ bed_id: "BED.FIELD.001" }],
    layout_options: [
      {
        layout_id: "LAYOUT.5_1",
        speakers: [
          { name: "L", azimuth_deg: -30, elevation_deg: 0 },
          { name: "R", azimuth_deg: 30, elevation_deg: 0 },
          { name: "C", azimuth_deg: 0, elevation_deg: 0 },
          { name: "Ls", azimuth_deg: -110, elevation_deg: 0 },
          { name: "Rs", azimuth_deg: 110, elevation_deg: 0 },
          { name: "LFE", azimuth_deg: 0, elevation_deg: 0 },
        ],
      },
    ],
    objects: [
      { object_id: "OBJ.VOX", azimuth_deg: 0, confidence: 0.92, inferred_position: false },
      { object_id: "OBJ.FX", azimuth_deg: 120, confidence: 0.68, inferred_position: true },
    ],
  };
}

function _testReportRowsExtractAllPrimaryMeters() {
  const rows = buildMeterRowsFromReport(_sampleReport());
  assert.equal(rows.length, 2);
  assert.equal(rows[0].stem_id, "vox");
  assert.equal(rows[0].peak_dbfs, -3.1);
  assert.equal(rows[0].rms_dbfs, -18.4);
  assert.equal(rows[0].true_peak_dbtp, -2.4);
  assert.equal(rows[0].integrated_lufs, -16.8);
}

function _testMeterSummaryAndHistogramStayDeterministic() {
  const rows = buildMeterRowsFromReport(_sampleReport());
  const summary = buildMeterSummary(rows);
  assert.equal(summary.row_count, 2);
  assert.equal(summary.peak_max_dbfs, -3.1);
  assert.equal(summary.true_peak_max_dbtp, -2.4);
  assert.equal(summary.lufs_span, 4.300000000000001);

  const histogram = buildMeterHistogram(rows, "integrated_lufs", {
    bins: 4,
    min: -24,
    max: -12,
  });
  assert.equal(histogram.bins.length, 4);
  assert.deepEqual(
    histogram.bins.map((row) => row.count),
    [1, 0, 1, 0],
  );
}

function _testRenderQaRowsAndComparisonResolveByOutputPath() {
  const rows = buildMeterRowsFromRenderQa(_sampleQa());
  assert.equal(rows.length, 1);
  assert.equal(rows[0].job_id, "JOB.002");
  assert.equal(rows[0].label, "render_a.wav");
  assert.equal(rows[0].integrated_lufs, -15.1);

  const overlay = resolveAuditionQaComparison(_sampleQa(), "JOB.002", "/tmp/render_a.wav");
  assert.ok(overlay);
  assert.equal(overlay.output.path, "/tmp/render_a.wav");
  assert.equal(overlay.comparison.metrics_delta.true_peak_dbtp, 1.4);
}

function _testSceneDistributionMapsObjectsAndBed() {
  const rows = buildSceneDistribution(_samplePreview(), "LAYOUT.5_1");
  const byId = new Map(rows.map((row) => [row.id, row]));
  assert.equal(byId.get("front").count, 1);
  assert.equal(byId.get("surround").count, 1);
  assert.equal(byId.get("bed").count, 1);
  assert.ok(byId.get("bed").value > 0);
  assert.equal(byId.get("lfe").speaker_count, 1);
}

export async function run() {
  _testReportRowsExtractAllPrimaryMeters();
  _testMeterSummaryAndHistogramStayDeterministic();
  _testRenderQaRowsAndComparisonResolveByOutputPath();
  _testSceneDistributionMapsObjectsAndBed();
}
