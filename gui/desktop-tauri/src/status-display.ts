export type DeliverableResultBucket =
  | "diagnostics_only"
  | "full_failure"
  | "partial_success"
  | "success_no_master"
  | "unknown"
  | "valid_master";

export type RenderOutcomeTone = "danger" | "info" | "ok" | "warn";

export type SafeRenderLifecycleStatus = "blocked" | "completed" | "dry_run_only";
export type QaGateStatus = "fail" | "not_run" | "pass" | "warn";
export type MeasurementState =
  | "invalid_due_to_silence"
  | "measurement_failed"
  | "measured"
  | "not_applicable";

const DELIVERABLE_FAILURE_REASON_LABELS: Record<string, string> = {
  "RENDER_RESULT.DOWNMIX_QA_FAILED": "Downmix similarity QA failed",
  "RENDER_RESULT.FALLBACK_APPLIED": "Fallback processing was required",
  "RENDER_RESULT.MISSING_CHANNEL_ORDER": "Missing channel order metadata",
  "RENDER_RESULT.NO_DECODABLE_STEMS": "No decodable stems",
  "RENDER_RESULT.NO_OUTPUT_ARTIFACT": "No output artifacts were written",
  "RENDER_RESULT.PLACEMENT_POLICY_UNAVAILABLE": "Placement policy unavailable",
  "RENDER_RESULT.SAFETY_COLLAPSE_APPLIED": "Safety collapse was applied",
  "RENDER_RESULT.SILENT_OUTPUT": "Rendered output is effectively silent",
  "RENDER_RESULT.STEM_DECODE_FAILED": "Stem decode failed",
  "RENDER_RESULT.STEMS_SKIPPED": "Some stems were skipped",
};

export const DELIVERABLE_RESULT_BUCKET_LABELS: Record<DeliverableResultBucket, string> = {
  diagnostics_only: "Invalid render with diagnostics",
  full_failure: "Full failure",
  partial_success: "Partial success",
  success_no_master: "Successful artifacts (no master)",
  unknown: "Unknown render result",
  valid_master: "Valid master render",
};

export const DELIVERABLE_RESULT_BUCKET_TONES: Record<DeliverableResultBucket, RenderOutcomeTone> = {
  diagnostics_only: "danger",
  full_failure: "danger",
  partial_success: "warn",
  success_no_master: "info",
  unknown: "info",
  valid_master: "ok",
};

export const SAFE_RENDER_LIFECYCLE_LABELS: Record<SafeRenderLifecycleStatus, string> = {
  blocked: "Blocked",
  completed: "Completed",
  dry_run_only: "Dry-run only",
};

export const QA_GATE_STATUS_LABELS: Record<QaGateStatus, string> = {
  fail: "Fail",
  not_run: "Not run",
  pass: "Pass",
  warn: "Warn",
};

export const MEASUREMENT_STATE_LABELS: Record<MeasurementState, string> = {
  invalid_due_to_silence: "Invalid due to silence",
  measurement_failed: "Measurement failed",
  measured: "Measured",
  not_applicable: "Not applicable",
};

export function renderOutcomeLabel(bucket: DeliverableResultBucket): string {
  return DELIVERABLE_RESULT_BUCKET_LABELS[bucket];
}

export function renderOutcomeTone(bucket: DeliverableResultBucket): RenderOutcomeTone {
  return DELIVERABLE_RESULT_BUCKET_TONES[bucket];
}

export function humanizeFailureReason(reason: string): string {
  const normalized = reason.trim();
  if (!normalized) {
    return "Unknown failure";
  }
  const mapped = DELIVERABLE_FAILURE_REASON_LABELS[normalized];
  if (mapped) {
    return mapped;
  }
  const segments = normalized.split(".");
  const suffix = normalized.includes(".")
    ? (segments[segments.length - 1] || normalized)
    : normalized;
  return suffix
    .toLowerCase()
    .split("_")
    .filter(Boolean)
    .map((token) => token[0].toUpperCase() + token.slice(1))
    .join(" ");
}
